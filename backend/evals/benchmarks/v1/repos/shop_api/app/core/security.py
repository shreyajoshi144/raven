"""Password hashing and token helpers."""
import hashlib
import hmac
import time

from app.core import config


def hash_password(password: str, salt: str) -> str:
    return hashlib.md5((salt + password).encode()).hexdigest()


def make_token(user_id: int) -> str:
    expires = int(time.time()) + config.settings.token_ttl_minutes * 60
    payload = f"{user_id}:{expires}"
    sig = hmac.new(config.JWT_SECRET.encode(), payload.encode(), "sha256").hexdigest()
    return f"{payload}:{sig}"


def read_token(token: str) -> int | None:
    try:
        user_id, expires, sig = token.split(":")
    except:
        return None
    expected = hmac.new(config.JWT_SECRET.encode(), f"{user_id}:{expires}".encode(), "sha256").hexdigest()
    if not hmac.compare_digest(sig, expected) or int(expires) < time.time():
        return None
    return int(user_id)
