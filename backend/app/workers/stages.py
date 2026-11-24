"""Worker stage executors. Each stage reads its inputs from PostgreSQL and writes idempotent outputs,
so a stage can be re-run after a crash or retry without duplicating artifacts."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.analysis.archive import Limits, read_archive
from app.analysis.graph import ANALYZER_VERSION, FileFacts, build_graph, stable_uuid
from app.analysis.readiness import build_readiness
from app.analysis.pyparse import extract_facts, parse_issue_warning, parse_warning_for
from app.analysis.webparse import extract_web_facts
from app.core.config import Settings, get_settings
from app.core.db import new_session
from app.core.errors import JobError
from app.core.logging import analysis_id_var, log, stage_var
from app.models import AnalysisFile, AnalysisJob, CodeEdge, CodeNode, utcnow
from app.services import embeddings, incremental
from app.services.github import GitHubClient
from app.services.jobs import backoff_seconds
from app.services.state import lock_job, transition, update_progress

logger = logging.getLogger("raven.worker")
BATCH = 1000


def limits_from(s: Settings) -> Limits:
    return Limits(s.max_repository_files, s.max_source_file_bytes, s.max_total_source_bytes, s.max_python_files,
                  s.max_archive_bytes, s.max_archive_uncompressed_bytes, s.max_web_files, s.max_web_file_bytes, s.max_web_total_bytes)


class Cancelled(Exception):
    pass


def _check_cancel(db: Session, job_id: uuid.UUID) -> None:
    db.expire_all()
    j = db.get(AnalysisJob, job_id)
    if j and j.cancel_requested:
        raise Cancelled()


def _stage_time(summary: dict[str, Any], name: str, started: float) -> None:
    summary.setdefault("stage_seconds", {})[name] = round(time.monotonic() - started, 2)


def record_stage_time(job_id: uuid.UUID, name: str, seconds: float) -> None:
    """Accumulate a named timing into summary.stage_seconds (used by stages that run outside the worker driver, e.g. docs)."""
    with new_session() as db:
        job = lock_job(db, job_id)
        if job is None:
            return
        summary = dict(job.summary or {})
        st = dict(summary.get("stage_seconds") or {})
        st[name] = round(st.get(name, 0) + seconds, 2)
        summary["stage_seconds"] = st
        job.summary = summary
        db.commit()


# ---------------------------------------------------------------------------------- fetch
def stage_fetch(job_id: uuid.UUID, s: Settings, github: GitHubClient, deadline: float) -> None:
    stage_var.set("FETCHING")
    t0 = time.monotonic()
    with new_session() as db:
        job = db.get(AnalysisJob, job_id)
        assert job is not None
        owner, name, sha = job.repository.owner, job.repository.name, job.commit_sha
    with github.open_archive(owner, name, sha) as chunks:
        result = read_archive(chunks, limits_from(s), deadline)
    with new_session() as db:
        job = lock_job(db, job_id)
        assert job is not None
        db.execute(delete(AnalysisFile).where(AnalysisFile.analysis_id == job_id))
        rows = []
        for e in result.entries:
            rows.append({
                "id": stable_uuid(job_id, f"file:{e.path}"), "analysis_id": job_id, "path": e.path, "kind": e.kind,
                "status": e.status, "excluded_reason": e.excluded_reason, "size_bytes": e.size, "line_count": e.line_count,
                "content_sha256": e.sha256, "content": e.content, "has_secret_like": e.has_secret_like,
                "redaction_count": e.redaction_count, "redaction_lines": e.redaction_lines or None,
            })
        for i in range(0, len(rows), BATCH):
            db.execute(insert(AnalysisFile), rows[i:i + BATCH])
        st = result.stats
        summary = dict(job.summary or {})
        summary["inventory"] = {
            "files_considered": st.considered, "python_found": st.python_found, "python_analyzed": st.python_analyzed, "web_found": st.web_found, "web_analyzed": st.web_analyzed,
            "excluded_by_reason": st.excluded, "source_bytes": st.total_source_bytes,
            "redacted_files": sum(1 for e in result.entries if e.redaction_count), "secret_bearing_files": sum(1 for e in result.entries if e.has_secret_like),
        }
        summary["incremental"] = incremental.plan(db, job, {e.path: e.sha256 for e in result.entries if e.sha256}, bool(summary.get("force_full")))
        summary["partial"] = result.partial
        summary["partial_reasons"] = result.partial_reasons
        _stage_time(summary, "fetch", t0)
        job.summary = summary
        update_progress(db, job, files_considered=st.considered, python_files=st.python_analyzed)
        db.commit()
    log(logger, "stage_complete", stage="FETCHING", duration=round(time.monotonic() - t0, 2), files=st.considered,
        python=st.python_analyzed, excluded=sum(st.excluded.values()), partial=result.partial)


# ---------------------------------------------------------------------------------- parse
def stage_parse(job_id: uuid.UUID, s: Settings, deadline: float) -> None:
    stage_var.set("PARSING")
    t0 = time.monotonic()
    parsed = failed = partial = compat = reused = 0
    with new_session() as db:
        base_id = ((db.get(AnalysisJob, job_id).summary or {}).get("incremental") or {}).get("base_analysis_id")
        prior: dict[tuple[str, str], Any] = {}
        if base_id:  # unchanged (same path, same content) files keep the facts parsed for the base commit
            prior = {(r.path, r.content_sha256): (r.facts, r.status, r.parse_warning) for r in db.execute(select(
                AnalysisFile.path, AnalysisFile.content_sha256, AnalysisFile.facts, AnalysisFile.status, AnalysisFile.parse_warning).where(
                AnalysisFile.analysis_id == uuid.UUID(base_id), AnalysisFile.kind.in_(("python", "web")),
                AnalysisFile.status.in_(("analyzed", "parse_error")), AnalysisFile.content_sha256.is_not(None))).all()}
        ids = db.execute(select(AnalysisFile.id).where(AnalysisFile.analysis_id == job_id, AnalysisFile.kind.in_(("python", "web")),
                                                         AnalysisFile.status.in_(("analyzed", "parse_error"))).order_by(AnalysisFile.path)).scalars().all()
        total = len(ids)
        for n, fid in enumerate(ids, 1):
            if time.monotonic() > deadline:
                raise JobError("ANALYSIS_TIMEOUT", "deadline during parse")
            f = db.get(AnalysisFile, fid)
            assert f is not None
            hit = prior.get((f.path, f.content_sha256 or ""))
            try:
                if hit is not None and hit[1] == "analyzed" and hit[0] is not None:
                    f.facts, reused = hit[0], reused + 1
                else:
                    f.facts = extract_facts(f.content or "", f.path) if f.kind == "python" else extract_web_facts(f.path, f.content or "")
                issues = (f.facts.get("parse_issues") or []) if f.kind == "python" else []
                f.status, f.parse_warning = "analyzed", parse_issue_warning(issues)
                if f.kind == "python":
                    parsed += 1
                    partial += any(i["kind"] == "skipped" for i in issues)
                    compat += any(i["kind"] == "compat_rewrite" for i in issues)
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                f.facts, f.status, f.parse_warning = None, "parse_error", parse_warning_for(exc)
                if f.kind == "python":
                    failed += 1
            if n % 50 == 0 or n == total:
                job = db.get(AnalysisJob, job_id)
                assert job is not None
                update_progress(db, job, files_parsed=n, files_total=total)
                db.commit()
                _check_cancel(db, job_id)
        job = lock_job(db, job_id)
        assert job is not None
        summary = dict(job.summary or {})
        summary["parse"] = {"parsed": parsed, "failed": failed, "partial": partial, "compat_rewrite": compat, "reused_from_base": reused, "reparsed": total - reused}
        _stage_time(summary, "parse", t0)
        job.summary = summary
        db.commit()
    if parsed == 0:
        raise JobError("NO_PYTHON_FILES", "no parseable python files")
    log(logger, "stage_complete", stage="PARSING", duration=round(time.monotonic() - t0, 2), parsed=parsed, parse_failures=failed)


# ---------------------------------------------------------------------------------- graph
def _node_row(job_id: uuid.UUID, n: Any) -> dict[str, Any]:
    text = " ".join([n.name, n.qname, n.path or ""] + n.facts[:3])[:1500]
    return {"id": stable_uuid(job_id, f"node:{n.key}"), "analysis_id": job_id, "node_key": n.key, "type": n.type, "name": n.name,
            "qualified_name": n.qname, "path": n.path, "start_line": n.start, "end_line": n.end, "facts": n.facts, "meta": n.meta,
            "evidence": n.evidence, "search_text": text}


def stage_graph(job_id: uuid.UUID, s: Settings, deadline: float) -> None:
    stage_var.set("BUILDING_GRAPH")
    t0 = time.monotonic()
    with new_session() as db:
        job = db.get(AnalysisJob, job_id)
        assert job is not None
        full_name = job.repository.full_name
        job_summary = dict(job.summary or {})
        files = db.execute(select(AnalysisFile.path, AnalysisFile.kind, AnalysisFile.status, AnalysisFile.facts, AnalysisFile.line_count,
                                  AnalysisFile.size_bytes, AnalysisFile.excluded_reason, AnalysisFile.redaction_lines).where(AnalysisFile.analysis_id == job_id)).all()
        support = {r.path: r.content for r in db.execute(select(AnalysisFile.path, AnalysisFile.content).where(
            AnalysisFile.analysis_id == job_id, AnalysisFile.kind == "support")).all() if r.content}
    all_paths = [f.path for f in files if f.status != "excluded"]
    ffacts = [FileFacts(f.path, f.facts, f.line_count, f.size_bytes, f.status) for f in files if f.kind == "python" and f.status in ("analyzed", "parse_error")]
    wfacts = [FileFacts(f.path, f.facts, f.line_count, f.size_bytes, f.status) for f in files if f.kind == "web" and f.status == "analyzed"]
    t_build = time.monotonic()
    graph = build_graph(full_name, ffacts, all_paths, support, wfacts)
    redactions = {f.path: list(f.redaction_lines) for f in files if f.redaction_lines}
    partial = bool(job_summary.get("partial"))
    t_health = time.monotonic()
    readiness = build_readiness(ffacts, wfacts, graph, support, redactions, partial)
    t_health = time.monotonic() - t_health
    if time.monotonic() > deadline:
        raise JobError("ANALYSIS_TIMEOUT", "deadline during graph build")
    t_persist = time.monotonic()
    with new_session() as db:
        job = lock_job(db, job_id)
        assert job is not None
        db.execute(delete(CodeEdge).where(CodeEdge.analysis_id == job_id))
        db.execute(delete(CodeNode).where(CodeNode.analysis_id == job_id))
        node_rows = [_node_row(job_id, n) for n in graph.nodes]
        for i in range(0, len(node_rows), BATCH):
            db.execute(insert(CodeNode), node_rows[i:i + BATCH])
        id_of = {n.key: stable_uuid(job_id, f"node:{n.key}") for n in graph.nodes}
        edge_rows = [{"id": stable_uuid(job_id, f"edge:{e.key}"), "analysis_id": job_id, "edge_key": e.key, "source_id": id_of[e.source],
                      "target_id": id_of[e.target], "relation": e.relation, "resolution": e.resolution, "evidence": e.evidence, "label": e.label}
                     for e in graph.edges]
        for i in range(0, len(edge_rows), BATCH):
            db.execute(insert(CodeEdge), edge_rows[i:i + BATCH])
        # deterministic per-file explanations (AI replaces these later when available)
        for path, text in graph.file_summaries.items():
            db.execute(update(AnalysisFile).where(AnalysisFile.analysis_id == job_id, AnalysisFile.path == path,
                                                  AnalysisFile.explanation_source.is_distinct_from("ai")).values(explanation=text, explanation_source="deterministic"))
        summary = dict(job.summary or {})
        summary["graph"] = graph.stats
        summary["readiness"] = readiness
        summary["entry_points"] = graph.entry_points[:50]
        summary["gaps"] = graph.gaps[:200]
        _stage_time(summary, "graph", t0)
        summary["stage_seconds"]["graph_build"] = round(t_persist - t_build, 2)
        summary["stage_seconds"]["health"] = round(t_health, 2)
        summary["stage_seconds"]["persist"] = round(time.monotonic() - t_persist, 2)
        job.summary = summary
        job.graph_complete = True
        update_progress(db, job, nodes=graph.stats["node_count"], edges=graph.stats["edge_count"], routes=graph.stats["route_count"])
        db.commit()
    log(logger, "stage_complete", stage="BUILDING_GRAPH", duration=round(time.monotonic() - t0, 2), nodes=graph.stats["node_count"],
        edges=graph.stats["edge_count"], routes=graph.stats["route_count"])


def _base_id(job_id: uuid.UUID, model: str) -> uuid.UUID | None:
    """Base analysis whose vectors may be reused: only if they came from the same embedding model."""
    with new_session() as db:
        b = ((db.get(AnalysisJob, job_id).summary or {}).get("incremental") or {}).get("base_analysis_id")
        if not b:
            return None
        base = db.get(AnalysisJob, uuid.UUID(b))
        return base.id if base and (base.summary or {}).get("embeddings_model") == model else None


def stage_embed(job_id: uuid.UUID, s: Settings) -> None:
    """Optional: embed nodes for semantic retrieval. Never fails the analysis."""
    if not s.embeddings_configured:
        return
    try:
        t0 = time.monotonic()
        n = embeddings.embed_analysis(job_id, s, reuse_from=_base_id(job_id, s.embeddings_model))
        record_stage_time(job_id, "embeddings", time.monotonic() - t0)
        with new_session() as db:
            job = lock_job(db, job_id)
            job.summary = {**(job.summary or {}), "embeddings_model": s.embeddings_model, "embeddings_sent": n}
            db.commit()
        log(logger, "stage_complete", stage="EMBEDDINGS", embedded=n)
    except Exception as exc:  # noqa: BLE001  retrieval stays lexical if embedding fails
        log(logger, "embeddings_skipped", logging.WARNING, error_type=type(exc).__name__)


# ---------------------------------------------------------------------------------- driver
def _fail_or_retry(job_id: uuid.UUID, exc: JobError, s: Settings) -> None:
    with new_session() as db:
        job = lock_job(db, job_id)
        if job is None or job.state not in {"FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS"}:
            return
        if exc.retryable and job.attempt + 1 < s.max_stage_attempts:
            delay = backoff_seconds(job.attempt, s)
            if exc.retry_after:
                delay = min(max(delay, exc.retry_after), s.retry_max_seconds)
            job.retry_after = utcnow() + timedelta(seconds=delay)
            transition(db, job, "RETRYING", actor="worker", error_code=exc.code, note=f"attempt {job.attempt + 1}/{s.max_stage_attempts}")
            log(logger, "job_retrying", logging.WARNING, error_code=exc.code, attempt=job.attempt, delay=delay)
        else:
            code = exc.code
            note = "retries exhausted" if exc.retryable else None
            transition(db, job, "FAILED", actor="worker", error_code=code, note=note)
            log(logger, "job_failed", logging.ERROR, error_code=code, retryable=exc.retryable)
        db.commit()


def run_analysis_task(job_id: uuid.UUID, github_factory=GitHubClient, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    analysis_id_var.set(str(job_id))
    started = time.monotonic()
    deadline = started + s.max_analysis_seconds
    try:
        with new_session() as db:
            job = lock_job(db, job_id)
            if job is None or job.state != "FETCHING":
                return  # stale task (job cancelled, failed or already advanced)
            if job.cancel_requested:
                transition(db, job, "CANCELLED", actor="worker", note="cancel requested")
                db.commit()
                return
            reuse = job.graph_complete and job.analyzer_version == ANALYZER_VERSION
        if not reuse:
            gh = github_factory(s)
            try:
                stage_fetch(job_id, s, gh, deadline)
            finally:
                gh.close()
        _advance(job_id, "PARSING", "parsing")
        if not reuse:
            stage_parse(job_id, s, deadline)
        _advance(job_id, "BUILDING_GRAPH", "building graph")
        if not reuse:
            stage_graph(job_id, s, deadline)
            stage_embed(job_id, s)
        if not reuse:  # whatever isn't a named stage is orchestration/DB overhead
            with new_session() as db:
                st = (db.get(AnalysisJob, job_id).summary or {}).get("stage_seconds") or {}
            named = sum(st.get(k, 0) for k in ("fetch", "parse", "graph", "embeddings"))
            record_stage_time(job_id, "orchestration", max(0.0, time.monotonic() - started - named))
        log(logger, "analysis_graph_ready", reused_artifacts=reuse)
    except Cancelled:
        with new_session() as db:
            job = lock_job(db, job_id)
            if job and job.state in {"FETCHING", "PARSING", "BUILDING_GRAPH"}:
                transition(db, job, "CANCELLED", actor="worker", note="cancel requested")
                db.commit()
    except JobError as exc:
        _fail_or_retry(job_id, exc, s)
    except Exception as exc:  # noqa: BLE001
        log(logger, "stage_unexpected_error", logging.ERROR, error_type=type(exc).__name__)
        _fail_or_retry(job_id, JobError("INTERNAL_ANALYSIS_ERROR", type(exc).__name__), s)
    finally:
        stage_var.set(None)


def _advance(job_id: uuid.UUID, to_state: str, detail: str) -> None:
    with new_session() as db:
        job = lock_job(db, job_id)
        assert job is not None
        if job.cancel_requested:
            raise Cancelled()
        transition(db, job, to_state, actor="worker", detail=detail)
        db.commit()
