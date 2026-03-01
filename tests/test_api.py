"""Tests for the FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from scraperguard.api.app import create_app
from scraperguard.config import ScraperGuardConfig, StorageConfig
from scraperguard.storage.models import (
    FieldFailure,
    Snapshot,
    SnapshotMetadata,
    ValidationResult,
)


@pytest.fixture()
def storage():
    config = ScraperGuardConfig(
        storage=StorageConfig(backend="sqlite", connection=":memory:")
    )
    app = create_app(config)
    return app.state.storage, app


@pytest.fixture()
def client(storage) -> TestClient:
    _, app = storage
    return TestClient(app)


@pytest.fixture()
def db(storage):
    s, _ = storage
    return s


def _make_snapshot_metadata() -> SnapshotMetadata:
    return SnapshotMetadata(
        http_status=200,
        latency_ms=150.0,
        timestamp=datetime.now(timezone.utc),
        headers={"content-type": "text/html"},
        response_size_bytes=5000,
    )


def _make_snapshot(run_id: str, url: str, html: str, ts: datetime | None = None) -> Snapshot:
    snap = Snapshot(
        run_id=run_id,
        url=url,
        normalized_html=html,
        fingerprint="abc123",
        metadata=_make_snapshot_metadata(),
        extracted_items=[{"name": "Test Product"}],
    )
    if ts is not None:
        snap.timestamp = ts
    return snap


def _make_validation_result(
    run_id: str,
    url: str,
    schema_name: str = "Product",
    null_ratios: dict | None = None,
    ts: datetime | None = None,
) -> ValidationResult:
    vr = ValidationResult(
        run_id=run_id,
        url=url,
        schema_name=schema_name,
        total_items=10,
        passed_count=8,
        failed_count=2,
        field_failures=[FieldFailure("price", "null", 2)],
        null_ratios=null_ratios or {"price": 0.1, "name": 0.0},
    )
    if ts is not None:
        vr.timestamp = ts
    return vr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_list_runs(client: TestClient, db) -> None:
    db.create_run("scraper-a")
    db.create_run("scraper-b")
    db.create_run("scraper-c")

    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["runs"]) == 3


def test_get_run(client: TestClient, db) -> None:
    run = db.create_run("my-scraper")

    resp = client.get(f"/api/runs/{run.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run.id
    assert data["scraper_name"] == "my-scraper"


def test_get_run_not_found(client: TestClient) -> None:
    resp = client.get("/api/runs/nonexistent-id")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_list_snapshots(client: TestClient, db) -> None:
    run = db.create_run("snap-scraper")
    url = "http://example.com/products"
    now = datetime.now(timezone.utc)

    for i in range(3):
        snap = _make_snapshot(run.id, url, f"<html><body>page {i}</body></html>")
        snap.timestamp = now + timedelta(seconds=i)
        db.save_snapshot(snap)

    resp = client.get("/api/snapshots", params={"url": url})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["snapshots"]) == 3
    # Should NOT contain HTML bodies
    for s in data["snapshots"]:
        assert "normalized_html" not in s
        assert "raw_html" not in s
        assert "fingerprint" in s


def test_get_snapshot_detail(client: TestClient, db) -> None:
    run = db.create_run("detail-scraper")
    snap = _make_snapshot(run.id, "http://example.com/p", "<html><body>detail</body></html>")
    snap.raw_html = "<html><body>raw detail</body></html>"
    db.save_snapshot(snap)

    # Without include_raw — normalized_html present, raw_html excluded
    resp = client.get(f"/api/snapshots/{snap.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "normalized_html" in data
    assert "raw_html" not in data

    # With include_raw=true
    resp = client.get(f"/api/snapshots/{snap.id}", params={"include_raw": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert "normalized_html" in data
    assert "raw_html" in data


def test_list_validation_results(client: TestClient, db) -> None:
    run = db.create_run("val-scraper")
    url = "http://example.com/products"
    now = datetime.now(timezone.utc)

    for i in range(3):
        vr = _make_validation_result(run.id, url)
        vr.timestamp = now + timedelta(seconds=i)
        db.save_validation_result(vr)

    resp = client.get(f"/api/validation/{url}", params={"schema_name": "Product"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 3


def test_drift_endpoint(client: TestClient, db) -> None:
    run = db.create_run("drift-scraper")
    url = "http://example.com/products"
    now = datetime.now(timezone.utc)

    # 3 historical results with low null ratios
    for i in range(3):
        vr = _make_validation_result(
            run.id, url, null_ratios={"price": 0.05, "name": 0.0},
            ts=now + timedelta(seconds=i),
        )
        db.save_validation_result(vr)

    # 1 current result with high null ratio for price
    current = _make_validation_result(
        run.id, url, null_ratios={"price": 0.85, "name": 0.0},
        ts=now + timedelta(seconds=10),
    )
    db.save_validation_result(current)

    resp = client.get(f"/api/drift/{url}", params={"schema_name": "Product"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["drift_events"]) > 0
    # The price drift should be detected
    price_events = [e for e in data["drift_events"] if e["field_name"] == "price"]
    assert len(price_events) == 1
    assert price_events[0]["severity"] == "critical"
    assert "baseline_count" in data
    assert "threshold" in data


def test_drift_no_data(client: TestClient) -> None:
    resp = client.get(
        "/api/drift/http://unknown.example.com/page",
        params={"schema_name": "Product"},
    )
    assert resp.status_code == 404


def test_report_endpoint(client: TestClient, db) -> None:
    run = db.create_run("report-scraper")
    url = "http://example.com/products"

    snap = _make_snapshot(run.id, url, "<html><body>report page</body></html>")
    db.save_snapshot(snap)

    vr = _make_validation_result(run.id, url)
    db.save_validation_result(vr)

    resp = client.get(f"/api/report/{run.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_score" in data
    assert "status" in data
    assert "components" in data
    assert len(data["components"]) == 4
    assert data["run_id"] == run.id
    assert data["url"] == url


def test_selector_tracking_endpoint(client: TestClient, db) -> None:
    run = db.create_run("selector-scraper")
    url = "http://example.com/product"
    now = datetime.now(timezone.utc)

    html_v1 = "<html><body><div class='product'><span class='price'>$10</span><span class='title'>Widget</span></div></body></html>"
    html_v2 = "<html><body><div class='product'><span class='title'>Widget</span></div></body></html>"

    snap1 = _make_snapshot(run.id, url, html_v1, ts=now)
    snap2 = _make_snapshot(run.id, url, html_v2, ts=now + timedelta(seconds=1))
    db.save_snapshot(snap1)
    db.save_snapshot(snap2)

    resp = client.get(
        f"/api/selectors/{url}",
        params={"selectors": ".price,.title"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "selector_statuses" in data
    statuses = {s["selector"]: s for s in data["selector_statuses"]}
    assert ".price" in statuses
    assert ".title" in statuses
    # .price was in v1 (older) but not in v2 (most recent) → broken
    assert statuses[".price"]["status"] == "broken"
