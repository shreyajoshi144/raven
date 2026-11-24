"""Job lifecycle: submission, retry/cancel/delete, queue operations and the internal (n8n) contract."""
from __future__ import annotations

import logging
import random
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.graph import ANALYZER_VERSION
from app.analysis.urls import parse_github_url
from app.core.config import Settings, get_settings
from app.core.errors import ApiError, JobError, info
from app.models import (
    AnalysisJob, AnalysisTransition, AuditEvent, CallbackReceipt, Documentation, Repository, User, WorkerTask, WorkflowRun, utcnow,
)
from app.services.github import GitHubClient
from app.services.orchestrator import Orchestrator
from app.services.security import rate_limit
from app.services.state import ACTIVE, TERMINAL, lock_job, reopen_ready, transition

logger = logging.getLogger("raven.jobs")

FAIL_CODES_FROM_N8N = {"WORKFLOW_TIMEOUT", "WORKFLOW_FAILED", "ORCHESTRATOR_UNAVAILABLE", "RETRIES_EXHAUSTED", "WORKER_LOST"}
USER_RETRYABLE_EXTRA = {"ANALYSIS_TIMEOUT"}


def audit(db: Session, action: str, *, actor: User | None = None, actor_kind: str = "user", resource_type: str | None = None,
          resource_id: Any = None, request_id: str | None = None, **meta: Any) -> None:
    db.add(AuditEvent(actor_id=actor.id if actor else None, actor_kind=actor_kind, action=action, resource_type=resource_type,
                      resource_id=str(resource_id) if resource_id else None, request_id=request_id, meta=meta))


def get_owned_job(db: Session, user: User, analysis_id: uuid.UUID) -> AnalysisJob:
    """Ownership check used by every analysis endpoint. Returns 404 (not 403) to avoid existence leaks."""
    job = db.get(AnalysisJob, analysis_id)
    if job is None or job.owner_id != user.id:
        raise ApiError("NOT_FOUND", "Analysis not found.")
    return job


# --------------------------------------------------------------------------- submission
def submit_analysis(db: Session, user: User, url: str, github: GitHubClient, settings: Settings | None = None,
                    request_id: str | None = None, sha: str | None = None) -> tuple[AnalysisJob, bool]:
    """Validate, pin to a commit SHA and create (or reuse) an analysis. Returns (job, created)."""
    s = settings or get_settings()
    ref = parse_github_url(url)
    rate_limit(db, "analysis_submit", str(user.id), s.analyses_per_hour, 3600)
    try:
        meta = github.get_repo(ref)
        if sha is None:
            sha = github.get_head_sha(meta.owner, meta.name, meta.default_branch)
        else:  # explicit commit (pull request base/head): must exist in this repository
            github.get_parent_sha(meta.owner, meta.name, sha)
    except JobError as exc:
        db.rollback()
        mi = info(exc.code)
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else {}
        raise ApiError(exc.code, mi.message, headers=headers) from None
    if meta.size_kb and meta.size_kb > 2_000_000:
        raise ApiError("REPO_TOO_LARGE")

    repo = db.execute(select(Repository).where(Repository.provider == "github",
                                               Repository.full_name_lower == meta.full_name.lower())).scalar_one_or_none()
    if repo is None:
        repo = Repository(provider="github", owner=meta.owner, name=meta.name, full_name=meta.full_name,
                          full_name_lower=meta.full_name.lower(), canonical_url=f"https://github.com/{meta.full_name}",
                          default_branch=meta.default_branch)
        db.add(repo)
    repo.default_branch = meta.default_branch
    repo.description = (meta.description or "")[:500] or None
    repo.primary_language = meta.language
    repo.size_kb = meta.size_kb
    repo.stars = meta.stars
    db.flush()

    existing = db.execute(select(AnalysisJob).where(
        AnalysisJob.owner_id == user.id, AnalysisJob.repository_id == repo.id, AnalysisJob.commit_sha == sha,
        AnalysisJob.analyzer_version == ANALYZER_VERSION, AnalysisJob.state != "CANCELLED")).scalar_one_or_none()
    if existing:
        audit(db, "analysis.reuse", actor=user, resource_type="analysis", resource_id=existing.id, request_id=request_id)
        return existing, False

    job = AnalysisJob(owner_id=user.id, repository_id=repo.id, commit_sha=sha, default_branch=meta.default_branch,
                      analyzer_version=ANALYZER_VERSION, state="QUEUED", progress={}, summary={},
                      idempotency_key=f"{user.id}:{repo.id}:{sha}:{ANALYZER_VERSION}:{uuid.uuid4().hex[:8]}")
    db.add(job)
    try:
        db.flush()
    except IntegrityError:  # concurrent duplicate submission: return the winner
        db.rollback()
        winner = db.execute(select(AnalysisJob).where(
            AnalysisJob.owner_id == user.id, AnalysisJob.repository_id == repo.id, AnalysisJob.commit_sha == sha,
            AnalysisJob.analyzer_version == ANALYZER_VERSION, AnalysisJob.state != "CANCELLED")).scalar_one()
        return winner, False
    db.add(AnalysisTransition(analysis_id=job.id, from_state=None, to_state="QUEUED", actor="api", note="submitted"))
    audit(db, "analysis.create", actor=user, resource_type="analysis", resource_id=job.id, request_id=request_id,
          repository=meta.full_name, commit=sha)
    return job, True


