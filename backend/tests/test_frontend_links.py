import pytest

from app.analysis.archive import Limits
from tests.conftest import create_analysis, emulate_n8n
from tests.fakes import FakeLLM
from tests.helpers import analyze


@pytest.fixture(scope="module")
def built():
    return analyze()


def edges(g, rel="calls_api"):
    nm = {n.key: n for n in g.nodes}
    return [(nm[e.source].path, nm[e.target].name, e.resolution, e.label) for e in g.edges if e.relation == rel]


def test_web_files_retained_and_minified_excluded(built):
    g, r, res, _ = built
    kinds = {e.path: (e.kind, e.status, e.excluded_reason) for e in res.entries}
    for p in ("static/index.html", "static/app.js", "static/util.js", "static/style.css"):
        assert kinds[p][:2] == ("web", "analyzed"), p
    assert kinds["static/vendor.min.js"][2] == "generated"
    assert next(e for e in res.entries if e.path == "static/app.js").content.startswith("import { helper }")


def test_api_links_resolved_only_when_statically_matching(built):
    g = built[0]
    ce = edges(g)
    by_label = {(p, n): (res, lab) for p, n, res, lab in ce}
    assert ("static/app.js", "GET /api/users/") in by_label                 # literal GET match
    assert ("static/app.js", "POST /api/users/") in by_label                # axios.post
    assert ("static/app.js", "GET /v1/items/{item_id}") in by_label         # literal id matches path parameter
    assert ("static/index.html", "POST /api/users/") in by_label            # <form method=post>
    unresolved = [(p, n, lab) for p, n, res, lab in ce if res == "unresolved"]
    assert any("not the HTTP method" in lab for _, _, lab in unresolved)    # POST /health vs GET /health
    assert any("no FastAPI route" in lab for _, _, lab in unresolved)       # DELETE /api/users/{} and /inline-missing
    assert any("computed at runtime" in lab for _, _, lab in unresolved)    # fetch(buildUrl())


def test_cross_language_links_are_never_marked_verified(built):
    g = built[0]
    for p, n, res, lab in edges(g):
        if "external host" in lab:
            assert res == "verified_static"                                 # literal absolute URL syntax
        else:
            assert res in ("inferred", "unresolved"), (p, n, res)           # string match / unknown, never "verified"


def test_frontend_imports_and_external_and_aliases(built):
    g = built[0]
    ie = {(p, n, res) for p, n, res, _ in edges(g, "imports") if p and p.startswith("static/")}
    assert ("static/app.js", "util.js", "verified_static") in ie            # relative import resolves to a file
    assert ("static/index.html", "app.js", "inferred") in ie                # /static/app.js served path → suffix match
    assert ("static/style.css", "base.css", "verified_static") in ie
    assert any(n == "npm:react" for _, n, _ in ie)
    kinds = {x["kind"] for x in g.gaps}
    assert "frontend_import_unresolved" in kinds and "frontend_api_unresolved" in kinds   # "@/config" alias + unresolved calls recorded
    web = g.stats["web"]
    assert web["frontend_files"] == 5 and web["frontend_calls"] >= 10 and web["frontend_unresolved"] >= 4 and web["frontend_linked"] >= 4


def test_graph_never_contains_script_text_or_secrets(built):
    blob = repr([(n.facts, n.meta) for n in built[0].nodes])
    assert "innerHTML = text" not in blob and "AKIAABCDEFGHIJKLMNOP" not in blob


def test_web_limits_produce_partial_not_silent_truncation():
    files = {f"w{i}.js": "export const x = 1;\n" for i in range(12)} | {"app.py": "x = 1\n"}
    _, _, res, _ = analyze(files, Limits(max_web_files=5))
    assert sum(1 for e in res.entries if e.kind == "web" and e.status == "analyzed") == 5 and res.partial
    assert any("Frontend file limit" in r for r in res.partial_reasons)
    _, _, res, _ = analyze({"big.js": "a = 1;\n" * 5000, "app.py": "x = 1\n"}, Limits(max_web_file_bytes=1000))
    assert next(e for e in res.entries if e.path == "big.js").excluded_reason == "too_large" and res.partial
    _, _, res, _ = analyze({"a.js": "x=1;\n" * 400, "b.js": "y=1;\n" * 400, "app.py": "x = 1\n"}, Limits(max_web_total_bytes=3000))
    assert any(e.excluded_reason == "web_total_size_limit" for e in res.entries)


