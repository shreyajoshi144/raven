from __future__ import annotations

import re
import time
import uuid
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.logging import log, request_id_var
from app.core.metrics import metrics

logger = logging.getLogger("raven.http")
_RID = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'self'")


class RequestContextMiddleware:
    """Request ID, body size cap, security headers and access logging (pure ASGI to cap streamed bodies)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        s = get_settings()
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        rid = headers.get("x-request-id", "")
        rid = rid if _RID.match(rid) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        scope.setdefault("state", {})["request_id"] = rid
        start = time.monotonic()
        status_holder = {"status": 0}
        limit = s.max_request_bytes

        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await self._reject(send, rid, 413, "PAYLOAD_TOO_LARGE")
            request_id_var.reset(token)
            return

        received = {"n": 0}

        async def limited_receive() -> Message:
            msg = await receive()
            if msg["type"] == "http.request":
                received["n"] += len(msg.get("body", b""))
                if received["n"] > limit:
                    raise _TooLarge()
            return msg

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                hdrs = list(message.get("headers", []))
                extra = {
                    "x-request-id": rid, "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
                    "x-frame-options": "DENY", "x-permitted-cross-domain-policies": "none", "cross-origin-resource-policy": "same-origin",
                    "permissions-policy": "geolocation=(), microphone=(), camera=(), payment=(), usb=(), serial=(), bluetooth=(), interest-cohort=()",
                    "content-security-policy": CSP, "cross-origin-opener-policy": "same-origin",
                }
                path = scope.get("path", "")
                if path.startswith(("/api/", "/internal/")):
                    extra["cache-control"] = "no-store"
                if s.is_production:
                    extra["strict-transport-security"] = "max-age=31536000; includeSubDomains"
                have = {k.lower() for k, _ in hdrs}
                for k, v in extra.items():
                    if k.encode() not in have:
                        hdrs.append((k.encode(), v.encode()))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _TooLarge:
            await self._reject(send, rid, 413, "PAYLOAD_TOO_LARGE")
            status_holder["status"] = 413
        finally:
            metrics.record(scope.get("path", ""), status_holder["status"], (time.monotonic() - start) * 1000)
            log(logger, "request", method=scope["method"], path=scope.get("path"), status=status_holder["status"],
                duration_ms=round((time.monotonic() - start) * 1000, 1))
            request_id_var.reset(token)

    @staticmethod
    async def _reject(send: Send, rid: str, status: int, code: str) -> None:
        from app.core.errors import info
        import json
        meta = info(code)
        body = json.dumps({"error": {"code": code, "message": meta.message, "request_id": rid, "retryable": meta.retryable}}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"), (b"x-request-id", rid.encode()), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass
