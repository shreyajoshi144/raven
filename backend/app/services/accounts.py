"""Email verification, password reset and TOTP two-factor (RFC 6238, SHA-1, 6 digits, 30 s) with stdlib only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta
from urllib.parse import quote

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuthToken, User, UserSession, utcnow
from app.services.mailer import send_email

STEP, DIGITS, WINDOW = 30, 6, 1
MFA_TTL_MINUTES = 5


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ single-use tokens
def issue_token(db: Session, user: User, kind: str, ttl_minutes: int | None, *, replace: bool = True) -> str:
    """Create a random token and store only its digest. Older unused tokens of the same kind are invalidated."""
    if replace:
        db.execute(update(AuthToken).where(AuthToken.user_id == user.id, AuthToken.kind == kind, AuthToken.used_at.is_(None)).values(used_at=utcnow()))
    raw = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user.id, kind=kind, token_hash=_digest(raw), expires_at=(utcnow() + timedelta(minutes=ttl_minutes)) if ttl_minutes else None))
    db.flush()
    return raw


def peek_token(db: Session, kind: str, raw: str) -> AuthToken | None:
    """Look up a valid token without using it (for steps that may be retried, such as the 2FA code)."""
    row = db.execute(select(AuthToken).where(AuthToken.token_hash == _digest(raw or ""), AuthToken.kind == kind)).scalar_one_or_none()
    if row is None or row.used_at is not None or (row.expires_at is not None and row.expires_at < utcnow()):
        return None
    return row


def consume_token(db: Session, kind: str, raw: str) -> User | None:
    """Mark a valid, unexpired, unused token as used and return its user (None if invalid)."""
    row = db.execute(select(AuthToken).where(AuthToken.token_hash == _digest(raw or ""), AuthToken.kind == kind).with_for_update()).scalar_one_or_none()
    if row is None or row.used_at is not None or (row.expires_at is not None and row.expires_at < utcnow()):
        return None
    row.used_at = utcnow()
    return db.get(User, row.user_id)


def revoke_all_sessions(db: Session, user: User) -> None:
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))


# ------------------------------------------------------------------ emails
def send_verification_email(db: Session, user: User) -> None:
    s = get_settings()
    raw = issue_token(db, user, "verify_email", s.email_token_ttl_minutes)
    send_email(user.email, "Verify your Raven email address",
               f"Confirm your email to activate your Raven account:\n\n{s.app_base_url.rstrip('/')}/#/verify-email?token={raw}\n\n"
               f"The link works once and expires in {s.email_token_ttl_minutes} minutes. If you did not create an account, ignore this email.", s)


def send_reset_email(db: Session, user: User) -> None:
    s = get_settings()
    raw = issue_token(db, user, "reset_password", s.email_token_ttl_minutes)
    send_email(user.email, "Reset your Raven password",
               f"Choose a new password:\n\n{s.app_base_url.rstrip('/')}/#/reset-password?token={raw}\n\n"
               f"The link works once and expires in {s.email_token_ttl_minutes} minutes. If you did not ask for this, ignore this email; your password is unchanged.", s)


# ------------------------------------------------------------------ TOTP
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def provisioning_uri(email: str, secret: str) -> str:
    return f"otpauth://totp/Raven:{quote(email)}?secret={secret}&issuer=Raven&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    h = hmac.new(key, struct.pack(">Q", step), "sha1").digest()
    off = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS:0{DIGITS}d}"


def totp_match(secret: str, code: str, now: float | None = None) -> int | None:
    """The matching 30 s step within +-1 step, or None."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    cur = int((now if now is not None else time.time()) // STEP)
    for step in range(cur - WINDOW, cur + WINDOW + 1):
        if hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def check_totp(user: User, code: str, now: float | None = None) -> bool:
    """Verify and record the step so the same code cannot be used twice."""
    if not user.totp_secret:
        return False
    step = totp_match(user.totp_secret, code, now)
    if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
        return False
    user.totp_last_step = step
    return True


def make_recovery_codes(db: Session, user: User, n: int = 8) -> list[str]:
    db.execute(update(AuthToken).where(AuthToken.user_id == user.id, AuthToken.kind == "recovery", AuthToken.used_at.is_(None)).values(used_at=utcnow()))
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]
    for c in codes:
        db.add(AuthToken(user_id=user.id, kind="recovery", token_hash=_digest(c)))
    db.flush()
    return codes


def use_recovery_code(db: Session, user: User, code: str) -> bool:
    row = db.execute(select(AuthToken).where(AuthToken.user_id == user.id, AuthToken.kind == "recovery", AuthToken.token_hash == _digest((code or "").strip().lower()),
                                              AuthToken.used_at.is_(None)).with_for_update()).scalar_one_or_none()
    if row is None:
        return False
    row.used_at = utcnow()
    return True
