import threading
import uuid

import pytest
from sqlalchemy import func, select

from app.core.db import new_session
from app.core.errors import ApiError
from app.models import AnalysisJob, AnalysisTransition, WorkerTask, WorkflowRun
from app.services import state
from app.services.jobs import backoff_seconds
from tests.conftest import create_analysis, emulate_n8n, internal
from tests.fakes import FakeLLM

D = {"kind": "analysis", "workflow": "raven_repository_analysis", "execution_id": "e1"}


def test_dispatch_is_idempotent_by_key_and_by_state(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    r1 = internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={**D, "idempotency_key": "k1"}).json()
    r2 = internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={**D, "idempotency_key": "k1"}).json()
    assert r2["duplicate"] is True and r1["task_id"] == r2["task_id"]
    # a different key while still FETCHING re-uses the same task (no duplicate worker task)
    r3 = internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={**D, "idempotency_key": "k2"}).json()
    assert r3["task_id"] == r1["task_id"]
    with new_session() as db:
        assert db.execute(select(func.count()).select_from(WorkerTask)).scalar() == 1


def test_idempotency_key_reused_by_another_analysis_is_not_a_duplicate(user_client, gh_fake):
    """n8n execution ids repeat after its data is reset; a reused key must not replay another analysis's receipt."""
    a = create_analysis(user_client, "https://github.com/owner/one").json()["analysis_id"]
    b = create_analysis(user_client, "https://github.com/owner/two").json()["analysis_id"]
    ra = internal(user_client, "POST", f"/analysis-jobs/{a}/dispatch", json={**D, "idempotency_key": "7:dispatch:0:0"}).json()
    rb = internal(user_client, "POST", f"/analysis-jobs/{b}/dispatch", json={**D, "idempotency_key": "7:dispatch:0:0"}).json()
    assert "duplicate" not in rb and rb["analysis_id"] == b and rb["task_id"] != ra["task_id"]
    with new_session() as db:
        assert db.execute(select(AnalysisJob.state).where(AnalysisJob.id == uuid.UUID(b))).scalar() == "FETCHING"


