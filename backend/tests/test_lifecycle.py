import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import new_session
from app.models import AnalysisFile, AnalysisJob, AnalysisTransition, CallbackReceipt, CodeEdge, CodeNode, Documentation, WorkerTask
from tests.conftest import create_analysis, emulate_n8n, internal, new_other_client, run_next_task
from tests.fakes import FakeLLM
from tests.fixtures.sample_repo import SHA


def test_full_pipeline_happy_path(user_client, orch, gh_fake):
    r = create_analysis(user_client)
    assert r.status_code == 202, r.text
    body = r.json()
    aid = body["analysis_id"]
    assert body["status"] == "QUEUED" and body["commit_sha"] == SHA and body["reused"] is False
    assert orch.triggers[0][0] == "raven_repository_analysis"
    final = emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    assert final["state"] == "READY" and final["docs"]["status"] == "READY"
    a = user_client.get(f"/api/v1/analyses/{aid}").json()
    assert a["status"] == "READY" and a["summary"]["inventory"]["python_analyzed"] >= 10
    states = [t["to"] for t in a["transitions"]]
    assert states == ["QUEUED", "FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS", "READY"]
    assert {r["workflow"] for r in a["workflow_runs"]} >= {"raven_repository_analysis", "raven_documentation_generation"}
    assert a["summary"]["graph"]["route_count"] >= 5


