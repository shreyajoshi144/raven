from __future__ import annotations

import logging
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, or_, select

from app.analysis.graph import NODE_TYPES, RELATIONS
from app.api.deps import CurrentUser, DB, OwnedJob, github_dep, orchestrator_dep, rate_limited, settings_dep
from app.core.config import Settings
from app.core.errors import ApiError, JobError, info
from app.models import (
    AnalysisFile, AnalysisJob, AnalysisTransition, ChatMessage, CodeEdge, CodeNode, Documentation, ImpactReport, WorkflowRun, utcnow,
)
from app.schemas.api import ChatBody, CreateAnalysisBody, ImpactBody
from app.services import architecture as archsvc
from app.services import codemap
from app.services import jobs as jobsvc
from app.services import qa as qasvc
from app.services import quotas
from app.services.diagrams import build_diagram
from app.services.flow import build_file_flow, build_trace
from app.services.github import GitHubClient
from app.services.impact import compute_impact
from app.services.orchestrator import Orchestrator
from app.services.security import rate_limit

logger = logging.getLogger("raven.api")
router = APIRouter(prefix="/api/v1", tags=["analyses"], dependencies=[Depends(rate_limited)])


# ------------------------------------------------------------------------------ serializers
def analysis_dict(job: AnalysisJob, db: Any | None = None, detail: bool = False) -> dict[str, Any]:
    end = job.finished_at or utcnow()
    begin = job.started_at or job.created_at
    summary = job.summary or {}
    graph = summary.get("graph", {})
    d: dict[str, Any] = {
        "analysis_id": str(job.id), "status": job.state, "stage": job.stage_detail, "progress": job.progress or {},
        "repository": {"full_name": job.repository.full_name, "url": job.repository.canonical_url, "description": job.repository.description,
                       "language": job.repository.primary_language, "stars": job.repository.stars},
        "commit_sha": job.commit_sha, "default_branch": job.default_branch, "analyzer_version": job.analyzer_version,
        "created_at": job.created_at.isoformat(), "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None, "elapsed_seconds": round((end - begin).total_seconds(), 1),
        "attempt": job.attempt, "graph_complete": job.graph_complete,
        "error": ({"code": job.error_code, "message": job.error_message, "retryable": job.error_retryable} if job.error_code else None),
        "retry_eligible": job.state == "FAILED" and bool(job.error_retryable or job.error_code in jobsvc.USER_RETRYABLE_EXTRA),
        "retry_after": job.retry_after.isoformat() if job.retry_after else None,
        "status_url": f"/api/v1/analyses/{job.id}",
        "summary": {"partial": summary.get("partial", False), "partial_reasons": summary.get("partial_reasons", []),
                    "inventory": summary.get("inventory"), "parse": summary.get("parse"),
                    "graph": {k: graph.get(k) for k in ("node_count", "edge_count", "route_count", "nodes_by_type", "edges_by_resolution",
                                                        "detected_frameworks", "unresolved_edges", "inferred_edges")} if graph else None},
    }
    if detail:
        d["summary"]["entry_points"] = summary.get("entry_points", [])
        d["summary"]["gaps"] = summary.get("gaps", [])[:100]
        d["summary"]["stage_seconds"] = summary.get("stage_seconds", {})
        d["summary"]["incremental"] = summary.get("incremental")
        if db is not None:
            d["transitions"] = [{"from": t.from_state, "to": t.to_state, "actor": t.actor, "error_code": t.error_code, "at": t.at.isoformat()}
                                for t in db.execute(select(AnalysisTransition).where(AnalysisTransition.analysis_id == job.id)
                                                    .order_by(AnalysisTransition.at, AnalysisTransition.id)).scalars()]
            d["workflow_runs"] = [{"workflow": r.workflow_name, "execution_id": r.n8n_execution_id, "stage": r.stage, "status": r.status,
                                   "error_code": r.error_code, "started_at": r.started_at.isoformat()}
                                  for r in db.execute(select(WorkflowRun).where(WorkflowRun.analysis_id == job.id).order_by(WorkflowRun.started_at.desc()).limit(20)).scalars()]
    return d


