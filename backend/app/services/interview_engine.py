"""Interview state machine.

States: ``draft -> in_progress -> completed``, plus ``in_progress ->
abandoned`` when the candidate exits early.

Concurrency model
-----------------
Every state-changing operation first *claims* the transition with a single
atomic ``find_one_and_update`` that filters on the exact state the caller
believes it is in (status, question number, pending question text). That is
what makes a double-clicked "Submit answer", a retried request, or two tabs
sharing one session safe:

* the loser of the race gets a 409 instead of a duplicate turn or a second
  billed question-generation call;
* the claim expires (``STALE_CLAIM_SECONDS``) so a crashed or timed-out
  request can never leave an interview permanently stuck;
* the claim is explicitly released when the operation fails, so the candidate
  can simply try again.

Turns are also protected by a unique ``(interviewId, sequence)`` index, which
makes answer submission idempotent even if a write is retried.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.core.logging import get_logger
from app.schemas.ai import AnswerAnalysis, QuestionGeneration
from app.schemas.candidate import CandidateProfile
from app.schemas.interview import AnswerResponse, PendingQuestionOut, StartInterviewResponse
from app.schemas.job import JobProfile
from app.schemas.profile import InterviewProfile
from app.services import prompts, similarity
from app.services.claims import (
    acquire_claim,
    claim_is_free,
    release_claim_shielded,
    run_within_claim_deadline,
)
from app.services.ai_client import AIClient
from app.services.profiles import DIFFICULTY_BASELINE, load_profile

logger = get_logger(__name__)

# Fields used to serialize work on one interview document. They exist only
# while an operation is in flight and are always removed afterwards.
START_CLAIM_FIELD = "startClaimedAt"
ANSWER_CLAIM_FIELD = "answerClaimedAt"
REPORT_CLAIM_FIELD = "reportClaimedAt"

# How long to wait for a concurrent request to finish writing before giving up
# on returning its result (only used on the idempotent-replay path).
_REPLAY_POLL_ATTEMPTS = 6
_REPLAY_POLL_DELAY_SECONDS = 0.1


class InterviewStateError(Exception):
    """Raised when an action is attempted in the wrong interview state
    (e.g. answering when there's no pending question). Maps to 400."""


class InterviewConflictError(InterviewStateError):
    """Raised when the same action is already in flight (or was already
    applied). Maps to 409 so the client can refetch instead of retrying."""


def _load_candidate_and_job(
    interview: dict,
) -> tuple[CandidateProfile | None, JobProfile | None]:
    """Resume/JD context, if it's been uploaded for this interview."""
    candidate_raw = interview.get("candidateProfile")
    job_raw = interview.get("jobProfile")
    candidate = CandidateProfile.model_validate(candidate_raw) if candidate_raw else None
    job = JobProfile.model_validate(job_raw) if job_raw else None
    return candidate, job


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _dedup_append(existing: list[str], new_items: list[str], cap: int) -> list[str]:
    result = list(existing)
    for item in new_items:
        if item and item not in result:
            result.append(item)
    return result[-cap:]


def _difficulty_delta(quality: int) -> int:
    if quality <= 2:
        return -1
    if quality >= 4:
        return 1
    return 0


def _compute_max_questions(duration_minutes: int) -> int:
    """Heuristic: roughly one question (with its follow-ups) per 3 minutes.

    Used only when the selected Interview Profile doesn't set an explicit
    question count.
    """
    return max(4, min(20, round(duration_minutes / 3)))


def _pick_next_topic(profile: InterviewProfile, asked_topics: list[str]) -> str:
    for subject in profile.subjects:
        if subject not in asked_topics:
            return subject
    # Every subject has come up at least once — cycle back through the list
    # rather than getting stuck, so a long interview still has something to ask.
    return profile.subjects[len(asked_topics) % len(profile.subjects)]


# --------------------------------------------------------------------------
# question generation
# --------------------------------------------------------------------------


async def _generate_unique_question(
    ai_client: AIClient,
    profile: InterviewProfile,
    *,
    mode: str,
    topic: str,
    difficulty: int,
    previously_asked: list[str],
    candidate: CandidateProfile | None = None,
    job: JobProfile | None = None,
    previous_question: str | None = None,
    previous_answer: str | None = None,
    missing_evidence: str | None = None,
    opening: bool = False,
    language: str | None = None,
) -> QuestionGeneration:
    system = prompts.question_system_prompt(
        profile, candidate=candidate, job=job, language=language
    )
    if mode == "follow_up":
        assert previous_question is not None and previous_answer is not None
        user = prompts.follow_up_question_user_prompt(
            topic, difficulty, previous_question, previous_answer, missing_evidence, previously_asked
        )
    else:
        user = prompts.baseline_question_user_prompt(topic, difficulty, previously_asked, opening=opening)

    question = await ai_client.generate_question(system=system, user=user)

    collision = similarity.find_too_similar(question.question, previously_asked)
    if collision:
        # One retry with an explicit nudge. If it still collides we proceed
        # anyway — per the architecture rule against unbounded retry loops, and
        # because a near-miss that slips through is a far smaller problem than
        # a stuck request.
        retry_user = user + prompts.regenerate_unique_suffix(collision)
        question = await ai_client.generate_question(system=system, user=retry_user)

    return question


# --------------------------------------------------------------------------
# transitions
# --------------------------------------------------------------------------


_LOST_CLAIM_MESSAGE = (
    "This interview changed while your request was being processed (it may have been "
    "exited, or another request took over). Refresh the page to see the current state."
)


async def start_interview(db: Any, ai_client: AIClient, interview: dict) -> StartInterviewResponse:
    """draft -> in_progress. Generates the opening question."""
    claimed = await acquire_claim(
        db,
        collection="interviews",
        document_id=interview["_id"],
        field=START_CLAIM_FIELD,
        extra_filter={"status": "draft"},
    )
    if claimed is None:
        current = await db.interviews.find_one({"_id": interview["_id"]})
        if current is None:
            raise InterviewStateError("Interview not found")
        if current.get("status") != "draft":
            raise InterviewStateError("This interview has already been started.")
        raise InterviewConflictError(
            "This interview is already being started — give it a moment and try again."
        )

    claim_owner = claimed[START_CLAIM_FIELD]
    try:
        profile, engine_settings = await load_profile(db, claimed)
        candidate, job = _load_candidate_and_job(claimed)
        if not engine_settings["resumeGrounding"]:
            candidate = None
        if not engine_settings["jdGrounding"]:
            job = None

        difficulty_level = DIFFICULTY_BASELINE[claimed["difficulty"]]
        max_questions = engine_settings["maxQuestions"] or _compute_max_questions(
            claimed["durationMinutes"]
        )
        first_topic = profile.subjects[0]

        question = await run_within_claim_deadline(
            _generate_unique_question(
                ai_client,
                profile,
                mode="baseline",
                topic=first_topic,
                difficulty=difficulty_level,
                previously_asked=[],
                candidate=candidate,
                job=job,
                opening=True,
                language=claimed.get("language"),
            )
        )

        now_ts = datetime.now(timezone.utc)
        updates = {
            "status": "in_progress",
            "questionNumber": 0,
            "maxQuestions": max_questions,
            "difficultyLevel": difficulty_level,
            "currentTopic": question.topic,
            "askedTopics": [],
            "askedQuestions": [question.question],
            "followUpCounts": {},
            "strengths": [],
            "weaknesses": [],
            "pendingQuestion": question.model_dump(),
            "startedAt": now_ts,
            "updatedAt": now_ts,
        }
        # Owner-checked write: if our claim went stale and was taken over (or the
        # interview was deleted), this matches nothing instead of clobbering state.
        result = await db.interviews.update_one(
            {"_id": claimed["_id"], "status": "draft", START_CLAIM_FIELD: claim_owner},
            {"$set": updates, "$unset": {START_CLAIM_FIELD: ""}},
        )
        if result.matched_count == 0:
            raise InterviewConflictError(_LOST_CLAIM_MESSAGE)
    except BaseException:
        # Includes cancellation (client disconnect): release so the candidate can
        # retry at once, then re-raise the original error for the caller.
        await release_claim_shielded(
            db,
            collection="interviews",
            document_id=claimed["_id"],
            field=START_CLAIM_FIELD,
            owner=claim_owner,
        )
        raise

    return StartInterviewResponse(
        status="in_progress",
        questionNumber=0,
        maxQuestions=max_questions,
        difficultyLevel=difficulty_level,
        pendingQuestion=PendingQuestionOut(**question.model_dump()),
    )


async def submit_answer(
    db: Any,
    ai_client: AIClient,
    interview: dict,
    answer_text: str,
    speech_metrics: dict | None = None,
    expected_question: str | None = None,
) -> AnswerResponse:
    """Record an answer, analyze it, and advance the interview.

    Ordering is deliberate: the analysis and the next question are generated
    *before* anything is persisted, so a provider failure leaves the interview
    exactly as it was and the candidate can retry the same answer without
    creating a duplicate turn.
    """
    pending = interview.get("pendingQuestion")
    if interview.get("status") != "in_progress" or not pending:
        raise InterviewStateError("There's no active question to answer right now.")

    # The question guard is what makes a duplicate submission safe. Without it,
    # a slow double-click would answer whatever question happens to be pending
    # by the time the second request runs — the previous answer would be
    # recorded against the *next* question. The client sends the question text
    # it displayed; if that is no longer the pending one, this request is a
    # duplicate (or stale) and must not consume another question.
    question_being_answered = expected_question or pending["question"]

    claimed = await acquire_claim(
        db,
        collection="interviews",
        document_id=interview["_id"],
        field=ANSWER_CLAIM_FIELD,
        extra_filter={
            "status": "in_progress",
            "pendingQuestion.question": question_being_answered,
        },
    )
    if claimed is None:
        raise InterviewConflictError(
            "That question has already been answered. Refresh the page to pick up the next one."
        )

    claim_owner = claimed[ANSWER_CLAIM_FIELD]
    claimed_pending = claimed["pendingQuestion"]
    sequence = claimed["questionNumber"] + 1

    try:
        return await _answer_under_claim(
            db,
            ai_client,
            claimed,
            claimed_pending,
            claim_owner,
            sequence,
            answer_text,
            speech_metrics,
        )
    except BaseException:
        # Includes cancellation: never leave the interview holding our claim.
        await release_claim_shielded(
            db,
            collection="interviews",
            document_id=claimed["_id"],
            field=ANSWER_CLAIM_FIELD,
            owner=claim_owner,
        )
        raise


async def _answer_under_claim(
    db: Any,
    ai_client: AIClient,
    claimed: dict,
    claimed_pending: dict,
    claim_owner: Any,
    sequence: int,
    answer_text: str,
    speech_metrics: dict | None,
) -> AnswerResponse:
    profile, engine_settings = await load_profile(db, claimed)
    candidate, job = _load_candidate_and_job(claimed)
    if not engine_settings["resumeGrounding"]:
        candidate = None
    if not engine_settings["jdGrounding"]:
        job = None
    language = claimed.get("language")

    async def _generate() -> tuple[AnswerAnalysis, dict, dict | None, str, datetime | None]:
        analysis = await ai_client.analyze_answer(
            system=prompts.analysis_system_prompt(profile, language=language),
            user=prompts.analysis_user_prompt(
                claimed_pending["question"], answer_text, claimed_pending["difficulty"]
            ),
        )

        difficulty_delta = (
            _difficulty_delta(analysis.quality) if engine_settings["adaptiveDifficulty"] else 0
        )
        new_difficulty = _clamp(claimed["difficultyLevel"] + difficulty_delta, 1, 5)

        asked_topics = list(claimed.get("askedTopics", []))
        if not claimed_pending["isFollowUp"] and claimed_pending["topic"] not in asked_topics:
            asked_topics.append(claimed_pending["topic"])

        follow_up_counts = dict(claimed.get("followUpCounts", {}))
        if claimed_pending["isFollowUp"]:
            follow_up_counts[claimed_pending["topic"]] = (
                follow_up_counts.get(claimed_pending["topic"], 0) + 1
            )

        asked_questions = list(claimed.get("askedQuestions", []))
        reached_limit = sequence >= claimed["maxQuestions"]

        next_pending: dict | None = None
        new_status = "in_progress"
        completed_at = None

        if reached_limit:
            new_status = "completed"
            completed_at = datetime.now(timezone.utc)
        else:
            # Follow-up depth is capped at one per topic; profile settings can
            # switch the branch off entirely.
            want_follow_up = (
                engine_settings["followUpEnabled"]
                and analysis.followUpNeeded
                and not claimed_pending["isFollowUp"]
                and follow_up_counts.get(claimed_pending["topic"], 0) < 1
            )

            if want_follow_up:
                next_question = await _generate_unique_question(
                    ai_client,
                    profile,
                    mode="follow_up",
                    topic=claimed_pending["topic"],
                    difficulty=new_difficulty,
                    previously_asked=asked_questions,
                    candidate=candidate,
                    job=job,
                    previous_question=claimed_pending["question"],
                    previous_answer=answer_text,
                    missing_evidence=analysis.missingEvidence,
                    language=language,
                )
            else:
                next_topic = _pick_next_topic(profile, asked_topics)
                next_question = await _generate_unique_question(
                    ai_client,
                    profile,
                    mode="baseline",
                    topic=next_topic,
                    difficulty=new_difficulty,
                    previously_asked=asked_questions,
                    candidate=candidate,
                    job=job,
                    language=language,
                )

            asked_questions.append(next_question.question)
            next_pending = next_question.model_dump()

        updates = {
            "questionNumber": sequence,
            "difficultyLevel": new_difficulty,
            "askedTopics": asked_topics,
            "askedQuestions": asked_questions,
            "followUpCounts": follow_up_counts,
            "strengths": _dedup_append(claimed.get("strengths", []), analysis.strengths, cap=8),
            "weaknesses": _dedup_append(claimed.get("weaknesses", []), analysis.weaknesses, cap=8),
            "pendingQuestion": next_pending,
            "status": new_status,
            "currentTopic": next_pending["topic"] if next_pending else claimed_pending["topic"],
        }
        return analysis, updates, next_pending, new_status, completed_at

    analysis, updates, next_pending, new_status, completed_at = await run_within_claim_deadline(
        _generate()
    )

    # ---- persist -------------------------------------------------------------
    # Cheap ownership check before writing anything: if the candidate exited, the
    # interview was deleted, or our claim was taken over while the AI was
    # thinking, don't record a turn for a session that no longer wants it.
    still_ours = await db.interviews.find_one(
        {"_id": claimed["_id"], "status": "in_progress", ANSWER_CLAIM_FIELD: claim_owner},
        {"_id": 1},
    )
    if still_ours is None:
        raise InterviewConflictError(_LOST_CLAIM_MESSAGE)

    now_ts = datetime.now(timezone.utc)
    turn_doc = {
        "interviewId": str(claimed["_id"]),
        "sequence": sequence,
        "question": claimed_pending["question"],
        "answer": answer_text,
        "topic": claimed_pending["topic"],
        "difficulty": claimed_pending["difficulty"],
        "isFollowUp": claimed_pending["isFollowUp"],
        "evaluation": analysis.model_dump(),
        "speechMetrics": speech_metrics,  # None for text answers — no audio to measure
        "claimedAt": claim_owner,  # which claim wrote this turn (orphan recovery)
        "createdAt": now_ts,
    }

    try:
        await db.interview_turns.insert_one(turn_doc)
    except DuplicateKeyError:
        existing = await db.interview_turns.find_one(
            {"interviewId": str(claimed["_id"]), "sequence": sequence}
        )
        latest = await db.interviews.find_one({"_id": claimed["_id"]})
        if latest is not None and latest.get("questionNumber", 0) >= sequence:
            # Another request already recorded AND applied this exact turn
            # (a double-click, a retry after a timeout, a second tab).
            # Our own claim is not cleaned up by the other request's write, so
            # release it here; otherwise it would block the next answer until it
            # went stale.
            await release_claim_shielded(
                db,
                collection="interviews",
                document_id=claimed["_id"],
                field=ANSWER_CLAIM_FIELD,
                owner=claim_owner,
            )
            return await _replay_previous_answer(db, claimed, sequence)
        if existing is None:  # pragma: no cover - defensive
            raise InterviewConflictError(_LOST_CLAIM_MESSAGE)
        # The turn exists but the interview never advanced: a previous holder of
        # this question's claim died between the two writes. We hold the live
        # claim, so take the orphan over rather than leaving the answer stuck.
        # insert_one() added an "_id" to turn_doc in place even though it failed; a
        # replacement document must not carry one (the _id is immutable).
        replacement = {key: value for key, value in turn_doc.items() if key != "_id"}
        replaced = await db.interview_turns.replace_one(
            {"_id": existing["_id"], "claimedAt": existing.get("claimedAt")}, replacement
        )
        if replaced.matched_count == 0:
            raise InterviewConflictError(_LOST_CLAIM_MESSAGE)

    updates["updatedAt"] = now_ts
    if completed_at:
        updates["completedAt"] = completed_at

    # Owner- and state-checked: an exit (abandoned), a delete, or a takeover
    # that happened since the check above wins; this write then matches nothing.
    result = await db.interviews.update_one(
        {"_id": claimed["_id"], "status": "in_progress", ANSWER_CLAIM_FIELD: claim_owner},
        {"$set": updates, "$unset": {ANSWER_CLAIM_FIELD: ""}},
    )
    if result.matched_count == 0:
        # Roll back the turn we just wrote so the transcript never holds an
        # answer for a question the interview state doesn't know was answered.
        await db.interview_turns.delete_one(
            {
                "interviewId": str(claimed["_id"]),
                "sequence": sequence,
                "claimedAt": claim_owner,
            }
        )
        raise InterviewConflictError(_LOST_CLAIM_MESSAGE)

    return AnswerResponse(
        status=new_status,
        questionNumber=sequence,
        maxQuestions=claimed["maxQuestions"],
        difficultyLevel=updates["difficultyLevel"],
        pendingQuestion=PendingQuestionOut(**next_pending) if next_pending else None,
        lastEvaluation=analysis,
    )


async def _replay_previous_answer(db: Any, claimed: dict, sequence: int) -> AnswerResponse:
    """Build the response for a turn another request already wrote.

    The interview document update is a separate write from the turn insert, so
    on this path it may not have landed yet. A short bounded poll covers that
    window; if it still hasn't landed we return the freshest state we have
    rather than blocking the request.
    """
    interview = claimed
    for _ in range(_REPLAY_POLL_ATTEMPTS):
        latest = await db.interviews.find_one({"_id": claimed["_id"]})
        if latest is None:
            raise InterviewStateError("Interview not found")
        interview = latest
        if latest.get("questionNumber", 0) >= sequence or latest.get("status") != "in_progress":
            break
        await asyncio.sleep(_REPLAY_POLL_DELAY_SECONDS)

    turn = await db.interview_turns.find_one(
        {"interviewId": str(claimed["_id"]), "sequence": sequence}
    )
    if turn is None:  # pragma: no cover - defensive
        raise InterviewConflictError("That answer was already submitted.")

    pending = interview.get("pendingQuestion")
    return AnswerResponse(
        status=interview["status"],
        questionNumber=interview.get("questionNumber", sequence),
        maxQuestions=interview.get("maxQuestions", claimed["maxQuestions"]),
        difficultyLevel=interview.get("difficultyLevel", claimed["difficultyLevel"]),
        pendingQuestion=PendingQuestionOut(**pending) if pending else None,
        lastEvaluation=AnswerAnalysis.model_validate(turn["evaluation"]),
    )


async def abandon_interview(db: Any, interview: dict) -> dict:
    """in_progress -> abandoned ('exit interview').

    The partial transcript already recorded in interview_turns survives; the
    interview is never deleted, and it is never scored.
    """
    now_ts = datetime.now(timezone.utc)
    result = await db.interviews.update_one(
        {"_id": interview["_id"], "status": "in_progress"},
        {
            "$set": {
                "status": "abandoned",
                "pendingQuestion": None,
                "completedAt": now_ts,
                "updatedAt": now_ts,
            },
            "$unset": {ANSWER_CLAIM_FIELD: ""},
        },
    )
    if result.modified_count == 0:
        current = await db.interviews.find_one({"_id": interview["_id"]})
        if current is None:
            raise InterviewStateError("Interview not found")
        if current.get("status") == "draft":
            raise InterviewStateError("This interview hasn't started yet.")
        if current.get("status") == "completed":
            raise InterviewStateError("This interview is already completed.")
        raise InterviewStateError("Only an interview in progress can be exited early.")

    current = await db.interviews.find_one({"_id": interview["_id"]})
    return {"status": "abandoned", "questionNumber": current.get("questionNumber", 0)}


async def _set_draft_field(db: Any, interview: dict, field: str, value: dict, *, what: str) -> None:
    """Write ``field`` on a draft interview that is not currently being started.

    ``start_interview`` reads the resume/JD when it takes its claim; a write that
    landed after that would be reported as saved yet never influence the
    questions, so it is rejected instead.
    """
    result = await db.interviews.update_one(
        {"_id": interview["_id"], "status": "draft", **claim_is_free(START_CLAIM_FIELD)},
        {"$set": {field: value, "updatedAt": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        current = await db.interviews.find_one({"_id": interview["_id"]}, {"status": 1})
        if current is not None and current.get("status") == "draft":
            raise InterviewConflictError(
                "The interview is being started — wait for it to begin before changing it."
            )
        raise InterviewStateError(f"{what} can only be added before the interview starts.")


async def set_candidate_profile(db: Any, interview: dict, profile: CandidateProfile) -> None:
    """Attach extracted resume data. Restricted to draft interviews — changing
    the candidate's background mid-interview would be a strange experience and
    isn't part of the upload-then-start flow."""
    await _set_draft_field(
        db, interview, "candidateProfile", profile.model_dump(), what="A resume"
    )


async def set_job_profile(db: Any, interview: dict, profile: JobProfile) -> None:
    """Attach extracted job-description data. Same restriction as
    set_candidate_profile."""
    await _set_draft_field(
        db, interview, "jobProfile", profile.model_dump(), what="A job description"
    )
