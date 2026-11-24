"""Unit tests for the evaluation harness (backend/evals): metrics, benchmark validation, usage/cost, judge plumbing, reporting.
No database, network or LLM is used here."""
import json
import shutil
import time

import pytest

from app.core.errors import JobError
from app.services.llm import LLMResult
from evals import metrics as M
from evals.benchmark import Benchmark, GroundTruth, ImpactCase, QAItem, Span, content_sha256, import_closure, is_test_file, validate
from evals.judge import Judge, JudgeConfig, api_key_for, judge_from_env, resolve
from evals.report import check_thresholds, compare_baseline, not_evaluated, render_markdown
from evals.usage import NoLLM, RateLimiter, RecordingProvider, UsageLedger, estimate_cost, latency_stats


# ------------------------------------------------------------------ core metric math
def test_prf_counts_and_undefined_ratios():
    r = M.prf({"a", "b", "x"}, {"a", "b", "c"})
    assert (r["tp"], r["fp"], r["fn"]) == (2, 1, 1) and r["precision"] == r["recall"] == 0.6667 and r["missing"] == ["c"] and r["extra"] == ["x"]
    empty = M.prf(set(), set())
    assert empty["precision"] is None and empty["recall"] is None and empty["f1"] is None  # 0/0 is undefined, never 0 or 1
    assert M.prf({"a"}, set())["precision"] == 0.0 and M.prf(set(), {"a"})["recall"] == 0.0


def test_precision_is_not_reported_for_non_exhaustive_labels():
    r = M.prf({"a", "zzz"}, {"a"}, exhaustive=False)
    assert r["precision"] is None and r["fp"] is None and r["recall"] == 1.0 and r["extra"] == []


def test_micro_average_sums_counts_and_ignores_non_exhaustive_precision():
    parts = [M.prf({"a"}, {"a", "b"}), M.prf({"x", "y"}, {"x"}), M.prf({"q", "r"}, {"q"}, exhaustive=False)]
    m = M.micro(parts)
    assert (m["tp"], m["fn"]) == (3, 1) and m["fp"] == 1 and m["precision"] == 0.6667 and m["recall"] == 0.75


def test_route_path_normalisation_strips_only_a_leading_dynamic_prefix():
    assert M.norm_route_path("/{?settings.API_V1_STR}/users/{user_id}") == "/users/{user_id}"
    assert M.norm_route_path("/api//items/") == "/api/items/" and M.norm_route_path("") == "/" and M.norm_route_path("/items/{id}") == "/items/{id}"


def test_span_overlap_is_inclusive_and_path_sensitive():
    s = Span(path="a.py", start_line=10, end_line=12)
    assert M.overlaps("a.py", 12, 20, s) and M.overlaps("a.py", 1, 10, s) and not M.overlaps("a.py", 13, 14, s) and not M.overlaps("b.py", 10, 12, s)


# ------------------------------------------------------------------ fixtures built from the real v1 ground truth
@pytest.fixture(scope="module")
def bm():
    return Benchmark("v1")


def test_graph_scoring_matches_routes_models_and_edges(bm):
    gt: GroundTruth = bm.truth["clean_service"]
    nodes = [{"id": "m", "type": "module", "name": "main", "path": "app/main.py", "start_line": 1, "meta": {}},
             {"id": "s", "type": "module", "name": "store", "path": "app/store.py", "start_line": 1, "meta": {}},
             {"id": "r1", "type": "route", "name": "GET /items/{item_id}", "path": "app/main.py", "start_line": 18, "meta": {"method": "GET", "full_path": "/items/{item_id}"}},
             {"id": "r2", "type": "route", "name": "POST /items", "path": "app/main.py", "start_line": 40, "meta": {"method": "POST", "full_path": "/items"}},
             {"id": "x", "type": "model", "name": "Bogus", "path": "app/main.py", "start_line": 3, "meta": {"model_kind": "sqlalchemy"}}]
    edges = [{"source": "m", "target": "s", "relation": "imports", "resolution": "verified_static"}, {"source": "s", "target": "m", "relation": "imports", "resolution": "inferred"}]
    g = M.score_graph(gt, nodes, edges, [{"path": "app/main.py"}])
    assert g["routes"]["recall"] == 1.0 and g["routes"]["precision"] == 1.0 and g["routes"]["line_accuracy"] == 0.5  # POST line 40 is outside 27-28
    assert g["orm_models"]["precision"] == 0.0 and g["data_models"]["fp"] == 1  # a model in a repo labelled as having none
    assert g["internal_imports"]["tp"] == 1 and g["internal_imports"]["fp"] == 1 and g["internal_imports"]["fn"] == 4
    assert g["internal_imports"]["verified_static_share"] == 1.0 and g["entry_points"]["recall"] == 1.0


