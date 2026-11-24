from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Environment must be set before the application modules are imported.
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql://raven:raven_dev_pw@127.0.0.1:5432/raven_test"),
    "APP_SECRET_KEY": "test-app-secret-key-0123456789abcdef0123",
    "INTERNAL_SERVICE_SECRET": "test-internal-secret-0123456789abcdef01",
    "N8N_WEBHOOK_SECRET": "test-n8n-webhook-secret-0123456789abcd",
    "N8N_BASE_URL": "http://n8n.invalid:5678",
    "LLM_API_KEY": "",
    "LLM_MODEL": "",
    "GITHUB_TOKEN": "",
    "RAVEN_SKIP_APP_BUILD": "1",
    "LOG_LEVEL": "WARNING",
    "MAX_STAGE_ATTEMPTS": "3",
})

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings, reset_settings_cache
from app.core.db import get_engine, reset_engine

BACKEND = Path(__file__).resolve().parents[1]
INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_SERVICE_SECRET"]}


def _migrate_fresh() -> None:
    engine = get_engine()
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, capture_output=True, text=True, env=os.environ.copy())
    assert r.returncode == 0, r.stderr


@pytest.fixture(scope="session", autouse=True)
def _database():
    reset_settings_cache()
    reset_engine()
    _migrate_fresh()
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def _clean_tables():
    from app.services import quotas
    quotas.reset_for_tests()
    yield
    with get_engine().begin() as c:
        c.execute(text("TRUNCATE users, repositories, audit_events, rate_limit_events, embedding_cache RESTART IDENTITY CASCADE"))


class FakeOrch:
    def __init__(self):
        self.triggers: list[tuple[str, dict]] = []
        self.accept = True
        self.qa_handler = None

    def trigger(self, workflow, payload):
        self.triggers.append((workflow, payload))
        return self.accept

    def run_qa(self, payload):
        if self.qa_handler:
            return self.qa_handler(payload)
        return {}

    def health(self):
        return {"reachable": True}


@pytest.fixture()
def orch():
    return FakeOrch()


@pytest.fixture()
def gh_fake():
    from tests.fakes import FakeGitHub
    return FakeGitHub()


@pytest.fixture()
def app(orch, gh_fake):
    from app.api import deps
    from app.main import create_app
    from app.services.github import GitHubClient
    application = create_app()
    application.dependency_overrides[deps.orchestrator_dep] = lambda: orch
    application.dependency_overrides[deps.github_dep] = lambda: GitHubClient(get_settings(), transport=gh_fake.transport())
    return application


@pytest.fixture()
def client(app):
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def register(client: TestClient, email: str = "dev@example.com", password: str = "correct-horse-battery") -> dict:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password}, headers={"Origin": "http://testserver"})
    assert r.status_code == 201, r.text
    client.headers["X-CSRF-Token"] = client.cookies.get("raven_csrf")
    return r.json()["user"]


@pytest.fixture()
def user_client(client):
    register(client)
    return client


@pytest.fixture()
def ready(user_client, gh_fake):
    """A finished analysis of the sample repository, owned by the signed-in user."""
    from tests.fakes import FakeLLM
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    return aid


def new_other_client(app, email: str) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    register(c, email)
    return c


# ------------------------------------------------------------------ n8n emulation helpers
def run_next_task(gh_fake, llm_fake=None) -> str | None:
    """Claim and execute one queued worker task in-process (what the worker process does)."""
    from app.services.github import GitHubClient
    from app.services.llm import AnthropicProvider
    from app.workers.docs_tasks import run_docs_assemble, run_docs_explain
    from app.workers.main import claim_task, finish_task
    from app.workers.stages import run_analysis_task
    s = get_settings()
    task = claim_task("test-worker", s)
    if task is None:
        return None
    try:
        if task.task_type == "analysis":
            run_analysis_task(task.analysis_id, github_factory=lambda st: GitHubClient(st, transport=gh_fake.transport()), settings=s)
        elif task.task_type == "docs_explain":
            provider = None
            if llm_fake is not None:
                provider = AnthropicProvider(s.model_copy(update={"llm_api_key": "k" * 20, "llm_model": "m"}), transport=llm_fake.transport(), sleep=lambda _: None)
            run_docs_explain(task.payload, task.analysis_id, s, provider)
        elif task.task_type == "docs_assemble":
            run_docs_assemble(task.payload, task.analysis_id)
        finish_task(task.id)
    except Exception:
        finish_task(task.id, "failed", "INTERNAL_ANALYSIS_ERROR")
        raise
    return task.task_type


def internal(client, method, path, **kw):
    return client.request(method, f"/internal/v1{path}", headers=INTERNAL, **kw)


def emulate_n8n(client, aid: str, gh_fake, llm_fake=None, exec_id: str = "exec1", max_rounds: int = 10) -> dict:
    """Perform exactly the calls the n8n analysis + documentation workflows make."""
    for rnd in range(max_rounds):
        r = internal(client, "POST", f"/analysis-jobs/{aid}/dispatch", json={
            "kind": "analysis", "workflow": "raven_repository_analysis", "execution_id": exec_id, "idempotency_key": f"{exec_id}:dispatch:{rnd}"})
        assert r.status_code == 200, r.text
        run_next_task(gh_fake, llm_fake)
        st = internal(client, "GET", f"/analysis-jobs/{aid}/status").json()
        if st["state"] == "RETRYING":
            continue
        if st["state"] in ("FAILED", "CANCELLED"):
            return st
        break
    st = internal(client, "GET", f"/analysis-jobs/{aid}/status").json()
    if not st["graph_complete"] or st["state"] != "BUILDING_GRAPH":
        return st
    r = internal(client, "POST", f"/analysis-jobs/{aid}/stage-result", json={"stage": "graph", "workflow": "raven_repository_analysis", "execution_id": exec_id, "idempotency_key": f"{exec_id}:graph"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["doc_id"]
    for kind in ("docs_explain", "docs_assemble"):
        r = internal(client, "POST", f"/analysis-jobs/{aid}/dispatch", json={"kind": kind, "workflow": "raven_documentation_generation", "execution_id": exec_id + "d", "doc_id": doc_id, "idempotency_key": f"{exec_id}:{kind}"})
        assert r.status_code == 200, r.text
        run_next_task(gh_fake, llm_fake)
    r = internal(client, "POST", f"/analysis-jobs/{aid}/complete", json={"doc_id": doc_id, "workflow": "raven_documentation_generation", "execution_id": exec_id + "d", "idempotency_key": f"{exec_id}:complete"})
    assert r.status_code == 200, r.text
    return internal(client, "GET", f"/analysis-jobs/{aid}/status").json()


def create_analysis(client, url="https://github.com/owner/sample"):
    r = client.post("/api/v1/analyses", json={"url": url}, headers={"Origin": "http://testserver"})
    return r
