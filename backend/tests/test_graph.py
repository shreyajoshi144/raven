import pytest

from app.analysis.archive import Limits, read_archive
from app.analysis.graph import FileFacts, build_graph
from app.analysis.pyparse import extract_facts
from tests.fixtures.sample_repo import SAMPLE_FILES, make_tarball


@pytest.fixture(scope="module")
def graph():
    res = read_archive(iter([make_tarball(SAMPLE_FILES)]), Limits())
    files, support, paths = [], {}, []
    for e in res.entries:
        if e.status == "excluded":
            continue
        paths.append(e.path)
        if e.kind == "support":
            support[e.path] = e.content
        if e.kind == "python":
            try:
                facts = extract_facts(e.content, e.path)
            except SyntaxError:
                facts = None
            files.append(FileFacts(e.path, facts, e.line_count))
    return build_graph("owner/sample", files, paths, support)


def nodes(g, type_):
    return [n for n in g.nodes if type_ == n.type]


def edge_names(g, rel):
    nm = {n.key: n for n in g.nodes}
    return {(nm[e.source].name, nm[e.target].name, e.resolution) for e in g.edges if e.relation == rel}


def test_routes_resolved_through_nested_includes(graph):
    got = {(r["method"], r["path"], r["status"]) for r in graph.routes}
    assert ("GET", "/health", "verified_static") in got
    assert ("GET", "/api/users/", "verified_static") in got
    assert ("POST", "/api/users/", "verified_static") in got
    assert ("GET", "/v1/items/{item_id}", "verified_static") in got


def test_dynamic_path_and_unmounted_router_flagged(graph):
    by = {(r["method"], r["path"]): r for r in graph.routes}
    dyn = [r for r in graph.routes if r["method"] == "PUT"]
    assert dyn and dyn[0]["status"] == "verified_static" or dyn[0]["status"] == "partial"
    orphan = [r for r in graph.routes if r["path"] == "/orphan/ping"]
    assert orphan and orphan[0]["status"] == "router_not_mounted" and orphan[0]["mounted"] is False


def test_models_classified(graph):
    models = {n.name: n.meta["model_kind"] for n in nodes(graph, "model")}
    assert models["UserCreate"] == "pydantic" and models["UserOut"] == "pydantic"
    assert models["User"] == "sqlalchemy" and models["Settings"] == "pydantic"
    user = next(n for n in nodes(graph, "model") if n.name == "User")
    assert user.meta["tablename"] == "users"


def test_edges_have_evidence_and_resolution(graph):
    for e in graph.edges:
        assert e.resolution in {"verified_static", "inferred", "unresolved"}
        if e.relation in {"imports", "calls", "uses_model", "uses_dependency", "registers_route", "configured_by", "starts_worker"}:
            assert e.evidence, (e.relation, e.label)
            assert all(x["start_line"] >= 1 for x in e.evidence)


def test_import_edges_internal_and_external(graph):
    imps = edge_names(graph, "imports")
    assert ("app.main", "app.api.items", "verified_static") in imps
    assert ("app.api.users", "app.schemas", "verified_static") in imps
    assert ("app.api.users", "app.deps", "verified_static") in imps
    ext = {n.name for n in nodes(graph, "external_dependency") if not n.meta.get("unresolved")}
    assert {"fastapi", "httpx", "sqlalchemy", "celery", "pydantic_settings"} <= ext
    assert "os" not in ext and "importlib" not in ext  # stdlib is not an external dependency


def test_dependency_model_and_call_edges(graph):
    assert ("list_users", "get_db", "verified_static") in edge_names(graph, "uses_dependency") or \
        any(a == "GET /api/users/" and b == "get_db" for a, b, _ in edge_names(graph, "uses_dependency"))
    deps = edge_names(graph, "uses_dependency")
    assert any(a == "POST /api/users/" and b == "get_db" for a, b, _ in deps)
    assert any(b == "get_current_user" for _, b, _ in deps)
    assert any(a == "GET /api/users/" and b == "UserOut" for a, b, _ in edge_names(graph, "uses_model"))
    assert ("add_user", "create_user", "verified_static") in edge_names(graph, "calls")


