"""Optional LLM-as-judge via DeepEval. Used only for what deterministic checks cannot decide:
semantic correctness against the reference answer, faithfulness of the answer to the retrieved evidence, and answer relevancy.

DeepEval is an evaluation-only dependency (requirements-eval.txt). If it, or the judge's API key, is missing the judge is
reported as `skipped` with the exact reason; no score is produced or imputed.
"""
from __future__ import annotations

import concurrent.futures
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from evals.usage import RateLimiter, load_pricing

KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
DEFAULT_MODEL = {"anthropic": "claude-opus-5-5"}  # openai has no default: name the model explicitly
CORRECTNESS_CRITERIA = (
    "Determine whether the actual output is factually consistent with the expected output for the given question about a code base. "
    "Penalise contradictions and missing key facts from the expected output. Do not penalise additional correct detail or different wording."
)


@dataclass
class JudgeConfig:
    provider: str = "none"  # none | anthropic | openai
    model: str | None = None
    timeout_s: float = 120.0
    max_retries: int = 2
    per_minute: float | None = 20.0
    threshold: float = 0.5


@dataclass
class JudgeStatus:
    state: str  # not_requested | ready | skipped
    reason: str | None = None
    provider: str | None = None
    model: str | None = None
    deepeval_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def judge_from_env(env: Mapping[str, str] = os.environ) -> JudgeConfig:
    def num(name: str, default: float | None) -> float | None:
        v = env.get(name)
        return float(v) if v not in (None, "") else default
    return JudgeConfig(provider=(env.get("EVAL_JUDGE_PROVIDER") or "none").lower(), model=env.get("EVAL_JUDGE_MODEL") or None,
                       timeout_s=num("EVAL_JUDGE_TIMEOUT_S", 120.0) or 120.0, max_retries=int(num("EVAL_JUDGE_MAX_RETRIES", 2) or 0),
                       per_minute=num("EVAL_JUDGE_PER_MINUTE", 20.0), threshold=num("EVAL_JUDGE_THRESHOLD", 0.5) or 0.5)


def api_key_for(provider: str, env: Mapping[str, str] = os.environ) -> tuple[str | None, str]:
    """The judge key comes from EVAL_JUDGE_API_KEY, else the provider's standard variable. Never from code or files."""
    if env.get("EVAL_JUDGE_API_KEY"):
        return env["EVAL_JUDGE_API_KEY"], "EVAL_JUDGE_API_KEY"
    name = KEY_ENV.get(provider, "")
    return (env.get(name) or None), name


def resolve(cfg: JudgeConfig, env: Mapping[str, str] = os.environ, importer: Callable[[], Any] | None = None) -> tuple[JudgeStatus, Any]:
    """Check everything the judge needs. Returns (status, deepeval judge model or None)."""
    if cfg.provider in ("", "none"):
        return JudgeStatus("not_requested", "EVAL_JUDGE_PROVIDER is not set (deterministic metrics only)"), None
    if cfg.provider not in KEY_ENV:
        return JudgeStatus("skipped", f"unsupported EVAL_JUDGE_PROVIDER={cfg.provider!r}; use one of {sorted(KEY_ENV)}", cfg.provider), None
    model = cfg.model or DEFAULT_MODEL.get(cfg.provider)
    if not model:
        return JudgeStatus("skipped", f"EVAL_JUDGE_MODEL is required for provider {cfg.provider}", cfg.provider), None
    try:
        dm = (importer or _import_deepeval)()
    except ImportError as exc:
        return JudgeStatus("skipped", f"deepeval is not installed ({exc.name or exc}); install backend/requirements-eval.txt in a separate virtualenv", cfg.provider, model), None
    key, key_name = api_key_for(cfg.provider, env)
    if not key:
        return JudgeStatus("skipped", f"missing credentials: set {key_name} or EVAL_JUDGE_API_KEY for the {cfg.provider} judge", cfg.provider, model, dm["version"]), None
    rate = (load_pricing().get("models") or {}).get(model, {})
    cost_kw = {"cost_per_input_token": rate["input_per_mtok"] / 1e6, "cost_per_output_token": rate["output_per_mtok"] / 1e6} if rate else {}
    # temperature is deliberately not set: current Claude models reject sampling parameters, and DeepEval only sends it when given.
    llm = dm["AnthropicModel"](model=model, api_key=key, **cost_kw) if cfg.provider == "anthropic" else dm["OpenAIModel"](model=model, api_key=key, **cost_kw)
    return JudgeStatus("ready", None, cfg.provider, model, dm["version"]), llm