def trigger_analysis(db: Session, job: AnalysisJob, orch: Orchestrator) -> bool:
    """Ask n8n to start the analysis workflow. Safe to call repeatedly (dispatch is idempotent)."""
    ok = orch.trigger("raven_repository_analysis", {"analysis_id": str(job.id), "attempt": job.attempt})
    job.trigger_attempts = (job.trigger_attempts or 0) + 1
    job.last_triggered_at = utcnow()
    return ok


def trigger_docs(db: Session, doc: Documentation, orch: Orchestrator) -> bool:
    ok = orch.trigger("raven_documentation_generation", {"analysis_id": str(doc.analysis_id), "doc_id": str(doc.id)})
    doc.trigger_attempts = (doc.trigger_attempts or 0) + 1
    doc.last_triggered_at = utcnow()
    return ok


# --------------------------------------------------------------------------- user actions
def retry_analysis(db: Session, user: User, job: AnalysisJob) -> AnalysisJob:
    locked = lock_job(db, job.id)
    assert locked is not None
    job = locked
    if job.state != "FAILED":
        raise ApiError("INVALID_STATE", "Only failed analyses can be retried.")
    if not (job.error_retryable or job.error_code in USER_RETRYABLE_EXTRA):
        raise ApiError("INVALID_STATE", "This failure is not retryable without changing the input.")
    job.attempt = 0
    job.trigger_attempts = 0
    job.cancel_requested = False
    transition(db, job, "QUEUED", actor="api", note="user retry")
    audit(db, "analysis.retry", actor=user, resource_type="analysis", resource_id=job.id)
    return job


def reindex_analysis(db: Session, user: User, job: AnalysisJob) -> AnalysisJob:
    """Recovery option: re-fetch and rebuild this analysis from scratch (no reuse of any earlier analysis's facts or vectors).
    Allowed for READY or FAILED analyses; answers already given stay attached to the same pinned commit."""
    locked = lock_job(db, job.id)
    assert locked is not None
    job = locked
    if job.state not in {"READY", "FAILED"}:
        raise ApiError("INVALID_STATE", "Only finished analyses can be reindexed.")
    job.summary = {**(job.summary or {}), "force_full": True}
    job.graph_complete = False
    job.attempt = 0
    job.trigger_attempts = 0
    job.cancel_requested = False
    if job.state == "READY":
        reopen_ready(db, job, actor="api", note="full reindex")
    else:
        transition(db, job, "QUEUED", actor="api", note="full reindex")
    audit(db, "analysis.reindex", actor=user, resource_type="analysis", resource_id=job.id)
    return job


def cancel_analysis(db: Session, user: User, job: AnalysisJob) -> AnalysisJob:
    locked = lock_job(db, job.id)
    assert locked is not None
    job = locked
    if job.state in TERMINAL:
        raise ApiError("INVALID_STATE", "This analysis has already finished.")
    if job.state in {"QUEUED", "RETRYING"}:
        transition(db, job, "CANCELLED", actor="api", note="user cancelled")
    else:
        job.cancel_requested = True  # honoured by the worker between stages
    audit(db, "analysis.cancel", actor=user, resource_type="analysis", resource_id=job.id)
    return job


