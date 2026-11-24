"""Evidence retrieval for grounded Q&A: exact symbol/path/route matching, PostgreSQL full-text search and graph neighbors.
Only redacted content of files that did not trip high-confidence secret screening is ever returned."""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import AnalysisFile, AnalysisJob, CodeEdge, CodeNode
from app.services import embeddings

CHANNELS = frozenset({"lexical", "semantic", "graph"})
MAX_ITEMS = 12
MAX_TOTAL_LINES = 400
MAX_SNIPPET_LINES = 60
STOP = set("the a an and or of to in on for with how does do is are what where which who why when this that these those it its from by as at be can "
           "code file files function functions class classes module modules repo repository project app application use used uses using work works "
           "explain show tell me about please there their into over under".split())
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:[./\-][A-Za-z0-9_]+)*|/[A-Za-z0-9_{}\-/]*")


def tokenize(question: str) -> tuple[list[str], list[str]]:
    """Return (identifier-like tokens, plain word tokens)."""
    idents: list[str] = []
    words: list[str] = []
    for m in _TOKEN.findall(question[:2000]):
        low = m.lower()
        if m.startswith("/") and len(m) > 1:
            idents.append(m)
            continue
        if len(m) < 3 or low in STOP:
            continue
        if any(c in m for c in "_./-") or re.search(r"[a-z][A-Z]", m) or m.isupper():
            idents.append(m)
        words.append(low)
    seen, out_i, out_w = set(), [], []
    for t in idents:
        if t not in seen:
            seen.add(t)
            out_i.append(t)
    for t in words:
        if t not in seen:
            seen.add(t)
            out_w.append(t)
    return out_i[:12], out_w[:12]


def _like(tok: str) -> str:
    return "%" + tok.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _ts_or(tokens: list[str]) -> str | None:
    parts = []
    for t in tokens:
        for piece in re.split(r"[^A-Za-z0-9]+", t.lower()):
            if len(piece) >= 3 and piece not in STOP:
                parts.append(piece)
    parts = list(dict.fromkeys(parts))[:12]
    return " | ".join(parts) if parts else None


