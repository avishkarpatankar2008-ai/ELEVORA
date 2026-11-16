"""Rate limiting for the auth endpoints and for endpoints that spend AI/CPU budget.

Two layers, no extra infrastructure
-----------------------------------
1. **In-process sliding log** (``RateLimiter``). Cheap, exact, and checked first:
   a flood is turned away without touching the database. Each worker only sees
   its own traffic, so on its own the effective limit would be N x the configured
   value with N workers.
2. **MongoDB sliding-window counter** (``_shared_check``). MongoDB is already a
   hard requirement of this service, so the limit can be made *global across
   workers and instances* with one atomic ``$inc`` upsert per check — no Redis.
   Counters live in 1-window buckets that a TTL index deletes on their own, and
   the previous bucket is weighted by how much of it still overlaps the sliding
   window (the standard "sliding window counter" approximation: within a few
   percent of an exact log, and no burst-at-the-boundary loophole).

If the shared layer fails (database hiccup) the request is judged by the
in-process layer alone — rate limiting degrades to per-process instead of
turning a database blip into a login outage.

Both layers must agree to allow a request, so the shared layer can only make the
limit stricter, never looser, than the local one.
"""

import hashlib
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from pymongo import ReturnDocument

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SHARED_COLLECTION = "rate_limit_windows"

# Bounds for the in-process store. Keys include client-supplied values (emails),
# so an attacker can mint keys freely; memory and sweep cost must stay bounded.
_MAX_KEYS = 50_000
_SWEEP_INTERVAL_SECONDS = 30.0


