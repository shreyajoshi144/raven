"""Documentation tasks: bounded AI explanation batches (docs_explain) and Markdown assembly (docs_assemble)."""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.analysis.secrets import scrub_text
from app.core.config import Settings, get_settings
from app.core.db import new_session
from app.core.errors import JobError
from app.core.logging import analysis_id_var, log
from app.models import AnalysisFile, AnalysisJob, CodeEdge, CodeNode, Documentation, utcnow
from app.schemas.llm import ExplainBatch, Overview
from app.services.docs_builder import DocInput, build_docs
from app.workers.stages import record_stage_time
from app.services.llm import LLMBudget, LLMProvider, StructuredLLM, build_provider

logger = logging.getLogger("raven.docs")
MAX_FILES_EXPLAINED = 60
MAX_FILES_PER_BATCH = 12
EXCERPT_LINES = 110
STOP_CODES = {"LLM_NOT_CONFIGURED", "LLM_AUTH_FAILED", "LLM_RATE_LIMITED", "LLM_TIMEOUT", "LLM_PROVIDER_UNAVAILABLE", "LLM_BUDGET_EXCEEDED"}

EXPLAIN_SYSTEM = (
    "You are a senior engineer writing concise onboarding notes for developers new to a Python/FastAPI repository. "
    "For each file provided, explain in plain language what it is for, using ONLY the static facts and source excerpt given. "
    "Do not guess about code you cannot see. JSON schema: {\"explanations\":[{\"path\":str,\"summary\":str (<=500 chars),"
    "\"responsibilities\":[str] (<=5),\"symbols\":[{\"qualname\":str,\"summary\":str}] (<=6, only symbols listed in the static facts),"
    "\"citations\":[{\"path\":str,\"start_line\":int,\"end_line\":int}] (<=3, lines must exist in the file)}]}. "
    "Cite line ranges for the claims you make. Include exactly one entry per provided file."
)
OVERVIEW_SYSTEM = (
    "You write a short architecture overview of a repository for new developers, using ONLY the supplied static facts and file notes. "
    "JSON schema: {\"overview\":str (<=1500 chars),\"key_flows\":[str] (<=4),\"citations\":[{\"path\":str,\"start_line\":int,\"end_line\":int}] (<=6)}. "
    "Do not invent components, commands, routes or tables. Cite only files and line ranges that appear in the evidence."
)


def _digest(f: AnalysisFile, budget_lines: int) -> tuple[str, int]:
    facts = f.facts or {}
    out = [f"=== FILE: {f.path} ({f.line_count} lines) ==="]
    out.append("Static facts:")
    for r in facts.get("routes", [])[:12]:
        out.append(f"- route {'/'.join(r['methods'])} {r.get('path') or '?'} -> {r.get('handler') or r.get('handler_expr')} (line {r['line']})")
    for c in facts.get("classes", [])[:15]:
        out.append(f"- class {c['qualname']} bases={c['bases'][:3]} (lines {c['line']}-{c['end_line']})")
    for fn in facts.get("functions", [])[:25]:
        out.append(f"- {'async ' if fn['async'] else ''}def {fn['qualname']} (lines {fn['line']}-{fn['end_line']})")
    envs = sorted({e["name"] for e in facts.get("env_vars", [])})
    if envs:
        out.append("- environment variables read: " + ", ".join(envs[:10]))
    out.append("Source excerpt (line-numbered):")
    lines = (f.content or "").split("\n")
    keep: list[int]
    if len(lines) <= EXCERPT_LINES:
        keep = list(range(len(lines)))
    else:
        keep = list(range(30))
        for i, line in enumerate(lines):
            if i >= 30 and re.match(r"\s*(@|def |async def |class )", line) and len(keep) < EXCERPT_LINES:
                keep.append(i)
    used = len(out)
    for i in keep:
        if used >= budget_lines:
            break
        out.append(f"{i + 1}| {lines[i][:200]}")
        used += 1
    return "\n".join(out), used


