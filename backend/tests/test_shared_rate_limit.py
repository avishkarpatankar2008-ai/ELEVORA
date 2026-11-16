"""Rate limiting that holds across worker processes, plus the in-process store's bounds."""

import time

import pytest

from app.config import get_settings
from app.core import rate_limit
from app.core.rate_limit import (
    RateLimiter,
    enforce_auth_rate_limit,
    enforce_user_rate_limit,
    reset_rate_limits,
)


async def test_login_limit_is_global_across_workers(test_db, monkeypatch):
    """Clearing the in-process counters simulates a request landing on a different
    worker. The shared counters live in MongoDB, so the limit still holds."""
    monkeypatch.setattr(get_settings(), "auth_login_rate_limit", 2)
    monkeypatch.setattr(get_settings(), "auth_ip_rate_multiplier", 1)
    allowed = []
    for _ in range(2):
        allowed.append(await enforce_auth_rate_limit(test_db, "login", "9.9.9.9", "a@example.com"))
        reset_rate_limits()  # "another worker" has never seen this client
    assert allowed == [0.0, 0.0]

    wait = await enforce_auth_rate_limit(test_db, "login", "9.9.9.9", "a@example.com")
    assert wait > 0


async def test_user_limit_is_global_across_workers(test_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "user_rate_limit", 3)
    results = []
    for _ in range(4):
        results.append(await enforce_user_rate_limit(test_db, "expensive", "user-1"))
        reset_rate_limits()
    assert results[:3] == [0.0, 0.0, 0.0] and results[3] > 0
    # Another user is unaffected.
    assert await enforce_user_rate_limit(test_db, "expensive", "user-2") == 0.0


async def test_rejected_attempts_are_refunded_so_a_lockout_does_not_extend_itself(test_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "user_rate_limit", 1)
    assert await enforce_user_rate_limit(test_db, "expensive", "u") == 0.0
    for _ in range(5):
        reset_rate_limits()
        assert await enforce_user_rate_limit(test_db, "expensive", "u") > 0
    stored = [doc async for doc in test_db[rate_limit.SHARED_COLLECTION].find({})]
    assert sum(doc["count"] for doc in stored) == 1  # only the one allowed hit is counted


async def test_shared_counters_are_hashed_and_expire_via_ttl_field(test_db):
    await enforce_auth_rate_limit(test_db, "login", "1.2.3.4", "Private.Person@example.com")
    docs = [doc async for doc in test_db[rate_limit.SHARED_COLLECTION].find({})]
    assert docs and all("expiresAt" in doc for doc in docs)
    assert not any("private.person" in str(doc["_id"]).lower() for doc in docs)


async def test_a_database_failure_degrades_to_per_process_limiting(monkeypatch):
    class BrokenDB:
        def __getitem__(self, name):
            raise RuntimeError("mongo is down")

    monkeypatch.setattr(get_settings(), "auth_login_rate_limit", 2)
    monkeypatch.setattr(get_settings(), "auth_ip_rate_multiplier", 1)
    assert await enforce_auth_rate_limit(BrokenDB(), "login", "5.5.5.5", "x@example.com") == 0.0
    assert await enforce_auth_rate_limit(BrokenDB(), "login", "5.5.5.5", "x@example.com") == 0.0
    assert await enforce_auth_rate_limit(BrokenDB(), "login", "5.5.5.5", "x@example.com") > 0


async def test_shared_layer_can_be_disabled(test_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "shared_rate_limit_enabled", False)
    await enforce_user_rate_limit(test_db, "expensive", "u")
    assert [doc async for doc in test_db[rate_limit.SHARED_COLLECTION].find({})] == []


# ------------------------------------------------------- in-process store hygiene


def test_sweeping_uses_each_keys_own_window():
    """A short-window check must not evict a still-live long-window counter (the old
    sweep judged every key by the *calling* request's window)."""
    limiter = RateLimiter()
    limiter.check("register:ip:1.1.1.1", limit=1, window_seconds=3600)
    limiter._last_sweep = time.monotonic() - 10_000  # force a sweep on the next check
    limiter.check("login:ip:2.2.2.2", limit=5, window_seconds=1)
    assert "register:ip:1.1.1.1" in limiter._hits
    assert limiter.check("register:ip:1.1.1.1", limit=1, window_seconds=3600) > 0


def test_expired_keys_are_swept_and_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(rate_limit, "_MAX_KEYS", 20)
    limiter = RateLimiter()
    for i in range(200):  # a flood of distinct, attacker-chosen keys
        limiter.check(f"login:email:{i}@example.com", limit=5, window_seconds=3600)
    assert len(limiter._hits) <= 40
    assert set(limiter._hits) == set(limiter._expires)


def test_undo_forgets_the_last_hit():
    limiter = RateLimiter()
    assert limiter.check("k", limit=1, window_seconds=60) == 0.0
    limiter.undo("k")
    assert limiter.check("k", limit=1, window_seconds=60) == 0.0


@pytest.mark.parametrize("limit", [1, 3])
def test_limiter_allows_exactly_limit_hits(limit):
    limiter = RateLimiter()
    results = [limiter.check("k", limit=limit, window_seconds=60) for _ in range(limit + 1)]
    assert results[:limit] == [0.0] * limit and results[limit] > 0
