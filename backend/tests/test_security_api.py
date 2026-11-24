from fastapi.testclient import TestClient

from tests.conftest import INTERNAL, create_analysis, register

O = {"Origin": "http://testserver"}


def test_register_login_logout_cookies(client):
    r = client.post("/api/v1/auth/register", json={"email": "A@Example.com", "password": "correct-horse-battery"}, headers=O)
    assert r.status_code == 201 and r.json()["user"]["email"] == "a@example.com"
    sc = r.headers.get_list("set-cookie")
    sess = next(c for c in sc if c.startswith("raven_session"))
    assert "HttpOnly" in sess and "samesite=lax" in sess.lower() and "Path=/" in sess
    csrf = next(c for c in sc if c.startswith("raven_csrf"))
    assert "HttpOnly" not in csrf
    assert "password" not in r.text.lower()
    client.headers["X-CSRF-Token"] = client.cookies["raven_csrf"]
    assert client.get("/api/v1/me").json()["user"]["email"] == "a@example.com"
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/me").status_code == 401


def test_session_revoked_server_side(client):
    register(client)
    token = client.cookies["raven_session"]
    client.post("/api/v1/auth/logout")
    client.cookies.set("raven_session", token)
    assert client.get("/api/v1/me").status_code == 401  # logout invalidated the stored session, not just the cookie


def test_password_validation_duplicates_and_generic_login_error(client):
    assert client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}, headers=O).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "correct-horse-battery"}, headers=O).status_code == 422
    register(client, "dup@example.com")
    c2 = TestClient(client.app, base_url="http://testserver")
    assert c2.post("/api/v1/auth/register", json={"email": "dup@example.com", "password": "correct-horse-battery"}, headers=O).json()["error"]["code"] == "EMAIL_TAKEN"
    a = c2.post("/api/v1/auth/login", json={"email": "dup@example.com", "password": "wrong-password-1"}, headers=O)
    b = c2.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "wrong-password-1"}, headers=O)
    assert a.status_code == b.status_code == 401 and a.json()["error"]["message"] == b.json()["error"]["message"]


def test_password_stored_as_argon2id(client):
    register(client)
    from sqlalchemy import select
    from app.core.db import new_session
    from app.models import User
    with new_session() as db:
        h = db.execute(select(User.password_hash)).scalar_one()
    assert h.startswith("$argon2id$") and "correct-horse" not in h