def delete_analysis(db: Session, user: User, job: AnalysisJob) -> None:
    audit(db, "analysis.delete", actor=user, resource_type="analysis", resource_id=job.id)
    db.delete(job)  # ON DELETE CASCADE removes files, nodes, edges, docs, chat, runs, tasks, receipts
    db.flush()


def request_docs(db: Session, user: User, job: AnalysisJob, orch: Orchestrator) -> Documentation:
    locked = lock_job(db, job.id)
    assert locked is not None
    job = locked
    if job.state != "READY" or not job.graph_complete:
        raise ApiError("INVALID_STATE", "Documentation can be regenerated once the analysis is ready.")
    pending = db.execute(select(Documentation).where(
        Documentation.analysis_id == job.id, Documentation.status.in_(("PENDING", "GENERATING")))).scalars().first()
    if pending:
        return pending
    rate_limit(db, "docs_generate", str(user.id), 10, 3600)
    version = (db.execute(select(func.max(Documentation.version)).where(Documentation.analysis_id == job.id)).scalar() or 0) + 1
    doc = Documentation(analysis_id=job.id, version=version, status="PENDING", ai_status="pending",
                        idempotency_key=f"{job.id}:docs:{version}")
    db.add(doc)
    db.flush()
    audit(db, "docs.generate", actor=user, resource_type="analysis", resource_id=job.id, version=version)
    return doc


# --------------------------------------------------------------------------- queue
def enqueue_task(db: Session, analysis_id: uuid.UUID, task_type: str, key: str, payload: dict[str, Any] | None = None) -> WorkerTask:
    stmt = pg_insert(WorkerTask).values(id=uuid.uuid4(), analysis_id=analysis_id, task_type=task_type, idempotency_key=key,
                                        status="pending", payload=payload or {}, attempts=0, created_at=utcnow(), updated_at=utcnow())
    stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])
    db.execute(stmt)
    return db.execute(select(WorkerTask).where(WorkerTask.idempotency_key == key)).scalar_one()


def backoff_seconds(attempt: int, s: Settings | None = None, rng: random.Random | None = None) -> float:
    """Bounded exponential backoff with full-ish jitter."""
    s = s or get_settings()
    r = rng or random
    base = min(s.retry_max_seconds, s.retry_base_seconds * (2 ** max(0, attempt)))
    return round(base * r.uniform(0.5, 1.0), 2)


# --------------------------------------------------------------------------- internal contract
def _receipt_key(analysis_id: uuid.UUID, key: str) -> str:
    # n8n execution ids are reused after its data is reset, so a bare "<exec>:dispatch:0:0" key can replay another analysis's receipt
    return f"{analysis_id}:{key}"


def _receipt(db: Session, analysis_id: uuid.UUID, key: str | None) -> dict[str, Any] | None:
    if not key:
        return None
    rec = db.get(CallbackReceipt, _receipt_key(analysis_id, key))
    return dict(rec.response, duplicate=True) if rec else None


def _store_receipt(db: Session, key: str | None, analysis_id: uuid.UUID, endpoint: str, response: dict[str, Any]) -> None:
    if key:
        stmt = pg_insert(CallbackReceipt).values(key=_receipt_key(analysis_id, key), analysis_id=analysis_id, endpoint=endpoint, response=response, created_at=utcnow())
        db.execute(stmt.on_conflict_do_nothing(index_elements=["key"]))


def _record_run(db: Session, analysis_id: uuid.UUID, workflow: str, execution_id: str, stage: str, status: str = "running",
                error_code: str | None = None) -> None:
    stmt = pg_insert(WorkflowRun).values(id=uuid.uuid4(), analysis_id=analysis_id, workflow_name=workflow, n8n_execution_id=execution_id,
                                         stage=stage, status=status, error_code=error_code, started_at=utcnow())
    stmt = stmt.on_conflict_do_update(constraint="uq_workflow_run", set_={"stage": stage, "status": status, "error_code": error_code,
                                                                          "finished_at": utcnow() if status != "running" else None})
    db.execute(stmt)


def _load(db: Session, analysis_id: uuid.UUID) -> AnalysisJob:
    job = lock_job(db, analysis_id)
    if job is None:
        raise ApiError("NOT_FOUND", "Analysis not found.")
    return job


