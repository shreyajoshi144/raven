"""Command line: python -m evals {validate|run|report|verify-sources}. Exit codes: 0 ok, 1 gate/regression failure, 2 setup error."""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import tarfile
from pathlib import Path

from evals.benchmark import Benchmark, content_sha256, validate
from evals.judge import judge_from_env
from evals.report import baseline_from, write
from evals.runner import EvalSetupError, RunConfig, run

HERE = Path(__file__).resolve().parent


def _load(path: str | None) -> dict | None:
    return json.loads(Path(path).read_text()) if path else None


def cmd_validate(a: argparse.Namespace) -> int:
    bm = Benchmark(a.version)
    problems = validate(bm)
    for p in problems:
        print("PROBLEM", p)
    t = bm.truth
    print(f"benchmark {bm.manifest.name} {bm.manifest.version} ({a.version}) fingerprint {bm.fingerprint()[:16]}: "
          f"{len(t)} repos, {sum(len(g.qa) for g in t.values())} questions ({sum(1 for g in t.values() for q in g.qa if not q.answerable)} unanswerable), "
          f"{sum(len(g.graph.routes.items) for g in t.values())} routes, {sum(len(g.graph.internal_imports.items) for g in t.values())} import edges, "
          f"{sum(len(g.impact) for g in t.values())} impact cases — {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


def cmd_run(a: argparse.Namespace) -> int:
    judge = judge_from_env()
    if a.judge_provider:
        judge.provider = a.judge_provider
    if a.judge_model:
        judge.model = a.judge_model
    cfg = RunConfig(version=a.version, suite=a.suite, repos=a.repos.split(",") if a.repos else None, sut=a.sut, repeats=a.repeats,
                    db_url=a.db_url or os.environ.get("EVAL_DATABASE_URL"), reset_db=not a.no_reset_db, judge=judge,
                    sut_per_minute=float(os.environ["EVAL_SUT_PER_MINUTE"]) if os.environ.get("EVAL_SUT_PER_MINUTE") else 30.0)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
    if cfg.sut == "retrieval_only" or a.suite == "smoke":
        logging.getLogger("raven.qa").setLevel(logging.ERROR)  # 'LLM unavailable' is the expected path in this mode
    try:
        results = run(cfg)
    except EvalSetupError as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    out = Path(a.out)
    baseline = _load(a.baseline) if a.baseline else _default(HERE / "baselines" / f"{a.version}-{a.suite}.json") if a.suite == "smoke" else None
    thresholds = _load(a.thresholds) if a.thresholds else _default(HERE / "thresholds" / f"{a.suite}.json")
    gate = write(results, out, baseline, thresholds, a.tolerance)
    if a.write_baseline:
        Path(a.write_baseline).parent.mkdir(parents=True, exist_ok=True)
        Path(a.write_baseline).write_text(json.dumps(baseline_from(results), indent=1) + "\n")
        print(f"baseline written to {a.write_baseline}")
    print(f"results: {out / 'results.json'}\nreport:  {out / 'report.md'}")
    print(f"judge: {results['judge_status']['state']} — {results['judge_status'].get('reason') or 'ok'}")
    for f in results["failures"]:
        print(f"failure: {f['suite']} {f.get('repo', '')} {f.get('id', '')} {f['kind']}: {f['detail']}")
    for t in gate["threshold_failures"]:
        print(f"THRESHOLD FAILED {t['metric']}: {t['value']} (required {'>=' if 'min' in t else '<='} {t.get('min', t.get('max'))})")
    for r in gate["regressions"]:
        print(f"REGRESSION {r['metric']}: {r['baseline']} -> {r['current']} ({r['delta']:+})")
    pipeline_failed = any(f["suite"] == "pipeline" for f in results["failures"])
    return 1 if gate["threshold_failures"] or (a.fail_on_regression and gate["regressions"]) or pipeline_failed else 0


def _default(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.is_file() else None


def cmd_report(a: argparse.Namespace) -> int:
    results = json.loads(Path(a.results).read_text())
    gate = write(results, Path(a.out or Path(a.results).parent), _load(a.baseline), _load(a.thresholds), a.tolerance)
    print(f"report written to {Path(a.out or Path(a.results).parent) / 'report.md'}")
    return 1 if gate["threshold_failures"] else 0


def cmd_verify_sources(a: argparse.Namespace) -> int:
    """Re-download each real repository's upstream archive and check the vendored subset is byte-identical (needs network)."""
    import httpx
    bm = Benchmark(a.version)
    rc = 0
    for entry in bm.manifest.repos:
        if not entry.upstream:
            continue
        up = entry.upstream
        owner_repo = up.url.removeprefix("https://github.com/")
        url = f"https://codeload.github.com/{owner_repo}/tar.gz/{up.commit}"
        try:
            data = httpx.get(url, timeout=60, follow_redirects=True).raise_for_status().content
        except httpx.HTTPError as exc:
            print(f"{entry.id}: could not download {url}: {exc}", file=sys.stderr)
            rc = 2
            continue
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile():
                    continue
                rel = m.name.split("/", 1)[1] if "/" in m.name else m.name
                if rel.startswith(up.subset) or rel == "LICENSE":
                    f = tar.extractfile(m)
                    files[rel] = f.read() if f else b""
        local = bm.files(entry.id)
        ok = content_sha256(files) == content_sha256(local) == entry.content_sha256
        print(f"{entry.id}: upstream {up.commit[:12]} subset {up.subset} — {'identical' if ok else 'DIFFERS'} ({len(files)} upstream files, {len(local)} vendored)")
        rc = rc or (0 if ok else 1)
    return rc


def cmd_pr(a: argparse.Namespace) -> int:
    from evals.pr_review import run_pr
    cfg = RunConfig(version=a.version, suite="full", sut="retrieval_only", db_url=a.db_url or os.environ.get("EVAL_DATABASE_URL"), reset_db=not a.no_reset_db)
    try:
        res = run_pr(cfg)
    except EvalSetupError as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pr-results.json").write_text(json.dumps(res, indent=1) + "\n")
    print(f"pr suite: {res['cases_passed']}/{res['cases']} cases, expected-finding recall {res['recall']}, forbidden {res['forbidden_violations']}, "
          f"invalid evidence {res['evidence_invalid']}/{res['evidence_checked']}, reproducible {res['reproducible_cases']}/{res['cases']}")
    for r in res["results"]:
        if not r["passed"]:
            print("FAILED:", r["id"], "missing", r["missing_expected"], "forbidden", r["forbidden_found"], "invalid evidence", r["evidence_invalid"], "reproducible", r["reproducible"])
    return 0 if res["cases_passed"] == res["cases"] else 1


def cmd_injection(a: argparse.Namespace) -> int:
    from evals.injection import run_injection
    cfg = RunConfig(version=a.version, suite="full", sut=a.sut, db_url=a.db_url or os.environ.get("EVAL_DATABASE_URL"), reset_db=not a.no_reset_db)
    try:
        res = run_injection(cfg)
    except EvalSetupError as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "injection-results.json").write_text(json.dumps(res, indent=1) + "\n")
    print(f"injection suite: {res['n_cases']} cases, AI answers {res['n_ai_answers']}, leaks {res['leaks']}, bad citations {res['bad_citation_cases']}, resisted rate {res['resisted_rate_ai']}")
    if res["note"]:
        print("NOTE:", res["note"])
    return 1 if res["leaks"] or res["bad_citation_cases"] or res["control_answered_ai"] is False else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals", description="Raven evaluation harness")
    p.add_argument("--version", default="v1", help="benchmark directory under evals/benchmarks (default v1)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="check the benchmark labels against the source files")
    r = sub.add_parser("run", help="run the evaluation")
    r.add_argument("--suite", choices=["smoke", "full"], default="smoke", help="smoke: hermetic, deterministic, no LLM/keys/network. full: every repo, honours --sut and the judge settings")
    r.add_argument("--repos", help="comma-separated repo ids (default: all repos of the suite)")
    r.add_argument("--sut", choices=["retrieval_only", "live"], default="retrieval_only", help="live = Raven's AI answer path (needs LLM_API_KEY, LLM_MODEL; costs money)")
    r.add_argument("--repeats", type=int, default=1, help="run everything N times and report reproducibility")
    r.add_argument("--db-url", help="disposable PostgreSQL URL (default $EVAL_DATABASE_URL); its schema is dropped and recreated")
    r.add_argument("--no-reset-db", action="store_true", help="reuse an already-migrated schema")
    r.add_argument("--judge-provider", choices=["none", "anthropic", "openai"], help="overrides $EVAL_JUDGE_PROVIDER")
    r.add_argument("--judge-model", help="overrides $EVAL_JUDGE_MODEL")
    r.add_argument("--out", default="eval-results", help="output directory for results.json and report.md")
    r.add_argument("--baseline", help="baseline results to compare against (smoke default: evals/baselines/<version>-smoke.json)")
    r.add_argument("--thresholds", help="threshold file (default: evals/thresholds/<suite>.json)")
    r.add_argument("--tolerance", type=float, default=0.0, help="allowed drop vs baseline before it counts as a regression")
    r.add_argument("--write-baseline", help="also write a baseline file from this run")
    r.add_argument("--fail-on-regression", action="store_true", help="exit 1 when any headline metric drops below the baseline by more than --tolerance (default: report only)")
    rp = sub.add_parser("report", help="re-render report.md from a results.json")
    rp.add_argument("results")
    rp.add_argument("--out")
    rp.add_argument("--baseline")
    rp.add_argument("--thresholds")
    rp.add_argument("--tolerance", type=float, default=0.0)
    ij = sub.add_parser("injection", help="prompt-injection suite (hostile repo); --sut live needs LLM_API_KEY and LLM_MODEL")
    ij.add_argument("--sut", choices=["retrieval_only", "live"], default="retrieval_only")
    ij.add_argument("--db-url")
    ij.add_argument("--no-reset-db", action="store_true")
    ij.add_argument("--out", default="eval-results")
    pq = sub.add_parser("pr", help="pull-request review benchmark (offline, deterministic)")
    pq.add_argument("--db-url")
    pq.add_argument("--no-reset-db", action="store_true")
    pq.add_argument("--out", default="eval-results")
    sub.add_parser("verify-sources", help="re-download upstream archives and check vendored subsets (network)")
    a = p.parse_args(argv)
    return {"validate": cmd_validate, "run": cmd_run, "report": cmd_report, "verify-sources": cmd_verify_sources, "injection": cmd_injection, "pr": cmd_pr}[a.cmd](a)
