"""Regression tests for the API fields the Health, Impact and Ask screens read (frontend/js/view_health.js, view_impact.js, view_chat.js)."""
import json
import re

import pytest

from tests.conftest import create_analysis, emulate_n8n, new_other_client
from tests.fakes import FakeLLM
from tests.test_chat import ask, wire

SEV = ["critical", "high", "medium", "low", "info"]
CONF = ["high", "medium", "low"]


@pytest.fixture()
def ready(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    return aid


def stored_paths(c, aid):
    return {f["path"] for f in c.get(f"/api/v1/analyses/{aid}/files", params={"limit": 500}).json()["items"] if f["has_content"]}


# ------------------------------------------------------------------ readiness (Health)
def test_readiness_shape_used_by_health_view(user_client, ready):
    d = user_client.get(f"/api/v1/analyses/{ready}/readiness").json()
    assert d["available"] is True and d["filtered"] is False and d["disclaimer"] and d["not_assessed"]
    assert set(d["summary"]["by_severity"]) == set(SEV) and sum(d["summary"]["by_severity"].values()) == d["summary"]["total"]
    assert {"application_files", "test_files", "frontend_files", "routes"} <= set(d["summary"]["scope"])
    for f in d["findings"]:
        assert {"id", "rule", "category", "severity", "confidence", "kind", "title", "detail", "claim", "recommendation", "verify", "evidence", "evidence_total"} <= set(f)
        assert f["evidence_total"] >= len(f["evidence"])


def test_readiness_evidence_links_resolve_to_stored_source_lines(user_client, ready):
    d = user_client.get(f"/api/v1/analyses/{ready}/readiness").json()
    files = {f["path"]: f for f in user_client.get(f"/api/v1/analyses/{ready}/files", params={"limit": 500}).json()["items"]}
    checked = 0
    for f in d["findings"]:
        for ev in f["evidence"]:
            row = files.get(ev["path"])
            assert row is not None, (f["rule"], ev)                     # the source viewer link target exists
            if row["has_content"]:
                assert 1 <= ev["start_line"] <= ev["end_line"] <= max(row["line_count"], 1), (f["rule"], ev)
                checked += 1
    assert checked > 0


@pytest.mark.parametrize("params", [{"severity": "high", "min_confidence": "medium"}, {"category": "security", "kind": "potential_risk"},
                                    {"min_confidence": "medium"}, {"severity": "info", "category": "maintainability", "min_confidence": "low", "kind": "metric"}])
def test_readiness_filters_combine_with_and_semantics(user_client, ready, params):
    full = user_client.get(f"/api/v1/analyses/{ready}/readiness").json()["findings"]
    d = user_client.get(f"/api/v1/analyses/{ready}/readiness", params=params).json()

    def keep(f):
        return all([params.get("severity") in (None, f["severity"]), params.get("category") in (None, f["category"]), params.get("kind") in (None, f["kind"]),
                    "min_confidence" not in params or CONF.index(f["confidence"]) <= CONF.index(params["min_confidence"])])
    assert [f["id"] for f in d["findings"]] == [f["id"] for f in full if keep(f)]
    assert d["filtered"] == (len(d["findings"]) != len(full))
    assert d["summary"]["total"] == len(full)                            # summary counts stay unfiltered for the severity tiles


@pytest.mark.parametrize("bad", [{"severity": "urgent"}, {"min_confidence": "certain"}, {"kind": "confirmed"}, {"category": "perf"}])
def test_readiness_rejects_unknown_filter_values(user_client, ready, bad):
    r = user_client.get(f"/api/v1/analyses/{ready}/readiness", params=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_readiness_before_graph_is_a_clean_409(user_client):
    aid = create_analysis(user_client).json()["analysis_id"]
    r = user_client.get(f"/api/v1/analyses/{aid}/readiness")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE" and r.json()["error"]["message"]


# ------------------------------------------------------------------ change impact
def test_impact_shape_used_by_impact_view(user_client, ready):
    d = user_client.post(f"/api/v1/analyses/{ready}/impact", json={}).json()
    assert {"id", "created_at", "base_ref", "head_sha", "compare_url", "status", "ahead_by", "truncated", "summary", "changed", "affected", "routes", "tests", "frontend", "graph", "limitations"} <= set(d)
    assert {"changed_files", "affected_modules", "routes", "relevant_tests", "frontend_touched", "removed"} <= set(d["summary"])
    for c in d["changed"]:
        assert {"path", "status", "kind", "in_graph", "removed", "additions", "deletions"} <= set(c)
    for x in d["affected"]:
        assert {"path", "distance", "via", "resolution"} <= set(x) and x["resolution"] in ("verified_static", "inferred", "unresolved")
    for r in d["routes"]:
        assert {"method", "path", "file", "line", "path_status", "reason", "resolution"} <= set(r)
    for t in d["tests"]:
        assert {"path", "reason", "resolution"} <= set(t)
    assert all({"id", "role", "tag", "label", "path"} <= set(n) for n in d["graph"]["nodes"])
    ids = {n["id"] for n in d["graph"]["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in d["graph"]["edges"])


def test_impact_links_point_at_stored_files(user_client, ready):
    d = user_client.post(f"/api/v1/analyses/{ready}/impact", json={}).json()
    stored = stored_paths(user_client, ready)
    linked = [c["path"] for c in d["changed"] if c["in_graph"] and not c["removed"]] + [a["path"] for a in d["affected"]] + [a["via"] for a in d["affected"]] + \
             [r["file"] for r in d["routes"]] + [t["path"] for t in d["tests"]] + [f["path"] for f in d["frontend"]]
    assert linked and set(linked) <= stored, set(linked) - stored
    assert not any(c["in_graph"] for c in d["changed"] if c["removed"])  # removed files are rendered as plain text, not links


def test_impact_history_entry_matches_detail(user_client, ready):
    a = user_client.post(f"/api/v1/analyses/{ready}/impact", json={"base": "dev"}).json()
    items = user_client.get(f"/api/v1/analyses/{ready}/impact").json()["items"]
    assert items[0]["id"] == a["id"] and items[0]["base_ref"] == "dev" and items[0]["summary"]["changed_files"] == a["summary"]["changed_files"] and items[0]["created_at"]
    assert user_client.get(f"/api/v1/analyses/{ready}/impact/{a['id']}").json()["routes"] == a["routes"]


def test_impact_errors_carry_messages_for_the_form(app, user_client, ready):
    r = user_client.post(f"/api/v1/analyses/{ready}/impact", json={"base": "../x"})
    assert r.status_code == 422 and r.json()["error"]["message"]
    r = user_client.post(f"/api/v1/analyses/{ready}/impact", json={"base": "nope-branch"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "REF_NOT_FOUND" and r.json()["error"]["message"]
    r = user_client.post(f"/api/v1/analyses/{ready}/impact", json={"base": "dev", "extra": 1})
    assert r.status_code == 422
    other = new_other_client(app, "intruder2@example.com")
    assert other.get(f"/api/v1/analyses/{ready}/readiness").status_code == 404


def test_impact_requires_csrf(user_client, ready):
    token = user_client.headers.pop("X-CSRF-Token")
    try:
        r = user_client.post(f"/api/v1/analyses/{ready}/impact", json={})
        assert r.status_code == 403
    finally:
        user_client.headers["X-CSRF-Token"] = token


# ------------------------------------------------------------------ Q&A confidence / inferred
def _responder_with_inferred(system, user):
    if "answer questions" not in system:
        return FakeLLM.default_responder(system, user)
    p, a, _ = re.findall(r"\[E\d+\] (\S+) lines (\d+)-(\d+)", user)[0]
    return json.dumps({"answer": f"It is defined in {p}.", "citations": [{"path": p, "start_line": int(a), "end_line": int(a)}],
                       "evidence_sufficiency": "sufficient", "inferred": ["It is probably called on every request."], "limitations": []})


def test_ai_answer_keeps_inferred_claims_separate_and_labels_confidence(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, FakeLLM(_responder_with_inferred), monkeypatch)
    a = ask(user_client, ready, "What does get_current_user do?").json()["answer"]
    assert a["answer_source"] == "ai" and a["inferred"] == ["It is probably called on every request."]
    assert "probably" not in a["content"]                                # inferred text is not mixed into the supported answer
    assert a["confidence"] == "medium"                                   # inferred claims cap confidence below high
    assert a["citations"] and {"path", "start_line", "end_line", "excerpt"} <= set(a["citations"][0])
    hist = user_client.get(f"/api/v1/analyses/{ready}/chat").json()["items"]
    assert hist[-1]["inferred"] == a["inferred"] and hist[-1]["confidence"] == "medium"


def test_grounded_answer_without_inferred_claims_can_be_high(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, FakeLLM(), monkeypatch)
    a = ask(user_client, ready, "What does get_current_user do?").json()["answer"]
    assert a["answer_source"] == "ai" and a["inferred"] == [] and a["confidence"] in ("high", "medium")


def test_retrieval_only_fallback_has_low_confidence_and_no_inferred(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, None, monkeypatch)                           # no LLM configured in tests
    a = ask(user_client, ready, "What does get_current_user do?").json()["answer"]
    assert a["answer_source"] == "retrieval_only" and a["confidence"] == "low" and a["inferred"] == []
    assert a["citations"] and all({"path", "start_line", "end_line"} <= set(c) for c in a["citations"])
    assert stored_paths(user_client, ready) >= {c["path"] for c in a["citations"]}
