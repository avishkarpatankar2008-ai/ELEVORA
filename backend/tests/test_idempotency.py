"""Safe idempotency for interview answers (text) and voice answers (audio)."""

import asyncio

import pytest

from app.services import idempotency
from app.services.ai_client import AIServiceError

PAYLOAD = {"category": "software-engineer", "difficulty": "medium", "language": "English", "durationMinutes": 5}
AUDIO = {"audio_file": ("answer.webm", b"fake-audio-bytes", "audio/webm")}


async def _started(client, fake, user_payload):
    await client.post("/auth/register", json=user_payload)
    interview = (await client.post("/interviews", json=PAYLOAD)).json()
    fake.queue_question(question="Q1?", topic="Databases", difficulty=3)
    assert (await client.post(f"/interviews/{interview['id']}/start")).status_code == 200
    return interview


async def _turns(test_db, interview_id):
    return [t async for t in test_db.interview_turns.find({"interviewId": interview_id})]


# ----------------------------------------------------------------- text answers


async def test_retry_with_the_same_key_replays_the_original_result(client, user_payload, fake_ai_client, test_db):
    """The server finished but the response was lost: the retry must get the same
    result, not an 'already answered' error, and must not cost another AI call."""
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_analysis(quality=4)
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    body = {"answer": "My answer.", "question": "Q1?"}
    headers = {"Idempotency-Key": "answer-key-0001"}

    first = await client.post(f"/interviews/{interview['id']}/answer", json=body, headers=headers)
    retry = await client.post(f"/interviews/{interview['id']}/answer", json=body, headers=headers)

    assert first.status_code == 200 and retry.status_code == 200
    assert retry.json() == first.json()
    assert len(fake_ai_client.analysis_calls) == 1
    assert len(await _turns(test_db, interview["id"])) == 1


async def test_without_a_key_a_late_duplicate_is_still_refused(client, user_payload, fake_ai_client):
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    body = {"answer": "My answer.", "question": "Q1?"}
    assert (await client.post(f"/interviews/{interview['id']}/answer", json=body)).status_code == 200
    late = await client.post(f"/interviews/{interview['id']}/answer", json=body)
    assert late.status_code == 409


async def test_reusing_a_key_for_a_different_answer_is_rejected(client, user_payload, fake_ai_client):
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    headers = {"Idempotency-Key": "answer-key-0002"}
    await client.post(
        f"/interviews/{interview['id']}/answer", json={"answer": "One.", "question": "Q1?"}, headers=headers
    )
    other = await client.post(
        f"/interviews/{interview['id']}/answer", json={"answer": "Different.", "question": "Q1?"}, headers=headers
    )
    assert other.status_code == 422
    assert "different submission" in other.json()["detail"]


@pytest.mark.parametrize("bad_key", ["short", "has spaces in it!", "x" * 129, "semi;colon-key-1"])
async def test_malformed_keys_are_rejected(client, user_payload, fake_ai_client, bad_key):
    interview = await _started(client, fake_ai_client, user_payload)
    resp = await client.post(
        f"/interviews/{interview['id']}/answer",
        json={"answer": "A.", "question": "Q1?"},
        headers={"Idempotency-Key": bad_key},
    )
    assert resp.status_code == 422


async def test_a_failed_attempt_leaves_the_key_retryable(client, user_payload, fake_ai_client, test_db):
    interview = await _started(client, fake_ai_client, user_payload)
    body = {"answer": "My answer.", "question": "Q1?"}
    headers = {"Idempotency-Key": "answer-key-0003"}

    fake_ai_client.fail_next("analyze_answer", AIServiceError("down", kind="unavailable"))
    failed = await client.post(f"/interviews/{interview['id']}/answer", json=body, headers=headers)
    assert failed.status_code == 502
    assert [d async for d in test_db.idempotency_keys.find({})] == []  # released

    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    retry = await client.post(f"/interviews/{interview['id']}/answer", json=body, headers=headers)
    assert retry.status_code == 200


async def test_concurrent_submissions_with_one_key_do_the_work_once(client, user_payload, fake_ai_client, test_db):
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    body = {"answer": "My answer.", "question": "Q1?"}
    headers = {"Idempotency-Key": "answer-key-0004"}

    a, b = await asyncio.gather(
        client.post(f"/interviews/{interview['id']}/answer", json=body, headers=headers),
        client.post(f"/interviews/{interview['id']}/answer", json=body, headers=headers),
    )
    assert sorted([a.status_code, b.status_code])[0] == 200
    assert {a.status_code, b.status_code} <= {200, 409}
    assert len(fake_ai_client.analysis_calls) == 1
    assert len(await _turns(test_db, interview["id"])) == 1


