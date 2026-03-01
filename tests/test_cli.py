"""Tests for the CLI command group."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from scraperguard.cli.main import cli
from scraperguard.cli.utils import SchemaLoadError, load_schema_from_file
from scraperguard.core.schema.base import BaseSchema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<html>
<body>
  <div class="product">
    <h1 class="title">Widget</h1>
    <span class="price">$9.99</span>
    <span class="stock">In Stock</span>
  </div>
</body>
</html>
"""

SAMPLE_ITEMS = [
    {"title": "Widget", "price": 9.99, "in_stock": True},
    {"title": "Gadget", "price": 19.99, "in_stock": False},
]

SCHEMA_FILE_CONTENT = """\
from scraperguard.core.schema.base import BaseSchema


class ProductSchema(BaseSchema):
    title: str
    price: float
    in_stock: bool
"""


def _write_json_file(tmp_dir: str, data: dict) -> str:
    """Write a JSON file and return its path."""
    path = os.path.join(tmp_dir, "input.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def _write_schema_file(tmp_dir: str) -> str:
    """Write a schema Python file and return its path."""
    path = os.path.join(tmp_dir, "schema.py")
    with open(path, "w") as f:
        f.write(SCHEMA_FILE_CONTENT)
    return path


# ---------------------------------------------------------------------------
# Basic CLI tests
# ---------------------------------------------------------------------------


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "ScraperGuard" in result.output


# ---------------------------------------------------------------------------
# run command tests
# ---------------------------------------------------------------------------


def test_run_with_json_file(tmp_path: Path) -> None:
    """Invoke 'run' with a JSON file containing url, html, items."""
    json_data = {
        "url": "http://example.com/products",
        "html": SAMPLE_HTML,
        "items": SAMPLE_ITEMS,
    }
    json_path = str(tmp_path / "input.json")
    with open(json_path, "w") as f:
        json.dump(json_data, f)

    # Use isolated filesystem to avoid polluting cwd with sqlite db
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["run", json_path])

    assert result.exit_code == 0, f"Output: {result.output}\nException: {result.exception}"
    assert "Health Score" in result.output


def test_run_with_schema(tmp_path: Path) -> None:
    """Invoke 'run' with a JSON file and a schema file."""
    json_data = {
        "url": "http://example.com/products",
        "html": SAMPLE_HTML,
        "items": SAMPLE_ITEMS,
    }
    json_path = str(tmp_path / "input.json")
    with open(json_path, "w") as f:
        json.dump(json_data, f)

    schema_path = str(tmp_path / "schema.py")
    with open(schema_path, "w") as f:
        f.write(SCHEMA_FILE_CONTENT)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["run", json_path, "--schema", schema_path])

    assert result.exit_code == 0, f"Output: {result.output}\nException: {result.exception}"
    assert "Schema validation" in result.output
    assert "Health Score" in result.output


def test_run_with_selectors(tmp_path: Path) -> None:
    """Invoke 'run' with --selectors flag."""
    json_data = {
        "url": "http://example.com/products",
        "html": SAMPLE_HTML,
        "items": SAMPLE_ITEMS,
    }
    json_path = str(tmp_path / "input.json")
    with open(json_path, "w") as f:
        json.dump(json_data, f)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["run", json_path, "--selectors", ".price,.title"])

    assert result.exit_code == 0, f"Output: {result.output}\nException: {result.exception}"
    assert "Selector tracking" in result.output or "selector" in result.output.lower()


# ---------------------------------------------------------------------------
# validate command tests
# ---------------------------------------------------------------------------


def test_validate_no_snapshot(tmp_path: Path) -> None:
    """Invoke 'validate' for a URL with no stored snapshot."""
    schema_path = str(tmp_path / "schema.py")
    with open(schema_path, "w") as f:
        f.write(SCHEMA_FILE_CONTENT)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["validate", "--url", "http://nonexistent.example.com", "--schema", schema_path],
        )

    assert result.exit_code != 0
    assert "No snapshot found" in result.output or "no snapshot" in result.output.lower()


# ---------------------------------------------------------------------------
# diff command tests
# ---------------------------------------------------------------------------


def test_diff_insufficient_snapshots(tmp_path: Path) -> None:
    """Invoke 'diff' with no stored snapshots."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["diff", "--url", "http://example.com"])

    assert result.exit_code != 0
    assert "Need at least 2 snapshots" in result.output or "2 snapshots" in result.output


# ---------------------------------------------------------------------------
# report command tests
# ---------------------------------------------------------------------------


def test_report_json_format(tmp_path: Path) -> None:
    """Pre-populate storage with a snapshot and get JSON report."""
    from scraperguard.config import get_storage_backend, load_config
    from scraperguard.core.snapshot.capture import capture_snapshot
    from scraperguard.storage.models import SnapshotMetadata

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Pre-populate storage
        cfg = load_config()
        storage = get_storage_backend(cfg)
        run_meta = storage.create_run(scraper_name="test")

        metadata = SnapshotMetadata(
            http_status=200,
            latency_ms=100.0,
            timestamp=datetime.now(timezone.utc),
            headers={},
            response_size_bytes=len(SAMPLE_HTML),
        )
        capture_snapshot(
            url="http://example.com/report-test",
            raw_html=SAMPLE_HTML,
            extracted_items=SAMPLE_ITEMS,
            metadata=metadata,
            storage=storage,
            run_id=run_meta.id,
        )

        result = runner.invoke(
            cli,
            ["report", "--url", "http://example.com/report-test", "--format", "json"],
        )

    assert result.exit_code == 0, f"Output: {result.output}\nException: {result.exception}"
    parsed = json.loads(result.output)
    assert "overall_score" in parsed
    assert "status" in parsed
    assert "url" in parsed


# ---------------------------------------------------------------------------
# load_schema_from_file tests
# ---------------------------------------------------------------------------


def test_load_schema_from_file(tmp_path: Path) -> None:
    """Create temp Python file with schema, load it, verify it's a BaseSchema subclass."""
    schema_path = str(tmp_path / "my_schema.py")
    with open(schema_path, "w") as f:
        f.write(SCHEMA_FILE_CONTENT)

    schema_cls = load_schema_from_file(schema_path)
    assert issubclass(schema_cls, BaseSchema)
    assert schema_cls.__name__ == "ProductSchema"


def test_load_schema_file_not_found() -> None:
    """Nonexistent path raises clear error."""
    with pytest.raises(SchemaLoadError, match="not found"):
        load_schema_from_file("/nonexistent/path/schema.py")


def test_load_schema_no_subclass(tmp_path: Path) -> None:
    """File without BaseSchema subclass raises clear error."""
    schema_path = str(tmp_path / "empty_schema.py")
    with open(schema_path, "w") as f:
        f.write("x = 42\n")

    with pytest.raises(SchemaLoadError, match="No BaseSchema subclass"):
        load_schema_from_file(schema_path)


# ---------------------------------------------------------------------------
# serve command test
# ---------------------------------------------------------------------------


def test_serve_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """serve command calls uvicorn.run with correct arguments."""
    calls: list[tuple] = []

    def fake_run(app: object, host: str, port: int) -> None:
        calls.append((app, host, port))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][1] == "0.0.0.0"
    assert calls[0][2] == 9000
