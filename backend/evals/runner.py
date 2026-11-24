"""Runs Raven's real pipeline on benchmark repositories and scores it.

System under test = the production code paths, unchanged:
  ingestion/parse/graph/readiness  app.workers.stages.run_analysis_task (GitHub served from the benchmark files by a mock transport)
  retrieval + answer               app.services.qa.internal_retrieve / internal_answer (exactly what the n8n Q&A workflow calls)
  change impact                    app.services.impact.compute_impact (GitHub compare replaced by the labelled change set)
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from evals import HARNESS_VERSION
from evals import metrics as M
from evals.benchmark import Benchmark, GroundTruth, content_sha256
from evals.judge import Judge, JudgeConfig, JudgeStatus, build_judge
from evals.usage import NoLLM, RateLimiter, RecordingProvider, UsageLedger, latency_stats

BACKEND = Path(__file__).resolve().parents[1]
SAFE_DB_MARKERS = ("eval", "test")


class EvalSetupError(RuntimeError):
    """Configuration problem the user must fix (exit code 2)."""


@dataclass
class RunConfig:
    version: str = "v1"
    suite: str = "smoke"  # smoke | full
    repos: list[str] | None = None
    sut: str = "retrieval_only"  # retrieval_only | live
    repeats: int = 1
    db_url: str | None = None
    reset_db: bool = True
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    sut_per_minute: float | None = 30.0


# ------------------------------------------------------------------ database
def configure_database(url: str | None) -> None:
    """Validate the URL and point Raven's settings at it (nothing is modified yet)."""
    if not url:
        raise EvalSetupError("EVAL_DATABASE_URL is not set. Point it at a dedicated, disposable PostgreSQL database whose name contains 'eval' or 'test'.")
    dbname = urlsplit(url).path.lstrip("/")
    if not any(m in dbname.lower() for m in SAFE_DB_MARKERS):
        raise EvalSetupError(f"Refusing to use database {dbname!r}: the evaluation drops and recreates its schema, so the name must contain 'eval' or 'test'.")
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    from app.core.config import reset_settings_cache
    from app.core.db import reset_engine
    reset_settings_cache()
    reset_engine()


def reset_schema() -> None:
    """Drop and recreate the schema, then migrate. Only ever runs against a database validated by configure_database()."""
    from sqlalchemy import text

    from app.core.db import get_engine
    with get_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, capture_output=True, text=True, env=os.environ.copy())
    if r.returncode != 0:
        raise EvalSetupError("alembic upgrade failed: " + r.stderr[-500:])


