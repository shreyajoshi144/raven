"""Pull-request reviews and AI usage accounting."""
from __future__ import annotations

import statistics
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.analysis.urls import parse_pr_url
from app.api.deps import CurrentUser, DB, OwnedJob, github_dep, orchestrator_dep, rate_limited, settings_dep
from app.services import quotas
from app.core.config import Settings
from app.core.errors import ApiError, JobError, info
from app.models import ChatMessage, Documentation, PrReview, Repository
from app.schemas.api import PrReviewBody
from app.services import jobs as jobsvc
from app.services import pr_review as prsvc
from app.services.github import GitHubClient
from app.services.orchestrator import Orchestrator

router = APIRouter(prefix="/api/v1", tags=["pull-requests"], dependencies=[Depends(rate_limited)])


def _owned(db: Any, user: Any, review_id: uuid.UUID) -> PrReview:
    pr = db.get(PrReview, review_id)
    if pr is None or pr.owner_id != user.id:
        raise ApiError("NOT_FOUND", "Review not found.")
    return pr


def _repo(db: Any, pr: PrReview) -> str:
    return db.get(Repository, pr.repository_id).full_name


@router.post("/pr-reviews", status_code=202)
def create_review(body: PrReviewBody, request: Request, user: CurrentUser, db: DB, gh: Annotated[GitHubClient, Depends(github_dep)],
                  orch: Annotated[Orchestrator, Depends(orchestrator_dep)], s: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    quotas.enforce(db, user, "analysis", s)
    ref, number = parse_pr_url(body.url)
    url = f"https://github.com/{ref.owner}/{ref.name}"
    try:
        try:
            meta = gh.get_pull(ref.owner, ref.name, number)
        except JobError as exc:
            raise ApiError(exc.code, info(exc.code).message) from None
        if meta["head_repo"].lower() != meta["base_repo"].lower():
            raise ApiError("PR_FORK_UNSUPPORTED")
        jobs, created = [], []
        for sha in (meta["base_sha"], meta["head_sha"]):
            try:
                job, new = jobsvc.submit_analysis(db, user, url, gh, s, request_id=request.state.request_id, sha=sha)
            except JobError as exc:
                raise ApiError(exc.code, info(exc.code).message) from None
            jobs.append(job)
            created.append(new)
        base, head = jobs
        pr = db.execute(select(PrReview).where(PrReview.owner_id == user.id, PrReview.repository_id == head.repository_id, PrReview.pr_number == number,
                                               PrReview.base_sha == meta["base_sha"], PrReview.head_sha == meta["head_sha"])).scalar_one_or_none()
        if pr is None:
            pr = PrReview(owner_id=user.id, repository_id=head.repository_id, pr_number=number, title=meta["title"], pr_state=meta["state"],
                          base_sha=meta["base_sha"], head_sha=meta["head_sha"], base_analysis_id=base.id, head_analysis_id=head.id)
            db.add(pr)
        pr.pr_state = meta["state"]
        db.commit()
    finally:
        gh.close()
    for job, new in zip(jobs, created):
        if new:
            jobsvc.trigger_analysis(db, job, orch)
    db.commit()
    prsvc.refresh(db, pr)
    db.commit()
    return prsvc.to_dict(db, pr, _repo(db, pr))


@router.get("/pr-reviews")
def list_reviews(user: CurrentUser, db: DB, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    rows = db.execute(select(PrReview).where(PrReview.owner_id == user.id).order_by(PrReview.created_at.desc()).limit(limit)).scalars().all()
    out = []
    for r in rows:
        prsvc.refresh(db, r)
        d = prsvc.to_dict(db, r, _repo(db, r))
        d["review"] = None  # list view: summary only
        d["risk"] = (r.result or {}).get("risk")
        d["verdict_level"] = ((r.result or {}).get("verdict") or {}).get("level")
        out.append(d)
    db.commit()
    return {"items": out}


@router.get("/pr-reviews/{review_id}")
def get_review(review_id: uuid.UUID, user: CurrentUser, db: DB) -> dict[str, Any]:
    pr = prsvc.refresh(db, _owned(db, user, review_id))
    db.commit()
    return prsvc.to_dict(db, pr, _repo(db, pr))


@router.get("/pr-reviews/{review_id}/markdown")
def review_markdown(review_id: uuid.UUID, user: CurrentUser, db: DB) -> PlainTextResponse:
    pr = prsvc.refresh(db, _owned(db, user, review_id))
    db.commit()
    return PlainTextResponse(prsvc.markdown(prsvc.to_dict(db, pr, _repo(db, pr))), media_type="text/markdown")


@router.get("/analyses/{analysis_id}/usage")
def usage(job: OwnedJob, db: DB, s: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    """Measured AI usage for this analysis: Q&A answers (tokens, latency, failures) and guide generation. Cost only when prices are configured."""
    msgs = db.execute(select(ChatMessage).where(ChatMessage.analysis_id == job.id, ChatMessage.role == "assistant", ChatMessage.status == "complete")).scalars().all()
    ai = [m for m in msgs if m.latency_ms is not None]
    lat = sorted(m.latency_ms for m in ai)
    by_source: dict[str, int] = {}
    fails: dict[str, int] = {}
    for m in msgs:
        by_source[m.answer_source or "unknown"] = by_source.get(m.answer_source or "unknown", 0) + 1
        if m.error_code:
            fails[m.error_code] = fails.get(m.error_code, 0) + 1
    qin, qout = sum(m.input_tokens or 0 for m in ai), sum(m.output_tokens or 0 for m in ai)
    docs = db.execute(select(Documentation).where(Documentation.analysis_id == job.id)).scalars().all()
    llm = [(d.stats or {}).get("llm") or {} for d in docs]
    gin, gout, gcalls = sum(x.get("input_tokens", 0) for x in llm), sum(x.get("output_tokens", 0) for x in llm), sum(x.get("calls", 0) for x in llm)
    tin, tout = qin + gin, qout + gout
    priced = s.llm_price_input_per_mtok is not None and s.llm_price_output_per_mtok is not None
    return {"analysis_id": str(job.id), "commit_sha": job.commit_sha,
            "qa": {"answers": len(msgs), "by_source": by_source, "failures": fails, "ai_calls_measured": len(ai), "input_tokens": qin, "output_tokens": qout,
                   "latency_ms": ({"p50": int(statistics.median(lat)), "p95": lat[min(len(lat) - 1, int(len(lat) * 0.95))], "max": lat[-1]} if lat else None)},
            "guide": {"llm_calls": gcalls, "input_tokens": gin, "output_tokens": gout},
            "total": {"input_tokens": tin, "output_tokens": tout,
                      "estimated_cost_usd": round(tin / 1e6 * s.llm_price_input_per_mtok + tout / 1e6 * s.llm_price_output_per_mtok, 6) if priced else None,
                      "cost_basis": "tokens × configured LLM_PRICE_*_PER_MTOK (no caching/batch discounts)" if priced else "not computed: set LLM_PRICE_INPUT_PER_MTOK and LLM_PRICE_OUTPUT_PER_MTOK"},
            "note": "Answers recorded before usage tracking was added have no token or latency data and are excluded from the measured figures."}
