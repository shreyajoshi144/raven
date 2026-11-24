"""Server-side Mermaid generation from stored graph data. Labels are sanitized; ids are opaque (n0, n1...)."""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeEdge, CodeNode
from app.services.docs_builder import mm_label

EDGE_STYLE = {"verified_static": "-->", "inferred": "-.->", "unresolved": "-.->"}


def _line(a: str, b: str, rel: str, res: str) -> str:
    return f"  {a} {EDGE_STYLE[res]}|{mm_label(rel + ('?' if res != 'verified_static' else ''), 18)}| {b}"


def build_diagram(db: Session, analysis_id: uuid.UUID, view: str, limit: int = 40) -> dict[str, Any]:
    limit = max(5, min(limit, 80))
    nodes = {n.id: n for n in db.execute(select(CodeNode).where(CodeNode.analysis_id == analysis_id)).scalars()}
    edges = list(db.execute(select(CodeEdge).where(CodeEdge.analysis_id == analysis_id, CodeEdge.relation != "contains")).scalars())
    ids: dict[uuid.UUID, str] = {}
    lines = ["flowchart LR", "  classDef unresolved stroke-dasharray: 4 4,stroke:#b42318", "  classDef route stroke-width:2px", "  classDef ext stroke-dasharray: 2 2"]
    deg: dict[uuid.UUID, int] = defaultdict(int)
    for e in edges:
        deg[e.source_id] += 1
        deg[e.target_id] += 1

    def nid(n: CodeNode) -> str:
        if n.id not in ids:
            ids[n.id] = f"n{len(ids)}"
        return ids[n.id]

    def decl(n: CodeNode) -> str:
        label = mm_label(n.name, 34)
        i = nid(n)
        if n.type == "external_dependency":
            cls = "unresolved" if n.meta.get("unresolved") else "ext"
            return f'  {i}[("{label}")]:::{cls}'
        if n.type == "route":
            return f'  {i}(["{label}"]):::route'
        if n.type == "model":
            return f'  {i}[("{label}")]'
        return f'  {i}["{label}"]'

    shown_nodes: list[CodeNode] = []
    shown_edges: list[CodeEdge] = []
    total = 0
    if view == "modules":
        mods = [n for n in nodes.values() if n.type == "module"]
        total = len(mods)
        chosen = sorted(mods, key=lambda n: (-deg[n.id], n.path or ""))[:limit]
        cset = {n.id for n in chosen}
        for e in edges:
            if e.relation != "imports" or e.source_id not in cset:
                continue
            t = nodes[e.target_id]
            if e.target_id in cset or (t.type == "external_dependency" and (t.meta.get("unresolved") or t.meta.get("category"))):
                shown_edges.append(e)
        ext = {e.target_id for e in shown_edges if nodes[e.target_id].type == "external_dependency"}
        keep_ext = set(sorted(ext, key=lambda i: -deg[i])[:10])
        shown_edges = [e for e in shown_edges if nodes[e.target_id].type != "external_dependency" or e.target_id in keep_ext]
        shown_nodes = chosen + [nodes[i] for i in keep_ext]
    elif view == "routes":
        routes = sorted([n for n in nodes.values() if n.type == "route"], key=lambda n: (n.meta.get("full_path", ""), n.name))
        total = len(routes)
        chosen_r = routes[:limit]
        rset = {r.id for r in chosen_r}
        handlers: set[uuid.UUID] = set()
        for e in edges:
            if e.relation == "registers_route" and e.target_id in rset:
                shown_edges.append(e)
                handlers.add(e.source_id)
            elif e.relation in {"uses_dependency", "uses_model"} and e.source_id in rset:
                shown_edges.append(e)
        shown_nodes = chosen_r + [nodes[i] for i in handlers] + [nodes[e.target_id] for e in shown_edges if e.relation in {"uses_dependency", "uses_model"}]
    elif view == "models":
        models = [n for n in nodes.values() if n.type == "model"]
        total = len(models)
        chosen_m = sorted(models, key=lambda n: (-deg[n.id], n.name))[:limit]
        mset = {n.id for n in chosen_m}
        shown_edges = [e for e in edges if e.relation == "uses_model" and e.source_id in mset and e.target_id in mset]
        shown_nodes = chosen_m
    else:
        raise ValueError("unknown view")
    primary_count = {"modules": len(chosen) if view == "modules" else 0, "routes": len(chosen_r) if view == "routes" else 0,
                     "models": len(chosen_m) if view == "models" else 0}[view]
    seen: set[uuid.UUID] = set()
    for n in shown_nodes:
        if n.id not in seen:
            seen.add(n.id)
            lines.append(decl(n))
    seen_edges: set[tuple[str, str, str]] = set()
    for e in shown_edges:
        if e.source_id in ids and e.target_id in ids:
            k = (ids[e.source_id], ids[e.target_id], e.relation)
            if k not in seen_edges:
                seen_edges.add(k)
                lines.append(_line(ids[e.source_id], ids[e.target_id], e.relation, e.resolution))
    if len(ids) == 0:
        return {"view": view, "mermaid": "", "mapping": {}, "shown": 0, "total": total, "truncated": False}
    return {"view": view, "mermaid": "\n".join(lines), "mapping": {v: str(k) for k, v in ids.items()}, "shown": primary_count,
            "total": total, "truncated": total > limit}