def test_graph_files_docs_download_apis(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    g = user_client.get(f"/api/v1/analyses/{aid}/graph", params={"types": "route"}).json()
    assert g["total_nodes"] >= 5 and all(n["type"] == "route" for n in g["nodes"])
    node = user_client.get(f"/api/v1/analyses/{aid}/graph/nodes/{g['nodes'][0]['id']}").json()
    assert node["source_url"].startswith(f"https://github.com/owner/sample/blob/{SHA}/")
    files = user_client.get(f"/api/v1/analyses/{aid}/files", params={"q": "users"}).json()
    f = next(i for i in files["items"] if i["path"] == "app/api/users.py")
    detail = user_client.get(f"/api/v1/analyses/{aid}/files/{f['id']}").json()
    assert "def list_users" in detail["content"] and detail["relationships"]["imports"] and detail["symbols"]
    svc = next(i for i in user_client.get(f"/api/v1/analyses/{aid}/files", params={"q": "user_service"}).json()["items"])
    content = user_client.get(f"/api/v1/analyses/{aid}/files/{svc['id']}").json()["content"]
    assert "AKIAABCDEFGHIJKLMNOP" not in content and "[REDACTED]" in content
    env = user_client.get(f"/api/v1/analyses/{aid}/files", params={"q": ".env"}).json()["items"]
    assert all(e["has_content"] is False or e["path"].endswith(".example") for e in env)
    docs = user_client.get(f"/api/v1/analyses/{aid}/docs").json()
    md = docs["document"]["markdown"]
    for n in range(1, 15):
        assert f"## {n}. " in md
    assert "GET" in md and "/api/users/" in md and f"blob/{SHA}/app/api/users.py" in md
    assert "AKIAABCDEFGHIJKLMNOP" not in md and "hunter2" not in md and "supersecretpassword" not in md
    assert "```mermaid" in md and "AI-generated summary" in md
    dl = user_client.get(f"/api/v1/analyses/{aid}/docs/download")
    assert dl.status_code == 200 and "attachment" in dl.headers["content-disposition"] and dl.text == md
    dia = user_client.get(f"/api/v1/analyses/{aid}/graph/diagram", params={"view": "modules"}).json()
    assert dia["mermaid"].startswith("flowchart") and dia["mapping"]
    for v in ("routes", "models"):
        assert user_client.get(f"/api/v1/analyses/{aid}/graph/diagram", params={"view": v}).json()["mermaid"]


def test_docs_without_llm_are_partial_and_honest(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    final = emulate_n8n(user_client, aid, gh_fake, None)  # LLM not configured
    assert final["state"] == "READY" and final["docs"]["status"] == "PARTIAL" and final["docs"]["ai_status"] == "unavailable"
    doc = user_client.get(f"/api/v1/analyses/{aid}/docs").json()["document"]
    assert "AI explanations are unavailable" in doc["markdown"] and any("AI explanations" in g for g in doc["gaps"])
    assert "AI-generated summary" not in doc["markdown"]
    files = user_client.get(f"/api/v1/analyses/{aid}/files").json()["items"]
    assert {f["explanation_source"] for f in files if f["kind"] == "python" and f["status"] == "analyzed"} == {"deterministic"}


def test_ai_output_validation_rejects_hallucinated_paths(user_client, gh_fake):
    import json as j
    def bad(system, user):
        if "onboarding notes" in system:
            return j.dumps({"explanations": [{"path": "does/not/exist.py", "summary": "x", "responsibilities": [], "symbols": [], "citations": []}]})
        return FakeLLM.default_responder(system, user)
    aid = create_analysis(user_client).json()["analysis_id"]
    final = emulate_n8n(user_client, aid, gh_fake, FakeLLM(bad))
    assert final["docs"]["ai_status"] in ("partial", "unavailable") and final["docs"]["status"] == "PARTIAL"
    with new_session() as db:
        assert db.execute(select(func.count()).select_from(AnalysisFile).where(AnalysisFile.explanation_source == "ai")).scalar() == 0


def test_duplicate_submission_returns_same_job(user_client, orch):
    a = create_analysis(user_client).json()
    b = create_analysis(user_client).json()
    assert a["analysis_id"] == b["analysis_id"] and b["reused"] is True
    assert len(orch.triggers) == 1
    with new_session() as db:
        assert db.execute(select(func.count()).select_from(AnalysisJob)).scalar() == 1


def test_ownership_enforced_everywhere(app, user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    other = new_other_client(app, "other@example.com")
    for path in ("", "/graph", "/graph/diagram", "/files", "/docs", "/docs/download", "/chat"):
        assert other.get(f"/api/v1/analyses/{aid}{path}").status_code == 404, path
    assert other.post(f"/api/v1/analyses/{aid}/chat", json={"message": "hi"}).status_code == 404
    assert other.post(f"/api/v1/analyses/{aid}/retry").status_code == 404
    assert other.post(f"/api/v1/analyses/{aid}/docs/generate").status_code == 404
    assert other.delete(f"/api/v1/analyses/{aid}").status_code == 404
    assert other.get("/api/v1/analyses").json()["total"] == 0
    # nested-resource IDOR: another user's node/file ids are not reachable through your own analysis
    mine = create_analysis(other, "https://github.com/owner/other").json()["analysis_id"]
    g = user_client.get(f"/api/v1/analyses/{aid}/graph").json()
    nid = g["nodes"][0]["id"]
    assert other.get(f"/api/v1/analyses/{mine}/graph/nodes/{nid}").status_code == 404
    fid = user_client.get(f"/api/v1/analyses/{aid}/files").json()["items"][0]["id"]
    assert other.get(f"/api/v1/analyses/{mine}/files/{fid}").status_code == 404
    assert other.get(f"/api/v1/analyses/{uuid.uuid4()}").status_code == 404
    assert user_client.get(f"/api/v1/analyses/{aid}").status_code == 200


def test_transient_failure_retries_then_succeeds(user_client, gh_fake):
    gh_fake.tarball_failures = [503, 503]
    aid = create_analysis(user_client).json()["analysis_id"]
    final = emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    assert final["state"] == "READY" and final["attempt"] == 2
    a = user_client.get(f"/api/v1/analyses/{aid}").json()
    seq = [t["to"] for t in a["transitions"]]
    assert seq.count("RETRYING") == 2 and seq[-1] == "READY"
    with new_session() as db:  # retries must not duplicate artifacts
        assert db.execute(select(func.count()).select_from(CodeNode).where(CodeNode.analysis_id == uuid.UUID(aid))).scalar() == \
            db.execute(select(func.count(func.distinct(CodeNode.node_key))).where(CodeNode.analysis_id == uuid.UUID(aid))).scalar()


def test_retry_exhaustion_fails_with_retryable_code_and_user_retry(user_client, gh_fake, orch):
    gh_fake.tarball_failures = [503] * 10
    aid = create_analysis(user_client).json()["analysis_id"]
    final = emulate_n8n(user_client, aid, gh_fake, None)
    assert final["state"] == "FAILED" and final["error_code"] == "GITHUB_UNAVAILABLE" and final["error_retryable"]
    a = user_client.get(f"/api/v1/analyses/{aid}").json()
    assert a["retry_eligible"] and a["error"]["message"] == "GitHub is temporarily unavailable."
    gh_fake.tarball_failures = []
    r = user_client.post(f"/api/v1/analyses/{aid}/retry")
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    assert orch.triggers[-1][0] == "raven_repository_analysis"
    assert emulate_n8n(user_client, aid, gh_fake, FakeLLM(), exec_id="exec2")["state"] == "READY"


@pytest.mark.parametrize("setup,code", [
    (lambda g: setattr(g, "files", {"README.md": "# no python", "a.txt": "x"}), "NO_PYTHON_FILES"),
    (lambda g: setattr(g, "files", {"broken.py": "def (:\n"}), "NO_PYTHON_FILES"),
])
def test_non_retryable_failures_do_not_retry(user_client, gh_fake, setup, code):
    setup(gh_fake)
    aid = create_analysis(user_client).json()["analysis_id"]
    final = emulate_n8n(user_client, aid, gh_fake, None)
    assert final["state"] == "FAILED" and final["error_code"] == code and not final["error_retryable"]
    assert user_client.post(f"/api/v1/analyses/{aid}/retry").status_code == 409


def test_submit_errors_map_to_safe_codes(user_client, gh_fake):
    gh_fake.repo_status = 404
    r = create_analysis(user_client)
    assert r.status_code == 404 and r.json()["error"]["code"] == "REPO_NOT_FOUND"
    gh_fake.repo_status = 200; gh_fake.private = True
    assert create_analysis(user_client).json()["error"]["code"] == "REPO_NOT_PUBLIC"
    gh_fake.private = False; gh_fake.rate_limit_on_repo = True
    r = create_analysis(user_client)
    assert r.status_code == 503 and r.json()["error"]["retryable"] is True and "Retry-After" in r.headers
    assert create_analysis(user_client, "https://evil.com/a/b").json()["error"]["code"] == "INVALID_REPOSITORY_URL"
    assert not any("evil" in x for x in gh_fake.requests)


def test_delete_cascades_everything(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    assert user_client.delete(f"/api/v1/analyses/{aid}").status_code == 204
    with new_session() as db:
        for model in (AnalysisFile, CodeNode, CodeEdge, Documentation, WorkerTask, CallbackReceipt, AnalysisTransition):
            assert db.execute(select(func.count()).select_from(model)).scalar() == 0, model
    assert user_client.get(f"/api/v1/analyses/{aid}").status_code == 404


def test_cancel_queued_and_running(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    assert user_client.post(f"/api/v1/analyses/{aid}/cancel").json()["status"] == "CANCELLED"
    assert internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e"}).status_code == 409
    assert user_client.post(f"/api/v1/analyses/{aid}/cancel").status_code == 409


def test_regenerate_docs_creates_new_version(user_client, orch, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    r = user_client.post(f"/api/v1/analyses/{aid}/docs/generate")
    assert r.status_code == 202 and r.json()["version"] == 2
    assert user_client.post(f"/api/v1/analyses/{aid}/docs/generate").json()["doc_id"] == r.json()["doc_id"]  # pending reused
    docs = user_client.get(f"/api/v1/analyses/{aid}/docs").json()
    assert docs["regenerating"] and docs["document"]["version"] == 1  # old version stays available
    doc_id = r.json()["doc_id"]
    for kind in ("docs_explain", "docs_assemble"):
        assert internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": kind, "workflow": "raven_documentation_generation", "execution_id": "r2", "doc_id": doc_id}).status_code == 200
        run_next_task(gh_fake, FakeLLM())
    assert user_client.get(f"/api/v1/analyses/{aid}/docs").json()["document"]["version"] == 2


def test_flow_and_trace_endpoints(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    f = user_client.get(f"/api/v1/analyses/{aid}/graph/flow").json()
    by_path = {n["path"]: n for n in f["nodes"] if n["path"]}
    assert by_path["app/main.py"]["role"] == "entry"
    assert by_path["app/api/users.py"]["role"] == "router" and by_path["app/api/users.py"]["counts"]["routes"] == 2
    assert by_path["app/schemas.py"]["role"] == "model" and by_path["app/models.py"]["role"] == "model"
    assert not any(p.startswith("tests/") for p in by_path)  # tests hidden by default
    ids = {n["id"] for n in f["nodes"]}
    assert f["edges"] and all(e["source"] in ids and e["target"] in ids for e in f["edges"])
    main_to_items = next(e for e in f["edges"] if e["source"] == by_path["app/main.py"]["id"] and e["target"] == by_path["app/api/items.py"]["id"])
    assert main_to_items["resolution"] == "verified_static" and main_to_items["evidence"] and "imports" in main_to_items["kinds"]
    ext = [n for n in f["nodes"] if n["kind"] == "external"]
    assert {"fastapi"} <= {n["label"] for n in ext}
    assert any(n["path"] and n["path"].startswith("tests/") for n in user_client.get(f"/api/v1/analyses/{aid}/graph/flow?include_tests=true").json()["nodes"])
    focused = user_client.get(f"/api/v1/analyses/{aid}/graph/flow?focus=app/api").json()
    assert all(n["path"] is None or n["path"].startswith("app/api/") or n["context"] for n in focused["nodes"])
    assert user_client.get(f"/api/v1/analyses/{aid}/graph/flow?limit=5").status_code == 422
    routes = user_client.get(f"/api/v1/analyses/{aid}/graph", params={"types": "route"}).json()["nodes"]
    r = next(x for x in routes if x["name"] == "GET /api/users/")
    t = user_client.get(f"/api/v1/analyses/{aid}/graph/trace", params={"node_id": r["id"]}).json()
    labels = {n["label"] for n in t["nodes"]}
    assert {"GET /api/users/", "list_users", "get_db", "UserOut"} <= labels
    rel = {(e["relation"]) for e in t["edges"]}
    assert "handled_by" in rel and "uses_dependency" in rel
    nm = {n["id"]: n["label"] for n in t["nodes"]}
    assert any(nm[e["source"]] == "GET /api/users/" and nm[e["target"]] == "list_users" and e["relation"] == "handled_by" for e in t["edges"])
    other = new_other_client(user_client.app, "o2@example.com")
    mine = create_analysis(other, "https://github.com/owner/other").json()["analysis_id"]
    assert other.get(f"/api/v1/analyses/{aid}/graph/flow").status_code == 404
    assert other.get(f"/api/v1/analyses/{mine}/graph/trace", params={"node_id": r["id"]}).status_code in (404, 409)
