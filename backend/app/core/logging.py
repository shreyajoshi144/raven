"""Structured JSON logging with request/analysis correlation and secret redaction."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
analysis_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("analysis_id", default=None)
workflow_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("workflow", default=None)
execution_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("execution_id", default=None)
stage_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("stage", default=None)

_SENSITIVE_KEY = re.compile(r"(authorization|password|secret|token|api[_-]?key|cookie|prompt)", re.I)
_TOKENISH = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._\-]{16,})"
)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return _TOKENISH.sub("[REDACTED]", value)[:2000]
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SENSITIVE_KEY.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value][:50]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": request_id_var.get(),
            "analysis_id": analysis_id_var.get(),
            "workflow": workflow_var.get(),
            "execution_id": execution_id_var.get(),
            "stage": stage_var.get(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(redact(extra))
        if record.exc_info and record.exc_info[0]:
            # Exception type only; tracebacks may contain prompts or source text.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps({k: v for k, v in payload.items() if v is not None}, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})
