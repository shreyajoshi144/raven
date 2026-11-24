"""Client for n8n. n8n is called through authenticated webhooks only; it calls back via /internal APIs."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.logging import log, request_id_var

logger = logging.getLogger("raven.orchestrator")

WEBHOOK_PATHS = {
    "raven_repository_analysis": "raven-analysis",
    "raven_documentation_generation": "raven-docs",
    "raven_codebase_qa": "raven-qa",
}


class Orchestrator:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
        self.s = settings or get_settings()
        self._transport = transport

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self.s.n8n_base_url.rstrip("/"), timeout=httpx.Timeout(timeout, connect=3.0),
                            transport=self._transport)

    def _headers(self) -> dict[str, str]:
        return {"X-Raven-Webhook-Secret": self.s.n8n_webhook_secret, "X-Request-ID": request_id_var.get() or uuid.uuid4().hex,
                "Content-Type": "application/json"}

    def trigger(self, workflow: str, payload: dict[str, Any]) -> bool:
        """Fire-and-forget start of an orchestration workflow. Returns True when n8n accepted the call."""
        path = WEBHOOK_PATHS[workflow]
        try:
            with self._client(self.s.n8n_trigger_timeout_seconds) as c:
                r = c.post(f"/webhook/{path}", json=payload, headers=self._headers())
            ok = 200 <= r.status_code < 300
            log(logger, "workflow_trigger", logging.INFO if ok else logging.WARNING, workflow=workflow, status=r.status_code)
            return ok
        except httpx.HTTPError as exc:
            log(logger, "workflow_trigger_failed", logging.WARNING, workflow=workflow, error_type=type(exc).__name__)
            return False

    def run_qa(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronous Q&A orchestration (webhook responds when the workflow finishes)."""
        try:
            with self._client(self.s.qa_workflow_timeout_seconds) as c:
                r = c.post(f"/webhook/{WEBHOOK_PATHS['raven_codebase_qa']}", json=payload, headers=self._headers())
        except httpx.TimeoutException:
            raise ApiError("WORKFLOW_TIMEOUT") from None
        except httpx.HTTPError:
            raise ApiError("WORKFLOW_UNAVAILABLE") from None
        if r.status_code in (401, 403):
            raise ApiError("WORKFLOW_UNAVAILABLE", "The automation service rejected the request. Check webhook secret configuration.")
        if r.status_code == 404:
            raise ApiError("WORKFLOW_UNAVAILABLE", "The Q&A workflow is not active in n8n.")
        if r.status_code >= 400:
            raise ApiError("WORKFLOW_FAILED")
        try:
            data = r.json()
        except ValueError:
            raise ApiError("WORKFLOW_FAILED") from None
        if not isinstance(data, dict):
            raise ApiError("WORKFLOW_FAILED")
        return data

    def health(self) -> dict[str, Any]:
        try:
            with self._client(3.0) as c:
                r = c.get("/healthz")
            return {"reachable": r.status_code == 200}
        except httpx.HTTPError:
            return {"reachable": False}