class RateLimiter:
    """Sliding-log limiter with per-key expiry and bounded memory."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._expires: dict[str, float] = {}
        self._lock = Lock()
        self._last_sweep = time.monotonic()

    def check(self, key: str, *, limit: int, window_seconds: int) -> float:
        """Record a hit for ``key``. Returns 0.0 when allowed, or the number of
        seconds the caller should wait before retrying."""
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            window = self._hits.get(key)
            if window is None:
                window = self._hits[key] = deque()
            while window and window[0] <= cutoff:
                window.popleft()

            if len(window) >= limit:
                self._expires[key] = now + window_seconds
                return max(0.0, window[0] + window_seconds - now)

            window.append(now)
            self._expires[key] = now + window_seconds
            self._maybe_sweep(now)
        return 0.0

    def undo(self, key: str) -> None:
        """Forget the most recent hit (used when the shared layer refuses a
        request this layer had already counted)."""
        with self._lock:
            window = self._hits.get(key)
            if window:
                window.pop()

    def _maybe_sweep(self, now: float) -> None:
        """Amortised cleanup, called with the lock held.

        Each key expires on *its own* window. (An earlier version used the
        calling request's window for every key, which could evict still-live
        one-hour registration counters when a one-minute login check ran.)
        """
        if now - self._last_sweep < _SWEEP_INTERVAL_SECONDS and len(self._hits) <= _MAX_KEYS:
            return
        self._last_sweep = now
        for stale_key in [k for k, expiry in self._expires.items() if expiry <= now]:
            self._hits.pop(stale_key, None)
            self._expires.pop(stale_key, None)
        # Still over the cap (a flood of distinct live keys): drop the oldest
        # tenth. Evicting forgets some counters, which is the right trade against
        # unbounded memory.
        overflow = len(self._hits) - _MAX_KEYS
        if overflow > 0:
            for victim in list(self._hits)[: overflow + _MAX_KEYS // 10]:
                self._hits.pop(victim, None)
                self._expires.pop(victim, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._expires.clear()


_limiter = RateLimiter()


def client_ip(request) -> str:
    """The client's address for rate-limiting purposes.

    With ``TRUSTED_PROXY_COUNT=0`` (default) this is the socket peer and
    ``X-Forwarded-For`` is ignored: a direct client could put anything in that
    header. With N trusted proxies in front, the address N entries from the
    *right* of ``X-Forwarded-For`` is the one our outermost trusted proxy
    observed; anything further left is client-supplied and not trusted.

    Behind the Next.js ``/api`` proxy every browser shares the proxy's socket
    address, so set ``TRUSTED_PROXY_COUNT`` to the number of proxies in front
    (docker-compose does). Without it all users would share one per-IP bucket.
    """
    peer = request.client.host if request.client else "unknown"
    proxies = get_settings().trusted_proxy_count
    if proxies <= 0:
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if len(hops) >= proxies:
        return hops[-proxies]
    return peer


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()[:254]


def _auth_limits(scope: str, ip: str, email: str) -> tuple[int, list[tuple[str, int]]]:
    """(window_seconds, [(key, limit), ...]) for one auth attempt.

    Three independent windows are checked, and the longest wait wins:

    * per (IP, email) — the original limit;
    * per IP, across all emails — so one address can't rotate emails (or, for
      registration, create unlimited accounts) to dodge the per-pair limit;
    * per email, across all IPs — so a distributed guessing attack on a single
      account is throttled too.

    ``scope`` is ``"login"`` or ``"register"``.
    """
    settings = get_settings()
    email = _normalize_email(email)
    if scope == "login":
        limit = settings.auth_login_rate_limit
        window = settings.auth_login_rate_window_seconds
        wide_limit = limit * settings.auth_ip_rate_multiplier
    elif scope == "register":
        limit = settings.auth_register_rate_limit
        window = settings.auth_register_rate_window_seconds
        wide_limit = limit  # registration has no reason to be looser per IP
    else:  # pragma: no cover - defensive; only the two scopes above are used
        raise ValueError(f"Unknown rate-limit scope: {scope}")

    checks = [
        (f"{scope}:pair:{ip}|{email}", limit),
        (f"{scope}:ip:{ip}", wide_limit),
    ]
    if email:
        checks.append((f"{scope}:email:{email}", wide_limit))
    return window, checks


# ------------------------------------------------------------------ local layer


def _check_local(window: int, checks: list[tuple[str, int]]) -> tuple[float, list[str]]:
    """Run every check (each records a hit). Returns (longest wait, keys counted)."""
    waits = []
    counted = []
    for key, limit in checks:
        wait = _limiter.check(key, limit=limit, window_seconds=window)
        waits.append(wait)
        if wait == 0.0:
            counted.append(key)
    return max(waits), counted


def check_auth_rate_limit(scope: str, ip: str, email: str = "") -> float:
    """Process-local check. Returns seconds-to-wait (0.0 = allowed).

    Kept for callers that have no database handle; request handlers use
    :func:`enforce_auth_rate_limit`, which adds the cross-worker layer.
    """
    if not get_settings().auth_rate_limit_enabled:
        return 0.0
    window, checks = _auth_limits(scope, ip, email)
    wait, _ = _check_local(window, checks)
    return wait


def check_user_rate_limit(scope: str, user_id: str) -> float:
    """Process-local per-authenticated-user limit."""
    settings = get_settings()
    if not settings.user_rate_limit_enabled:
        return 0.0
    return _limiter.check(
        f"user:{scope}:{user_id}",
        limit=settings.user_rate_limit,
        window_seconds=settings.user_rate_window_seconds,
    )


# ------------------------------------------------------------------ shared layer

_last_shared_warning = 0.0


async def _shared_check(db: Any, key: str, *, limit: int, window_seconds: int) -> float:
    """Global sliding-window counter. Returns 0.0 when allowed, else seconds to wait.

    One atomic upsert-increment on the current bucket plus one read of the
    previous bucket. A request the counter refuses is refunded, so a client
    hammering a closed door doesn't extend its own lockout.
    """
    now = time.time()
    bucket = int(now // window_seconds)
    bucket_start = bucket * window_seconds
    previous_weight = 1.0 - (now - bucket_start) / window_seconds

    # The key itself can contain an email; store only a digest.
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    collection = db[SHARED_COLLECTION]

    previous = await collection.find_one({"_id": f"{digest}:{bucket - 1}"}, {"count": 1})
    previous_count = int(previous["count"]) if previous and "count" in previous else 0

    current = await collection.find_one_and_update(
        {"_id": f"{digest}:{bucket}"},
        {
            "$inc": {"count": 1},
            # Kept for two windows because the next bucket still weighs this one.
            "$setOnInsert": {
                "expiresAt": datetime.fromtimestamp(bucket_start + 2 * window_seconds, tz=timezone.utc)
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    estimated = previous_count * previous_weight + int(current["count"])
    if estimated <= limit:
        return 0.0

    await collection.update_one({"_id": f"{digest}:{bucket}"}, {"$inc": {"count": -1}})
    return max(1.0, bucket_start + window_seconds - now)


async def _check_shared(db: Any, window: int, checks: list[tuple[str, int]]) -> float:
    global _last_shared_warning
    if db is None or not get_settings().shared_rate_limit_enabled:
        return 0.0
    waits = [0.0]
    try:
        for key, limit in checks:
            waits.append(await _shared_check(db, key, limit=limit, window_seconds=window))
    except Exception as exc:  # noqa: BLE001 - never turn a DB blip into an outage
        now = time.monotonic()
        if now - _last_shared_warning > 60:
            _last_shared_warning = now
            logger.warning(
                "Shared rate limiting unavailable (%s); using per-process limits only.",
                type(exc).__name__,
            )
        return 0.0
    return max(waits)


async def enforce_auth_rate_limit(db: Any, scope: str, ip: str, email: str = "") -> float:
    """Seconds-to-wait (0.0 = allowed) for an unauthenticated auth attempt,
    global across workers."""
    if not get_settings().auth_rate_limit_enabled:
        return 0.0
    window, checks = _auth_limits(scope, ip, email)
    wait, counted = _check_local(window, checks)
    if wait > 0:
        return wait
    wait = await _check_shared(db, window, checks)
    if wait > 0:
        for key in counted:
            _limiter.undo(key)
    return wait


async def enforce_user_rate_limit(db: Any, scope: str, user_id: str) -> float:
    """Per-authenticated-user limit for endpoints that spend AI/CPU budget,
    global across workers."""
    settings = get_settings()
    if not settings.user_rate_limit_enabled:
        return 0.0
    key = f"user:{scope}:{user_id}"
    window = settings.user_rate_window_seconds
    wait = _limiter.check(key, limit=settings.user_rate_limit, window_seconds=window)
    if wait > 0:
        return wait
    wait = await _check_shared(db, window, [(key, settings.user_rate_limit)])
    if wait > 0:
        _limiter.undo(key)
    return wait


def reset_rate_limits() -> None:
    """Test/ops hook — clears every in-process counter."""
    _limiter.reset()
