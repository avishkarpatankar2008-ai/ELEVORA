"""Idempotent submission of interview answers (text and voice).

The problem
-----------
A candidate's request can be sent twice without the candidate meaning to: a
double-click, a retry after a dropped connection (the server finished but the
response never arrived), two tabs. The engine already refuses to *record* a
second turn (atomic claims + unique turn index), but for a voice answer the
expensive work — decoding and a billed Groq transcription — happens before the
engine is reached, and a retry after a lost response used to surface as a
confusing "already answered" error instead of the result the first request
produced.

The mechanism
-------------
A client attaches an ``Idempotency-Key`` (any unique string per submission).
For each (user, scope, key) the server stores one small document:

* ``pending``  — set atomically with a unique ``_id`` insert, so exactly one
  concurrent request wins and does the work; the others get 409 and the
  client resyncs. A pending record expires, so a crashed request can't wedge
  the answer forever.
* ``done``     — the winner's JSON response. A retry with the same key and the
  same payload gets that response back, with no transcription and no AI call.
* released     — if the work fails (provider error, validation, cancellation)
  the record is deleted so the candidate can retry straight away.

Reusing a key for a *different* payload is a client bug and is refused (422)
rather than silently returning someone else's result. Keys are scoped per user,
and the stored ``_id`` is a digest, so a key can never reach another account's
record. Records are deleted by a TTL index; nothing is kept beyond the replay
window.
"""

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

COLLECTION = "idempotency_keys"

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:\-]{8,128}$")


class IdempotencyError(Exception):
    """Base class; subclasses map to HTTP statuses in the router."""


class IdempotencyInFlightError(IdempotencyError):
    """The same submission is already being processed (409)."""


class IdempotencyMismatchError(IdempotencyError):
    """The key was already used for a different payload (422)."""


@dataclass(frozen=True)
class IdempotencyHandle:
    doc_id: str
    owner: str


def validate_key(raw: str | None) -> str | None:
    """Return the key, None when absent, or raise ``ValueError`` when malformed."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if not _KEY_PATTERN.fullmatch(raw):
        raise ValueError(
            "Idempotency-Key must be 8-128 characters: letters, digits, and _ . : -"
        )
    return raw


def fingerprint(*parts: str | bytes) -> str:
    """Digest of the request payload. Length-prefixed so ("ab", "c") != ("a", "bc")."""
    digest = hashlib.sha256()
    for part in parts:
        data = part.encode("utf-8") if isinstance(part, str) else part
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _doc_id(user_id: str, scope: str, key: str) -> str:
    return hashlib.sha256(f"{user_id}|{scope}|{key}".encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    # Mongo (and mongomock) hand back naive datetimes; they are UTC by construction.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def begin(
    db: Any, *, user_id: str, scope: str, key: str, request_fingerprint: str
) -> tuple[IdempotencyHandle | None, dict | None]:
    """Claim (user, scope, key).

    Returns ``(handle, None)`` when the caller must do the work, or
    ``(None, stored_response)`` when an identical submission already finished.
    Raises :class:`IdempotencyInFlightError` / :class:`IdempotencyMismatchError`.
    """
    settings = get_settings()
    collection = db[COLLECTION]
    doc_id = _doc_id(user_id, scope, key)

    for _ in range(3):
        now = _now()
        owner = uuid.uuid4().hex
        record = {
            "_id": doc_id,
            "userId": user_id,
            "scope": scope,
            "fingerprint": request_fingerprint,
            "status": "pending",
            "owner": owner,
            "createdAt": now,
            "expiresAt": now + timedelta(seconds=settings.idempotency_ttl_seconds),
        }
        try:
            await collection.insert_one(record)
            return IdempotencyHandle(doc_id, owner), None
        except DuplicateKeyError:
            pass

        existing = await collection.find_one({"_id": doc_id})
        if existing is None:
            continue  # purged between the insert and the read; try again

        if existing.get("fingerprint") != request_fingerprint:
            raise IdempotencyMismatchError(
                "That Idempotency-Key was already used for a different submission."
            )

        status = existing.get("status")
        expires_at = existing.get("expiresAt")
        expired = expires_at is not None and _as_utc(expires_at) <= now

        if status == "done" and not expired:
            return None, existing.get("response") or {}

        if status == "pending" and not expired:
            created_at = existing.get("createdAt")
            age = (now - _as_utc(created_at)).total_seconds() if created_at else 0.0
            if age < settings.idempotency_pending_seconds:
                raise IdempotencyInFlightError(
                    "This answer is already being processed. Give it a moment."
                )

        # A stale pending record (its request died) or an expired result that the
        # TTL sweep hasn't removed yet: take it over, but only if nobody else did
        # first (the owner token makes the swap atomic).
        taken = await collection.update_one(
            {"_id": doc_id, "owner": existing.get("owner")},
            {
                "$set": {
                    "status": "pending",
                    "owner": owner,
                    "createdAt": now,
                    "expiresAt": record["expiresAt"],
                },
                "$unset": {"response": ""},
            },
        )
        if taken.matched_count == 1:
            return IdempotencyHandle(doc_id, owner), None
        raise IdempotencyInFlightError("This answer is already being processed. Give it a moment.")

    raise IdempotencyInFlightError("This answer is already being processed. Give it a moment.")


async def complete(db: Any, handle: IdempotencyHandle, response: dict) -> None:
    """Store the winner's response for replay. Only the current owner may write."""
    await db[COLLECTION].update_one(
        {"_id": handle.doc_id, "owner": handle.owner},
        {
            "$set": {
                "status": "done",
                "response": response,
                "expiresAt": _now() + timedelta(seconds=get_settings().idempotency_ttl_seconds),
            }
        },
    )


async def release(db: Any, handle: IdempotencyHandle) -> None:
    """Drop our pending record so a retry can run. Never raises (cleanup)."""
    try:
        await db[COLLECTION].delete_one(
            {"_id": handle.doc_id, "owner": handle.owner, "status": "pending"}
        )
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the real error
        logger.error("Failed to release idempotency record: %s", exc)


async def release_shielded(db: Any, handle: IdempotencyHandle) -> None:
    """Like :func:`release`, but completes even if the request is being cancelled
    (client disconnect), in its own task."""
    cleanup = asyncio.ensure_future(release(db, handle))
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        raise
