"""Browser checks that need no workflow engine: auth flow, validation, queued state, status page, CSP cleanliness, palette audit."""
import os
import sys
import uuid
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0, os.path.dirname(__file__))
from palette_audit import audit

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SHOTS = "/tmp/shots"; os.makedirs(SHOTS, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    problems = []
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") and "status of" not in m.text else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))

    page.goto(BASE + "/")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    assert page.url.endswith("#/login"), page.url
    page.wait_for_timeout(400)
    assert page.evaluate("document.fonts.check('16px Inter') && document.fonts.check('14px \"JetBrains Mono\"')"), "vendored fonts did not load"
    audit(page, "login")
    page.get_by_label("Email").fill("nobody@example.com"); page.get_by_label("Password").fill("not-the-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("Email or password is incorrect.")).to_be_visible()
    audit(page, "login-error")

    page.goto(BASE + "/#/register")
    page.get_by_label("Email").fill(f"ui-{uuid.uuid4().hex[:6]}@example.com"); page.get_by_label("Password").fill("short")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_text("at least 10 characters")).to_be_visible()
    page.get_by_label("Password").fill("correct-horse-battery"); page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("heading", name="Understand a codebase in minutes.")).to_be_visible()
    expect(page.get_by_text("No analyses yet")).to_be_visible()
    page.screenshot(path=f"{SHOTS}/20-dashboard.png"); audit(page, "dashboard-empty")

    for bad in ["https://evil.example.com/a/b", "https://github.com/a/b/tree/main"]:
        page.get_by_label("Repository URL").fill(bad); page.get_by_role("button", name="Analyze").click()
        expect(page.get_by_text("Invalid repository URL")).to_be_visible()
    audit(page, "dashboard-error")
    page.get_by_label("Repository URL").fill("https://github.com/owner/missing"); page.get_by_role("button", name="Analyze").click()
    expect(page.get_by_text("Repository not found")).to_be_visible()
    page.get_by_label("Repository URL").fill("https://github.com/owner/private"); page.get_by_role("button", name="Analyze").click()
    expect(page.get_by_text("not public")).to_be_visible()

    page.get_by_label("Repository URL").fill("https://github.com/owner/sample"); page.get_by_role("button", name="Analyze").click()
    expect(page.get_by_role("heading", name="owner/sample")).to_be_visible()
    expect(page.get_by_role("group", name="Analysis progress")).to_be_visible()
    assert page.locator(".tabs a[aria-disabled=true]").count() == 4
    page.screenshot(path=f"{SHOTS}/21-queued.png"); audit(page, "analysis-active")

    page.goto(BASE + "/#/status")
    expect(page.get_by_role("heading", name="System status")).to_be_visible(); audit(page, "status")
    page.keyboard.press("Control+k"); expect(page.get_by_role("dialog", name="Command palette")).to_be_visible()
    page.get_by_role("combobox", name="Command palette").fill("status"); page.keyboard.press("Enter"); expect(page.get_by_role("heading", name="System status")).to_be_visible()
    page.goto(BASE + "/#/")
    assert page.locator("script").count() == 1
    page.get_by_role("button", name="Sign out").click(); expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    page.goto(BASE + "/#/"); expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    b.close()
    assert not problems, problems
    print("BASIC UI CHECKS PASSED")