def test_readiness_scoring_rule_and_location_levels(bm):
    gt = bm.truth["shop_api"]
    findings = [
        {"rule": "SEC-WEAK-HASH", "evidence": [{"path": "app/core/security.py", "start_line": 10}]},                     # TP
        {"rule": "LOG-PRINT", "evidence": [{"path": "app/api/orders.py", "start_line": 19}, {"path": "app/db.py", "start_line": 3}]},  # TP + location FP
        {"rule": "SEC-YAML-LOAD", "evidence": [{"path": "app/db.py", "start_line": 1}]},                                 # rule FP
        {"rule": "EH-NO-GLOBAL-HANDLER", "evidence": []},                                                                 # absence TP
        {"rule": "SOME-UNASSESSED-RULE", "evidence": [{"path": "x.py", "start_line": 1}]},                              # ignored
    ]
    r = M.score_readiness(gt, findings)
    assert r["per_rule"]["SEC-WEAK-HASH"] == "TP" and r["per_rule"]["SEC-YAML-LOAD"] == "FP" and r["per_rule"]["SEC-CORS-WILDCARD"] == "FN" and r["per_rule"]["LOG-NONE"] == "TN"
    assert r["rule_level"]["tp"] == 3 and r["rule_level"]["fp"] == 1 and r["unassessed_findings"] == ["SOME-UNASSESSED-RULE"]
    loc = r["location_level"]
    assert loc["tp"] == 2 and "LOG-PRINT app/db.py:3" in loc["false_positives"] and "SEC-YAML-LOAD app/db.py:1" in loc["false_positives"]
    assert "SEC-CORS-WILDCARD app/main.py:9" in loc["false_negatives"]


def test_impact_scoring_ignores_fixture_helpers_in_test_lists():
    case = ImpactCase.model_validate({"id": "c", "description": "d", "changed": [{"path": "a.py", "status": "modified"}],
                                      "expected": {"affected_modules": {"exhaustive": True, "items": ["b.py"]}, "routes": {"exhaustive": True, "items": ["GET /x"]},
                                                   "relevant_tests": {"exhaustive": True, "items": ["tests/test_a.py"]}}})
    res = {"affected": [{"path": "b.py"}, {"path": "c.py"}], "routes": [{"method": "GET", "path": "/{?P}/x"}],
           "tests": [{"path": "tests/test_a.py"}, {"path": "tests/conftest.py"}, {"path": "tests/utils/user.py"}]}
    s = M.score_impact(case, res)
    assert s["affected_modules"]["precision"] == 0.5 and s["routes"]["recall"] == 1.0
    assert s["relevant_tests"]["precision"] == 1.0 and s["relevant_tests"]["ignored_non_test_files"] == ["tests/conftest.py", "tests/utils/user.py"]
    assert is_test_file("tests/test_a.py") and not is_test_file("tests/conftest.py")


def _q(answerable=True):
    return QAItem.model_validate({"id": "q", "category": "c", "question": "?", "answerable": answerable, "expected_answer": "e",
                                  "key_facts": [["md5"], ["salt", "prefix"]] if answerable else [],
                                  "evidence": [{"path": "s.py", "start_line": 9, "end_line": 10}, {"path": "t.py", "start_line": 1, "end_line": 2}] if answerable else []})


def test_retrieval_scoring_ranks_and_recall():
    ev = [{"path": "x.py", "start_line": 1, "end_line": 5}, {"path": "s.py", "start_line": 8, "end_line": 12}]
    r = M.score_retrieval(_q(), ev)
    assert r["span_recall"] == 0.5 and not r["hit@1"] and r["hit@3"] and r["reciprocal_rank"] == 0.5 and r["snippet_precision"] == 0.5 and r["missed_spans"] == ["t.py:1-2"]
    assert M.score_retrieval(_q(False), [])["empty"] is True
    agg = M.aggregate_retrieval([r, M.score_retrieval(_q(False), ev)])
    assert agg["n_answerable"] == 1 and agg["unanswerable_empty_retrieval_rate"] == 0.0