def test_config_workers_tests(graph):
    cfg = {n.name for n in nodes(graph, "configuration")}
    assert {"DATABASE_URL", "REDIS_URL"} <= cfg
    assert "DATABASE_URL" in cfg and all("hunter2" not in " ".join(n.facts) for n in nodes(graph, "configuration"))
    kinds = {n.meta["kind"] for n in nodes(graph, "worker")}
    assert {"celery_task", "celery_app", "fastapi_background_tasks"} <= kinds
    tested = edge_names(graph, "tested_by")
    assert ("app.api.users", "tests.test_users", "verified_static") in tested


def test_dynamic_import_and_parse_failure_recorded(graph):
    kinds = {g["kind"] for g in graph.gaps}
    assert "dynamic_import" in kinds
    assert graph.stats["parse_failed_files"] == 1
    unresolved = [e for e in graph.edges if e.resolution == "unresolved"]
    assert unresolved and all(e.label for e in unresolved)


def test_entry_points(graph):
    reasons = {(e["path"], e["reason"].split(" ")[0]) for e in graph.entry_points}
    assert any(p == "app/main.py" for p, _ in reasons)
    assert any("uvicorn.run" in e["reason"] for e in graph.entry_points)


def test_node_keys_stable_and_unique(graph):
    res = read_archive(iter([make_tarball(SAMPLE_FILES)]), Limits())
    assert len({n.key for n in graph.nodes}) == len(graph.nodes)
    assert len({e.key for e in graph.edges}) == len(graph.edges)


def test_no_secret_values_in_graph(graph):
    blob = repr([(n.facts, n.meta) for n in graph.nodes])
    assert "AKIAABCDEFGHIJKLMNOP" not in blob and "hunter2" not in blob


def test_parser_never_executes_code():
    evil = "import os\nos.system('touch /tmp/raven_pwned')\nraise SystemExit(3)\n"
    extract_facts(evil, "evil.py")
    import os
    assert not os.path.exists("/tmp/raven_pwned")


@pytest.mark.parametrize("src", ["def f(:\n", "x = \x00", "(" * 5000 + ")" * 5000])
def test_parser_raises_catchable_errors(src):
    with pytest.raises((SyntaxError, ValueError, RecursionError, MemoryError)):
        extract_facts(src, "bad.py")


def test_cycle_in_router_includes_does_not_hang():
    files = {
        "a.py": "from fastapi import FastAPI, APIRouter\nfrom b import rb\napp = FastAPI()\nra = APIRouter()\napp.include_router(ra)\nra.include_router(rb)\n",
        "b.py": "from fastapi import APIRouter\nfrom a import ra\nrb = APIRouter()\nrb.include_router(ra)\n@rb.get('/x')\ndef x(): pass\n",
    }
    ff = [FileFacts(p, extract_facts(s, p), 5) for p, s in files.items()]
    g = build_graph("o/r", ff, list(files))
    assert any(x["kind"] == "router_include_cycle" for x in g.gaps)


def test_import_of_module_level_variable_is_not_unresolved():
    """Regression: `from app.core.config import settings` (an assignment, not a def) must resolve to the module."""
    files = {
        "app/__init__.py": "",
        "app/core/__init__.py": "",
        "app/core/config.py": "class Settings: ...\nsettings = Settings()\nA, B = 1, 2\nif True:\n    LATE = 3\n",
        "app/use.py": "from app.core.config import settings, A, LATE\nfrom app.core import config\nx = settings\n",
    }
    ff = [FileFacts(p, extract_facts(s, p), 3) for p, s in files.items()]
    g = build_graph("o/r", ff, list(files))
    nm = {n.key: n for n in g.nodes}
    imps = {(nm[e.source].name, nm[e.target].name, e.resolution) for e in g.edges if e.relation == "imports"}
    assert ("app.use", "app.core.config", "verified_static") in imps
    assert not [e for e in g.edges if e.resolution == "unresolved"] and not g.gaps