# ------------------------------------------------------------------ pipeline
def make_tarball(files: dict[str, bytes], prefix: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(files):
            info = tarfile.TarInfo(f"{prefix}/{path}")
            info.size, info.mtime = len(files[path]), 0
            tar.addfile(info, io.BytesIO(files[path]))
    return buf.getvalue()


@dataclass
class Analysis:
    job_id: uuid.UUID
    user_id: uuid.UUID
    commit_sha: str
    wall_s: float
    state: str
    error_code: str | None
    stage_seconds: dict[str, float]


def analyze(full_name: str, files: dict[str, bytes]) -> Analysis:
    import httpx
    from sqlalchemy import select

    from app.analysis.graph import ANALYZER_VERSION
    from app.core.config import get_settings
    from app.core.db import new_session
    from app.models import AnalysisJob, Repository, User
    from app.services.github import GitHubClient
    from app.services.state import transition
    from app.workers.stages import run_analysis_task

    sha = hashlib.sha1(content_sha256(files).encode()).hexdigest()  # deterministic per content
    owner, name = full_name.split("/")
    tar = make_tarball(files, f"{owner}-{name}-{sha[:7]}")

    def handler(request: httpx.Request) -> httpx.Response:
        if "/tarball/" in request.url.path:
            return httpx.Response(200, content=tar, headers={"content-type": "application/x-gzip"})
        return httpx.Response(404, json={"message": "Not Found"})

    with new_session() as db:
        user = User(email=f"eval-{uuid.uuid4().hex[:12]}@raven.invalid", password_hash="!disabled")
        repo = db.execute(select(Repository).where(Repository.provider == "github", Repository.full_name_lower == full_name.lower())).scalar_one_or_none()
        if repo is None:  # one row per repository, as in production, so repeated runs see identical inputs
            repo = Repository(provider="github", owner=owner, name=name, full_name=full_name, full_name_lower=full_name.lower(),
                              canonical_url=f"https://github.com/{full_name}", default_branch="main")
        db.add_all([user, repo])
        db.flush()
        job = AnalysisJob(owner_id=user.id, repository_id=repo.id, commit_sha=sha, default_branch="main", analyzer_version=ANALYZER_VERSION, idempotency_key=f"eval:{uuid.uuid4()}")
        db.add(job)
        db.flush()
        transition(db, job, "FETCHING", actor="n8n", detail="evaluation")
        job_id, user_id = job.id, user.id
        db.commit()
    t0 = time.perf_counter()
    run_analysis_task(job_id, github_factory=lambda s: GitHubClient(s, transport=httpx.MockTransport(handler)), settings=get_settings())
    wall = time.perf_counter() - t0
    with new_session() as db:
        job = db.get(AnalysisJob, job_id)
        return Analysis(job_id, user_id, sha, wall, job.state, job.error_code, dict((job.summary or {}).get("stage_seconds", {})))


def load_artifacts(job_id: uuid.UUID) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.db import new_session
    from app.models import AnalysisFile, AnalysisJob, CodeEdge, CodeNode
    with new_session() as db:
        job = db.get(AnalysisJob, job_id)
        nodes = [{"id": str(n.id), "type": n.type, "name": n.name, "path": n.path, "start_line": n.start_line, "meta": n.meta or {}}
                 for n in db.execute(select(CodeNode).where(CodeNode.analysis_id == job_id)).scalars()]
        edges = [{"source": str(e.source_id), "target": str(e.target_id), "relation": e.relation, "resolution": e.resolution}
                 for e in db.execute(select(CodeEdge).where(CodeEdge.analysis_id == job_id)).scalars()]
        files = {f.path: f.line_count for f in db.execute(select(AnalysisFile).where(AnalysisFile.analysis_id == job_id)).scalars() if f.content is not None}
        summary = job.summary or {}
    return {"nodes": nodes, "edges": edges, "line_counts": files, "entry_points": summary.get("entry_points", []),
            "readiness": (summary.get("readiness") or {}).get("findings", []), "graph_complete": job.graph_complete}


def run_impact(job_id: uuid.UUID, full_name: str, head_sha: str, changed: list[dict[str, Any]]) -> tuple[dict[str, Any], float]:
    from app.core.db import new_session
    from app.services.impact import compute_impact
    compare = {"files": [{**c, "previous_path": None} for c in changed], "status": "ahead", "ahead_by": 1, "truncated": False, "base_sha": "0" * 40}
    with new_session() as db:
        t0 = time.perf_counter()
        res = compute_impact(db, job_id, compare, "benchmark-base", "0" * 40, head_sha, full_name)
        return res, time.perf_counter() - t0


def ask(job_id: uuid.UUID, user_id: uuid.UUID, question: str, provider: Any) -> dict[str, Any]:
    from app.core.config import get_settings
    from app.core.db import new_session
    from app.models import ChatMessage
    from app.services import qa as qasvc
    with new_session() as db:
        um = ChatMessage(owner_id=user_id, analysis_id=job_id, role="user", content=question, status="complete")
        db.add(um)
        db.flush()
        am = ChatMessage(owner_id=user_id, analysis_id=job_id, role="assistant", content="", status="pending", parent_id=um.id)
        db.add(am)
        db.commit()
        t0 = time.perf_counter()
        qasvc.internal_retrieve(db, job_id, am.id)
        db.commit()
        t_ret = time.perf_counter() - t0
        evidence = [dict(e) for e in (db.get(ChatMessage, am.id).evidence or [])]  # captured before answering clears it
        t1 = time.perf_counter()
        msg = qasvc.internal_answer(db, am.id, get_settings(), provider)
        db.commit()
        t_ans = time.perf_counter() - t1
    return {"evidence": evidence, "message": msg, "retrieve_s": t_ret, "answer_s": t_ans}


# ------------------------------------------------------------------ digests (reproducibility)
def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def graph_digest(art: dict[str, Any]) -> str:
    by_id = {n["id"]: n for n in art["nodes"]}
    nodes = sorted((n["type"], n["name"], n["path"] or "", n["start_line"] or 0) for n in art["nodes"])
    edges = sorted((e["relation"], e["resolution"], by_id[e["source"]]["name"], by_id[e["source"]]["path"] or "", by_id[e["target"]]["name"], by_id[e["target"]]["path"] or "") for e in art["edges"])
    return _digest([nodes, edges])


# ------------------------------------------------------------------ main loop
def build_provider(cfg: RunConfig, ledger: UsageLedger) -> tuple[Any, str | None]:
    if cfg.sut == "retrieval_only":
        return NoLLM(), None
    if cfg.sut != "live":
        raise EvalSetupError(f"unknown --sut {cfg.sut!r}")
    from app.core.config import get_settings
    from app.services.llm import AnthropicProvider
    s = get_settings()
    if not s.llm_configured:
        raise EvalSetupError("--sut live needs Raven's LLM settings: set LLM_API_KEY and LLM_MODEL (and optionally LLM_PROVIDER=anthropic).")
    return RecordingProvider(AnthropicProvider(s), ledger, RateLimiter(cfg.sut_per_minute)), s.llm_model


def run(cfg: RunConfig, bm: Benchmark | None = None) -> dict[str, Any]:
    bm = bm or Benchmark(cfg.version)
    if cfg.suite == "smoke":
        cfg.sut, cfg.judge = "retrieval_only", JudgeConfig()  # hermetic: no network, no keys, no cost
    repo_ids = cfg.repos or (bm.manifest.smoke_repos if cfg.suite == "smoke" else [r.id for r in bm.manifest.repos])
    unknown = [r for r in repo_ids if r not in bm.truth]
    if unknown:
        raise EvalSetupError(f"unknown repos: {unknown}")
    configure_database(cfg.db_url)
    ledger = UsageLedger()
    provider, sut_model = build_provider(cfg, ledger)  # credentials are checked before anything is modified
    judge: Judge | None = None
    if cfg.sut == "live":
        judge_status, judge = build_judge(cfg.judge)
    elif cfg.judge.provider not in ("", "none"):
        judge_status = JudgeStatus("skipped", "judge metrics score AI answers, so they need --sut live", cfg.judge.provider, cfg.judge.model)
    else:
        judge_status = JudgeStatus("not_requested", "EVAL_JUDGE_PROVIDER is not set (deterministic metrics only)")
    if cfg.reset_db:
        reset_schema()

    started = time.time()
    failures: list[dict[str, Any]] = []
    out: dict[str, Any] = {"graph": {}, "readiness": {}, "impact": {}, "retrieval": {}, "qa": {}, "judge": {}}
    samples: dict[str, list[dict[str, Any]]] = {"qa": [], "impact": []}
    timing: dict[str, list[float]] = {"pipeline_s": [], "retrieve_s": [], "answer_s": [], "impact_s": []}
    repro: dict[str, dict[str, set[str]]] = {}
    qa_runs: dict[str, list[dict[str, Any]]] = {}
    ret_by_rep: dict[int, list[dict[str, Any]]] = {}
    runs_per_repo: dict[str, int] = {}

    for rid in repo_ids:
        entry, gt = bm.repo(rid), bm.truth[rid]
        files = bm.files(rid)
        for rep in range(cfg.repeats):
            primary = rep == 0
            try:
                an = analyze(entry.full_name, files)
            except Exception as exc:  # noqa: BLE001
                failures.append({"suite": "pipeline", "repo": rid, "repeat": rep, "kind": "exception", "detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
                continue
            timing["pipeline_s"].append(an.wall_s)
            if an.state != "BUILDING_GRAPH":
                failures.append({"suite": "pipeline", "repo": rid, "repeat": rep, "kind": "analysis_failed", "detail": f"state={an.state} error={an.error_code}"})
                continue
            art = load_artifacts(an.job_id)
            runs_per_repo[rid] = runs_per_repo.get(rid, 0) + 1
            rd = repro.setdefault(rid, {})  # keys are namespaced by repo below via aggregate()
            rd.setdefault("graph", set()).add(graph_digest(art))
            rd.setdefault("readiness", set()).add(_digest(art["readiness"]))
            if primary:
                out["graph"][rid] = M.score_graph(gt, art["nodes"], art["edges"], art["entry_points"])
                out["readiness"][rid] = M.score_readiness(gt, art["readiness"])
                out["graph"][rid]["stage_seconds"] = an.stage_seconds
            _impact(rid, gt, an, entry.full_name, primary, out, samples, timing, rd, failures, rep)
            _qa(rid, gt, an, art, provider, primary, out, samples, timing, rd, failures, rep, qa_runs, judge, ret_by_rep.setdefault(rep, []))
    if judge:
        judge.close()

    results = {
        "schema_version": 1, "harness_version": HARNESS_VERSION, "run_id": uuid.uuid4().hex[:12],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)), "duration_s": round(time.time() - started, 2),
        "config": {"suite": cfg.suite, "repos": repo_ids, "sut": cfg.sut, "repeats": cfg.repeats, "judge": {k: v for k, v in cfg.judge.__dict__.items()}},
        "environment": environment(), "benchmark": {"name": bm.manifest.name, "version": bm.manifest.version, "fingerprint": bm.fingerprint(), "repos": repo_ids},
        "sut": {"mode": cfg.sut, "model": sut_model, "answer_generation": "Raven AI answer path" if cfg.sut == "live" else "Raven retrieval-only fallback (no LLM)"},
        "judge_status": judge_status.as_dict(),
        "metrics": aggregate(out, timing, ledger, sut_model, repro, qa_runs, samples["qa"], ret_by_rep, runs_per_repo),
        "per_repo": out, "samples": samples, "failures": failures,
    }
    return results


def _impact(rid: str, gt: GroundTruth, an: Analysis, full_name: str, primary: bool, out: dict, samples: dict, timing: dict, rd: dict, failures: list, rep: int) -> None:
    for case in gt.impact:
        try:
            res, dt = run_impact(an.job_id, full_name, an.commit_sha, [c.model_dump() for c in case.changed])
        except Exception as exc:  # noqa: BLE001
            failures.append({"suite": "impact", "repo": rid, "id": case.id, "repeat": rep, "kind": "exception", "detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
            continue
        timing["impact_s"].append(dt)
        rd.setdefault(f"impact:{case.id}", set()).add(_digest({k: res[k] for k in ("affected", "routes", "tests")}))
        if primary:
            sc = M.score_impact(case, res)
            out["impact"][case.id] = {"repo": rid, **sc}
            samples["impact"].append({"id": case.id, "repo": rid, "changed": [c.path for c in case.changed],
                                      "predicted": {"affected_modules": sorted(a["path"] for a in res["affected"]), "routes": sorted(f"{r['method']} {r['path']}" for r in res["routes"]),
                                                    "tests": sorted(t["path"] for t in res["tests"])}})


def _qa(rid: str, gt: GroundTruth, an: Analysis, art: dict, provider: Any, primary: bool, out: dict, samples: dict, timing: dict, rd: dict, failures: list, rep: int,
        qa_runs: dict, judge: Judge | None, ret_rows_this_repeat: list[dict[str, Any]]) -> None:
    ret_rows, ans_rows = [], []
    for q in gt.qa:
        try:
            r = ask(an.job_id, an.user_id, q.question, provider)
        except Exception as exc:  # noqa: BLE001
            failures.append({"suite": "qa", "repo": rid, "id": q.id, "repeat": rep, "kind": "exception", "detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
            continue
        timing["retrieve_s"].append(r["retrieve_s"])
        timing["answer_s"].append(r["answer_s"])
        msg, ev = r["message"], r["evidence"]
        rd.setdefault(f"retrieval:{q.id}", set()).add(_digest([(e["path"], e["start_line"], e["end_line"]) for e in ev]))
        ret_rows_this_repeat.append(M.score_retrieval(q, ev))
        qa_runs.setdefault(q.id, []).append({"content": msg.get("content"), "citations": sorted((c["path"], c["start_line"], c["end_line"]) for c in msg.get("citations") or []),
                                             "abstained": msg.get("evidence_sufficiency") == "insufficient", "answer_source": msg.get("answer_source")})
        if not primary:
            continue
        rr = M.score_retrieval(q, ev)
        ar = M.score_answer(q, msg, art["line_counts"])
        ret_rows.append(rr)
        ans_rows.append(ar)
        if ar["structure_problems"]:
            failures.append({"suite": "qa", "repo": rid, "id": q.id, "kind": "structured_output", "detail": "; ".join(ar["structure_problems"])})
        judged = None
        if judge and msg.get("answer_source") == "ai" and q.answerable:
            ctx = [f"{e['path']}:{e['start_line']}-{e['end_line']}\n{e.get('text', '')}" for e in ev]
            judged = judge.evaluate(q.question, msg.get("content") or "", q.expected_answer, ctx)
            for name, j in judged.items():
                if j["error"]:
                    failures.append({"suite": "judge", "repo": rid, "id": q.id, "kind": f"judge:{name}", "detail": j["error"]})
        samples["qa"].append({"repo": rid, "id": q.id, "question": q.question, "answerable": q.answerable, "expected_answer": q.expected_answer,
                              "answer": msg.get("content"), "inferred": msg.get("inferred"), "citations": msg.get("citations"), "limitations": msg.get("limitations"),
                              "retrieved": [{"path": e["path"], "start_line": e["start_line"], "end_line": e["end_line"], "reason": e.get("reason")} for e in ev],
                              "retrieval": rr, "answer_scores": ar, "judge": judged})
    if primary:
        out["retrieval"][rid] = M.aggregate_retrieval(ret_rows)
        out["qa"][rid] = M.aggregate_answers(ans_rows)


def aggregate(out: dict, timing: dict, ledger: UsageLedger, sut_model: str | None, repro: dict, qa_runs: dict, qa_samples: list[dict[str, Any]],
              ret_by_rep: dict[int, list[dict[str, Any]]], runs_per_repo: dict[str, int]) -> dict[str, Any]:
    from evals.usage import load_pricing
    g = out["graph"]
    graph = {cat: M.micro([g[r][cat] for r in g]) for cat in ("routes", "data_models", "orm_models", "internal_imports", "entry_points")} if g else {}
    rl = [out["readiness"][r]["rule_level"] for r in out["readiness"]]
    ll = [out["readiness"][r]["location_level"] for r in out["readiness"]]
    readiness = {}
    if rl:
        readiness["rule_level"] = M.micro(rl)
        readiness["rule_level"]["false_positive_rate"] = M.ratio(sum(x["fp"] for x in rl), sum(x["fp"] + x["tn"] for x in rl))
        tp, fp, fn = (sum(x[k] for x in ll) for k in ("tp", "fp", "fn"))
        readiness["location_level"] = {"tp": tp, "fp": fp, "fn": fn, "precision": M.ratio(tp, tp + fp), "recall": M.ratio(tp, tp + fn), "f1": M.f1(M.ratio(tp, tp + fp), M.ratio(tp, tp + fn))}
    imp = out["impact"]
    impact = {cat: M.micro([imp[c][cat] for c in imp]) for cat in ("affected_modules", "routes", "relevant_tests")} if imp else {}
    if imp:
        impact["n_cases"] = len(imp)
    samples_ret = [r for rid in out["retrieval"] for r in [out["retrieval"][rid]]]
    retrieval = _weighted(samples_ret, ("span_recall", "mrr", "hit@1", "hit@3", "hit@5", "hit@all", "snippet_precision"), "n_answerable") if samples_ret else {}
    if samples_ret:
        retrieval["unanswerable_empty_retrieval_rate"] = _weighted(samples_ret, ("unanswerable_empty_retrieval_rate",), "n_unanswerable")["unanswerable_empty_retrieval_rate"]
        retrieval["n_answerable"] = sum(r["n_answerable"] for r in samples_ret)
        retrieval["n_unanswerable"] = sum(r["n_unanswerable"] for r in samples_ret)
    qa_parts = list(out["qa"].values())
    qa = {}
    if qa_parts:
        qa = _weighted(qa_parts, ("structured_output_valid_rate",), "n")
        qa |= _weighted([p for p in qa_parts if p["citation_validity"] is not None], ("citation_validity",), "n")
        for k in ("citation_support_precision", "citation_recall", "key_fact_recall_ai", "deterministic_accuracy_ai", "abstention_recall_ai", "false_abstention_rate_ai"):
            qa |= _weighted([p for p in qa_parts if p[k] is not None], (k,), "n")
        qa["n"] = sum(p["n"] for p in qa_parts)
        qa["n_answerable"] = sum(p["n_answerable"] for p in qa_parts)
        qa["n_with_citations"] = sum(p["n_with_citations"] for p in qa_parts)
        qa["n_ai"] = sum(p["n_ai"] for p in qa_parts)
        qa["n_retrieval_only"] = sum(p["n_retrieval_only"] for p in qa_parts)
        qa["llm_error_codes"] = sorted({c for p in qa_parts for c in p["llm_error_codes"]})
    judge = aggregate_judge(qa_samples)
    stable = {f"{rid}:{k}": len(v) == 1 for rid, rd in repro.items() for k, v in rd.items()}
    qa_stability = {}
    multi = {qid: runs for qid, runs in qa_runs.items() if len(runs) > 1}
    if multi:
        qa_stability = {"questions": len(multi), "identical_answer_text_rate": M.ratio(sum(len({r["content"] for r in runs}) == 1 for runs in multi.values()), len(multi)),
                        "identical_citation_set_rate": M.ratio(sum(len({tuple(r["citations"]) for r in runs}) == 1 for runs in multi.values()), len(multi)),
                        "consistent_abstention_rate": M.ratio(sum(len({r["abstained"] for r in runs}) == 1 for runs in multi.values()), len(multi))}
    return {
        "graph": graph, "readiness": readiness, "impact": impact, "retrieval": retrieval, "qa": qa, "judge": judge,
        "operational": {"pipeline_s": latency_stats(timing["pipeline_s"]), "retrieve_s": latency_stats(timing["retrieve_s"]), "answer_s": latency_stats(timing["answer_s"]),
                        "impact_s": latency_stats(timing["impact_s"]), "sut_llm": ledger.summary(sut_model, load_pricing())},
        "reproducibility": {"repeats_compared": min(runs_per_repo.values(), default=0),  # completed analyses per repo (not distinct outputs)
                            "deterministic_outputs_identical": all(stable.values()) if stable else None,
                            "unstable_outputs": sorted(k for k, ok in stable.items() if not ok), "qa": qa_stability,
                            "retrieval_per_repeat": [{"repeat": rep, **{k: v for k, v in M.aggregate_retrieval(rows).items() if k in ("span_recall", "mrr", "hit@5", "snippet_precision")}}
                                                     for rep, rows in sorted(ret_by_rep.items())] if len(ret_by_rep) > 1 else []},
    }


def _weighted(parts: list[dict[str, Any]], keys: tuple[str, ...], weight: str) -> dict[str, Any]:
    res = {}
    for k in keys:
        num = sum((p[k] or 0) * p[weight] for p in parts if p.get(k) is not None)
        den = sum(p[weight] for p in parts if p.get(k) is not None)
        res[k] = M.ratio(num, den)
    return res


def aggregate_judge(qa_samples: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [s["judge"] for s in qa_samples if s.get("judge")]
    if not judged:
        return {}
    res: dict[str, Any] = {"n_judged_answers": len(judged)}
    for name in sorted({k for j in judged for k in j}):
        rows = [j[name] for j in judged if name in j]
        scores = [r["score"] for r in rows if r["score"] is not None]
        costs = [r["judge_cost_usd"] for r in rows if isinstance(r.get("judge_cost_usd"), int | float)]
        res[name] = {"mean": M.ratio(sum(scores), len(scores)), "n": len(scores), "errors": len(rows) - len(scores),
                     "pass_rate": M.ratio(sum(1 for r in rows if r["passed"]), len(scores)), "judge_cost_usd": round(sum(costs), 6) if costs else None}
    return res


def environment() -> dict[str, Any]:
    from app.analysis.graph import ANALYZER_VERSION
    git, dirty = None, None
    try:
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True, timeout=5).stdout.strip() or None
        if git:
            dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=BACKEND, capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        import deepeval
        dv = getattr(deepeval, "__version__", "unknown")
    except ImportError:
        dv = None
    return {"python": platform.python_version(), "platform": platform.platform(), "raven_analyzer_version": ANALYZER_VERSION, "git_commit": git, "git_dirty": dirty, "deepeval": dv}
