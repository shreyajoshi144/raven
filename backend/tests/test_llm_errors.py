"""OpenAI-style error taxonomy: quota vs rate limit vs auth vs 5xx; bounded, jittered retries; token budget."""
import httpx
import pytest

from app.core.errors import JobError
from app.services.llm import FallbackProvider, LLMBudget, LLMResult, OpenAICompatProvider
from tests.test_llm_fallback import OK, settings


def provider(handler, **kw):
    sleeps = []
    p = OpenAICompatProvider(settings(llm_base_url="http://x.invalid", llm_max_retries=kw.pop("retries", 2), **kw),
                             transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return p, sleeps


def body(code):
    return {"error": {"code": code, "type": code, "message": "m"}}


def test_quota_429_is_not_retried():
    calls = []
    p, sleeps = provider(lambda r: calls.append(1) or httpx.Response(429, json=body("insufficient_quota")))
    with pytest.raises(JobError) as e:
        p.complete("s", "u", 10)
    assert e.value.code == "LLM_QUOTA_EXHAUSTED" and len(calls) == 1 and not sleeps


def test_rate_limit_429_retries_with_retry_after_then_succeeds():
    seq = [httpx.Response(429, json=body("rate_limit_exceeded"), headers={"retry-after": "3"}),
           httpx.Response(200, json={"choices": [{"message": {"content": OK}}], "usage": {}})]
    p, sleeps = provider(lambda r: seq.pop(0))
    assert p.complete("s", "u", 10).text == OK
    assert len(sleeps) == 1 and sleeps[0] >= 3


def test_long_retry_after_fails_fast():
    calls = []
    p, sleeps = provider(lambda r: calls.append(1) or httpx.Response(429, json=body("rate_limit_exceeded"), headers={"retry-after": "600"}))
    with pytest.raises(JobError) as e:
        p.complete("s", "u", 10)
    assert e.value.code == "LLM_RATE_LIMITED" and len(calls) == 1 and not sleeps


def test_auth_never_retried_and_5xx_bounded():
    calls = []
    p, _ = provider(lambda r: calls.append(1) or httpx.Response(401, json={}))
    with pytest.raises(JobError) as e:
        p.complete("s", "u", 10)
    assert e.value.code == "LLM_AUTH_FAILED" and len(calls) == 1
    calls.clear()
    p, sleeps = provider(lambda r: calls.append(1) or httpx.Response(503, json={}), retries=2)
    with pytest.raises(JobError) as e:
        p.complete("s", "u", 10)
    assert e.value.code == "LLM_PROVIDER_UNAVAILABLE" and len(calls) == 3 and len(sleeps) == 2


def test_quota_triggers_fallback_and_token_budget_caps():
    class Dead:
        def complete(self, *a):
            raise JobError("LLM_QUOTA_EXHAUSTED")

    class Ok:
        def complete(self, *a):
            return LLMResult(OK, 1, 1, "fb")
    assert FallbackProvider(Dead(), Ok()).complete("s", "u", 5).model == "fb"
    b = LLMBudget(max_calls=9, max_tokens=10, input_tokens=8, output_tokens=2)
    with pytest.raises(JobError):
        b.spend()
