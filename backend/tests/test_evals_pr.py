"""The PR benchmark harness itself: mutations apply exactly, and a wrong label is reported as a failure (the suite can fail)."""
import json

import pytest

from evals import pr_review
from evals.pr_review import mutate, _review

SPEC = json.loads((pr_review.HERE / "pr" / "cases.json").read_text())
BASE = {k: v.encode() for k, v in SPEC["inline_repo"].items()}


def test_mutate_prepend_replace_add_and_missing_target():
    out = mutate(BASE, [{"file": "app/models/item.py", "prepend": "# x\n"}, {"file": "app/services/pricing.py", "replace": ["import json\n", ""]}, {"add": "app/new.py", "content": "x = 1\n"}])
    assert out["app/models/item.py"].startswith(b"# x\n") and b"import json" not in out["app/services/pricing.py"] and out["app/new.py"] == b"x = 1\n"
    assert BASE["app/models/item.py"] == SPEC["inline_repo"]["app/models/item.py"].encode()  # input untouched
    with pytest.raises(AssertionError):
        mutate(BASE, [{"file": "app/models/item.py", "replace": ["not there", "x"]}])


def test_every_case_declares_expectations_over_known_kinds():
    known = {"new_dependency", "new_cycle", "boundary_violation", "breaking_symbol_removed", "breaking_signature_changed", "breaking_route_removed", "coupling_increase",
             "complexity_growth", "new_readiness_finding", "sensitive_area_changed", "missing_tests"}
    for c in SPEC["cases"]:
        assert set(c["expect"]) | set(c["forbid"]) <= known and not set(c["expect"]) & set(c["forbid"]), c["id"]


def test_review_flags_the_mutation_and_not_an_untouched_tree():
    changed = mutate(BASE, [{"file": "app/services/pricing.py", "prepend": "import requests\n"}])
    r = _review(BASE, changed, "eval/pr-test")
    assert {f["kind"] for f in r["review"]["findings"]} == {"new_dependency"}
    same = _review(BASE, dict(BASE), "eval/pr-test")
    assert same["review"]["findings"] == []
