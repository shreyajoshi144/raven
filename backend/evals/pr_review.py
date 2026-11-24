"""Pull-request review benchmark (python -m evals pr). Each case = a base tree plus a labelled mutation; Raven's real analysis pipeline runs on both
trees and the real review engine compares them. Scores: expected-kind recall, forbidden-kind violations (false positives), evidence validity
(every cited file exists at the cited commit and the line is inside it) and run-to-run reproducibility. Offline, deterministic, no LLM."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.benchmark import read_tree
from evals.runner import RunConfig, analyze, configure_database, load_artifacts, reset_schema

HERE = Path(__file__).resolve().parent
REAL = HERE / "benchmarks" / "v1" / "repos" / "fastapi_template"


def mutate(base: dict[str, bytes], ops: list[dict[str, Any]]) -> dict[str, bytes]:
    out = dict(base)
    for op in ops:
        if "add" in op:
            out[op["add"]] = op["content"].encode()
        else:
            text = out[op["file"]].decode()
            if "prepend" in op:
                text = op["prepend"] + text
            if "replace" in op:
                assert op["replace"][0] in text, f"mutation target missing in {op['file']}"
                text = text.replace(op["replace"][0], op["replace"][1], 1)
            out[op["file"]] = text.encode()
    return out


def _review(base_files: dict[str, bytes], head_files: dict[str, bytes], name: str) -> dict[str, Any]:
    from app.core.db import new_session
    from app.models import AnalysisJob
    from app.services import pr_review
    b, h = analyze(name, base_files), analyze(name, head_files)
    with new_session() as db:
        rev = pr_review.review(db, db.get(AnalysisJob, b.job_id), db.get(AnalysisJob, h.job_id), {"number": 0, "title": "benchmark", "state": "open", "base_sha": b.commit_sha, "head_sha": h.commit_sha})
    lines = {b.commit_sha: load_artifacts(b.job_id)["line_counts"], h.commit_sha: load_artifacts(h.job_id)["line_counts"]}
    return {"review": rev, "lines": lines}


def run_pr(cfg: RunConfig, repeats: int = 2) -> dict[str, Any]:
    spec = json.loads((HERE / "pr" / "cases.json").read_text())
    configure_database(cfg.db_url)
    if cfg.reset_db:
        reset_schema()
    bases = {"real": (read_tree(REAL), "eval/fastapi-template"), "inline": ({k: v.encode() for k, v in spec["inline_repo"].items()}, "eval/pr-inline")}
    rows, sigs = [], {}
    for case in spec["cases"]:
        base, name = bases[case["base"]]
        runs = [_review(base, mutate(base, case["ops"]), name) for _ in range(repeats)]
        rev, lines = runs[0]["review"], runs[0]["lines"]
        kinds = {f["kind"] for f in rev["findings"]}
        ev = [(e["path"], e["start_line"], e["commit_sha"]) for f in rev["findings"] for e in f["evidence"]]
        bad = [x for x in ev if x[2] not in lines or x[0] not in lines[x[2]] or not 1 <= x[1] <= max(1, lines[x[2]][x[0]])]
        sig = [json.dumps([[f["kind"], f["title"], f["evidence"]] for f in r["review"]["findings"]], sort_keys=True) for r in runs]
        sigs[case["id"]] = len(set(sig)) == 1
        missing = [k for k in case["expect"] if k not in kinds]
        fp = [k for k in case["forbid"] if k in kinds]
        rows.append({"id": case["id"], "kinds": sorted(kinds), "missing_expected": missing, "forbidden_found": fp, "evidence_checked": len(ev), "evidence_invalid": len(bad),
                     "reproducible": sigs[case["id"]], "risk": rev["risk"], "passed": not missing and not fp and not bad and sigs[case["id"]]})
    exp = sum(len(c["expect"]) for c in spec["cases"])
    found = exp - sum(len(r["missing_expected"]) for r in rows)
    return {"suite": spec["name"], "cases": len(rows), "expected_findings": exp, "recall": round(found / exp, 4) if exp else None,
            "forbidden_violations": sum(len(r["forbidden_found"]) for r in rows), "evidence_checked": sum(r["evidence_checked"] for r in rows),
            "evidence_invalid": sum(r["evidence_invalid"] for r in rows), "reproducible_cases": sum(r["reproducible"] for r in rows),
            "cases_passed": sum(r["passed"] for r in rows), "results": rows,
            "note": "Small hand-labelled suite: a regression check for the review engine, not a measure of accuracy on arbitrary pull requests. Precision beyond the listed forbidden kinds was not measured."}
