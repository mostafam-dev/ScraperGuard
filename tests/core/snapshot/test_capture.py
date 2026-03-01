"""Tests for snapshot capture and should_diff."""

from datetime import datetime, timezone

from scraperguard.core.snapshot.capture import capture_snapshot, should_diff
from scraperguard.storage.models import SnapshotMetadata
from scraperguard.storage.sqlite import SQLiteBackend


def _make_metadata() -> SnapshotMetadata:
    return SnapshotMetadata(
        http_status=200,
        latency_ms=123.4,
        timestamp=datetime.now(timezone.utc),
        headers={"content-type": "text/html"},
        response_size_bytes=1024,
    )


def _make_storage() -> tuple[SQLiteBackend, str]:
    """Create an in-memory storage backend with a run already created."""
    storage = SQLiteBackend(":memory:")
    run = storage.create_run("test-scraper")
    return storage, run.id


RAW_HTML = """
<html>
<head><script>var x = 1;</script></head>
<body>
  <div class="product">
    <h1>Widget</h1>
    <span class="price">$79.99</span>
  </div>
</body>
</html>
"""


class TestCaptureSnapshot:
    def test_saves_to_storage(self):
        storage, run_id = _make_storage()
        snap = capture_snapshot(
            url="https://example.com/product",
            raw_html=RAW_HTML,
            extracted_items=[{"name": "Widget", "price": 79.99}],
            metadata=_make_metadata(),
            storage=storage,
            run_id=run_id,
        )
        retrieved = storage.get_snapshot_by_id(snap.id)
        assert retrieved is not None
        assert retrieved.id == snap.id
        assert retrieved.url == "https://example.com/product"

    def test_normalizes_html(self):
        storage, run_id = _make_storage()
        snap = capture_snapshot(
            url="https://example.com",
            raw_html=RAW_HTML,
            extracted_items=[],
            metadata=_make_metadata(),
            storage=storage,
            run_id=run_id,
        )
        assert "<script>" not in snap.normalized_html
        assert "var x = 1" not in snap.normalized_html

    def test_computes_fingerprint(self):
        storage, run_id = _make_storage()
        snap = capture_snapshot(
            url="https://example.com",
            raw_html=RAW_HTML,
            extracted_items=[],
            metadata=_make_metadata(),
            storage=storage,
            run_id=run_id,
        )
        assert snap.fingerprint
        assert len(snap.fingerprint) == 64  # SHA-256 hex

    def test_without_raw_html(self):
        storage, run_id = _make_storage()
        snap = capture_snapshot(
            url="https://example.com",
            raw_html=RAW_HTML,
            extracted_items=[],
            metadata=_make_metadata(),
            storage=storage,
            store_raw_html=False,
            run_id=run_id,
        )
        assert snap.raw_html is None

    def test_with_raw_html(self):
        storage, run_id = _make_storage()
        snap = capture_snapshot(
            url="https://example.com",
            raw_html=RAW_HTML,
            extracted_items=[],
            metadata=_make_metadata(),
            storage=storage,
            store_raw_html=True,
            run_id=run_id,
        )
        assert snap.raw_html == RAW_HTML


class TestShouldDiff:
    def test_different_fingerprints(self):
        assert should_diff("aaa", "bbb") is True

    def test_same_fingerprints(self):
        assert should_diff("aaa", "aaa") is False

    def test_no_previous(self):
        assert should_diff("aaa", None) is True
