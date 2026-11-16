"""Origin / Referer verification for state-changing requests (pure ASGI).

Why this exists
---------------
Authentication is an HTTP-only session cookie, which browsers attach to *any*
request to this API — including ones triggered by another site. ``SameSite=Lax``
(the default here) already stops most cross-site POSTs, but it is a single
browser-side control, it is weaker for same-site sibling domains, and it is
simply off when a deployment needs ``SameSite=None``. This middleware adds a
server-side check that does not depend on cookie attributes.

What it enforces (POST/PUT/PATCH/DELETE only; reads and CORS preflights pass)
-------------------------------------------------------------------------
1. If the browser sent ``Origin``, it must be one of the trusted origins
   (``Settings.trusted_origins``). ``Origin: null`` and every other site are
   refused. This is applied even before login, which also blocks "login CSRF".
2. Otherwise, if it sent ``Referer``, that URL's origin must be trusted.
3. With neither header, ``Sec-Fetch-Site`` (when present) must say
   ``same-origin`` or ``none``. A request that carries the session cookie and
   no browser-origin signal at all must declare itself with an
   ``X-Requested-With`` header, which a cross-site page cannot add without a
   CORS preflight that this API's CORS policy refuses.

Browsers always attach ``Origin`` to cross-origin unsafe requests, so a forged
request cannot dodge rule 1 by omitting it. Non-browser clients (curl, test
suites) have no ambient cookie to abuse and can pass rule 3 explicitly.

Deliberately *not* a token scheme: a double-submit token would need a
JS-readable cookie, which does not exist when the API is on another origin than
the frontend. Origin verification works identically for the same-origin proxy
and for a split deployment.
"""

import json
from typing import Mapping
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

REJECTION_DETAIL = (
    "This request was blocked because it didn't come from an allowed origin. "
    "If you host ELEVORA yourself, make sure FRONTEND_ORIGIN matches the address "
    "shown in your browser."
)


def _normalize_origin(value: str) -> str:
    return value.strip().rstrip("/").lower()


def origin_of(url: str) -> str | None:
    """``https://app.example.com/path?x`` -> ``https://app.example.com``."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def _has_cookie(cookie_header: str, cookie_name: str) -> bool:
    prefix = f"{cookie_name}="
    return any(part.strip().startswith(prefix) for part in cookie_header.split(";"))


def rejection_reason(
    *,
    method: str,
    headers: Mapping[str, str],
    trusted_origins: frozenset[str],
    cookie_name: str,
) -> str | None:
    """Why a request must be refused, or None when it may proceed.

    ``headers`` must have lower-case names. Pure function: unit-testable without
    an ASGI stack.
    """
    if method.upper() in SAFE_METHODS:
        return None

    origin = headers.get("origin")
    if origin is not None:
        if _normalize_origin(origin) in trusted_origins:
            return None
        return "origin_not_allowed"

    referer = headers.get("referer")
    if referer:
        if origin_of(referer) in trusted_origins:
            return None
        return "referer_not_allowed"

    fetch_site = headers.get("sec-fetch-site")
    if fetch_site and fetch_site.strip().lower() not in {"same-origin", "none"}:
        return "fetch_site_not_allowed"

    has_session = _has_cookie(headers.get("cookie", ""), cookie_name)
    if has_session and not fetch_site and not headers.get("x-requested-with"):
        return "missing_origin_information"
    return None


class CSRFOriginMiddleware:
    def __init__(self, app: ASGIApp, *, trusted_origins: list[str], cookie_name: str) -> None:
        self.app = app
        self.trusted_origins = frozenset(_normalize_origin(o) for o in trusted_origins if o)
        self.cookie_name = cookie_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET").upper() in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers: dict[str, str] = {}
        for raw_name, raw_value in scope.get("headers", []):
            name = raw_name.decode("latin-1").lower()
            headers.setdefault(name, raw_value.decode("latin-1"))

        reason = rejection_reason(
            method=scope.get("method", "POST"),
            headers=headers,
            trusted_origins=self.trusted_origins,
            cookie_name=self.cookie_name,
        )
        if reason is None:
            await self.app(scope, receive, send)
            return

        body = json.dumps({"detail": REJECTION_DETAIL}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
