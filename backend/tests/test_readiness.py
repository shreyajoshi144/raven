import json
import re

import pytest

from app.analysis.readiness import CONF, SEV, _Builder
from tests.conftest import create_analysis, emulate_n8n, new_other_client
from tests.fakes import FakeLLM
from tests.helpers import analyze

SECRETS = ["AKIAABCDEFGHIJKLMNOP", "hard-coded-secret-value-1", "hunter2"]


@pytest.fixture(scope="module")
def built():
    return analyze()


def rules(r):
    return {f["rule"] for f in r["findings"]}


def test_expected_rules_fire_on_known_patterns(built):
    expected = {"EH-BARE-EXCEPT", "EH-SWALLOWED-BROAD", "SEC-SHELL-EXEC", "SEC-SQL-STRING-BUILD", "SEC-TLS-VERIFY-DISABLED", "SEC-YAML-LOAD", "SEC-WEAK-HASH",
                "SEC-HARDCODED-SECRET-DEFAULT", "SEC-SECRET-LIKE-CONTENT", "LOG-PRINT", "SEC-DOM-SINK"}
    assert expected <= rules(built[1]), expected - rules(built[1])


def test_every_pattern_finding_has_valid_evidence_and_absence_has_basis(built):
    _, r, res, lines = built
    for f in r["findings"]:
        assert f["severity"] in SEV and f["confidence"] in CONF and f["category"] and f["recommendation"] and f["verify"] and f["claim"]
        if f["kind"] == "absence":
            assert f.get("basis") and f["evidence"] == []
            continue
        assert f["evidence"], f["rule"]
        for ev in f["evidence"]:
            assert ev["path"] in lines, (f["rule"], ev)
            assert 1 <= ev["start_line"] <= ev["end_line"] <= max(lines[ev["path"]], 1), (f["rule"], ev, lines[ev["path"]])


def test_findings_sorted_by_severity_then_confidence(built):
    keys = [(SEV.index(f["severity"]), CONF.index(f["confidence"])) for f in built[1]["findings"]]
    assert keys == sorted(keys)


def test_security_findings_are_never_presented_as_confirmed(built):
    r = built[1]
    assert {f["kind"] for f in r["findings"]} <= {"observed", "potential_risk", "absence", "coverage_gap", "metric"}
    for f in r["findings"]:
        if f["category"] == "security" and f["kind"] == "potential_risk":
            assert "NOT verified" in f["claim"]
        assert not re.search(r"confirmed (vulnerab|exploit)", json.dumps(f), re.I) or "NOT" in f["claim"]
    assert "not that a vulnerability is confirmed" in r["disclaimer"].lower() and r["not_assessed"]


def test_secret_values_never_appear_in_report(built):
    blob = json.dumps(built[1])
    for s in SECRETS:
        assert s not in blob


def test_pattern_finding_without_evidence_is_dropped_and_absence_requires_basis():
    b = _Builder()
    b.add("X", "security", "high", "high", "potential_risk", "t", "d", "r", "v", [])
    b.add("Y", "logging", "low", "low", "absence", "t", "d", "r", "v", [])
    assert b.findings == []
    b.add("Y", "logging", "low", "low", "absence", "t", "d", "r", "v", [], basis="searched N files")
    assert len(b.findings) == 1


def test_test_reachability_is_import_based_and_labelled_as_such(built):
    g, r, _, _ = built
    gap = next(f for f in r["findings"] if f["rule"] == "TEST-UNREACHED-ROUTER")
    assert gap["kind"] == "coverage_gap" and "not measured coverage" in gap["detail"]
    paths = {e["path"] for e in gap["evidence"]}
    assert "app/api/users.py" not in paths          # imported by tests/test_users.py
    assert "Measured coverage was not collected" in gap["claim"]


def test_no_tests_is_an_absence_finding_with_basis_and_partial_lowers_confidence():
    files = {"app/__init__.py": "", "app/a.py": "def f():\n    return 1\n", "app/b.py": "def g():\n    return 2\n", "app/c.py": "def h():\n    return 3\n"}
    f = next(x for x in analyze(files)[1]["findings"] if x["rule"] == "TEST-NONE")
    assert f["kind"] == "absence" and f["confidence"] == "high" and "analyzed Python files" in f["basis"]
    f2 = next(x for x in analyze(files, partial=True)[1]["findings"] if x["rule"] == "TEST-NONE")
    assert f2["confidence"] == "medium" and "partial" in f2["basis"]


