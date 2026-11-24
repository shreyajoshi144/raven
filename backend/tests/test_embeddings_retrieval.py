"""Optional semantic retrieval via an OpenAI-compatible embeddings endpoint (faked here with a deterministic concept embedder)."""
import httpx
import pytest

from app.core.config import get_settings
from app.core.db import new_session
from app.retrieval.search import retrieve
from app.services import embeddings
from app.services.embeddings import EmbeddingError, cosine, embed_texts
from evals.runner import analyze
from tests.helpers import analyze as analyze_mem  # noqa: F401  (kept for parity with other suites)

SRC = {"app/__init__.py": "", "app/accounts.py": '''def verify_credentials(user, secret):
    """Check the login password against the stored hash."""
    return user.hash == secret


def render_invoice(order):
    """Format an order as a printable invoice."""
    return str(order)
'''}
CONCEPTS = [("login", "password", "credentials", "sign in", "sign-in", "authenticate"), ("invoice", "printable", "order", "bill")]


def fake_embed(texts, s=None, transport=None):
    return [[float(any(w in t.lower() for w in group)) for group in CONCEPTS] + [0.01] for t in texts]


@pytest.fixture()
def semantic(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "embeddings_base_url", "http://emb.invalid")
    monkeypatch.setattr(s, "embeddings_model", "fake-embed")
    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)


def ranked(job, q):
    with new_session() as db:
        return [(e["path"], e["start_line"], e["reason"]) for e in retrieve(db, job, q)]


def test_without_embeddings_a_synonym_question_finds_nothing_relevant():
    an = analyze("o/semantic", {p: c.encode() for p, c in SRC.items()})
    assert not any("verify_credentials" in str(r) or r[2].startswith("related to the question by meaning") for r in ranked(an.job_id, "how do users sign in?"))


def test_semantic_retrieval_finds_synonym_matches_and_labels_them_indirect(semantic):
    an = analyze("o/semantic", {p: c.encode() for p, c in SRC.items()})
    got = ranked(an.job_id, "how do users sign in?")
    assert any(p == "app/accounts.py" and r.startswith("related to the question by meaning") for p, _, r in got)  # "related to ..." is never counted as direct evidence
    assert not any("render_invoice" in r for _, _, r in got[:1])


def test_semantic_retrieval_is_deterministic_across_reanalysis(semantic):
    files = {p: c.encode() for p, c in SRC.items()}
    first = ranked(analyze("o/semantic", files).job_id, "how do users sign in?")
    assert all(ranked(analyze("o/semantic", files).job_id, "how do users sign in?") == first for _ in range(2))


def test_failing_embeddings_degrade_to_lexical_without_failing_analysis_or_qa(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "embeddings_base_url", "http://emb.invalid")
    monkeypatch.setattr(s, "embeddings_model", "fake-embed")

    def boom(*a, **k):
        raise EmbeddingError("ConnectError")
    monkeypatch.setattr(embeddings, "embed_texts", boom)
    an = analyze("o/semantic", {p: c.encode() for p, c in SRC.items()})
    assert an.state == "BUILDING_GRAPH"  # analysis still completes
    assert any("verify_credentials" in str(r) for r in ranked(an.job_id, "what does verify_credentials do?"))  # lexical retrieval unaffected


def test_embed_texts_speaks_the_openai_embeddings_protocol():
    def h(req):
        assert req.url.path == "/v1/embeddings" and req.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]})
    s = get_settings().model_copy(update={"embeddings_base_url": "http://e.invalid", "embeddings_model": "m", "embeddings_api_key": "k"})
    assert embed_texts(["a", "b"], s, httpx.MockTransport(h)) == [[1.0, 0.0], [0.0, 1.0]]
    with pytest.raises(EmbeddingError):
        embed_texts(["a"], s, httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})))
    with pytest.raises(EmbeddingError):
        embed_texts(["a"], s, httpx.MockTransport(lambda r: httpx.Response(500)))


def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0 and cosine([1, 0], [0, 1]) == 0.0 and cosine([0, 0], [1, 1]) == 0.0
