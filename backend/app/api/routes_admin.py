"""Administrator API. Every route requires role=admin; mutations are written to the admin_events audit trail."""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import extract, func, select, update

from app.api.deps import AdminUser, DB, settings_dep
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.metrics import metrics
from app.models import WorkerTask
from app.models import AdminEvent, AnalysisJob, AnswerCache, ChatMessage, EmbeddingCache, Repository, User, UserSession, utcnow
from app.services import quotas

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class DisableBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field("", max_length=200)


class QuotaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quota_analyses_day: int | None = Field(None, ge=0, le=100000)
    quota_questions_day: int | None = Field(None, ge=0, le=100000)
    quota_tokens_day: int | None = Field(None, ge=0, le=100_000_000)


def _audit(db, admin: User, action: str, target: User | None = None, **detail: Any) -> None:
    db.add(AdminEvent(admin_id=admin.id, action=action, target_user_id=target.id if target else None, detail=detail))


def _target(db, user_id: uuid.UUID) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise ApiError("NOT_FOUND", "No such user.", status=404)
    return u


def _user_row(db, u: User, s: Settings) -> dict:
    use = quotas.usage_today(db, u.id, s)
    total = db.execute(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.owner_id == u.id)).scalar_one()
    return {"id": str(u.id), "email": u.email, "role": u.role, "disabled": u.disabled_at is not None, "disabled_reason": u.disabled_reason,
            "created_at": u.created_at.isoformat(), "email_verified": u.email_verified_at is not None, "totp_enabled": bool(u.totp_enabled),
            "analyses_total": int(total), "today": use, "limits": quotas.limits_for(u, s),
            "overrides": {"quota_analyses_day": u.quota_analyses_day, "quota_questions_day": u.quota_questions_day, "quota_tokens_day": u.quota_tokens_day}}


@router.get("/overview")
def overview(admin: AdminUser, db: DB, s: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    now = utcnow(); d1, d30 = now - timedelta(days=1), now - timedelta(days=30)
    users = db.execute(select(func.count(), func.count().filter(User.disabled_at.is_not(None)), func.count().filter(User.created_at >= d1))).one()
    states = dict(db.execute(select(AnalysisJob.state, func.count()).where(AnalysisJob.created_at >= d1).group_by(AnalysisJob.state)).all())
    def spend(since):
        q, ti, to = db.execute(select(func.count().filter(ChatMessage.role == "user"), func.coalesce(func.sum(ChatMessage.input_tokens), 0), func.coalesce(func.sum(ChatMessage.output_tokens), 0)).where(ChatMessage.created_at >= since)).one()
        return {"questions": int(q), "input_tokens": int(ti), "output_tokens": int(to), "spend_usd": quotas.cost_usd(int(ti), int(to), s)}
    failed_total = db.execute(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.state == "FAILED")).scalar_one()
    avg_ms = db.execute(select(func.avg(ChatMessage.latency_ms)).where(ChatMessage.latency_ms.is_not(None), ChatMessage.created_at >= d1)).scalar()
    fallback = db.execute(select(func.count()).where(ChatMessage.answer_source == "retrieval_only", ChatMessage.created_at >= d1)).scalar_one()
    ai24 = db.execute(select(func.count().filter(ChatMessage.cache_hit), func.count()).where(ChatMessage.role == "assistant", ChatMessage.answer_source == "ai", ChatMessage.created_at >= d1)).one()
    saved = db.execute(select(func.coalesce(func.sum(AnswerCache.hits * AnswerCache.input_tokens), 0), func.coalesce(func.sum(AnswerCache.hits * AnswerCache.output_tokens), 0),
                              func.coalesce(func.sum(AnswerCache.hits), 0), func.count())).one()
    emb = db.execute(select(func.coalesce(func.sum(EmbeddingCache.hits), 0), func.count())).one()
    cache = {"answers_24h": {"served_from_cache": int(ai24[0]), "ai_answers": int(ai24[1]), "hit_rate": round(ai24[0] / ai24[1], 3) if ai24[1] else None},
             "answers_all_time": {"hits": int(saved[2]), "entries": int(saved[3]), "tokens_saved": int(saved[0]) + int(saved[1]), "spend_saved_usd": quotas.cost_usd(int(saved[0]), int(saved[1]), s)},
             "question_embeddings": {"reused": int(emb[0]), "computed": int(emb[1])}}
    return {"cache": cache, "users": {"total": users[0], "disabled": users[1], "new_24h": users[2]}, "analyses_24h": states, "failed_total": int(failed_total),
            "llm_24h": {**spend(d1), "avg_latency_ms": int(avg_ms) if avg_ms else None, "retrieval_only_answers": int(fallback)}, "llm_30d": spend(d30),
            "pricing_configured": s.llm_price_input_per_mtok is not None and s.llm_price_output_per_mtok is not None}


