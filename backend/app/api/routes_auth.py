from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.deps import CSRF_COOKIE, SESSION_COOKIE, CurrentAuth, CurrentUser, DB, check_origin
from app.core.config import get_settings
from app.core.errors import ApiError
from app.models import User, utcnow
from app.schemas.api import CodeBody, DisableMfaBody, EmailBody, LoginBody, MfaLoginBody, RegisterBody, ResetPasswordBody, TokenBody
from app.services import accounts
from app.services.jobs import audit
from app.services.security import (
    create_session, csrf_token_for, hash_password, normalize_email, rate_limit, revoke_session, validate_password, verify_password,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _user_dict(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "display_name": u.display_name, "created_at": u.created_at.isoformat(),
            "email_verified": u.email_verified_at is not None, "role": u.role, "totp_enabled": bool(u.totp_enabled)}


def _set_cookies(response: Response, raw: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, raw, max_age=max_age, httponly=True, secure=bool(s.cookie_secure), samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf_token_for(raw), max_age=max_age, httponly=False, secure=bool(s.cookie_secure), samesite="lax", path="/")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, db: DB) -> dict:
    s = get_settings()
    check_origin(request)
    if not s.allow_registration:
        raise ApiError("REGISTRATION_DISABLED")
    rate_limit(db, "register", _client_ip(request), 20, 3600)
    email = normalize_email(body.email)
    validate_password(body.password)
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        db.commit()  # keep the rate-limit event
        raise ApiError("EMAIL_TAKEN")
    user = User(email=email, password_hash=hash_password(body.password), display_name=(body.display_name or None))
    db.add(user)
    db.flush()
    audit(db, "auth.register", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id)
    if s.require_email_verification or s.smtp_host:
        accounts.send_verification_email(db, user)
    if s.require_email_verification:  # no session until the address is confirmed
        db.commit()
        return {"user": _user_dict(user), "verification_required": True}
    raw, _ = create_session(db, user)
    db.commit()
    _set_cookies(response, raw)
    return {"user": _user_dict(user)}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, db: DB) -> dict:
    s = get_settings()
    check_origin(request)
    email = body.email.strip().lower()[:320]
    ip = _client_ip(request)
    rate_limit(db, "login", f"{ip}:{email}", s.login_max_attempts, s.login_window_seconds)
    rate_limit(db, "login_ip", ip, s.login_max_attempts * 5, s.login_window_seconds)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None:
        db.commit()  # persist the failed-attempt counter
        raise ApiError("INVALID_CREDENTIALS")
    if user.disabled_at is not None:
        db.commit()
        raise ApiError("ACCOUNT_DISABLED")
    if s.require_email_verification and user.email_verified_at is None:
        db.commit()
        raise ApiError("EMAIL_NOT_VERIFIED")
    if user.totp_enabled:  # password was right; the session is issued only after the second factor
        mfa = accounts.issue_token(db, user, "mfa", accounts.MFA_TTL_MINUTES)
        db.commit()
        return {"mfa_required": True, "mfa_token": mfa}
    raw, _ = create_session(db, user)
    audit(db, "auth.login", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id)
    db.commit()
    _set_cookies(response, raw)
    return {"user": _user_dict(user)}


def _fail(db: DB, code: str) -> None:
    db.commit()  # persist rate-limit counters
    raise ApiError(code)


@router.post("/auth/login/2fa")
def login_2fa(body: MfaLoginBody, request: Request, response: Response, db: DB) -> dict:
    check_origin(request)
    ip = _client_ip(request)
    rate_limit(db, "mfa_ip", ip, 30, 900)
    rate_limit(db, "mfa_token", accounts._digest(body.mfa_token), 5, 900)
    row = accounts.peek_token(db, "mfa", body.mfa_token)
    user = db.get(User, row.user_id) if row else None
    if user is None:
        _fail(db, "TOKEN_INVALID")
    code = body.code.strip()
    ok = accounts.check_totp(user, code) if len(code.replace(" ", "")) == 6 else accounts.use_recovery_code(db, user, code)
    if not ok:
        _fail(db, "MFA_CODE_INVALID")
    row.used_at = utcnow()
    raw, _ = create_session(db, user)
    audit(db, "auth.login", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id, mfa=True)
    db.commit()
    _set_cookies(response, raw)
    return {"user": _user_dict(user)}


