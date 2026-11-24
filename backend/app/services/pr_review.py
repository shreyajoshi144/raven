"""Pull-request intelligence. Both commits of the PR are analysed like any other commit; the review is the comparison of the two analyses:
architecture drift (services/architecture.py), new readiness findings, risky areas and untested changed modules. Every finding and every
comment cites file/lines/commit from those analyses. Nothing is posted to GitHub and no LLM is involved, so a review is reproducible."""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import AnalysisJob, CodeEdge, CodeNode, PrReview, utcnow
from app.services import architecture as arch
from app.services.areas import AREAS, area_of
from app.services.incremental import diff_files, file_hashes

SENSITIVE = re.compile(r"(^|/)(auth|security|permissions?|payments?|billing|crypto|secrets?|tokens?|session|login|oauth)[^/]*(/|\.py$)", re.I)
SEV = {"critical": 0, "high": 0, "medium": 1, "low": 2, "info": 3}
LIMITATIONS = arch.LIMITATIONS + [
    "The change set is the difference between the two analysed commits (file content hashes), restricted to files Raven analyses (Python and supported web files).",
    "'New readiness finding' compares (rule, file) pairs, so a finding that moves to another file is reported as new and a second instance in the same file is not.",
    "'Untested' means no test imports the module and no test matches it by file name; test coverage was not measured and no test was run.",
    "Review comments are generated from templates over the findings. They are not posted to GitHub by Raven; copy them from the markdown view.",
    "Pull requests from forks are not supported, and only public repositories are analysed.",
]


WHY = {
    "breaking_route_removed": ("route", "removed route(s): anything that still calls them will start failing", "A removed endpoint breaks clients (the frontend, other services) that still call it."),
    "breaking_symbol_removed": ("function", "removed function(s) that other code still mentions", "Other modules import this and refer to its name, so they may fail at runtime."),
    "breaking_signature_changed": ("function", "function(s) whose parameters changed", "Existing callers pass the old parameters and may need updating."),
    "new_cycle": ("circular import", "new circular import(s) between modules", "Modules that import each other are harder to change and can fail at start-up."),
    "new_dependency": ("package", "new external package(s) added", "New dependencies add maintenance and security surface."),
    "boundary_violation": ("import", "import(s) that break the project's layering", "A lower layer reaching into a higher one makes the structure harder to follow."),
    "coupling_increase": ("module", "module(s) that now depend on many more modules", "The more a file depends on, the more likely a change elsewhere breaks it."),
    "complexity_growth": ("module", "module(s) that became noticeably more complex", "Complex code is harder to review and more likely to hide bugs."),
    "new_readiness_finding": ("issue", "new engineering-readiness issue(s) in the changed files", "Raven's static checks found a pattern (for example a secret-like value or missing error handling)."),
    "sensitive_area_changed": ("file", "change(s) in security-sensitive files (auth, sessions, payments)", "Mistakes here have a bigger effect, so they deserve a slower read."),
    "missing_tests": ("module", "changed module(s) with no linked test", "Nothing in the test suite appears to exercise this code."),
}
LEVELS = {
    "review_closely": ("Review closely", "high", "Raven found changes that commonly break other code. Check the items below before merging."),
    "review_normally": ("Worth a careful read", "medium", "Nothing looks broken, but a few changes deserve a second look."),
    "quick_look": ("Looks routine", "low", "Raven found no structural problems in this change."),
}


def _verdict(findings: list[dict[str, Any]]) -> dict[str, Any]:
    level = "review_closely" if any(f["severity"] in ("high", "critical") for f in findings) else "review_normally" if any(f["severity"] == "medium" for f in findings) else "quick_look"
    order = {"high": 0, "critical": 0, "medium": 1, "low": 2, "info": 3}
    kinds: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(findings, key=lambda f: order[f["severity"]]):
        kinds.setdefault(f["kind"], []).append(f)
    reasons = []
    for k, fs in kinds.items():
        if k in WHY and fs[0]["severity"] != "low" and len(reasons) < 3:
            reasons.append({"kind": k, "count": len(fs), "severity": fs[0]["severity"], "text": f"{len(fs)} {WHY[k][1]}"})
    head, risk, sub = LEVELS[level]
    return {"level": level, "headline": head, "risk": risk, "summary": sub, "reasons": reasons}


