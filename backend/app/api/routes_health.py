from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import orchestrator_dep
from app.core.db import get_engine
from app.services.orchestrator import Orchestrator

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> JSONResponse:
    """Readiness covers required dependencies only (PostgreSQL + applied migrations). n8n is checked separately."""
    checks = {"database": False, "migrations": False}
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
            checks["database"] = True
            row = c.execute(text("SELECT version_num FROM alembic_version")).first()
            checks["migrations"] = row is not None
    except Exception:  # noqa: BLE001
        pass
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not_ready", "checks": checks})


@router.get("/health/orchestrator")
def orchestrator_health(orch: Orchestrator = Depends(orchestrator_dep)) -> JSONResponse:
    h = orch.health()
    return JSONResponse(status_code=200 if h["reachable"] else 503, content={"status": "ok" if h["reachable"] else "unreachable", **h})
