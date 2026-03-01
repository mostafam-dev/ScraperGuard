"""Tests for ScraperGuard Scrapy integration.

Tests the ObserverMiddleware and ValidationPipeline with mocked Scrapy objects,
verifying that ScraperGuard observes without interfering with the Scrapy pipeline.
"""

from __future__ import annotations

import tempfile
from collections import defaultdict
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scraperguard.config import ScraperGuardConfig
from scraperguard.core.schema.base import BaseSchema
from scraperguard.integrations.scrapy.middleware import ScraperGuardObserverMiddleware
from scraperguard.integrations.scrapy.pipeline import ScraperGuardValidationPipeline
from scraperguard.storage.models import SnapshotMetadata
from scraperguard.storage.sqlite import SQLiteBackend


# ---------------------------------------------------------------------------
# Test schema
# ---------------------------------------------------------------------------


class ProductSchema(BaseSchema):
    title: str
    price: float
    currency: str


# ---------------------------------------------------------------------------
# Helpers to create mock Scrapy objects
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
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


def _make_request(url: str = "https://example.com/product/1", meta: dict | None = None) -> MagicMock:
    """Create a mock Scrapy Request."""
    request = MagicMock()
    request.url = url
    request.meta = dict(meta) if meta else {}
    return request


def _make_response(
    url: str = "https://example.com/product/1",
    status: int = 200,
    body: str = SAMPLE_HTML,
    headers: dict | None = None,
) -> MagicMock:
    """Create a mock Scrapy Response."""
    response = MagicMock()
    response.url = url
    response.status = status
    response.text = body
    response.body = body.encode("utf-8")

    # Mock headers — use a custom dict subclass so .items() works naturally
    raw_headers = headers or {"Content-Type": "text/html"}
    mock_headers: dict[bytes, list[bytes]] = {}
    for k, v in raw_headers.items():
        mock_headers[k.encode("utf-8")] = [v.encode("utf-8")]
    response.headers = mock_headers
    return response


def _make_spider(name: str = "test_spider") -> MagicMock:
    """Create a mock Scrapy Spider."""
    spider = MagicMock()
    spider.name = name
    spider.start_urls = ["https://example.com/product/1"]
    spider.logger = MagicMock()
    return spider


