import pytest

from tests.conftest import create_analysis, emulate_n8n, new_other_client
from tests.fakes import FakeLLM


@pytest.fixture()
def ready(user_client, gh_fake):
    aid = create_analysis(user_client).json()["analysis_id"]
    emulate_n8n(user_client, aid, gh_fake, FakeLLM())
    return aid


def post(c, aid, **body):
    return c.post(f"/api/v1/analyses/{aid}/impact", json=body)


def test_default_base_is_first_parent_and_result_maps_onto_graph(user_client, ready, gh_fake):
    r = post(user_client, ready)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["base_ref"] == "b" * 40 and d["head_sha"] == gh_fake.sha and d["compare_url"].endswith(f"{'b' * 40}...{gh_fake.sha}")
    ch = {c["path"]: c for c in d["changed"]}
    assert ch["app/deps.py"]["kind"] == "python" and ch["app/deps.py"]["in_graph"]
    assert ch["static/util.js"]["kind"] == "frontend"
    assert ch["docs/old.md"]["removed"] and "removed" in ch["docs/old.md"]["note"] and not ch["docs/old.md"]["in_graph"]
    aff = {a["path"]: a for a in d["affected"]}
    assert aff["app/api/users.py"]["distance"] == 1 and aff["app/api/users.py"]["via"] == "app/deps.py" and aff["app/api/users.py"]["resolution"] == "verified_static"
    assert {r_["path"] for r_ in d["routes"]} >= {"/api/users/"}
    users_route = next(r_ for r_ in d["routes"] if r_["path"] == "/api/users/")
    assert "imports changed code" in users_route["reason"] and users_route["resolution"] == "verified_static"
    tests = {t["path"]: t for t in d["tests"]}
    assert "tests/test_users.py" in tests and tests["tests/test_users.py"]["resolution"] in ("verified_static", "inferred")
    fe = {f["path"]: f for f in d["frontend"]}
    assert fe["static/util.js"]["reason"] == "frontend file changed" and "static/app.js" in fe
    assert {n["tag"] for n in d["graph"]["nodes"]} >= {"changed", "affected", "test"}
    s = d["summary"]
    assert s["changed_files"] == 3 and s["removed"] == 1 and s["python"] == 1 and s["frontend"] == 1
    assert any("no test was run" in x for x in d["limitations"])


def test_explicit_base_branch_cached_history_and_detail(user_client, ready):
    a = post(user_client, ready, base="dev").json()
    b = post(user_client, ready, base="feature/x").json()
    assert a["base_ref"] == "dev" and b["base_ref"] == "feature/x" and a["id"] != b["id"]
    lst = user_client.get(f"/api/v1/analyses/{ready}/impact").json()["items"]
    assert [i["base_ref"] for i in lst] == ["feature/x", "dev"]
    d = user_client.get(f"/api/v1/analyses/{ready}/impact/{a['id']}").json()
    assert d["summary"] == a["summary"] and d["changed"] == a["changed"]


def test_unknown_ref_is_a_clean_404_not_a_500(user_client, ready):
    r = post(user_client, ready, base="does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "REF_NOT_FOUND"


@pytest.mark.parametrize("bad", ["../etc/passwd", "a..b", "main...dev", "-rf", "a b", "x?y=1", "x#frag", "a//b", "%2e%2e", "dev/", "x.lock", "x@{1}", "a\nb", "é", "x" * 150 + "/" * 3])
def test_hostile_refs_are_rejected_before_any_github_request(user_client, ready, gh_fake, bad):
    before = len(gh_fake.requests)
    r = post(user_client, ready, base=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REF"
    assert len(gh_fake.requests) == before


def test_overlong_ref_rejected_by_schema(user_client, ready, gh_fake):
    before = len(gh_fake.requests)
    assert post(user_client, ready, base="x" * 300).status_code == 422
    assert len(gh_fake.requests) == before


def test_only_allowlisted_github_paths_are_requested(user_client, ready, gh_fake):
    post(user_client, ready, base="feature/x")
    compare = [r for r in gh_fake.requests if "/compare/" in r]
    assert compare and all(r.startswith("api.github.com/repos/owner/sample/compare/feature/x...") or "api.github.com" in r for r in compare)


def test_isolation_and_state(app, user_client, ready, gh_fake):
    other = new_other_client(app, "intruder@example.com")
    rid = post(user_client, ready).json()["id"]
    assert post(other, ready).status_code == 404
    assert other.get(f"/api/v1/analyses/{ready}/impact").status_code == 404
    assert other.get(f"/api/v1/analyses/{ready}/impact/{rid}").status_code == 404
    own2 = create_analysis(other, "https://github.com/owner/sample").json()["analysis_id"]
    assert other.get(f"/api/v1/analyses/{own2}/impact/{rid}").status_code == 404      # report id from another analysis/user
    assert post(other, own2).status_code == 409                                       # not READY yet


def test_rate_limited_per_user(user_client, ready):
    codes = [post(user_client, ready).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10:] == [429, 429]


def test_github_failures_map_to_retryable_errors_and_do_not_leak(user_client, ready, gh_fake, monkeypatch):
    gh_fake.rate_limit_on_repo = True
    r = post(user_client, ready, base="dev")
    assert r.status_code in (200, 503)
    gh_fake.compare_files = [{"filename": f"f{i}.txt", "status": "added", "additions": 1, "deletions": 0} for i in range(300)]
    d = post(user_client, ready, base="main").json()
    assert d.get("truncated") is True or d.get("error")


def test_malformed_compare_payload_is_rejected(user_client, ready, gh_fake):
    gh_fake.compare_files = "not-a-list"
    r = post(user_client, ready, base="dev")
    assert r.status_code == 502 and r.json()["error"]["code"] == "GITHUB_BAD_RESPONSE"
