"""Short-lived, self-expiring claims used to serialize work on one document.

A claim is a timestamp field on the document that a request sets with an
atomic conditional update before doing expensive work (an AI call), and clears
when it is finished. Three properties matter:

* **Single winner.** The ``find_one_and_update`` filter includes the exact
  state the caller expects plus "no live claim", so exactly one concurrent
  request proceeds.
* **Self-healing.** A claim older than ``stale_claim_seconds`` is ignored, so a
  crashed, killed, or timed-out request can never leave an interview
  permanently stuck.
* **Explicit release.** Failures release the claim immediately rather than
  making the next attempt wait out the stale window.
* **Owner-checked.** The claim's timestamp doubles as an ownership token.
  Releasing and the final state write both filter on it, so a request whose
  claim went stale and was taken over can neither release the new owner's claim
  nor overwrite the state the new owner is producing.
* **Deadline < stale window.** Work done under a claim is bounded by
  :func:`run_within_claim_deadline`, which is shorter than the stale window, so
  a healthy-but-slow request gives up before anyone is allowed to take over.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Optional, TypeVar

from pymongo import ReturnDocument

from app.config import get_settings
from app.core.logging import get_logger
from app.services.ai_client import AIServiceError

logger = get_logger(__name__)

T = TypeVar("T")


def _stale_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=get_settings().stale_claim_seconds)


def claim_is_free(field: str) -> dict[str, Any]:
    """Filter fragment matching a document with no live claim on ``field``."""
    return {
        "$or": [
            {field: {"$exists": False}},
            {field: None},
            {field: {"$lt": _stale_cutoff()}},
        ]
    }


async def acquire_claim(
    db: Any,
    *,
    collection: str,
    document_id: Any,
    field: str,
    extra_filter: Optional[dict[str, Any]] = None,
) -> Optional[dict]:
    """Atomically claim ``document_id``. Returns the updated document, or None
    if someone else holds a live claim (or the extra filter didn't match)."""
    query: dict[str, Any] = {"_id": document_id, **claim_is_free(field)}
    if extra_filter:
        query.update(extra_filter)

    return await db[collection].find_one_and_update(
        query,
        {"$set": {field: datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


async def release_claim(
    db: Any, *, collection: str, document_id: Any, field: str, owner: Any = None
) -> None:
    """Release a claim. Failures are logged, never raised: releasing is cleanup
    and must not mask the original error.

    When ``owner`` (the value returned by :func:`acquire_claim` in ``field``) is
    given, only that exact claim is released, so a stale request can't free a
    claim that now belongs to someone else.
    """
    query: dict[str, Any] = {"_id": document_id}
    if owner is not None:
        query[field] = owner
    try:
        await db[collection].update_one(query, {"$unset": {field: ""}})
    except Exception as exc:  # noqa: BLE001 - cleanup must not raise
        logger.error("Failed to release %s on %s/%s: %s", field, collection, document_id, exc)


async def release_claim_shielded(
    db: Any, *, collection: str, document_id: Any, field: str, owner: Any = None
) -> None:
    """Release a claim even when the surrounding task is being cancelled (client
    disconnect, server shutdown). The cleanup runs to completion in its own task."""
    cleanup = asyncio.ensure_future(
        release_claim(db, collection=collection, document_id=document_id, field=field, owner=owner)
    )
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        # We are being cancelled; the cleanup task keeps running on its own.
        raise


def claim_deadline_seconds() -> float:
    """Work under a claim must finish (or give up) before the claim can be
    taken over as stale."""
    return max(5.0, get_settings().stale_claim_seconds * 0.8)


async def run_within_claim_deadline(work: Awaitable[T]) -> T:
    try:
        return await asyncio.wait_for(work, timeout=claim_deadline_seconds())
    except asyncio.TimeoutError as exc:
        raise AIServiceError("Operation exceeded its claim deadline.", kind="timeout") from exc