def _score(f: AnalysisFile) -> float:
    facts = f.facts or {}
    sc = 5 * len(facts.get("apps", [])) + 4 * min(len(facts.get("routes", [])), 5) + min(len(facts.get("classes", [])), 5)
    sc += 0.3 * min(len(facts.get("functions", [])), 20) + (1 if facts.get("env_vars") else 0)
    if facts.get("entry", {}).get("main_guard"):
        sc += 2
    name = f.path.rsplit("/", 1)[-1]
    if name in {"main.py", "app.py", "asgi.py"}:
        sc += 3
    if re.search(r"(^|/)(tests?|test_[^/]*|conftest)", f.path):
        sc -= 6
    return sc


def _load_budget(job: AnalysisJob, s: Settings) -> LLMBudget:
    return LLMBudget(max_calls=s.max_llm_calls_per_analysis)


def run_docs_explain(task_payload: dict[str, Any], job_id: uuid.UUID, s: Settings | None = None,
                     provider: LLMProvider | None = None) -> None:
    s = s or get_settings()
    analysis_id_var.set(str(job_id))
    doc_id = uuid.UUID(task_payload["doc_id"])
    t0 = time.monotonic()
    deadline = t0 + s.max_docs_seconds
    stats: dict[str, Any] = {"batches_ok": 0, "batches_failed": 0, "files_explained": 0, "reason": None}
    budget = LLMBudget(max_calls=s.max_llm_calls_per_analysis)
    ai_status = "ok"
    overview: dict[str, Any] | None = None
    try:
        provider = provider or build_provider(s)
    except JobError as exc:
        _finish_explain(doc_id, "unavailable", {"reason": exc.code, **stats, "llm": budget.to_dict()}, None)
        return
    llm = StructuredLLM(provider, budget, s.llm_max_output_tokens)

    with new_session() as db:
        files = db.execute(select(AnalysisFile).where(AnalysisFile.analysis_id == job_id, AnalysisFile.kind == "python",
                                                        AnalysisFile.status == "analyzed", AnalysisFile.has_secret_like.is_(False))).scalars().all()
        todo = [f for f in files if f.facts and f.line_count >= 3 and f.explanation_source != "ai"]
        already = [f for f in files if f.explanation_source == "ai"]
        todo.sort(key=lambda f: (-_score(f), f.path))
        todo = todo[:MAX_FILES_EXPLAINED]
        batches: list[list[tuple[AnalysisFile, str]]] = []
        cur: list[tuple[AnalysisFile, str]] = []
        used = 0
        for f in todo:
            text, n = _digest(f, max(30, s.max_llm_lines_per_request // 4))
            if cur and (used + n > s.max_llm_lines_per_request or len(cur) >= MAX_FILES_PER_BATCH):
                batches.append(cur)
                cur, used = [], 0
            cur.append((f, text))
            used += n
        if cur:
            batches.append(cur)
        stop = False
        for batch in batches:
            if stop:
                break
            if time.monotonic() > deadline:
                stats["reason"] = "DOCS_TIME_BUDGET"
                ai_status = "partial"
                stop = True
                break
            allowed = {f.path: f.line_count for f, _ in batch}
            user = ("<repository_data>\n" + "\n\n".join(t for _, t in batch) + "\n</repository_data>\n\n"
                    "Return the JSON object now. Files in this batch: " + ", ".join(allowed))

            def check(out: ExplainBatch, allowed=allowed) -> str | None:
                got = {e.path for e in out.explanations}
                if not got <= set(allowed):
                    return f"unknown path(s): {sorted(got - set(allowed))[:3]}"
                for e in out.explanations:
                    for c in e.citations:
                        if c.path not in allowed or not (1 <= c.start_line <= c.end_line <= allowed[c.path]):
                            return f"invalid citation {c.path}:{c.start_line}-{c.end_line}"
                return None
            try:
                out = llm.structured(ExplainBatch, EXPLAIN_SYSTEM, user, max_repairs=2, semantic_check=check)
            except JobError as exc:
                stats["batches_failed"] += 1
                stats["reason"] = exc.code
                ai_status = "partial"
                if exc.code in STOP_CODES:
                    stop = True
                continue
            by_path = {f.path: f for f, _ in batch}
            for e in out.explanations:
                f = by_path.get(e.path)
                if not f:
                    continue
                text = scrub_text(e.summary + ("\n" + "\n".join("• " + r for r in e.responsibilities) if e.responsibilities else ""), 1500)
                f.explanation, f.explanation_source = text, "ai"
                node_texts = {sy.qualname: scrub_text(sy.summary, 400) for sy in e.symbols}
                db.execute(update(CodeNode).where(CodeNode.analysis_id == job_id, CodeNode.path == f.path,
                                                  CodeNode.type.in_(("module", "test"))).values(explanation=text, explanation_source="ai"))
                for qn, summ in node_texts.items():
                    db.execute(update(CodeNode).where(CodeNode.analysis_id == job_id, CodeNode.path == f.path, CodeNode.name == qn,
                                                      CodeNode.type.in_(("function", "class", "model"))).values(explanation=summ, explanation_source="ai"))
                stats["files_explained"] += 1
            stats["batches_ok"] += 1
            db.commit()

        if stats["batches_ok"] == 0 and (stats["batches_failed"] or todo) and not already:
            ai_status = "unavailable"
        elif stats["batches_failed"]:
            ai_status = "partial"

        # overview
        if ai_status != "unavailable" and not stop:
            job = db.get(AnalysisJob, job_id)
            assert job is not None
            overview = _overview(db, job, llm, files, stats)
            if overview is None and ai_status == "ok":
                ai_status = "partial"
    stats["llm"] = budget.to_dict()
    stats["seconds"] = round(time.monotonic() - t0, 2)
    _finish_explain(doc_id, ai_status, stats, overview)
    record_stage_time(job_id, "guide_ai", time.monotonic() - t0)
    log(logger, "docs_explain_done", ai_status=ai_status, files=stats["files_explained"], llm_calls=budget.calls)


def _overview(db: Session, job: AnalysisJob, llm: StructuredLLM, files: list[AnalysisFile], stats: dict[str, Any]) -> dict[str, Any] | None:
    g = (job.summary or {}).get("graph", {})
    routes = db.execute(select(CodeNode.name, CodeNode.path, CodeNode.start_line).where(CodeNode.analysis_id == job.id, CodeNode.type == "route").limit(12)).all()
    bounds = {f.path: f.line_count for f in files}
    notes = sorted((f for f in files if f.explanation), key=lambda f: -_score(f))[:15]
    facts = [f"repository: {job.repository.full_name}", f"python files analyzed: {len(files)}", f"frameworks (from imports): {g.get('detected_frameworks', [])}",
             f"routes: {g.get('route_count', 0)}", "entry points: " + "; ".join(f"{e['path']}:{e['line']} {e['reason']}" for e in (job.summary or {}).get("entry_points", [])[:6])]
    facts += [f"route {r.name} at {r.path}:{r.start_line}" for r in routes]
    facts += [f"file {f.path} ({f.line_count} lines): {(f.explanation or '')[:250]}" for f in notes]
    user = "<repository_data>\n" + "\n".join(facts) + "\n</repository_data>\nReturn the JSON object now."

    def check(o: Overview) -> str | None:
        for c in o.citations:
            if c.path not in bounds or not (1 <= c.start_line <= c.end_line <= bounds[c.path]):
                return f"invalid citation {c.path}:{c.start_line}-{c.end_line}"
        return None
    try:
        out = llm.structured(Overview, OVERVIEW_SYSTEM, user, max_repairs=2, semantic_check=check)
    except JobError as exc:
        stats["reason"] = stats.get("reason") or exc.code
        return None
    return {"overview": scrub_text(out.overview, 2000), "key_flows": [scrub_text(x, 300) for x in out.key_flows],
            "citations": [c.model_dump() for c in out.citations]}


def _finish_explain(doc_id: uuid.UUID, ai_status: str, stats: dict[str, Any], overview: dict[str, Any] | None) -> None:
    with new_session() as db:
        doc = db.get(Documentation, doc_id)
        if doc is None:
            return
        doc.ai_status = ai_status
        doc.stats = {**(doc.stats or {}), **stats, **({"overview": overview} if overview else {})}
        db.commit()


# ----------------------------------------------------------------------------------- assemble
def load_doc_input(db: Session, job: AnalysisJob, doc: Documentation) -> DocInput:
    files = [{"path": f.path, "kind": f.kind, "status": f.status, "line_count": f.line_count, "explanation": f.explanation,
              "explanation_source": f.explanation_source, "parse_warning": f.parse_warning, "excluded_reason": f.excluded_reason}
             for f in db.execute(select(AnalysisFile).where(AnalysisFile.analysis_id == job.id, AnalysisFile.status != "excluded")).scalars()]
    support = {r.path: r.content for r in db.execute(select(AnalysisFile.path, AnalysisFile.content).where(
        AnalysisFile.analysis_id == job.id, AnalysisFile.kind == "support")).all() if r.content}
    nodes = [{"id": str(n.id), "type": n.type, "name": n.name, "qname": n.qualified_name, "path": n.path, "start": n.start_line, "end": n.end_line,
              "facts": n.facts, "meta": n.meta, "evidence": n.evidence, "explanation": n.explanation}
             for n in db.execute(select(CodeNode).where(CodeNode.analysis_id == job.id)).scalars()]
    edges = [{"source": str(e.source_id), "target": str(e.target_id), "relation": e.relation, "resolution": e.resolution, "evidence": e.evidence, "label": e.label}
             for e in db.execute(select(CodeEdge).where(CodeEdge.analysis_id == job.id, CodeEdge.relation != "contains")).scalars()]
    stats = doc.stats or {}
    return DocInput(
        repo_full_name=job.repository.full_name, description=job.repository.description, primary_language=job.repository.primary_language,
        default_branch=job.default_branch, commit_sha=job.commit_sha, analyzer_version=job.analyzer_version,
        analyzed_at=(job.finished_at or job.updated_at or utcnow()).strftime("%Y-%m-%d %H:%M UTC"), summary=job.summary or {},
        files=files, nodes=nodes, edges=edges, support=support, overview=stats.get("overview"), ai_status=doc.ai_status,
        ai_reason=stats.get("reason"))


def run_docs_assemble(task_payload: dict[str, Any], job_id: uuid.UUID) -> None:
    analysis_id_var.set(str(job_id))
    t_start = time.monotonic()
    doc_id = uuid.UUID(task_payload["doc_id"])
    with new_session() as db:
        job = db.get(AnalysisJob, job_id)
        doc = db.get(Documentation, doc_id)
        if job is None or doc is None:
            return
        if doc.status in {"READY", "PARTIAL"} and doc.markdown:
            return  # idempotent re-run
        inp = load_doc_input(db, job, doc)
        out = build_docs(inp)
        gaps = list(out.gaps)
        if doc.ai_status in {"unavailable", "partial", "pending"}:
            gaps.append(f"AI explanations {'partly ' if doc.ai_status == 'partial' else ''}unavailable"
                        + (f" ({inp.ai_reason})" if inp.ai_reason else ""))
        doc.markdown, doc.diagrams, doc.gaps = out.markdown, out.diagrams, sorted(set(gaps))
        partial = bool(doc.ai_status != "ok" or (job.summary or {}).get("partial"))
        doc.status = "PARTIAL" if partial else "READY"
        doc.updated_at = utcnow()
        db.commit()
    record_stage_time(job_id, "guide_assemble", time.monotonic() - t_start)
    log(logger, "docs_assembled", status=doc.status, size=len(doc.markdown or ""))
