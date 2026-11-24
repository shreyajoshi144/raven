"""Results files, threshold gates, baseline comparison and the Markdown report."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# (dotted path under results["metrics"], label, higher_is_better)
HEADLINE: list[tuple[str, str, bool]] = [
    ("graph.routes.precision", "Graph · routes precision", True), ("graph.routes.recall", "Graph · routes recall", True),
    ("graph.data_models.f1", "Graph · data models F1", True), ("graph.orm_models.recall", "Graph · ORM models recall", True),
    ("graph.internal_imports.precision", "Graph · import edges precision", True), ("graph.internal_imports.recall", "Graph · import edges recall", True),
    ("readiness.rule_level.precision", "Readiness · rule precision", True), ("readiness.rule_level.recall", "Readiness · rule recall", True),
    ("readiness.rule_level.false_positive_rate", "Readiness · rule false-positive rate", False),
    ("readiness.location_level.precision", "Readiness · location precision", True), ("readiness.location_level.recall", "Readiness · location recall", True),
    ("impact.affected_modules.precision", "Impact · affected modules precision", True), ("impact.affected_modules.recall", "Impact · affected modules recall", True),
    ("impact.routes.precision", "Impact · routes precision", True), ("impact.routes.recall", "Impact · routes recall", True),
    ("impact.relevant_tests.precision", "Impact · tests precision", True), ("impact.relevant_tests.recall", "Impact · tests recall", True),
    ("retrieval.span_recall", "Retrieval · evidence span recall", True), ("retrieval.mrr", "Retrieval · MRR", True), ("retrieval.hit@5", "Retrieval · hit@5", True),
    ("retrieval.snippet_precision", "Retrieval · snippet precision", True),
    ("qa.structured_output_valid_rate", "Q&A · structured output valid", True), ("qa.citation_validity", "Q&A · citation validity (path/lines exist)", True),
    ("qa.citation_support_precision", "Q&A · citation faithfulness (cites labelled evidence)", True), ("qa.citation_recall", "Q&A · citation recall", True),
    ("qa.key_fact_recall_ai", "Q&A · key-fact recall (AI answers)", True), ("qa.deterministic_accuracy_ai", "Q&A · deterministic accuracy (AI answers)", True),
    ("qa.abstention_recall_ai", "Q&A · abstains when unanswerable (AI)", True), ("qa.false_abstention_rate_ai", "Q&A · false abstention rate (AI)", False),
    ("judge.correctness.mean", "Judge · correctness (GEval)", True), ("judge.faithfulness.mean", "Judge · faithfulness", True), ("judge.answer_relevancy.mean", "Judge · answer relevancy", True),
]
SAMPLE_COUNT = {"graph.routes": "n_gold", "graph.data_models": "n_gold", "graph.orm_models": "n_gold", "graph.internal_imports": "n_gold", "readiness.rule_level": "n_gold",
                "impact.affected_modules": "n_gold", "impact.routes": "n_gold", "impact.relevant_tests": "n_gold"}


def get(d: dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def sample_count(results: dict[str, Any], path: str) -> int | None:
    m = results["metrics"]
    area = path.split(".")[0]
    parent = path.rsplit(".", 1)[0]
    if parent in SAMPLE_COUNT:
        return get(m, f"{parent}.{SAMPLE_COUNT[parent]}")
    if area == "readiness":
        loc = get(m, "readiness.location_level") or {}
        return (loc.get("tp", 0) + loc.get("fn", 0)) if "location" in path else get(m, "readiness.rule_level.n_gold")
    if area == "retrieval":
        return get(m, "retrieval.n_answerable")
    if area == "qa":
        if path.endswith("_ai"):
            return get(m, "qa.n_ai")
        if path == "qa.citation_validity":
            return get(m, "qa.n_with_citations")
        return get(m, "qa.n_answerable") if path in ("qa.citation_support_precision", "qa.citation_recall") else get(m, "qa.n")
    if area == "judge":
        return get(m, f"{parent}.n")
    return None


def check_thresholds(results: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    """Each threshold: {"metric": dotted path, "min" | "max": number, "required": bool}. A missing value fails only if required."""
    out = []
    for t in thresholds.get("checks", []):
        v = get(results["metrics"], t["metric"])
        if v is None:
            out.append({**t, "value": None, "passed": not t.get("required", False), "status": "missing" if t.get("required") else "not_applicable"})
            continue
        ok = (v >= t["min"]) if "min" in t else (v <= t["max"])
        out.append({**t, "value": v, "passed": ok, "status": "pass" if ok else "fail"})
    return out


def compare_baseline(results: dict[str, Any], baseline: dict[str, Any], tolerance: float = 0.0) -> list[dict[str, Any]]:
    rows = []
    for path, label, hib in HEADLINE:
        cur, base = get(results["metrics"], path), get(baseline.get("metrics", {}), path)
        if cur is None and base is None:
            continue
        delta = round(cur - base, 4) if isinstance(cur, int | float) and isinstance(base, int | float) else None
        regressed = delta is not None and ((delta < -tolerance) if hib else (delta > tolerance))
        rows.append({"metric": path, "label": label, "current": cur, "baseline": base, "delta": delta, "regressed": regressed})
    return rows


def baseline_from(results: dict[str, Any]) -> dict[str, Any]:
    """The subset of a results file kept as a committed baseline."""
    return {"schema_version": 1, "created_from_run": results["run_id"], "started_at": results["started_at"], "benchmark": results["benchmark"],
            "config": results["config"], "sut": results["sut"], "environment": results["environment"], "metrics": results["metrics"]}


def fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def not_evaluated(results: dict[str, Any]) -> list[str]:
    notes = []
    m, sut = results["metrics"], results["sut"]
    if sut["mode"] != "live" or not m.get("qa", {}).get("n_ai"):
        notes.append("**AI answer quality was not measured**: no AI answers were produced (SUT mode `{}`). Key-fact recall, deterministic accuracy, abstention and "
                     "judge metrics are therefore `—`, not zero. Citation metrics describe Raven's retrieval-only fallback answers.".format(sut["mode"]))
    js = results["judge_status"]
    if js["state"] != "ready":
        notes.append(f"**LLM-as-judge: {js['state']}** — {js.get('reason')}")
    if not m.get("reproducibility", {}).get("qa"):
        notes.append("Answer stability across repeats was not measured (run with `--repeats 3` or more).")
    return notes


def render_markdown(results: dict[str, Any], baseline_rows: list[dict[str, Any]] | None = None, threshold_rows: list[dict[str, Any]] | None = None) -> str:
    m, b, env = results["metrics"], results["benchmark"], results["environment"]
    L: list[str] = []
    L += ["# Raven evaluation report", "",
          f"Run `{results['run_id']}` · {results['started_at']} · {results['duration_s']} s · suite **{results['config']['suite']}**", "",
          "| | |", "|---|---|",
          f"| System under test | {results['sut']['answer_generation']}{' · model `' + results['sut']['model'] + '`' if results['sut']['model'] else ''} |",
          f"| Judge | {results['judge_status']['state']}{' · ' + str(results['judge_status'].get('provider')) + ' `' + str(results['judge_status'].get('model')) + '`' if results['judge_status']['state'] == 'ready' else ''} |",
          f"| Benchmark | {b['name']} {b['version']} · fingerprint `{b['fingerprint'][:16]}` · repos: {', '.join(b['repos'])} |",
          f"| Environment | Python {env['python']} · analyzer {env['raven_analyzer_version']} · commit `{(env.get('git_commit') or 'n/a')[:12]}`{' (uncommitted changes)' if env.get('git_dirty') else ''} · DeepEval {env.get('deepeval') or 'not installed'} |",
          f"| Repeats | {results['config']['repeats']} |", ""]
    notes = not_evaluated(results)
    if notes:
        L += ["## Not evaluated in this run", ""] + [f"- {n}" for n in notes] + [""]
    base = {r["metric"]: r for r in baseline_rows or []}
    thr = {t["metric"]: t for t in threshold_rows or []}
    L += ["## Scores", "", "`—` = not measurable in this run (no samples or not applicable). n = labelled items behind the score.", "",
          "| Metric | Value | n | Baseline | Δ | Gate |", "|---|---:|---:|---:|---:|---|"]
    for path, label, _ in HEADLINE:
        v = get(m, path)
        br, tr = base.get(path), thr.get(path)
        gate = "" if not tr else (f"{'≥' if 'min' in tr else '≤'} {tr.get('min', tr.get('max'))} {'✅' if tr['passed'] and tr['status'] == 'pass' else '❌' if not tr['passed'] else '—'}")
        delta = "" if not br or br["delta"] is None else (f"{br['delta']:+.3f}" + (" ⚠️" if br["regressed"] else ""))
        L.append(f"| {label} | {fmt(v)} | {fmt(sample_count(results, path))} | {fmt(br['baseline']) if br else ''} | {delta} | {gate} |")
    L.append("")
    L += _graph_section(results) + _readiness_section(results) + _impact_section(results) + _qa_section(results) + _ops_section(results)
    if results["failures"]:
        L += ["## Run failures", ""] + [f"- `{f['suite']}` {f.get('repo', '')} {f.get('id', '')}: {f['kind']} — {f['detail']}" for f in results["failures"][:60]] + [""]
    L += ["## How to read these numbers", "",
          "- Scores are computed against hand-labelled ground truth in `backend/evals/benchmarks/" + "v1/` (labels verified against the source by the maintainers, not independently reviewed). "
          "The benchmark is small (" + str(len(b["repos"])) + " repositories); treat scores as regression signals and diagnostics, not as general accuracy claims.",
          "- Precision is only reported where the label set is exhaustive. Graph and impact labels use file-level static-dependency semantics (see the metric definitions in docs/evaluation/AI_EVALUATION.md).",
          "- Judge scores (if present) come from an LLM and inherit its biases; they are reported next to, never instead of, the deterministic metrics.", ""]
    return "\n".join(L)


def _graph_section(r: dict[str, Any]) -> list[str]:
    g = r["per_repo"]["graph"]
    if not g:
        return []
    L = ["## Graph accuracy per repository", "", "| Repo | Routes P / R | Route line acc. | Data models P / R | ORM models P / R | Import edges P / R | verified share |", "|---|---|---:|---|---|---|---:|"]
    for rid, x in g.items():
        pr = lambda c, x=x: f"{fmt(x[c]['precision'])} / {fmt(x[c]['recall'])}"  # noqa: E731
        L.append(f"| {rid} | {pr('routes')} | {fmt(x['routes']['line_accuracy'])} | {pr('data_models')} | {pr('orm_models')} | {pr('internal_imports')} | {fmt(x['internal_imports']['verified_static_share'])} |")
    misses = [(rid, c, x[c]["missing"], x[c]["extra"]) for rid, x in g.items() for c in ("routes", "data_models", "orm_models", "internal_imports") if x[c]["missing"] or x[c]["extra"]]
    if misses:
        L += ["", "Misses (`-` expected but not found, `+` found but not expected):", ""]
        for rid, c, miss, extra in misses:
            L.append(f"- **{rid} · {c}**: " + "; ".join([f"- {i}" for i in miss[:12]] + [f"+ {i}" for i in extra[:12]]) + (" …" if len(miss) + len(extra) > 24 else ""))
    return L + [""]


def _readiness_section(r: dict[str, Any]) -> list[str]:
    rd = r["per_repo"]["readiness"]
    if not rd:
        return []
    L = ["## Readiness findings per repository", "", "| Repo | Rules assessed | TP | FP | FN | TN | Location P / R |", "|---|---:|---:|---:|---:|---:|---|"]
    for rid, x in rd.items():
        rl, ll = x["rule_level"], x["location_level"]
        L.append(f"| {rid} | {rl['assessed']} | {rl['tp']} | {rl['fp']} | {rl['fn']} | {rl['tn']} | {fmt(ll['precision'])} / {fmt(ll['recall'])} |")
    L += [""]
    for rid, x in rd.items():
        bad = {k: v for k, v in x["per_rule"].items() if v in ("FP", "FN")}
        if bad or x["location_level"]["false_positives"] or x["location_level"]["false_negatives"]:
            L.append(f"- **{rid}**: rule errors {bad or 'none'}; location FP {x['location_level']['false_positives'] or 'none'}; location FN {x['location_level']['false_negatives'] or 'none'}")
    return L + [""]


def _impact_section(r: dict[str, Any]) -> list[str]:
    im = r["per_repo"]["impact"]
    if not im:
        return []
    L = ["## Change impact per scenario", "", "| Case | Repo | Modules P / R | Routes P / R | Tests P / R |", "|---|---|---|---|---|"]
    for cid, x in im.items():
        pr = lambda c, x=x: f"{fmt(x[c]['precision'])} / {fmt(x[c]['recall'])}"  # noqa: E731
        L.append(f"| {cid} | {x['repo']} | {pr('affected_modules')} | {pr('routes')} | {pr('relevant_tests')} |")
    for cid, x in im.items():
        miss = [f"{c}: -{', -'.join(x[c]['missing'])}" for c in ("affected_modules", "routes", "relevant_tests") if x[c]["missing"]]
        extra = [f"{c}: +{', +'.join(x[c]['extra'])}" for c in ("affected_modules", "routes", "relevant_tests") if x[c]["extra"]]
        if miss or extra:
            L.append(f"- **{cid}**: " + "; ".join(miss + extra))
    return L + [""]


def _qa_section(r: dict[str, Any]) -> list[str]:
    qs = r["samples"]["qa"]
    if not qs:
        return []
    L = ["## Retrieval and Q&A per question", "", "| Question | Answerable | Retrieved | Span recall | Hit@5 | Answer source | Confidence | Cites valid | Cites labelled evidence | Key facts | Judge (corr / faith / rel) |",
         "|---|---|---:|---:|---|---|---|---:|---:|---:|---|"]
    for s in qs:
        rr, ar, j = s["retrieval"], s["answer_scores"], s.get("judge") or {}
        jj = " / ".join(fmt((j.get(k) or {}).get("score")) for k in ("correctness", "faithfulness", "answer_relevancy")) if j else "—"
        L.append(f"| {s['id']} | {fmt(s['answerable'])} | {rr['n_retrieved']} | {fmt(rr.get('span_recall'))} | {fmt(rr.get('hit@5'))} | {ar['answer_source']} | {ar['confidence']} | "
                 f"{fmt(ar['citation_validity'])} | {fmt(ar.get('citation_support_precision'))} | {fmt(ar.get('key_fact_recall'))} | {jj} |")
    return L + [""]


def _ops_section(r: dict[str, Any]) -> list[str]:
    o, rep = r["metrics"]["operational"], r["metrics"]["reproducibility"]
    llm = o["sut_llm"]
    L = ["## Latency, tokens, cost, errors", "", "| Stage | n | mean s | p50 s | p95 s | max s |", "|---|---:|---:|---:|---:|---:|"]
    for k, label in (("pipeline_s", "Ingest + parse + graph (per repo)"), ("retrieve_s", "Retrieval (per question)"), ("answer_s", "Answer (per question)"), ("impact_s", "Impact (per scenario)")):
        x = o[k]
        L.append(f"| {label} | {x['n']} | {fmt(x['mean'])} | {fmt(x['p50'])} | {fmt(x['p95'])} | {fmt(x['max'])} |")
    L += ["", f"SUT LLM calls: {llm['calls']} (errors {llm['errors']} {llm['error_codes'] or ''}) · input tokens {llm['input_tokens']} · output tokens {llm['output_tokens']} · "
          f"estimated cost {fmt(llm['estimated_cost_usd'])} USD ({llm['cost_basis']})."]
    jm = r["metrics"].get("judge") or {}
    jc = [v.get("judge_cost_usd") for k, v in jm.items() if isinstance(v, dict) and v.get("judge_cost_usd") is not None]
    if jm:
        L.append(f"Judge: {jm.get('n_judged_answers')} answers judged · reported judge cost {fmt(round(sum(jc), 6)) if jc else '—'} USD.")
    L += ["", "## Reproducibility", "",
          f"Deterministic outputs (graph, readiness, impact, retrieval) identical across {rep['repeats_compared']} repeat(s): {fmt(rep['deterministic_outputs_identical'])}"
          + (f" — unstable: {', '.join(rep['unstable_outputs'])}" if rep["unstable_outputs"] else "") + "."]
    if rep.get("retrieval_per_repeat"):
        L.append("Retrieval aggregates per repeat: " + "; ".join(f"#{x['repeat']} span recall {fmt(x['span_recall'])}, MRR {fmt(x['mrr'])}, hit@5 {fmt(x['hit@5'])}" for x in rep["retrieval_per_repeat"]) + ".")
    if rep.get("qa"):
        q = rep["qa"]
        L.append(f"Answers over {q['questions']} questions: identical text {fmt(q['identical_answer_text_rate'])}, identical citation sets {fmt(q['identical_citation_set_rate'])}, "
                 f"consistent abstention {fmt(q['consistent_abstention_rate'])}.")
    return L + [""]


def write(results: dict[str, Any], out_dir: Path, baseline: dict[str, Any] | None, thresholds: dict[str, Any] | None, tolerance: float = 0.0) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    brows = compare_baseline(results, baseline, tolerance) if baseline else None
    trows = check_thresholds(results, thresholds) if thresholds else None
    results["baseline_comparison"] = {"baseline_run": baseline.get("created_from_run") if baseline else None, "tolerance": tolerance, "rows": brows} if brows is not None else None
    results["threshold_checks"] = trows
    (out_dir / "results.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
    (out_dir / "report.md").write_text(render_markdown(results, brows, trows))
    return {"regressions": [r for r in brows or [] if r["regressed"]], "threshold_failures": [t for t in trows or [] if not t["passed"]]}