def node_dict(n: CodeNode) -> dict[str, Any]:
    return {"id": str(n.id), "type": n.type, "name": n.name, "qualified_name": n.qualified_name, "path": n.path, "start_line": n.start_line,
            "end_line": n.end_line, "facts": n.facts, "meta": n.meta, "evidence": n.evidence, "explanation": n.explanation,
            "explanation_source": n.explanation_source}


def edge_dict(e: CodeEdge) -> dict[str, Any]:
    return {"id": str(e.id), "source": str(e.source_id), "target": str(e.target_id), "relation": e.relation, "resolution": e.resolution,
            "evidence": e.evidence, "label": e.label}


def _source_url(job: AnalysisJob, path: str, start: int | None = None, end: int | None = None) -> str:
    anchor = f"#L{start}-L{end}" if start and end and end != start else (f"#L{start}" if start else "")
    return f"https://github.com/{job.repository.full_name}/blob/{job.commit_sha}/{path}{anchor}"


def _page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 500)), max(0, offset)


# ------------------------------------------------------------------------------ analyses
@router.post("/analyses", status_code=202)
def create_analysis(body: CreateAnalysisBody, request: Request, response: Response, user: CurrentUser, db: DB,
                    gh: Annotated[GitHubClient, Depends(github_dep)], orch: Annotated[Orchestrator, Depends(orchestrator_dep)],
                    s: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    quotas.enforce(db, user, "analysis", s)
    try:
        job, created = jobsvc.submit_analysis(db, user, body.url, gh, s, request_id=request.state.request_id)
    finally:
        gh.close()
    db.commit()
    if created:
        jobsvc.trigger_analysis(db, job, orch)
        db.commit()
    elif job.state == "READY":
        response.status_code = 200
    out = analysis_dict(job)
    out["reused"] = not created
    return out


@router.get("/analyses")
def list_analyses(user: CurrentUser, db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    total = db.execute(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.owner_id == user.id)).scalar_one()
    rows = db.execute(select(AnalysisJob).where(AnalysisJob.owner_id == user.id).order_by(AnalysisJob.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return {"items": [analysis_dict(j) for j in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/analyses/{analysis_id}")
def get_analysis(job: OwnedJob, db: DB) -> dict[str, Any]:
    return analysis_dict(job, db, detail=True)


@router.post("/analyses/{analysis_id}/retry", status_code=202)
def retry(job: OwnedJob, user: CurrentUser, db: DB, orch: Annotated[Orchestrator, Depends(orchestrator_dep)]) -> dict[str, Any]:
    job = jobsvc.retry_analysis(db, user, job)
    db.commit()
    jobsvc.trigger_analysis(db, job, orch)
    db.commit()
    return analysis_dict(job)


@router.post("/analyses/{analysis_id}/reindex", status_code=202)
def reindex(job: OwnedJob, user: CurrentUser, db: DB, orch: Annotated[Orchestrator, Depends(orchestrator_dep)]) -> dict[str, Any]:
    job = jobsvc.reindex_analysis(db, user, job)
    db.commit()
    jobsvc.trigger_analysis(db, job, orch)
    db.commit()
    return analysis_dict(job)


@router.post("/analyses/{analysis_id}/cancel")
def cancel(job: OwnedJob, user: CurrentUser, db: DB) -> dict[str, Any]:
    job = jobsvc.cancel_analysis(db, user, job)
    db.commit()
    return analysis_dict(job)


@router.delete("/analyses/{analysis_id}", status_code=204)
def delete_analysis_route(job: OwnedJob, user: CurrentUser, db: DB) -> Response:
    jobsvc.delete_analysis(db, user, job)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------------------ graph
@router.get("/analyses/{analysis_id}/graph")
def graph(job: OwnedJob, db: DB, types: str | None = None, relations: str | None = None, q: str | None = Query(None, max_length=100),
          path: str | None = Query(None, max_length=500), limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    limit, offset = _page(limit, offset)
    cond = [CodeNode.analysis_id == job.id]
    if types:
        tl = [t for t in types.split(",") if t]
        if any(t not in NODE_TYPES for t in tl):
            raise ApiError("VALIDATION_ERROR", "Unknown node type filter.")
        cond.append(CodeNode.type.in_(tl))
    if q:
        like = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append(or_(CodeNode.name.ilike(like), CodeNode.qualified_name.ilike(like), CodeNode.path.ilike(like)))
    if path:
        cond.append(CodeNode.path == path)
    total = db.execute(select(func.count()).select_from(CodeNode).where(*cond)).scalar_one()
    nodes = db.execute(select(CodeNode).where(*cond).order_by(CodeNode.type, CodeNode.qualified_name).limit(limit).offset(offset)).scalars().all()
    ids = [n.id for n in nodes]
    ecnd = [CodeEdge.analysis_id == job.id, CodeEdge.source_id.in_(ids), CodeEdge.target_id.in_(ids)]
    if relations:
        rl = [r for r in relations.split(",") if r]
        if any(r not in RELATIONS for r in rl):
            raise ApiError("VALIDATION_ERROR", "Unknown relation filter.")
        ecnd.append(CodeEdge.relation.in_(rl))
    edges = db.execute(select(CodeEdge).where(*ecnd).limit(5000)).scalars().all() if ids else []
    return {"nodes": [node_dict(n) for n in nodes], "edges": [edge_dict(e) for e in edges], "total_nodes": total, "limit": limit, "offset": offset}


@router.get("/analyses/{analysis_id}/graph/diagram")
def diagram(job: OwnedJob, db: DB, view: str = Query("modules", pattern="^(modules|routes|models)$"), limit: int = Query(40, ge=5, le=80)) -> dict[str, Any]:
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "The graph is not ready yet.")
    return build_diagram(db, job.id, view, limit)


@router.get("/analyses/{analysis_id}/graph/flow")
def graph_flow(job: OwnedJob, db: DB, limit: int = Query(70, ge=10, le=200), focus: str | None = Query(None, max_length=500),
               include_tests: bool = False, include_external: bool = True) -> dict[str, Any]:
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "The graph is not ready yet.")
    return build_file_flow(db, job.id, limit=limit, focus=focus, include_tests=include_tests, include_external=include_external)


@router.get("/analyses/{analysis_id}/graph/trace")
def graph_trace(job: OwnedJob, db: DB, node_id: uuid.UUID, depth: int = Query(3, ge=1, le=4)) -> dict[str, Any]:
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "The graph is not ready yet.")
    return build_trace(db, job.id, node_id, depth)


@router.get("/analyses/{analysis_id}/graph/nodes/{node_id}")
def graph_node(job: OwnedJob, node_id: uuid.UUID, db: DB) -> dict[str, Any]:
    n = db.get(CodeNode, node_id)
    if n is None or n.analysis_id != job.id:
        raise ApiError("NOT_FOUND", "Node not found.")
    out_e = db.execute(select(CodeEdge).where(CodeEdge.analysis_id == job.id, CodeEdge.source_id == n.id, CodeEdge.relation != "contains").limit(100)).scalars().all()
    in_e = db.execute(select(CodeEdge).where(CodeEdge.analysis_id == job.id, CodeEdge.target_id == n.id, CodeEdge.relation != "contains").limit(100)).scalars().all()
    other_ids = {e.target_id for e in out_e} | {e.source_id for e in in_e}
    others = {x.id: x for x in db.execute(select(CodeNode).where(CodeNode.id.in_(list(other_ids)))).scalars()} if other_ids else {}

    def brief(x: CodeNode) -> dict[str, Any]:
        return {"id": str(x.id), "type": x.type, "name": x.name, "path": x.path, "start_line": x.start_line, "end_line": x.end_line,
                "unresolved": bool(x.meta.get("unresolved"))}
    file_row = db.execute(select(AnalysisFile.id).where(AnalysisFile.analysis_id == job.id, AnalysisFile.path == n.path)).scalar_one_or_none() if n.path else None
    return {"node": node_dict(n), "file_id": str(file_row) if file_row else None,
            "source_url": _source_url(job, n.path, n.start_line, n.end_line) if n.path else None,
            "outgoing": [{**edge_dict(e), "node": brief(others[e.target_id])} for e in out_e if e.target_id in others],
            "incoming": [{**edge_dict(e), "node": brief(others[e.source_id])} for e in in_e if e.source_id in others]}


# ------------------------------------------------------------------------------ readiness
@router.get("/analyses/{analysis_id}/map")
def code_map(job: OwnedJob, db: DB) -> dict[str, Any]:
    """Architecture-first map: areas -> groups -> files, with lifted file-to-file links."""
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "The code graph is not ready yet.")
    return codemap.build_map(db, job.id)


@router.get("/analyses/{analysis_id}/readiness")
def readiness(job: OwnedJob, category: str | None = Query(None, pattern="^(testing|error_handling|security|configuration|logging|maintainability)$"),
              severity: str | None = Query(None, pattern="^(critical|high|medium|low|info)$"), min_confidence: str | None = Query(None, pattern="^(high|medium|low)$"),
              kind: str | None = Query(None, pattern="^(observed|potential_risk|absence|coverage_gap|metric)$")) -> dict[str, Any]:
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "The report is available once the code graph has been built.")
    rep = (job.summary or {}).get("readiness")
    if not rep:
        return {"available": False, "reason": "This analysis was produced by an older analyzer version. Re-run the analysis to generate the report.", "findings": []}
    order = ["high", "medium", "low"]
    out = [f for f in rep["findings"] if (not category or f["category"] == category) and (not severity or f["severity"] == severity) and (not kind or f["kind"] == kind)
           and (not min_confidence or order.index(f["confidence"]) <= order.index(min_confidence))]
    return {"available": True, "commit_sha": job.commit_sha, **{k: rep[k] for k in ("version", "disclaimer", "not_assessed", "partial_analysis", "summary")},
            "findings": [{**f, "commit_sha": job.commit_sha} for f in out], "filtered": len(out) != len(rep["findings"])}


# ------------------------------------------------------------------------------ architecture intelligence
@router.get("/analyses/{analysis_id}/architecture")
def architecture(job: OwnedJob, db: DB) -> dict[str, Any]:
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "Architecture is available once the code graph has been built.")
    return archsvc.describe(archsvc.snapshot(db, job))


