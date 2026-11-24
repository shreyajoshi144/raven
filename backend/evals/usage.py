"""LLM usage accounting (tokens, latency, errors, estimated cost) and a simple rate limiter."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import JobError
from app.services.llm import LLMProvider, LLMResult

PRICING_FILE = Path(__file__).resolve().parent / "pricing.json"


@dataclass
class CallRecord:
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@dataclass
class UsageLedger:
    calls: list[CallRecord] = field(default_factory=list)

    def summary(self, model: str | None, pricing: dict[str, Any] | None = None) -> dict[str, Any]:
        ok = [c for c in self.calls if c.error is None]
        tin, tout = sum(c.input_tokens for c in ok), sum(c.output_tokens for c in ok)
        lat = sorted(c.latency_s for c in self.calls)
        return {"calls": len(self.calls), "errors": len(self.calls) - len(ok), "error_codes": sorted({c.error for c in self.calls if c.error}),
                "input_tokens": tin, "output_tokens": tout, "latency_s": latency_stats(lat), **estimate_cost(model, tin, tout, pricing)}


def latency_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "max": None}
    v = sorted(values)
    pick = lambda q: round(v[min(len(v) - 1, max(0, round(q * (len(v) - 1))))], 4)  # noqa: E731  nearest-rank
    return {"n": len(v), "mean": round(sum(v) / len(v), 4), "p50": pick(0.5), "p95": pick(0.95), "max": round(v[-1], 4)}


def load_pricing(path: Path = PRICING_FILE) -> dict[str, Any]:
    return json.loads(path.read_text())


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int, pricing: dict[str, Any] | None = None) -> dict[str, Any]:
    if not input_tokens and not output_tokens:
        return {"estimated_cost_usd": 0.0, "cost_basis": "no tokens used"}
    pricing = pricing or load_pricing()
    rate = (pricing.get("models") or {}).get(model or "")
    if not rate:
        return {"estimated_cost_usd": None, "cost_basis": f"unknown: no price for model {model!r} in pricing.json"}
    cost = input_tokens / 1e6 * rate["input_per_mtok"] + output_tokens / 1e6 * rate["output_per_mtok"]
    return {"estimated_cost_usd": round(cost, 6), "cost_basis": f"{model} list price as of {pricing.get('as_of')} (no caching/batch discounts)"}


class RecordingProvider:
    """Wraps Raven's LLMProvider: records latency, tokens and error codes for every call, then delegates unchanged."""

    def __init__(self, inner: LLMProvider, ledger: UsageLedger, limiter: RateLimiter | None = None):
        self.inner, self.ledger, self.limiter = inner, ledger, limiter

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResult:
        if self.limiter:
            self.limiter.wait()
        t0 = time.perf_counter()
        try:
            res = self.inner.complete(system, user, max_tokens)
        except JobError as exc:
            self.ledger.calls.append(CallRecord(time.perf_counter() - t0, error=exc.code))
            raise
        self.ledger.calls.append(CallRecord(time.perf_counter() - t0, res.input_tokens, res.output_tokens))
        return res


class NoLLM:
    """Provider used in retrieval-only mode: behaves exactly like an unconfigured Raven deployment."""

    def complete(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise JobError("LLM_NOT_CONFIGURED", "evaluation run in retrieval_only mode")


class RateLimiter:
    """At most `per_minute` acquisitions per rolling minute (simple spacing; thread-safe)."""

    def __init__(self, per_minute: float | None, clock=time.monotonic, sleep=time.sleep):
        self.interval = 60.0 / per_minute if per_minute else 0.0
        self.clock, self.sleep = clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> float:
        if not self.interval:
            return 0.0
        with self._lock:
            now = self.clock()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if delay:
            self.sleep(delay)
        return delay
