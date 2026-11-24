"""Backend-owned job state machine. Browsers never set state; every transition is persisted."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, info
from app.models import AnalysisJob, AnalysisTransition, utcnow

PIPELINE = ["QUEUED", "FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS", "READY"]
ACTIVE = {"QUEUED", "FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS", "RETRYING"}
TERMINAL = {"READY", "FAILED", "CANCELLED"}

LEGAL: dict[str, set[str]] = {
    "QUEUED": {"FETCHING", "FAILED", "CANCELLED"},
    "FETCHING": {"PARSING", "RETRYING", "FAILED", "CANCELLED"},
    "PARSING": {"BUILDING_GRAPH", "RETRYING", "FAILED", "CANCELLED", "FETCHING"},  # FETCHING: crash recovery re-entry
    "BUILDING_GRAPH": {"GENERATING_DOCS", "RETRYING", "FAILED", "CANCELLED", "FETCHING"},  # FETCHING: crash recovery re-entry
    "GENERATING_DOCS": {"READY", "RETRYING", "FAILED", "CANCELLED"},
    "RETRYING": {"FETCHING", "GENERATING_DOCS", "FAILED", "CANCELLED"},
    "FAILED": {"QUEUED"},
    "READY": set(),
    "CANCELLED": set(),
}


class IllegalTransition(ApiError):
    def __init__(self, src: str, dst: str):
        super().__init__("INVALID_STATE", f"Illegal transition {src} -> {dst}.")


def lock_job(db: Session, analysis_id: uuid.UUID) -> AnalysisJob | None:
    return db.execute(
        select(AnalysisJob).where(AnalysisJob.id == analysis_id).with_for_update(of=AnalysisJob)
    ).scalar_one_or_none()


def transition(db: Session, job: AnalysisJob, to_state: str, *, actor: str, error_code: str | None = None,
               note: str | None = None, detail: str | None = None, progress: dict[str, Any] | None = None) -> None:
    """Apply a legal transition (caller should hold the row lock) and persist an audit row."""
    src = job.state
    if to_state not in LEGAL.get(src, set()):
        raise IllegalTransition(src, to_state)
    now = utcnow()
    job.state = to_state
    job.stage_detail = detail
    job.updated_at = now
    if progress:
        job.progress = {**(job.progress or {}), **progress}
    if to_state == "FETCHING" and job.started_at is None:
        job.started_at = now
    if to_state == "QUEUED":
        job.finished_at = None
        job.error_code = job.error_message = job.failed_state = None
        job.error_retryable = False
        job.retry_after = None
    if to_state in TERMINAL:
        job.finished_at = now
    if to_state in {"FAILED", "RETRYING"}:
        meta = info(error_code or "INTERNAL_ANALYSIS_ERROR")
        job.error_code = meta.code
        job.error_message = meta.message
        job.error_retryable = meta.retryable
        job.failed_state = src if src != "RETRYING" else job.failed_state
    if to_state in {"READY", "FETCHING", "GENERATING_DOCS"} and src == "RETRYING":
        job.error_code = job.error_message = None
        job.retry_after = None
    if to_state == "READY":
        job.error_code = job.error_message = job.failed_state = None
        job.error_retryable = False
    db.add(AnalysisTransition(analysis_id=job.id, from_state=src, to_state=to_state, actor=actor,
                              error_code=error_code, note=(note or "")[:200] or None))
    db.flush()


def reopen_ready(db: Session, job: AnalysisJob, *, actor: str, note: str) -> None:
    """The one sanctioned way out of READY: an owner-requested full reindex. READY stays terminal in LEGAL for every other path."""
    if job.state != "READY":
        raise IllegalTransition(job.state, "QUEUED")
    job.state, job.stage_detail, job.updated_at, job.finished_at = "QUEUED", None, utcnow(), None
    db.add(AnalysisTransition(analysis_id=job.id, from_state="READY", to_state="QUEUED", actor=actor, note=note[:200]))
    db.flush()


def update_progress(db: Session, job: AnalysisJob, **counters: Any) -> None:
    job.progress = {**(job.progress or {}), **counters}
    job.updated_at = utcnow()
    db.flush()
