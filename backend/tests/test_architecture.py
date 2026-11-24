"""Sprint 2: architecture snapshot, drift between commits, history, predicted impact, tenant isolation."""
import uuid

import pytest

from app.core.db import new_session
from app.models import AnalysisJob
from app.services import architecture as arch
from tests.conftest import new_other_client
from tests.test_sprint1 import run

SHA1, SHA2 = "b" * 40, "c" * 40
B = {
    "app/__init__.py": "", "app/api/__init__.py": "", "app/services/__init__.py": "", "app/models/__init__.py": "",
    "app/api/items.py": "from app.services.pricing import price\n\n\ndef list_items():\n    return price(1)\n",
    "app/services/pricing.py": "import json\nfrom app.models.item import Item\n\n\ndef price(qty, currency):\n    return Item(qty)\n\n\ndef discount(x):\n    return x\n",
    "app/models/item.py": "class Item:\n    def __init__(self, qty):\n        self.qty = qty\n",
    "tests/test_pricing.py": "from app.services.pricing import price\n\n\ndef test_price():\n    assert price(1, 'x')\n",
}
H = {**{k: v for k, v in B.items() if k != "app/services/pricing.py"},
     # discount() removed, price() lost `currency`, new dep requests, models now import api (boundary violation) and pricing<->items cycle
     "app/services/pricing.py": "import json\nimport requests\nfrom app.models.item import Item\nfrom app.api.items import list_items\n\n\ndef price(qty):\n    return Item(qty)\n",
     "app/models/item.py": "from app.services.pricing import price\n\n\nclass Item:\n    def __init__(self, qty):\n        self.qty = qty\n"}


@pytest.fixture()
def two(user_client, gh_fake):
    a1 = run(user_client, gh_fake, B, SHA1)
    a2 = run(user_client, gh_fake, H, SHA2)
    return user_client, a1, a2


def kinds(d):
    return {f["kind"] for f in d["findings"]}


def test_snapshot_reports_cycles_and_violations_with_evidence(two):
    c, a1, a2 = two
    s1, s2 = (c.get(f"/api/v1/analyses/{a}/architecture").json() for a in (a1, a2))
    assert s1["commit_sha"] == SHA1 and s1["metrics"]["cycles"] == 0 and s1["metrics"]["boundary_violations"] == 0
    assert s2["metrics"]["cycles"] == 1 and s2["metrics"]["boundary_violations"] >= 1
    assert {e["commit_sha"] for cyc in s2["cycles"] for e in cyc["evidence"]} == {SHA2}
    assert any(v["source"] == "app/models/item.py" and v["target"] == "app/services/pricing.py" for v in s2["violations"])


def test_drift_detects_new_dependency_cycle_boundary_and_breaking_changes(two):
    c, a1, a2 = two
    d = c.get(f"/api/v1/analyses/{a2}/architecture/drift").json()
    assert d["available"] and d["base"]["analysis_id"] == a1 and d["head"]["commit_sha"] == SHA2
    assert {"new_dependency", "new_cycle", "boundary_violation", "breaking_symbol_removed", "breaking_signature_changed"} <= kinds(d)
    dep = next(f for f in d["findings"] if f["kind"] == "new_dependency")
    assert "requests" in dep["title"] and dep["evidence"][0]["path"] == "app/services/pricing.py" and dep["evidence"][0]["commit_sha"] == SHA2
    assert "json" not in " ".join(f["title"] for f in d["findings"] if f["kind"] == "new_dependency")  # unchanged deps are not drift
    sig = next(f for f in d["findings"] if f["kind"] == "breaking_signature_changed")
    assert "currency" in sig["detail"] and {e["commit_sha"] for e in sig["evidence"]} == {SHA1, SHA2}
    assert any("discount" in f["title"] for f in d["findings"] if f["kind"] == "breaking_symbol_removed")
    assert d["metrics"]["delta"]["external_dependencies"] == 1 and d["metrics"]["delta"]["cycles"] == 1


