"""Deterministic onboarding-guide assembly. AI text (if any) is limited to clearly labelled narrative sections;
every table and list below is derived from stored static-analysis facts and carries file/line citations."""
from __future__ import annotations

import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

AUTH_NAME = re.compile(r"(auth|current_user|token|jwt|oauth|login|permission|security|api_key|credential)", re.I)
SERVICE_DIRS = {"services", "service", "core", "crud", "repositories", "repository", "usecases", "use_cases", "domain", "managers", "logic"}
SETUP_CMD = re.compile(r"^\s*\$?\s*(pip|pip3|python -m pip|uv|poetry|pipenv|uvicorn|gunicorn|alembic|pytest|docker|docker-compose|make|npm|cp)\b")


@dataclass
class DocInput:
    repo_full_name: str
    description: str | None
    primary_language: str | None
    default_branch: str
    commit_sha: str
    analyzer_version: str
    analyzed_at: str
    summary: dict[str, Any]
    files: list[dict[str, Any]]  # path, kind, status, line_count, explanation, explanation_source, parse_warning, excluded_reason
    nodes: list[dict[str, Any]]  # id, type, name, qname, path, start, end, facts, meta, explanation
    edges: list[dict[str, Any]]  # source, target, relation, resolution, evidence, label
    support: dict[str, str]
    overview: dict[str, Any] | None = None
    ai_status: str = "unavailable"
    ai_reason: str | None = None


@dataclass
class DocOutput:
    markdown: str
    diagrams: list[dict[str, str]]
    gaps: list[str]


def mm_label(text: str, n: int = 38) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _./:{}\-]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned[: n - 1] + "…") if len(cleaned) > n else (cleaned or "node")