def internal_status(db: Session, analysis_id: uuid.UUID, s: Settings | None = None, doc_id: uuid.UUID | None = None) -> dict[str, Any]:
    s = s or get_settings()
    job = db.get(AnalysisJob, analysis_id)
    if job is None:
        raise ApiError("NOT_FOUND", "Analysis not found.")
    doc = db.execute(select(Documentation).where(Documentation.analysis_id == job.id).order_by(Documentation.version.desc())).scalars().first()
    retry_in = None
    if job.state == "RETRYING" and job.retry_after:
        retry_in = max(0.0, (job.retry_after - utcnow()).total_seconds())
    doc_tasks: dict[str, str] = {}
    if doc_id is not None:
        for t in db.execute(select(WorkerTask).where(WorkerTask.analysis_id == job.id, WorkerTask.task_type.in_(("docs_explain", "docs_assemble")))
                            .order_by(WorkerTask.created_at)).scalars():
            if t.payload.get("doc_id") == str(doc_id):
                doc_tasks[t.task_type] = t.status
    return {
        "doc_tasks": doc_tasks,
        "analysis_id": str(job.id), "state": job.state, "attempt": job.attempt, "max_attempts": s.max_stage_attempts,
        "graph_complete": job.graph_complete, "error_code": job.error_code, "error_retryable": job.error_retryable,
        "failed_state": job.failed_state, "retry_in_seconds": retry_in, "cancel_requested": job.cancel_requested,
        "docs": {"id": str(doc.id), "status": doc.status, "version": doc.version, "ai_status": doc.ai_status} if doc else None,
        "terminal": job.state in TERMINAL,
    }


def internal_dispatch(db: Session, analysis_id: uuid.UUID, *, kind: str, workflow: str, execution_id: str,
                      idempotency_key: str | None, doc_id: uuid.UUID | None = None, s: Settings | None = None) -> dict[str, Any]:
    s = s or get_settings()
    if (dup := _receipt(db, analysis_id, idempotency_key)) is not None:
        return dup
    job = _load(db, analysis_id)
    _record_run(db, job.id, workflow, execution_id, kind)
    if kind == "analysis":
        if job.cancel_requested:
            raise ApiError("INVALID_STATE", "Analysis was cancelled.")
        if job.state == "RETRYING":
            if job.failed_state == "GENERATING_DOCS":
                raise ApiError("INVALID_STATE", "Docs-stage retries are dispatched with a documentation kind.")
            if job.attempt + 1 >= s.max_stage_attempts + 1:
                raise ApiError("INVALID_STATE", "Retry limit reached.")
            job.attempt += 1
            transition(db, job, "FETCHING", actor="n8n", note=f"retry attempt {job.attempt}", detail="fetching")
        elif job.state == "QUEUED":
            transition(db, job, "FETCHING", actor="n8n", detail="fetching")
        elif job.state != "FETCHING":
            raise ApiError("INVALID_STATE", f"Cannot dispatch analysis from state {job.state}.")
        job.dispatched_at = utcnow()
        generation = db.execute(select(func.count()).select_from(AnalysisTransition).where(
            AnalysisTransition.analysis_id == job.id, AnalysisTransition.to_state == "QUEUED")).scalar_one()
        task = enqueue_task(db, job.id, "analysis", f"{job.id}:analysis:{ANALYZER_VERSION}:g{generation}:a{job.attempt}")
        resp = {"analysis_id": str(job.id), "state": job.state, "task_id": str(task.id), "attempt": job.attempt}
    elif kind in {"docs_explain", "docs_assemble"}:
        if doc_id is None:
            raise ApiError("VALIDATION_ERROR", "doc_id is required for documentation dispatch.")
        doc = db.get(Documentation, doc_id)
        if doc is None or doc.analysis_id != job.id:
            raise ApiError("NOT_FOUND", "Documentation job not found.")
        if job.state == "RETRYING" and job.failed_state == "GENERATING_DOCS":
            job.attempt += 1
            transition(db, job, "GENERATING_DOCS", actor="n8n", note=f"docs retry attempt {job.attempt}", detail="documenting")
        elif job.state not in {"GENERATING_DOCS", "READY"}:
            raise ApiError("INVALID_STATE", f"Cannot dispatch documentation from state {job.state}.")
        if doc.status == "PENDING":
            doc.status = "GENERATING"
        task = enqueue_task(db, job.id, kind, f"{doc.id}:{kind}:{job.attempt}", {"doc_id": str(doc.id)})
        resp = {"analysis_id": str(job.id), "state": job.state, "task_id": str(task.id), "doc_id": str(doc.id)}
    else:
        raise ApiError("VALIDATION_ERROR", "Unknown dispatch kind.")
    _store_receipt(db, idempotency_key, job.id, "dispatch", resp)
    return resp


