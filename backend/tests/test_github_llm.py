import httpx
import pytest

from app.analysis.urls import RepoRef
from app.core.config import get_settings
from app.core.errors import JobError
from app.services.github import GitHubClient
from app.services.llm import AnthropicProvider, LLMBudget, StructuredLLM
from app.schemas.llm import QAAnswer
from tests.fakes import FakeGitHub, FakeLLM

REF = RepoRef("owner", "sample")


def client(fake, **settings):
    s = get_settings()
    return GitHubClient(s, transport=fake.transport())


def test_repo_and_sha_ok():
    f = FakeGitHub()
    c = client(f)
    meta = c.get_repo(REF)
    assert meta.full_name == "owner/sample" and meta.default_branch == "main"
    assert c.get_head_sha("owner", "sample", "main") == f.sha


@pytest.mark.parametrize("status,code,retry", [(404, "REPO_NOT_FOUND", False), (451, "REPO_UNAVAILABLE", False), (503, "GITHUB_UNAVAILABLE", True),
                                                (500, "GITHUB_UNAVAILABLE", True), (401, "REPO_FORBIDDEN", False), (418, "GITHUB_BAD_RESPONSE", False)])
def test_status_classification(status, code, retry):
    f = FakeGitHub(); f.repo_status = status
    with pytest.raises(JobError) as e:
        client(f).get_repo(REF)
    assert e.value.code == code and e.value.retryable is retry


def test_rate_limit_and_private_and_malformed():
    f = FakeGitHub(); f.rate_limit_on_repo = True
    with pytest.raises(JobError) as e:
        client(f).get_repo(REF)
    assert e.value.code == "GITHUB_RATE_LIMITED" and e.value.retryable and e.value.retry_after is not None
    with pytest.raises(JobError) as e:
        client(FakeGitHub(private=True)).get_repo(REF)
    assert e.value.code == "REPO_NOT_PUBLIC"
    f = FakeGitHub(); f.malformed_repo = True
    with pytest.raises(JobError) as e:
        client(f).get_repo(REF)
    assert e.value.code == "GITHUB_BAD_RESPONSE" and not e.value.retryable


def test_timeout_is_retryable():
    f = FakeGitHub(); f.timeout_on_tarball = True
    with pytest.raises(JobError) as e:
        with client(f).open_archive("owner", "sample", f.sha):
            pass
    assert e.value.code == "GITHUB_TIMEOUT" and e.value.retryable


def test_archive_redirect_allowlist_and_token_not_forwarded(monkeypatch):
    f = FakeGitHub()
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 36)
    from app.core.config import reset_settings_cache
    reset_settings_cache()
    try:
        c = GitHubClient(get_settings(), transport=f.transport())
        with c.open_archive("owner", "sample", f.sha) as chunks:
            assert b"".join(chunks)[:2] == b"\x1f\x8b"
        by_host = dict(f.auth_headers)
        assert by_host["api.github.com"] == "Bearer ghp_" + "a" * 36
        assert by_host["codeload.github.com"] is None  # token never sent to the redirect host
        f2 = FakeGitHub(); f2.redirect_host = "evil.example.com"
        with pytest.raises(JobError) as e:
            with GitHubClient(get_settings(), transport=f2.transport()).open_archive("owner", "sample", f2.sha):
                pass
        assert e.value.code == "GITHUB_BAD_RESPONSE"
        assert not any("evil.example.com" in r for r in f2.requests)
    finally:
        monkeypatch.delenv("GITHUB_TOKEN")
        reset_settings_cache()


def test_invalid_sha_rejected():
    with pytest.raises(JobError):
        with client(FakeGitHub()).open_archive("owner", "sample", "../../etc/passwd"):
            pass


# -------------------------------------------------------------------------- LLM
def provider(fake, monkeypatch_settings=None):
    s = get_settings().model_copy(update={"llm_api_key": "k" * 20, "llm_model": "claude-sonnet-5-5", "llm_max_retries": 2})
    return AnthropicProvider(s, transport=fake.transport(), sleep=lambda _: None)


def test_llm_headers_and_success():
    f = FakeLLM(lambda s, u: '{"answer":"x","citations":[],"evidence_sufficiency":"insufficient","limitations":[]}')
    p = provider(f)
    out = StructuredLLM(p, LLMBudget(5)).structured(QAAnswer, "sys", "user")
    assert out.answer == "x"
    assert f.calls[0]["headers"]["x-api-key"] == "k" * 20 and "repository_data" in f.calls[0]["system"]


def test_llm_transient_retry_then_success():
    f = FakeLLM(); f.status_sequence = [529, 429]
    f.responder = lambda s, u: '{"answer":"ok","citations":[],"evidence_sufficiency":"insufficient","limitations":[]}'
    b = LLMBudget(10)
    assert StructuredLLM(provider(f), b).structured(QAAnswer, "s", "u").answer == "ok"
    assert len(f.calls) == 3


def test_llm_retries_exhausted_and_auth_not_retried():
    f = FakeLLM(); f.status_sequence = [500, 500, 500]
    with pytest.raises(JobError) as e:
        StructuredLLM(provider(f), LLMBudget(10)).structured(QAAnswer, "s", "u")
    assert e.value.code == "LLM_PROVIDER_UNAVAILABLE" and len(f.calls) == 3
    f = FakeLLM(); f.status_sequence = [401]
    with pytest.raises(JobError) as e:
        StructuredLLM(provider(f), LLMBudget(10)).structured(QAAnswer, "s", "u")
    assert e.value.code == "LLM_AUTH_FAILED" and len(f.calls) == 1


def test_llm_repairs_malformed_then_gives_up():
    replies = iter(["not json", '{"answer":"x"}', '{"answer":"fixed","citations":[],"evidence_sufficiency":"insufficient","limitations":[]}'])
    f = FakeLLM(lambda s, u: next(replies))
    assert StructuredLLM(provider(f), LLMBudget(10)).structured(QAAnswer, "s", "u", max_repairs=2).answer == "fixed"
    assert "rejected" in f.calls[1]["user"]
    f = FakeLLM(lambda s, u: "garbage")
    with pytest.raises(JobError) as e:
        StructuredLLM(provider(f), LLMBudget(10)).structured(QAAnswer, "s", "u", max_repairs=2)
    assert e.value.code == "LLM_MALFORMED_OUTPUT" and len(f.calls) == 3


def test_llm_budget_enforced_and_semantic_check():
    f = FakeLLM(lambda s, u: '{"answer":"x","citations":[],"evidence_sufficiency":"insufficient","limitations":[]}')
    with pytest.raises(JobError) as e:
        StructuredLLM(provider(f), LLMBudget(1)).structured(QAAnswer, "s", "u", max_repairs=2, semantic_check=lambda o: "nope")
    assert e.value.code == "LLM_BUDGET_EXCEEDED" and len(f.calls) == 1


def test_llm_timeout_classified():
    def boom(request):
        raise httpx.ReadTimeout("t", request=request)
    s = get_settings().model_copy(update={"llm_api_key": "k" * 20, "llm_model": "m", "llm_max_retries": 0})
    p = AnthropicProvider(s, transport=httpx.MockTransport(boom), sleep=lambda _: None)
    with pytest.raises(JobError) as e:
        p.complete("s", "u", 10)
    assert e.value.code == "LLM_TIMEOUT"
