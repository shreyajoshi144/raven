"""Worker process: PostgreSQL-backed queue consumer with leases, heartbeats, crash recovery and graceful shutdown.

    python -m app.workers.main
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, text, update

from app.core.config import Settings, load_settings_or_exit
from app.core.db import new_session
from app.core.errors import JobError
from app.core.logging import configure_logging, log
from app.models import AnalysisJob, Documentation, WorkerTask, utcnow
from app.services.jobs import trigger_analysis, trigger_docs
from app.services.orchestrator import Orchestrator
from app.services.state import lock_job, transition
from app.workers.docs_tasks import run_docs_assemble, run_docs_explain
from app.workers.stages import run_analysis_task

logger = logging.getLogger("raven.worker")
MAX_TASK_ATTEMPTS = 5
RETRIGGER_AFTER_SECONDS = 90


def claim_task(worker_id: str, s: Settings) -> WorkerTask | None:
    """Atomically claim one pending task (FOR UPDATE SKIP LOCKED) and take a lease."""
    with new_session() as db:
        row = db.execute(text("""
            SELECT id FROM worker_tasks WHERE status = 'pending'
            ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED""")).first()
        if not row:
            return None
        task = db.get(WorkerTask, row[0])
        assert task is not None
        task.status, task.claimed_by = "running", worker_id
        task.attempts += 1
        task.lease_expires_at = utcnow() + timedelta(seconds=s.worker_lease_seconds)
        db.commit()
        db.refresh(task)
        db.expunge(task)
        return task


def heartbeat(task_id: uuid.UUID, s: Settings) -> None:
    with new_session() as db:
        db.execute(update(WorkerTask).where(WorkerTask.id == task_id, WorkerTask.status == "running")
                   .values(lease_expires_at=utcnow() + timedelta(seconds=s.worker_lease_seconds)))
        db.commit()


def finish_task(task_id: uuid.UUID, status: str = "done", error_code: str | None = None) -> None:
    with new_session() as db:
        db.execute(update(WorkerTask).where(WorkerTask.id == task_id).values(status=status, error_code=error_code, finished_at=utcnow(), lease_expires_at=None))
        db.commit()


def execute_task(task: WorkerTask, s: Settings) -> None:
    jid = task.analysis_id
    if task.task_type == "analysis":
        run_analysis_task(jid, settings=s)
    elif task.task_type == "docs_explain":
        run_docs_explain(task.payload, jid, s)
    elif task.task_type == "docs_assemble":
        run_docs_assemble(task.payload, jid)
    else:
        raise JobError("INTERNAL_ANALYSIS_ERROR", f"unknown task type {task.task_type}")


def _run_with_heartbeat(task: WorkerTask, s: Settings) -> None:
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(max(1.0, s.worker_lease_seconds / 3)):
            try:
                heartbeat(task.id, s)
            except Exception:  # noqa: BLE001
                pass

    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        execute_task(task, s)
        finish_task(task.id)
    except Exception as exc:  # noqa: BLE001
        log(logger, "task_crashed", logging.ERROR, task_type=task.task_type, error_type=type(exc).__name__)
        finish_task(task.id, "failed", "INTERNAL_ANALYSIS_ERROR")
        _fail_job_after_crash(task, s)
    finally:
        stop.set()


def _fail_job_after_crash(task: WorkerTask, s: Settings) -> None:
    with new_session() as db:
        job = lock_job(db, task.analysis_id)
        if job and job.state in {"FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS"}:
            transition(db, job, "FAILED", actor="worker", error_code="INTERNAL_ANALYSIS_ERROR", note="worker task crashed")
            db.commit()


def recover(s: Settings, orch: Orchestrator) -> dict[str, int]:
    """Crash recovery and orchestration re-triggering. Safe to run repeatedly from any worker."""
    counts = {"leases_reset": 0, "tasks_failed": 0, "retriggered": 0, "failed_unreachable": 0}
    now = utcnow()
    with new_session() as db:
        stale = db.execute(select(WorkerTask).where(WorkerTask.status == "running", WorkerTask.lease_expires_at < now).with_for_update(skip_locked=True)).scalars().all()
        for t in stale:
            if t.attempts >= MAX_TASK_ATTEMPTS:
                t.status, t.error_code, t.finished_at = "failed", "WORKER_LOST", now
                job = lock_job(db, t.analysis_id)
                if job and job.state in {"FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS"}:
                    transition(db, job, "FAILED", actor="worker", error_code="WORKER_LOST", note="task lease expired repeatedly")
                counts["tasks_failed"] += 1
            else:
                t.status, t.claimed_by, t.lease_expires_at = "pending", None, None
                job = lock_job(db, t.analysis_id)
                if job and t.task_type == "analysis" and job.state in {"PARSING", "BUILDING_GRAPH"}:
                    # stages are idempotent: re-enter the pipeline at FETCHING (recorded as a recovery transition)
                    transition(db, job, "FETCHING", actor="worker", note="recovered after worker loss", detail="fetching")
                counts["leases_reset"] += 1
        db.commit()

    cutoff = now - timedelta(seconds=RETRIGGER_AFTER_SECONDS)
    with new_session() as db:
        queued = db.execute(select(AnalysisJob).where(AnalysisJob.state == "QUEUED", or_(AnalysisJob.last_triggered_at.is_(None), AnalysisJob.last_triggered_at < cutoff))
                            .with_for_update(skip_locked=True, of=AnalysisJob)).scalars().all()
        for job in queued:
            if job.trigger_attempts >= s.trigger_max_attempts:
                transition(db, job, "FAILED", actor="worker", error_code="ORCHESTRATOR_UNAVAILABLE", note="could not reach n8n")
                counts["failed_unreachable"] += 1
                continue
            trigger_analysis(db, job, orch)
            counts["retriggered"] += 1
        docs = db.execute(select(Documentation).join(AnalysisJob, AnalysisJob.id == Documentation.analysis_id).where(
            Documentation.status.in_(("PENDING", "GENERATING")), AnalysisJob.state.in_(("GENERATING_DOCS", "READY")),
            or_(Documentation.last_triggered_at.is_(None), Documentation.last_triggered_at < cutoff)).with_for_update(skip_locked=True, of=Documentation)).scalars().all()
        for doc in docs:
            if doc.trigger_attempts >= s.trigger_max_attempts:
                doc.status, doc.error_code = "FAILED", "ORCHESTRATOR_UNAVAILABLE"
                job = lock_job(db, doc.analysis_id)
                if job and job.state == "GENERATING_DOCS":
                    transition(db, job, "FAILED", actor="worker", error_code="ORCHESTRATOR_UNAVAILABLE", note="could not reach n8n for docs")
                continue
            trigger_docs(db, doc, orch)
            counts["retriggered"] += 1
        # initial docs finished but n8n never reported completion
        stuck = db.execute(select(AnalysisJob).join(Documentation, Documentation.analysis_id == AnalysisJob.id).where(
            AnalysisJob.state == "GENERATING_DOCS", Documentation.status.in_(("READY", "PARTIAL")), Documentation.updated_at < cutoff)
            .with_for_update(skip_locked=True, of=AnalysisJob)).scalars().all()
        for job in stuck:
            doc = db.execute(select(Documentation).where(Documentation.analysis_id == job.id).order_by(Documentation.version.desc())).scalars().first()
            if doc:
                trigger_docs(db, doc, orch)
        db.commit()
    return counts


class Worker:
    def __init__(self, s: Settings):
        self.s = s
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=s.max_concurrent_analyses, thread_name_prefix="raven-task")
        self.inflight: dict[uuid.UUID, Future[None]] = {}
        self.orch = Orchestrator(s)

    def request_stop(self, *_: Any) -> None:
        log(logger, "worker_shutdown_requested")
        self.stopping.set()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        log(logger, "worker_started", worker=self.id, concurrency=self.s.max_concurrent_analyses)
        last_recover = 0.0
        while not self.stopping.is_set():
            self.inflight = {k: v for k, v in self.inflight.items() if not v.done()}
            now = time.monotonic()
            if now - last_recover > 15:
                try:
                    c = recover(self.s, self.orch)
                    if any(c.values()):
                        log(logger, "recovery", **c)
                except Exception as exc:  # noqa: BLE001
                    log(logger, "recovery_error", logging.ERROR, error_type=type(exc).__name__)
                last_recover = now
            if len(self.inflight) >= self.s.max_concurrent_analyses:
                self.stopping.wait(self.s.worker_poll_seconds)
                continue
            try:
                task = claim_task(self.id, self.s)
            except Exception as exc:  # noqa: BLE001
                log(logger, "claim_error", logging.ERROR, error_type=type(exc).__name__)
                self.stopping.wait(2.0)
                continue
            if task is None:
                self.stopping.wait(self.s.worker_poll_seconds)
                continue
            self.inflight[task.id] = self.pool.submit(_run_with_heartbeat, task, self.s)
        self._drain()

    def _drain(self) -> None:
        deadline = time.monotonic() + self.s.worker_shutdown_grace_seconds
        while self.inflight and time.monotonic() < deadline:
            self.inflight = {k: v for k, v in self.inflight.items() if not v.done()}
            time.sleep(0.2)
        if self.inflight:
            # hand unfinished tasks back to the queue; stages are idempotent
            with new_session() as db:
                db.execute(update(WorkerTask).where(WorkerTask.id.in_(list(self.inflight)), WorkerTask.status == "running")
                           .values(status="pending", claimed_by=None, lease_expires_at=None))
                db.commit()
            log(logger, "worker_released_tasks", count=len(self.inflight))
        self.pool.shutdown(wait=False, cancel_futures=True)
        log(logger, "worker_stopped")


def main() -> None:
    s = load_settings_or_exit()
    configure_logging(s.log_level)
    Worker(s).run()


if __name__ == "__main__":
    main()
