"""Second provider, fallback model, and model/prompt versioning."""
import json

import httpx
import pytest

from app.core.config import get_settings
from app.core.errors import JobError
from app.services import qa as qasvc
from app.services.llm import (
    AnthropicProvider, FallbackProvider, LLMBudget, LLMResult, OpenAICompatProvider, StructuredLLM, build_provider, prompt_version,
)
from app.schemas.llm import QAAnswer
from tests.conftest import create_analysis, emulate_n8n
from tests.fakes import FakeLLM
from tests.test_chat import ask, wire

OK = json.dumps({"answer": "x", "citations": [], "evidence_sufficiency": "insufficient", "inferred": [], "limitations": []})


def settings(**kw):
    return get_settings().model_copy(update={"llm_api_key": "k" * 20, "llm_model": "primary-m", "llm_max_retries": 0, **kw})


def anthropic(status, model="primary-m"):
    def h(req):
        return httpx.Response(status, json={"content": [{"type": "text", "text": OK}], "usage": {"input_tokens": 3, "output_tokens": 2}}) if status == 200 else httpx.Response(status, json={})
    return AnthropicProvider(settings(llm_model=model), transport=httpx.MockTransport(h), sleep=lambda _: None)


def openai_compat(model="local-m", status=200):
    def h(req):
        assert req.url.path == "/v1/chat/completions" and json.loads(req.content)["messages"][0]["role"] == "system"
        return httpx.Response(status, json={"choices": [{"message": {"content": OK}}], "usage": {"prompt_tokens": 7, "completion_tokens": 4}})
    return OpenAICompatProvider(settings(llm_model=model, llm_base_url="http://local.invalid", llm_api_key=""), transport=httpx.MockTransport(h), sleep=lambda _: None)


def test_openai_compatible_provider_parses_reply_and_reports_model():
    r = openai_compat().complete("sys", "user", 50)
    assert (r.text, r.input_tokens, r.output_tokens, r.model) == (OK, 7, 4, "local-m")


@pytest.mark.parametrize("status", [503, 429, 401])
def test_availability_errors_fall_back_and_record_the_fallback_model(status):
    p = FallbackProvider(anthropic(status), openai_compat())
    r = p.complete("s", "u", 50)
    assert r.model == "local-m" and p.fallbacks == 1


def test_primary_success_does_not_touch_the_fallback():
    p = FallbackProvider(anthropic(200), openai_compat(status=500))
    assert p.complete("s", "u", 50).model == "primary-m" and p.fallbacks == 0


def test_bad_output_is_not_an_availability_error():
    p = FallbackProvider(anthropic(400), openai_compat())
    with pytest.raises(JobError) as e:
        p.complete("s", "u", 50)
    assert e.value.code == "LLM_MALFORMED_OUTPUT" and p.fallbacks == 0


def test_both_failing_raises_the_fallbacks_error():
    p = FallbackProvider(anthropic(503), openai_compat(status=503))
    with pytest.raises(JobError) as e:
        p.complete("s", "u", 50)
    assert e.value.code == "LLM_PROVIDER_UNAVAILABLE"


def test_structured_llm_tracks_which_model_answered():
    llm = StructuredLLM(FallbackProvider(anthropic(503), openai_compat()), LLMBudget(5), 100)
    llm.structured(QAAnswer, "sys", "user")
    assert llm.model == "local-m"


def test_build_provider_wires_the_fallback_from_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr("app.services.llm.get_settings", lambda: s.model_copy(update={"llm_api_key": "k" * 20, "llm_model": "a", "llm_fallback_provider": "openai_compat",
                                                                                      "llm_fallback_model": "b", "llm_fallback_base_url": "http://x.invalid"}))
    p = build_provider()
    assert isinstance(p, FallbackProvider) and isinstance(p.fallback, OpenAICompatProvider) and p.fallback.s.llm_model == "b"
    monkeypatch.setattr("app.services.llm.get_settings", lambda: s.model_copy(update={"llm_api_key": "k" * 20, "llm_model": "a"}))
    assert isinstance(build_provider(), AnthropicProvider)


def test_prompt_version_is_a_stable_content_hash():
    assert prompt_version("a", "b") == prompt_version("a", "b") != prompt_version("a", "c") and len(prompt_version("x")) == 10
    assert qasvc.PROMPT_VERSION == prompt_version(qasvc.QA_SYSTEM, __import__("app.services.llm", fromlist=["x"]).INJECTION_GUARD)


@pytest.fixture()
def ready(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    return aid


def test_answers_store_model_and_prompt_version(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, FakeLLM(), monkeypatch)
    a = ask(user_client, ready, "What does get_current_user do?").json()["answer"]
    assert a["answer_source"] == "ai" and a["model"] == "m" and a["prompt_version"] == qasvc.PROMPT_VERSION
    assert user_client.get(f"/api/v1/analyses/{ready}/chat").json()["items"][-1]["prompt_version"] == qasvc.PROMPT_VERSION


def test_retrieval_only_answers_have_no_model_or_prompt(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, None, monkeypatch)
    a = ask(user_client, ready, "What does get_current_user do?").json()["answer"]
    assert a["answer_source"] == "retrieval_only" and a["model"] is None and a["prompt_version"] is None
    assert LLMResult("x").model == ""