def test_predicted_impact_lists_dependents_tests_and_symbol_users_with_evidence(two):
    c, a1, a2 = two
    pi = c.get(f"/api/v1/analyses/{a2}/architecture/drift").json()["predicted_impact"]
    assert "app/services/pricing.py" in pi["changed_modules"]
    assert any(m["path"] == "app/api/items.py" and m["distance"] == 1 and m["evidence"]["commit_sha"] == SHA1 for m in pi["affected_modules"])
    assert any(t["path"] == "tests/test_pricing.py" for t in pi["tests"])
    assert any(u["symbol"] == "price" and u["used_by"] == "app/api/items.py" for u in pi["breaking_symbol_users"])
    assert not any(u["symbol"] == "discount" for u in pi["breaking_symbol_users"])  # nobody references it: no invented victims


def test_no_drift_between_identical_content_and_no_prior_analysis(user_client, gh_fake):
    a1 = run(user_client, gh_fake, B, SHA1)
    assert user_client.get(f"/api/v1/analyses/{a1}/architecture/drift").json()["available"] is False
    a2 = run(user_client, gh_fake, B, SHA2)  # new commit, same content
    d = user_client.get(f"/api/v1/analyses/{a2}/architecture/drift").json()
    assert d["available"] and d["findings"] == [] and all(v == 0 for v in d["metrics"]["delta"].values())
    assert d["predicted_impact"]["affected_modules"] == []


def test_history_is_ordered_with_deltas_and_old_commits_unchanged(two):
    c, a1, a2 = two
    h = c.get(f"/api/v1/analyses/{a2}/architecture/history").json()["points"]
    assert [p["commit_sha"] for p in h] == [SHA1, SHA2] and h[0]["delta"] is None and h[1]["delta"]["cycles"] == 1 and h[1]["current"]
    assert c.get(f"/api/v1/analyses/{a1}/architecture").json()["metrics"]["cycles"] == 0  # history never rewritten


def test_explicit_base_must_be_owned_and_same_repository(app, two):
    c, a1, a2 = two
    assert c.get(f"/api/v1/analyses/{a2}/architecture/drift?base={a1}").json()["available"]
    assert c.get(f"/api/v1/analyses/{a2}/architecture/drift?base={uuid.uuid4()}").status_code == 404
    other = new_other_client(app, "x@example.com")
    for path in ("architecture", "architecture/history", "architecture/drift"):
        assert other.get(f"/api/v1/analyses/{a2}/{path}").status_code == 404
    with new_session() as db:  # even a guessed id of someone else's analysis cannot be used as a base
        j = db.get(AnalysisJob, uuid.UUID(a1))
        assert arch.same_repo_job(db, uuid.uuid4(), j.repository_id, j.id) is None


def test_cycle_detection_is_iterative_and_exact():
    adj = {str(i): {str(i + 1)} for i in range(5000)} | {"5000": {"0"}, "x": {"y"}, "y": set()}
    cyc = arch._sccs(adj)
    assert len(cyc) == 1 and len(cyc[0]) == 5001
    assert arch._sccs({"a": {"b"}, "b": {"a"}, "c": {"a"}}) == [["a", "b"]]


def test_coupling_and_complexity_growth_are_flagged_only_past_thresholds(user_client, gh_fake):
    mods = {f"app/m{i}.py": f"def f{i}():\n    return {i}\n" for i in range(9)}
    small = {"app/__init__.py": "", **mods, "app/hub.py": "from app.m0 import f0\n\n\ndef run(x):\n    return f0()\n"}
    branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(14))
    big = {**small, "app/hub.py": "".join(f"from app.m{i} import f{i}\n" for i in range(9)) + f"\n\ndef run(x):\n{branches}    return f0()\n"}
    run(user_client, gh_fake, small, SHA1)
    a2 = run(user_client, gh_fake, big, SHA2)
    d = user_client.get(f"/api/v1/analyses/{a2}/architecture/drift").json()
    assert {"coupling_increase", "complexity_growth"} <= kinds(d)
    c = next(f for f in d["findings"] if f["kind"] == "coupling_increase")
    assert "9 internal modules (was 1)" in c["title"] and c["evidence"]
    run(user_client, gh_fake, {**small, "app/hub.py": small["app/hub.py"] + "\n\ndef extra():\n    return 1\n"}, "e" * 40)
    mild = user_client.get(f"/api/v1/analyses/{user_client.get('/api/v1/analyses').json()['items'][0]['analysis_id']}/architecture/drift").json()
    assert not kinds(mild) & {"coupling_increase", "complexity_growth"}
