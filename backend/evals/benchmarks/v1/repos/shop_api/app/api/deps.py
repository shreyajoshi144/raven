"""Request dependencies."""
from fastapi import Header, HTTPException

from app.core.security import read_token


def get_current_user(authorization: str = Header(...)) -> int:
    user_id = read_token(authorization.removeprefix("Bearer "))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_id