def _msg(**kw):
    m = {"content": "It uses md5 with a salt.", "citations": [{"path": "s.py", "start_line": 9, "end_line": 9}], "evidence_sufficiency": "sufficient",
         "answer_source": "ai", "confidence": "high", "inferred": [], "status": "complete", "error_code": None, "limitations": []}
    return m | kw


def test_answer_scoring_citations_key_facts_and_abstention():
    lines = {"s.py": 20, "t.py": 5}
    a = M.score_answer(_q(), _msg(), lines)
    assert a["citation_validity"] == 1.0 and a["citation_support_precision"] == 1.0 and a["citation_recall"] == 0.5 and a["key_fact_recall"] == 1.0 and a["correct_deterministic"]
    bad = M.score_answer(_q(), _msg(citations=[{"path": "s.py", "start_line": 9, "end_line": 99}, {"path": "nope.py", "start_line": 1, "end_line": 1}]), lines)
    assert bad["citation_validity"] == 0.0 and bad["citation_support_precision"] == 0.0  # out-of-file and unknown paths are never "supported"
    ro = M.score_answer(_q(), _msg(answer_source="retrieval_only", confidence="low", evidence_sufficiency="insufficient"), lines)
    assert ro["key_fact_recall"] is None and not ro["correct_deterministic"]  # retrieval-only text is not scored as an answer
    un = M.score_answer(_q(False), _msg(evidence_sufficiency="insufficient", citations=[]), lines)
    assert un["correct_deterministic"] and un["abstained"]
    agg = M.aggregate_answers([a, bad, ro, un])
    assert agg["n_ai"] == 3 and agg["n_retrieval_only"] == 1 and agg["abstention_recall_ai"] == 1.0 and agg["false_abstention_rate_ai"] == 0.0


def test_structured_output_problems_are_detected():
    assert M.structure_problems(_msg()) == []
    probs = M.structure_problems(_msg(confidence="certain", inferred="x", citations=[{"path": 1}], answer_source="retrieval_only"))
    assert any("confidence" in p for p in probs) and any("inferred" in p for p in probs) and "malformed citation" in probs


# ------------------------------------------------------------------ benchmark integrity
def test_v1_benchmark_is_internally_consistent(bm):
    assert validate(bm) == []
    assert {r.id for r in bm.manifest.repos} == {"shop_api", "clean_service", "fastapi_template"}
    assert sum(len(g.qa) for g in bm.truth.values()) == 27 and sum(1 for g in bm.truth.values() for q in g.qa if not q.answerable) == 7


def test_validation_detects_stale_labels(tmp_path, bm):
    shutil.copytree(bm.dir, tmp_path / "v1")
    p = tmp_path / "v1" / "ground_truth" / "shop_api.json"
    d = json.loads(p.read_text())
    d["qa"][0]["evidence"][0].update(start_line=2, end_line=3)  # span moved away from its anchor (hashlib.md5 is on line 10)
    d["impact"][0]["expected"]["affected_modules"]["items"].pop()
    p.write_text(json.dumps(d))
    (tmp_path / "v1" / "repos" / "clean_service" / "README.md").write_text("changed\n")
    problems = validate(Benchmark("v1", root=tmp_path))
    assert any("anchor" in x for x in problems) and any("affected_modules differ" in x for x in problems) and any("clean_service: content_sha256 mismatch" in x for x in problems)


def test_content_hash_ignores_tool_caches_and_closure_is_transitive(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    from evals.benchmark import read_tree
    h1 = content_sha256(read_tree(tmp_path))
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / ".ruff_cache" / "x").write_text("cache")
    assert content_sha256(read_tree(tmp_path)) == h1
    assert import_closure([["b", "a"], ["c", "b"], ["d", "x"]], {"a"}) == {"b", "c"}


