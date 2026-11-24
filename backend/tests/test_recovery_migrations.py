import subprocess
import sys
import uuid

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import get_engine, new_session
from app.models import AnalysisJob, Documentation
from app.workers.main import claim_task, recover
from tests.conftest import BACKEND, create_analysis, internal, run_next_task
from tests.fakes import FakeLLM


class Orch:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def trigger(self, wf, payload):
        self.calls.append(wf)
        return self.ok


def test_expired_lease_requeues_and_pipeline_completes(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e"})
    s = get_settings()
    t = claim_task("dead-worker", s)  # worker claims then "crashes" without finishing
    assert t is not None and claim_task("other", s) is None  # nobody else can take a leased task
    with new_session() as db:
        db.execute(text("UPDATE worker_tasks SET lease_expires_at = now() - interval '5 minutes'"))
        db.commit()
    counts = recover(s, Orch())
    assert counts["leases_reset"] == 1
    assert run_next_task(gh_fake, FakeLLM()) == "analysis"
    st = internal(user_client, "GET", f"/analysis-jobs/{aid}/status").json()
    assert st["state"] == "BUILDING_GRAPH" and st["graph_complete"]


def test_crash_mid_pipeline_is_recovered_idempotently(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e"})
    run_next_task(gh_fake)  # full run
    with new_session() as db:  # simulate a crash that left the job in PARSING with an expired lease
        db.execute(text("UPDATE analysis_jobs SET state='PARSING', graph_complete=false"))
        db.execute(text("UPDATE worker_tasks SET status='running', lease_expires_at = now() - interval '1 minute', attempts=1"))
        db.commit()
    recover(get_settings(), Orch())
    assert run_next_task(gh_fake) == "analysis"
    with new_session() as db:
        j = db.execute(select(AnalysisJob)).scalar_one()
        assert j.state == "BUILDING_GRAPH" and j.graph_complete
        n = db.execute(text("SELECT count(*), count(distinct node_key) FROM code_nodes")).one()
        assert n[0] == n[1] > 0


def test_repeatedly_lost_task_fails_job(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e"})
    with new_session() as db:
        db.execute(text("UPDATE worker_tasks SET status='running', attempts=5, lease_expires_at = now() - interval '1 minute'"))
        db.commit()
    recover(get_settings(), Orch())
    st = internal(user_client, "GET", f"/analysis-jobs/{aid}/status").json()
    assert st["state"] == "FAILED" and st["error_code"] == "WORKER_LOST"


def test_unreached_orchestrator_retriggers_then_fails(user_client, orch):
    aid = create_analysis(user_client).json()["analysis_id"]
    s = get_settings()
    o = Orch(ok=False)
    for _i in range(s.trigger_max_attempts + 1):
        with new_session() as db:
            db.execute(text("UPDATE analysis_jobs SET last_triggered_at = now() - interval '10 minutes'"))
            db.commit()
        recover(s, o)
    st = internal(user_client, "GET", f"/analysis-jobs/{aid}/status").json()
    assert st["state"] == "FAILED" and st["error_code"] == "ORCHESTRATOR_UNAVAILABLE"
    assert user_client.get(f"/api/v1/analyses/{aid}").json()["retry_eligible"] is True
    assert o.calls.count("raven_repository_analysis") >= s.trigger_max_attempts - 1


def test_recent_trigger_not_repeated(user_client, orch):
    create_analysis(user_client)
    o = Orch()
    assert recover(get_settings(), o)["retriggered"] == 0 and o.calls == []


def test_unfinished_docs_are_retriggered(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e"})
    run_next_task(gh_fake)
    internal(user_client, "POST", f"/analysis-jobs/{aid}/stage-result", json={"stage": "graph", "workflow": "w", "execution_id": "e"})
    o = Orch()
    with new_session() as db:
        db.execute(text("UPDATE documentation SET last_triggered_at = now() - interval '10 minutes'"))
        db.commit()
    assert recover(get_settings(), o)["retriggered"] == 1 and o.calls == ["raven_documentation_generation"]


def test_docs_failure_marks_doc_not_ready_and_fail_endpoint(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e"})
    run_next_task(gh_fake)
    doc_id = internal(user_client, "POST", f"/analysis-jobs/{aid}/stage-result", json={"stage": "graph", "workflow": "w", "execution_id": "e"}).json()["doc_id"]
    r = internal(user_client, "POST", f"/analysis-jobs/{aid}/complete", json={"doc_id": doc_id, "workflow": "w", "execution_id": "e"})
    assert r.status_code == 409  # cannot complete before docs exist
    internal(user_client, "POST", f"/analysis-jobs/{aid}/fail", json={"error_code": "WORKFLOW_FAILED", "stage": "docs", "workflow": "w", "execution_id": "e", "doc_id": doc_id})
    with new_session() as db:
        assert db.get(Documentation, uuid.UUID(doc_id)).status == "FAILED"
    assert user_client.get(f"/api/v1/analyses/{aid}").json()["status"] == "FAILED"


def test_user_retry_after_docs_failure_reuses_graph(user_client, gh_fake, orch):
    aid = create_analysis(user_client).json()["analysis_id"]
    internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e"})
    run_next_task(gh_fake)
    internal(user_client, "POST", f"/analysis-jobs/{aid}/stage-result", json={"stage": "graph", "workflow": "w", "execution_id": "e"})
    internal(user_client, "POST", f"/analysis-jobs/{aid}/fail", json={"error_code": "WORKFLOW_FAILED", "stage": "docs", "workflow": "w", "execution_id": "e"})
    before = len(gh_fake.requests)
    assert user_client.post(f"/api/v1/analyses/{aid}/retry").status_code == 202
    internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "analysis", "workflow": "w", "execution_id": "e2"})
    run_next_task(gh_fake)
    assert len(gh_fake.requests) == before  # cached artifacts reused: GitHub was not hit again
    assert internal(user_client, "GET", f"/analysis-jobs/{aid}/status").json()["state"] == "BUILDING_GRAPH"


# -------------------------------------------------------------------------- migrations
def alembic(*args):
    import os
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, capture_output=True, text=True, env=os.environ.copy())


def test_migrations_match_models_and_roundtrip():
    r = alembic("check")
    assert r.returncode == 0, r.stdout + r.stderr  # models and migrations are in sync
    r = alembic("downgrade", "base")
    assert r.returncode == 0, r.stderr
    with get_engine().connect() as c:
        tables = {row[0] for row in c.execute(text("select tablename from pg_tables where schemaname='public'"))}
    assert tables <= {"alembic_version"}
    r = alembic("upgrade", "head")
    assert r.returncode == 0, r.stderr
    with get_engine().connect() as c:
        tables = {row[0] for row in c.execute(text("select tablename from pg_tables where schemaname='public'"))}
    assert {"users", "analysis_jobs", "code_nodes", "code_edges", "documentation", "chat_messages", "workflow_runs", "audit_events", "worker_tasks"} <= tables