def internal_stage_result(db: Session, analysis_id: uuid.UUID, *, stage: str, workflow: str, execution_id: str,
                          idempotency_key: str | None) -> dict[str, Any]:
    if (dup := _receipt(db, analysis_id, idempotency_key)) is not None:
        return dup
    job = _load(db, analysis_id)
    if stage != "graph":
        raise ApiError("VALIDATION_ERROR", "Unknown stage.")
    if job.state == "GENERATING_DOCS" or job.state == "READY":
        doc = db.execute(select(Documentation).where(Documentation.analysis_id == job.id).order_by(Documentation.version)).scalars().first()
        resp = {"analysis_id": str(job.id), "state": job.state, "doc_id": str(doc.id) if doc else None}
    else:
        if job.state != "BUILDING_GRAPH" or not job.graph_complete:
            raise ApiError("INVALID_STATE", "The graph stage has not completed.")
        transition(db, job, "GENERATING_DOCS", actor="n8n", detail="documenting")
        doc = db.execute(select(Documentation).where(Documentation.idempotency_key == f"{job.id}:docs:1")).scalar_one_or_none()
        if doc is None:
            doc = Documentation(analysis_id=job.id, version=1, status="PENDING", ai_status="pending", idempotency_key=f"{job.id}:docs:1",
                                last_triggered_at=utcnow(), trigger_attempts=1)  # n8n starts the docs workflow itself right after this call
            db.add(doc)
            db.flush()
        resp = {"analysis_id": str(job.id), "state": job.state, "doc_id": str(doc.id)}
    _record_run(db, job.id, workflow, execution_id, "graph_complete", "succeeded")
    _store_receipt(db, idempotency_key, job.id, "stage-result", resp)
    return resp


def internal_complete(db: Session, analysis_id: uuid.UUID, *, doc_id: uuid.UUID, workflow: str, execution_id: str,
                      idempotency_key: str | None) -> dict[str, Any]:
    if (dup := _receipt(db, analysis_id, idempotency_key)) is not None:
        return dup
    job = _load(db, analysis_id)
    doc = db.get(Documentation, doc_id)
    if doc is None or doc.analysis_id != job.id:
        raise ApiError("NOT_FOUND", "Documentation job not found.")
    if doc.status not in {"READY", "PARTIAL"}:
        raise ApiError("INVALID_STATE", "Documentation has not finished.")
    if job.state == "GENERATING_DOCS":
        transition(db, job, "READY", actor="n8n", note=f"docs {doc.status.lower()}")
    elif job.state != "READY":
        raise ApiError("INVALID_STATE", f"Cannot complete from state {job.state}.")
    _record_run(db, job.id, workflow, execution_id, "complete", "succeeded")
    resp = {"analysis_id": str(job.id), "state": job.state, "doc_status": doc.status}
    _store_receipt(db, idempotency_key, job.id, "complete", resp)
    return resp


def internal_fail(db: Session, analysis_id: uuid.UUID, *, error_code: str, stage: str, workflow: str, execution_id: str,
                  idempotency_key: str | None, doc_id: uuid.UUID | None = None) -> dict[str, Any]:
    if (dup := _receipt(db, analysis_id, idempotency_key)) is not None:
        return dup
    if error_code not in FAIL_CODES_FROM_N8N:
        raise ApiError("VALIDATION_ERROR", "Unsupported error code.")
    job = _load(db, analysis_id)
    if doc_id:
        doc = db.get(Documentation, doc_id)
        if doc and doc.analysis_id == job.id and doc.status in {"PENDING", "GENERATING"}:
            doc.status = "FAILED"
            doc.error_code = error_code
    if job.state in ACTIVE:
        transition(db, job, "FAILED", actor="n8n", error_code=error_code, note=f"workflow {stage} failed")
    _record_run(db, job.id, workflow, execution_id, stage, "failed", error_code)
    resp = {"analysis_id": str(job.id), "state": job.state, "error_code": job.error_code}
    _store_receipt(db, idempotency_key, job.id, "fail", resp)
    return resp
