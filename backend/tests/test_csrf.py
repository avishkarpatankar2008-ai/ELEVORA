"""Origin/Referer (CSRF) protection for cookie-authenticated, state-changing requests."""

import pytest

from app.config import get_settings
from app.core.csrf import rejection_reason

TRUSTED = frozenset({"https://app.example.com"})
COOKIE = "elevora_session"


def reason(method="POST", **headers):
    return rejection_reason(
        method=method,
        headers={k.replace("_", "-"): v for k, v in headers.items()},
        trusted_origins=TRUSTED,
        cookie_name=COOKIE,
    )


# ----------------------------------------------------------------- pure function


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_are_never_blocked(method):
    assert reason(method, origin="https://evil.example", cookie=f"{COOKIE}=x") is None


def test_trusted_origin_is_allowed_and_case_and_slash_insensitive():
    assert reason(origin="https://app.example.com") is None
    assert reason(origin="HTTPS://APP.EXAMPLE.COM/") is None


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "null", "http://app.example.com", "https://app.example.com.evil.example"],
)
def test_untrusted_origins_are_blocked_even_without_a_session_cookie(origin):
    # Without a cookie this is "login CSRF": making a victim sign in as the attacker.
    assert reason(origin=origin) == "origin_not_allowed"


def test_referer_is_used_when_origin_is_missing():
    assert reason(referer="https://app.example.com/interviews/1") is None
    assert reason(referer="https://evil.example/page") == "referer_not_allowed"


def test_cross_site_fetch_metadata_is_blocked_when_no_origin_or_referer():
    assert reason(sec_fetch_site="cross-site") == "fetch_site_not_allowed"
    assert reason(sec_fetch_site="same-site") == "fetch_site_not_allowed"
    assert reason(sec_fetch_site="same-origin", cookie=f"{COOKIE}=x") is None


def test_cookie_without_any_origin_signal_needs_a_declared_client():
    cookie = f"theme=dark; {COOKIE}=abc"
    assert reason(cookie=cookie) == "missing_origin_information"
    assert reason(cookie=cookie, x_requested_with="elevora") is None


def test_cookieless_non_browser_requests_pass():
    assert reason() is None  # nothing ambient to forge


def test_other_cookies_do_not_count_as_a_session():
    assert reason(cookie="theme=dark") is None


# ----------------------------------------------------------------- through the app


async def test_login_from_untrusted_origin_is_refused(client, user_payload):
    await client.post("/auth/register", json=user_payload)
    client.cookies.clear()
    resp = await client.post(
        "/auth/login",
        json={"email": user_payload["email"], "password": user_payload["password"]},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert "allowed origin" in resp.json()["detail"]
    assert "set-cookie" not in resp.headers


async def test_state_change_with_session_cookie_from_untrusted_origin_is_refused(client, user_payload):
    await client.post("/auth/register", json=user_payload)
    forged = await client.patch(
        "/auth/me", json={"name": "Hijacked"}, headers={"Origin": "https://evil.example"}
    )
    assert forged.status_code == 403
    assert (await client.get("/auth/me")).json()["name"] == user_payload["name"]


async def test_trusted_origin_state_change_succeeds(client, user_payload):
    await client.post("/auth/register", json=user_payload)
    ok = await client.patch("/auth/me", json={"name": "Ada L."})
    assert ok.status_code == 200 and ok.json()["name"] == "Ada L."


async def test_cookie_request_without_origin_info_is_refused_unless_declared(client, user_payload):
    await client.post("/auth/register", json=user_payload)
    del client.headers["origin"]
    refused = await client.patch("/auth/me", json={"name": "No Origin"})
    assert refused.status_code == 403
    declared = await client.patch(
        "/auth/me", json={"name": "Scripted"}, headers={"X-Requested-With": "elevora"}
    )
    assert declared.status_code == 200


async def test_reads_are_unaffected_by_the_origin_check(client, user_payload):
    await client.post("/auth/register", json=user_payload)
    resp = await client.get("/auth/me", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200


async def test_logout_is_protected_too(client, user_payload):
    await client.post("/auth/register", json=user_payload)
    forged = await client.post("/auth/logout", headers={"Origin": "https://evil.example"})
    assert forged.status_code == 403
    assert (await client.get("/auth/me")).status_code == 200  # still signed in


def test_development_trusts_loopback_aliases_but_production_only_the_frontend():
    from app.config import Settings

    dev = Settings(env="development")
    assert "http://127.0.0.1:3000" in dev.trusted_origins
    assert "http://localhost:3000" in dev.trusted_origins

    prod = Settings(
        env="production",
        jwt_secret="a8f3c1d9e7b24f60918d5c3a7e2b4d1f",
        frontend_origin="https://app.example.com",
    )
    assert prod.trusted_origins == ["https://app.example.com"]
    assert get_settings().frontend_origin  # sanity: tests run with a configured origin