# ------------------------------------------------------------------ usage, cost, rate limiting
def test_cost_estimate_uses_pricing_table_and_never_guesses():
    assert estimate_cost("claude-sonnet-5-5", 1_000_000, 100_000)["estimated_cost_usd"] == 3.0  # 2.00 + 0.1 * 10.00
    unknown = estimate_cost("some-unlisted-model", 10, 10)
    assert unknown["estimated_cost_usd"] is None and "unknown" in unknown["cost_basis"]
    assert estimate_cost(None, 0, 0)["estimated_cost_usd"] == 0.0


def test_recording_provider_records_tokens_latency_and_errors():
    class Inner:
        n = 0

        def complete(self, system, user, max_tokens):
            Inner.n += 1
            if Inner.n == 2:
                raise JobError("LLM_RATE_LIMITED", "429")
            return LLMResult('{"answer": "x"}', 120, 30)
    ledger = UsageLedger()
    p = RecordingProvider(Inner(), ledger)
    p.complete("s", "u", 10)
    with pytest.raises(JobError):
        p.complete("s", "u", 10)
    s = ledger.summary("claude-sonnet-5-5")
    assert s["calls"] == 2 and s["errors"] == 1 and s["error_codes"] == ["LLM_RATE_LIMITED"] and s["input_tokens"] == 120 and s["output_tokens"] == 30
    with pytest.raises(JobError) as ei:
        NoLLM().complete("s", "u", 1)
    assert ei.value.code == "LLM_NOT_CONFIGURED"


def test_rate_limiter_spaces_calls():
    now = [0.0]
    slept = []
    rl = RateLimiter(60, clock=lambda: now[0], sleep=lambda d: slept.append(d))
    rl.wait()
    rl.wait()
    rl.wait()
    assert slept == [1.0, 2.0]
    assert RateLimiter(None).wait() == 0.0


def test_latency_stats():
    assert latency_stats([])["mean"] is None
    s = latency_stats([0.1, 0.2, 0.3, 0.4])
    assert s["n"] == 4 and s["max"] == 0.4 and s["p50"] in (0.2, 0.3)


# ------------------------------------------------------------------ judge plumbing (no DeepEval needed)
def test_judge_resolution_reports_exact_missing_pieces():
    assert resolve(JudgeConfig(provider="none"), {})[0].state == "not_requested"
    assert "unsupported" in resolve(JudgeConfig(provider="vertex"), {})[0].reason
    assert "EVAL_JUDGE_MODEL is required" in resolve(JudgeConfig(provider="openai"), {})[0].reason

    def missing():
        raise ImportError(name="deepeval")
    st, _ = resolve(JudgeConfig(provider="anthropic"), {}, importer=missing)
    assert st.state == "skipped" and "deepeval is not installed" in st.reason and st.model == "claude-opus-5-5"
    st, _ = resolve(JudgeConfig(provider="anthropic"), {}, importer=lambda: {"version": "x"})
    assert st.state == "skipped" and "ANTHROPIC_API_KEY" in st.reason


def test_judge_key_and_env_config_come_from_environment_only():
    assert api_key_for("anthropic", {"EVAL_JUDGE_API_KEY": "k1", "ANTHROPIC_API_KEY": "k2"}) == ("k1", "EVAL_JUDGE_API_KEY")
    assert api_key_for("openai", {"OPENAI_API_KEY": "k3"}) == ("k3", "OPENAI_API_KEY")
    cfg = judge_from_env({"EVAL_JUDGE_PROVIDER": "Anthropic", "EVAL_JUDGE_TIMEOUT_S": "5", "EVAL_JUDGE_MAX_RETRIES": "0", "EVAL_JUDGE_PER_MINUTE": "6"})
    assert (cfg.provider, cfg.timeout_s, cfg.max_retries, cfg.per_minute) == ("anthropic", 5.0, 0, 6.0)


class _Metric:
    def __init__(self, behaviour):
        self.behaviour, self.score, self.reason, self.evaluation_cost = behaviour, None, None, 0.001

    def measure(self, case):
        b = self.behaviour.pop(0)
        if b == "slow":
            time.sleep(0.5)
        elif b == "boom":
            raise RuntimeError("judge exploded")
        self.score, self.reason = b, "because"