def test_invalid_state_transitions_rejected(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    # stage-result / complete before the pipeline got there
    r = internal(user_client, "POST", f"/analysis-jobs/{aid}/stage-result", json={"stage": "graph", "workflow": "w", "execution_id": "e"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    r = internal(user_client, "POST", f"/analysis-jobs/{aid}/complete", json={"doc_id": str(uuid.uuid4()), "workflow": "w", "execution_id": "e"})
    assert r.status_code == 404
    r = internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": "docs_explain", "workflow": "w", "execution_id": "e", "doc_id": str(uuid.uuid4())})
    assert r.status_code == 404
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    r = internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={**D, "execution_id": "late"})
    assert r.status_code == 409  # READY jobs cannot be re-dispatched


def test_duplicate_callbacks_replay_receipts(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM(), exec_id="x")
    again = internal(user_client, "POST", f"/analysis-jobs/{aid}/stage-result", json={"stage": "graph", "workflow": "raven_repository_analysis", "execution_id": "x", "idempotency_key": "x:graph"})
    assert again.status_code == 200 and again.json()["duplicate"] is True
    comp = internal(user_client, "POST", f"/analysis-jobs/{aid}/complete", json={"doc_id": again.json()["doc_id"], "workflow": "w", "execution_id": "x", "idempotency_key": "x:complete"})
    assert comp.status_code == 200 and comp.json()["duplicate"] is True
    with new_session() as db:
        n = db.execute(select(func.count()).select_from(AnalysisTransition).where(AnalysisTransition.to_state == "READY")).scalar()
        assert n == 1


def test_fail_endpoint_restricts_codes_and_is_safe(user_client):
    aid = create_analysis(user_client).json()["analysis_id"]
    bad = internal(user_client, "POST", f"/analysis-jobs/{aid}/fail", json={"error_code": "<script>alert(1)</script>", "stage": "s", "workflow": "w", "execution_id": "e"})
    assert bad.status_code == 422
    ok = internal(user_client, "POST", f"/analysis-jobs/{aid}/fail", json={"error_code": "WORKFLOW_TIMEOUT", "stage": "poll", "workflow": "w", "execution_id": "e", "idempotency_key": "f1"})
    assert ok.status_code == 200 and ok.json()["state"] == "FAILED"
    a = user_client.get(f"/api/v1/analyses/{aid}").json()
    assert a["status"] == "FAILED" and a["error"]["code"] == "WORKFLOW_TIMEOUT" and a["retry_eligible"]
    # failing an already-failed job is a no-op, not a crash
    assert internal(user_client, "POST", f"/analysis-jobs/{aid}/fail", json={"error_code": "WORKFLOW_FAILED", "stage": "s", "workflow": "w", "execution_id": "e2"}).status_code == 200


def test_malformed_internal_payloads(user_client):
    aid = create_analysis(user_client).json()["analysis_id"]
    for body in ({}, {"kind": "nope", "workflow": "w", "execution_id": "e"}, {**D, "extra": 1}, {**D, "execution_id": ""}):
        assert internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json=body).status_code == 422
    assert internal(user_client, "POST", f"/analysis-jobs/{aid}/complete", json={"doc_id": "zzz", "workflow": "w", "execution_id": "e"}).status_code == 422


def test_concurrent_dispatch_creates_one_task(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    results = []

    def go(i):
        r = internal(user_client, "POST", f"/analysis-jobs/{aid}/dispatch", json={**D, "idempotency_key": f"c{i}"})
        results.append(r.status_code)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert set(results) == {200}
    with new_session() as db:
        assert db.execute(select(func.count()).select_from(WorkerTask)).scalar() == 1


def test_workflow_runs_record_execution_ids(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM(), exec_id="abc123")
    with new_session() as db:
        runs = db.execute(select(WorkflowRun.n8n_execution_id, WorkflowRun.workflow_name)).all()
    assert ("abc123", "raven_repository_analysis") in {tuple(r) for r in runs}


# --------------------------------------------------------------------- state machine unit tests
def _job(db, to="QUEUED"):
    from app.models import Repository, User
    u = User(email=f"{uuid.uuid4().hex[:6]}@example.com", password_hash="x")
    r = Repository(owner="o", name=uuid.uuid4().hex[:6], full_name="o/x", full_name_lower=uuid.uuid4().hex, canonical_url="u", default_branch="main")
    db.add_all([u, r]); db.flush()
    j = AnalysisJob(owner_id=u.id, repository_id=r.id, commit_sha="a" * 40, default_branch="main", analyzer_version="1", state=to, idempotency_key=uuid.uuid4().hex)
    db.add(j); db.flush()
    return j


ALL = ["QUEUED", "FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS", "READY", "RETRYING", "FAILED", "CANCELLED"]


@pytest.mark.parametrize("src", ALL)
@pytest.mark.parametrize("dst", ALL)
def test_transition_matrix(src, dst):
    with new_session() as db:
        j = _job(db, src)
        legal = dst in state.LEGAL[src]
        if legal:
            state.transition(db, j, dst, actor="test", error_code="GITHUB_UNAVAILABLE" if dst in ("FAILED", "RETRYING") else None)
            assert j.state == dst
        else:
            with pytest.raises(ApiError) as e:
                state.transition(db, j, dst, actor="test")
            assert e.value.code == "INVALID_STATE" and j.state == src
        db.rollback()


def test_terminal_states_are_terminal():
    assert state.LEGAL["READY"] == set() and state.LEGAL["CANCELLED"] == set() and state.LEGAL["FAILED"] == {"QUEUED"}


def test_backoff_bounded_with_jitter():
    import random
    from app.core.config import get_settings
    s = get_settings()
    vals = [backoff_seconds(a, s, random.Random(1)) for a in range(12)]
    assert all(0 < v <= s.retry_max_seconds for v in vals) and vals[3] > vals[0]
    assert len({backoff_seconds(2, s) for _ in range(20)}) > 1
