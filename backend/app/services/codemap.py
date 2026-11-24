"""The Map: an architecture-first view of an analysis. Level 1 areas -> level 2 groups -> level 3 files. Built from the same stored
nodes and edges as every other view, so each connection keeps its relation and resolution; file-to-file links are lifted from symbols."""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CodeEdge, CodeNode
from app.services.areas import AREAS, area_of, group_files
from app.services.flow import LIFT_RELATIONS, SERVICE_DIRS


def _label(group: str) -> str:
    return (group.replace("_", " ").replace("-", " ").strip() or "root").title() if group not in ("", "other") else ("Main folder" if group == "" else "Other")


def build_map(db: Session, analysis_id: uuid.UUID) -> dict[str, Any]:
    nodes = list(db.execute(select(CodeNode).where(CodeNode.analysis_id == analysis_id, CodeNode.type.in_(
        ("module", "test", "route", "model", "class", "function", "worker", "external_dependency", "configuration")))).scalars())
    by_id = {n.id: n for n in nodes}
    mods = {n.path: n for n in nodes if n.type in ("module", "test") and n.path and PurePosixPath(n.path).name != "__init__.py"}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    routes: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        if n.path not in mods:
            continue
        if n.type == "route":
            counts[n.path]["routes"] += 1
            if len(routes[n.path]) < 6:
                routes[n.path].append(n.name)
        elif n.type == "model":
            counts[n.path]["models"] += 1
        elif n.type == "function" and "." not in n.name:
            counts[n.path]["functions"] += 1
        elif n.type == "worker":
            counts[n.path]["workers"] += 1
    edges = list(db.execute(select(CodeEdge).where(CodeEdge.analysis_id == analysis_id, CodeEdge.relation.in_(LIFT_RELATIONS))).scalars())
    links: dict[tuple[str, str], dict[str, Any]] = {}
    ext_users: dict[str, set[str]] = defaultdict(set)
    ext_meta: dict[str, str | None] = {}
    indeg: Counter[str] = Counter()
    tested: Counter[str] = Counter()
    for e in edges:
        s, t = by_id.get(e.source_id), by_id.get(e.target_id)
        if s is None or t is None or s.path not in mods:
            continue
        if t.type == "external_dependency":
            ext_users[t.name].add(s.path)
            ext_meta[t.name] = (t.meta or {}).get("category")
            continue
        if t.path not in mods or t.path == s.path:
            continue
        if e.relation == "tested_by":  # tests are shown as coverage, not as something a file depends on
            tested[s.path] += 1
            continue
        k = (s.path, t.path)
        slot = links.setdefault(k, {"kinds": Counter(), "res": set()})
        slot["kinds"][e.relation] += 1
        slot["res"].add(e.resolution)
        if mods[s.path].type != "test":
            indeg[t.path] += 1
    files, by_area = [], defaultdict(list)
    for p, n in mods.items():
        meta = n.meta or {}
        role = "test" if n.type == "test" else "frontend" if meta.get("web") else "entry" if any(str(r.get("reason", "")).startswith("creates FastAPI app")
                                                                                                 for r in meta.get("entry_reasons", [])) else \
            "router" if counts[p]["routes"] else "model" if counts[p]["models"] else "worker" if counts[p]["workers"] else \
            "service" if ({x.lower() for x in PurePosixPath(p).parts[:-1]} & SERVICE_DIRS or indeg[p] >= 3) else "module"
        area = area_of(p, role, bool(meta.get("web")))
        by_area[area].append(p)
        files.append({"id": str(n.id), "path": p, "name": PurePosixPath(p).name, "role": role, "area": area, "routes": counts[p]["routes"], "models": counts[p]["models"],
                      "functions": counts[p]["functions"], "workers": counts[p]["workers"], "tests": tested[p], "route_names": routes.get(p, []), "line": n.start_line or 1})
    file_group: dict[str, str] = {}
    groups = []
    for area, paths in by_area.items():
        for g, gp in group_files(sorted(paths)).items():
            gid = f"{area}/{g or '_root'}"
            for p in gp:
                file_group[p] = gid
            c = Counter()
            for p in gp:
                c.update(counts[p])
            top = sorted(gp, key=lambda p: -(indeg[p] + counts[p]["routes"] * 3))[:3]
            groups.append({"id": gid, "area": area, "label": _label(g), "folder": g, "files": len(gp), "routes": c["routes"], "models": c["models"], "functions": c["functions"],
                           "top": [PurePosixPath(p).name for p in top]})
    for f in files:
        f["group"] = file_group[f["path"]]
    id_of = {f["path"]: f["id"] for f in files}
    out_links = [{"s": id_of[s], "t": id_of[t], "kinds": dict(v["kinds"]), "resolution": "verified_static" if v["res"] == {"verified_static"} else "inferred"}
                 for (s, t), v in links.items() if s in id_of and t in id_of]
    areas = []
    for aid, meta in AREAS.items():
        fs = [f for f in files if f["area"] == aid]
        if aid == "external":
            if ext_users:
                areas.append({"id": aid, **meta, "files": len(ext_users), "routes": 0, "models": 0, "functions": 0})
            continue
        if fs:
            areas.append({"id": aid, **meta, "files": len(fs), "routes": sum(f["routes"] for f in fs), "models": sum(f["models"] for f in fs), "functions": sum(f["functions"] for f in fs)})
    externals = sorted(({"name": k, "category": ext_meta.get(k), "used_by": len(v), "files": [id_of[p] for p in sorted(v) if p in id_of][:20]} for k, v in ext_users.items()), key=lambda x: -x["used_by"])[:40]
    return {"areas": areas, "groups": groups, "files": files, "links": out_links, "externals": externals,
            "totals": {"files": len(files), "links": len(out_links), "routes": sum(f["routes"] for f in files)}}
