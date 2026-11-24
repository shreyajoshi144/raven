"""Full browser journey against a live stack: pipeline (with injected GitHub 503s) → overview → atlas (file flow + route trace)
→ files → guide → ask → isolation → delete. Runs the palette/design audit on every main screen."""
import os
import sys
import time
import urllib.request
import uuid
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0, os.path.dirname(__file__))
from palette_audit import audit

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
FAKE = "http://127.0.0.1:9101"
SHOTS = "/tmp/shots"; os.makedirs(SHOTS, exist_ok=True)
results = []


def step(name):
    results.append(name); print("PASS", name, flush=True)


def register(page, email):
    page.goto(BASE + "/#/register")
    page.get_by_label("Email").fill(email); page.get_by_label("Password").fill("correct-horse-battery")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("heading", name="Understand a codebase in minutes.")).to_be_visible()


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type in ("error", "warning") and "status of" not in m.text else None)

    register(page, f"flow-{uuid.uuid4().hex[:6]}@example.com"); step("register + dashboard")

    urllib.request.urlopen(FAKE + "/__control/fail_tarball?n=2").read()
    page.get_by_label("Repository URL").fill("https://github.com/owner/sample"); page.get_by_role("button", name="Analyze").click()
    expect(page.get_by_role("group", name="Analysis progress")).to_be_visible(timeout=15000)
    aid = page.url.split("/a/")[1].split("/")[0].split("?")[0]
    seen_retry, deadline = False, time.time() + 240
    while time.time() < deadline:
        if page.get_by_text("Retrying after a temporary error").count():
            seen_retry = True
        if page.locator(".badge", has_text="Ready").count() or page.get_by_text("Analysis failed.").count():
            break
        time.sleep(0.7)
    expect(page.locator(".badge", has_text="Ready").first).to_be_visible()
    assert seen_retry, "UI never showed RETRYING"
    step("pipeline completed after 2 injected GitHub 503s (RETRYING shown)")
    page.wait_for_timeout(1500)
    expect(page.get_by_text("How far to trust the map")).to_be_visible()
    tl = page.locator(".timeline").inner_text()
    for s in ("FETCHING", "RETRYING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS", "READY"):
        assert s in tl, (s, tl)
    assert page.locator("#glance svg.flow .fnode").count() >= 5, "architecture preview flow missing"
    assert page.locator(".trustbar i.v").evaluate("e => e.getBoundingClientRect().width") > 20, "trust bar did not render"
    page.screenshot(path=f"{SHOTS}/30-overview.png"); audit(page, "overview")
    step("overview: stats, trust bar, architecture preview, full timeline")

    # ---------------- atlas: file flow -----------------
    page.get_by_role("link", name="Map", exact=True).click()
    expect(page.locator(".atlas")).to_be_visible(timeout=20000)
    expect(page.get_by_text("connections").first).to_be_visible(timeout=20000)
    page.wait_for_function("document.querySelectorAll('.atlas svg.flow .fnode').length > 0")
    n_nodes = page.locator("svg.flow .fnode").count(); n_edges = page.locator("svg.flow .edge-g").count()
    assert n_nodes >= 10 and n_edges >= 10, (n_nodes, n_edges)
    assert page.locator("canvas.minimap").count() == 1
    swatch = page.locator(".rchip i").first.evaluate("e => getComputedStyle(e).backgroundColor")
    assert swatch not in ("rgba(0, 0, 0, 0)", ""), "role chip swatch missing"
    page.wait_for_timeout(700); page.screenshot(path=f"{SHOTS}/31-atlas.png"); audit(page, "atlas")
    page.locator("svg.flow .fnode", has_text="users.py").first.click()
    expect(page.get_by_text("Depends on")).to_be_visible()
    assert page.locator("svg.flow .edge-g.hl").count() >= 2 and page.locator("svg.flow .fnode.dim").count() >= 1
    assert "verified" in page.locator(".drawer").inner_text()
    page.screenshot(path=f"{SHOTS}/32-atlas-selected.png"); audit(page, "atlas-selected")
    # keyboard traversal: focus a node, follow a connection with ArrowRight
    page.locator("svg.flow .fnode", has_text="users.py").first.focus(); before = page.locator("svg.flow .fnode.sel").text_content()
    page.keyboard.press("ArrowRight"); page.wait_for_timeout(300)
    assert page.locator("svg.flow .fnode.sel").text_content() != before, "ArrowRight did not move selection"
    page.keyboard.press("Escape")
    step("atlas file flow: nodes+edges+minimap, selection lights up path, keyboard traversal")
    # edge click shows evidence
    page.locator("svg.flow .edge-g").first.dispatch_event("click")
    expect(page.get_by_text("Evidence in the source")).to_be_visible()
    step("edge click shows evidence with source links")
    # role filter hides nodes and re-lays out
    page.get_by_role("button", name="Tests").count()
    before_n = page.locator("svg.flow .fnode").count()
    page.locator(".rchip", has_text="Routes").click(); page.wait_for_timeout(300)
    assert page.locator("svg.flow .fnode").count() < before_n
    page.locator(".rchip", has_text="Routes").click()
    # search dims non-matching
    page.get_by_label("Find a file or symbol").fill("schemas"); page.wait_for_timeout(500)
    assert page.locator("svg.flow .fnode.match").count() >= 1 and page.locator("svg.flow .fnode.dim").count() >= 3
    page.get_by_label("Find a file or symbol").fill("")
    # zoom
    t0 = page.locator("svg.flow .vp").get_attribute("transform"); page.get_by_role("button", name="Zoom in").click()
    assert page.locator("svg.flow .vp").get_attribute("transform") != t0
    step("atlas: role filter re-layout, search highlight, zoom")
    # folder focus
    page.get_by_label("Focus on a folder").select_option("app/api"); page.wait_for_timeout(800)
    assert page.locator("svg.flow .fnode.ctx").count() >= 1 and "app/api" in page.locator("svg.flow").text_content()
    page.get_by_label("Focus on a folder").select_option("")
    step("atlas: folder focus with context nodes")

    # ---------------- atlas: route trace -----------------
    page.get_by_role("button", name="Route trace").click()
    expect(page.locator("svg.flow .fnode", has_text="list_users")).to_be_visible(timeout=20000)
    txt = page.locator("svg.flow").text_content()
    assert "list_users" in txt and "get_db" in txt and "UserOut" in txt
    page.get_by_label("Route to trace").select_option(label="POST /api/users/"); page.wait_for_timeout(900)
    assert "add_user" in page.locator("svg.flow").text_content()
    page.screenshot(path=f"{SHOTS}/33-trace.png"); audit(page, "route-trace")
    page.locator("svg.flow .fnode", has_text="add_user").first.click(); expect(page.get_by_role("button", name="Open source")).to_be_visible()
    step("route trace: handler, dependencies, models, per-route switching")

    # ---------------- files -----------------
    page.get_by_role("link", name="Files").click()
    page.get_by_label("Filter files by path").fill("users.py"); page.wait_for_timeout(700)
    page.locator(".tree-body").get_by_role("button", name="app/api/users.py").click()
    expect(page.get_by_role("region", name="Source of app/api/users.py")).to_be_visible()
    assert "def list_users" in page.locator(".code").inner_text()
    assert page.locator(".code .tk-kw").count() >= 3, "syntax highlighting missing"
    page.wait_for_timeout(1200)
    assert page.locator(".neigh svg.flow .fnode").count() >= 3, "file neighborhood flow missing"
    gh = page.get_by_role("link", name="GitHub").get_attribute("href")
    assert gh.startswith("https://github.com/owner/sample/blob/a1b2c3d4e5f60718293a4b5c6d7e8f9012345678/app/api/users.py"), gh
    page.screenshot(path=f"{SHOTS}/34-files.png"); audit(page, "files")
    page.get_by_label("Filter files by path").fill("user_service"); page.wait_for_timeout(700)
    page.locator(".tree-body").get_by_role("button", name="app/services/user_service.py").click()
    expect(page.get_by_text("secret-like text redacted")).to_be_visible()
    code = page.locator(".code").inner_text(); assert "AKIAABCDEFGHIJKLMNOP" not in code and "[REDACTED]" in code
    page.get_by_label("File kind").select_option(""); page.get_by_label("Filter files by path").fill(".env"); page.wait_for_timeout(700)
    page.locator(".tree-body button", has_text=".env").first.click()
    assert "hunter2" not in page.content() and "supersecretpassword" not in page.content()
    step("files: highlighted source, neighborhood flow, pinned permalink, redaction, .env unreachable")

    # command palette file search
    page.keyboard.press("Control+k"); page.get_by_role("combobox", name="Command palette").fill("deps.py"); page.wait_for_timeout(900)
    page.keyboard.press("ArrowDown") if False else None
    page.get_by_role("option", name="app/deps.py").first.click()
    expect(page.get_by_role("region", name="Source of app/deps.py")).to_be_visible()
    step("command palette: file search → source")

    # ---------------- guide -----------------
    page.get_by_role("link", name="Guide").click()
    expect(page.get_by_role("heading", name="1. Repository overview")).to_be_visible(timeout=15000)
    for n in range(1, 15):
        assert page.locator(f"h2:has-text('{n}. ')").count() >= 1, n
    assert page.locator(".toc a").count() == 16
    expect(page.locator(".diagram svg").first).to_be_visible(timeout=30000)
    assert page.locator(".diagram svg").count() >= 2 and page.get_by_text("AI-generated summary").count() == 1
    page.wait_for_timeout(600); page.screenshot(path=f"{SHOTS}/35-guide.png"); audit(page, "guide")
    page.locator("a.source-link").first.click(); expect(page.get_by_role("region", name="Source of")).to_be_visible()
    r = page.request.get(f"{BASE}/api/v1/analyses/{aid}/docs/download")
    assert r.status == 200 and "attachment" in r.headers["content-disposition"] and "AKIAABCDEFGHIJKLMNOP" not in r.text() and "hunter2" not in r.text()
    step("guide: TOC, 14 sections, Mermaid diagrams (palette-audited), citations → viewer, clean download")

    # ---------------- ask -----------------
    page.goto(f"{BASE}/#/a/{aid}/chat")
    page.get_by_label("Ask a question").fill("What does get_current_user do?"); page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.locator(".bubble", has_text="AI answer")).to_be_visible(timeout=60000); expect(page.locator(".cite").first).to_be_visible()
    page.screenshot(path=f"{SHOTS}/36-chat.png"); audit(page, "chat")
    page.locator(".cite").first.click(); expect(page.get_by_role("region", name="Source of app/deps.py")).to_be_visible()
    page.goto(f"{BASE}/#/a/{aid}/chat")
    page.get_by_label("Ask a question").fill("zzzqq nonexistentthing qqzzz"); page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.get_by_text("insufficient evidence").first).to_be_visible(timeout=60000)
    step("ask: cited answer → source; unanswerable → insufficient evidence")

    # ---------------- isolation + delete -----------------
    other = b.new_context().new_page(); register(other, f"other-{uuid.uuid4().hex[:6]}@example.com")
    for path in ("", "/graph", "/graph/flow", "/files", "/docs", "/chat"):
        assert other.request.get(f"{BASE}/api/v1/analyses/{aid}{path}").status == 404, path
    step("another user gets 404 for every resource, including the new flow endpoints")
    page.goto(f"{BASE}/#/a/{aid}"); page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Delete").click(); expect(page.get_by_text("No analyses yet")).to_be_visible()
    step("delete analysis")
    b.close()
    assert not errors, errors
    print(f"\nFULL FLOW PASSED ({len(results)} checks, palette audit on every main screen)")