@router.get("/analyses/{analysis_id}/architecture/history")
def architecture_history(job: OwnedJob, db: DB, limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "Architecture is available once the code graph has been built.")
    return {"repository": job.repository.full_name, "points": archsvc.history(db, job, limit), "limitations": archsvc.LIMITATIONS}


@router.get("/analyses/{analysis_id}/architecture/drift")
def architecture_drift(job: OwnedJob, user: CurrentUser, db: DB, base: uuid.UUID | None = None) -> dict[str, Any]:
    if not job.graph_complete:
        raise ApiError("INVALID_STATE", "Architecture is available once the code graph has been built.")
    prev = archsvc.same_repo_job(db, user.id, job.repository_id, base) if base else archsvc.previous_job(db, job)
    if prev is None or prev.id == job.id:
        if base:
            raise ApiError("NOT_FOUND")
        return {"available": False, "reason": "No earlier analysis of this repository at a different commit. Analyze a newer commit to see drift.", "limitations": archsvc.LIMITATIONS}
    return {"available": True, **archsvc.drift(db, prev, job)}


# ------------------------------------------------------------------------------ change impact
@router.post("/analyses/{analysis_id}/impact")
def impact(body: ImpactBody, job: OwnedJob, user: CurrentUser, db: DB, gh: Annotated[GitHubClient, Depends(github_dep)], s: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    """Compare a base commit/branch (default: the analyzed commit's first parent) with the analyzed commit and map the change onto the graph."""
    if not job.graph_complete or job.state != "READY":
        raise ApiError("INVALID_STATE", "Change impact is available once the analysis is ready.")
    base = (body.base or "").strip() or None
    if base is not None and not GitHubClient.valid_ref(base):
        raise ApiError("INVALID_REF")
    rate_limit(db, "impact", str(user.id), s.impact_per_hour, 3600)
    repo = job.repository
    try:
        if base is None:
            base = gh.get_parent_sha(repo.owner, repo.name, job.commit_sha)
            if base is None:
                raise ApiError("INVALID_REF", "This commit has no parent to compare against; enter a base commit or branch.")
        cmp = gh.compare(repo.owner, repo.name, base, job.commit_sha)
    except JobError as exc:
        db.commit()  # keep the rate-limit event
        raise ApiError(exc.code, info(exc.code).message, headers={"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None) from None
    finally:
        gh.close()
    result = compute_impact(db, job.id, cmp, base, cmp.get("base_sha"), job.commit_sha, repo.full_name)
    rep = ImpactReport(analysis_id=job.id, base_ref=base[:255], base_sha=cmp.get("base_sha"), head_sha=job.commit_sha, result=result)
    db.add(rep)
    db.flush()
    old = db.execute(select(ImpactReport.id).where(ImpactReport.analysis_id == job.id).order_by(ImpactReport.created_at.desc()).offset(20)).scalars().all()
    if old:
        db.execute(delete(ImpactReport).where(ImpactReport.id.in_(old)))
    jobsvc.audit(db, "impact.compute", actor=user, resource_type="analysis", resource_id=job.id, base=base[:60])
    db.commit()
    return {"id": str(rep.id), "created_at": rep.created_at.isoformat(), **result}


@router.get("/analyses/{analysis_id}/impact")
def impact_list(job: OwnedJob, db: DB) -> dict[str, Any]:
    rows = db.execute(select(ImpactReport).where(ImpactReport.analysis_id == job.id).order_by(ImpactReport.created_at.desc()).limit(20)).scalars().all()
    return {"items": [{"id": str(r.id), "base_ref": r.base_ref, "base_sha": r.base_sha, "created_at": r.created_at.isoformat(), "summary": r.result.get("summary", {})} for r in rows]}


@router.get("/analyses/{analysis_id}/impact/{report_id}")
def impact_detail(job: OwnedJob, report_id: uuid.UUID, db: DB) -> dict[str, Any]:
    r = db.get(ImpactReport, report_id)
    if r is None or r.analysis_id != job.id:
        raise ApiError("NOT_FOUND", "Report not found.")
    return {"id": str(r.id), "created_at": r.created_at.isoformat(), **r.result}


# ------------------------------------------------------------------------------ files
@router.get("/analyses/{analysis_id}/files")
def files(job: OwnedJob, db: DB, q: str | None = Query(None, max_length=100), kind: str | None = Query(None, pattern="^(python|web|support|other)$"),
          status: str | None = Query(None, pattern="^(analyzed|parse_error|excluded|skipped_limit)(,(analyzed|parse_error|excluded|skipped_limit))*$"), limit: int = Query(200, ge=1, le=500),
          offset: int = Query(0, ge=0)) -> dict[str, Any]:
    cond = [AnalysisFile.analysis_id == job.id]
    if q:
        cond.append(AnalysisFile.path.ilike("%" + q.replace("%", "\\%").replace("_", "\\_") + "%"))
    if kind:
        cond.append(AnalysisFile.kind == kind)
    if status:
        cond.append(AnalysisFile.status.in_(status.split(",")))
    total = db.execute(select(func.count()).select_from(AnalysisFile).where(*cond)).scalar_one()
    rows = db.execute(select(AnalysisFile).where(*cond).order_by(AnalysisFile.path).limit(limit).offset(offset)).scalars().all()
    return {"items": [{"id": str(f.id), "path": f.path, "kind": f.kind, "status": f.status, "excluded_reason": f.excluded_reason,
                       "size_bytes": f.size_bytes, "line_count": f.line_count, "explanation": f.explanation,
                       "explanation_source": f.explanation_source, "parse_warning": f.parse_warning,
                       "has_content": f.content is not None, "redacted": f.redaction_count > 0} for f in rows],
            "total": total, "limit": limit, "offset": offset}


@router.get("/analyses/{analysis_id}/files/{file_id}")
def file_detail(job: OwnedJob, file_id: uuid.UUID, db: DB) -> dict[str, Any]:
    f = db.get(AnalysisFile, file_id)
    if f is None or f.analysis_id != job.id:
        raise ApiError("NOT_FOUND", "File not found.")
    symbols = db.execute(select(CodeNode).where(CodeNode.analysis_id == job.id, CodeNode.path == f.path,
                                                CodeNode.type.in_(("function", "class", "model", "route", "worker"))).order_by(CodeNode.start_line)).scalars().all()
    mod = db.execute(select(CodeNode).where(CodeNode.analysis_id == job.id, CodeNode.path == f.path, CodeNode.type.in_(("module", "test")))).scalars().first()
    rel: dict[str, list[dict[str, Any]]] = {"imports": [], "imported_by": [], "tested_by": [], "configured_by": [], "calls_api": []}
    if mod:
        for e, other_id, key in [(e, e.target_id, "out") for e in db.execute(select(CodeEdge).where(CodeEdge.source_id == mod.id, CodeEdge.relation.in_(("imports", "configured_by", "calls_api"))).limit(200)).scalars()] + \
                                [(e, e.source_id, "in") for e in db.execute(select(CodeEdge).where(CodeEdge.target_id == mod.id, CodeEdge.relation.in_(("imports", "tested_by"))).limit(200)).scalars()]:
            o = db.get(CodeNode, other_id)
            if not o:
                continue
            bucket = ("calls_api" if e.relation == "calls_api" else "imports" if e.relation == "imports" and key == "out" else "imported_by" if e.relation == "imports" else
                      "tested_by" if e.relation == "tested_by" else "configured_by")
            rel[bucket].append({"node_id": str(o.id), "name": o.name, "path": o.path, "resolution": e.resolution, "label": e.label,
                                "line": (e.evidence[0]["start_line"] if e.evidence else None), "unresolved": bool(o.meta.get("unresolved"))})
    return {"id": str(f.id), "path": f.path, "kind": f.kind, "status": f.status, "excluded_reason": f.excluded_reason, "size_bytes": f.size_bytes,
            "line_count": f.line_count, "content": f.content, "redacted": f.redaction_count > 0, "contains_secret_like": f.has_secret_like,
            "explanation": f.explanation, "explanation_source": f.explanation_source, "parse_warning": f.parse_warning,
            "commit_sha": job.commit_sha, "source_url": _source_url(job, f.path), "module_node_id": str(mod.id) if mod else None,
            "symbols": [{"id": str(n.id), "type": n.type, "name": n.name, "start_line": n.start_line, "end_line": n.end_line,
                         "explanation": n.explanation, "facts": n.facts[:3]} for n in symbols], "relationships": rel}


# ------------------------------------------------------------------------------ docs
def _final_doc(db: Any, job: AnalysisJob) -> Documentation | None:
    return db.execute(select(Documentation).where(Documentation.analysis_id == job.id, Documentation.status.in_(("READY", "PARTIAL")))
                      .order_by(Documentation.version.desc())).scalars().first()


@router.get("/analyses/{analysis_id}/docs")
def get_docs(job: OwnedJob, db: DB) -> dict[str, Any]:
    final = _final_doc(db, job)
    latest = db.execute(select(Documentation).where(Documentation.analysis_id == job.id).order_by(Documentation.version.desc())).scalars().first()
    if latest is None:
        return {"status": "NONE", "document": None, "regenerating": False}
    regenerating = latest.status in {"PENDING", "GENERATING"} and final is not None
    doc = final or latest
    stats = {k: v for k, v in (doc.stats or {}).items() if k != "overview"}
    return {"status": doc.status, "regenerating": regenerating, "pending_status": latest.status if latest is not doc else None,
            "document": {"id": str(doc.id), "version": doc.version, "status": doc.status, "ai_status": doc.ai_status, "markdown": doc.markdown,
                         "diagrams": doc.diagrams, "gaps": doc.gaps, "stats": stats, "error_code": doc.error_code,
                         "error_message": info(doc.error_code).message if doc.error_code else None,
                         "created_at": doc.created_at.isoformat(), "updated_at": doc.updated_at.isoformat(),
                         "commit_sha": job.commit_sha}}


@router.get("/analyses/{analysis_id}/docs/download")
def download_docs(job: OwnedJob, db: DB) -> PlainTextResponse:
    doc = _final_doc(db, job)
    if doc is None or not doc.markdown:
        raise ApiError("INVALID_STATE", "Documentation is not available yet.")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", job.repository.full_name).strip("-")
    return PlainTextResponse(doc.markdown, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="raven-{safe}-{job.commit_sha[:7]}.md"'})


@router.post("/analyses/{analysis_id}/docs/generate", status_code=202)
def generate_docs(job: OwnedJob, user: CurrentUser, db: DB, orch: Annotated[Orchestrator, Depends(orchestrator_dep)]) -> dict[str, Any]:
    doc = jobsvc.request_docs(db, user, job, orch)
    db.commit()
    if doc.trigger_attempts == 0:
        jobsvc.trigger_docs(db, doc, orch)
        db.commit()
    return {"doc_id": str(doc.id), "version": doc.version, "status": doc.status}


# ------------------------------------------------------------------------------ chat
@router.post("/analyses/{analysis_id}/chat")
def chat(body: ChatBody, job: OwnedJob, user: CurrentUser, db: DB, orch: Annotated[Orchestrator, Depends(orchestrator_dep)],
         s: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    quotas.enforce(db, user, "question", s)
    um, am = qasvc.create_question(db, user, job, body.message, s)
    if qasvc.serve_from_cache(db, um, am, job, s):
        db.commit()
        return {"question": qasvc.message_dict(um), "answer": qasvc.message_dict(am)}
    db.commit()
    try:
        orch.run_qa({"analysis_id": str(job.id), "message_id": str(am.id)})
    except ApiError as exc:
        fresh = db.get(ChatMessage, am.id)
        if fresh is not None and fresh.status == "pending":
            fresh.status, fresh.error_code, fresh.content = "failed", exc.code, exc.message
            db.commit()
        raise
    db.expire_all()
    done = db.get(ChatMessage, am.id)
    if done is None or done.status != "complete":
        if done is not None and done.status == "pending":
            done.status, done.error_code, done.content = "failed", "WORKFLOW_FAILED", info("WORKFLOW_FAILED").message
            db.commit()
        raise ApiError("WORKFLOW_FAILED")
    return {"question": qasvc.message_dict(um), "answer": qasvc.message_dict(done)}


@router.get("/analyses/{analysis_id}/chat")
def chat_history(job: OwnedJob, user: CurrentUser, db: DB, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    cond = [ChatMessage.analysis_id == job.id, ChatMessage.owner_id == user.id, ChatMessage.status != "pending"]
    total = db.execute(select(func.count()).select_from(ChatMessage).where(*cond)).scalar_one()
    rows = db.execute(select(ChatMessage).where(*cond).order_by(ChatMessage.created_at, ChatMessage.id).limit(limit).offset(offset)).scalars().all()
    return {"items": [qasvc.message_dict(m) for m in rows], "total": total, "limit": limit, "offset": offset}


@router.delete("/analyses/{analysis_id}/chat", status_code=204)
def clear_chat(job: OwnedJob, user: CurrentUser, db: DB) -> Response:
    db.execute(delete(ChatMessage).where(ChatMessage.analysis_id == job.id, ChatMessage.owner_id == user.id))
    jobsvc.audit(db, "chat.clear", actor=user, resource_type="analysis", resource_id=job.id)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------------------ status
@router.get("/status")
def status(user: CurrentUser, s: Annotated[Settings, Depends(settings_dep)], orch: Annotated[Orchestrator, Depends(orchestrator_dep)], db: DB) -> dict[str, Any]:
    db.execute(select(1))
    return {
        "version": "1.0.0", "environment": s.app_env,
        "llm": {"provider": s.llm_provider, "configured": s.llm_configured, "model": s.llm_model if s.llm_configured else None},
        "orchestrator": orch.health(), "database": {"reachable": True},
        "github": {"authenticated": bool(s.github_token)},
        "limits": {"max_repository_files": s.max_repository_files, "max_source_file_bytes": s.max_source_file_bytes,
                   "max_total_source_bytes": s.max_total_source_bytes, "max_python_files": s.max_python_files,
                   "max_analysis_seconds": s.max_analysis_seconds, "max_concurrent_analyses": s.max_concurrent_analyses,
                   "max_llm_calls_per_analysis": s.max_llm_calls_per_analysis, "analyses_per_hour": s.analyses_per_hour},
    }
