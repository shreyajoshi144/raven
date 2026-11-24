"""Normalized code graph construction from per-file facts.

Edges carry an explicit resolution status:
  verified_static - supported directly by syntax (e.g. an import statement that resolves to a file in the repo)
  inferred        - heuristic (naming conventions, ambiguous matches, unmounted routers...)
  unresolved      - a reference exists but its target cannot be determined statically
No numeric confidence is produced because no calibrated method exists.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

ANALYZER_VERSION = "1.1.0"
STDLIB = set(sys.stdlib_module_names)
NODE_TYPES = ("repository", "directory", "file", "module", "route", "function", "class", "model",
              "configuration", "test", "external_dependency", "worker")
RELATIONS = ("contains", "imports", "calls_api", "defines", "registers_route", "calls", "uses_model", "uses_dependency",
             "configured_by", "tested_by", "starts_worker")
MAX_NODES = 60000
MAX_EDGES = 150000

PYDANTIC_BASES = {"pydantic.BaseModel", "pydantic.main.BaseModel", "pydantic.v1.BaseModel", "pydantic_settings.BaseSettings",
                  "pydantic.BaseSettings", "pydantic_settings.main.BaseSettings", "sqlmodel.SQLModel", "sqlmodel.main.SQLModel"}
SQLA_BASE_SUFFIXES = ("DeclarativeBase", "declarative_base", "DeclarativeBaseNoMeta", "DeclarativeMeta")
KNOWN_CATEGORIES = {
    "httpx": "http_client", "requests": "http_client", "aiohttp": "http_client", "urllib3": "http_client",
    "boto3": "cloud", "botocore": "cloud", "google": "cloud", "azure": "cloud",
    "redis": "cache_queue", "celery": "task_queue", "rq": "task_queue", "dramatiq": "task_queue", "arq": "task_queue",
    "kafka": "messaging", "pika": "messaging", "aio_pika": "messaging", "confluent_kafka": "messaging",
    "openai": "llm", "anthropic": "llm", "langchain": "llm", "cohere": "llm", "transformers": "ml",
    "stripe": "payments", "twilio": "messaging", "sendgrid": "email", "smtplib": "email",
    "sqlalchemy": "database", "psycopg": "database", "psycopg2": "database", "asyncpg": "database", "pymongo": "database",
    "motor": "database", "alembic": "database", "databases": "database", "tortoise": "database", "peewee": "database",
    "sentry_sdk": "observability", "prometheus_client": "observability", "opentelemetry": "observability",
}
FRAMEWORKS = {"fastapi": "FastAPI", "starlette": "Starlette", "pydantic": "Pydantic", "sqlalchemy": "SQLAlchemy",
              "alembic": "Alembic", "uvicorn": "Uvicorn", "gunicorn": "Gunicorn", "celery": "Celery", "httpx": "HTTPX",
              "requests": "Requests", "pytest": "pytest", "redis": "Redis client", "sqlmodel": "SQLModel",
              "flask": "Flask", "django": "Django"}
ENTRY_FILE_NAMES = {"main.py", "app.py", "asgi.py", "wsgi.py", "__main__.py", "manage.py", "run.py", "server.py"}


def stable_key(*parts: object) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:32]


def stable_uuid(analysis_id: uuid.UUID | str, key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.UUID(str(analysis_id)), key)


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    return (any(part in {"tests", "test"} for part in p.parts[:-1]) or name.startswith("test_")
            or name.endswith("_test.py") or name == "conftest.py")


def join_path(*parts: str) -> str:
    joined = "".join(p for p in parts if p)
    joined = re.sub(r"/{2,}", "/", joined)
    if not joined.startswith("/"):
        joined = "/" + joined
    return joined


@dataclass
class GNode:
    key: str
    type: str
    name: str
    qname: str
    path: str | None = None
    start: int | None = None
    end: int | None = None
    facts: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GEdge:
    key: str
    source: str
    target: str
    relation: str
    resolution: str
    evidence: list[dict[str, Any]]
    label: str | None = None


@dataclass
class FileFacts:
    path: str
    facts: dict[str, Any] | None
    line_count: int = 0
    size_bytes: int = 0
    status: str = "analyzed"


@dataclass
class GraphResult:
    nodes: list[GNode]
    edges: list[GEdge]
    stats: dict[str, Any]
    gaps: list[dict[str, Any]]
    entry_points: list[dict[str, Any]]
    routes: list[dict[str, Any]]
    file_summaries: dict[str, str]
    symbol_index: dict[str, str]  # "path::qualname" -> node key


def _ev(path: str, start: int, end: int | None = None) -> dict[str, Any]:
    return {"path": path, "start_line": start, "end_line": end or start}


class GraphBuilder:
    def __init__(self, repo_full_name: str, files: list[FileFacts], all_paths: list[str], support: dict[str, str] | None = None,
                 web_files: list[FileFacts] | None = None):
        self.repo = repo_full_name
        self.files = [f for f in files if f.facts is not None]
        self.web_by_path = {f.path: f.facts for f in (web_files or []) if f.facts}
        self.broken = [f for f in files if f.facts is None]
        self.all_paths = sorted(all_paths)
        self.support = support or {}
        self.nodes: dict[str, GNode] = {}
        self.edges: dict[str, GEdge] = {}
        self.gaps: list[dict[str, Any]] = []
        self.by_path = {f.path: f.facts for f in self.files if f.facts}
        self.exact: dict[str, str] = {}
        self.suffix: dict[str, list[str]] = defaultdict(list)
        self.top_packages: set[str] = set()
        self.defined: dict[str, set[str]] = {}
        self.sym_node: dict[tuple[str, str], str] = {}
        self.module_node: dict[str, str] = {}
        self.file_node: dict[str, str] = {}
        self.containers: dict[tuple[str, str], dict[str, Any]] = {}
        self.class_kind: dict[tuple[str, str], str] = {}
        self._target_cache: dict[tuple[str, str], tuple[Any, ...]] = {}
        self.stats: dict[str, Any] = defaultdict(int)
        self.ext_nodes: dict[str, str] = {}
        self.unresolved_nodes: dict[str, str] = {}

    # ---------------------------------------------------------------- primitives
    def _add_node(self, n: GNode) -> str:
        if n.key not in self.nodes:
            if len(self.nodes) >= MAX_NODES:
                self.stats["node_cap_reached"] = 1
                return n.key
            self.nodes[n.key] = n
        return n.key

    def _node(self, type_: str, qname: str, name: str, path: str | None = None, start: int | None = None,
              end: int | None = None, facts: list[str] | None = None, meta: dict[str, Any] | None = None,
              evidence: list[dict[str, Any]] | None = None) -> str:
        key = stable_key(type_, qname, path or "", start or 0)
        return self._add_node(GNode(key, type_, name[:300], qname[:600], path, start, end, facts or [], meta or {}, evidence or []))

    def _edge(self, src: str, dst: str, relation: str, resolution: str, evidence: list[dict[str, Any]], label: str | None = None) -> None:
        if src == dst or src not in self.nodes or dst not in self.nodes:
            return
        ev0 = evidence[0] if evidence else {}
        key = stable_key(src, dst, relation, ev0.get("path", ""), ev0.get("start_line", 0))
        if key in self.edges:
            return
        if len(self.edges) >= MAX_EDGES:
            self.stats["edge_cap_reached"] = 1
            return
        self.edges[key] = GEdge(key, src, dst, relation, resolution, evidence[:3], label[:200] if label else None)

    def _external(self, top: str) -> str:
        if top not in self.ext_nodes:
            cat = KNOWN_CATEGORIES.get(top)
            self.ext_nodes[top] = self._node(
                "external_dependency", f"ext:{top}", top, facts=[f"External package imported as `{top}`"] + ([f"Category (by package name): {cat}"] if cat else []),
                meta={"category": cat, "external": True})
        return self.ext_nodes[top]

    def _unresolved(self, text: str, kind: str) -> str:
        qn = f"unresolved:{kind}:{text}"[:300]
        if qn not in self.unresolved_nodes:
            self.unresolved_nodes[qn] = self._node(
                "external_dependency", qn, text[:120], facts=[f"Unresolved {kind}: `{text[:120]}` could not be determined statically"],
                meta={"unresolved": True, "kind": kind})
        return self.unresolved_nodes[qn]

    # --------------------------------------------------------------- module index
    def _index_modules(self) -> None:
        for path, facts in self.by_path.items():
            mod = facts["module"]
            if not mod:
                continue
            self.exact[mod] = path
            parts = mod.split(".")
            self.top_packages.add(parts[0])
            for i in range(1, len(parts)):
                self.suffix[".".join(parts[i:])].append(path)
            names = {f["qualname"] for f in facts["functions"] if "." not in f["qualname"]}
            names |= {c["qualname"] for c in facts["classes"] if "." not in c["qualname"]}
            names |= {r["var"] for r in facts["routers"]} | {a["var"] for a in facts["apps"]}
            names |= set(facts["constants"]) | {b["var"] for b in facts["sa_bases"]} | set(facts.get("assigned", []))
            self.defined[path] = names

    @staticmethod
    def _shared_prefix(a: str, b: str) -> int:
        pa, pb = a.split("/"), b.split("/")
        n = 0
        for x, y in zip(pa, pb):
            if x != y:
                break
            n += 1
        return n

    def _lookup_module(self, dotted: str, from_path: str) -> tuple[str | None, bool]:
        if dotted in self.exact:
            return self.exact[dotted], False
        top = dotted.split(".")[0]
        cands = self.suffix.get(dotted, [])
        if cands and top in STDLIB:
            cands = []  # stdlib names win over nested repo files with the same name
        if not cands:
            return None, False
        best = sorted(cands, key=lambda p: (-self._shared_prefix(p, from_path), p))
        return best[0], len(cands) > 1

    def _resolve_target(self, from_path: str, dotted: str, depth: int = 0) -> tuple[Any, ...]:
        """Return ('module', path, ambiguous) | ('symbol', path, name, ambiguous) | ('external', top) | ('unresolved', dotted) | ('stdlib', top)."""
        ck = (from_path, dotted)
        if ck in self._target_cache:
            return self._target_cache[ck]
        res = self._resolve_target_uncached(from_path, dotted, depth)
        self._target_cache[ck] = res
        return res

    def _resolve_target_uncached(self, from_path: str, dotted: str, depth: int) -> tuple[Any, ...]:
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            modname = ".".join(parts[:i])
            mpath, amb = self._lookup_module(modname, from_path)
            if mpath is None:
                continue
            rest = parts[i:]
            if not rest:
                return ("module", mpath, amb)
            sym = rest[0]
            if len(rest) == 1 or True:
                # a submodule?
                sub, samb = self._lookup_module(f"{self.by_path[mpath]['module']}.{sym}", from_path)
                if sub is not None and len(rest) == 1:
                    return ("module", sub, samb or amb)
                if sym in self.defined.get(mpath, set()):
                    return ("symbol", mpath, ".".join(rest), amb)
                # re-export through a binding in that module (e.g. package __init__)
                b = self.by_path[mpath]["bindings"].get(sym)
                if b and depth < 4 and b != dotted:
                    nxt = self._resolve_target(mpath, b, depth + 1)
                    if nxt[0] == "symbol" and len(rest) > 1:
                        return ("symbol", nxt[1], nxt[2] + "." + ".".join(rest[1:]), amb)
                    if nxt[0] in {"symbol", "module"}:
                        return nxt
                    return nxt
                if sub is not None:
                    return ("module", sub, samb or amb)
                return ("unresolved", dotted)
        top = parts[0]
        if top in STDLIB:
            return ("stdlib", top)
        if top in self.top_packages:
            return ("unresolved", dotted)
        return ("external", top)

    def _alias_deps(self, path: str, handler_q: str | None) -> list[dict[str, Any]]:
        """Depends() hidden behind `Name = Annotated[..., Depends(f)]` aliases used as parameter annotations (local or imported)."""
        out: list[dict[str, Any]] = []
        for ann in (self.by_path[path].get("handler_annotations") or {}).get(handler_q or "", []):
            tgt = self._resolve_name(path, ann["name"])
            if tgt[0] == "symbol" and tgt[1] in self.by_path:
                out.extend((self.by_path[tgt[1]].get("dep_aliases") or {}).get(tgt[2], []))
        return out

    def _resolve_name(self, path: str, expr: str) -> tuple[Any, ...]:
        """Resolve a (dotted) name as used inside ``path`` to a target."""
        facts = self.by_path[path]
        head, _, rest = expr.partition(".")
        if head in self.defined.get(path, set()):
            return ("symbol", path, expr, False)
        b = facts["bindings"].get(head)
        if b is None:
            return ("unknown", expr)
        full = f"{b}.{rest}" if rest else b
        return self._resolve_target(path, full)

    # ------------------------------------------------------------------- build
    def build(self) -> GraphResult:
        self._index_modules()
        repo_key = self._node("repository", self.repo, self.repo, facts=[f"Repository `{self.repo}`"])
        self._build_tree(repo_key)
        for path in sorted(self.by_path):
            self._build_module_nodes(path)
        self._classify_classes()
        for path in sorted(self.by_path):
            self._build_symbol_nodes(path)
        for path in sorted(self.by_path):
            self._build_imports(path)
        self._build_containers()
        self._build_routes()
        self._build_web()
        for path in sorted(self.by_path):
            self._build_calls_and_refs(path)
            self._build_config_and_workers(path)
        self._build_tests()
        return self._finish()

    # tree ---------------------------------------------------------------------
    def _build_tree(self, repo_key: str) -> None:
        dirs: dict[str, str] = {}

        def ensure_dir(d: str) -> str:
            if d == "":
                return repo_key
            if d not in dirs:
                key = self._node("directory", d, PurePosixPath(d).name, path=d, facts=[f"Directory `{d}/`"])
                dirs[d] = key
                parent = str(PurePosixPath(d).parent)
                parent = "" if parent == "." else parent
                self._edge(ensure_dir(parent), key, "contains", "verified_static", [])
            return dirs[d]

        for path in self.all_paths:
            parent = str(PurePosixPath(path).parent)
            parent = "" if parent == "." else parent
            pk = ensure_dir(parent)
            facts_obj = self.by_path.get(path) or self.web_by_path.get(path)
            lines = f"{facts_obj['line_count']} lines" if facts_obj else "not analyzed"
            fk = self._node("file", path, PurePosixPath(path).name, path=path, start=1, end=facts_obj["line_count"] if facts_obj else None,
                            facts=[f"File `{path}` ({lines})"], meta={"language": "python" if path.endswith(".py") else ((facts_obj or {}).get("language") or "other")},
                            evidence=[_ev(path, 1, facts_obj["line_count"])] if facts_obj else [])
            self.file_node[path] = fk
            self._edge(pk, fk, "contains", "verified_static", [])

    def _build_module_nodes(self, path: str) -> None:
        facts = self.by_path[path]
        for issue in facts.get("parse_issues") or []:
            if issue["kind"] == "skipped":
                self.gaps.append({"kind": "partial_parse", "path": path, "line": issue["start_line"],
                                  "text": f"lines {issue['start_line']}-{issue['end_line']} not parsed: {issue['detail']}"})
        test = is_test_path(path)
        n_fn = len([f for f in facts["functions"] if "." not in f["qualname"]])
        n_cls = len([c for c in facts["classes"] if "." not in c["qualname"]])
        fl = [f"Module `{facts['module'] or path}` — {facts['line_count']} lines, {n_fn} top-level functions, {n_cls} classes"]
        if facts.get("module_doc"):
            fl.append(f"Docstring: {facts['module_doc'][:200]}")
        meta: dict[str, Any] = {"module": facts["module"], "is_package": facts["is_package"], "is_test": test}
        entry = facts["entry"]
        reasons = []
        for a in facts["apps"]:
            reasons.append({"reason": f"creates FastAPI app `{a['var']}`", "line": a["line"], "resolution": "verified_static" if a["via_import"] else "inferred"})
        if entry["main_guard"]:
            reasons.append({"reason": "has `if __name__ == \"__main__\"` block", "line": entry["main_guard"], "resolution": "verified_static"})
        if entry["uvicorn_run"]:
            reasons.append({"reason": f"calls uvicorn.run({entry['uvicorn_target'] or '...'})", "line": entry["uvicorn_run"], "resolution": "verified_static"})
        for f in entry["factories"]:
            reasons.append({"reason": f"defines application factory `{f['name']}`", "line": f["line"], "resolution": "inferred"})
        if PurePosixPath(path).name in ENTRY_FILE_NAMES and not reasons:
            reasons.append({"reason": f"conventional entry-point file name `{PurePosixPath(path).name}`", "line": 1, "resolution": "inferred"})
        if reasons and not test:
            meta["entry_reasons"] = reasons
            fl.extend(f"Entry point: {r['reason']} (line {r['line']})" for r in reasons[:5])
        key = self._node("test" if test else "module", facts["module"] or path, facts["module"] or PurePosixPath(path).name,
                         path=path, start=1, end=facts["line_count"], facts=fl, meta=meta, evidence=[_ev(path, 1, facts["line_count"])])
        self.module_node[path] = key
        self._edge(self.file_node[path], key, "defines", "verified_static", [_ev(path, 1, facts["line_count"])], "file defines module")

    # models -------------------------------------------------------------------
    def _classify_classes(self) -> None:
        sa_vars: set[tuple[str, str]] = {(p, b["var"]) for p, f in self.by_path.items() for b in f["sa_bases"]}
        changed = True
        kinds: dict[tuple[str, str], str] = {}
        sqlmodel: set[tuple[str, str]] = set()  # classes with SQLModel in their ancestry: `table=True` makes them ORM tables
        for _ in range(8):
            if not changed:
                break
            changed = False
            for path, facts in self.by_path.items():
                for c in facts["classes"]:
                    k = (path, c["qualname"])
                    if k in kinds:
                        continue
                    kind = None
                    for raw, res in zip(c["bases"], self._base_dotted(facts, c)):
                        if res in PYDANTIC_BASES:
                            kind = "pydantic"
                            if res.endswith("SQLModel"):
                                sqlmodel.add(k)
                                if c["keywords"].get("table") == "True":
                                    kind = "sqlalchemy"
                            break
                        short = (res or raw).split(".")[-1]
                        if res and res.split(".")[0] in {"sqlalchemy", "sqlmodel"} and short.endswith(SQLA_BASE_SUFFIXES + ("Base",)):
                            kind = "sqlalchemy"
                            break
                        tgt = self._resolve_name(path, raw) if raw.replace(".", "").replace("_", "").isalnum() else ("unknown", raw)
                        if tgt[0] == "symbol":
                            if (tgt[1], tgt[2]) in sa_vars:
                                kind = "sqlalchemy"
                                break
                            if (tgt[1], tgt[2]) in kinds:
                                kind = kinds[(tgt[1], tgt[2])]
                                if (tgt[1], tgt[2]) in sqlmodel:
                                    sqlmodel.add(k)
                                    if c["keywords"].get("table") == "True":
                                        kind = "sqlalchemy"
                                break
                    if kind is None and c["tablename"]:
                        kind = "sqlalchemy"
                        c["_inferred_model"] = True
                    if kind:
                        kinds[k] = kind
                        changed = True
        self.class_kind = kinds

    def _base_dotted(self, facts: dict[str, Any], c: dict[str, Any]) -> list[str | None]:
        out: list[str | None] = []
        for raw in c["bases"]:
            head, _, rest = raw.partition(".")
            b = facts["bindings"].get(head)
            out.append((f"{b}.{rest}" if rest else b) if b else None)
        return out

    # symbols ------------------------------------------------------------------
    def _build_symbol_nodes(self, path: str) -> None:
        facts = self.by_path[path]
        mod_key = self.module_node[path]
        for c in facts["classes"]:
            kind = self.class_kind.get((path, c["qualname"]))
            fl = [f"class {c['qualname']}({', '.join(c['bases'])})" if c["bases"] else f"class {c['qualname']}"]
            meta: dict[str, Any] = {"bases": c["bases"], "methods": c["methods"][:30]}
            if kind:
                meta["model_kind"] = kind
                meta["fields"] = [{"name": f["name"], "type": f["type"], "line": f["line"]} for f in c["fields"][:40]]
                meta["tablename"] = c["tablename"]
                meta["columns"] = [col["name"] for col in c["columns"][:40]]
                label = {"pydantic": "Pydantic model", "sqlalchemy": "SQLAlchemy model"}[kind]
                if c.get("_inferred_model"):
                    label += " (inferred from __tablename__)"
                    meta["inferred"] = True
                fl.append(label)
                if c["tablename"]:
                    fl.append(f"Table: `{c['tablename']}`")
                if c["fields"]:
                    fl.append("Fields: " + ", ".join(f"{f['name']}: {f['type']}" for f in c["fields"][:12]))
            if c["doc"]:
                fl.append(f"Docstring: {c['doc'][:200]}")
            key = self._node("model" if kind else "class", f"{facts['module']}.{c['qualname']}", c["qualname"], path=path,
                             start=c["line"], end=c["end_line"], facts=fl, meta=meta, evidence=[_ev(path, c["line"], c["end_line"])])
            self.sym_node[(path, c["qualname"])] = key
            self._edge(mod_key, key, "defines", "verified_static", [_ev(path, c["line"], c["end_line"])])
        for f in facts["functions"]:
            sig = f"{'async ' if f['async'] else ''}def {f['qualname']}({', '.join(f['params'])})" + (f" -> {f['returns']}" if f["returns"] else "")
            fl = [sig]
            if f["decorators"]:
                fl.append("Decorators: " + "; ".join("@" + d for d in f["decorators"][:4]))
            if f["doc"]:
                fl.append(f"Docstring: {f['doc'][:200]}")
            key = self._node("function", f"{facts['module']}.{f['qualname']}", f["qualname"], path=path, start=f["line"], end=f["end_line"],
                             facts=fl, meta={"async": f["async"], "class": f["class"], "params": f["params"], "decorators": f["decorators"]},
                             evidence=[_ev(path, f["line"], f["end_line"])])
            self.sym_node[(path, f["qualname"])] = key
            parent_q = f["qualname"].rpartition(".")[0]
            parent = self.sym_node.get((path, parent_q)) if parent_q else None
            self._edge(parent or mod_key, key, "defines", "verified_static", [_ev(path, f["line"], f["end_line"])])
        if facts["dynamic_imports"]:
            for d in facts["dynamic_imports"]:
                if d["literal"] is None:
                    self.gaps.append({"kind": "dynamic_import", "path": path, "line": d["line"], "text": d.get("expr", "")})
                    self._edge(mod_key, self._unresolved(d.get("expr", "dynamic"), "dynamic_import"), "imports", "unresolved",
                               [_ev(path, d["line"])], "dynamic import with a non-literal argument")

    # imports ------------------------------------------------------------------
    def _build_imports(self, path: str) -> None:
        facts = self.by_path[path]
        src = self.module_node[path]
        for imp in facts["imports"]:
            ev = [_ev(path, imp["line"], imp["end_line"])]
            targets: list[tuple[tuple[Any, ...], str]] = []
            if imp["kind"] == "import":
                for n in imp["names"]:
                    targets.append((self._resolve_target(path, n["name"]), n["name"]))
            else:
                base = imp.get("abs_module")
                if base is None:
                    self.gaps.append({"kind": "unresolvable_relative_import", "path": path, "line": imp["line"], "text": "." * imp["level"] + (imp["module"] or "")})
                    self._edge(src, self._unresolved("." * imp["level"] + (imp["module"] or ""), "relative_import"), "imports", "unresolved", ev,
                               "relative import goes above the repository root")
                    continue
                names = [n["name"] for n in imp["names"] if n["name"] != "*"]
                if not names or any(n["name"] == "*" for n in imp["names"]):
                    targets.append((self._resolve_target(path, base) if base else ("unknown", ""), base))
                    if any(n["name"] == "*" for n in imp["names"]):
                        self.gaps.append({"kind": "star_import", "path": path, "line": imp["line"], "text": f"from {base or '.'} import *"})
                for nm in names:
                    targets.append((self._resolve_target(path, f"{base}.{nm}" if base else nm), f"{base}.{nm}" if base else nm))
            for tgt, text in targets:
                kind = tgt[0]
                if kind in {"module", "symbol"}:
                    tpath = tgt[1]
                    if tpath == path:
                        continue
                    amb = tgt[-1] is True
                    self._edge(src, self.module_node[tpath], "imports", "inferred" if amb else "verified_static", ev,
                               f"imports {text}" + (" (ambiguous module name)" if amb else ""))
                elif kind == "external":
                    self._edge(src, self._external(tgt[1]), "imports", "verified_static", ev, f"imports {text}")
                elif kind == "unresolved":
                    self.gaps.append({"kind": "unresolved_import", "path": path, "line": imp["line"], "text": text})
                    self._edge(src, self._unresolved(text, "import"), "imports", "unresolved", ev,
                               "import refers to a repository package but no matching file was found")
        for d in facts["dynamic_imports"]:
            if d["literal"]:
                tgt = self._resolve_target(path, d["literal"])
                if tgt[0] in {"module", "symbol"} and tgt[1] != path:
                    self._edge(src, self.module_node[tgt[1]], "imports", "inferred", [_ev(path, d["line"])], "importlib.import_module with a literal name")
                elif tgt[0] == "external":
                    self._edge(src, self._external(tgt[1]), "imports", "inferred", [_ev(path, d["line"])], "importlib.import_module with a literal name")

    # FastAPI containers & routes ----------------------------------------------
    def _build_containers(self) -> None:
        for path, facts in self.by_path.items():
            for a in facts["apps"]:
                self.containers[(path, a["var"])] = {"kind": "app", "prefix": "", "status": "literal", "line": a["line"], "path": path, "var": a["var"],
                                                    "deps": tuple(d["text"] for d in a.get("dependencies", []))}
            for r in facts["routers"]:
                self.containers[(path, r["var"])] = {"kind": "router", "prefix": r["prefix"] or "", "status": r["prefix_status"] if r["prefix_status"] != "none" else "literal",
                                                    "prefix_expr": r.get("prefix_expr"), "line": r["line"], "path": path, "var": r["var"],
                                                    "deps": tuple(d["text"] for d in r.get("dependencies", []))}

    def _resolve_container(self, path: str, expr: str | None) -> tuple[str, str] | None:
        if not expr:
            return None
        if (path, expr) in self.containers:
            return (path, expr)
        tgt = self._resolve_name(path, expr)
        if tgt[0] == "symbol" and (tgt[1], tgt[2]) in self.containers:
            return (tgt[1], tgt[2])
        return None

    def _build_routes(self) -> None:
        routes_by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for path, facts in self.by_path.items():
            for r in facts["routes"]:
                owner = self._resolve_container(path, r["owner"])
                r = dict(r, _path=path)
                if owner is None:
                    self.gaps.append({"kind": "route_owner_unresolved", "path": path, "line": r["decorator_line"], "text": r["owner"]})
                    continue
                routes_by[owner].append(r)
        includes_by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        included: set[tuple[str, str]] = set()
        for path, facts in self.by_path.items():
            for inc in facts["includes"]:
                parent = self._resolve_container(path, inc["parent"])
                child = self._resolve_container(path, inc["child"])
                if parent is None:
                    continue
                if child is None:
                    self.gaps.append({"kind": "include_router_unresolved", "path": path, "line": inc["line"], "text": inc["child_text"]})
                    self._edge(self.module_node[path], self._unresolved(inc["child_text"], "include_router"), "registers_route", "unresolved",
                               [_ev(path, inc["line"], inc["end_line"])], "include_router target could not be resolved statically")
                    continue
                includes_by[parent].append(dict(inc, _path=path, _child=child))
                included.add(child)

        emitted: set[tuple[Any, ...]] = set()
        route_summaries: list[dict[str, Any]] = []

        def emit(container: tuple[str, str], acc: str, acc_status: str, chain: list[dict[str, Any]], mounted: bool, deps: tuple[str, ...] = ()) -> None:
            cdata = self.containers[container]
            for r in routes_by.get(container, []):
                status = acc_status
                if r["path_status"] == "dynamic":
                    status = "partial"
                    tail = "{?" + (r.get("path_expr") or "dynamic") + "}"
                else:
                    tail = r["path"] or ""
                full = join_path(acc, tail) if (acc or tail) else "/"
                if r["path_status"] == "constant" and status == "verified_static":
                    status = "verified_static"
                for method in r["methods"]:
                    sig = (r["_path"], r["decorator_line"], method, full)
                    if sig in emitted:
                        continue
                    emitted.add(sig)
                    self._emit_route(r, method, full, status, chain, mounted, cdata, route_summaries, deps)

        def walk(container: tuple[str, str], acc: str, acc_status: str, chain: list[dict[str, Any]], seen: frozenset[tuple[str, str]], mounted: bool,
                 deps_in: tuple[str, ...] = ()) -> None:
            here = deps_in + tuple(self.containers[container].get("deps", ()))
            emit(container, acc, acc_status, chain, mounted, here)
            for inc in includes_by.get(container, []):
                child = inc["_child"]
                if child in seen:
                    self.gaps.append({"kind": "router_include_cycle", "path": inc["_path"], "line": inc["line"], "text": inc["child_text"]})
                    continue
                cdata = self.containers[child]
                st = acc_status
                piece = inc["prefix"] or ""
                if inc["prefix_status"] == "dynamic":
                    st = "partial"
                    piece = "{?" + (inc.get("prefix_expr") or "prefix") + "}"
                cprefix = cdata["prefix"]
                if cdata["status"] == "dynamic":
                    st = "partial"
                    cprefix = "{?" + (cdata.get("prefix_expr") or "prefix") + "}"
                step = {"path": inc["_path"], "line": inc["line"], "prefix": inc["prefix"], "child": inc["child_text"]}
                walk(child, join_path(acc, piece, cprefix) if (acc or piece or cprefix) else "", st, chain + [step], seen | {child}, mounted,
                     here + tuple(d["text"] for d in inc.get("dependencies", [])))

        apps = [k for k, v in self.containers.items() if v["kind"] == "app"]
        for app in sorted(apps):
            walk(app, "", "verified_static", [], frozenset({app}), True)
        # routers never reached from an app: still emit, honestly labelled
        reached_cache = {sig[0] for sig in emitted}
        for container in sorted(routes_by):
            cdata = self.containers[container]
            if cdata["kind"] == "app":
                continue
            remaining = [r for r in routes_by[container] if r["_path"] not in {None} and not any(e[0] == r["_path"] and e[1] == r["decorator_line"] for e in emitted)]
            if not remaining:
                continue
            routes_by_tmp = routes_by[container]
            routes_by[container] = remaining
            prefix = cdata["prefix"]
            st = "router_not_mounted" if container not in included or not apps else "router_not_mounted"
            emit(container, prefix, st, [], False, tuple(cdata.get("deps", ())))
            routes_by[container] = routes_by_tmp
        _ = reached_cache
        self._route_summaries = route_summaries

    def _emit_route(self, r: dict[str, Any], method: str, full: str, status: str, chain: list[dict[str, Any]], mounted: bool,
                    cdata: dict[str, Any], summaries: list[dict[str, Any]], inherited: tuple[str, ...] = ()) -> None:
        path = r["_path"]
        facts = self.by_path[path]
        handler_q = r.get("handler")
        handler_key = None
        if handler_q is None and r.get("handler_expr"):
            tgt = self._resolve_name(path, r["handler_expr"])
            if tgt[0] == "symbol":
                handler_path, handler_q = tgt[1], tgt[2]
                handler_key = self.sym_node.get((handler_path, handler_q))
        else:
            handler_key = self.sym_node.get((path, handler_q)) if handler_q else None
        resolution = "verified_static" if status == "verified_static" else "inferred"
        flags = []
        if status == "partial":
            flags.append("Path contains a dynamic segment that could not be resolved statically")
        if status == "router_not_mounted":
            flags.append("Router is not included by any FastAPI app detected statically (may be mounted dynamically)")
        ev_start, ev_end = r["decorator_line"], r["end_line"]
        deps = list(r["dependencies"]) + list(facts["handler_deps"].get(handler_q or "", [])) + self._alias_deps(path, handler_q)
        fl = [f"{method} {full}", f"Handler: `{handler_q or r.get('handler_expr') or '?'}` in `{path}` (line {r['line']})"]
        if r.get("response_model"):
            fl.append(f"response_model: `{r['response_model']}`")
        if deps:
            fl.append("Dependencies: " + ", ".join(f"`{d['text']}`" for d in deps[:6]))
        if chain:
            fl.append("Mounted via: " + " → ".join(f"{c['path']}:{c['line']} include_router({c['child']}, prefix={c['prefix']!r})" for c in chain))
        fl.extend(flags)
        meta = {"method": method, "full_path": full, "path_status": status, "handler": handler_q, "handler_path": path,
                "response_model": r.get("response_model"), "include_chain": chain, "mounted": mounted, "via": r["via"],
                "websocket": r["websocket"], "container": f"{cdata['path']}::{cdata['var']}", "summary": r.get("summary"),
                "dependencies": [d["text"] for d in deps[:10]], "inherited_dependencies": list(inherited)[:10]}
        rkey = self._node("route", f"{method} {full}", f"{method} {full}", path=path, start=ev_start, end=ev_end, facts=fl, meta=meta,
                          evidence=[_ev(path, ev_start, ev_end)] + [_ev(c["path"], c["line"]) for c in chain[:3]])
        self.stats["routes"] += 1
        if handler_key:
            self._edge(handler_key, rkey, "registers_route", resolution, [_ev(path, r["decorator_line"], r["end_line"])],
                       f"{method} {full}" + (" (path partially unresolved)" if status == "partial" else ""))
        else:
            self._edge(self.module_node[path], rkey, "registers_route", "inferred", [_ev(path, r["decorator_line"], r["end_line"])], "handler could not be resolved")
            self.gaps.append({"kind": "route_handler_unresolved", "path": path, "line": r["line"], "text": r.get("handler_expr") or ""})
        # dependencies
        for d in deps:
            self._link_dependency(path, rkey, d)
        # models from response_model / handler refs
        refs: set[str] = set(re.findall(r"[A-Za-z_][\w.]*", r.get("response_model") or ""))
        if handler_q:
            refs |= set(facts["refs"].get(handler_q, []))
        self._link_models(path, rkey, refs, [_ev(path, r["decorator_line"], r["end_line"])])
        summaries.append({"method": method, "path": full, "status": status, "handler": handler_q, "file": path, "line": r["line"],
                          "decorator_line": r["decorator_line"], "end_line": r["end_line"], "key": rkey, "response_model": r.get("response_model"),
                          "mounted": mounted, "chain": chain, "dependencies": [d["text"] for d in deps[:6]]})

    def _link_dependency(self, path: str, src_key: str, dep: dict[str, Any]) -> None:
        ev = [_ev(path, dep["line"])]
        expr = dep.get("expr")
        if not expr:
            self._edge(src_key, self._unresolved(dep["text"], "dependency"), "uses_dependency", "unresolved", ev, "Depends() argument is not a simple name")
            return
        tgt = self._resolve_name(path, expr)
        if tgt[0] == "symbol":
            key = self.sym_node.get((tgt[1], tgt[2]))
            if key:
                self._edge(src_key, key, "uses_dependency", "inferred" if tgt[-1] is True else "verified_static", ev, f"Depends({dep['text']})")
                return
        if tgt[0] == "external":
            self._edge(src_key, self._external(tgt[1]), "uses_dependency", "verified_static", ev, f"Depends({dep['text']})")
            return
        self._edge(src_key, self._unresolved(dep["text"], "dependency"), "uses_dependency", "unresolved", ev, "dependency target could not be resolved")
        self.gaps.append({"kind": "dependency_unresolved", "path": path, "line": dep["line"], "text": dep["text"]})

    def _link_models(self, path: str, src_key: str, refs: set[str], ev: list[dict[str, Any]]) -> None:
        done: set[str] = set()
        for ref in sorted(refs)[:200]:
            tgt = self._resolve_name(path, ref)
            if tgt[0] != "symbol":
                continue
            key = self.sym_node.get((tgt[1], tgt[2]))
            node = self.nodes.get(key) if key else None
            if node and node.type == "model" and key not in done and key != src_key:
                done.add(key)
                self._edge(src_key, key, "uses_model", "verified_static", ev, f"references `{ref}`")

    # calls / refs ---------------------------------------------------------------
    def _build_calls_and_refs(self, path: str) -> None:
        facts = self.by_path[path]
        for f in facts["functions"]:
            src = self.sym_node.get((path, f["qualname"]))
            if not src:
                continue
            for call in facts["calls"].get(f["qualname"], []):
                self._link_call(path, f, src, call)
            if f["qualname"] in facts["refs"]:
                # models referenced anywhere in the function (signature or body)
                self._link_models(path, src, set(facts["refs"][f["qualname"]]), [_ev(path, f["line"], f["end_line"])])
        for c in facts["classes"]:
            src = self.sym_node.get((path, c["qualname"]))
            if src and self.nodes.get(src) and self.nodes[src].type == "model":
                self._link_models(path, src, set(facts["refs"].get(c["qualname"], [])), [_ev(path, c["line"], c["end_line"])])

    def _link_call(self, path: str, f: dict[str, Any], src: str, call: dict[str, Any]) -> None:
        expr = call["expr"]
        ev = [_ev(path, call["line"])]
        head, _, rest = expr.partition(".")
        if head in {"self", "cls"} and rest and "." not in rest and f["class"]:
            key = self.sym_node.get((path, f"{f['class']}.{rest}"))
            if key:
                self._edge(src, key, "calls", "inferred", ev, f"{expr}() — resolved within the same class; subclasses may override")
            return
        tgt = self._resolve_name(path, expr)
        if tgt[0] == "symbol":
            key = self.sym_node.get((tgt[1], tgt[2]))
            if key and key != src:
                node = self.nodes.get(key)
                if node and node.type in {"function", "class", "model"}:
                    amb = tgt[-1] is True
                    self._edge(src, key, "calls", "inferred" if amb else "verified_static", ev, f"{expr}()" + (" — ambiguous module name" if amb else ""))
            elif key is None:
                self.stats["calls_unresolved"] += 1
        elif tgt[0] == "unresolved":
            self.stats["calls_unresolved"] += 1

    # config / workers -------------------------------------------------------------
    def _build_config_and_workers(self, path: str) -> None:
        facts = self.by_path[path]
        mod_key = self.module_node[path]
        seen_cfg: set[str] = set()
        for e in facts["env_vars"]:
            name = e["name"]
            ck = self._node("configuration", f"env:{name}", name, facts=[f"Environment variable `{name}` (value never recorded)"], meta={"kind": "env_var"})
            node = self.nodes.get(ck)
            if node is not None:
                node.evidence = (node.evidence + [_ev(path, e["line"])])[:10]
            if (name, e["line"]) not in {(n, 0) for n in seen_cfg}:
                self._edge(self.sym_node.get((path, e["scope"])) if e.get("scope") and self.sym_node.get((path, e["scope"])) else mod_key,
                           ck, "configured_by", "verified_static", [_ev(path, e["line"])], e["how"])
            seen_cfg.add(name)
        for c in facts["classes"]:
            if self.class_kind.get((path, c["qualname"])) == "pydantic" and any("Settings" in b for b in c["bases"]):
                for fld in c["fields"][:60]:
                    nm = fld["name"].upper()
                    ck = self._node("configuration", f"env:{nm}", nm, facts=[f"Environment variable `{nm}` (value never recorded)"], meta={"kind": "env_var"})
                    node = self.nodes.get(ck)
                    if node is not None:
                        node.evidence = (node.evidence + [_ev(path, fld["line"])])[:10]
                    self._edge(self.sym_node.get((path, c["qualname"]), mod_key), ck, "configured_by", "inferred", [_ev(path, fld["line"])],
                               "settings field (env var name inferred from field name)")
        for w in facts["background"]:
            label = {"fastapi_background_tasks": "FastAPI BackgroundTasks", "celery_task": "Celery task", "celery_app": "Celery app",
                     "rq_enqueue": "RQ enqueue", "dramatiq_actor": "Dramatiq actor", "apscheduler": "APScheduler", "thread": "threading.Thread",
                     "process": "multiprocessing.Process", "asyncio_task": "asyncio task", "startup_hook": "startup hook",
                     "shutdown_hook": "shutdown hook", "lifespan": "ASGI lifespan"}.get(w["kind"], w["kind"])
            qn = f"{facts['module']}:{w['kind']}:{w['line']}"
            fl = [f"{label} detected at {path}:{w['line']}"] + ([f"Target: `{w['target']}`"] if w.get("target") else [])
            wk = self._node("worker", qn, f"{label} @ {PurePosixPath(path).name}:{w['line']}", path=path, start=w["line"], end=w["line"], facts=fl,
                            meta={"kind": w["kind"], "target": w.get("target")}, evidence=[_ev(path, w["line"])])
            scope_key = self.sym_node.get((path, w["scope"])) if w.get("scope") else None
            if w["kind"] in {"celery_task", "dramatiq_actor", "startup_hook", "shutdown_hook"} and w.get("target"):
                scope_key = self.sym_node.get((path, w["target"])) or scope_key
            self._edge(scope_key or mod_key, wk, "starts_worker", "verified_static" if w["kind"] != "thread" or w.get("target") else "inferred",
                       [_ev(path, w["line"])], label)

    # frontend (HTML/CSS/JS/TS) ----------------------------------------------------------
    _WEB_EXTS = (".js", ".mjs", ".ts", ".tsx", ".jsx", ".vue", ".css", ".html", ".htm", ".cjs")

    def _resolve_web_spec(self, from_path: str, spec: str, kind: str) -> tuple[str, str, str]:
        """Return (status, target, resolution): status in web|external|unresolved."""
        if spec.startswith(("http://", "https://", "//", "data:")):
            return "external", spec.split("//", 1)[-1].split("/")[0][:80] or "external", "verified_static"
        if spec.startswith(("@/", "~/", "#")) or (spec.startswith("@") and spec.count("/") == 0):
            return "unresolved", spec, "unresolved"  # path aliases need bundler/tsconfig knowledge
        if not spec.startswith((".", "/")) and kind in ("import", "require", "dynamic"):
            name = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
            return "external", "npm:" + name, "verified_static"
        known = self.web_by_path
        if spec.startswith("/"):
            rel = spec.lstrip("/").split("?")[0]
            cands = [p for p in known if p == rel or p.endswith("/" + rel)] or [p for p in known if any((p == rel + e or p.endswith("/" + rel + e)) for e in self._WEB_EXTS)]
            if cands:
                return "web", sorted(cands, key=lambda p: (len(p), p))[0], "inferred"  # served-path -> file match depends on deployment
            return "unresolved", spec, "unresolved"
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), spec.split("?")[0]))
        for cand in [rel] + [rel + e for e in self._WEB_EXTS] + [rel + "/index" + e for e in (".js", ".ts", ".tsx", ".jsx")]:
            if cand in known:
                return "web", cand, "verified_static"
        return "unresolved", spec, "unresolved"

    @staticmethod
    def _route_regex(path: str) -> re.Pattern[str]:
        segs = []
        for seg in path.strip("/").split("/"):
            m = re.fullmatch(r"\{[^}]*:path\}", seg)
            segs.append(".+" if m else ("[^/]+" if re.fullmatch(r"\{[^}]*\}", seg) else re.escape(seg)))
        return re.compile("^/" + "/".join(segs) + "/?$")

    def _build_web(self) -> None:
        web = self.web_by_path
        stats = {"frontend_files": len(web), "frontend_calls": 0, "frontend_linked": 0, "frontend_ambiguous": 0, "frontend_unresolved": 0, "frontend_external": 0}
        self.stats["web"] = stats
        if not web:
            return
        matchers = [(self._route_regex(r["path"]), r) for r in getattr(self, "_route_summaries", []) if r["status"] != "partial" and "{?" not in r["path"]]
        keys: dict[str, str] = {}
        for path, facts in sorted(web.items()):
            lines = facts["line_count"]
            meta = {"web": True, "language": facts["language"], "calls": [], "sinks": facts.get("sinks", [])[:10], "is_test": False}
            fl = [f"Frontend {facts['language'].upper()} file `{path}` — {lines} lines, {len(facts['calls'])} HTTP call site(s), {len(facts['imports'])} import/reference(s)"]
            key = self._node("module", f"web:{path}", PurePosixPath(path).name, path=path, start=1, end=lines, facts=fl, meta=meta, evidence=[_ev(path, 1, lines)])
            keys[path] = key
            if path in self.file_node:
                self._edge(self.file_node[path], key, "defines", "verified_static", [_ev(path, 1, lines)], "file defines module")
        self.module_node.update(keys)
        for path, facts in sorted(web.items()):
            src, node_meta = keys[path], self.nodes[keys[path]].meta
            for imp in facts["imports"]:
                status, target, res = self._resolve_web_spec(path, imp["spec"], imp["kind"])
                ev = [_ev(path, imp["line"])]
                if status == "web" and target in keys and target != path:
                    self._edge(src, keys[target], "imports", res, ev, f"{imp['kind']} {imp['spec']}" + (" (served path matched by file suffix)" if res == "inferred" else ""))
                elif status == "external":
                    ext = self._external(target)
                    self._edge(src, ext, "imports", res, ev, f"{imp['kind']} {imp['spec']}")
                elif status == "unresolved":
                    self.gaps.append({"kind": "frontend_import_unresolved", "path": path, "line": imp["line"], "text": imp["spec"]})
                    self._edge(src, self._unresolved(imp["spec"], "web_import"), "imports", "unresolved", ev, "import target could not be resolved statically (alias, missing file or non-relative path)")
            for call in facts["calls"]:
                stats["frontend_calls"] += 1
                ev = [_ev(path, call["line"])]
                m, url, kind = call["method"], call["url"], call["url_kind"]
                rec = {"line": call["line"], "client": call["client"], "method": m, "url": url or call["expr"], "url_kind": kind}
                if kind == "external":
                    stats["frontend_external"] += 1
                    host = (url or "").split("//", 1)[-1].split("/")[0]
                    self._edge(src, self._external(host or "external"), "calls_api", "verified_static", ev, f"{call['client']} call to an external host")
                    rec["status"] = "external"
                elif kind in ("dynamic", "relative") or not url:
                    stats["frontend_unresolved"] += 1
                    reason = "URL is computed at runtime" if kind == "dynamic" else "relative URL depends on the page location"
                    self.gaps.append({"kind": "frontend_api_unresolved", "path": path, "line": call["line"], "text": call["expr"]})
                    self._edge(src, self._unresolved(f"{call['client']} {call['expr']}", "api_call"), "calls_api", "unresolved", ev, reason)
                    rec.update(status="unresolved", reason=reason)
                else:
                    probe = url.replace("{}", "PARAM")
                    cands = [r for rx, r in matchers if rx.match(probe)]
                    exact = [r for r in cands if m is None or r["method"] == m]
                    if exact:
                        amb = len(exact) > 1
                        stats["frontend_ambiguous" if amb else "frontend_linked"] += 1
                        note = "path parameter placeholder" if kind == "template" else "literal URL"
                        for r in exact[:5]:
                            self._edge(src, r["key"], "calls_api", "inferred", ev,
                                       f"{call['client']} {m or '?'} {url} matches {r['method']} {r['path']} ({note}{'; ambiguous: ' + str(len(exact)) + ' routes' if amb else ''})")
                        rec.update(status="ambiguous" if amb else "linked", routes=[f"{r['method']} {r['path']}" for r in exact[:5]])
                    else:
                        stats["frontend_unresolved"] += 1
                        reason = (f"path matches {', '.join(r['method'] + ' ' + r['path'] for r in cands[:3])} but not the HTTP method" if cands
                                  else "no FastAPI route matches this URL (it may be served by another service, behind a proxy prefix, or be a static file)")
                        self.gaps.append({"kind": "frontend_api_unresolved", "path": path, "line": call["line"], "text": f"{m or '?'} {url}"})
                        self._edge(src, self._unresolved(f"{m or '?'} {url}", "api_call"), "calls_api", "unresolved", ev, reason)
                        rec.update(status="unresolved", reason=reason)
                if len(node_meta["calls"]) < 60:
                    node_meta["calls"].append(rec)

    # tests ----------------------------------------------------------------------
    def _build_tests(self) -> None:
        tests = {p for p in self.by_path if is_test_path(p)}
        linked: set[tuple[str, str]] = set()
        for e in list(self.edges.values()):
            if e.relation != "imports":
                continue
            s, t = self.nodes.get(e.source), self.nodes.get(e.target)
            if s and t and s.type == "test" and t.type == "module" and s.path in tests:
                self._edge(t.key, s.key, "tested_by", e.resolution, e.evidence, "test module imports this module")
                linked.add((t.path or "", s.path or ""))
        by_stem: dict[str, list[str]] = defaultdict(list)
        for p in self.by_path:
            if p not in tests and PurePosixPath(p).name != "__init__.py":
                by_stem[PurePosixPath(p).stem].append(p)
        for tp in sorted(tests):
            name = PurePosixPath(tp).stem
            stem = name[5:] if name.startswith("test_") else name[:-5] if name.endswith("_test") else None
            if not stem:
                continue
            for mp in by_stem.get(stem, []):
                if (mp, tp) not in linked:
                    self._edge(self.module_node[mp], self.module_node[tp], "tested_by", "inferred", [_ev(tp, 1)], "matched by file name convention")

    # finish ---------------------------------------------------------------------
    def _entry_points(self) -> list[dict[str, Any]]:
        out = []
        for path, node_key in sorted(self.module_node.items()):
            meta = self.nodes[node_key].meta
            for r in meta.get("entry_reasons", []):
                out.append({"path": path, "line": r["line"], "reason": r["reason"], "resolution": r["resolution"]})
        return out

    def _file_summaries(self) -> dict[str, str]:
        out: dict[str, str] = {}
        incoming: dict[str, int] = defaultdict(int)
        for e in self.edges.values():
            if e.relation == "imports":
                t = self.nodes.get(e.target)
                if t and t.path:
                    incoming[t.path] += 1
        routes_by_file: dict[str, int] = defaultdict(int)
        for r in getattr(self, "_route_summaries", []):
            routes_by_file[r["file"]] += 1
        for path, facts in self.by_path.items():
            parts = []
            n_fn = len([f for f in facts["functions"] if "." not in f["qualname"]])
            models = [c["name"] for c in facts["classes"] if (path, c["qualname"]) in self.class_kind]
            plain = [c["name"] for c in facts["classes"] if (path, c["qualname"]) not in self.class_kind and "." not in c["qualname"]]
            if is_test_path(path):
                parts.append("Test module")
            if routes_by_file.get(path):
                parts.append(f"declares {routes_by_file[path]} route(s)")
            if models:
                parts.append(f"defines {len(models)} data model(s): {', '.join(models[:5])}")
            if plain:
                parts.append(f"defines {len(plain)} class(es): {', '.join(plain[:4])}")
            if n_fn:
                parts.append(f"{n_fn} top-level function(s)")
            if facts["apps"]:
                parts.append("creates a FastAPI application")
            if facts["env_vars"]:
                parts.append(f"reads {len({e['name'] for e in facts['env_vars']})} environment variable(s)")
            if incoming.get(path):
                parts.append(f"imported by {incoming[path]} module(s)")
            doc = f" Docstring: {facts['module_doc'][:160]}" if facts.get("module_doc") else ""
            out[path] = ("; ".join(parts).capitalize() + "." if parts else "Python module with no top-level definitions.") + doc
        return out

    def _finish(self) -> GraphResult:
        by_type: dict[str, int] = defaultdict(int)
        for n in self.nodes.values():
            by_type[n.type] += 1
        by_rel: dict[str, int] = defaultdict(int)
        by_res: dict[str, int] = defaultdict(int)
        for e in self.edges.values():
            by_rel[e.relation] += 1
            by_res[e.resolution] += 1
        externals = sorted(n.name for n in self.nodes.values() if n.type == "external_dependency" and not n.meta.get("unresolved"))
        frameworks = sorted({FRAMEWORKS[e] for e in externals if e in FRAMEWORKS})
        stats = {
            "nodes_by_type": dict(by_type), "edges_by_relation": dict(by_rel), "edges_by_resolution": dict(by_res),
            "node_count": len(self.nodes), "edge_count": len(self.edges), "route_count": self.stats["routes"],
            "calls_unresolved": self.stats["calls_unresolved"], "web": self.stats.get("web") or {}, "parse_failed_files": len(self.broken),
            "parse_partial_files": sum(1 for f in self.files if f.facts and any(i["kind"] == "skipped" for i in f.facts.get("parse_issues") or [])),
            "unresolved_edges": by_res.get("unresolved", 0), "inferred_edges": by_res.get("inferred", 0),
            "external_packages": externals[:100], "detected_frameworks": frameworks,
            "node_cap_reached": bool(self.stats["node_cap_reached"]), "edge_cap_reached": bool(self.stats["edge_cap_reached"]),
        }
        sym_index = {f"{p}::{q}": k for (p, q), k in self.sym_node.items()}
        return GraphResult(list(self.nodes.values()), list(self.edges.values()), stats, self.gaps[:500], self._entry_points(),
                           getattr(self, "_route_summaries", []), self._file_summaries(), sym_index)


def build_graph(repo_full_name: str, files: list[FileFacts], all_paths: list[str], support: dict[str, str] | None = None,
                web_files: list[FileFacts] | None = None) -> GraphResult:
    return GraphBuilder(repo_full_name, files, all_paths, support, web_files).build()