def test_judge_retries_times_out_and_records_errors_without_raising():
    plan = {"good": [0.9], "flaky": ["boom", 0.4], "dead": ["boom", "boom"], "slow": ["slow", "slow"]}
    metrics = {name: (lambda n=name: _Metric(plan[n])) for name in plan}
    j = Judge(JudgeConfig(provider="anthropic", timeout_s=0.1, max_retries=1, per_minute=None, threshold=0.5), metrics,
              make_case=lambda **kw: kw, sleep=lambda s: None)
    out = j.evaluate("q", "a", "e", [])
    j.close()
    assert out["good"]["score"] == 0.9 and out["good"]["passed"] and out["good"]["judge_cost_usd"] == 0.001
    assert out["flaky"]["score"] == 0.4 and out["flaky"]["passed"] is False and out["flaky"]["attempts"] == 2
    assert out["dead"]["score"] is None and "judge exploded" in out["dead"]["error"]
    assert out["slow"]["score"] is None and "timeout" in out["slow"]["error"]


# ------------------------------------------------------------------ reporting
def _results(**metrics):
    return {"run_id": "r", "started_at": "t", "duration_s": 1, "config": {"suite": "smoke", "repeats": 1},
            "sut": {"mode": "retrieval_only", "model": None, "answer_generation": "fallback"},
            "judge_status": {"state": "not_requested", "reason": "EVAL_JUDGE_PROVIDER is not set"},
            "benchmark": {"name": "raven-eval", "version": "1.0.0", "fingerprint": "f" * 64, "repos": ["a"]},
            "environment": {"python": "3.12", "raven_analyzer_version": "1.1.0", "git_commit": None, "deepeval": None},
            "metrics": {"graph": {}, "qa": {"n_ai": 0}, "operational": {k: latency_stats([]) for k in ("pipeline_s", "retrieve_s", "answer_s", "impact_s")}
                        | {"sut_llm": UsageLedger().summary(None)}, "reproducibility": {"repeats_compared": 1, "deterministic_outputs_identical": True, "unstable_outputs": []}} | metrics,
            "per_repo": {"graph": {}, "readiness": {}, "impact": {}}, "samples": {"qa": []}, "failures": []}


def test_thresholds_and_baseline_comparison():
    res = _results(graph={"routes": {"recall": 0.9}}, readiness={"rule_level": {"false_positive_rate": 0.1}})
    checks = check_thresholds(res, {"checks": [{"metric": "graph.routes.recall", "min": 1.0, "required": True},
                                               {"metric": "readiness.rule_level.false_positive_rate", "max": 0.2},
                                               {"metric": "qa.key_fact_recall_ai", "min": 0.5, "required": False},
                                               {"metric": "judge.correctness.mean", "min": 0.5, "required": True}]})
    st = {c["metric"]: (c["status"], c["passed"]) for c in checks}
    assert st == {"graph.routes.recall": ("fail", False), "readiness.rule_level.false_positive_rate": ("pass", True),
                  "qa.key_fact_recall_ai": ("not_applicable", True), "judge.correctness.mean": ("missing", False)}
    rows = {r["metric"]: r for r in compare_baseline(res, {"metrics": {"graph": {"routes": {"recall": 1.0}}, "readiness": {"rule_level": {"false_positive_rate": 0.05}}}})}
    assert rows["graph.routes.recall"]["regressed"] and rows["readiness.rule_level.false_positive_rate"]["regressed"]  # lower-is-better metric went up


def test_report_states_what_was_not_evaluated():
    res = _results()
    notes = " ".join(not_evaluated(res))
    assert "AI answer quality was not measured" in notes and "LLM-as-judge: not_requested" in notes
    md = render_markdown(res)
    assert "## Not evaluated in this run" in md and "| Q&A · key-fact recall (AI answers) | — |" in md


def test_reproducibility_counts_repeats_not_distinct_outputs():
    from evals.runner import aggregate
    repro = {"r": {"graph": {"same"}, "readiness": {"same"}}}
    m = aggregate({"graph": {}, "readiness": {}, "impact": {}, "retrieval": {}, "qa": {}}, {k: [] for k in ("pipeline_s", "retrieve_s", "answer_s", "impact_s")},
                  UsageLedger(), None, repro, {}, [], {}, {"r": 3})
    assert m["reproducibility"]["repeats_compared"] == 3 and m["reproducibility"]["deterministic_outputs_identical"] is True
