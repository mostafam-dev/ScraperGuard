"""Tests for the SQLite storage backend."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from scraperguard.storage.models import (
    FieldFailure,
    Snapshot,
    SnapshotMetadata,
    ValidationResult,
)
from scraperguard.storage.sqlite import SQLiteBackend

PRODUCT_HTML = (
    '<html><body><div class="product">'
    '<h1 class="title">Test Product</h1>'
    '<span class="price">29.99</span>'
    '<span class="stock">In Stock</span>'
    "</div></body></html>"
)

EXTRACTED_ITEMS = [
    {"title": "Test Product", "price": 29.99, "availability": True, "rating": 4.5},
    {"title": "Another Product", "price": None, "availability": True, "rating": 3.2},
    {"title": "Third Item", "price": 15.00, "availability": False, "rating": None},
]

TEST_URL = "https://example.com/products"


def _make_metadata(ts: datetime | None = None) -> SnapshotMetadata:
    return SnapshotMetadata(
        http_status=200,
        latency_ms=123.45,
        timestamp=ts or datetime.now(timezone.utc),
        headers={"content-type": "text/html", "x-request-id": "abc-123"},
        response_size_bytes=8192,
    )


def _make_snapshot(
    run_id: str,
    url: str = TEST_URL,
    ts: datetime | None = None,
    extracted_items: list[dict] | None = None,
) -> Snapshot:
    now = ts or datetime.now(timezone.utc)
    return Snapshot(
        run_id=run_id,
        url=url,
        normalized_html=PRODUCT_HTML,
        fingerprint="fp-" + uuid.uuid4().hex[:8],
        metadata=_make_metadata(now),
        raw_html="<html><body>raw</body></html>",
        extracted_items=extracted_items if extracted_items is not None else EXTRACTED_ITEMS,
        timestamp=now,
    )


@pytest.fixture()
def backend() -> SQLiteBackend:
    return SQLiteBackend(":memory:")


# ---------------------------------------------------------------------------
# Test group 1 — Run operations
# ---------------------------------------------------------------------------


class TestRunOperations:
    def test_create_run(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("price_spider", config={"retries": 3})

        uuid.UUID(run.id)  # raises if not a valid UUID
        assert run.scraper_name == "price_spider"
        assert run.status == "running"
        assert run.config == {"retries": 3}
        assert isinstance(run.timestamp, datetime)

    def test_get_run(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("price_spider", config={"timeout": 30})

        fetched = backend.get_run(run.id)
        assert fetched is not None
        assert fetched.id == run.id
        assert fetched.scraper_name == run.scraper_name
        assert fetched.status == run.status
        assert fetched.config == run.config
        assert fetched.timestamp == run.timestamp

    def test_get_run_not_found(self, backend: SQLiteBackend) -> None:
        assert backend.get_run("nonexistent-id-000") is None

    def test_update_run_status(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("price_spider")
        assert run.status == "running"

        backend.update_run_status(run.id, "completed")
        fetched = backend.get_run(run.id)
        assert fetched is not None
        assert fetched.status == "completed"


# ---------------------------------------------------------------------------
# Test group 2 — Snapshot operations
# ---------------------------------------------------------------------------


class TestSnapshotOperations:
    def test_save_and_retrieve_snapshot(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("product_spider")
        original = _make_snapshot(run.id)
        backend.save_snapshot(original)

        fetched = backend.get_snapshot_by_id(original.id)
        assert fetched is not None

        # Top-level fields
        assert fetched.id == original.id
        assert fetched.run_id == original.run_id
        assert fetched.url == original.url
        assert fetched.normalized_html == original.normalized_html
        assert fetched.fingerprint == original.fingerprint
        assert fetched.raw_html == original.raw_html
        assert fetched.timestamp == original.timestamp

        # Nested SnapshotMetadata
        assert fetched.metadata.http_status == original.metadata.http_status
        assert fetched.metadata.latency_ms == original.metadata.latency_ms
        assert fetched.metadata.timestamp == original.metadata.timestamp
        assert fetched.metadata.headers == original.metadata.headers
        assert fetched.metadata.response_size_bytes == original.metadata.response_size_bytes

        # Extracted items — full content check
        assert fetched.extracted_items == original.extracted_items
        assert len(fetched.extracted_items) == 3
        assert fetched.extracted_items[0]["price"] == 29.99
        assert fetched.extracted_items[0]["availability"] is True
        assert fetched.extracted_items[1]["price"] is None
        assert fetched.extracted_items[2]["availability"] is False
        assert fetched.extracted_items[2]["rating"] is None

    def test_get_latest_snapshot(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("spider")
        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        for i in range(3):
            snap = _make_snapshot(run.id, ts=base_time + timedelta(minutes=i))
            backend.save_snapshot(snap)

        latest = backend.get_latest_snapshot(TEST_URL)
        assert latest is not None
        assert latest.timestamp == base_time + timedelta(minutes=2)

    def test_get_latest_snapshot_different_urls(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("spider")
        url_a = "https://example.com/a"
        url_b = "https://example.com/b"

        snap_a = _make_snapshot(run.id, url=url_a)
        snap_b = _make_snapshot(run.id, url=url_b)
        backend.save_snapshot(snap_a)
        backend.save_snapshot(snap_b)

        result = backend.get_latest_snapshot(url_a)
        assert result is not None
        assert result.url == url_a
        assert result.id == snap_a.id

    def test_get_latest_snapshot_not_found(self, backend: SQLiteBackend) -> None:
        assert backend.get_latest_snapshot("https://nonexistent.example.com") is None

    def test_list_snapshots(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("spider")
        base_time = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        ids_newest_first = []

        for i in range(5):
            snap = _make_snapshot(run.id, ts=base_time + timedelta(minutes=i))
            backend.save_snapshot(snap)
            ids_newest_first.insert(0, snap.id)

        results = backend.list_snapshots(TEST_URL, limit=3)
        assert len(results) == 3
        assert [s.id for s in results] == ids_newest_first[:3]

    def test_json_roundtrip_edge_cases(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("spider")
        edge_items = [
            {"key": None},
            {"key": ""},
            {"int_zero": 0, "float_zero": 0.0},
            {"flag": False},
            {"nested": [1, "two", None, True]},
        ]
        snap = _make_snapshot(run.id, extracted_items=edge_items)
        backend.save_snapshot(snap)

        fetched = backend.get_snapshot_by_id(snap.id)
        assert fetched is not None
        items = fetched.extracted_items

        assert items[0]["key"] is None
        assert items[1]["key"] == ""
        assert items[2]["int_zero"] == 0
        assert items[2]["float_zero"] == 0.0
        assert items[3]["flag"] is False
        assert items[4]["nested"] == [1, "two", None, True]


# ---------------------------------------------------------------------------
# Test group 3 — Validation result operations
# ---------------------------------------------------------------------------


class TestValidationResultOperations:
    def test_save_and_retrieve_validation_result(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("spider")
        original = ValidationResult(
            run_id=run.id,
            url=TEST_URL,
            schema_name="ProductSchema",
            total_items=150,
            passed_count=142,
            failed_count=8,
            field_failures=[
                FieldFailure(field_name="price", failure_type="null", count=5),
                FieldFailure(field_name="availability", failure_type="missing", count=2),
                FieldFailure(field_name="rating", failure_type="out_of_range", count=1),
            ],
            null_ratios={
                "title": 0.0,
                "price": 0.033,
                "availability": 0.013,
                "rating": 0.007,
            },
        )
        backend.save_validation_result(original)

        fetched = backend.get_latest_validation_result(TEST_URL, "ProductSchema")
        assert fetched is not None
        assert fetched.id == original.id
        assert fetched.run_id == original.run_id
        assert fetched.url == original.url
        assert fetched.schema_name == original.schema_name
        assert fetched.total_items == 150
        assert fetched.passed_count == 142
        assert fetched.failed_count == 8
        assert fetched.timestamp == original.timestamp

        assert len(fetched.field_failures) == 3
        assert fetched.field_failures[0].field_name == "price"
        assert fetched.field_failures[0].failure_type == "null"
        assert fetched.field_failures[0].count == 5
        assert fetched.field_failures[1].field_name == "availability"
        assert fetched.field_failures[1].failure_type == "missing"
        assert fetched.field_failures[1].count == 2
        assert fetched.field_failures[2].field_name == "rating"
        assert fetched.field_failures[2].failure_type == "out_of_range"
        assert fetched.field_failures[2].count == 1

        assert fetched.null_ratios == original.null_ratios

    def test_get_latest_validation_result_filters_by_schema(
        self, backend: SQLiteBackend
    ) -> None:
        run = backend.create_run("spider")

        product_vr = ValidationResult(
            run_id=run.id,
            url=TEST_URL,
            schema_name="ProductSchema",
            total_items=100,
            passed_count=95,
            failed_count=5,
            field_failures=[FieldFailure("price", "null", 5)],
            null_ratios={"price": 0.05},
        )
        review_vr = ValidationResult(
            run_id=run.id,
            url=TEST_URL,
            schema_name="ReviewSchema",
            total_items=200,
            passed_count=180,
            failed_count=20,
            field_failures=[FieldFailure("author", "missing", 20)],
            null_ratios={"author": 0.10},
        )
        backend.save_validation_result(product_vr)
        backend.save_validation_result(review_vr)

        result = backend.get_latest_validation_result(TEST_URL, "ProductSchema")
        assert result is not None
        assert result.schema_name == "ProductSchema"
        assert result.total_items == 100
        assert result.id == product_vr.id

    def test_list_validation_results(self, backend: SQLiteBackend) -> None:
        run = backend.create_run("spider")
        base_time = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        ids_newest_first = []

        for i in range(5):
            vr = ValidationResult(
                run_id=run.id,
                url=TEST_URL,
                schema_name="ProductSchema",
                total_items=100 + i,
                passed_count=90 + i,
                failed_count=10,
                field_failures=[],
                null_ratios={},
                timestamp=base_time + timedelta(minutes=i),
            )
            backend.save_validation_result(vr)
            ids_newest_first.insert(0, vr.id)

        results = backend.list_validation_results(TEST_URL, "ProductSchema", limit=3)
        assert len(results) == 3
        assert [r.id for r in results] == ids_newest_first[:3]

    def test_get_latest_validation_result_not_found(
        self, backend: SQLiteBackend
    ) -> None:
        assert backend.get_latest_validation_result("https://nope.com", "Nope") is None
