"""Sprint 3: pull-request intelligence, usage accounting."""
import uuid

import pytest

from app.analysis.urls import parse_pr_url
from app.core.config import get_settings
from app.core.db import new_session
from app.core.errors import ApiError
from app.models import AnalysisJob
from tests.conftest import emulate_n8n, new_other_client
from tests.fakes import FakeLLM
from tests.test_architecture import B, H, SHA1, SHA2
from tests.test_chat import ask, wire

HDR = {"Origin": "http://testserver"}
H2 = {**H, "app/services/newthing.py": "def compute(x):\n    return x\n", "app/services/auth_utils.py": "def check(token):\n    return bool(token)\n"}
URL = "https://github.com/owner/sample/pull/7"


def open_pr(client, gh, head_files=H2, base_files=B, number=7, **pr):
    gh.files_by_sha = {SHA1: base_files, SHA2: head_files}
    gh.pulls[number] = {"number": number, "title": "Rework pricing", "base": SHA1, "head": SHA2, **pr}
    return client.post("/api/v1/pr-reviews", json={"url": f"https://github.com/owner/sample/pull/{number}"}, headers=HDR)


def finish(client, gh, rv):
    for n, side in enumerate(("base", "head")):
        emulate_n8n(client, rv[side]["analysis_id"], gh, FakeLLM(), exec_id=f"pr{side}{n}")
    return client.get(f"/api/v1/pr-reviews/{rv['id']}").json()


def test_parse_pr_url_is_strict():
    ref, n = parse_pr_url("https://github.com/o/r/pull/12/")
    assert (ref.owner, ref.name, n) == ("o", "r", 12)
    for bad in ("https://github.com/o/r/pull/0", "https://github.com/o/r/pull/x", "https://github.com/o/r/issues/3", "http://github.com/o/r/pull/1",
                "https://evil.com/o/r/pull/1", "https://github.com/o/r/pull/1?x=1", "https://github.com/o/r/pull/1/files"):
        with pytest.raises(ApiError):
            parse_pr_url(bad)


def test_pr_review_end_to_end_with_evidence(user_client, gh_fake):
    r = open_pr(user_client, gh_fake)
    assert r.status_code == 202 and r.json()["status"] == "PENDING" and r.json()["review"] is None
    rv = r.json()
    assert rv["base"]["analysis_id"] != rv["head"]["analysis_id"] and rv["number"] == 7
    done = finish(user_client, gh_fake, rv)
    assert done["status"] == "READY"
    rev = done["review"]
    assert rev["risk"] == "high" and rev["head"]["commit_sha"] == SHA2
    kinds = {f["kind"] for f in rev["findings"]}
    assert {"new_dependency", "new_cycle", "boundary_violation", "breaking_signature_changed", "missing_tests", "sensitive_area_changed"} <= kinds
    miss = {m["path"] for m in rev["missing_tests"]}
    assert "app/services/newthing.py" in miss and "app/services/pricing.py" not in miss  # pricing is imported by tests/test_pricing.py
    assert "app/services/newthing.py" in rev["changed_files"]["added"] and "app/services/pricing.py" in rev["changed_files"]["modified"]
    # nothing invented: every comment is backed by a finding evidence item that names an existing file at the cited commit
    files = {SHA1: set(B), SHA2: set(H2)}
    assert rev["comments"] and all(c["path"] in files[c["commit_sha"]] and c["line"] >= 1 and c["body"] for c in rev["comments"])
    ev = {(e["path"], e["start_line"]) for f in rev["findings"] for e in f["evidence"]}
    assert all((c["path"], c["line"]) in ev for c in rev["comments"])
    md = user_client.get(f"/api/v1/pr-reviews/{rv['id']}/markdown").text
    assert "Rework pricing" in md and "app/services/newthing.py" in md and "Limitations" in md
    # idempotent resubmission: same review, same stored result, no extra analyses
    again = user_client.post("/api/v1/pr-reviews", json={"url": URL}, headers=HDR).json()
    assert again["id"] == rv["id"] and again["review"]["computed_at"] == rev["computed_at"]
    with new_session() as db:
        assert db.query(AnalysisJob).count() == 2