def test_login_rate_limited(client):
    register(client, "rl@example.com")
    c2 = TestClient(client.app, base_url="http://testserver")
    codes = [c2.post("/api/v1/auth/login", json={"email": "rl@example.com", "password": "bad-password-xx"}, headers=O).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    r = c2.post("/api/v1/auth/login", json={"email": "rl@example.com", "password": "correct-horse-battery"}, headers=O)
    assert r.status_code == 429 and r.headers["retry-after"] and r.json()["error"]["retryable"] is True


def test_csrf_required_for_mutations(user_client):
    del user_client.headers["X-CSRF-Token"]
    r = user_client.post("/api/v1/analyses", json={"url": "https://github.com/owner/sample"}, headers=O)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_FAILED"
    user_client.headers["X-CSRF-Token"] = "0" * 64
    assert user_client.post("/api/v1/analyses", json={"url": "https://github.com/owner/sample"}, headers=O).status_code == 403
    # GET needs no token
    assert user_client.get("/api/v1/analyses").status_code == 200


def test_cross_origin_mutation_rejected(user_client):
    r = user_client.post("/api/v1/analyses", json={"url": "https://github.com/owner/sample"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_FAILED"
    r = TestClient(user_client.app, base_url="http://testserver").post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_csrf_token_bound_to_session(app, user_client):
    other = TestClient(app, base_url="http://testserver")
    register(other, "second@example.com")
    user_client.headers["X-CSRF-Token"] = other.cookies["raven_csrf"]  # another user's valid token
    assert user_client.post("/api/v1/analyses", json={"url": "https://github.com/owner/sample"}, headers=O).status_code == 403


def test_unauthenticated_endpoints(client):
    for m, p in [("get", "/api/v1/analyses"), ("get", "/api/v1/me"), ("get", "/api/v1/status"), ("post", "/api/v1/analyses"),
                 ("get", "/api/v1/analyses/00000000-0000-0000-0000-000000000000")]:
        r = getattr(client, m)(p)
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_security_headers_and_request_id(client):
    r = client.get("/health/live", headers={"X-Request-ID": "abcdef123456"})
    assert r.headers["x-request-id"] == "abcdef123456"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "object-src 'none'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp and "script-src 'self' 'unsafe-inline'" not in csp
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cross-origin-resource-policy"] == "same-origin" and r.headers["x-permitted-cross-domain-policies"] == "none"
    assert "frame-src 'none'" in csp and "payment=()" in r.headers["permissions-policy"] and r.headers["cross-origin-opener-policy"] == "same-origin"
    r2 = client.get("/health/live", headers={"X-Request-ID": "bad id with spaces\r\n"})
    assert r2.headers["x-request-id"] != "bad id with spaces"
    assert client.get("/api/v1/me").headers["cache-control"] == "no-store"


def test_request_size_limit(user_client):
    aid = create_analysis(user_client).json()["analysis_id"]
    r = user_client.post("/api/v1/analyses", content=b"x" * 70_000, headers={**O, "Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    r = user_client.post(f"/api/v1/analyses/{aid}/chat", json={"message": "x" * 2001}, headers=O)
    assert r.status_code == 422


def test_error_envelope_never_leaks_internals(user_client):
    r = user_client.post("/api/v1/analyses", json={"url": 123}, headers=O)
    assert r.status_code == 422 and set(r.json()["error"]) == {"code", "message", "request_id", "retryable"}
    r = user_client.post("/api/v1/analyses", json={"url": "https://github.com/a/b", "extra": 1}, headers=O)
    assert r.status_code == 422
    r = user_client.get("/api/v1/analyses/not-a-uuid")
    assert r.status_code == 422 and "Traceback" not in r.text
    assert user_client.get("/nope").status_code == 404


def test_analysis_submission_rate_limit(user_client, gh_fake):
    from app.core.config import get_settings
    n = get_settings().analyses_per_hour
    codes = []
    for i in range(n + 2):
        codes.append(create_analysis(user_client, f"https://github.com/owner/repo{i}").status_code)
    assert codes[:n] == [202] * n and codes[n] == 429


def test_internal_requires_service_secret(client):
    aid = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/internal/v1/analysis-jobs/{aid}/status").status_code == 401
    assert client.get(f"/internal/v1/analysis-jobs/{aid}/status", headers={"X-Internal-Secret": "wrong"}).status_code == 401
    assert client.get(f"/internal/v1/analysis-jobs/{aid}/status", headers={**INTERNAL, "Origin": "http://testserver"}).status_code == 403
    assert client.get(f"/internal/v1/analysis-jobs/{aid}/status", headers=INTERNAL).status_code == 404


def test_session_cookie_cannot_call_internal(user_client):
    r = user_client.get("/internal/v1/analysis-jobs/00000000-0000-0000-0000-000000000000/status")
    assert r.status_code == 401


def test_status_endpoint_never_exposes_secrets(user_client):
    body = user_client.get("/api/v1/status").json()
    blob = str(body)
    assert body["llm"]["configured"] is False and "api_key" not in blob.lower() and "secret" not in blob.lower()


def test_health_endpoints(client):
    assert client.get("/health/live").status_code == 200
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"database": True, "migrations": True}


def test_react_app_is_served_at_root_with_legacy_ui_kept(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app
    (tmp_path / "static").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "static" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(get_settings(), "web_dist_dir", str(tmp_path))
    with TestClient(create_app(), base_url="http://testserver") as c:
        assert c.get("/").text == "<div id=root></div>" and c.get("/static/app.js").status_code == 200
        legacy = c.get("/legacy")
        assert legacy.status_code == 200 and "Raven" in legacy.text and c.get("/js/app.js").status_code == 200
        assert c.get("/").headers["content-security-policy"].count("script-src 'self'") == 1  # strict CSP applies to the React app too
