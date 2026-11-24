from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.errors import ApiError
from app.models import AnalysisJob, User
from app.services.github import GitHubClient
from app.services.jobs import get_owned_job
from app.services.orchestrator import Orchestrator
from app.services.security import constant_time_equals, csrf_token_for, lookup_session

SESSION_COOKIE = "raven_session"
CSRF_COOKIE = "raven_csrf"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Auth:
    user: User
    session_token: str


def settings_dep() -> Settings:
    return get_settings()


def github_dep() -> GitHubClient:  # overridden in tests
    return GitHubClient()


def orchestrator_dep() -> Orchestrator:  # overridden in tests
    return Orchestrator()


DB = Annotated[Session, Depends(get_db)]


def check_origin(request: Request) -> None:
    """Reject cross-origin browser mutations (defense in depth alongside SameSite cookies and the CSRF token)."""
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("host", "")
        if urlsplit(origin).netloc.lower() != host.lower():
            raise ApiError("CSRF_FAILED")
    elif request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise ApiError("CSRF_FAILED")


def current_auth(request: Request, db: DB) -> Auth:
    raw = request.cookies.get(SESSION_COOKIE)
    found = lookup_session(db, raw)
    if not found:
        raise ApiError("UNAUTHENTICATED")
    user, _ = found
    if user.disabled_at is not None:
        raise ApiError("ACCOUNT_DISABLED")
    if request.method in UNSAFE:
        check_origin(request)
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not constant_time_equals(sent, csrf_token_for(raw or "")):
            raise ApiError("CSRF_FAILED")
    return Auth(user=user, session_token=raw or "")


CurrentAuth = Annotated[Auth, Depends(current_auth)]


def current_user(auth: CurrentAuth) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise ApiError("FORBIDDEN", "Administrator access is required.", status=403)
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def rate_limited(request: Request, user: CurrentUser, db: DB, s: Annotated[Settings, Depends(settings_dep)]) -> None:
    """Router-level per-user, per-route rate limit (reads and writes have separate budgets)."""
    from app.services.quotas import endpoint_limit
    route = request.scope.get("route")
    endpoint_limit(db, user, request.method, getattr(route, "path", request.url.path), s)


def owned_job(analysis_id: uuid.UUID, user: CurrentUser, db: DB) -> AnalysisJob:
    return get_owned_job(db, user, analysis_id)


OwnedJob = Annotated[AnalysisJob, Depends(owned_job)]


def internal_auth(request: Request, s: Annotated[Settings, Depends(settings_dep)]) -> None:
    """Service authentication for n8n -> app calls. Browser sessions and browser-originated requests are refused."""
    if request.headers.get("origin"):
        raise ApiError("FORBIDDEN", "Internal endpoints are not available to browsers.", status=403)
    sent = request.headers.get("x-internal-secret", "")
    if not sent or not constant_time_equals(sent, s.internal_service_secret):
        raise ApiError("UNAUTHENTICATED", "Invalid service credentials.", status=401)
