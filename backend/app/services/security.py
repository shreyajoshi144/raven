from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError
from app.models import RateLimitEvent, User, UserSession, utcnow

_hasher = PasswordHasher()  # Argon2id with library defaults
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
# Verified against when the account does not exist, to keep timing uniform.
_DUMMY_HASH = _hasher.hash("raven-dummy-password")


def normalize_email(email: str) -> str:
    e = email.strip().lower()
    if len(e) > 320 or not _EMAIL_RE.match(e):
        raise ApiError("VALIDATION_ERROR", "Enter a valid email address.")
    return e


def validate_password(pw: str) -> None:
    if len(pw) < 10:
        raise ApiError("VALIDATION_ERROR", "Password must be at least 10 characters.")
    if len(pw) > 200:
        raise ApiError("VALIDATION_ERROR", "Password is too long.")


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(stored: str | None, pw: str) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY_HASH, pw) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, UserSession]:
    s = get_settings()
    raw = secrets.token_urlsafe(32)
    sess = UserSession(user_id=user.id, token_hash=_digest(raw), expires_at=utcnow() + timedelta(hours=s.session_ttl_hours))
    db.add(sess)
    db.flush()
    return raw, sess


def lookup_session(db: Session, raw: str | None) -> tuple[User, UserSession] | None:
    if not raw or len(raw) > 100:
        return None
    sess = db.execute(select(UserSession).where(UserSession.token_hash == _digest(raw))).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or sess.expires_at <= utcnow():
        return None
    user = db.get(User, sess.user_id)
    return (user, sess) if user else None


def revoke_session(db: Session, raw: str | None) -> None:
    if not raw:
        return
    sess = db.execute(select(UserSession).where(UserSession.token_hash == _digest(raw))).scalar_one_or_none()
    if sess and sess.revoked_at is None:
        sess.revoked_at = utcnow()


def csrf_token_for(session_token: str) -> str:
    key = get_settings().app_secret_key.encode()
    return hmac.new(key, b"csrf:" + session_token.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def rate_limit(db: Session, bucket: str, key: str, limit: int, window_seconds: int) -> None:
    """Sliding-window limiter stored in PostgreSQL (shared across processes). Raises RATE_LIMITED."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"{bucket}:{key}"})
    cutoff = utcnow() - timedelta(seconds=window_seconds)
    count = db.execute(
        select(func.count()).select_from(RateLimitEvent).where(
            RateLimitEvent.bucket == bucket, RateLimitEvent.key == key, RateLimitEvent.at > cutoff)
    ).scalar_one()
    if count >= limit:
        raise ApiError("RATE_LIMITED", headers={"Retry-After": str(window_seconds)})
    db.add(RateLimitEvent(bucket=bucket, key=key))
    if secrets.randbelow(100) == 0:  # opportunistic cleanup
        db.execute(delete(RateLimitEvent).where(RateLimitEvent.at < utcnow() - timedelta(days=1)))