def test_import_cycle_detected_with_evidence():
    files = {"pkg/__init__.py": "", "pkg/a.py": "from pkg import b\n\n\ndef fa():\n    return b.fb()\n", "pkg/b.py": "from pkg import a\n\n\ndef fb():\n    return a.fa()\n"}
    f = next(x for x in analyze(files)[1]["findings"] if x["rule"] == "MAINT-IMPORT-CYCLE")
    assert f["confidence"] == "high" and {e["path"] for e in f["evidence"]} == {"pkg/a.py", "pkg/b.py"}


def test_secret_default_is_detected_after_redaction_rewrites_the_value():
    r = analyze({"app/__init__.py": "", "app/cfg.py": 'SECRET_KEY = "AKIA' + 'ABCDEFGHIJKLMNOP"\nOTHER = 1\n'})[1]
    f = next(x for x in r["findings"] if x["rule"] == "SEC-HARDCODED-SECRET-DEFAULT")
    assert f["evidence"][0]["path"] == "app/cfg.py" and f["severity"] == "high" and "AKIA" not in json.dumps(r)


def test_clean_code_produces_no_security_findings():
    files = {"app/__init__.py": "", "app/a.py": "import logging\n\nlog = logging.getLogger(__name__)\n\n\ndef f(x):\n    try:\n        return int(x)\n    except ValueError:\n        log.exception('bad')\n        raise\n"}
    r = analyze(files)[1]
    assert not [f for f in r["findings"] if f["category"] == "security"]


def test_unparsable_files_are_reported_not_hidden():
    r = analyze({"app/ok.py": "x = 1\n", "app/bad.py": "def (:\n"})[1]
    f = next(x for x in r["findings"] if x["rule"] == "MAINT-PARSE-FAILURES")
    assert f["evidence"][0]["path"] == "app/bad.py"


def test_unauth_mutation_respects_router_level_dependencies():
    files = {"app/__init__.py": "", "app/main.py": '''from fastapi import APIRouter, Depends, FastAPI


def get_current_user():
    return 1


app = FastAPI()
guarded = APIRouter(dependencies=[Depends(get_current_user)])
open_r = APIRouter()


@guarded.post("/safe")
def safe():
    return 1


@open_r.post("/open")
def open_():
    return 1


app.include_router(guarded)
app.include_router(open_r)
'''}
    r = analyze(files)[1]
    f = next(x for x in r["findings"] if x["rule"] == "SEC-UNAUTH-MUTATION")
    assert [e["note"] for e in f["evidence"]] == ["POST /open"] and f["confidence"] == "low"


def test_readiness_api_filters_isolation_and_old_analyzer(app, user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    full = user_client.get(f"/api/v1/analyses/{aid}/readiness").json()
    assert full["available"] and full["summary"]["total"] == len(full["findings"]) and full["summary"]["scope"]["frontend_files"] == 5
    sec = user_client.get(f"/api/v1/analyses/{aid}/readiness", params={"category": "security"}).json()
    assert sec["filtered"] and sec["findings"] and {f["category"] for f in sec["findings"]} == {"security"}
    hi = user_client.get(f"/api/v1/analyses/{aid}/readiness", params={"min_confidence": "high"}).json()
    assert {f["confidence"] for f in hi["findings"]} == {"high"}
    assert user_client.get(f"/api/v1/analyses/{aid}/readiness", params={"category": "nope"}).status_code == 422
    other = new_other_client(app, "intruder@example.com")
    assert other.get(f"/api/v1/analyses/{aid}/readiness").status_code == 404
    from sqlalchemy import text

    from app.core.db import session_scope
    with session_scope() as db:
        db.execute(text("UPDATE analysis_jobs SET summary = summary - 'readiness' WHERE id = :i"), {"i": aid})
    old = user_client.get(f"/api/v1/analyses/{aid}/readiness").json()
    assert old["available"] is False and "older analyzer" in old["reason"]
