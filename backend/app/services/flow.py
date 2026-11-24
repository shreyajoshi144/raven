"""Graph projections for the interactive flow views (file-level 'file graph' and symbol-level route trace).

Everything is derived from stored nodes/edges, so each connection keeps its evidence and resolution status.
Symbol-level edges are *lifted* to the files that contain them; an aggregated connection is `verified_static` only if every
underlying edge is, otherwise `inferred` (or `unresolved` for placeholder targets).
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict, deque
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import CodeEdge, CodeNode

SERVICE_DIRS = {"services", "service", "core", "crud", "repositories", "repository", "usecases", "use_cases", "domain", "managers", "logic"}
LIFT_RELATIONS = {"imports", "calls_api", "calls", "uses_model", "uses_dependency", "starts_worker", "configured_by", "tested_by"}
TRACE_RELATIONS = {"calls_api", "calls", "uses_model", "uses_dependency", "starts_worker", "configured_by", "registers_route"}
ROLE_BONUS = {"frontend": 18, "entry": 50, "router": 20, "model": 12, "service": 10, "worker": 8, "config": 4, "module": 0, "test": -5}


def _res(rs: set[str]) -> str:
    if "unresolved" in rs:
        return "unresolved"
    return "verified_static" if rs == {"verified_static"} else "inferred"


def build_file_flow(db: Session, analysis_id: uuid.UUID, *, limit: int = 70, focus: str | None = None, include_tests: bool = False,
                    include_external: bool = True) -> dict[str, Any]:
    limit = max(10, min(limit, 200))
    nodes = list(db.execute(select(CodeNode).where(CodeNode.analysis_id == analysis_id, CodeNode.type != "directory", CodeNode.type != "file",
                                                   CodeNode.type != "repository")).scalars())
    edges = list(db.execute(select(CodeEdge).where(CodeEdge.analysis_id == analysis_id, CodeEdge.relation.in_(LIFT_RELATIONS))).scalars())
    by_id = {n.id: n for n in nodes}
    mods = {n.path: n for n in nodes if n.type in ("module", "test") and n.path}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for n in nodes:
        if n.path in mods:
            if n.type == "route":
                counts[n.path]["routes"] += 1
            elif n.type == "model":
                counts[n.path]["models"] += 1
                counts[n.path]["classes"] += 1
            elif n.type == "class":
                counts[n.path]["classes"] += 1
            elif n.type == "function" and "." not in n.name:
                counts[n.path]["functions"] += 1
            elif n.type == "worker":
                counts[n.path]["workers"] += 1

    def owner(nid: uuid.UUID) -> tuple[str, str | uuid.UUID] | None:
        n = by_id.get(nid)
        if n is None:
            return None
        if n.type == "external_dependency":
            return ("ext", n.id)
        if n.type == "configuration":
            return ("cfg", n.id)
        if n.path in mods:
            return ("mod", n.path)  # type: ignore[arg-type]
        return None

    agg: dict[tuple[Any, Any], dict[str, Any]] = {}
    env_count: Counter[str] = Counter()
    for e in edges:
        a, b = owner(e.source_id), owner(e.target_id)
        if a is None or b is None or a == b:
            continue
        if b[0] == "cfg":
            if a[0] == "mod":
                env_count[a[1]] += 1  # type: ignore[index]
            continue
        if a[0] != "mod":
            continue
        if e.relation == "tested_by" and not include_tests:
            continue
        key = (a[1], b[1] if b[0] == "mod" else ("ext", b[1]))
        slot = agg.setdefault(key, {"kinds": Counter(), "res": set(), "evidence": [], "labels": []})
        slot["kinds"][e.relation] += 1
        slot["res"].add(e.resolution)
        if len(slot["evidence"]) < 4 and e.evidence:
            slot["evidence"].append(e.evidence[0])
        if len(slot["labels"]) < 3 and e.label:
            slot["labels"].append(e.label)
    for p, c in env_count.items():
        counts[p]["env"] = c

    indeg: Counter[str] = Counter()
    deg: Counter[Any] = Counter()
    for (s, t), _ in agg.items():
        deg[s] += 1
        deg[t] += 1
        if isinstance(t, str) and not (mods[s].type == "test"):
            indeg[t] += 1

    def role(path: str) -> str:
        n = mods[path]
        c = counts[path]
        if n.type == "test":
            return "test"
        if n.meta.get("web"):
            return "frontend"
        if any(r.get("reason", "").startswith(("creates FastAPI app", "has `if __name__")) for r in n.meta.get("entry_reasons", [])):
            return "entry"
        if c["routes"]:
            return "router"
        if c["models"]:
            return "model"
        if c["workers"]:
            return "worker"
        parts = {p.lower() for p in PurePosixPath(path).parts[:-1]}
        if parts & SERVICE_DIRS or indeg[path] >= 3:
            return "service"
        if PurePosixPath(path).stem.lower() in {"config", "settings", "db", "database", "session"}:
            return "config"
        return "module"

    roles = {p: role(p) for p in mods}
    candidates = [p for p in mods if (include_tests or roles[p] != "test") and PurePosixPath(p).name != "__init__.py" or (mods[p].meta.get("is_package") and deg[p] > 0 and (include_tests or roles[p] != "test"))]
    if focus:
        f = focus.strip("/")
        inside = [p for p in candidates if p == f or p.startswith(f + "/")]
        chosen = sorted(inside, key=lambda p: (-(ROLE_BONUS[roles[p]] + deg[p]), p))[:limit]
        cs = set(chosen)
        ctx: list[str] = []
        for (s, t), _ in agg.items():
            for x, y in ((s, t), (t, s)):
                if x in cs and isinstance(y, str) and y in mods and y not in cs and y in candidates and y not in ctx and len(ctx) < 20:
                    ctx.append(y)
        context = set(ctx)
        chosen += ctx
    else:
        chosen = sorted(candidates, key=lambda p: (-(ROLE_BONUS[roles[p]] + deg[p]), p))[:limit]
        context = set()
    cset = set(chosen)

    out_nodes = []
    for p in chosen:
        n = mods[p]
        c = counts[p]
        out_nodes.append({
            "id": str(n.id), "kind": "file", "label": PurePosixPath(p).name, "path": p, "dir": str(PurePosixPath(p).parent) if "/" in p else "",
            "role": roles[p], "lines": (n.end_line or 0), "context": p in context, "degree": deg[p],
            "counts": {**{k: c[k] for k in ("routes", "models", "functions", "classes", "env", "workers") if c[k]}, **({"api": len(n.meta.get("calls", []))} if n.meta.get("web") and n.meta.get("calls") else {})},
            "summary": (n.explanation or None), "summary_source": n.explanation_source,
        })
    ext_nodes: dict[uuid.UUID, dict[str, Any]] = {}
    out_edges = []
    for (s, t), slot in agg.items():
        if s not in cset:
            continue
        if isinstance(t, tuple):
            if not include_external:
                continue
            en = by_id[t[1]]
            if en.meta.get("unresolved") is None and not (en.meta.get("category") or deg[t] >= 2):
                continue
            ext_nodes.setdefault(en.id, {"id": str(en.id), "kind": "external", "label": en.name, "path": None, "dir": "", "role": "external",
                                         "category": en.meta.get("category"), "unresolved": bool(en.meta.get("unresolved")), "degree": 0, "counts": {}})
            ext_nodes[en.id]["degree"] += 1
            tid = str(en.id)
        else:
            if t not in cset:
                continue
            tid = str(mods[t].id)
        out_edges.append({"id": f"{mods[s].id}>{tid}", "source": str(mods[s].id), "target": tid, "kinds": dict(slot["kinds"]), "count": sum(slot["kinds"].values()),
                          "resolution": _res(slot["res"]), "evidence": slot["evidence"], "labels": slot["labels"]})
    ext_sorted = sorted(ext_nodes.values(), key=lambda x: (x["unresolved"], -x["degree"]))
    keep = {x["id"] for x in ext_sorted[:14]}
    out_edges = [e for e in out_edges if e["target"] in {n["id"] for n in out_nodes} or e["target"] in keep]
    total_mods = len([p for p in candidates])
    return {"nodes": out_nodes + [x for x in ext_sorted[:14]], "edges": out_edges, "total_files": total_mods, "shown_files": len(chosen),
            "truncated": total_mods > len(chosen) and not focus, "focus": focus,
            "folders": sorted({str(PurePosixPath(p).parent) for p in candidates if "/" in p})[:300]}


def build_trace(db: Session, analysis_id: uuid.UUID, node_id: uuid.UUID, depth: int = 3, max_nodes: int = 60) -> dict[str, Any]:
    depth = max(1, min(depth, 4))
    root = db.get(CodeNode, node_id)
    if root is None or root.analysis_id != analysis_id or root.type in ("directory", "repository", "file"):
        raise ApiError("NOT_FOUND", "Node not found.")
    out_by: dict[uuid.UUID, list[CodeEdge]] = defaultdict(list)
    in_by: dict[uuid.UUID, list[CodeEdge]] = defaultdict(list)
    for e in db.execute(select(CodeEdge).where(CodeEdge.analysis_id == analysis_id, CodeEdge.relation.in_(TRACE_RELATIONS))).scalars():
        out_by[e.source_id].append(e)
        in_by[e.target_id].append(e)
    seen: dict[uuid.UUID, int] = {root.id: 0}
    order: list[uuid.UUID] = [root.id]
    out_edges: list[dict[str, Any]] = []
    q: deque[uuid.UUID] = deque([root.id])
    ids_needed = {root.id}

    def add_edge(e: CodeEdge, src: uuid.UUID, dst: uuid.UUID, relation: str) -> None:
        ids_needed.update((src, dst))
        out_edges.append({"id": f"{src}>{dst}>{relation}", "source": str(src), "target": str(dst), "relation": relation, "resolution": e.resolution,
                          "evidence": e.evidence[:2], "label": e.label, "count": 1, "kinds": {relation: 1}})

    while q and len(seen) < max_nodes:
        cur = q.popleft()
        d = seen[cur]
        if d >= depth:
            continue
        nxt: list[tuple[CodeEdge, uuid.UUID, uuid.UUID, str]] = []
        for e in out_by.get(cur, []):
            if e.relation == "registers_route":
                continue  # handler -> route is shown in the reverse direction below
            nxt.append((e, e.source_id, e.target_id, e.relation))
        for e in in_by.get(cur, []):
            if e.relation == "registers_route":  # present as route -> handler ("handled by")
                nxt.append((e, e.target_id, e.source_id, "handled_by"))
            elif e.relation == "calls_api":  # frontend call site -> route (shown left of the route)
                nxt.append((e, e.source_id, e.target_id, "calls_api"))
        for e, s, t, rel in nxt:
            other = t if s == cur else s
            if other not in seen:
                if len(seen) >= max_nodes:
                    continue
                seen[other] = d + 1
                order.append(other)
                q.append(other)
            add_edge(e, s, t, rel)
    nodes = {n.id: n for n in db.execute(select(CodeNode).where(CodeNode.id.in_(list(ids_needed)))).scalars()}
    out_nodes = []
    for nid in order:
        n = nodes.get(nid)
        if n is None:
            continue
        role = "frontend" if n.meta.get("web") else {"route": "router", "model": "model", "external_dependency": "external", "configuration": "config", "worker": "worker", "class": "service",
                "function": "module", "module": "module", "test": "test"}.get(n.type, "module")
        out_nodes.append({"id": str(n.id), "kind": n.type, "label": n.name.split(".")[-1] if n.type in ("function", "class", "model") else n.name,
                          "path": n.path, "dir": n.path or "", "role": role, "start_line": n.start_line, "end_line": n.end_line, "depth": seen[nid],
                          "unresolved": bool(n.meta.get("unresolved")), "summary": n.explanation, "summary_source": n.explanation_source,
                          "counts": {}, "lines": (n.end_line or 0) - (n.start_line or 0) + 1 if n.start_line else 0, "degree": 0,
                          "facts": n.facts[:3]})
    present = {n["id"] for n in out_nodes}
    out_edges = [e for e in out_edges if e["source"] in present and e["target"] in present]
    uniq = {e["id"]: e for e in out_edges}
    return {"root": str(root.id), "nodes": out_nodes, "edges": list(uniq.values()), "truncated": len(seen) >= max_nodes}
