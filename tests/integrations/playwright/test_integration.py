"""Tests for ScraperGuard Playwright integration.

Tests the PageObserver, observe() context manager, and capture_page()
convenience function with a MockPage — no real browser required.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

from scraperguard.core.schema.base import BaseSchema
from scraperguard.health import HealthReport
from scraperguard.integrations.playwright.observer import (
    PageObserver,
    capture_page,
    observe,
)
from scraperguard.storage.sqlite import SQLiteBackend


# ---------------------------------------------------------------------------
# Test schema
# ---------------------------------------------------------------------------


class ProductSchema(BaseSchema):
    title: str
    price: float
    currency: str


# ---------------------------------------------------------------------------
# Fixture HTML (matches the product_page_normal.html style)
# ---------------------------------------------------------------------------

FIXTURE_HTML = """
<html>
<head><title>Product Page</title></head>
<body>
<div class="product">
    <h1 class="title">Widget Pro</h1>
    <span class="price">29.99</span>
    <span class="currency">USD</span>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# MockPage — mimics Playwright's async Page API
# ---------------------------------------------------------------------------


class MockPage:
    """Mimics the subset of Playwright's Page API used by PageObserver."""

    def __init__(
        self,
        html: str = FIXTURE_HTML,
        url: str = "http://test.example.com/product",
    ) -> None:
        self._html = html
        self.url = url

    async def content(self) -> str:
        return self._html

    async def goto(self, url: str) -> None:
        self.url = url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage(tmp_path: str | None = None) -> SQLiteBackend:
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    db_path = os.path.join(tmp_path, "test_scraperguard.db")
    return SQLiteBackend(db_path=db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestObserveCapturesSnapshot:
    """test_observe_captures_snapshot: Use observe() with MockPage, verify snapshot saved."""

    async def test_captures_snapshot(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="playwright")
        page = MockPage()

        async with observe(page, storage=storage, run_id=run.id) as observer:
            await page.goto("http://test.example.com/product")

        # Verify a snapshot was persisted
        snapshots = storage.list_snapshots("http://test.example.com/product", limit=10)
        assert len(snapshots) >= 1
        snapshot = snapshots[0]
        assert snapshot.url == "http://test.example.com/product"
        assert snapshot.run_id == run.id
        assert snapshot.normalized_html  # Non-empty


class TestObserveWithSchema:
    """test_observe_with_schema: Set items and schema, verify validation result saved."""

    async def test_validates_items(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="playwright")
        page = MockPage()

        items = [
            {"title": "Widget Pro", "price": 29.99, "currency": "USD"},
            {"title": "Widget Lite", "price": 19.99, "currency": "USD"},
        ]

        async with observe(page, storage=storage, run_id=run.id, schema=ProductSchema) as observer:
            observer.set_items(items)

        # Verify validation result was persisted
        vr = storage.get_latest_validation_result(
            "http://test.example.com/product", "ProductSchema",
        )
        assert vr is not None
        assert vr.total_items == 2
        assert vr.passed_count == 2
        assert vr.failed_count == 0


class TestObserveWithSelectors:
    """test_observe_with_selectors: Track selectors, verify they're evaluated."""

    async def test_tracks_selectors(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="playwright")
        page = MockPage()

        async with observe(
            page,
            storage=storage,
            run_id=run.id,
            selectors=[".title", ".price"],
        ) as observer:
            pass

        # The observer ran the pipeline with selectors.
        # Verify snapshot was created (selector tracking happens internally).
        snapshots = storage.list_snapshots("http://test.example.com/product", limit=10)
        assert len(snapshots) >= 1

        # Health report should exist and reflect selector tracking
        report = observer.get_health_report()
        assert report is not None
        assert isinstance(report, HealthReport)


class TestObserveFaultTolerance:
    """test_observe_fault_tolerance: Storage failure doesn't crash context manager."""

    async def test_storage_failure_does_not_raise(self) -> None:
        broken_storage = MagicMock()
        broken_storage.save_snapshot.side_effect = RuntimeError("DB connection lost")
        broken_storage.list_snapshots.side_effect = RuntimeError("DB connection lost")

        page = MockPage()

        # This must NOT raise
        async with observe(page, storage=broken_storage, run_id="test-run") as observer:
            observer.set_items([{"title": "X", "price": 1.0, "currency": "USD"}])

        # No exception means the test passes


class TestCapturePageConvenience:
    """test_capture_page_convenience: Use capture_page with MockPage, verify health report."""

    async def test_returns_health_report(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="playwright")
        page = MockPage()

        report = await capture_page(
            page,
            storage=storage,
            run_id=run.id,
            items=[{"title": "Widget", "price": 9.99, "currency": "USD"}],
            schema=ProductSchema,
        )

        assert report is not None
        assert isinstance(report, HealthReport)
        assert 0 <= report.overall_score <= 100


class TestGetHealthReportAfterExit:
    """test_get_health_report_after_exit: After exit, get_health_report() returns a HealthReport."""

    async def test_health_report_available(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="playwright")
        page = MockPage()

        async with observe(page, storage=storage, run_id=run.id) as observer:
            # Health report not yet available
            assert observer.get_health_report() is None

        # Now it should be available
        report = observer.get_health_report()
        assert report is not None
        assert isinstance(report, HealthReport)
        assert report.url == "http://test.example.com/product"
        assert report.run_id == run.id


class TestSetUrlOverride:
    """test_set_url_override: Use set_url() to override MockPage.url."""

    async def test_overrides_url(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="playwright")
        page = MockPage(url="http://test.example.com/spa-hash")

        async with observe(page, storage=storage, run_id=run.id) as observer:
            observer.set_url("http://test.example.com/real-product-url")

        # Snapshot should use the overridden URL, not the page.url
        snapshots = storage.list_snapshots("http://test.example.com/real-product-url", limit=10)
        assert len(snapshots) >= 1
        assert snapshots[0].url == "http://test.example.com/real-product-url"

        # Original URL should have no snapshots
        original_snapshots = storage.list_snapshots("http://test.example.com/spa-hash", limit=10)
        assert len(original_snapshots) == 0
