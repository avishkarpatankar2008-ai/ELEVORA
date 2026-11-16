"""Streamed request-body size limiting (pure ASGI).

The previous guard only looked at the ``Content-Length`` header, which a client
can omit (chunked transfer) or lie about. This middleware also counts the bytes
as they actually arrive and aborts with 413 the moment the limit is crossed, so
an oversized upload is never buffered or spooled to disk past the limit.

It is deliberately not a ``BaseHTTPMiddleware``: those cannot wrap the receive
channel. Raising ``HTTPException`` from the wrapped ``receive`` lets FastAPI's
own body-parsing re-raise it untouched (it converts other exceptions to 400) and
the normal exception handler turn it into the JSON 413 response.
"""

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

# Slack on top of the file-size limit for multipart boundaries and form fields.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def _header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value
    return None


class RequestSizeLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_request_bytes: int,
        max_json_body_bytes: int,
        max_document_upload_bytes: int,
        max_audio_upload_bytes: int,
    ) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes
        self.max_json_body_bytes = max_json_body_bytes
        self.max_document_upload_bytes = max_document_upload_bytes
        self.max_audio_upload_bytes = max_audio_upload_bytes

    def _limit_for(self, scope: Scope) -> int:
        path: str = scope.get("path", "")
        content_type = (_header(scope, b"content-type") or b"").decode("latin-1").lower()
        if not content_type.startswith("multipart/"):
            return min(self.max_json_body_bytes, self.max_request_bytes)
        if path.endswith("/answer/audio"):
            limit = self.max_audio_upload_bytes + MULTIPART_OVERHEAD_BYTES
        elif path.endswith(("/resume", "/job-description")):
            limit = self.max_document_upload_bytes + MULTIPART_OVERHEAD_BYTES
        else:
            limit = self.max_request_bytes
        return min(limit, self.max_request_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope)
        too_large = HTTPException(status_code=413, detail="That upload is too large.")

        declared = _header(scope, b"content-length")
        if declared is not None:
            if not declared.isdigit():
                await self.app(scope, _reject_with(HTTPException(400, "Invalid Content-Length.")), send)
                return
            if int(declared) > limit:
                await self.app(scope, _reject_with(too_large), send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise too_large
            return message

        await self.app(scope, limited_receive, send)


def _reject_with(exc: HTTPException) -> Receive:
    async def receive():
        raise exc

    return receive
