"""Architecture intelligence: a per-analysis snapshot (modules, internal/external imports, cycles, layer violations, coupling, complexity,
routes, public symbols) and the drift between two analyses of the same repository, plus the change impact that drift predicts.

Everything is derived from stored graph/facts of analyses (static `ast` data) and every finding cites file+line evidence with the commit.
Nothing is executed and nothing is guessed: boundary rules are a documented directory-name heuristic and are labelled `inferred`.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisFile, AnalysisJob, CodeEdge, CodeNode

# Heuristic layers by directory name; a module may only depend on its own or a *lower* layer (higher number).
LAYER_DIRS = {"api": 0, "routes": 0, "routers": 0, "endpoints": 0, "views": 0, "controllers": 0,
              "services": 1, "service": 1, "usecases": 1,
              "models": 2, "db": 2, "repositories": 2, "repository": 2, "crud": 2,
              "core": 3, "config": 3, "utils": 3, "common": 3}
LAYER_NAMES = ["presentation", "service", "data", "core"]
FANOUT_GROWTH, FANOUT_MIN = 3, 8  # coupling finding: a module gained >= 3 internal imports and now has >= 8
COMPLEXITY_ABS, COMPLEXITY_REL = 10, 0.25  # complexity finding: +10 and +25 % on one module
MAX_DEPTH, MAX_LIST = 3, 60
LIMITATIONS = [
    "Static analysis of Python source only: dynamic imports, dependency injection, reflection and runtime wiring are not seen.",
    "Layer/boundary rules are a heuristic based on directory names (api, services, models, core, ...); they are reported as inferred, not as proven design violations.",
    "'Previous' means the owner's most recent earlier analysis of the same repository, not necessarily the parent commit; compare any two analyses with ?base=.",
    "Predicted impact lists code that statically imports changed code. It is a bounded estimate, not a guarantee, and no test was run.",
]


def layer_of(path: str) -> int | None:
    for part in path.split("/")[:-1]:
        if part in LAYER_DIRS:
            return LAYER_DIRS[part]
    return None


def _ev(path: str, start: int | None, end: int | None, sha: str) -> dict[str, Any]:
    return {"path": path, "start_line": start or 1, "end_line": end or start or 1, "commit_sha": sha}


def _sccs(adj: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected components with more than one member (import cycles). Iterative Tarjan: deep graphs must not hit recursion limits."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in sorted(adj):
        if root in index:
            continue
        work = [(root, iter(sorted(adj[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(adj.get(w, ())))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        out.append(sorted(comp))
    return sorted(out)


def snapshot(db: Session, job: AnalysisJob) -> dict[str, Any]:
    sha = job.commit_sha
    nodes = {n.id: n for n in db.execute(select(CodeNode).where(
        CodeNode.analysis_id == job.id, CodeNode.type.in_(("module", "test", "route", "external_dependency")))).scalars()}
    py = {i: n for i, n in nodes.items() if n.type in ("module", "test") and n.path and not n.meta.get("web")}
    internal: dict[str, set[str]] = defaultdict(set)
    imp_ev: dict[tuple[str, str], dict[str, Any]] = {}
    ext: dict[str, dict[str, Any]] = {}
    tests_importing: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for e in db.execute(select(CodeEdge).where(CodeEdge.analysis_id == job.id, CodeEdge.relation == "imports")).scalars():
        s, t = py.get(e.source_id), nodes.get(e.target_id)
        if s is None or t is None or not e.evidence:
            continue
        ev = e.evidence[0]
        evd = _ev(ev.get("path", s.path), ev.get("start_line"), ev.get("end_line"), sha)
        if t.type == "external_dependency":
            if not t.meta.get("unresolved") and s.type == "module":
                ext.setdefault(t.name, {"name": t.name, "category": t.meta.get("category"), "evidence": evd, "resolution": e.resolution})
        elif t.id in py:
            if s.type == "test":
                tests_importing[t.path].setdefault(s.path, {"path": s.path, "evidence": evd, "resolution": e.resolution})
            elif t.type == "module":
                internal[s.path].add(t.path)
                imp_ev.setdefault((s.path, t.path), {"evidence": evd, "resolution": e.resolution})
    mods = sorted(n.path for n in py.values() if n.type == "module")
    for m in mods:
        internal.setdefault(m, set())
    facts = {p: f for p, f in db.execute(select(AnalysisFile.path, AnalysisFile.facts).where(
        AnalysisFile.analysis_id == job.id, AnalysisFile.kind == "python", AnalysisFile.status == "analyzed")).all() if f}
    complexity = {p: sum(int(fn.get("complexity") or 0) for fn in f.get("functions", [])) for p, f in facts.items()}
    symbols: dict[str, dict[str, Any]] = {}
    test_paths = {n.path for n in py.values() if n.type == "test"}
    for p, f in facts.items():
        if p in test_paths:  # test code is not public API: removing or renaming a test must not read as a breaking change
            continue
        for fn in f.get("functions", []):
            if not fn["name"].startswith("_"):
                symbols[f"{p}::{fn['qualname']}"] = {"path": p, "name": fn["qualname"], "params": fn.get("params", []), "line": fn["line"],
                                                    "end_line": fn["end_line"], "async": fn.get("async", False)}
    routes = {n.name: {"name": n.name, "path": n.path, "line": n.start_line, "end_line": n.end_line} for n in nodes.values() if n.type == "route" and n.path}
    cycles = _sccs({m: {d for d in internal[m] if d in internal} for m in mods})
    violations = []
    for (s, t), info in sorted(imp_ev.items()):
        ls, lt = layer_of(s), layer_of(t)
        if ls is not None and lt is not None and lt < ls:
            violations.append({"source": s, "target": t, "rule": f"{LAYER_NAMES[ls]} layer imports {LAYER_NAMES[lt]} layer", **info})
    fan_in: dict[str, int] = defaultdict(int)
    for s in internal:
        for t in internal[s]:
            fan_in[t] += 1
    return {"analysis_id": str(job.id), "commit_sha": sha, "modules": mods, "internal": {m: sorted(v) for m, v in internal.items()}, "import_evidence": imp_ev,
            "external": ext, "tests_importing": {k: list(v.values()) for k, v in tests_importing.items()}, "complexity": complexity, "symbols": symbols,
            "routes": routes, "cycles": cycles, "violations": violations, "fan_in": dict(fan_in)}


def metrics(s: dict[str, Any]) -> dict[str, Any]:
    fan_out = {m: len(v) for m, v in s["internal"].items()}
    top = sorted(fan_out.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {"modules": len(s["modules"]), "internal_imports": sum(fan_out.values()), "external_dependencies": len(s["external"]), "cycles": len(s["cycles"]),
            "boundary_violations": len(s["violations"]), "routes": len(s["routes"]), "total_complexity": sum(s["complexity"].values()),
            "max_fan_out": top[0][1] if top else 0, "top_fan_out": [{"path": p, "fan_out": n} for p, n in top if n]}


def describe(s: dict[str, Any]) -> dict[str, Any]:
    """The per-analysis view returned by the API (no raw maps)."""
    return {"analysis_id": s["analysis_id"], "commit_sha": s["commit_sha"], "metrics": metrics(s),
            "cycles": [{"modules": c, "evidence": [s["import_evidence"][(a, b)]["evidence"] for a in c for b in s["internal"].get(a, []) if b in c][:5]} for c in s["cycles"][:MAX_LIST]],
            "violations": [{k: v for k, v in x.items()} for x in s["violations"][:MAX_LIST]], "external": sorted(s["external"].values(), key=lambda x: x["name"])[:200],
            "limitations": LIMITATIONS}


def _finding(kind: str, severity: str, title: str, detail: str, evidence: list[dict[str, Any]], resolution: str = "verified_static") -> dict[str, Any]:
    return {"kind": kind, "severity": severity, "title": title, "detail": detail, "evidence": evidence[:5], "resolution": resolution}


def _reverse_closure(internal: dict[str, list[str]], seeds: set[str]) -> dict[str, tuple[int, str]]:
    rev: dict[str, list[str]] = defaultdict(list)
    for s, ts in internal.items():
        for t in ts:
            rev[t].append(s)
    dist: dict[str, tuple[int, str]] = {}
    q = deque((p, 0, p) for p in sorted(seeds))
    seen = set(seeds)
    while q:
        p, d, _via = q.popleft()
        if d >= MAX_DEPTH:
            continue
        for dep in sorted(rev.get(p, [])):
            if dep not in seen:
                seen.add(dep)
                dist[dep] = (d + 1, p)
                q.append((dep, d + 1, p))
    return dist


def drift(db: Session, base: AnalysisJob, head: AnalysisJob) -> dict[str, Any]:
    b, h = snapshot(db, base), snapshot(db, head)
    f: list[dict[str, Any]] = []
    hs, bs = head.commit_sha, base.commit_sha
    for name in sorted(set(h["external"]) - set(b["external"])):
        x = h["external"][name]
        f.append(_finding("new_dependency", "medium", f"New external dependency `{name}`", f"Not imported at {bs[:7]}, imported at {hs[:7]}.", [x["evidence"]], x["resolution"]))
    for name in sorted(set(b["external"]) - set(h["external"])):
        f.append(_finding("removed_dependency", "info", f"External dependency `{name}` no longer imported", f"Imported at {bs[:7]}, not at {hs[:7]}.", [b["external"][name]["evidence"]]))
    bcyc = {tuple(c) for c in b["cycles"]}
    for c in h["cycles"]:
        if tuple(c) not in bcyc:
            ev = [h["import_evidence"][(x, y)]["evidence"] for x in c for y in h["internal"].get(x, []) if y in c]
            f.append(_finding("new_cycle", "medium", f"New import cycle across {len(c)} modules", " → ".join(c[:6]) + (" …" if len(c) > 6 else ""), ev))
    hcyc = {tuple(c) for c in h["cycles"]}
    for c in b["cycles"]:
        if tuple(c) not in hcyc:
            f.append(_finding("resolved_cycle", "info", f"Import cycle resolved ({len(c)} modules)", " → ".join(c[:6]), []))
    bviol = {(v["source"], v["target"]) for v in b["violations"]}
    for v in h["violations"]:
        if (v["source"], v["target"]) not in bviol:
            f.append(_finding("boundary_violation", "medium", f"New boundary violation: {v['source']} → {v['target']}", v["rule"] + " (directory-name heuristic)", [v["evidence"]], "inferred"))
    for m in h["modules"]:
        fo_b, fo_h = len(b["internal"].get(m, [])), len(h["internal"].get(m, []))
        if m in b["internal"] and fo_h - fo_b >= FANOUT_GROWTH and fo_h >= FANOUT_MIN:
            new = sorted(set(h["internal"][m]) - set(b["internal"].get(m, [])))
            f.append(_finding("coupling_increase", "medium", f"`{m}` now imports {fo_h} internal modules (was {fo_b})", "New: " + ", ".join(new[:6]),
                              [h["import_evidence"][(m, t)]["evidence"] for t in new if (m, t) in h["import_evidence"]]))
        cb, ch = b["complexity"].get(m), h["complexity"].get(m, 0)
        if cb is not None and ch - cb >= COMPLEXITY_ABS and ch >= cb * (1 + COMPLEXITY_REL):
            f.append(_finding("complexity_growth", "medium", f"Complexity of `{m}` grew {cb} → {ch}", "Sum of cyclomatic complexity of its functions.", [_ev(m, 1, None, hs)]))
    for name in sorted(set(h["routes"]) - set(b["routes"])):
        r = h["routes"][name]
        f.append(_finding("route_added", "info", f"New route {name}", "", [_ev(r["path"], r["line"], r["end_line"], hs)]))
    # breaking changes: removed public symbols/routes, changed parameters (evidence is the BASE definition that dependents relied on)
    breaking: list[tuple[str, str, dict[str, Any]]] = []  # (module path, symbol, finding-evidence)
    for key, sym in sorted(b["symbols"].items()):
        new = h["symbols"].get(key)
        if new is None:
            gone = sym["path"] not in h["modules"]
            f.append(_finding("breaking_symbol_removed", "high", f"Public `{sym['name']}` removed" + (" (module deleted)" if gone else ""), f"Defined in {sym['path']} at {bs[:7]}.",
                              [_ev(sym["path"], sym["line"], sym["end_line"], bs)]))
            breaking.append((sym["path"], sym["name"], _ev(sym["path"], sym["line"], sym["end_line"], bs)))
        elif new["params"] != sym["params"]:
            lost = [p for p in sym["params"] if p not in new["params"]]
            f.append(_finding("breaking_signature_changed", "high" if lost else "medium", f"Signature of `{sym['name']}` changed",
                              f"Parameters {sym['params']} → {new['params']}." + (f" Removed: {lost}." if lost else ""),
                              [_ev(sym["path"], sym["line"], sym["end_line"], bs), _ev(new["path"], new["line"], new["end_line"], hs)]))
            breaking.append((sym["path"], sym["name"], _ev(new["path"], new["line"], new["end_line"], hs)))
    for name in sorted(set(b["routes"]) - set(h["routes"])):
        r = b["routes"][name]
        f.append(_finding("breaking_route_removed", "high", f"Route {name} removed", "Clients calling this route will fail.", [_ev(r["path"], r["line"], r["end_line"], bs)]))
    # predicted impact: dependents (on the base graph, which is what the changed code was used by) of modified/deleted modules
    base_files = {p: h_ for p, h_ in db.execute(select(AnalysisFile.path, AnalysisFile.content_sha256).where(AnalysisFile.analysis_id == base.id, AnalysisFile.content_sha256.is_not(None))).all()}
    head_files = {p: h_ for p, h_ in db.execute(select(AnalysisFile.path, AnalysisFile.content_sha256).where(AnalysisFile.analysis_id == head.id, AnalysisFile.content_sha256.is_not(None))).all()}
    touched = {p for p in b["modules"] if p not in head_files or head_files[p] != base_files.get(p)}
    closure = _reverse_closure(b["internal"], touched)
    affected = [{"path": p, "distance": d, "via": via, "resolution": b["import_evidence"].get((p, via), {}).get("resolution", "verified_static"),
                 "evidence": b["import_evidence"].get((p, via), {}).get("evidence")} for p, (d, via) in sorted(closure.items(), key=lambda kv: (kv[1][0], kv[0]))][:MAX_LIST]
    in_scope = touched | set(closure)
    routes = [{"name": r["name"], "path": r["path"], "evidence": _ev(r["path"], r["line"], r["end_line"], bs), "status": "removed" if r["name"] not in h["routes"] else "present"}
              for r in b["routes"].values() if r["path"] in in_scope][:MAX_LIST]
    tests = {}
    for m in in_scope:
        for t in b["tests_importing"].get(m, []):
            tests.setdefault(t["path"], {"path": t["path"], "imports": m, "evidence": t["evidence"], "resolution": t["resolution"]})
    bodies = {p: c for p, c in db.execute(select(AnalysisFile.path, AnalysisFile.content).where(
        AnalysisFile.analysis_id == base.id, AnalysisFile.path.in_({p for p, _, _ in breaking} | set(closure)))).all() if c}
    breaking_users = []
    for mod, sym, _unused in breaking:
        name = sym.split(".")[-1]
        for p, (d, via) in closure.items():
            if d == 1 and via == mod and name != "__init__" and re.search(rf"\b{re.escape(name)}\b", bodies.get(p, "")):
                breaking_users.append({"symbol": sym, "defined_in": mod, "used_by": p, "evidence": b["import_evidence"].get((p, mod), {}).get("evidence")})
    used = {(u["defined_in"], u["symbol"]) for u in breaking_users}
    for x in f:  # a removed public symbol is only "high" when another module in the changed set still references it by name
        if x["kind"] == "breaking_symbol_removed" and x["severity"] == "high":
            ev = x["evidence"][0]
            sym = x["title"].split("`")[1]
            if (ev["path"], sym) not in used:
                x["severity"] = "low"
                x["detail"] += " No other module that imports it mentions this name, so nothing else appears to depend on it."
    bm, hm = metrics(b), metrics(h)
    delta = {k: hm[k] - bm[k] for k in bm if isinstance(bm[k], int)}
    counts: dict[str, int] = defaultdict(int)
    for x in f:
        counts[x["kind"]] += 1
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    f.sort(key=lambda x: (order[x["severity"]], x["kind"], x["title"]))
    return {"base": {"analysis_id": str(base.id), "commit_sha": bs}, "head": {"analysis_id": str(head.id), "commit_sha": hs}, "metrics": {"base": bm, "head": hm, "delta": delta},
            "summary": dict(counts), "findings": f[:200],
            "predicted_impact": {"basis": "static import graph at the base commit", "changed_modules": sorted(touched)[:MAX_LIST], "affected_modules": affected, "routes": routes,
                                 "tests": sorted(tests.values(), key=lambda t: t["path"])[:MAX_LIST], "breaking_symbol_users": breaking_users[:MAX_LIST]},
            "limitations": LIMITATIONS}


def previous_job(db: Session, job: AnalysisJob) -> AnalysisJob | None:
    return db.execute(select(AnalysisJob).where(
        AnalysisJob.owner_id == job.owner_id, AnalysisJob.repository_id == job.repository_id, AnalysisJob.id != job.id, AnalysisJob.state == "READY",
        AnalysisJob.graph_complete.is_(True), AnalysisJob.commit_sha != job.commit_sha, AnalysisJob.created_at < job.created_at)
        .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id).limit(1)).scalar_one_or_none()


def history(db: Session, job: AnalysisJob, limit: int = 20) -> list[dict[str, Any]]:
    """Oldest-first timeline of the owner's READY analyses of this repository with metrics and the change from the previous point."""
    rows = db.execute(select(AnalysisJob).where(
        AnalysisJob.owner_id == job.owner_id, AnalysisJob.repository_id == job.repository_id, AnalysisJob.state == "READY", AnalysisJob.graph_complete.is_(True))
        .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id).limit(limit)).scalars().all()[::-1]
    out, prev = [], None
    for r in rows:
        m = metrics(snapshot(db, r))
        out.append({"analysis_id": str(r.id), "commit_sha": r.commit_sha, "analyzed_at": r.created_at.isoformat(), "current": r.id == job.id, "metrics": m,
                    "delta": {k: m[k] - prev[k] for k in m if isinstance(m[k], int)} if prev else None})
        prev = m
    return out


def same_repo_job(db: Session, owner_id: uuid.UUID, repository_id: uuid.UUID, analysis_id: uuid.UUID) -> AnalysisJob | None:
    j = db.get(AnalysisJob, analysis_id)
    return j if j and j.owner_id == owner_id and j.repository_id == repository_id and j.state == "READY" and j.graph_complete else None
