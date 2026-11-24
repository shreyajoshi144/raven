"""Internal service API used by n8n. Separate service authentication; never reachable with browser sessions."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import DB, internal_auth
from app.core.errors import ApiError
from app.core.logging import execution_id_var, workflow_var
from app.models import AnalysisJob
from app.schemas.api import CompleteBody, DispatchBody, FailBody, QaAnswerBody, QaRetrieveBody, StageResultBody
from app.services import jobs as jobsvc
from app.services import qa as qasvc

from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/internal/v1", tags=["internal"], dependencies=[Depends(internal_auth)])


def _uuid(v: str, what: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError:
        raise ApiError("VALIDATION_ERROR", f"Invalid {what}.") from None


@router.get("/analysis-jobs/{analysis_id}/status")
def status(analysis_id: uuid.UUID, db: DB, doc_id: uuid.UUID | None = None) -> dict[str, Any]:
    return jobsvc.internal_status(db, analysis_id, doc_id=doc_id)


@router.post("/analysis-jobs/{analysis_id}/dispatch")
def dispatch(analysis_id: uuid.UUID, body: DispatchBody, db: DB) -> dict[str, Any]:
    workflow_var.set(body.workflow)
    execution_id_var.set(body.execution_id)
    out = jobsvc.internal_dispatch(db, analysis_id, kind=body.kind, workflow=body.workflow, execution_id=body.execution_id,
                                   idempotency_key=body.idempotency_key, doc_id=_uuid(body.doc_id, "doc_id") if body.doc_id else None)
    db.commit()
    return out


@router.post("/analysis-jobs/{analysis_id}/stage-result")
def stage_result(analysis_id: uuid.UUID, body: StageResultBody, db: DB) -> dict[str, Any]:
    workflow_var.set(body.workflow)
    execution_id_var.set(body.execution_id)
    out = jobsvc.internal_stage_result(db, analysis_id, stage=body.stage, workflow=body.workflow, execution_id=body.execution_id,
                                       idempotency_key=body.idempotency_key)
    db.commit()
    return out


@router.post("/analysis-jobs/{analysis_id}/complete")
def complete(analysis_id: uuid.UUID, body: CompleteBody, db: DB) -> dict[str, Any]:
    workflow_var.set(body.workflow)
    execution_id_var.set(body.execution_id)
    out = jobsvc.internal_complete(db, analysis_id, doc_id=_uuid(body.doc_id, "doc_id"), workflow=body.workflow,
                                   execution_id=body.execution_id, idempotency_key=body.idempotency_key)
    db.commit()
    return out


@router.post("/analysis-jobs/{analysis_id}/fail")
def fail(analysis_id: uuid.UUID, body: FailBody, db: DB) -> dict[str, Any]:
    workflow_var.set(body.workflow)
    execution_id_var.set(body.execution_id)
    out = jobsvc.internal_fail(db, analysis_id, error_code=body.error_code, stage=body.stage, workflow=body.workflow,
                               execution_id=body.execution_id, idempotency_key=body.idempotency_key,
                               doc_id=_uuid(body.doc_id, "doc_id") if body.doc_id else None)
    db.commit()
    return out


@router.post("/qa/retrieve")
def qa_retrieve(body: QaRetrieveBody, db: DB) -> dict[str, Any]:
    workflow_var.set("raven_codebase_qa")
    execution_id_var.set(body.execution_id)
    aid = _uuid(body.analysis_id, "analysis_id")
    if db.get(AnalysisJob, aid) is None:
        raise ApiError("NOT_FOUND", "Analysis not found.")
    jobsvc._record_run(db, aid, "raven_codebase_qa", body.execution_id, "retrieve")
    out = qasvc.internal_retrieve(db, aid, _uuid(body.message_id, "message_id"))
    db.commit()
    return out


@router.post("/qa/answer")
def qa_answer(body: QaAnswerBody, db: DB) -> dict[str, Any]:
    workflow_var.set("raven_codebase_qa")
    execution_id_var.set(body.execution_id)
    aid = _uuid(body.analysis_id, "analysis_id")
    msg_id = _uuid(body.message_id, "message_id")
    out = qasvc.internal_answer(db, msg_id)
    jobsvc._record_run(db, aid, "raven_codebase_qa", body.execution_id, "answer", "succeeded")
    db.commit()
    return out


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus(db: DB) -> str:
    """Prometheus text exposition (service-secret protected; blocked at the public proxy together with the rest of /internal/)."""
    from sqlalchemy import func, select
    from app.core.metrics import metrics
    from app.models import WorkerTask
    snap, t = metrics.snapshot(5), metrics.total
    out = ["# TYPE raven_http_requests_total counter", f"raven_http_requests_total {t['n']}", "# TYPE raven_http_errors_total counter",
           f'raven_http_errors_total{{class="4xx"}} {t["e4"]}', f'raven_http_errors_total{{class="5xx"}} {t["e5"]}',
           "# TYPE raven_http_latency_p95_ms gauge", f"raven_http_latency_p95_ms {snap['p95_ms'] or 0}", "# TYPE raven_process_uptime_seconds gauge", f"raven_process_uptime_seconds {snap['uptime_seconds']}",
           "# TYPE raven_analysis_jobs gauge"]
    out += [f'raven_analysis_jobs{{state="{k}"}} {v}' for k, v in db.execute(select(AnalysisJob.state, func.count()).group_by(AnalysisJob.state)).all()]
    out.append("# TYPE raven_worker_tasks gauge")
    out += [f'raven_worker_tasks{{status="{k}"}} {v}' for k, v in db.execute(select(WorkerTask.status, func.count()).group_by(WorkerTask.status)).all()]
    return "\n".join(out) + "\n"