def _areas_changed(ch: dict[str, Any], mods_meta: dict[str, bool]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    def add(path: str, how: str) -> None:
        a = area_of(path, None, mods_meta.get(path, False))
        slot = out.setdefault(a, {"area": a, "label": AREAS[a]["label"], "blurb": AREAS[a]["blurb"], "added": 0, "modified": 0, "deleted": 0, "files": []})
        slot[how] += 1
        if len(slot["files"]) < 8:
            slot["files"].append({"path": path, "change": how})
    for p in ch["added"]:
        add(p, "added")
    for p in ch["modified"]:
        add(p, "modified")
    for p in ch["deleted"]:
        add(p, "deleted")
    for r in ch["renamed"]:
        add(r["to"], "modified")
    return sorted(out.values(), key=lambda x: -(x["added"] + x["modified"] + x["deleted"]))


def _ev(path: str, start: int | None, end: int | None, sha: str) -> dict[str, Any]:
    return {"path": path, "start_line": start or 1, "end_line": end or start or 1, "commit_sha": sha}


def _tested_by_name(db: Session, analysis_id: uuid.UUID) -> set[str]:
    mods = {n.id: n.path for n in db.execute(select(CodeNode).where(CodeNode.analysis_id == analysis_id, CodeNode.type == "module")).scalars()}
    return {mods[e.source_id] for e in db.execute(select(CodeEdge).where(CodeEdge.analysis_id == analysis_id, CodeEdge.relation == "tested_by")).scalars()
            if e.source_id in mods and mods[e.source_id]}


def review(db: Session, base: AnalysisJob, head: AnalysisJob, pr: dict[str, Any]) -> dict[str, Any]:
    d = arch.drift(db, base, head)
    hs = head.commit_sha
    ch = diff_files(file_hashes(db, base.id), file_hashes(db, head.id))
    hsnap = arch.snapshot(db, head)
    mods = set(hsnap["modules"])
    changed_head = sorted((set(ch["added"]) | set(ch["modified"]) | {r["to"] for r in ch["renamed"]}) & mods)
    findings = [f for f in d["findings"] if f["severity"] != "info"]  # info-level drift (resolved cycles, removed deps, new routes) stays in the drift view
    # new readiness findings
    old = {(f["rule"], f["evidence"][0]["path"]) for f in ((base.summary or {}).get("readiness") or {}).get("findings", []) if f.get("evidence")}
    for f in ((head.summary or {}).get("readiness") or {}).get("findings", []):
        if not f.get("evidence") or f["severity"] not in ("critical", "high", "medium") or f["kind"] not in ("observed", "potential_risk"):
            continue
        key = (f["rule"], f["evidence"][0]["path"])
        if key not in old and f["evidence"][0]["path"] in set(ch["added"]) | set(ch["modified"]) | {r["to"] for r in ch["renamed"]}:
            findings.append({"kind": "new_readiness_finding", "severity": "high" if f["severity"] == "critical" else f["severity"], "title": f["title"], "detail": f["claim"] + " " + f["detail"],
                             "evidence": [_ev(e["path"], e.get("start_line"), e.get("end_line"), hs) for e in f["evidence"][:3]],
                             "resolution": "verified_static" if f["confidence"] == "high" else "inferred"})
    # risky areas touched (name heuristic, so inferred)
    for p in changed_head:
        if SENSITIVE.search(p) and not p.startswith("tests/"):
            findings.append({"kind": "sensitive_area_changed", "severity": "medium", "title": f"Change touches a sensitive area: {p}", "detail": "File path matches auth/security/payment/crypto naming; review it with extra care.",
                             "evidence": [_ev(p, 1, None, hs)], "resolution": "inferred"})
    # changed modules with no linked test
    tested = _tested_by_name(db, head.id) | {m for m, ts in hsnap["tests_importing"].items() if ts}
    missing = []
    for p in changed_head:
        if p.endswith("__init__.py") or p in tested or hsnap["complexity"].get(p, 0) == 0:
            continue
        syms = sorted((s for s in hsnap["symbols"].values() if s["path"] == p), key=lambda s: s["line"])[:3]
        new = p in ch["added"]
        missing.append({"path": p, "added": new, "symbols": [s["name"] for s in syms], "evidence": [_ev(s["path"], s["line"], s["end_line"], hs) for s in syms] or [_ev(p, 1, None, hs)]})
        findings.append({"kind": "missing_tests", "severity": "medium" if new else "low", "title": f"{'New' if new else 'Changed'} module has no linked test: {p}",
                         "detail": "No test imports it and none matches its file name." + (f" Public functions: {', '.join(s['name'] for s in syms)}." if syms else ""),
                         "evidence": missing[-1]["evidence"], "resolution": "verified_static"})
    findings.sort(key=lambda f: (SEV[f["severity"]], f["kind"], f["title"]))
    seen, comments = set(), []
    for f in findings:
        if not f["evidence"]:
            continue
        e = f["evidence"][-1] if f["kind"] == "breaking_signature_changed" else f["evidence"][0]
        key = (e["path"], e["start_line"], f["kind"])
        if key in seen:
            continue
        seen.add(key)
        side = "head" if e["commit_sha"] == hs else "base"
        comments.append({"path": e["path"], "line": e["start_line"], "side": side, "commit_sha": e["commit_sha"], "severity": f["severity"], "kind": f["kind"], "resolution": f["resolution"],
                         "body": f"**{f['title']}**\n\n{f['detail']}\n\nEvidence: `{e['path']}:{e['start_line']}` @ `{e['commit_sha'][:7]}` ({'verified by static analysis' if f['resolution'] == 'verified_static' else 'inferred, heuristic'})."})
    for f in findings:
        f["why"] = WHY.get(f["kind"], ("", "", ""))[2]
        f["area"] = area_of(f["evidence"][0]["path"]) if f.get("evidence") else None
    verdict = _verdict(findings)
    risk = verdict["risk"]
    web = {n.path: True for n in db.execute(select(CodeNode).where(CodeNode.analysis_id == head.id, CodeNode.type == "module")).scalars() if n.path and (n.meta or {}).get("web")}
    areas_changed = _areas_changed(ch, web)
    nfiles = len(ch["added"]) + len(ch["modified"]) + len(ch["deleted"]) + len(ch["renamed"])
    routes_added = [f["title"] for f in d["findings"] if f["kind"] == "route_added"]
    what = (f"Changes {nfiles} file(s): {len(ch['added'])} added, {len(ch['modified'])} modified, {len(ch['deleted'])} deleted"
            + (f", mostly in {areas_changed[0]['label']}" if areas_changed else "") + (f". Adds {len(routes_added)} new route(s)" if routes_added else "") + ".")
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    tests_changed = [p for p in set(ch["added"]) | set(ch["modified"]) if p.startswith("tests/") or "/tests/" in p or p.split("/")[-1].startswith("test_")]
    return {"pr": pr, "risk": risk, "verdict": verdict, "what_it_does": what, "areas_changed": areas_changed, "summary": {"counts": counts, "findings": len(findings), "files_added": len(ch["added"]), "files_modified": len(ch["modified"]), "files_deleted": len(ch["deleted"]),
                                                "files_renamed": len(ch["renamed"]), "test_files_changed": len(tests_changed)},
            "changed_files": {k: ch[k][:200] for k in ("added", "modified", "deleted", "renamed")}, "findings": findings[:100], "missing_tests": missing[:50], "comments": comments[:60],
            "metrics": d["metrics"], "predicted_impact": d["predicted_impact"], "base": d["base"], "head": d["head"], "limitations": LIMITATIONS, "computed_at": utcnow().isoformat()}


def refresh(db: Session, pr: PrReview) -> PrReview:
    """PENDING -> READY (both analyses finished) or FAILED. Idempotent; the stored result is never recomputed once READY."""
    if pr.status == "READY" and pr.result and "verdict" not in pr.result:  # stored before the plain-language verdict: recompute from the two analyses
        base, head = (db.get(AnalysisJob, i) if i else None for i in (pr.base_analysis_id, pr.head_analysis_id))
        if base is not None and head is not None and base.state == "READY" and head.state == "READY":
            pr.result = review(db, base, head, {"number": pr.pr_number, "title": pr.title, "state": pr.pr_state, "base_sha": pr.base_sha, "head_sha": pr.head_sha})
            pr.updated_at = utcnow()
        return pr
    if pr.status != "PENDING":
        return pr
    base, head = (db.get(AnalysisJob, i) if i else None for i in (pr.base_analysis_id, pr.head_analysis_id))
    if base is None or head is None or base.state in ("FAILED", "CANCELLED") or head.state in ("FAILED", "CANCELLED"):
        pr.status, pr.error_code = "FAILED", "PR_ANALYSIS_FAILED"
    elif base.state == "READY" and head.state == "READY":
        pr.result = review(db, base, head, {"number": pr.pr_number, "title": pr.title, "state": pr.pr_state, "base_sha": pr.base_sha, "head_sha": pr.head_sha})
        pr.status = "READY"
    pr.updated_at = utcnow()
    return pr


def to_dict(db: Session, pr: PrReview, repo_full_name: str) -> dict[str, Any]:
    def st(i):
        j = db.get(AnalysisJob, i) if i else None
        return {"analysis_id": str(i) if i else None, "state": j.state if j else None, "progress": (j.progress or {}) if j else {}}
    return {"id": str(pr.id), "repository": repo_full_name, "number": pr.pr_number, "title": pr.title, "pr_state": pr.pr_state, "base_sha": pr.base_sha, "head_sha": pr.head_sha,
            "status": pr.status, "error": ({"code": pr.error_code} if pr.error_code else None), "base": st(pr.base_analysis_id), "head": st(pr.head_analysis_id),
            "url": f"https://github.com/{repo_full_name}/pull/{pr.pr_number}", "created_at": pr.created_at.isoformat(), "review": pr.result}


def markdown(pr: dict[str, Any]) -> str:
    r = pr["review"]
    if not r:
        raise ApiError("INVALID_STATE", "The review is not ready yet.")
    out = [f"# Raven review: {pr['repository']}#{pr['number']} — {pr['title']}", "",
           f"Review priority: **{r['verdict']['headline'] if r.get('verdict') else r['risk']}** · base `{pr['base_sha'][:7]}` → head `{pr['head_sha'][:7]}` · {r['summary']['findings']} finding(s)", ""]
    for c in r["comments"]:
        out += [f"### `{c['path']}:{c['line']}` — {c['severity']}", c["body"], ""]
    if not r["comments"]:
        out.append("No evidence-backed findings.")
    out += ["", "_Limitations:_"] + [f"- {x}" for x in r["limitations"]]
    return "\n".join(out)