def _make_storage(tmp_path: str | None = None) -> SQLiteBackend:
    """Create a real SQLite storage backend in a temp directory."""
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    import os

    db_path = os.path.join(tmp_path, "test_scraperguard.db")
    return SQLiteBackend(db_path=db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMiddlewareCapturesResponse:
    """test_middleware_captures_response: Verify HTML is stored in request.meta."""

    def test_captures_html_and_metadata(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="test")

        mw = ScraperGuardObserverMiddleware(
            config=ScraperGuardConfig(),
            storage=storage,
            run_id=run.id,
        )

        request = _make_request()
        response = _make_response()
        spider = _make_spider()

        result = mw.process_response(request, response, spider)

        # HTML stored in request.meta
        assert "scraperguard_html" in request.meta
        assert request.meta["scraperguard_html"] == SAMPLE_HTML

        # Metadata stored in request.meta
        assert "scraperguard_metadata" in request.meta
        meta = request.meta["scraperguard_metadata"]
        assert isinstance(meta, SnapshotMetadata)
        assert meta.http_status == 200
        assert meta.response_size_bytes == len(SAMPLE_HTML.encode("utf-8"))

        # Also stored in middleware's shared state
        assert response.url in mw._captured

    def test_captures_latency_from_download_latency(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="test")

        mw = ScraperGuardObserverMiddleware(
            config=ScraperGuardConfig(),
            storage=storage,
            run_id=run.id,
        )

        request = _make_request(meta={"download_latency": 0.5})
        response = _make_response()
        spider = _make_spider()

        mw.process_response(request, response, spider)

        meta = request.meta["scraperguard_metadata"]
        assert meta.latency_ms == pytest.approx(500.0)


class TestMiddlewareDoesNotModifyResponse:
    """test_middleware_does_not_modify_response: Returned response is identical to input."""

    def test_returns_same_response(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="test")

        mw = ScraperGuardObserverMiddleware(
            config=ScraperGuardConfig(),
            storage=storage,
            run_id=run.id,
        )

        request = _make_request()
        response = _make_response()
        spider = _make_spider()

        result = mw.process_response(request, response, spider)

        assert result is response


class TestPipelineCollectsItems:
    """test_pipeline_collects_items: Process 5 items and verify they're buffered."""

    def test_buffers_five_items(self) -> None:
        pipeline = ScraperGuardValidationPipeline(
            schema_cls=ProductSchema,
            storage=None,
            run_id="test-run",
            config=ScraperGuardConfig(),
            selectors=[],
            store_raw_html=False,
        )
        spider = _make_spider()
        pipeline.open_spider(spider)

        items = [
            {"title": f"Product {i}", "price": 10.0 + i, "currency": "USD", "url": "https://example.com/p"}
            for i in range(5)
        ]

        for item in items:
            pipeline.process_item(item, spider)

        assert len(pipeline._items_by_url["https://example.com/p"]) == 5

    def test_groups_items_by_url(self) -> None:
        pipeline = ScraperGuardValidationPipeline(
            schema_cls=ProductSchema,
            storage=None,
            run_id="test-run",
            config=ScraperGuardConfig(),
            selectors=[],
            store_raw_html=False,
        )
        spider = _make_spider()
        pipeline.open_spider(spider)

        pipeline.process_item({"title": "A", "price": 1.0, "currency": "USD", "url": "https://a.com"}, spider)
        pipeline.process_item({"title": "B", "price": 2.0, "currency": "USD", "url": "https://b.com"}, spider)
        pipeline.process_item({"title": "C", "price": 3.0, "currency": "USD", "url": "https://a.com"}, spider)

        assert len(pipeline._items_by_url["https://a.com"]) == 2
        assert len(pipeline._items_by_url["https://b.com"]) == 1


class TestPipelineDoesNotDropItems:
    """test_pipeline_does_not_drop_items: Verify process_item returns the item unchanged."""

    def test_returns_item_unchanged(self) -> None:
        pipeline = ScraperGuardValidationPipeline(
            schema_cls=ProductSchema,
            storage=None,
            run_id="test-run",
            config=ScraperGuardConfig(),
            selectors=[],
            store_raw_html=False,
        )
        spider = _make_spider()
        pipeline.open_spider(spider)

        item = {"title": "Widget", "price": 19.99, "currency": "EUR", "url": "https://example.com"}
        result = pipeline.process_item(item, spider)

        assert result is item

    def test_returns_non_dict_item_unchanged(self) -> None:
        """Even if the item is not a dict subclass, it should be returned as-is."""
        pipeline = ScraperGuardValidationPipeline(
            schema_cls=ProductSchema,
            storage=None,
            run_id="test-run",
            config=ScraperGuardConfig(),
            selectors=[],
            store_raw_html=False,
        )
        spider = _make_spider()
        pipeline.open_spider(spider)

        # Simulate a Scrapy Item-like object
        class FakeItem:
            def __init__(self) -> None:
                self.data = {"title": "X", "price": 1.0, "currency": "USD"}

            def __iter__(self):
                return iter(self.data.items())

            def __getitem__(self, key: str) -> Any:
                return self.data[key]

            def keys(self):
                return self.data.keys()

        item = FakeItem()
        result = pipeline.process_item(item, spider)
        assert result is item


class TestPipelineFaultTolerance:
    """test_pipeline_fault_tolerance: Storage failure in close_spider doesn't propagate."""

    def test_storage_failure_does_not_propagate(self, tmp_path: Any) -> None:
        """Mock a storage failure during close_spider, verify no exception propagates."""
        broken_storage = MagicMock()
        broken_storage.save_snapshot.side_effect = RuntimeError("DB connection lost")
        broken_storage.list_snapshots.side_effect = RuntimeError("DB connection lost")

        pipeline = ScraperGuardValidationPipeline(
            schema_cls=ProductSchema,
            storage=broken_storage,
            run_id="test-run",
            config=ScraperGuardConfig(),
            selectors=[],
            store_raw_html=False,
        )
        spider = _make_spider()
        pipeline.open_spider(spider)

        for i in range(3):
            pipeline.process_item(
                {"title": f"P{i}", "price": float(i), "currency": "USD", "url": "https://example.com"},
                spider,
            )

        # This must NOT raise — ScraperGuard should never break the scraper
        pipeline.close_spider(spider)

    def test_schema_import_failure_does_not_propagate(self) -> None:
        """If schema class can't be found, pipeline still works."""
        pipeline = ScraperGuardValidationPipeline(
            schema_cls=None,  # No schema
            storage=MagicMock(),
            run_id="test-run",
            config=ScraperGuardConfig(),
            selectors=[],
            store_raw_html=False,
        )
        spider = _make_spider()
        pipeline.open_spider(spider)

        item = {"title": "Widget", "price": 9.99, "currency": "USD", "url": "https://example.com"}
        result = pipeline.process_item(item, spider)
        assert result is item

        # close_spider should not raise even with mock storage
        pipeline.close_spider(spider)


class TestFullScrapyFlow:
    """test_full_scrapy_flow: End-to-end test with middleware + pipeline."""

    def test_full_flow(self, tmp_path: Any) -> None:
        """Simulate a minimal Scrapy spider yielding 3 items with fake responses.

        Verifies that after the spider closes:
        - A snapshot exists in storage
        - A validation result exists
        - The run status is "completed"
        """
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="scrapy")
        config = ScraperGuardConfig()

        # --- Set up middleware ---
        mw = ScraperGuardObserverMiddleware(
            config=config,
            storage=storage,
            run_id=run.id,
            store_raw_html=False,
            selectors=[".title", ".price"],
        )

        # --- Set up pipeline ---
        pipeline = ScraperGuardValidationPipeline(
            schema_cls=ProductSchema,
            storage=storage,
            run_id=run.id,
            config=config,
            selectors=[".title", ".price"],
            store_raw_html=False,
            crawler=None,
        )
        # Manually wire the middleware reference for the pipeline
        pipeline._middleware_ref = mw

        # Monkey-patch _get_middleware to return our middleware
        original_get_middleware = ScraperGuardValidationPipeline._get_middleware

        @staticmethod  # type: ignore[misc]
        def _mock_get_middleware(crawler: Any) -> Any:
            return mw

        ScraperGuardValidationPipeline._get_middleware = _mock_get_middleware  # type: ignore[assignment]

        try:
            spider = _make_spider()
            url = "https://example.com/product/1"

            # --- Simulate 3 responses going through middleware ---
            items_data = [
                {"title": "Widget Pro", "price": 29.99, "currency": "USD"},
                {"title": "Widget Lite", "price": 19.99, "currency": "USD"},
                {"title": "Widget Ultra", "price": 49.99, "currency": "EUR"},
            ]

            pipeline.open_spider(spider)

            for item_data in items_data:
                request = _make_request(url=url)
                response = _make_response(url=url)

                # Middleware captures the response
                mw.process_response(request, response, spider)

                # Pipeline collects the item
                item_with_url = {**item_data, "url": url}
                result = pipeline.process_item(item_with_url, spider)
                assert result is item_with_url  # Never drops

            # --- Spider closes ---
            pipeline.close_spider(spider)
            mw.spider_closed(spider, reason="finished")

            # --- Verify results ---

            # 1. Snapshot exists
            snapshots = storage.list_snapshots(url, limit=10)
            assert len(snapshots) >= 1, "Expected at least one snapshot"
            snapshot = snapshots[0]
            assert snapshot.url == url
            assert snapshot.run_id == run.id
            assert len(snapshot.extracted_items) == 3

            # 2. Validation result exists
            vr = storage.get_latest_validation_result(url, "ProductSchema")
            assert vr is not None, "Expected a validation result"
            assert vr.total_items == 3
            assert vr.passed_count == 3
            assert vr.failed_count == 0
            assert vr.schema_name == "ProductSchema"

            # 3. Run status is "completed"
            run_meta = storage.get_run(run.id)
            assert run_meta is not None
            assert run_meta.status == "completed"

        finally:
            ScraperGuardValidationPipeline._get_middleware = original_get_middleware  # type: ignore[assignment]

    def test_full_flow_with_failures(self, tmp_path: Any) -> None:
        """Test that validation failures are recorded but don't break the pipeline."""
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="scrapy")
        config = ScraperGuardConfig()

        mw = ScraperGuardObserverMiddleware(
            config=config,
            storage=storage,
            run_id=run.id,
        )

        pipeline = ScraperGuardValidationPipeline(
            schema_cls=ProductSchema,
            storage=storage,
            run_id=run.id,
            config=config,
            selectors=[],
            store_raw_html=False,
        )

        original_get_middleware = ScraperGuardValidationPipeline._get_middleware

        @staticmethod  # type: ignore[misc]
        def _mock_get_middleware(crawler: Any) -> Any:
            return mw

        ScraperGuardValidationPipeline._get_middleware = _mock_get_middleware  # type: ignore[assignment]

        try:
            spider = _make_spider()
            url = "https://example.com/product/2"
            pipeline.open_spider(spider)

            request = _make_request(url=url)
            response = _make_response(url=url)
            mw.process_response(request, response, spider)

            # Item with missing required field (price is not a float)
            bad_items = [
                {"title": "Good", "price": 10.0, "currency": "USD", "url": url},
                {"title": "Bad", "price": "not_a_number", "currency": "USD", "url": url},
                {"title": None, "price": 5.0, "currency": "USD", "url": url},
            ]

            for item in bad_items:
                pipeline.process_item(item, spider)

            pipeline.close_spider(spider)

            # Validation result should exist with failures recorded
            vr = storage.get_latest_validation_result(url, "ProductSchema")
            assert vr is not None
            assert vr.total_items == 3
            assert vr.failed_count > 0

        finally:
            ScraperGuardValidationPipeline._get_middleware = original_get_middleware  # type: ignore[assignment]


class TestMiddlewareSpiderClosed:
    """Test spider_closed updates run status correctly."""

    def test_completed_on_finished(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="test")

        mw = ScraperGuardObserverMiddleware(
            config=ScraperGuardConfig(),
            storage=storage,
            run_id=run.id,
        )
        spider = _make_spider()

        mw.spider_closed(spider, reason="finished")

        updated_run = storage.get_run(run.id)
        assert updated_run is not None
        assert updated_run.status == "completed"

    def test_failed_on_error(self, tmp_path: Any) -> None:
        storage = _make_storage(str(tmp_path))
        run = storage.create_run(scraper_name="test")

        mw = ScraperGuardObserverMiddleware(
            config=ScraperGuardConfig(),
            storage=storage,
            run_id=run.id,
        )
        spider = _make_spider()

        mw.spider_closed(spider, reason="shutdown")

        updated_run = storage.get_run(run.id)
        assert updated_run is not None
        assert updated_run.status == "failed"
