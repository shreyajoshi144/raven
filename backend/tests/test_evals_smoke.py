"""Regression test: the hermetic smoke evaluation runs Raven's real pipeline on benchmark v1 and must meet the committed floors.
Uses the test database (TEST_DATABASE_URL), no network and no LLM. Also pins the known Raven defects the benchmark exposes, so a
fix shows up as a (welcome) test failure that prompts raising the floors and updating the baseline."""
import json
import os
from pathlib import Path

import pytest

from evals.report import check_thresholds
from evals.runner import RunConfig, run

THRESHOLDS = Path(__file__).resolve().parents[1] / "evals" / "thresholds" / "smoke.json"


@pytest.fixture(scope="module")
def smoke():
    return run(RunConfig(suite="smoke", db_url=os.environ["DATABASE_URL"], reset_db=False, repeats=2))


def test_smoke_meets_committed_floors(smoke):
    failed = [c for c in check_thresholds(smoke, json.loads(THRESHOLDS.read_text())) if not c["passed"]]
    assert failed == [], failed
    assert smoke["failures"] == []
    assert smoke["judge_status"]["state"] == "not_requested" and smoke["sut"]["mode"] == "retrieval_only"
    assert smoke["metrics"]["operational"]["sut_llm"]["calls"] == 0  # smoke never calls a model


def test_smoke_results_are_complete_and_honest(smoke):
    m = smoke["metrics"]
    assert m["qa"]["n"] == 27 and m["qa"]["n_ai"] == 0 and m["qa"]["key_fact_recall_ai"] is None  # no AI answers -> no AI-quality score
    assert m["retrieval"]["n_answerable"] == 20 and m["retrieval"]["n_unanswerable"] == 7
    assert m["impact"]["n_cases"] == 5 and len(smoke["samples"]["qa"]) == 27
    assert smoke["benchmark"]["version"] == "1.0.0" and len(smoke["benchmark"]["fingerprint"]) == 64
    rep = m["reproducibility"]
    assert rep["repeats_compared"] == 2 and rep["unstable_outputs"] == []


def test_fixed_defects_stay_fixed_and_open_issues_are_still_detected(smoke):
    ft = smoke["per_repo"]["graph"]["fastapi_template"]
    assert ft["orm_models"]["recall"] == 1.0                # SQLModel table=True through a base class is an ORM table (fixed)
    assert ft["internal_imports"]["missing"] == ["('backend/app/alembic/env.py', 'backend/app/models.py')"]  # deps.py (Python 3.14 syntax) now parsed; re-export edge still open
    rd = smoke["per_repo"]["readiness"]
    assert rd["fastapi_template"]["per_rule"]["SEC-NO-AUTH-DETECTED"] == "TN" and rd["fastapi_template"]["per_rule"]["SEC-UNAUTH-MUTATION"] == "TP"
    assert "CFG-REQUIRED-ENV-AT-IMPORT app/core/config.py:6" not in rd["shop_api"]["location_level"]["false_positives"]  # os.getenv no longer "required" (fixed)
    assert rd["shop_api"]["per_rule"]["TEST-UNREACHED-ROUTER"] == "TN"   # 20-line file no longer counted as 21 lines (fixed)
    # SEC-UNAUTH-MUTATION recognises superuser dependencies and Annotated aliases such as CurrentUser (fixed 2026-11-01)
    assert rd["fastapi_template"]["location_level"]["false_positives"] == [] and rd["fastapi_template"]["location_level"]["false_negatives"] == []
    assert rd["shop_api"]["per_rule"]["SEC-HARDCODED-SECRET-DEFAULT"] == "FN"  # literal os.getenv fallback not reported (open)
    assert rd["clean_service"]["rule_level"]["fp"] == 0
    assert smoke["metrics"]["reproducibility"]["unstable_outputs"] == []   # retrieval is deterministic across re-analyses (fixed)
