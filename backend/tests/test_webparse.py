import time

import pytest

from app.analysis.webparse import classify_url, extract_web_facts, strip_js_comments


def calls(src, path="a.js"):
    return extract_web_facts(path, src)["calls"]


def test_comments_are_ignored_but_strings_with_slashes_are_not():
    src = 'fetch("/real"); // fetch("/c1")\n/* axios.get("/c2") */ const u = "http://x.test/a//b"; fetch(u)'
    assert [c["url"] for c in calls(src)] == ["/real", None]
    assert strip_js_comments(src).count("\n") == src.count("\n")


@pytest.mark.parametrize("arg,url,kind", [
    ('"/api/x"', "/api/x", "literal"), ("'/api/x?q=1#f'", "/api/x", "literal"), ("`/api/x/${id}`", "/api/x/{}", "template"),
    ('"/api/" + name', "/api/{}", "template"), ("buildUrl()", None, "dynamic"), ('"users"', "users", "relative"),
    ('"https://cdn.other.com/x"', "https://cdn.other.com/x", "external"), ('"http://localhost:8000/api/y"', "/api/y", "literal"),
])
def test_url_classification(arg, url, kind):
    u, k, _ = classify_url(arg)
    assert (u, k) == (url, kind)


def test_clients_methods_and_false_positives():
    src = '''
fetch("/a"); fetch("/b", {method: "put"}); axios.get("/c"); axios.post("/d", {}); http.delete("/e"); this.http.patch(`/f/${x}`);
map.get("key"); cache.get("/not-a-client"); $.post("/g"); $.getJSON("/h"); $.ajax({url: "/i", type: "DELETE"});
xhr.open("GET", "/j"); axios({url: "/k", method: "post"}); htmx.ajax("GET", "/not-attr");
'''
    got = {(c["method"], c["url"]) for c in calls(src)}
    assert got >= {("GET", "/a"), ("PUT", "/b"), ("GET", "/c"), ("POST", "/d"), ("DELETE", "/e"), ("PATCH", "/f/{}"), ("POST", "/g"), ("GET", "/h"), ("DELETE", "/i"), ("GET", "/j"), ("POST", "/k")}
    assert not any(u in ("key", "/not-a-client") for _, u in got)


def test_html_forms_htmx_inline_scripts_and_line_numbers():
    html = '<link rel="stylesheet" href="x.css">\n<script src="/s.js"></script>\n<form action="/api/f" method="post"></form>\n<div hx-get="/api/h"></div>\n<script>\n\nfetch("/api/inline")\n</script>'
    f = extract_web_facts("p.html", html)
    by = {c["url"]: c for c in f["calls"]}
    assert by["/api/f"]["method"] == "POST" and by["/api/f"]["client"] == "form" and by["/api/f"]["line"] == 3
    assert by["/api/h"]["client"] == "htmx" and by["/api/inline"]["line"] == 7
    assert {(i["kind"], i["spec"]) for i in f["imports"]} == {("link", "x.css"), ("script", "/s.js")}


def test_imports_and_sinks():
    f = extract_web_facts("a.ts", 'import a from "./a"; import "side"; export * from "../b"; const c = require("c"); import("lazy"); el.innerHTML = x; eval(y); new Function("z");')
    assert {(i["kind"], i["spec"]) for i in f["imports"]} >= {("import", "./a"), ("import", "side"), ("import", "../b"), ("require", "c"), ("dynamic", "lazy")}
    assert {s["kind"] for s in f["sinks"]} == {"innerHTML assignment", "eval", "new Function"}
    assert extract_web_facts("s.css", "@import './x.css'; @import url('y.css');")["imports"][1]["spec"] == "y.css"


def test_script_content_is_never_executed():
    # would hang or throw if evaluated; the extractor only scans text
    f = extract_web_facts("x.js", "while(true){}; throw new Error('boom'); process.exit(1); fetch('/ok')")
    assert [c["url"] for c in f["calls"]] == ["/ok"]


ADVERSARIAL = {
    "nested-fetch": "fetch(" * 6000, "unterminated-string": "fetch('" + "a" * 200000, "template-braces": "`" + "${" * 20000, "deep-parens": "(" * 50000 + ")" * 50000,
    "comment-openers": "/*" * 30000, "long-axios-path": 'axios.get("' + "/a" * 50000 + '")', "many-forms": "<form " * 8000, "many-scripts": "<script>" * 5000,
}


@pytest.mark.parametrize("payload", list(ADVERSARIAL.values()), ids=list(ADVERSARIAL))
def test_adversarial_inputs_stay_fast(payload):
    t = time.process_time()  # CPU time: immune to machine load
    for ext in ("x.js", "x.html", "x.css"):
        extract_web_facts(ext, payload)
    assert time.process_time() - t < 3.0
