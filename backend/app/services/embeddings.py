"""Optional semantic retrieval. Embeddings come from any OpenAI-compatible /v1/embeddings endpoint (EMBEDDINGS_* settings); nothing is
downloaded or bundled. Unset = Raven stays purely lexical. Vectors are stored in code_nodes.embedding (JSONB) and compared in Python, which
is fine for the node counts Raven handles (hundreds to a few thousand per analysis); pgvector would be the next step at larger scale."""
from __future__ import annotations

import hashlib
import logging
import math
import uuid

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import Settings, get_settings
from app.core.db import new_session
from app.core.logging import log
from app.models import CodeNode, EmbeddingCache, utcnow

logger = logging.getLogger("raven.embeddings")
EMBED_TYPES = ("function", "class", "model", "route", "module", "configuration", "worker")
BATCH, MAX_CHARS, MIN_SIMILARITY = 64, 2000, 0.30


class EmbeddingError(Exception):
    pass


def embed_texts(texts: list[str], s: Settings | None = None, transport: httpx.BaseTransport | None = None) -> list[list[float]]:
    s = s or get_settings()
    headers = {"content-type": "application/json", **({"authorization": f"Bearer {s.embeddings_api_key}"} if s.embeddings_api_key else {})}
    try:
        with httpx.Client(base_url=s.embeddings_base_url.rstrip("/"), timeout=httpx.Timeout(30.0, connect=5.0), transport=transport) as c:
            r = c.post("/v1/embeddings", headers=headers, json={"model": s.embeddings_model, "input": [t[:MAX_CHARS] for t in texts]})
        r.raise_for_status()
        rows = sorted(r.json()["data"], key=lambda d: d["index"])
        out = [[float(x) for x in d["embedding"]] for d in rows]
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise EmbeddingError(type(exc).__name__) from None
    if len(out) != len(texts):
        raise EmbeddingError("wrong number of vectors")
    return out


def embed_query_cached(db, text: str, s: Settings, transport: httpx.BaseTransport | None = None) -> list[float]:
    """Embed a question, reusing a stored vector for the same (model, normalised text). Misses call the endpoint and are stored."""
    norm = " ".join(text.lower().split())[:MAX_CHARS]
    key = hashlib.sha256(f"{s.embeddings_model}\x1f{norm}".encode()).hexdigest()
    row = db.get(EmbeddingCache, key, with_for_update=True)
    if row is not None:
        row.hits += 1
        return [float(x) for x in row.vector]
    vec = embed_texts([norm], s, transport)[0]
    db.execute(pg_insert(EmbeddingCache).values(key=key, vector=vec, hits=0, created_at=utcnow()).on_conflict_do_nothing(index_elements=["key"]))
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def embed_analysis(job_id: uuid.UUID, s: Settings | None = None, transport: httpx.BaseTransport | None = None,
                   reuse_from: uuid.UUID | None = None) -> int:
    """Embed every retrievable node of an analysis. Nodes whose key and text are unchanged since `reuse_from` copy that vector instead of
    calling the endpoint. Returns the number of nodes sent to the endpoint."""
    s = s or get_settings()
    with new_session() as db:
        rows = db.execute(select(CodeNode.id, CodeNode.search_text, CodeNode.node_key).where(
            CodeNode.analysis_id == job_id, CodeNode.type.in_(EMBED_TYPES), CodeNode.search_text != "").order_by(CodeNode.node_key)).all()
        if reuse_from:
            old = {k: (txt, emb) for k, txt, emb in db.execute(select(CodeNode.node_key, CodeNode.search_text, CodeNode.embedding).where(
                CodeNode.analysis_id == reuse_from, CodeNode.embedding.is_not(None))).all()}
            todo = []
            for nid, txt, key in rows:
                if key in old and old[key][0] == txt:
                    db.execute(update(CodeNode).where(CodeNode.id == nid).values(embedding=old[key][1]))
                else:
                    todo.append((nid, txt, key))
            rows = todo
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            for (nid, _, _k), vec in zip(chunk, embed_texts([t for _, t, _k in chunk], s, transport)):
                db.execute(update(CodeNode).where(CodeNode.id == nid).values(embedding=vec))
        db.commit()
    return len(rows)


def semantic_candidates(db, analysis_id: uuid.UUID, question: str, s: Settings | None = None, k: int = 8,
                        transport: httpx.BaseTransport | None = None) -> list[tuple[float, CodeNode]]:
    """Nodes whose embedding is closest to the question (cosine >= MIN_SIMILARITY), best first, with a deterministic tie-break."""
    s = s or get_settings()
    nodes = db.execute(select(CodeNode).where(CodeNode.analysis_id == analysis_id, CodeNode.embedding.is_not(None))).scalars().all()
    if not nodes:
        return []
    q = embed_query_cached(db, question, s, transport)
    scored = [(cosine(q, n.embedding), n) for n in nodes]
    scored = [x for x in scored if x[0] >= MIN_SIMILARITY]
    scored.sort(key=lambda x: (-round(x[0], 6), x[1].path or "", x[1].start_line or 0, x[1].node_key))
    return scored[:k]


def safe_semantic_candidates(db, analysis_id: uuid.UUID, question: str) -> list[tuple[float, CodeNode]]:
    """Never raises: a failing embeddings endpoint must degrade retrieval to lexical, not break Q&A."""
    s = get_settings()
    if not s.embeddings_configured:
        return []
    try:
        return semantic_candidates(db, analysis_id, question, s)
    except EmbeddingError as exc:
        log(logger, "semantic_retrieval_skipped", logging.WARNING, error=str(exc))
        return []