@router.post("/auth/verify-email")
def verify_email(body: TokenBody, request: Request, db: DB) -> dict:
    check_origin(request)
    rate_limit(db, "verify_email", _client_ip(request), 30, 3600)
    user = accounts.consume_token(db, "verify_email", body.token)
    if user is None:
        _fail(db, "TOKEN_INVALID")
    user.email_verified_at = user.email_verified_at or utcnow()
    audit(db, "auth.verify_email", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


@router.post("/auth/resend-verification")
def resend_verification(body: EmailBody, request: Request, db: DB) -> dict:
    """Always answers the same way so it cannot be used to find out which emails have accounts."""
    check_origin(request)
    email = body.email.strip().lower()[:320]
    rate_limit(db, "resend_ip", _client_ip(request), 10, 3600)
    rate_limit(db, "resend_email", email, 3, 3600)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None and user.email_verified_at is None:
        accounts.send_verification_email(db, user)
    db.commit()
    return {"ok": True}


@router.post("/auth/forgot-password")
def forgot_password(body: EmailBody, request: Request, db: DB) -> dict:
    check_origin(request)
    email = body.email.strip().lower()[:320]
    rate_limit(db, "forgot_ip", _client_ip(request), 10, 3600)
    rate_limit(db, "forgot_email", email, 3, 3600)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None:
        accounts.send_reset_email(db, user)
        audit(db, "auth.forgot_password", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


@router.post("/auth/reset-password")
def reset_password(body: ResetPasswordBody, request: Request, db: DB) -> dict:
    check_origin(request)
    rate_limit(db, "reset_ip", _client_ip(request), 20, 3600)
    validate_password(body.password)
    user = accounts.consume_token(db, "reset_password", body.token)
    if user is None:
        _fail(db, "TOKEN_INVALID")
    user.password_hash = hash_password(body.password)
    user.email_verified_at = user.email_verified_at or utcnow()  # following the emailed link proves control of the inbox
    accounts.revoke_all_sessions(db, user)
    audit(db, "auth.reset_password", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


@router.post("/auth/2fa/setup")
def mfa_setup(user: CurrentUser, db: DB) -> dict:
    if user.totp_enabled:
        raise ApiError("MFA_STATE")
    user.totp_secret = accounts.new_totp_secret()
    user.totp_last_step = None
    db.commit()
    return {"secret": user.totp_secret, "uri": accounts.provisioning_uri(user.email, user.totp_secret)}


@router.post("/auth/2fa/enable")
def mfa_enable(body: CodeBody, request: Request, user: CurrentUser, db: DB) -> dict:
    rate_limit(db, "mfa_enable", str(user.id), 10, 900)
    if user.totp_enabled or not user.totp_secret:
        raise ApiError("MFA_STATE")
    if not accounts.check_totp(user, body.code):
        _fail(db, "MFA_CODE_INVALID")
    user.totp_enabled = True
    codes = accounts.make_recovery_codes(db, user)
    audit(db, "auth.2fa_enable", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id)
    db.commit()
    return {"recovery_codes": codes}  # shown once; only digests are stored


@router.post("/auth/2fa/disable")
def mfa_disable(body: DisableMfaBody, request: Request, user: CurrentUser, db: DB) -> dict:
    rate_limit(db, "mfa_disable", str(user.id), 10, 900)
    if not user.totp_enabled:
        raise ApiError("MFA_STATE")
    code = body.code.strip()
    ok = verify_password(user.password_hash, body.password) and (accounts.check_totp(user, code) if len(code.replace(" ", "")) == 6 else accounts.use_recovery_code(db, user, code))
    if not ok:
        _fail(db, "MFA_CODE_INVALID")
    user.totp_enabled, user.totp_secret, user.totp_last_step = False, None, None
    audit(db, "auth.2fa_disable", actor=user, resource_type="user", resource_id=user.id, request_id=request.state.request_id)
    db.commit()
    return {"ok": True}


@router.post("/auth/logout")
def logout(auth: CurrentAuth, response: Response, db: DB) -> dict:
    revoke_session(db, auth.session_token)
    audit(db, "auth.logout", actor=auth.user, resource_type="user", resource_id=auth.user.id)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"user": _user_dict(user)}
