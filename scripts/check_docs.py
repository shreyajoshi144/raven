#!/usr/bin/env python3
"""Documentation consistency check. Fails (exit 1) when documents disagree with each other or with the code.

Checks: markdown links and anchors resolve; the retired screen name is not used; headline numbers (routes, tables, migrations,
workflows, test totals) match the code or the one place they are declared; the management pack's counts and IDs agree; every
file named in the traceability matrix exists. Standard library only:  python3 scripts/check_docs.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTS = {"tests_passed": 490, "web_tests": 6, "legacy_tests": 9, "gates": 22}  # declared once here; the QA report is the narrative source
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def md_files() -> list[Path]:
    out = [ROOT / "README.md", ROOT / "CHANGELOG.md"] + sorted((ROOT / "docs").rglob("*.md"))
    return [p for p in out if "evaluation/results" not in p.as_posix()]


def slug(heading: str) -> str:
    h = re.sub(r"[`*_]", "", heading.strip().lower())
    h = re.sub(r"[^\w\s-]", "", h)
    return re.sub(r"\s", "-", h)


def anchors(p: Path) -> set[str]:
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+)$", p.read_text(), re.M)}


# ---- 1. links and anchors -------------------------------------------------------------------------------------------
for f in md_files():
    text = re.sub(r"```.*?```", "", f.read_text(), flags=re.S)
    for m in re.finditer(r"\]\(([^)\s]+)\)", text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, frag = target.partition("#")
        dest = (f.parent / path).resolve() if path else f
        if not dest.exists():
            err(f"{f.relative_to(ROOT)}: broken link {target}")
        elif frag and dest.suffix == ".md" and frag not in anchors(dest):
            err(f"{f.relative_to(ROOT)}: missing anchor #{frag} in {dest.relative_to(ROOT)}")

# ---- 2. retired name ------------------------------------------------------------------------------------------------
for f in md_files():
    for i, line in enumerate(f.read_text().splitlines(), 1):
        if re.search(r"\batlas\b", line, re.I) and "#/a/{id}/atlas" not in line and "Pre-redesign screen names" not in line:
            err(f"{f.relative_to(ROOT)}:{i}: retired name 'Atlas' used")

# ---- 3. headline numbers --------------------------------------------------------------------------------------------
routes = sum(len(re.findall(r"@router\.(?:get|post|put|delete)\(", p.read_text())) for p in (ROOT / "backend/app/api").glob("routes_*.py"))
tables = len(re.findall(r"__tablename__\s*=", (ROOT / "backend/app/models/entities.py").read_text()))
migrations = len(list((ROOT / "backend/migrations/versions").glob("0*.py")))
workflows = len(list((ROOT / "automation/n8n").glob("*.json")))
actual = {"API routes": routes, "tables": tables, "migrations": migrations, "workflows": workflows, "tests": FACTS["tests_passed"]}
PATTERNS = {"API routes": r"\b(\d+) API routes\b", "tables": r"\b(\d+) (?:database )?tables\b", "migrations": r"\b(\d+) (?:Alembic |reversible )?migrations\b",
            "workflows": r"\b(\d+) (?:n8n )?workflows\b", "tests": r"\b(\d{3}) (?:automated |backend )?tests\b"}
CURRENT = [ROOT / "README.md", ROOT / "docs/PORTFOLIO.md", ROOT / "docs/CASE_STUDY.md", ROOT / "docs/ADMIN_AND_OPERATIONS.md", ROOT / "docs/product/PRODUCT.md",
           ROOT / "docs/architecture/ARCHITECTURE_AND_WORKFLOWS.md", ROOT / "docs/API.md", ROOT / "docs/evaluation/EVALUATION_AND_RESULTS.md"] + sorted((ROOT / "docs/project").glob("*.md"))
HISTORICAL = {ROOT / "docs/project/04-MILESTONES.md"}  # milestone rows quote the test count of their own day
for f in CURRENT:
    text = f.read_text()
    for name, rx in PATTERNS.items():
        if f in HISTORICAL and name == "tests":
            continue
        for m in re.finditer(rx, text):
            n = int(m.group(1))
            ctx = text[max(0, m.start() - 40):m.end() + 10].lower()
            if "sprint" in ctx or "s0" in ctx or "at the time" in ctx or "then" in ctx:
                continue
            if n != actual[name] and not (name == "routes" and n < 10) and not (name == "tests" and n < 100):
                err(f"{f.relative_to(ROOT)}: says {n} {name}, expected {actual[name]}")
for f in CURRENT:
    for m in re.finditer(r"\*\*(\d+) passed\b", f.read_text()):
        if int(m.group(1)) not in (FACTS["tests_passed"], FACTS["web_tests"], FACTS["legacy_tests"]):
            err(f"{f.relative_to(ROOT)}: '{m.group(0)}' is not a current result")

# ---- 4. management pack: counts and IDs -----------------------------------------------------------------------------
P = ROOT / "docs/project"


def ids(path: Path, prefix: str) -> set[str]:
    return set(re.findall(rf"\b({prefix}-\d{{2}})\b", path.read_text()))


def defined(path: Path, prefix: str) -> set[str]:
    return set(re.findall(rf"^\|\s*({prefix}-\d{{2}})\s*\|", path.read_text(), re.M))


risks, decisions, defects, backlog = defined(P / "06-RISK-REGISTER.md", "R"), defined(P / "07-DECISION-LOG.md", "D"), defined(P / "08-QA-REPORT.md", "DEF"), defined(P / "05-PRODUCT-BACKLOG.md", "B")
frs, nfrs = defined(P / "02-PRD.md", "FR"), defined(P / "02-PRD.md", "NFR")
index = (P / "README.md").read_text()
for label, found, rx in (("risks", risks, r"(\d+) risks"), ("decisions", decisions, r"(\d+) key decisions"), ("defects", defects, r"(\d+) defects")):
    m = re.search(rx, index)
    if not m or int(m.group(1)) != len(found):
        err(f"docs/project/README.md: says {m.group(1) if m else 'nothing'} {label}, found {len(found)}")
m = re.search(r"(\d+) functional, (\d+) non-functional", index)
if not m or (int(m.group(1)), int(m.group(2))) != (len(frs), len(nfrs)):
    err(f"docs/project/README.md: requirement counts differ from the PRD ({len(frs)} functional, {len(nfrs)} non-functional)")
trace = P / "09-TRACEABILITY-MATRIX.md"
if defined(trace, "FR") != frs or defined(trace, "NFR") != nfrs:
    err("traceability matrix and PRD list different requirements")
for f in sorted(P.glob("*.md")):
    for prefix, known in (("B", backlog), ("R", risks), ("D", decisions), ("DEF", defects), ("FR", frs), ("NFR", nfrs)):
        for ref in ids(f, prefix):
            if ref not in known:
                err(f"{f.relative_to(ROOT)}: reference to unknown {ref}")

# ---- 5. files named in the traceability matrix exist ----------------------------------------------------------------
for token in sorted(set(re.findall(r"`([\w./]+\.(?:py|mjs|jsx|yml|json|md))`", trace.read_text()))):
    cands = [ROOT / token, ROOT / "backend/tests" / token, ROOT / "backend/app" / token, ROOT / "web/tests" / token, ROOT / "docs" / token]
    if not any(c.exists() for c in cands) and not token.startswith(("scripts/", "..")):
        err(f"traceability matrix names a file that does not exist: {token}")
    if token.startswith("scripts/") and not (ROOT / token).exists():
        err(f"traceability matrix names a file that does not exist: {token}")

# ---- 6. sprint ids --------------------------------------------------------------------------------------------------
sprints = (ROOT / "docs/sprints/SPRINTS.md").read_text()
for n in range(0, 17):
    if not re.search(rf"^## S{n}\b", sprints, re.M):
        err(f"docs/sprints/SPRINTS.md: no section for S{n}")

if errors:
    print("\n".join(sorted(set(errors))))
    print(f"\n{len(set(errors))} documentation problem(s)")
    sys.exit(1)
print(f"documentation consistent: {len(md_files())} files; routes={routes} tables={tables} migrations={migrations} workflows={workflows}")
