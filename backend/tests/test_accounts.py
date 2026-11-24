"""Email verification, password reset and TOTP two-factor."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import session_scope
from app.models import AuthToken, User, utcnow
from app.services import accounts
from app.services.mailer import OUTBOX

H = {"Origin": "http://testserver"}
EMAIL, PW = "new@example.com", "correct-horse-battery"


@pytest.fixture(autouse=True)
def _outbox():
    OUTBOX.clear()
    yield
    OUTBOX.clear()


@pytest.fixture()
def verify_required(monkeypatch):
    monkeypatch.setattr(get_settings(), "require_email_verification", True)


def post(c, path, **body):
    return c.post(f"/api/v1{path}", json=body, headers=H)


def token_from_outbox(kind_path):
    link = re.search(rf"{kind_path}\?token=([\w-]+)", OUTBOX[-1]["body"])
    assert link, OUTBOX[-1]
    return link.group(1)


def login_ok(c, email=EMAIL, pw=PW):
    r = post(c, "/auth/login", email=email, password=pw)
    return r


# ------------------------------------------------------------------ email verification
def test_register_requires_verification_before_any_session(client, verify_required):
    r = post(client, "/auth/register", email=EMAIL, password=PW)
    assert r.status_code == 201 and r.json()["verification_required"] is True and r.json()["user"]["email_verified"] is False
    assert "raven_session" not in client.cookies and client.get("/api/v1/me").status_code == 401
    assert login_ok(client).status_code == 403 and login_ok(client).json()["error"]["code"] == "EMAIL_NOT_VERIFIED"
    assert len(OUTBOX) == 1 and OUTBOX[0]["to"] == EMAIL
    token = token_from_outbox("verify-email")
    assert post(client, "/auth/verify-email", token=token).status_code == 200
    assert post(client, "/auth/verify-email", token=token).json()["error"]["code"] == "TOKEN_INVALID"  # single use
    assert login_ok(client).status_code == 200 and login_ok(client).json()["user"]["email_verified"] is True


def test_invalid_and_expired_verification_tokens_are_rejected(client, verify_required):
    post(client, "/auth/register", email=EMAIL, password=PW)
    assert post(client, "/auth/verify-email", token="x" * 30).json()["error"]["code"] == "TOKEN_INVALID"
    token = token_from_outbox("verify-email")
    with session_scope() as db:
        db.execute(update(AuthToken).values(expires_at=utcnow() - timedelta(minutes=1)))
    assert post(client, "/auth/verify-email", token=token).status_code == 400


def test_resend_never_reveals_whether_an_account_exists(client, verify_required):
    post(client, "/auth/register", email=EMAIL, password=PW)
    OUTBOX.clear()
    a = post(client, "/auth/resend-verification", email=EMAIL)
    b = post(client, "/auth/resend-verification", email="nobody@example.com")
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert [m["to"] for m in OUTBOX] == [EMAIL]
    old = token_from_outbox("verify-email")
    post(client, "/auth/resend-verification", email=EMAIL)  # a newer link invalidates the older one
    assert post(client, "/auth/verify-email", token=old).status_code == 400


def test_resend_is_rate_limited(client, verify_required):
    post(client, "/auth/register", email=EMAIL, password=PW)
    codes = [post(client, "/auth/resend-verification", email=EMAIL).status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[3] == 429


def test_without_the_requirement_registration_still_logs_in_immediately(client):
    r = post(client, "/auth/register", email=EMAIL, password=PW)
    assert r.status_code == 201 and "verification_required" not in r.json() and client.get("/api/v1/me").status_code == 200 and OUTBOX == []


# ------------------------------------------------------------------ password reset
def test_password_reset_flow(client, app):
    post(client, "/auth/register", email=EMAIL, password=PW)
    old_cookie = client.cookies.get("raven_session")
    OUTBOX.clear()
    a, b = post(client, "/auth/forgot-password", email=EMAIL), post(client, "/auth/forgot-password", email="ghost@example.com")
    assert a.status_code == b.status_code == 200 and a.json() == b.json() and [m["to"] for m in OUTBOX] == [EMAIL]
    token = token_from_outbox("reset-password")
    weak = post(client, "/auth/reset-password", token=token, password="short")
    assert weak.status_code == 422  # a weak password does not burn the token
    assert post(client, "/auth/reset-password", token=token, password="a-brand-new-passphrase").status_code == 200
    assert post(client, "/auth/reset-password", token=token, password="another-passphrase-1").json()["error"]["code"] == "TOKEN_INVALID"
    client.cookies.set("raven_session", old_cookie)
    assert client.get("/api/v1/me").status_code == 401  # existing sessions were revoked
    client.cookies.clear()
    assert login_ok(client, pw=PW).status_code == 401 and login_ok(client, pw="a-brand-new-passphrase").status_code == 200


def test_reset_tokens_expire_and_cannot_be_used_as_verification_tokens(client, verify_required):
    post(client, "/auth/register", email=EMAIL, password=PW)
    post(client, "/auth/forgot-password", email=EMAIL)
    token = token_from_outbox("reset-password")
    assert post(client, "/auth/verify-email", token=token).status_code == 400  # wrong kind
    with session_scope() as db:
        db.execute(update(AuthToken).where(AuthToken.kind == "reset_password").values(expires_at=utcnow() - timedelta(seconds=1)))
    assert post(client, "/auth/reset-password", token=token, password="a-brand-new-passphrase").status_code == 400


def test_only_digests_are_stored(client, verify_required):
    post(client, "/auth/register", email=EMAIL, password=PW)
    token = token_from_outbox("verify-email")
    with session_scope() as db:
        assert token not in {t.token_hash for t in db.execute(select(AuthToken)).scalars()}


# ------------------------------------------------------------------ TOTP
def test_totp_matches_the_rfc_6238_vector_and_window():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"
    assert accounts.totp_match(secret, "287082", now=59) == 1  # RFC 6238 appendix B (94287082, last 6 digits)
    assert accounts.totp_match(secret, "287082", now=59 + 30) == 1 and accounts.totp_match(secret, "287082", now=59 + 90) is None
    assert accounts.totp_match(secret, "12345", now=59) is None and accounts.totp_match(secret, "abcdef", now=59) is None


def _enable_2fa(client):
    s = post(client, "/auth/2fa/setup").json()
    step = int(__import__("time").time() // 30)
    r = post(client, "/auth/2fa/enable", code=accounts._code(s["secret"], step))
    assert r.status_code == 200, r.text
    return s["secret"], step, r.json()["recovery_codes"]


@pytest.fixture()
def authed(user_client):
    return user_client


def test_two_factor_login_flow(authed):
    c = authed
    uri = post(c, "/auth/2fa/setup").json()["uri"]
    assert uri.startswith("otpauth://totp/Raven:") and "secret=" in uri
    secret, step, recovery = _enable_2fa(c)
    assert len(recovery) == 8 and c.get("/api/v1/me").json()["user"]["totp_enabled"] is True
    c.post("/api/v1/auth/logout", headers={**H, "X-CSRF-Token": c.headers["X-CSRF-Token"]})
    c.cookies.clear()
    r = login_ok(c, "dev@example.com")
    assert r.json()["mfa_required"] is True and "raven_session" not in c.cookies
    mfa = r.json()["mfa_token"]
    assert post(c, "/auth/login/2fa", mfa_token=mfa, code="000000").json()["error"]["code"] == "MFA_CODE_INVALID"
    assert post(c, "/auth/login/2fa", mfa_token=mfa, code=accounts._code(secret, step)).status_code == 401  # same step as enabling: replay
    ok = post(c, "/auth/login/2fa", mfa_token=mfa, code=accounts._code(secret, step + 1))
    assert ok.status_code == 200 and c.get("/api/v1/me").status_code == 200
    assert post(c, "/auth/login/2fa", mfa_token=mfa, code=accounts._code(secret, step + 1)).json()["error"]["code"] == "TOKEN_INVALID"  # token is single use


def test_recovery_codes_work_once_and_mfa_attempts_are_limited(authed):
    c = authed
    _, _, recovery = _enable_2fa(c)
    c.cookies.clear()
    mfa = login_ok(c, "dev@example.com").json()["mfa_token"]
    assert post(c, "/auth/login/2fa", mfa_token=mfa, code=recovery[0]).status_code == 200
    c.cookies.clear()
    mfa2 = login_ok(c, "dev@example.com").json()["mfa_token"]
    assert post(c, "/auth/login/2fa", mfa_token=mfa2, code=recovery[0]).status_code == 401  # used
    for _ in range(4):
        post(c, "/auth/login/2fa", mfa_token=mfa2, code="111111")
    assert post(c, "/auth/login/2fa", mfa_token=mfa2, code="222222").status_code == 429


def test_disable_requires_password_and_a_code(authed):
    c = authed
    secret, step, _ = _enable_2fa(c)
    assert post(c, "/auth/2fa/disable", password="wrong-password-1", code=accounts._code(secret, step + 1)).status_code == 401
    assert post(c, "/auth/2fa/disable", password="correct-horse-battery", code=accounts._code(secret, step + 1)).status_code == 200
    assert c.get("/api/v1/me").json()["user"]["totp_enabled"] is False and post(c, "/auth/2fa/setup").status_code == 200


def test_2fa_state_checks_and_authentication(authed, app):
    c = authed
    assert post(c, "/auth/2fa/enable", code="123456").json()["error"]["code"] == "MFA_STATE"  # no setup yet
    _enable_2fa(c)
    assert post(c, "/auth/2fa/setup").json()["error"]["code"] == "MFA_STATE"  # already enabled
    from fastapi.testclient import TestClient
    anon = TestClient(app, base_url="http://testserver")
    assert post(anon, "/auth/2fa/setup").status_code == 401


def test_secrets_are_not_returned_by_me(authed):
    _enable_2fa(authed)
    assert "totp_secret" not in authed.get("/api/v1/me").text and "password" not in authed.get("/api/v1/me").text


def test_user_model_columns_exist():
    with session_scope() as db:
        assert db.execute(select(User)).scalars().first() is None