# Every query that is limited or whose order affects the result has a content-derived tie-breaker (path, line, node/edge key):
# node ids differ per analysis, so ordering by database row order made re-analyses of the same commit retrieve different evidence.
def retrieve(db: Session, analysis_id: uuid.UUID, question: str, *, max_items: int = MAX_ITEMS, max_lines: int = MAX_TOTAL_LINES,
             channels: frozenset[str] = CHANNELS) -> list[dict[str, Any]]:
    idents, words = tokenize(question)
    tokens = idents + words
    if not tokens:
        return []
    cand: dict[tuple[str, int, int], dict[str, Any]] = {}
    node_hits: list[tuple[float, CodeNode]] = []

    def add(path: str | None, start: int | None, end: int | None, score: float, kind: str, reason: str, symbol: str | None = None,
            channel: str = "lexical") -> None:
        if not path or channel not in channels:
            return
        s0 = max(1, start or 1)
        e0 = max(s0, end or s0)
        key = (path, s0, e0)
        cur = cand.get(key)
        if cur is None or score > cur["score"]:
            cand[key] = {"path": path, "start": s0, "end": e0, "score": score, "kind": kind, "reason": reason, "symbol": symbol, "channel": channel}

    base = select(CodeNode).where(CodeNode.analysis_id == analysis_id, CodeNode.type.in_(("function", "class", "model", "route", "module", "test", "configuration", "worker")))
    # exact + partial symbol / route / path matches
    for tok in idents:
        low = tok.lower()
        conds = [func.lower(CodeNode.name) == low, CodeNode.qualified_name.ilike(_like(tok)), CodeNode.path.ilike(_like(tok))]
        if tok.startswith("/"):
            conds.append(CodeNode.meta["full_path"].astext.ilike(_like(tok)))
        for n in db.execute(base.where(or_(*conds)).order_by(CodeNode.path, CodeNode.start_line, CodeNode.node_key).limit(40)).scalars():
            exact = n.name.lower() == low
            score = 10.0 if exact else (9.0 if tok.startswith("/") else 6.0)
            node_hits.append((score, n))
            add(n.path, n.start_line, n.end_line, score, n.type, f"matches `{tok}`", n.qualified_name)
    for tok in words:
        for n in db.execute(base.where(func.lower(CodeNode.name) == tok).order_by(CodeNode.path, CodeNode.start_line, CodeNode.node_key).limit(15)).scalars():
            node_hits.append((7.0, n))
            add(n.path, n.start_line, n.end_line, 7.0, n.type, f"name matches `{tok}`", n.qualified_name)
    # full-text search over node search_text
    q = _ts_or(tokens)
    if q:
        tsv = func.to_tsvector("simple", CodeNode.search_text)
        tsq = func.to_tsquery("simple", q)
        rank = func.ts_rank(tsv, tsq)
        for n, r in db.execute(select(CodeNode, rank).where(CodeNode.analysis_id == analysis_id, tsv.op("@@")(tsq),
                                                            CodeNode.type.in_(("function", "class", "model", "route", "module", "configuration", "worker")))
                               .order_by(rank.desc(), CodeNode.path, CodeNode.start_line, CodeNode.node_key).limit(25)).all():
            sc = 2.0 + float(r) * 6
            node_hits.append((sc, n))
            add(n.path, n.start_line, n.end_line, sc, n.type, "full-text match on name/docstring", n.qualified_name)
        # file content search → matching lines
        ftsv = func.to_tsvector("simple", func.coalesce(AnalysisFile.content, ""))
        frank = func.ts_rank(ftsv, tsq)
        rows = db.execute(select(AnalysisFile.path, AnalysisFile.content, frank).where(
            AnalysisFile.analysis_id == analysis_id, AnalysisFile.has_secret_like.is_(False), ftsv.op("@@")(tsq))
            .order_by(frank.desc(), AnalysisFile.path).limit(6)).all()
        needles = [t.lower() for t in tokens if len(t) >= 3]
        for path, content, r in rows:
            lines = (content or "").split("\n")
            hit_lines = [i + 1 for i, ln in enumerate(lines) if any(nd in ln.lower() for nd in needles)][:3]
            for ln in hit_lines:
                add(path, max(1, ln - 3), ln + 12, 1.5 + float(r) * 4, "text", "source text matches question terms")
    # optional semantic matches (embeddings): weaker than exact hits, labelled "related to ..." so confidence never counts them as direct evidence
    for cos, n in (embeddings.safe_semantic_candidates(db, analysis_id, question) if "semantic" in channels else []):
        node_hits.append((3.0 + cos * 5, n))
        add(n.path, n.start_line, n.end_line, 3.0 + cos * 5, n.type, "related to the question by meaning (embedding similarity)", n.qualified_name, "semantic")
    # graph neighbors of the strongest symbol hits
    top = sorted(node_hits, key=lambda x: -x[0])
    seen_ids: set[uuid.UUID] = set()
    primary = []
    for sc, n in top:
        if n.id not in seen_ids and n.type in {"function", "route", "class", "model"}:
            seen_ids.add(n.id)
            primary.append((sc, n))
        if len(primary) >= 4:
            break
    for sc, n in primary:
        edges = db.execute(select(CodeEdge).where(CodeEdge.analysis_id == analysis_id, or_(CodeEdge.source_id == n.id, CodeEdge.target_id == n.id),
                                                  CodeEdge.relation.in_(("calls", "registers_route", "uses_model", "uses_dependency", "starts_worker")),
                                                  CodeEdge.resolution != "unresolved").order_by(CodeEdge.relation, CodeEdge.edge_key).limit(8)).scalars().all()
        ids = {e.source_id if e.target_id == n.id else e.target_id: e.relation for e in edges}
        if ids:
            for nb in db.execute(select(CodeNode).where(CodeNode.id.in_(list(ids))).order_by(CodeNode.path, CodeNode.start_line, CodeNode.node_key)).scalars():
                add(nb.path, nb.start_line, nb.end_line, 1.5 + sc * 0.1, nb.type, f"related to `{n.name}` via {ids[nb.id]}", nb.qualified_name, "graph")

    if not cand:
        return []
    # materialize snippets from stored (redacted) content; skip secret-bearing files
    paths = {k[0] for k in cand}
    files = {f.path: f for f in db.execute(select(AnalysisFile).where(AnalysisFile.analysis_id == analysis_id, AnalysisFile.path.in_(paths))).scalars()}
    commit_sha = db.execute(select(AnalysisJob.commit_sha).where(AnalysisJob.id == analysis_id)).scalar_one_or_none()
    ordered = sorted(cand.values(), key=lambda c: (-c["score"], c["path"], c["start"], c["end"]))
    by_file: dict[str, list[tuple[int, int]]] = defaultdict(list)
    out: list[dict[str, Any]] = []
    total = 0
    for c in ordered:
        f = files.get(c["path"])
        if f is None or f.content is None or f.has_secret_like:
            continue
        end = min(c["end"], c["start"] + MAX_SNIPPET_LINES - 1, f.line_count)
        start = min(c["start"], f.line_count)
        if start < 1 or end < start:
            continue  # empty file (0 lines) or range outside the file
        if any(not (end < a or start > b) for a, b in by_file[c["path"]]):
            continue  # overlaps an already selected range in this file
        n_lines = end - start + 1
        if total + n_lines > max_lines and out:
            continue
        lines = f.content.split("\n")[start - 1:end]
        out.append({"id": f"E{len(out) + 1}", "path": c["path"], "start_line": start, "end_line": end, "kind": c["kind"], "reason": c["reason"],
                    "symbol": c["symbol"], "channel": c["channel"], "commit_sha": commit_sha,
                    "text": "\n".join(lines)})
        by_file[c["path"]].append((start, end))
        total += n_lines
        if len(out) >= max_items:
            break
    return out
