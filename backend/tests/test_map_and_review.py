from app.services import pr_review
from app.services.areas import area_of, group_files, is_test_path


def test_area_classification():
    assert area_of("tests/test_users.py") == "tests" and is_test_path("backend/tests/unit/x.py") and is_test_path("pkg/test_a.py")
    assert area_of("web/src/screens/Landing.jsx", None, True) == "frontend"
    assert area_of("app/api/routes/items.py") == "api" and area_of("app/models.py", "model") == "data"
    assert area_of("app/services/billing.py") == "logic" and area_of("app/workers/tasks.py") == "jobs" and area_of("app/utils.py") == "shared"
    assert area_of("app/api/x.py", "router") == "api"  # an analyser role wins over folder names
    assert area_of("scripts/build.py", "entry") == "tools" and area_of("loadtests/x.py") == "tools" and area_of("app/main.py", "entry") == "api"


def test_flat_project_file_names_carry_the_hint():
    assert area_of("workspace_api.py") == "api" and area_of("billing_service.py") == "logic" and area_of("query_planner.py") == "logic"
    assert area_of("models.py") == "data" and area_of("alert_worker.py") == "jobs" and area_of("helpers.py") == "shared"


def test_grouping_by_folder_then_by_name():
    g = group_files(["app/api/routes/items.py", "app/api/routes/users.py", "app/api/deps.py"])
    assert set(g) == {"routes", ""} and len(g["routes"]) == 2
    flat = group_files([f"web/src/screens/{n}.jsx" for n in ("Landing", "AuthLogin", "AuthRegister", "Workspace")])
    assert "auth" in flat and len(flat["auth"]) == 2 and "landing" in flat and "workspace" in flat
    many = group_files([f"pkg/m{i}/f.py" for i in range(30)])
    assert len(many) <= 14 and "other" in many


def test_map_endpoint_levels_and_links(user_client, ready):
    m = user_client.get(f"/api/v1/analyses/{ready}/map").json()
    ids = {a["id"] for a in m["areas"]}
    assert {"api", "data"} & ids and m["totals"]["files"] == len(m["files"]) > 0
    gids = {g["id"] for g in m["groups"]}
    assert all(f["group"] in gids and f["area"] in ids for f in m["files"])
    assert sum(g["files"] for g in m["groups"]) == len(m["files"])
    fid = {f["id"] for f in m["files"]}
    assert all(link["s"] in fid and link["t"] in fid for link in m["links"])
    assert all("tested_by" not in link["kinds"] for link in m["links"]) and all("tests" in f for f in m["files"])
    assert user_client.get(f"/api/v1/analyses/{ready}/map", headers={}).status_code == 200


def test_map_is_owner_only(ready, app):
    from tests.conftest import new_other_client
    other = new_other_client(app, "other@example.com")
    assert other.get(f"/api/v1/analyses/{ready}/map").status_code == 404


def test_verdict_levels_and_plain_reasons():
    hi = pr_review._verdict([{"kind": "breaking_route_removed", "severity": "high"}, {"kind": "new_cycle", "severity": "medium"}])
    assert hi["level"] == "review_closely" and hi["risk"] == "high" and "removed route" in hi["reasons"][0]["text"]
    mid = pr_review._verdict([{"kind": "new_dependency", "severity": "medium"}])
    assert mid["level"] == "review_normally" and mid["risk"] == "medium"
    low = pr_review._verdict([{"kind": "missing_tests", "severity": "low"}])
    assert low["level"] == "quick_look" and low["risk"] == "low" and low["reasons"] == []


def test_areas_changed_groups_files():
    ch = {"added": ["tests/test_a.py", "app/api/routes/x.py"], "modified": ["app/services/s.py"], "deleted": [], "renamed": [{"from": "a.py", "to": "app/models.py"}]}
    out = pr_review._areas_changed(ch, {})
    labels = {a["label"] for a in out}
    assert {"Tests", "API & routes", "Business logic"} <= labels
    assert sum(a["added"] + a["modified"] + a["deleted"] for a in out) == 4