def _import_deepeval() -> dict[str, Any]:
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")  # no telemetry from evaluation runs
    import deepeval
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
    from deepeval.models import AnthropicModel, OpenAIModel
    from deepeval.test_case import LLMTestCase
    try:
        from deepeval.test_case import SingleTurnParams as Params
    except ImportError:  # older DeepEval
        from deepeval.test_case import LLMTestCaseParams as Params
    return {"version": getattr(deepeval, "__version__", "unknown"), "GEval": GEval, "FaithfulnessMetric": FaithfulnessMetric, "AnswerRelevancyMetric": AnswerRelevancyMetric,
            "AnthropicModel": AnthropicModel, "OpenAIModel": OpenAIModel, "LLMTestCase": LLMTestCase, "Params": Params}


def deepeval_metrics(dm: dict[str, Any], llm: Any, threshold: float) -> dict[str, Callable[[], Any]]:
    P = dm["Params"]
    return {
        "correctness": lambda: dm["GEval"](name="Correctness", criteria=CORRECTNESS_CRITERIA, evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT, P.EXPECTED_OUTPUT],
                                           model=llm, threshold=threshold, async_mode=False),
        "faithfulness": lambda: dm["FaithfulnessMetric"](model=llm, threshold=threshold, async_mode=False, include_reason=True),
        "answer_relevancy": lambda: dm["AnswerRelevancyMetric"](model=llm, threshold=threshold, async_mode=False, include_reason=True),
    }


class Judge:
    """Runs each judge metric with a timeout, bounded retries and a rate limit. Metric objects are created per measurement."""

    def __init__(self, cfg: JudgeConfig, metrics: Mapping[str, Callable[[], Any]], make_case: Callable[..., Any], sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.metrics, self.make_case, self.sleep = cfg, metrics, make_case, sleep
        self.limiter = RateLimiter(cfg.per_minute)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def evaluate(self, question: str, answer: str, expected: str, retrieval_context: list[str]) -> dict[str, Any]:
        case = self.make_case(input=question, actual_output=answer, expected_output=expected, retrieval_context=retrieval_context or ["(no evidence retrieved)"])
        return {name: self._run(name, factory, case) for name, factory in self.metrics.items()}

    def _run(self, name: str, factory: Callable[[], Any], case: Any) -> dict[str, Any]:
        last = "unknown error"
        for attempt in range(self.cfg.max_retries + 1):
            self.limiter.wait()
            metric = factory()
            t0 = time.perf_counter()
            fut = self.pool.submit(metric.measure, case)
            try:
                fut.result(timeout=self.cfg.timeout_s)
                score = getattr(metric, "score", None)
                return {"score": None if score is None else round(float(score), 4), "passed": None if score is None else float(score) >= self.cfg.threshold,
                        "reason": (getattr(metric, "reason", None) or "")[:500], "latency_s": round(time.perf_counter() - t0, 3),
                        "judge_cost_usd": getattr(metric, "evaluation_cost", None), "attempts": attempt + 1, "error": None}
            except concurrent.futures.TimeoutError:
                last = f"timeout after {self.cfg.timeout_s}s"  # the worker thread cannot be killed; it finishes in the background
            except Exception as exc:  # noqa: BLE001  judge failures are recorded, never raised into the run
                last = f"{type(exc).__name__}: {str(exc)[:200]}"
            if attempt < self.cfg.max_retries:
                self.sleep(min(30.0, 2.0 * (2 ** attempt)))
        return {"score": None, "passed": None, "reason": None, "latency_s": None, "judge_cost_usd": None, "attempts": self.cfg.max_retries + 1, "error": last}

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def build_judge(cfg: JudgeConfig, env: Mapping[str, str] = os.environ) -> tuple[JudgeStatus, Judge | None]:
    status, llm = resolve(cfg, env)
    if status.state != "ready":
        return status, None
    dm = _import_deepeval()
    return status, Judge(cfg, deepeval_metrics(dm, llm, cfg.threshold), dm["LLMTestCase"])
