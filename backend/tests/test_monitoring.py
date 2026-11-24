from sqlalchemy import select

from app.core.db import new_session
from app.core.metrics import Metrics, metrics, percentile, route_label
from app.models import User
from tests.conftest import create_analysis, internal


def test_route_labels_collapse_ids():
    assert route_label("/api/v1/analyses/3f2b8c1e-1111-4222-8333-444455556666/graph") == "/api/v1/analyses/{id}/graph"
    assert route_label("/api/v1/pr-reviews/42") == "/api/v1/pr-reviews/{n}"


def test_percentile_edges():
    assert percentile([], .95) is None and percentile([5.0], .95) == 5.0
    vals = [float(i) for i in range(1, 101)]
    assert percentile(vals, .5) in (50.0, 51.0) and percentile(vals, .95) in (95.0, 96.0)


def test_buckets_error_classes_and_pruning():
    m = Metrics()
    t = 1_000_000.0
    for ms, st in ((10, 200), (20, 200), (500, 500), (30, 404)):
        m.record("/api/v1/analyses", st, ms, now=t)
    m.record("/static/app.js", 200, 1, now=t)       # static assets are not tracked
    m.record("/health/live", 200, 1, now=t)
    snap = m.snapshot(5, now=t)
    assert snap["requests"] == 4 and snap["errors_5xx"] == 1 and snap["errors_4xx"] == 1 and snap["error_rate"] == .25
    assert len(snap["series"]) == 5 and snap["series"][-1]["n"] == 4 and snap["p95_ms"] == 500.0
    assert snap["slowest_routes"][0]["route"] == "/api/v1/analyses"
    m.record("/api/v1/x", 200, 1, now=t + 60 * 200)  # 200 minutes later: the old bucket is dropped
    assert m.snapshot(120, now=t + 60 * 200)["requests"] == 1


def test_middleware_records_real_requests(client):
    metrics.reset()
    client.get("/api/v1/me")
    client.get("/api/v1/me")
    snap = metrics.snapshot(5)
    assert snap["requests"] == 2 and snap["errors_4xx"] == 2


def test_admin_monitoring_requires_admin_and_returns_all_sections(user_client):
    assert user_client.get("/api/v1/admin/monitoring").status_code == 403
    with new_session() as db:
        db.execute(select(User)).scalar_one().role = "admin"
        db.commit()
    create_analysis(user_client)
    d = user_client.get("/api/v1/admin/monitoring").json()
    assert set(d) == {"generated_at", "http", "jobs", "queue", "llm", "services"}
    assert d["services"]["database"] is True and d["jobs"]["in_flight"] >= 1 and d["queue"]["by_status"] is not None
    assert len(d["http"]["series"]) == 60 and d["llm"]["answers_24h"] == 0 and d["llm"]["fallback_rate"] is None
    assert user_client.get("/api/v1/admin/monitoring?minutes=1").status_code == 422


def test_prometheus_endpoint_needs_service_secret(client, user_client):
    assert client.get("/internal/v1/metrics").status_code in (401, 403)
    r = internal(user_client, "GET", "/metrics")
    assert r.status_code == 200 and "raven_http_requests_total" in r.text and "raven_analysis_jobs" in r.text
