"""Change-impact analysis: a GitHub compare result mapped onto the stored graph of the analyzed (head) commit.

Honest scope: static import/route/test links only. Tests are "potentially relevant", never a guaranteed regression set.
"""
from __future__ import annotations

import uuid
from collections import defaultdict, deque
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.filters import classify_path
from app.models import CodeEdge, CodeNode

MAX_DEPTH = 3
MAX_AFFECTED = 200
LIMITATIONS = [
    "Computed on the dependency graph of the analyzed (head) commit; files deleted or renamed in this range have no node there, so their former dependents are not traced.",
    "Only static imports, route registrations and frontend URL matches are followed. Dynamic imports, dependency injection, reflection and runtime wiring are not.",
    "Tests are listed because a static link exists (they import the changed/affected code, or match it by name). This is not a guaranteed regression set and no test was run.",
    "GitHub's compare API returns at most 300 files; larger ranges are truncated.",
]


def _weaker(a: str, b: str) -> str:
    order = {"verified_static": 0, "inferred": 1, "unresolved": 2}
    return a if order[a] >= order[b] else b


def compute_impact(db: Session, analysis_id: uuid.UUID, compare: dict[str, Any], base_ref: str, base_sha: str | None, head_sha: str, repo_full_name: str) -> dict[str, Any]:
    nodes = {n.id: n for n in db.execute(select(CodeNode).where(CodeNode.analysis_id == analysis_id, CodeNode.type.in_(("module", "test", "route")))).scalars()}
    mods = {n.path: n for n in nodes.values() if n.type in ("module", "test") and n.path}
    edges = list(db.execute(select(CodeEdge).where(CodeEdge.analysis_id == analysis_id, CodeEdge.relation.in_(("imports", "tested_by", "calls_api")))).scalars())
    routes_by_path: dict[str, list[CodeNode]] = defaultdict(list)
    for n in nodes.values():
        if n.type == "route" and n.path:
            routes_by_path[n.path].append(n)

    changed, seeds = [], {}
    for f in compare["files"]:
        path = f["path"]
        node = mods.get(path)
        dec = classify_path(path)
        kind = ("test" if node is not None and node.type == "test" else "frontend" if node is not None and node.meta.get("web") else "python" if node is not None else
                dec.kind if dec.kind in ("python", "web", "support") else "other")
        entry = {**f, "kind": kind, "in_graph": node is not None, "removed": f["status"] == "removed"}
        if f["status"] == "removed":
            entry["note"] = "removed in this range — not present in the analyzed commit"
        elif node is None and dec.kind in ("python", "web"):
            entry["note"] = "source file not in the analysis (excluded or over a limit)"
        changed.append(entry)
        if node is not None:
            seeds[node.id] = node

    # reverse import closure: dependents of changed modules
    rev: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    for e in edges:
        if e.relation == "imports" and e.resolution != "unresolved" and e.source_id in nodes and e.target_id in nodes:
            rev[e.target_id].append((e.source_id, e.resolution))
    dist: dict[uuid.UUID, int] = {i: 0 for i in seeds}
    via: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    res_of: dict[uuid.UUID, str] = {i: "verified_static" for i in seeds}
    q: deque[uuid.UUID] = deque(seeds)
    while q and len(dist) < MAX_AFFECTED + len(seeds):
        cur = q.popleft()
        if dist[cur] >= MAX_DEPTH:
            continue
        for src, res in rev.get(cur, []):
            if src not in dist:
                dist[src] = dist[cur] + 1
                via[src] = (cur, res)
                res_of[src] = _weaker(res_of[cur], res)
                q.append(src)
    affected = [i for i in dist if i not in seeds]
    affected_py = [i for i in affected if nodes[i].type == "module"]
    tests: dict[uuid.UUID, dict[str, Any]] = {}
    for i in seeds:
        if nodes[i].type == "test":
            tests[i] = {"path": nodes[i].path, "reason": "test file changed in this range", "resolution": "verified_static", "distance": 0}
    for i in affected:
        if nodes[i].type == "test":
            tests[i] = {"path": nodes[i].path, "reason": f"imports changed/affected code ({dist[i]} import hop{'s' if dist[i] > 1 else ''})", "resolution": res_of[i], "distance": dist[i]}
    relevant = set(seeds) | set(affected_py)
    for e in edges:
        if e.relation == "tested_by" and e.source_id in relevant and e.target_id in nodes and e.target_id not in tests:
            t = nodes[e.target_id]
            tests[e.target_id] = {"path": t.path, "reason": "linked to " + (nodes[e.source_id].path or "") + (" by import" if e.resolution == "verified_static" else " by file-name convention"),
                                  "resolution": e.resolution, "distance": dist.get(e.source_id, 0)}

    routes, route_ids = [], set()
    for i in relevant:
        n = nodes[i]
        for r in routes_by_path.get(n.path or "", []):
            route_ids.add(r.id)
            routes.append({"method": r.meta.get("method"), "path": r.meta.get("full_path"), "file": r.path, "line": r.start_line, "path_status": r.meta.get("path_status"),
                           "reason": "handler file changed" if i in seeds else f"handler file imports changed code ({dist[i]} hop{'s' if dist[i] > 1 else ''})", "resolution": "verified_static" if i in seeds else res_of[i]})
    frontend: dict[uuid.UUID, dict[str, Any]] = {}
    for i in seeds:
        if nodes[i].meta.get("web"):
            frontend[i] = {"path": nodes[i].path, "reason": "frontend file changed", "resolution": "verified_static", "evidence": []}
    for e in edges:
        if e.relation == "calls_api" and e.target_id in route_ids and e.source_id in nodes and nodes[e.source_id].meta.get("web"):
            slot = frontend.setdefault(e.source_id, {"path": nodes[e.source_id].path, "reason": "calls an API route in affected code", "resolution": e.resolution, "evidence": []})
            slot["evidence"] += e.evidence[:1]
    for i in affected:
        if nodes[i].meta.get("web") and i not in frontend:
            frontend[i] = {"path": nodes[i].path, "reason": f"imports changed frontend code ({dist[i]} hop{'s' if dist[i] > 1 else ''})", "resolution": res_of[i], "evidence": []}

    # small graph for the UI (changed ∪ affected ∪ tests ∪ frontend callers), edges = dependent -> dependency
    ids = (set(seeds) | set(affected[:40]) | set(tests) | set(frontend))
    route_file_ids = {mods[p].id for p in routes_by_path if p in mods}
    gn = []
    for i in sorted(ids, key=lambda x: nodes[x].path or ""):
        n = nodes[i]
        tag = "changed" if i in seeds else ("test" if i in tests else "affected")
        gn.append({"id": str(i), "kind": "file", "label": PurePosixPath(n.path or "").name, "path": n.path, "dir": str(PurePosixPath(n.path or "").parent) if "/" in (n.path or "") else "",
                   "role": "test" if n.type == "test" else "frontend" if n.meta.get("web") else "router" if i in route_file_ids else "module", "tag": tag, "counts": {}, "lines": n.end_line or 0, "degree": 0})
    ge = []
    for e in edges:
        if e.source_id in ids and e.target_id in ids and e.relation == "imports" and e.resolution != "unresolved":
            ge.append({"id": f"{e.source_id}>{e.target_id}", "source": str(e.source_id), "target": str(e.target_id), "kinds": {"imports": 1}, "count": 1, "resolution": e.resolution, "evidence": e.evidence[:1], "labels": []})
        elif e.relation == "tested_by" and e.source_id in ids and e.target_id in ids:
            ge.append({"id": f"{e.target_id}>{e.source_id}:t", "source": str(e.target_id), "target": str(e.source_id), "kinds": {"tests": 1}, "count": 1, "resolution": e.resolution, "evidence": e.evidence[:1], "labels": []})
    for e in edges:
        if e.relation == "calls_api" and e.source_id in ids and e.target_id in route_ids:
            tgt = mods.get(nodes[e.target_id].path or "")
            if tgt is not None and tgt.id in ids:
                ge.append({"id": f"{e.source_id}>{tgt.id}:api", "source": str(e.source_id), "target": str(tgt.id), "kinds": {"calls_api": 1}, "count": 1, "resolution": e.resolution, "evidence": e.evidence[:1], "labels": []})
    counts = defaultdict(int)
    for c in changed:
        counts[c["kind"]] += 1
    return {
        "repository": repo_full_name, "base_ref": base_ref, "base_sha": base_sha, "head_sha": head_sha, "compare_url": f"https://github.com/{repo_full_name}/compare/{base_sha or base_ref}...{head_sha}",
        "status": compare.get("status"), "ahead_by": compare.get("ahead_by"), "truncated": compare.get("truncated", False),
        "summary": {"changed_files": len(changed), "python": counts["python"], "frontend": counts["frontend"], "tests_changed": counts["test"], "other": counts["other"] + counts["support"] + counts["web"],
                    "removed": sum(1 for c in changed if c["removed"]), "affected_modules": len(affected_py), "routes": len(routes), "relevant_tests": len(tests), "frontend_touched": len(frontend)},
        "changed": sorted(changed, key=lambda c: c["path"])[:300],
        "affected": [{"path": nodes[i].path, "distance": dist[i], "via": nodes[via[i][0]].path, "resolution": res_of[i], "is_test": nodes[i].type == "test"} for i in sorted(affected, key=lambda x: (dist[x], nodes[x].path or ""))[:MAX_AFFECTED] if nodes[i].type == "module"],
        "routes": sorted(routes, key=lambda r: (r["path"] or "", r["method"] or ""))[:100],
        "tests": sorted(tests.values(), key=lambda t: (t["distance"], t["path"] or ""))[:60],
        "frontend": list(frontend.values())[:60], "graph": {"nodes": gn, "edges": ge[:400]}, "limitations": LIMITATIONS,
    }