@router.get("/users")
def users(admin: AdminUser, db: DB, s: Annotated[Settings, Depends(settings_dep)], q: str = Query("", max_length=100), limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if q.strip():
        stmt = stmt.where(User.email.ilike(f"%{q.strip().lower()}%"))
    return {"users": [_user_row(db, u, s) for u in db.execute(stmt).scalars()]}


@router.post("/users/{user_id}/disable")
def disable(user_id: uuid.UUID, body: DisableBody, admin: AdminUser, db: DB) -> dict[str, Any]:
    u = _target(db, user_id)
    if u.id == admin.id:
        raise ApiError("FORBIDDEN", "You cannot disable your own account.", status=403)
    if u.role == "admin":
        raise ApiError("FORBIDDEN", "Demote the administrator before disabling the account.", status=403)
    u.disabled_at, u.disabled_reason = utcnow(), body.reason.strip() or None
    db.execute(update(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))  # sign out everywhere
    _audit(db, admin, "user.disable", u, reason=u.disabled_reason)
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/enable")
def enable(user_id: uuid.UUID, admin: AdminUser, db: DB) -> dict[str, Any]:
    u = _target(db, user_id)
    u.disabled_at, u.disabled_reason = None, None
    _audit(db, admin, "user.enable", u)
    db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/quotas")
def set_quotas(user_id: uuid.UUID, body: QuotaBody, admin: AdminUser, db: DB) -> dict[str, Any]:
    u = _target(db, user_id)
    u.quota_analyses_day, u.quota_questions_day, u.quota_tokens_day = body.quota_analyses_day, body.quota_questions_day, body.quota_tokens_day
    _audit(db, admin, "user.quotas", u, **body.model_dump())
    db.commit()
    return {"ok": True}


def _job_row(j: AnalysisJob, email: str | None, repo: str | None) -> dict:
    return {"id": str(j.id), "owner": email, "repository": repo, "state": j.state, "error_code": j.error_code, "error_message": j.error_message,
            "failed_state": j.failed_state, "retryable": j.error_retryable, "created_at": j.created_at.isoformat(), "commit_sha": j.commit_sha[:10]}


@router.get("/analyses")
def analyses(admin: AdminUser, db: DB, state: str = Query("", max_length=24), limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    stmt = (select(AnalysisJob, User.email, Repository.full_name).join(User, User.id == AnalysisJob.owner_id)
            .join(Repository, Repository.id == AnalysisJob.repository_id).order_by(AnalysisJob.created_at.desc()).limit(limit))
    if state:
        stmt = stmt.where(AnalysisJob.state == state.upper())
    return {"analyses": [_job_row(j, e, r) for j, e, r in db.execute(stmt).all()]}


@router.get("/failures")
def failures(admin: AdminUser, db: DB, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    stmt = (select(AnalysisJob, User.email, Repository.full_name).join(User, User.id == AnalysisJob.owner_id).join(Repository, Repository.id == AnalysisJob.repository_id)
            .where(AnalysisJob.state == "FAILED").order_by(AnalysisJob.updated_at.desc()).limit(limit))
    rows = [_job_row(j, e, r) for j, e, r in db.execute(stmt).all()]
    by_code = dict(db.execute(select(func.coalesce(AnalysisJob.error_code, "UNKNOWN"), func.count()).where(AnalysisJob.state == "FAILED").group_by(AnalysisJob.error_code)).all())
    return {"failures": rows, "by_code": by_code}


@router.get("/spend")
def spend(admin: AdminUser, db: DB, s: Annotated[Settings, Depends(settings_dep)], days: int = Query(14, ge=1, le=90)) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    day = func.date_trunc("day", ChatMessage.created_at)
    series = db.execute(select(day, func.count().filter(ChatMessage.role == "user"), func.coalesce(func.sum(ChatMessage.input_tokens), 0), func.coalesce(func.sum(ChatMessage.output_tokens), 0))
                        .where(ChatMessage.created_at >= since).group_by(day).order_by(day)).all()
    tok = func.coalesce(func.sum(ChatMessage.input_tokens), 0) + func.coalesce(func.sum(ChatMessage.output_tokens), 0)
    top = db.execute(select(User.email, func.count().filter(ChatMessage.role == "user"), func.coalesce(func.sum(ChatMessage.input_tokens), 0), func.coalesce(func.sum(ChatMessage.output_tokens), 0))
                     .join(User, User.id == ChatMessage.owner_id).where(ChatMessage.created_at >= since).group_by(User.email).order_by(tok.desc()).limit(10)).all()
    row = lambda q, i, o: {"questions": int(q), "input_tokens": int(i), "output_tokens": int(o), "spend_usd": quotas.cost_usd(int(i), int(o), s)}
    return {"days": [{"day": d.date().isoformat(), **row(q, i, o)} for d, q, i, o in series], "top_users": [{"email": e, **row(q, i, o)} for e, q, i, o in top]}


@router.get("/audit")
def audit(admin: AdminUser, db: DB, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    a, t = User.__table__.alias("a"), User.__table__.alias("t")
    rows = db.execute(select(AdminEvent, a.c.email, t.c.email).outerjoin(a, a.c.id == AdminEvent.admin_id).outerjoin(t, t.c.id == AdminEvent.target_user_id)
                      .order_by(AdminEvent.created_at.desc()).limit(limit)).all()
    return {"events": [{"id": str(e.id), "action": e.action, "admin": ae, "target": te, "detail": e.detail, "at": e.created_at.isoformat()} for e, ae, te in rows]}


@router.get("/monitoring")
def monitoring(admin: AdminUser, db: DB, minutes: int = Query(60, ge=5, le=120)) -> dict[str, Any]:
    from app.services.orchestrator import Orchestrator
    now = utcnow(); d1, d14 = now - timedelta(days=1), now - timedelta(days=14)
    day = func.date_trunc("day", AnalysisJob.created_at)
    secs = extract("epoch", AnalysisJob.finished_at - AnalysisJob.started_at)
    rows = db.execute(select(day, func.count(), func.count().filter(AnalysisJob.state == "READY"), func.count().filter(AnalysisJob.state == "FAILED"),
                             func.avg(secs).filter(AnalysisJob.state == "READY")).where(AnalysisJob.created_at >= d14).group_by(day).order_by(day)).all()
    p95 = db.execute(select(func.percentile_cont(0.95).within_group(secs)).where(AnalysisJob.state == "READY", AnalysisJob.created_at >= d14)).scalar()
    jobs = {"days": [{"day": d.date().isoformat(), "created": int(c), "ready": int(r), "failed": int(f), "avg_seconds": round(float(a), 1) if a is not None else None} for d, c, r, f, a in rows],
            "p95_seconds": round(float(p95), 1) if p95 is not None else None,
            "success_rate": (lambda r, f: round(r / (r + f), 3) if (r + f) else None)(sum(x[2] for x in rows), sum(x[3] for x in rows)),
            "in_flight": int(db.execute(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.state.in_(("QUEUED", "FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS", "RETRYING")))).scalar_one())}
    by_status = dict(db.execute(select(WorkerTask.status, func.count()).group_by(WorkerTask.status)).all())
    oldest = db.execute(select(func.min(WorkerTask.created_at)).where(WorkerTask.status == "pending")).scalar()
    stuck = db.execute(select(func.count()).select_from(WorkerTask).where(WorkerTask.status == "running", WorkerTask.lease_expires_at < now)).scalar_one()
    last_done = db.execute(select(func.max(WorkerTask.finished_at))).scalar()
    queue = {"by_status": by_status, "oldest_pending_seconds": int((now - oldest).total_seconds()) if oldest else 0, "expired_leases": int(stuck),
             "last_task_finished_at": last_done.isoformat() if last_done else None}
    lat = ChatMessage.latency_ms
    p50, p95l, avgl, n_ai, n_fb, n_err = db.execute(select(
        func.percentile_cont(0.5).within_group(lat).filter(ChatMessage.answer_source == "ai"), func.percentile_cont(0.95).within_group(lat).filter(ChatMessage.answer_source == "ai"),
        func.avg(lat).filter(ChatMessage.answer_source == "ai"), func.count().filter(ChatMessage.answer_source == "ai"),
        func.count().filter(ChatMessage.answer_source == "retrieval_only"), func.count().filter(ChatMessage.status == "failed"),
    ).where(ChatMessage.role == "assistant", ChatMessage.created_at >= d1)).one()
    llm = {"answers_24h": int(n_ai) + int(n_fb), "ai": int(n_ai), "retrieval_only": int(n_fb), "failed": int(n_err), "fallback_rate": round(n_fb / (n_ai + n_fb), 3) if (n_ai + n_fb) else None,
           "latency_p50_ms": int(p50) if p50 is not None else None, "latency_p95_ms": int(p95l) if p95l is not None else None}
    try:
        db.execute(select(1)); db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"generated_at": now.isoformat(), "http": metrics.snapshot(minutes), "jobs": jobs, "queue": queue, "llm": llm,
            "services": {"database": db_ok, "orchestrator": Orchestrator().health().get("reachable", False)}}