def test_clean_pr_has_no_findings(user_client, gh_fake):
    rv = open_pr(user_client, gh_fake, head_files=B).json()
    rev = finish(user_client, gh_fake, rv)["review"]
    assert rev["findings"] == [] and rev["comments"] == [] and rev["risk"] == "low"
    assert rev["changed_files"] == {"added": [], "modified": [], "deleted": [], "renamed": []}


def test_rejections_fork_unknown_and_failed_analysis(user_client, gh_fake):
    r = open_pr(user_client, gh_fake, head_repo="someone/fork")
    assert r.status_code == 422 and r.json()["error"]["code"] == "PR_FORK_UNSUPPORTED"
    assert user_client.post("/api/v1/pr-reviews", json={"url": "https://github.com/owner/sample/pull/999"}, headers=HDR).status_code == 404
    assert user_client.post("/api/v1/pr-reviews", json={"url": "https://github.com/owner/sample"}, headers=HDR).status_code in (400, 422)
    rv = open_pr(user_client, gh_fake, number=8).json()
    with new_session() as db:
        j = db.get(AnalysisJob, uuid.UUID(rv["head"]["analysis_id"]))
        j.state = "FAILED"
        db.commit()
    got = user_client.get(f"/api/v1/pr-reviews/{rv['id']}").json()
    assert got["status"] == "FAILED" and got["error"]["code"] == "PR_ANALYSIS_FAILED" and got["review"] is None


def test_reviews_are_private_to_their_owner(app, user_client, gh_fake):
    rv = finish(user_client, gh_fake, open_pr(user_client, gh_fake).json())
    other = new_other_client(app, "nosy@example.com")
    assert other.get(f"/api/v1/pr-reviews/{rv['id']}").status_code == 404
    assert other.get(f"/api/v1/pr-reviews/{rv['id']}/markdown").status_code == 404
    assert other.get("/api/v1/pr-reviews").json()["items"] == []
    assert [i["id"] for i in user_client.get("/api/v1/pr-reviews").json()["items"]] == [rv["id"]]
    assert all(i["review"] is None for i in user_client.get("/api/v1/pr-reviews").json()["items"])  # list view never carries the full review


def test_usage_is_owner_only(app, user_client, gh_fake):
    rv = open_pr(user_client, gh_fake).json()
    assert new_other_client(app, "u2@example.com").get(f"/api/v1/analyses/{rv['head']['analysis_id']}/usage").status_code == 404


def test_usage_records_measured_tokens_latency_and_never_invents_cost(user_client, gh_fake, orch, monkeypatch):
    wire(orch, user_client, FakeLLM(), monkeypatch)
    rv = open_pr(user_client, gh_fake).json()
    finish(user_client, gh_fake, rv)
    aid = rv["head"]["analysis_id"]
    assert ask(user_client, aid, "what does price do in app/services/pricing.py?").status_code == 200
    u = user_client.get(f"/api/v1/analyses/{aid}/usage").json()
    assert u["qa"]["answers"] == 1 and u["qa"]["ai_calls_measured"] == 1 and u["qa"]["latency_ms"]["p50"] >= 0
    assert u["total"]["input_tokens"] > 0 and u["total"]["estimated_cost_usd"] is None and "not computed" in u["total"]["cost_basis"]
    s = get_settings()
    monkeypatch.setattr(s, "llm_price_input_per_mtok", 3.0)
    monkeypatch.setattr(s, "llm_price_output_per_mtok", 15.0)
    u2 = user_client.get(f"/api/v1/analyses/{aid}/usage").json()
    t = u2["total"]
    assert t["estimated_cost_usd"] == pytest.approx(t["input_tokens"] / 1e6 * 3 + t["output_tokens"] / 1e6 * 15, abs=1e-6)


def test_blank_price_variables_from_compose_mean_unset(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_MTOK", "")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_MTOK", "15")
    from app.core.config import Settings
    s = Settings()
    assert s.llm_price_input_per_mtok is None and s.llm_price_output_per_mtok == 15.0
