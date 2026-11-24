import httpx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import new_session
from app.models import AnswerCache, EmbeddingCache
from app.services import embeddings
from app.services import qa as qasvc
from tests.conftest import create_analysis, emulate_n8n, new_other_client
from tests.fakes import FakeLLM
from tests.test_chat import ask, wire


def _counted(orch):
    n = {"calls": 0}
    inner = orch.qa_handler
    def handler(p):
        n["calls"] += 1
        return inner(p)
    orch.qa_handler = handler
    return n


def test_repeat_question_is_served_from_cache_without_a_model_call(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, FakeLLM(), monkeypatch)
    n = _counted(orch)
    first = ask(user_client, ready, "What does get_current_user do?").json()["answer"]
    assert first["cache_hit"] is False and first["answer_source"] == "ai"
    again = ask(user_client, ready, "  what does   GET_CURRENT_USER do ").json()["answer"]  # case / spacing / punctuation do not matter
    assert again["cache_hit"] is True and n["calls"] == 1
    assert again["content"] == first["content"] and again["citations"] == first["citations"] and again["confidence"] == first["confidence"]
    with new_session() as db:
        row = db.execute(select(AnswerCache)).scalar_one()
        assert row.hits == 1 and row.input_tokens > 0
    assert ask(user_client, ready, "Which handler serves /api/users/ ?").json()["answer"]["cache_hit"] is False  # a different question is a miss


def test_cache_is_shared_across_users_for_the_same_commit(user_client, orch, ready, monkeypatch, app, gh_fake):
    wire(orch, user_client, FakeLLM(), monkeypatch)
    ask(user_client, ready, "What does get_current_user do?")
    other = new_other_client(app, "second@example.com")
    aid2 = create_analysis(other).json()["analysis_id"]
    emulate_n8n(other, aid2, gh_fake, FakeLLM())
    r = ask(other, aid2, "What does get_current_user do?")
    assert r.status_code == 200 and r.json()["answer"]["cache_hit"] is True


def test_fallback_answers_are_never_cached(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, None, monkeypatch)  # no provider configured -> retrieval-only answers
    for _ in range(2):
        a = ask(user_client, ready, "What does get_current_user do?").json()["answer"]
        assert a["answer_source"] == "retrieval_only" and a["cache_hit"] is False
    with new_session() as db:
        assert db.execute(select(func.count()).select_from(AnswerCache)).scalar() == 0


def test_cache_can_be_disabled(user_client, orch, ready, monkeypatch):
    wire(orch, user_client, FakeLLM(), monkeypatch)
    monkeypatch.setattr(get_settings(), "answer_cache_enabled", False, raising=False)
    ask(user_client, ready, "What does get_current_user do?")
    assert ask(user_client, ready, "What does get_current_user do?").json()["answer"]["cache_hit"] is False


def test_question_embeddings_are_cached():
    calls = {"n": 0}
    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
    s = get_settings().model_copy(update={"embeddings_base_url": "http://emb.test", "embeddings_model": "m"})
    t = httpx.MockTransport(handler)
    with new_session() as db:
        a = embeddings.embed_query_cached(db, "Where is auth?", s, t)
        b = embeddings.embed_query_cached(db, "  where is   AUTH? ", s, t)
        db.commit()
        assert a == b == [0.1, 0.2, 0.3] and calls["n"] == 1
        row = db.execute(select(EmbeddingCache)).scalar_one()
        assert row.hits == 1


def test_normalisation_and_key_inputs():
    assert qasvc.normalize_question("  What DOES `get_current_user`  do?? ") == "what does get_current_user do"
