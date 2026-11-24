"""Per-user daily quotas (UTC day) and per-endpoint rate limits. Usage is derived from the tables that already record it,
so there is no second counter to drift: analyses from analysis_jobs, questions and LLM tokens from chat_messages."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.models import AnalysisJob, ChatMessage, User
from app.services.security import rate_limit


def day_start(now: datetime | None = None) -> datetime:
    n = now or datetime.now(timezone.utc)
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def cost_usd(tokens_in: int, tokens_out: int, s: Settings) -> float | None:
    if s.llm_price_input_per_mtok is None or s.llm_price_output_per_mtok is None:
        return None
    return round(tokens_in / 1e6 * s.llm_price_input_per_mtok + tokens_out / 1e6 * s.llm_price_output_per_mtok, 6)


def limits_for(user: User, s: Settings) -> dict:
    return {"analyses": user.quota_analyses_day if user.quota_analyses_day is not None else s.daily_analyses,
            "questions": user.quota_questions_day if user.quota_questions_day is not None else s.daily_questions,
            "tokens": user.quota_tokens_day if user.quota_tokens_day is not None else s.daily_llm_tokens,
            "spend_usd": s.daily_spend_usd}


def usage_today(db: Session, user_id, s: Settings | None = None, since: datetime | None = None) -> dict:
    s = s or get_settings()
    t0 = since or day_start()
    analyses = db.execute(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.owner_id == user_id, AnalysisJob.created_at >= t0)).scalar_one()
    q, ti, to = db.execute(select(
        func.count().filter(ChatMessage.role == "user"),
        func.coalesce(func.sum(ChatMessage.input_tokens), 0), func.coalesce(func.sum(ChatMessage.output_tokens), 0),
    ).where(ChatMessage.owner_id == user_id, ChatMessage.created_at >= t0)).one()
    return {"analyses": int(analyses), "questions": int(q), "tokens": int(ti) + int(to), "input_tokens": int(ti), "output_tokens": int(to), "spend_usd": cost_usd(int(ti), int(to), s)}


def enforce(db: Session, user: User, kind: str, s: Settings | None = None) -> None:
    """Raise QUOTA_EXCEEDED when today's usage has reached the user's limit for `kind` ('analysis' | 'question')."""
    s = s or get_settings()
    lim, use = limits_for(user, s), usage_today(db, user.id, s)
    if kind == "analysis" and use["analyses"] >= lim["analyses"]:
        raise ApiError("QUOTA_EXCEEDED", f"Daily limit of {lim['analyses']} analyses reached. It resets at 00:00 UTC.")
    if kind == "question":
        if use["questions"] >= lim["questions"]:
            raise ApiError("QUOTA_EXCEEDED", f"Daily limit of {lim['questions']} questions reached. It resets at 00:00 UTC.")
        if use["tokens"] >= lim["tokens"]:
            raise ApiError("QUOTA_EXCEEDED", "Daily AI token budget reached. It resets at 00:00 UTC.")
        if lim["spend_usd"] is not None and use["spend_usd"] is not None and use["spend_usd"] >= lim["spend_usd"]:
            raise ApiError("QUOTA_EXCEEDED", "Daily AI spend cap reached. It resets at 00:00 UTC.")


# ---- per-endpoint rate limits: reads use a cheap in-process sliding window, writes the shared PostgreSQL limiter
_hits: dict[str, deque] = defaultdict(deque)
_lock = Lock()


def _read_limit(key: str, limit: int) -> None:
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= limit:
            raise ApiError("RATE_LIMITED", headers={"Retry-After": str(max(1, int(60 - (now - q[0]))))})
        q.append(now)
        if len(_hits) > 20000:  # bound memory
            for k in [k for k, v in _hits.items() if not v or v[-1] < now - 60][:5000]:
                _hits.pop(k, None)


def endpoint_limit(db: Session, user: User, method: str, route: str, s: Settings) -> None:
    key = f"{user.id}:{method}:{route}"
    if method in ("GET", "HEAD"):
        _read_limit(key, s.rl_read_per_minute)
    else:
        rate_limit(db, "endpoint", key[:200], s.rl_write_per_minute, 60)
        db.commit()  # persist the counter even though the handler may not commit


def reset_for_tests() -> None:
    _hits.clear()