def test_minified_and_bundled_variants_are_excluded():
    files = {"a.min.js": "x=1;" * 3000, "chunk.abcdef123456.js": "x=1\n", "lib.bundle.js": "x=1\n", "types.d.ts": "export {}\n", "long.js": "var a=" + "1+" * 2000 + "1;\n", "ok.js": "export const x = 1\n", "app.py": "x = 1\n"}
    _, _, res, _ = analyze(files)
    st = {e.path: e.status for e in res.entries}
    assert st["ok.js"] == "analyzed" and all(st[k] == "excluded" for k in ("a.min.js", "chunk.abcdef123456.js", "lib.bundle.js", "types.d.ts", "long.js"))


def test_secret_in_frontend_file_is_redacted_with_line_numbers_only():
    _, r, res, _ = analyze({"cfg.js": 'const a = 1;\nconst key = "AKIA' + 'ABCDEFGHIJKLMNOP";\n', "app.py": "x = 1\n"})
    e = next(x for x in res.entries if x.path == "cfg.js")
    assert "AKIAABCDEFGHIJKLMNOP" not in e.content and e.redaction_lines == [2]
    f = next(x for x in r["findings"] if x["rule"] == "SEC-SECRET-LIKE-CONTENT")
    assert f["evidence"][0] == {"path": "cfg.js", "start_line": 2, "end_line": 2, "note": "redacted"}


def test_api_flow_and_trace_show_frontend(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    flow = user_client.get(f"/api/v1/analyses/{aid}/graph/flow?limit=100").json()
    fe = [n for n in flow["nodes"] if n["role"] == "frontend"]
    assert {n["path"] for n in fe} >= {"static/app.js", "static/index.html"}
    app_js = next(n for n in fe if n["path"] == "static/app.js")
    assert app_js["counts"]["api"] >= 6
    assert any(e["source"] == app_js["id"] and "calls_api" in e["kinds"] and e["resolution"] != "verified_static" for e in flow["edges"])
    routes = user_client.get(f"/api/v1/analyses/{aid}/graph", params={"types": "route"}).json()["nodes"]
    r = next(x for x in routes if x["name"] == "POST /api/users/")
    t = user_client.get(f"/api/v1/analyses/{aid}/graph/trace", params={"node_id": r["id"]}).json()
    nm = {n["id"]: n for n in t["nodes"]}
    assert any(e["relation"] == "calls_api" and nm[e["source"]]["role"] == "frontend" and e["target"] == r["id"] for e in t["edges"])
    mods = user_client.get(f"/api/v1/analyses/{aid}/graph", params={"types": "module", "q": "static/app.js"}).json()["nodes"]
    t2 = user_client.get(f"/api/v1/analyses/{aid}/graph/trace", params={"node_id": mods[0]["id"]}).json()
    assert {"POST /api/users/", "GET /api/users/"} <= {n["label"] for n in t2["nodes"]}
    files = user_client.get(f"/api/v1/analyses/{aid}/files", params={"kind": "web"}).json()["items"]
    assert {f["path"] for f in files if f["status"] == "analyzed"} >= {"static/app.js", "static/index.html", "static/style.css"}
    detail = user_client.get(f"/api/v1/analyses/{aid}/files/{next(f['id'] for f in files if f['path'] == 'static/app.js')}").json()
    assert "fetch(" in detail["content"] and detail["kind"] == "web"
    md = user_client.get(f"/api/v1/analyses/{aid}/docs").json()["document"]["markdown"]
    assert "## 15. Frontend and API linkage" in md and "inferred, not proven" in md and "## 16. Engineering readiness" in md
