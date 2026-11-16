"""Interview endpoints: configuration, lifecycle, documents, voice, reports."""

import hashlib
from typing import Awaitable, Callable, Optional, TypeVar

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.core.ai_deps import get_ai_client
from app.core.deps import get_current_user, user_rate_limit
from app.core.logging import get_logger
from app.database import get_database
from app.models.interview import interview_doc_to_out, new_interview_document
from app.schemas.interview import (
    AnswerRequest,
    AnswerResponse,
    AudioAnswerResponse,
    ExitInterviewResponse,
    InterviewCreate,
    InterviewOut,
    InterviewTurnOut,
    JobDescriptionUploadResponse,
    ResumeUploadResponse,
    StartInterviewResponse,
)
from app.schemas.report import InterviewReport
from app.schemas.webcam import WebcamMetrics
from app.services import idempotency, prompts, speech_analytics
from app.services.ai_client import AIClient, AIServiceError
from app.services.audio_cache import question_audio_cache
from app.services.documents import DocumentParseError, extract_text
from app.services.evaluation import generate_report
from app.services.interview_engine import (
    InterviewConflictError,
    InterviewStateError,
    abandon_interview,
    set_candidate_profile,
    set_job_profile,
    start_interview,
    submit_answer,
)
from app.services.interview_profiles import get_visible_profile
from app.services.processing import (
    ProcessingBusyError,
    ProcessingTimeoutError,
    run_bounded,
)

router = APIRouter(prefix="/interviews", tags=["interviews"])
settings = get_settings()
logger = get_logger(__name__)

ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/webm",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/x-m4a",
}

# pydub/ffmpeg format strings for each allowed content type — lets
# compute_speech_metrics skip format auto-detection and decode directly.
_AUDIO_FORMAT_HINTS: dict[str, str] = {
    "audio/webm": "webm",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
    "audio/x-m4a": "m4a",
}



def _base_content_type(content_type: str | None) -> str:
    """``audio/webm;codecs=opus`` -> ``audio/webm``.

    Browsers' MediaRecorder labels recordings with codec parameters, so an exact
    string match against the allow-list rejected the most common real uploads.
    """
    return (content_type or "").split(";", 1)[0].strip().lower()


# Read uploads in bounded chunks so a hostile Content-Length can't force the
# process to buffer an arbitrary amount of memory.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