async def test_keys_are_scoped_to_the_user(client, user_payload, fake_ai_client, test_db):
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    await client.post(
        f"/interviews/{interview['id']}/answer",
        json={"answer": "Mine.", "question": "Q1?"},
        headers={"Idempotency-Key": "shared-key-0001"},
    )
    stored = [d async for d in test_db.idempotency_keys.find({})]
    assert len(stored) == 1 and stored[0]["status"] == "done"
    assert idempotency._doc_id("another-user", "answer", "shared-key-0001") != stored[0]["_id"]


# ----------------------------------------------------------------- voice answers


async def test_same_recording_is_transcribed_once_even_without_a_key(client, user_payload, fake_ai_client, test_db):
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_transcript("I led a small team.")
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    url = f"/interviews/{interview['id']}/answer/audio"

    first = await client.post(url, files=AUDIO, data={"question": "Q1?"})
    again = await client.post(url, files=AUDIO, data={"question": "Q1?"})

    assert first.status_code == 200 and again.status_code == 200
    assert again.json() == first.json()
    assert len(fake_ai_client.transcribe_calls) == 1
    assert len(fake_ai_client.analysis_calls) == 1
    assert len(await _turns(test_db, interview["id"])) == 1


async def test_explicit_key_replays_a_voice_answer(client, user_payload, fake_ai_client):
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_transcript("Spoken answer.")
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    url = f"/interviews/{interview['id']}/answer/audio"
    headers = {"Idempotency-Key": "audio-key-0001"}

    first = await client.post(url, files=AUDIO, data={"question": "Q1?"}, headers=headers)
    again = await client.post(url, files=AUDIO, data={"question": "Q1?"}, headers=headers)
    assert first.json() == again.json() and first.json()["transcript"] == "Spoken answer."
    assert len(fake_ai_client.transcribe_calls) == 1


async def test_stale_voice_answer_is_refused_before_any_transcription(client, user_payload, fake_ai_client):
    """A different recording aimed at a question that was already answered must not
    spend a transcription call just to be rejected afterwards."""
    interview = await _started(client, fake_ai_client, user_payload)
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    assert (
        await client.post(
            f"/interviews/{interview['id']}/answer", json={"answer": "Typed.", "question": "Q1?"}
        )
    ).status_code == 200

    stale = await client.post(
        f"/interviews/{interview['id']}/answer/audio",
        files={"audio_file": ("answer.webm", b"another-recording", "audio/webm")},
        data={"question": "Q1?"},
    )
    assert stale.status_code == 409
    assert fake_ai_client.transcribe_calls == []


async def test_failed_transcription_can_be_retried_with_the_same_recording(client, user_payload, fake_ai_client):
    interview = await _started(client, fake_ai_client, user_payload)
    url = f"/interviews/{interview['id']}/answer/audio"
    fake_ai_client.fail_next("transcribe_audio", AIServiceError("down", kind="unavailable"))
    assert (await client.post(url, files=AUDIO, data={"question": "Q1?"})).status_code == 502

    fake_ai_client.queue_transcript("Second try.")
    fake_ai_client.queue_analysis()
    fake_ai_client.queue_question(question="Q2?", topic="Databases", difficulty=3)
    ok = await client.post(url, files=AUDIO, data={"question": "Q1?"})
    assert ok.status_code == 200 and ok.json()["transcript"] == "Second try."


# ---------------------------------------------------------------- service level


async def test_a_stale_pending_record_is_taken_over(test_db):
    """A request that died mid-flight must not wedge the key forever."""
    from datetime import datetime, timedelta, timezone

    handle, stored = await idempotency.begin(
        test_db, user_id="u1", scope="answer", key="takeover-key-1", request_fingerprint="fp"
    )
    assert handle and stored is None
    with pytest.raises(idempotency.IdempotencyInFlightError):
        await idempotency.begin(
            test_db, user_id="u1", scope="answer", key="takeover-key-1", request_fingerprint="fp"
        )

    await test_db.idempotency_keys.update_one(
        {"_id": handle.doc_id}, {"$set": {"createdAt": datetime.now(timezone.utc) - timedelta(hours=1)}}
    )
    new_handle, stored = await idempotency.begin(
        test_db, user_id="u1", scope="answer", key="takeover-key-1", request_fingerprint="fp"
    )
    assert new_handle and new_handle.owner != handle.owner and stored is None

    # The dead request waking up later can't overwrite the new owner's record.
    await idempotency.complete(test_db, handle, {"late": True})
    record = await test_db.idempotency_keys.find_one({"_id": handle.doc_id})
    assert record["status"] == "pending" and "response" not in record


def test_fingerprint_is_unambiguous():
    assert idempotency.fingerprint("ab", "c") != idempotency.fingerprint("a", "bc")
    assert idempotency.validate_key(None) is None and idempotency.validate_key("   ") is None
