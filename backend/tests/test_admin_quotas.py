import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import new_session
from app.core.errors import ApiError
from app.models import AdminEvent, ChatMessage, User
from app.services import quotas
from tests.conftest import create_analysis, new_other_client, register

O = {"Origin": "http://testserver"}


def _set(email, **cols):
    with new_session() as db:
        u = db.execute(select(User).where(User.email == email)).scalar_one()
        for k, v in cols.items():
            setattr(u, k, v)
        db.commit()
        return str(u.id)


@pytest.fixture()
def admin(client):
    register(client, "boss@example.com")
    _set("boss@example.com", role="admin")
    return client


def test_admin_api_requires_admin_role(user_client, client):
    for path in ("overview", "users", "analyses", "failures", "spend", "audit"):
        r = user_client.get(f"/api/v1/admin/{path}")
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN", path
    anon = client.__class__(client.app, base_url="http://testserver")
    assert anon.get("/api/v1/admin/overview").status_code == 401


def test_admin_read_endpoints(admin, gh_fake):
    create_analysis(admin)
    assert admin.get("/api/v1/me").json()["user"]["role"] == "admin"
    ov = admin.get("/api/v1/admin/overview").json()
    assert ov["users"]["total"] == 1 and sum(ov["analyses_24h"].values()) == 1
    us = admin.get("/api/v1/admin/users?q=boss").json()["users"]
    assert us[0]["email"] == "boss@example.com" and us[0]["today"]["analyses"] == 1 and us[0]["limits"]["analyses"] == get_settings().daily_analyses
    assert len(admin.get("/api/v1/admin/analyses").json()["analyses"]) == 1
    assert admin.get("/api/v1/admin/failures").json()["failures"] == []
    assert admin.get("/api/v1/admin/spend").status_code == 200 and admin.get("/api/v1/admin/audit").status_code == 200


def test_disable_blocks_everything_and_enable_restores(admin, app):
    other = new_other_client(app, "victim@example.com")
    uid = str(_uid("victim@example.com"))
    assert other.get("/api/v1/me").status_code == 200
    assert admin.post(f"/api/v1/admin/users/{uid}/disable", json={"reason": "abuse"}, headers=O).status_code == 200
    r = other.get("/api/v1/me")
    assert r.status_code in (401, 403)  # sessions were revoked
    fresh = new_other_client_login(app, "victim@example.com")
    assert fresh.status_code == 403 and fresh.json()["error"]["code"] == "ACCOUNT_DISABLED"
    assert admin.post(f"/api/v1/admin/users/{uid}/enable", headers=O).status_code == 200
    assert new_other_client_login(app, "victim@example.com").status_code == 200
    actions = [e["action"] for e in admin.get("/api/v1/admin/audit").json()["events"]]
    assert actions[:2] == ["user.enable", "user.disable"]


def _uid(email):
    with new_session() as db:
        return db.execute(select(User.id).where(User.email == email)).scalar_one()


def new_other_client_login(app, email):
    from fastapi.testclient import TestClient
    c = TestClient(app, base_url="http://testserver")
    return c.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery"}, headers=O)


def test_cannot_disable_self_or_another_admin(admin, app):
    me = str(_uid("boss@example.com"))
    assert admin.post(f"/api/v1/admin/users/{me}/disable", json={}, headers=O).status_code == 403
    new_other_client(app, "second@example.com"); _set("second@example.com", role="admin")
    assert admin.post(f"/api/v1/admin/users/{_uid('second@example.com')}/disable", json={}, headers=O).status_code == 403


def test_admin_mutations_need_csrf_and_valid_body(admin, app):
    new_other_client(app, "x@example.com")
    uid = _uid("x@example.com")
    admin.headers.pop("X-CSRF-Token")
    assert admin.post(f"/api/v1/admin/users/{uid}/disable", json={}, headers=O).status_code == 403
    admin.headers["X-CSRF-Token"] = admin.cookies.get("raven_csrf")
    assert admin.put(f"/api/v1/admin/users/{uid}/quotas", json={"quota_analyses_day": -1}, headers=O).status_code == 422
    assert admin.post(f"/api/v1/admin/users/{uuid.uuid4()}/enable", headers=O).status_code == 404


def test_daily_analysis_quota_and_admin_override(admin, gh_fake):
    _set("boss@example.com", quota_analyses_day=1)
    assert create_analysis(admin, "https://github.com/owner/one").status_code == 202
    r = create_analysis(admin, "https://github.com/owner/two")
    assert r.status_code == 429 and r.json()["error"]["code"] == "QUOTA_EXCEEDED"
    uid = _uid("boss@example.com")
    assert admin.put(f"/api/v1/admin/users/{uid}/quotas", json={"quota_analyses_day": 5}, headers=O).status_code == 200
    assert create_analysis(admin, "https://github.com/owner/two").status_code == 202


def test_question_and_token_quotas(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    s = get_settings()
    with new_session() as db:
        u = db.execute(select(User)).scalar_one()
        quotas.enforce(db, u, "question", s)  # nothing used yet
        db.add(ChatMessage(owner_id=u.id, analysis_id=uuid.UUID(aid), role="assistant", content="a", input_tokens=900, output_tokens=200))
        db.commit()
        u.quota_tokens_day = 1000
        with pytest.raises(ApiError) as e:
            quotas.enforce(db, u, "question", s)
        assert e.value.code == "QUOTA_EXCEEDED"
        u.quota_tokens_day = None; u.quota_questions_day = 0
        with pytest.raises(ApiError):
            quotas.enforce(db, u, "question", s)
        use = quotas.usage_today(db, u.id, s)
        assert use["tokens"] == 1100 and use["questions"] == 0


def test_spend_cap_uses_configured_prices():
    s = get_settings().model_copy(update={"llm_price_input_per_mtok": 1.0, "llm_price_output_per_mtok": 2.0})
    assert quotas.cost_usd(1_000_000, 500_000, s) == 2.0
    assert quotas.cost_usd(1, 1, get_settings().model_copy(update={"llm_price_input_per_mtok": None})) is None


def test_per_endpoint_rate_limits():
    s = get_settings().model_copy(update={"rl_read_per_minute": 3, "rl_write_per_minute": 2})
    quotas.reset_for_tests()
    with new_session() as db:
        u = User(email="r@example.com", password_hash="x"); db.add(u); db.flush()
        for _ in range(3):
            quotas.endpoint_limit(db, u, "GET", "/api/v1/analyses", s)
        with pytest.raises(ApiError) as e:
            quotas.endpoint_limit(db, u, "GET", "/api/v1/analyses", s)
        assert e.value.code == "RATE_LIMITED"
        quotas.endpoint_limit(db, u, "GET", "/api/v1/status", s)  # separate budget per route
        for _ in range(2):
            quotas.endpoint_limit(db, u, "POST", "/api/v1/x", s)
        with pytest.raises(ApiError):
            quotas.endpoint_limit(db, u, "POST", "/api/v1/x", s)
        db.rollback()