def _object_id_or_404(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")


async def _get_owned_interview_or_404(
    db: AsyncIOMotorDatabase, interview_id: str, user: dict
) -> dict:
    """Fetch an interview, scoped to its owner. Any id that isn't the caller's
    own interview is a 404 — never a 403 — so ids can't be probed for
    existence."""
    object_id = _object_id_or_404(interview_id)
    doc = await db.interviews.find_one({"_id": object_id, "userId": str(user["_id"])})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    return doc


async def _read_upload_limited(file: UploadFile, *, max_bytes: int, what: str) -> bytes:
    """Read an upload, refusing anything over ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"That {what} is too large — keep it under {max_bytes // (1024 * 1024)}MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _processing_http_error(exc: Exception, *, what: str) -> HTTPException:
    if isinstance(exc, ProcessingBusyError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The server is busy processing other {what}s. Please try again in a moment.",
            headers={"Retry-After": "5"},
        )
    return HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail=f"Processing that {what} took too long. Try a smaller or simpler file.",
    )


def _ai_http_error(exc: AIServiceError, *, context: str) -> HTTPException:
    """Log the provider detail, return the candidate-safe message."""
    logger.warning("%s failed (%s): %s", context, exc.kind, exc)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.user_message)


def _state_http_error(exc: InterviewStateError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, InterviewConflictError)
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=str(exc))


_ResponseT = TypeVar("_ResponseT")

_IN_FLIGHT_DETAIL = "This answer is already being processed. Give it a moment."


def _parse_idempotency_key(raw: str | None) -> str | None:
    try:
        return idempotency.validate_key(raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


async def _run_idempotent(
    db: AsyncIOMotorDatabase,
    *,
    user: dict,
    scope: str,
    key: str | None,
    request_fingerprint: str,
    response_model: type[_ResponseT],
    work: Callable[[], Awaitable[_ResponseT]],
) -> _ResponseT:
    """Run ``work`` at most once per (user, scope, key); replay its result after.

    Without a key this is just ``work()``, so clients that don't send one behave
    exactly as before. See ``services/idempotency.py`` for the guarantees.
    """
    if key is None:
        return await work()

    try:
        handle, stored = await idempotency.begin(
            db,
            user_id=str(user["_id"]),
            scope=scope,
            key=key,
            request_fingerprint=request_fingerprint,
        )
    except idempotency.IdempotencyInFlightError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_IN_FLIGHT_DETAIL)
    except idempotency.IdempotencyMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    if stored is not None:
        return response_model.model_validate(stored)  # type: ignore[attr-defined]

    assert handle is not None
    try:
        result = await work()
    except BaseException:
        # Includes cancellation: a failed attempt must leave the key retryable.
        await idempotency.release_shielded(db, handle)
        raise

    try:
        await idempotency.complete(db, handle, result.model_dump(mode="json"))  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - the answer is already recorded; don't fail it
        logger.error("Could not store idempotent result: %s", exc)
    return result


# ---------------------------------------------------------------- configuration


@router.post("", response_model=InterviewOut, status_code=status.HTTP_201_CREATED)
async def create_interview(
    payload: InterviewCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InterviewOut:
    user_id = str(current_user["_id"])

    if payload.profileId:
        profile_doc = await get_visible_profile(db, payload.profileId, user_id)
        if not profile_doc or not profile_doc.get("isActive", True):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Interview profile not found"
            )
        if not payload.category:
            # category stays populated on the interview document itself (used by
            # report weighting and shown in interview history) even though the
            # profile — not this string — drives question generation.
            payload = payload.model_copy(update={"category": profile_doc["category"]})

    doc = new_interview_document(user_id=user_id, payload=payload)
    result = await db.interviews.insert_one(doc)
    doc["_id"] = result.inserted_id
    return interview_doc_to_out(doc)


@router.get("", response_model=list[InterviewOut])
async def list_interviews(
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum interviews to return."),
    offset: int = Query(default=0, ge=0, description="Number of interviews to skip."),
) -> list[InterviewOut]:
    """A candidate's own interviews, newest first.

    Bounded on purpose: without a limit, a long-running account would eventually
    pull its entire history (and every embedded resume/JD extraction) into one
    response.
    """
    cursor = (
        db.interviews.find({"userId": str(current_user["_id"])})
        .sort("createdAt", -1)
        .skip(offset)
        .limit(limit)
    )
    return [interview_doc_to_out(doc) async for doc in cursor]


@router.get("/{interview_id}", response_model=InterviewOut)
async def get_interview(
    interview_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InterviewOut:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    return interview_doc_to_out(doc)


@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview(
    interview_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> None:
    object_id = _object_id_or_404(interview_id)
    result = await db.interviews.delete_one({"_id": object_id, "userId": str(current_user["_id"])})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    await db.interview_turns.delete_many({"interviewId": interview_id})


# --------------------------------------------------------------------- lifecycle


@router.post("/{interview_id}/start", response_model=StartInterviewResponse)
async def start_interview_endpoint(
    interview_id: str,
    current_user: dict = Depends(user_rate_limit("expensive")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    ai_client: AIClient = Depends(get_ai_client),
) -> StartInterviewResponse:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    try:
        return await start_interview(db, ai_client, doc)
    except InterviewStateError as exc:
        raise _state_http_error(exc)
    except AIServiceError as exc:
        raise _ai_http_error(exc, context="start_interview")


@router.post("/{interview_id}/answer", response_model=AnswerResponse)
async def answer_endpoint(
    interview_id: str,
    payload: AnswerRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(user_rate_limit("expensive")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    ai_client: AIClient = Depends(get_ai_client),
) -> AnswerResponse:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    key = _parse_idempotency_key(idempotency_key)

    async def work() -> AnswerResponse:
        try:
            return await submit_answer(
                db, ai_client, doc, payload.answer, expected_question=payload.question
            )
        except InterviewStateError as exc:
            raise _state_http_error(exc)
        except AIServiceError as exc:
            raise _ai_http_error(exc, context="submit_answer")

    return await _run_idempotent(
        db,
        user=current_user,
        scope="answer",
        key=key,
        request_fingerprint=idempotency.fingerprint(
            interview_id, payload.question or "", payload.answer
        ),
        response_model=AnswerResponse,
        work=work,
    )


@router.get("/{interview_id}/turns", response_model=list[InterviewTurnOut])
async def list_turns(
    interview_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> list[InterviewTurnOut]:
    await _get_owned_interview_or_404(db, interview_id, current_user)
    cursor = db.interview_turns.find({"interviewId": interview_id}).sort("sequence", 1)
    return [InterviewTurnOut(**turn) async for turn in cursor]


@router.post("/{interview_id}/exit", response_model=ExitInterviewResponse)
async def exit_interview_endpoint(
    interview_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ExitInterviewResponse:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    try:
        result = await abandon_interview(db, doc)
    except InterviewStateError as exc:
        raise _state_http_error(exc)
    return ExitInterviewResponse(**result)


# -------------------------------------------------------------------------- voice


@router.get("/{interview_id}/question-audio")
async def get_question_audio(
    interview_id: str,
    current_user: dict = Depends(user_rate_limit("expensive")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    ai_client: AIClient = Depends(get_ai_client),
) -> Response:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    pending = doc.get("pendingQuestion")
    if doc["status"] != "in_progress" or not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="There's no active question to speak."
        )

    question_text = pending["question"]
    cache_key = hashlib.sha256(
        f"browser-web-speech|{question_text}".encode("utf-8")
    ).hexdigest()

    audio_bytes = question_audio_cache.get(cache_key)
    if audio_bytes is None:
        try:
            audio_bytes = await ai_client.synthesize_speech(text=question_text)
        except AIServiceError as exc:
            raise _ai_http_error(exc, context="synthesize_speech")
        question_audio_cache.set(cache_key, audio_bytes)

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/{interview_id}/answer/audio", response_model=AudioAnswerResponse)
async def answer_audio_endpoint(
    interview_id: str,
    audio_file: UploadFile = File(...),
    question: Optional[str] = Form(default=None, max_length=2000),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(user_rate_limit("expensive")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    ai_client: AIClient = Depends(get_ai_client),
) -> AudioAnswerResponse:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    key = _parse_idempotency_key(idempotency_key)

    base_type = _base_content_type(audio_file.content_type)
    if base_type not in ALLOWED_AUDIO_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="That audio format isn't supported. Try recording again.",
        )
    format_hint = _AUDIO_FORMAT_HINTS[base_type]

    raw = await _read_upload_limited(
        audio_file, max_bytes=settings.max_audio_upload_bytes, what="recording"
    )
    if len(raw) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio file.")
    if len(raw) > settings.max_audio_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio file too large — keep answers under a few minutes.",
        )

    # Duplicate protection for the expensive part. The same recording for the same
    # question is the same submission, so even a client that sends no
    # Idempotency-Key can't have one recording transcribed twice (double-click,
    # a retry after a lost response). An explicit key from the client wins.
    pending_question = (doc.get("pendingQuestion") or {}).get("question", "")
    question_being_answered = question or pending_question
    audio_digest = hashlib.sha256(raw).hexdigest()
    request_fingerprint = idempotency.fingerprint(interview_id, question_being_answered, audio_digest)
    effective_key = key or f"auto-{request_fingerprint}"

    async def work() -> AudioAnswerResponse:
        if doc["status"] != "in_progress" or not doc.get("pendingQuestion"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There's no active question to answer right now.",
            )

        # Cheap stale-question check *before* decoding or transcribing: a delayed
        # duplicate of an answer that was already accepted must not spend a
        # transcription call just to be refused by the engine afterwards.
        if question and question != pending_question:
            raise _state_http_error(
                InterviewConflictError(
                    "That question has already been answered. Refresh the page to pick up the next one."
                )
            )

        # Decode once, bounded (worker thread, concurrency slot, timeout, ffmpeg
        # output cap), *before* spending a transcription call: this is where an
        # over-long recording is rejected. A decode failure only means "no speech
        # metrics".
        max_seconds = settings.max_audio_duration_seconds
        segment = None
        try:
            segment = await run_bounded(
                speech_analytics.decode_audio_bounded,
                raw,
                format_hint,
                max_seconds=max_seconds,
                timeout=settings.audio_decode_timeout_seconds,
            )
        except speech_analytics.AudioTooLongError:
            limit_label = (
                f"{max_seconds // 60} minute(s)" if max_seconds >= 60 else f"{max_seconds} seconds"
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"That recording is too long — keep answers under {limit_label}.",
            )
        except speech_analytics.SpeechAnalyticsError as exc:
            logger.info("Speech analytics unavailable for this turn: %s", exc)
        except (ProcessingBusyError, ProcessingTimeoutError) as exc:
            raise _processing_http_error(exc, what="recording")

        # Never forward the client-chosen filename to the provider; it only needs a
        # correct extension to know the container format.
        try:
            transcript = await ai_client.transcribe_audio(
                audio_bytes=raw,
                filename=f"answer.{format_hint}",
                language=doc.get("language"),
            )
        except AIServiceError as exc:
            raise _ai_http_error(exc, context="transcribe_audio")

        transcript = transcript.strip()
        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Couldn't make out any speech in that recording. Try again, closer to the mic.",
            )

        # Speech analytics measure the real audio before it is discarded (this
        # project never persists raw audio). A decode failure degrades gracefully:
        # analytics are a bonus, not a requirement for the interview to proceed.
        speech_metrics: dict | None = None
        if segment is not None:
            try:
                metrics = await run_bounded(
                    speech_analytics.compute_speech_metrics,
                    raw,
                    transcript,
                    format_hint=format_hint,
                    language=doc.get("language"),
                    segment=segment,
                    timeout=settings.audio_decode_timeout_seconds,
                )
                speech_metrics = metrics.model_dump()
            except speech_analytics.SpeechAnalyticsError as exc:
                logger.info("Speech analytics unavailable for this turn: %s", exc)
            except (ProcessingBusyError, ProcessingTimeoutError) as exc:
                logger.info("Speech analytics skipped for this turn: %s", type(exc).__name__)

        try:
            result = await submit_answer(
                db,
                ai_client,
                doc,
                transcript,
                speech_metrics=speech_metrics,
                expected_question=question,
            )
        except InterviewStateError as exc:
            raise _state_http_error(exc)
        except AIServiceError as exc:
            raise _ai_http_error(exc, context="submit_answer(audio)")

        return AudioAnswerResponse(**result.model_dump(), transcript=transcript)

    return await _run_idempotent(
        db,
        user=current_user,
        scope="answer-audio",
        key=effective_key,
        request_fingerprint=request_fingerprint,
        response_model=AudioAnswerResponse,
        work=work,
    )


# ---------------------------------------------------------------------- documents


@router.post("/{interview_id}/resume", response_model=ResumeUploadResponse)
async def upload_resume(
    interview_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(user_rate_limit("expensive")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    ai_client: AIClient = Depends(get_ai_client),
) -> ResumeUploadResponse:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)

    # Check the state *before* spending an extraction call.
    if doc["status"] != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resume can only be uploaded before the interview starts.",
        )

    raw = await _read_upload_limited(
        file, max_bytes=settings.max_document_upload_bytes, what="file"
    )
    try:
        resume_text = await run_bounded(
            extract_text,
            filename=file.filename or "resume",
            content_type=file.content_type,
            raw=raw,
            timeout=settings.document_parse_timeout_seconds,
        )
    except DocumentParseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except (ProcessingBusyError, ProcessingTimeoutError) as exc:
        raise _processing_http_error(exc, what="document")

    try:
        candidate_profile = await ai_client.extract_candidate_profile(
            system=prompts.RESUME_EXTRACTION_SYSTEM_PROMPT,
            user=prompts.resume_extraction_user_prompt(resume_text),
        )
    except AIServiceError as exc:
        raise _ai_http_error(exc, context="extract_candidate_profile")

    try:
        await set_candidate_profile(db, doc, candidate_profile)
    except InterviewStateError as exc:
        raise _state_http_error(exc)

    return ResumeUploadResponse(candidateProfile=candidate_profile)


@router.post("/{interview_id}/job-description", response_model=JobDescriptionUploadResponse)
async def upload_job_description(
    interview_id: str,
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    current_user: dict = Depends(user_rate_limit("expensive")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    ai_client: AIClient = Depends(get_ai_client),
) -> JobDescriptionUploadResponse:
    """Accepts either a pasted text field or an uploaded PDF/DOCX file — job
    descriptions are more often copy-pasted from a posting than uploaded as a
    document, so both paths are supported rather than forcing a file."""
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)

    if doc["status"] != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A job description can only be added before the interview starts.",
        )

    if file is None and not (text and text.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either a 'text' field or a 'file' upload.",
        )

    if file is not None:
        raw = await _read_upload_limited(
            file, max_bytes=settings.max_document_upload_bytes, what="file"
        )
        try:
            jd_text = await run_bounded(
                extract_text,
                filename=file.filename or "job-description",
                content_type=file.content_type,
                raw=raw,
                timeout=settings.document_parse_timeout_seconds,
            )
        except DocumentParseError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except (ProcessingBusyError, ProcessingTimeoutError) as exc:
            raise _processing_http_error(exc, what="document")
    else:
        assert text is not None
        jd_text = text.strip()[:15_000]
        if not jd_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Job description text is empty."
            )

    try:
        job_profile = await ai_client.extract_job_profile(
            system=prompts.JOB_EXTRACTION_SYSTEM_PROMPT,
            user=prompts.job_extraction_user_prompt(jd_text),
        )
    except AIServiceError as exc:
        raise _ai_http_error(exc, context="extract_job_profile")

    try:
        await set_job_profile(db, doc, job_profile)
    except InterviewStateError as exc:
        raise _state_http_error(exc)

    return JobDescriptionUploadResponse(jobProfile=job_profile)


# ---------------------------------------------------------------------- analytics


@router.post("/{interview_id}/webcam-metrics", response_model=WebcamMetrics)
async def submit_webcam_metrics(
    interview_id: str,
    metrics: WebcamMetrics,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> WebcamMetrics:
    """Client-computed aggregate signals only — see WebcamMetrics' docstring.
    No raw video ever reaches this endpoint or this backend at all."""
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    if not metrics.consentGiven:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Explicit per-session consent is required before webcam metrics can be saved.",
        )
    if metrics.sampledFrames <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No camera frames were sampled, so there are no webcam metrics to save.",
        )
    if doc["status"] not in ("in_progress", "completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webcam analytics can only be submitted for a session that has started.",
        )
    await db.interviews.update_one(
        {"_id": doc["_id"]}, {"$set": {"webcamMetrics": metrics.model_dump()}}
    )
    return metrics


# ------------------------------------------------------------------------- reports


@router.post("/{interview_id}/report", response_model=InterviewReport)
async def generate_report_endpoint(
    interview_id: str,
    current_user: dict = Depends(user_rate_limit("expensive")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    ai_client: AIClient = Depends(get_ai_client),
) -> InterviewReport:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    try:
        return await generate_report(db, ai_client, doc)
    except InterviewStateError as exc:
        raise _state_http_error(exc)
    except AIServiceError as exc:
        raise _ai_http_error(exc, context="generate_report")


@router.get("/{interview_id}/report", response_model=InterviewReport)
async def get_report_endpoint(
    interview_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> InterviewReport:
    doc = await _get_owned_interview_or_404(db, interview_id, current_user)
    report = doc.get("report")
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No report has been generated for this interview yet.",
        )
    return InterviewReport(**report)