def md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").replace("`", "'")[:200]


class Cite:
    def __init__(self, repo: str, sha: str):
        self.repo, self.sha = repo, sha

    def __call__(self, path: str, start: int | None = None, end: int | None = None) -> str:
        label = f"{path}:{start}-{end}" if start and end and end != start else (f"{path}:{start}" if start else path)
        anchor = f"#L{start}-L{end}" if start and end and end != start else (f"#L{start}" if start else "")
        return f"[`{label}`](https://github.com/{self.repo}/blob/{self.sha}/{path}{anchor})"


def _first_ev(edge_or_node: dict[str, Any]) -> dict[str, Any] | None:
    ev = edge_or_node.get("evidence") or []
    return ev[0] if ev else None


def parse_declared_dependencies(support: dict[str, str]) -> tuple[list[dict[str, str]], str | None]:
    deps: list[dict[str, str]] = []
    py_req = None
    for path, text in sorted(support.items()):
        name = PurePosixPath(path).name.lower()
        if name.startswith("requirements") and name.endswith(".txt"):
            for i, line in enumerate(text.splitlines(), 1):
                line = line.split("#")[0].strip()
                if not line or line.startswith(("-", "git+", "http")):
                    continue
                m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)$", line)
                if m:
                    deps.append({"name": m.group(1), "spec": m.group(3)[:40], "path": path, "line": str(i)})
        elif name == "pyproject.toml":
            try:
                data = tomllib.loads(text)
            except Exception:  # noqa: BLE001
                continue
            proj = data.get("project", {})
            py_req = proj.get("requires-python") or data.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python") or py_req
            for d in proj.get("dependencies", []) or []:
                m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)$", str(d))
                if m:
                    deps.append({"name": m.group(1), "spec": m.group(3)[:40], "path": path, "line": "1"})
            for k, v in (data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}).items():
                if k.lower() != "python":
                    deps.append({"name": k, "spec": v if isinstance(v, str) else "", "path": path, "line": "1"})
    seen, out = set(), []
    for d in deps:
        key = d["name"].lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out, py_req


def _readme_commands(support: dict[str, str]) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    for path, text in sorted(support.items()):
        if not PurePosixPath(path).name.lower().startswith("readme"):
            continue
        in_code = False
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code and SETUP_CMD.match(line) and len(line) < 160:
                out.append((line.strip().lstrip("$ ").strip(), path, i))
            if len(out) >= 12:
                return out
    return out


def _compose_and_docker(support: dict[str, str]) -> list[tuple[str, str, int]]:
    out = []
    for path, text in sorted(support.items()):
        low = PurePosixPath(path).name.lower()
        if low.startswith("dockerfile") or low.startswith(("docker-compose", "compose")):
            for i, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                if re.match(r"^(CMD|ENTRYPOINT)\b", s) or re.match(r"^command\s*:", s):
                    out.append((s[:160], path, i))
    return out[:10]


def build_docs(inp: DocInput) -> DocOutput:
    cite = Cite(inp.repo_full_name, inp.commit_sha)
    nodes = {n["id"]: n for n in inp.nodes}
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in inp.nodes:
        by_type[n["type"]].append(n)
    out_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    in_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in inp.edges:
        out_edges[e["source"]].append(e)
        in_edges[e["target"]].append(e)
    files = {f["path"]: f for f in inp.files}
    py_files = [f for f in inp.files if f["kind"] == "python" and f["status"] in ("analyzed", "parse_error")]
    gaps: list[str] = []
    summary = inp.summary
    L: list[str] = []
    diagrams: list[dict[str, str]] = []
    ai_note = {"ok": "", "partial": "_Some AI explanations were unavailable; those items show deterministic summaries only._",
               "unavailable": f"_AI explanations are unavailable ({inp.ai_reason or 'not configured'}); this guide contains deterministic, evidence-derived content only._"}

    # ---- 1 overview
    L.append(f"# Onboarding guide: {inp.repo_full_name}\n")
    L.append("## 1. Repository overview\n")
    L.append(f"- **Repository:** https://github.com/{inp.repo_full_name}")
    if inp.description:
        L.append(f"- **Description (from GitHub):** {md_cell(inp.description)}")
    L.append(f"- **Analyzed commit:** `{inp.commit_sha}` (default branch `{inp.default_branch}`)")
    L.append(f"- **Analyzer version:** {inp.analyzer_version} — analyzed {inp.analyzed_at}")
    inv = summary.get("inventory", {})
    L.append(f"- **Coverage:** {inv.get('files_considered', 0)} files inspected, {inv.get('python_analyzed', 0)} Python files analyzed, "
             f"{summary.get('parse', {}).get('failed', 0)} failed to parse")
    if summary.get("partial"):
        L.append("- **⚠ Partial analysis:** " + "; ".join(summary.get("partial_reasons", [])))
        gaps.extend(summary.get("partial_reasons", []))
    L.append("")
    if inp.overview:
        L.append("**AI-generated summary** (validated against analyzed files; verify against the cited code):\n")
        L.append(md_cell_block(inp.overview["overview"]))
        for flow in inp.overview.get("key_flows", []):
            L.append(f"- {md_cell(flow)}")
        if inp.overview.get("citations"):
            L.append("\nSources: " + ", ".join(cite(c["path"], c["start_line"], c["end_line"]) for c in inp.overview["citations"][:6]))
        L.append("")
    elif ai_note.get(inp.ai_status):
        L.append(ai_note[inp.ai_status] + "\n")

    # ---- 2 technology
    L.append("## 2. Technology and dependency summary\n")
    graph_stats = summary.get("graph", {})
    fw = graph_stats.get("detected_frameworks", [])
    L.append("- **Frameworks/libraries detected from imports:** " + (", ".join(fw) if fw else "none of the tracked frameworks detected"))
    declared, py_req = parse_declared_dependencies(inp.support)
    if py_req:
        L.append(f"- **Declared Python requirement:** `{md_cell(py_req)}`")
    if declared:
        L.append("\n| Declared dependency | Spec | Declared in |\n|---|---|---|")
        for d in declared[:40]:
            L.append(f"| {md_cell(d['name'])} | {md_cell(d['spec'])} | {cite(d['path'], int(d['line']))} |")
        if len(declared) > 40:
            L.append(f"\n_{len(declared) - 40} more declared dependencies not shown._")
    else:
        L.append("- No `requirements*.txt` or `pyproject.toml` dependency declarations were found among analyzed files.")
    exts = sorted([n for n in by_type["external_dependency"] if not n["meta"].get("unresolved")], key=lambda n: -len(in_edges[n["id"]]))
    if exts:
        L.append("\n**Most-imported external packages (from import statements):** " + ", ".join(f"`{n['name']}` ({len(in_edges[n['id']])})" for n in exts[:15]))
    L.append("")

    # ---- 3 directory/module map
    L.append("## 3. Directory and module map\n")
    dirs: dict[str, list[str]] = defaultdict(list)
    for f in py_files:
        parent = str(PurePosixPath(f["path"]).parent)
        dirs["(root)" if parent == "." else parent].append(f["path"])
    L.append("| Directory | Python files | Notes |\n|---|---|---|")
    for d, paths in sorted(dirs.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:40]:
        L.append(f"| `{md_cell(d)}` | {len(paths)} | {md_cell(', '.join(PurePosixPath(p).name for p in sorted(paths)[:5]))}{'…' if len(paths) > 5 else ''} |")
    mods = [n for n in by_type["module"] if not n["meta"].get("web")]
    imported_by = {n["id"]: len([e for e in in_edges[n["id"]] if e["relation"] == "imports"]) for n in mods}
    L.append("\n**Key modules** (most imported by other modules):\n")
    L.append("| Module | File | Imported by | Summary | Source |\n|---|---|---|---|---|")
    for n in sorted(mods, key=lambda n: (-imported_by[n["id"]], n["path"] or ""))[:25]:
        f = files.get(n["path"] or "", {})
        tag = "AI" if f.get("explanation_source") == "ai" else "static"
        L.append(f"| `{md_cell(n['name'])}` | {cite(n['path'], 1, f.get('line_count'))} | {imported_by[n['id']]} | {md_cell(f.get('explanation') or '')} _({tag})_ | |")
    L.append("")

    # ---- 4 entry points
    L.append("## 4. Application entry points and startup path\n")
    eps = summary.get("entry_points", [])
    if eps:
        L.append("| Entry point | Reason | Resolution |\n|---|---|---|")
        for ep in eps[:20]:
            L.append(f"| {cite(ep['path'], ep['line'])} | {md_cell(ep['reason'])} | {ep['resolution']} |")
    else:
        L.append("No FastAPI application object, `__main__` block, or conventional entry-point file was detected statically.")
    cmds = _compose_and_docker(inp.support)
    if cmds:
        L.append("\n**Container/start commands found in repository files (not executed by Raven):**\n")
        for text, path, line in cmds:
            L.append(f"- `{md_cell(text)}` — {cite(path, line)}")
    app_nodes = [n for n in mods if any(r["reason"].startswith("creates FastAPI app") for r in n["meta"].get("entry_reasons", []))]
    if app_nodes:
        L.append("\n**Startup path (static):** " + "; ".join(
            f"`{n['name']}` creates the app" + (" and mounts routers (see §5 for resulting paths)" if any(r["mounted"] for r in summary.get("routes_summary", [])) else "")
            for n in app_nodes[:3]) + ".")
    L.append("")

    # ---- 5 routes
    routes = sorted(by_type["route"], key=lambda n: (n["meta"].get("full_path", ""), n["meta"].get("method", "")))
    L.append("## 5. API routes\n")
    if routes:
        L.append("| Method | Path | Handler | Source | Resolution |\n|---|---|---|---|---|")
        for r in routes[:250]:
            m = r["meta"]
            flag = {"verified_static": "verified", "partial": "path partially unresolved", "router_not_mounted": "router not mounted statically"}.get(m["path_status"], m["path_status"])
            L.append(f"| {m['method']} | `{md_cell(m['full_path'])}` | `{md_cell(m.get('handler') or '?')}` | {cite(r['path'], r['start'], r['end'])} | {flag} |")
        if len(routes) > 250:
            L.append(f"\n_{len(routes) - 250} more routes not shown._")
        if any(r["meta"]["path_status"] != "verified_static" for r in routes):
            gaps.append("Some route paths are partial or belong to routers not mounted statically.")
    else:
        L.append("No FastAPI route registrations were detected statically.")
    L.append("")

    # ---- 6 services
    L.append("## 6. Core services and responsibilities\n")
    route_files = {r["path"] for r in routes}
    candidates = []
    for n in mods:
        p = PurePosixPath(n["path"] or "")
        in_service_dir = any(part.lower() in SERVICE_DIRS for part in p.parts[:-1])
        if (in_service_dir or imported_by[n["id"]] >= 2) and n["path"] not in route_files and p.name != "__init__.py":
            candidates.append(n)
    if candidates:
        L.append("_Heuristic selection (directory names and import counts); treat as inferred._\n")
        L.append("| Module | Imported by | Responsibility | Source |\n|---|---|---|---|")
        for n in sorted(candidates, key=lambda n: -imported_by[n["id"]])[:20]:
            f = files.get(n["path"] or "", {})
            L.append(f"| `{md_cell(n['name'])}` | {imported_by[n['id']]} | {md_cell(f.get('explanation') or '')} | {cite(n['path'], 1, f.get('line_count'))} |")
    else:
        L.append("No service-layer modules were identified by the static heuristics.")
    L.append("")

    # ---- 7 data models
    L.append("## 7. Data models and persistence relationships\n")
    models = by_type["model"]
    sa = [m for m in models if m["meta"].get("model_kind") == "sqlalchemy"]
    pyd = [m for m in models if m["meta"].get("model_kind") == "pydantic"]
    if sa:
        L.append("**SQLAlchemy/SQLModel models**\n")
        L.append("| Model | Table | Columns/relationships | Source |\n|---|---|---|---|")
        for m in sorted(sa, key=lambda m: m["qname"])[:50]:
            L.append(f"| `{md_cell(m['name'])}` | `{md_cell(m['meta'].get('tablename') or '—')}` | {md_cell(', '.join(m['meta'].get('columns', [])[:12]) or '—')} | {cite(m['path'], m['start'], m['end'])} |")
    if pyd:
        L.append("\n**Pydantic models**\n")
        L.append("| Model | Fields | Source |\n|---|---|---|")
        for m in sorted(pyd, key=lambda m: m["qname"])[:60]:
            fl = ", ".join(f"{f['name']}: {f['type']}" for f in m["meta"].get("fields", [])[:8])
            L.append(f"| `{md_cell(m['name'])}` | {md_cell(fl or '—')} | {cite(m['path'], m['start'], m['end'])} |")
    rel = [e for e in inp.edges if e["relation"] == "uses_model" and nodes[e["source"]]["type"] == "model"]
    if rel:
        L.append("\n**Model-to-model references:** " + "; ".join(f"`{nodes[e['source']]['name']}` → `{nodes[e['target']]['name']}`" for e in rel[:20]))
    if not models:
        L.append("No Pydantic or SQLAlchemy models were detected statically.")
    L.append("")

    # ---- 8 auth
    L.append("## 8. Authentication and authorization\n")
    auth_funcs = [n for n in by_type["function"] if AUTH_NAME.search(n["name"]) and any(e["relation"] == "uses_dependency" for e in in_edges[n["id"]])]
    auth_ext = [n for n in exts if n["name"] in {"jwt", "jose", "passlib", "authlib", "fastapi_users", "itsdangerous", "bcrypt", "argon2"}]
    sec_deps = [e for e in inp.edges if e["relation"] == "uses_dependency" and nodes[e["target"]]["type"] == "external_dependency" and nodes[e["target"]]["name"] == "fastapi"
                and re.search(r"Security|OAuth2|HTTPBearer|APIKey|HTTPBasic", e.get("label") or "")]
    if auth_funcs or auth_ext or sec_deps:
        L.append("_Detected by naming conventions and imports; this is inferred, not proof of enforcement._\n")
        for n in auth_funcs[:10]:
            users = [nodes[e["source"]] for e in in_edges[n["id"]] if e["relation"] == "uses_dependency"]
            L.append(f"- Dependency `{n['name']}` ({cite(n['path'], n['start'], n['end'])}) is used by {len(users)} route(s)/function(s)")
        for n in auth_ext[:6]:
            L.append(f"- Auth-related package imported: `{n['name']}`")
        for e in sec_deps[:6]:
            ev = _first_ev(e)
            if ev:
                L.append(f"- FastAPI security dependency: {md_cell(e.get('label') or '')} — {cite(ev['path'], ev['start_line'])}")
    else:
        L.append("No authentication or authorization mechanism was detected statically.")
    L.append("")

    # ---- 9 integrations & background
    L.append("## 9. External integrations and background jobs\n")
    integ = [n for n in exts if n["meta"].get("category") and n["meta"]["category"] not in {"database"}]
    if integ:
        L.append("| Package | Category (by name) | Imported in |\n|---|---|---|")
        for n in integ[:20]:
            mods_using = sorted({nodes[e["source"]]["path"] or "" for e in in_edges[n["id"]] if e["relation"] == "imports"})
            ev0 = next((_first_ev(e) for e in in_edges[n["id"]] if e["relation"] == "imports"), None)
            L.append(f"| `{n['name']}` | {n['meta']['category']} | {md_cell(', '.join(mods_using[:3]))}{'…' if len(mods_using) > 3 else ''} {cite(ev0['path'], ev0['start_line']) if ev0 else ''} |")
    else:
        L.append("No well-known external service clients were detected from imports.")
    workers = by_type["worker"]
    if workers:
        L.append("\n**Background work / workers**\n")
        for w in workers[:25]:
            L.append(f"- {md_cell(w['name'])} — {cite(w['path'], w['start'])}" + (f" (target `{md_cell(w['meta'].get('target'))}`)" if w["meta"].get("target") else ""))
    else:
        L.append("\nNo background task or worker mechanisms were detected statically.")
    L.append("")

    # ---- 10 flows
    L.append("## 10. Important request and data flows\n")
    arch = architecture_mermaid(nodes, out_edges, in_edges, by_type)
    if arch:
        L.append("**Module architecture (static imports; unresolved relationships are omitted here and listed in §14)**\n")
        L.append("```mermaid\n" + arch + "\n```\n")
        diagrams.append({"title": "Module architecture", "mermaid": arch})
    shown = 0
    for r in routes:
        if shown >= 5:
            break
        flow = route_flow_mermaid(r, nodes, out_edges)
        if flow:
            shown += 1
            L.append(f"**{r['meta']['method']} `{md_cell(r['meta']['full_path'])}`** — handler {cite(r['path'], r['start'], r['end'])}\n")
            L.append("```mermaid\n" + flow + "\n```\n")
            diagrams.append({"title": f"{r['meta']['method']} {r['meta']['full_path']}", "mermaid": flow})
    if not arch and shown == 0:
        L.append("Not enough static evidence to draw request flows.")
    L.append("_Call edges show statically resolvable function calls only; runtime behavior (dependency injection, dynamic dispatch) may differ._\n")

    # ---- 11 config
    L.append("## 11. Configuration variables\n")
    cfgs = sorted(by_type["configuration"], key=lambda n: n["name"])
    template = {}
    for path, text in inp.support.items():
        if PurePosixPath(path).name.lower() in {".env.example", ".env.sample", ".env.template", ".env.dist", "env.example"}:
            for i, line in enumerate(text.splitlines(), 1):
                if "=" in line:
                    template[line.split("=")[0].strip()] = (path, i)
    if cfgs or template:
        L.append("Names only — values are never recorded.\n")
        L.append("| Variable | Consumed in | In env template |\n|---|---|---|")
        names = {n["name"]: n for n in cfgs}
        for name in sorted(set(names) | set(template))[:120]:
            n = names.get(name)
            cons = ", ".join(cite(ev["path"], ev["start_line"]) for ev in (n["evidence"][:3] if n else []))
            tm = template.get(name)
            L.append(f"| `{md_cell(name)}` | {cons or '—'} | {cite(tm[0], tm[1]) if tm else '—'} |")
    else:
        L.append("No environment variable access or env template was detected statically.")
    L.append("")

    # ---- 12 tests
    L.append("## 12. Tests\n")
    tests = by_type["test"]
    L.append(f"{len(tests)} test file(s) detected. _Raven does not run tests; nothing here claims they pass._\n")
    if tests:
        L.append("| Test file | Covers (by import/name) | Resolution |\n|---|---|---|")
        for t in sorted(tests, key=lambda n: n["path"] or "")[:40]:
            covered = [(nodes[e["source"]]["name"], e["resolution"]) for e in in_edges[t["id"]] if e["relation"] == "tested_by"]
            res = "verified_static" if any(r == "verified_static" for _, r in covered) else ("inferred" if covered else "—")
            L.append(f"| {cite(t['path'], 1)} | {md_cell(', '.join(m for m, _ in covered[:5]) or '—')} | {res} |")
    L.append("")

    # ---- 13 setup
    L.append("## 13. Local setup (only what repository files support)\n")
    present = [p for p in inp.support if PurePosixPath(p).name.lower() in {"pyproject.toml", "setup.py", "setup.cfg", "pipfile"} or PurePosixPath(p).name.lower().startswith(("requirements", "dockerfile", "docker-compose", "compose", "makefile", "alembic"))]
    if present:
        L.append("Setup-related files present: " + ", ".join(cite(p, 1) for p in sorted(present)[:12]))
    cmds2 = _readme_commands(inp.support)
    if cmds2:
        L.append("\n**Commands copied verbatim from README code blocks — UNVERIFIED, not executed by Raven:**\n")
        for c, p, i in cmds2:
            L.append(f"- `{md_cell(c)}` — {cite(p, i)}")
    if not present and not cmds2:
        L.append("No setup instructions could be derived from repository files. Setup steps are unknown.")
    L.append("")

    # ---- 14 gaps
    L.append("## 14. Known analysis gaps\n")
    exc = inv.get("excluded_by_reason", {})
    if exc:
        L.append("**Excluded files (by reason):** " + ", ".join(f"{k}: {v}" for k, v in sorted(exc.items())))
    if inv.get("redacted_files"):
        L.append(f"- {inv['redacted_files']} file(s) contained text that matched secret-like patterns; matches were redacted. Screening is best-effort, not perfect.")
    parse_fail = [f for f in inp.files if f["status"] == "parse_error"]
    if parse_fail:
        L.append(f"- {len(parse_fail)} Python file(s) could not be parsed: " + ", ".join(f"`{md_cell(f['path'])}` ({md_cell(f.get('parse_warning') or '')})" for f in parse_fail[:8]))
        gaps.append(f"{len(parse_fail)} Python file(s) failed to parse.")
    gp = summary.get("gaps", [])
    kinds = Counter(g["kind"] for g in gp)
    names = {"dynamic_import": "dynamic imports with non-literal arguments", "unresolved_import": "imports that look internal but matched no file",
             "include_router_unresolved": "include_router targets that could not be resolved", "dependency_unresolved": "Depends() targets that could not be resolved",
             "star_import": "wildcard imports", "route_owner_unresolved": "route decorators on objects that could not be resolved",
             "route_handler_unresolved": "route handlers that could not be resolved", "unresolvable_relative_import": "relative imports above the repo root",
             "router_include_cycle": "router include cycles", "partial_parse": "statements that could not be parsed and were left out"}
    for k, v in kinds.most_common():
        L.append(f"- {v} × {names.get(k, k)}")
    for g in gp[:25]:
        L.append(f"  - {cite(g['path'], g['line'])} — `{md_cell(g.get('text') or '')}` ({g['kind']})")
    if gp:
        gaps.append("Unresolved dynamic patterns exist; see §14.")
    L.append(f"- {summary.get('graph', {}).get('calls_unresolved', 0)} call expression(s) on internally-bound names could not be resolved to a definition.")
    L.append("- Static analysis cannot determine runtime behavior: decorator aliases, dynamic imports, reflection, dependency injection and runtime-generated routes may be missing or incomplete.")
    L.append("- `calls` edges are limited to statically resolvable names; they are not a complete call graph.")
    L.append("")
    # ---- 15 frontend / API linkage
    L.append("## 15. Frontend and API linkage\n")
    webs = sorted([n for n in by_type["module"] if n["meta"].get("web")], key=lambda n: n["path"] or "")
    if not webs:
        L.append("No HTML/CSS/JS/TS frontend files were found among the analyzed files.")
    else:
        w = summary.get("graph", {}).get("web", {})
        L.append(f"{len(webs)} frontend file(s); {w.get('frontend_calls', 0)} HTTP call site(s): {w.get('frontend_linked', 0)} matched to one route, {w.get('frontend_ambiguous', 0)} ambiguous, "
                 f"{w.get('frontend_unresolved', 0)} unresolved, {w.get('frontend_external', 0)} to external hosts.\n")
        L.append("> Links are made by matching URL strings in frontend code to FastAPI route paths. They are **inferred, not proven**: a reverse-proxy prefix, another backend or a different base URL can change the real target. Calls whose URL is computed at runtime are listed as unresolved rather than guessed.\n")
        rows = []
        for n in webs:
            for c in n["meta"].get("calls", []):
                res = {"linked": "→ " + ", ".join(c.get("routes", [])), "ambiguous": "⚠ ambiguous: " + ", ".join(c.get("routes", [])), "external": "external host", "unresolved": "unresolved: " + c.get("reason", "")}[c["status"]]
                rows.append(f"| {cite(n['path'], c['line'])} | {md_cell(c['client'])} | `{md_cell((c.get('method') or '?') + ' ' + str(c.get('url') or ''))}` | {md_cell(res)} | {'inferred' if c['status'] in ('linked', 'ambiguous') else ('verified' if c['status'] == 'external' else 'unresolved')} |")
        if rows:
            L.append("| Call site | Client | Request | Result | Resolution |\n|---|---|---|---|---|")
            L.extend(rows[:80])
            if len(rows) > 80:
                L.append(f"\n_{len(rows) - 80} more call sites not shown._")
        else:
            L.append("No outgoing HTTP call sites were detected in the frontend files.")
        gaps.append("Frontend→API links are string matches (inferred).") if rows else None
    L.append("")

    # ---- 16 engineering readiness
    L.append("## 16. Engineering readiness (summary)\n")
    rd = summary.get("readiness")
    if not rd:
        L.append("Not available: this analysis predates the readiness report. Re-run the analysis to generate it.")
    else:
        L.append(f"> {rd['disclaimer']}\n")
        sv = rd["summary"]["by_severity"]
        L.append("**Findings:** " + ", ".join(f"{sv.get(k, 0)} {k}" for k in ("critical", "high", "medium", "low", "info")) + ". Severity is the impact if the concern is real; confidence is how sure Raven is that the pattern is what it says.\n")
        top = rd["findings"][:12]
        if top:
            L.append("| Severity | Confidence | Category | Finding | Evidence |\n|---|---|---|---|---|")
            for f in top:
                ev = f["evidence"][0] if f["evidence"] else None
                L.append(f"| {f['severity']} | {f['confidence']} | {f['category'].replace('_', ' ')} | {md_cell(f['title'])} _({f['kind'].replace('_', ' ')})_ | {cite(ev['path'], ev['start_line'], ev.get('end_line')) if ev else 'absence — ' + md_cell(f.get('basis', ''))[:90]} |")
        L.append("\nThe Health tab lists every finding with its evidence, a recommendation and how to verify it. Not assessed: " + "; ".join(rd["not_assessed"][:4]) + ".")
    L.append("")
    return DocOutput("\n".join(L), diagrams, sorted(set(gaps)))


def md_cell_block(text: str) -> str:
    return "\n".join("> " + line for line in text.strip().splitlines()) + "\n"


def architecture_mermaid(nodes: dict[str, Any], out_edges: dict[str, list], in_edges: dict[str, list], by_type: dict[str, list]) -> str:
    mods = [n for n in by_type["module"] if not n["meta"].get("web")]
    if not mods:
        return ""
    score = {}
    route_paths = {r["path"] for r in by_type["route"]}
    for n in mods:
        imp = len([e for e in in_edges[n["id"]] if e["relation"] == "imports"])
        bonus = (6 if any(r["reason"].startswith("creates FastAPI") for r in n["meta"].get("entry_reasons", [])) else 0) + (3 if n["path"] in route_paths else 0)
        bonus += 2 if any(c["type"] == "model" for c in [nodes[e["target"]] for e in out_edges[n["id"]] if e["relation"] == "defines"]) else 0
        score[n["id"]] = imp + bonus
    chosen = sorted(mods, key=lambda n: (-score[n["id"]], n["path"] or ""))[:18]
    ids = {n["id"]: f"m{i}" for i, n in enumerate(chosen)}
    lines = ["flowchart LR"]
    for n in chosen:
        shape = f'{ids[n["id"]]}["{mm_label(n["name"])}"]'
        lines.append("  " + shape)
    seen = set()
    for n in chosen:
        for e in out_edges[n["id"]]:
            if e["relation"] == "imports" and e["target"] in ids and e["resolution"] != "unresolved":
                k = (ids[n["id"]], ids[e["target"]])
                if k not in seen:
                    seen.add(k)
                    lines.append(f"  {k[0]} --> {k[1]}")
    ext_ids: dict[str, str] = {}
    for n in chosen:
        for e in out_edges[n["id"]]:
            t = nodes[e["target"]]
            if e["relation"] == "imports" and t["type"] == "external_dependency" and not t["meta"].get("unresolved") and t["meta"].get("category"):
                if len(ext_ids) < 8 or t["id"] in ext_ids:
                    eid = ext_ids.setdefault(t["id"], f"x{len(ext_ids)}")
                    lines.append(f"  {ids[n['id']]} -.-> {eid}")
    for tid, eid in ext_ids.items():
        lines.append(f'  {eid}[("{mm_label(nodes[tid]["name"])}")]')
    return "\n".join(lines) if len(lines) > 1 else ""


def route_flow_mermaid(route: dict[str, Any], nodes: dict[str, Any], out_edges: dict[str, list]) -> str:
    handler = None
    # registers_route is handler -> route; find incoming via scanning out_edges of all (cheap: nodes small)
    for nid, es in out_edges.items():
        for e in es:
            if e["relation"] == "registers_route" and e["target"] == route["id"] and nodes[nid]["type"] == "function":
                handler = nodes[nid]
    lines = ["flowchart LR", f'  c(["Client"]) --> r["{mm_label(route["meta"]["method"] + " " + route["meta"]["full_path"], 44)}"]']
    n = 0
    if handler is None:
        return ""
    lines.append(f'  r --> h["{mm_label(handler["name"])}"]')
    for e in out_edges.get(route["id"], []):
        if e["relation"] == "uses_dependency" and e["resolution"] != "unresolved" and n < 6:
            n += 1
            lines.append(f'  r -.->|depends| d{n}["{mm_label(nodes[e["target"]]["name"])}"]')
    for e in out_edges.get(handler["id"], []):
        t = nodes[e["target"]]
        if e["relation"] == "calls" and n < 12:
            n += 1
            lines.append(f'  h -->|calls| f{n}["{mm_label(t["name"])}"]')
        elif e["relation"] == "uses_model" and n < 12:
            n += 1
            lines.append(f'  h -.->|references| o{n}[("{mm_label(t["name"])}")]')
    return "\n".join(lines) if len(lines) > 3 else ""
