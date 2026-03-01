"""Tests for configuration loading and environment variable interpolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scraperguard.config import (
    AlertsConfig,
    AlertThresholds,
    ScraperGuardConfig,
    SchemaConfig,
    SlackAlertConfig,
    SnapshotConfig,
    StorageConfig,
    get_storage_backend,
    load_config,
)
from scraperguard.storage.sqlite import SQLiteBackend


class TestDefaultConfig:
    def test_default_config(self) -> None:
        cfg = ScraperGuardConfig()

        # Schema defaults
        assert cfg.schema.strict is True
        assert cfg.schema.null_drift_threshold == 0.15

        # Storage defaults
        assert cfg.storage.backend == "sqlite"
        assert cfg.storage.connection == "scraperguard.db"

        # Alerts defaults
        assert cfg.alerts.slack.enabled is False
        assert cfg.alerts.slack.webhook == ""
        assert cfg.alerts.email_enabled is False
        assert cfg.alerts.webhook_url == ""
        assert cfg.alerts.thresholds.health_score == 60
        assert cfg.alerts.thresholds.schema_failure == "critical"
        assert cfg.alerts.thresholds.selector_break == "warning"

        # Snapshot defaults
        assert cfg.snapshots.store_raw_html is False
        assert cfg.snapshots.retention_days == 30


class TestLoadFromYaml:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
schema:
  strict: false
  null_drift_threshold: 0.25
storage:
  backend: sqlite
  connection: /tmp/test.db
alerts:
  slack:
    enabled: true
    webhook: https://hooks.slack.test/xyz
  thresholds:
    health_score: 40
snapshots:
  store_raw_html: true
"""
        config_file = tmp_path / "scraperguard.yaml"
        config_file.write_text(yaml_content)

        cfg = load_config(str(config_file))

        # Overridden values
        assert cfg.schema.strict is False
        assert cfg.schema.null_drift_threshold == 0.25
        assert cfg.storage.backend == "sqlite"
        assert cfg.storage.connection == "/tmp/test.db"
        assert cfg.alerts.slack.enabled is True
        assert cfg.alerts.slack.webhook == "https://hooks.slack.test/xyz"
        assert cfg.alerts.thresholds.health_score == 40
        assert cfg.snapshots.store_raw_html is True

        # Non-overridden values keep defaults
        assert cfg.alerts.email_enabled is False
        assert cfg.alerts.webhook_url == ""
        assert cfg.alerts.thresholds.schema_failure == "critical"
        assert cfg.alerts.thresholds.selector_break == "warning"
        assert cfg.snapshots.retention_days == 30


class TestEnvVarInterpolation:
    def test_env_var_interpolation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_DB_URL", "postgresql://user:pass@localhost/scraper")
        monkeypatch.setenv("TEST_SLACK_HOOK", "https://hooks.slack.test/secret")

        yaml_content = """\
storage:
  backend: sqlite
  connection: ${TEST_DB_URL}
alerts:
  slack:
    enabled: true
    webhook: ${TEST_SLACK_HOOK}
"""
        config_file = tmp_path / "scraperguard.yaml"
        config_file.write_text(yaml_content)

        cfg = load_config(str(config_file))

        assert cfg.storage.connection == "postgresql://user:pass@localhost/scraper"
        assert cfg.alerts.slack.webhook == "https://hooks.slack.test/secret"

    def test_unset_env_var_becomes_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEFINITELY_NOT_SET_XYZ", raising=False)

        yaml_content = """\
storage:
  connection: ${DEFINITELY_NOT_SET_XYZ}
"""
        config_file = tmp_path / "scraperguard.yaml"
        config_file.write_text(yaml_content)

        cfg = load_config(str(config_file))
        assert cfg.storage.connection == ""


class TestMissingFile:
    def test_missing_file_returns_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SCRAPERGUARD_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)

        cfg = load_config(None)
        default = ScraperGuardConfig()

        assert cfg == default


class TestGetStorageBackend:
    def test_get_storage_backend_sqlite(self) -> None:
        cfg = ScraperGuardConfig(
            storage=StorageConfig(backend="sqlite", connection=":memory:")
        )
        backend = get_storage_backend(cfg)
        assert isinstance(backend, SQLiteBackend)

    def test_get_storage_backend_postgres_not_implemented(self) -> None:
        cfg = ScraperGuardConfig(
            storage=StorageConfig(backend="postgres", connection="postgresql://localhost/db")
        )
        with pytest.raises(NotImplementedError, match="PostgreSQL"):
            get_storage_backend(cfg)

    def test_get_storage_backend_jsonl_not_implemented(self) -> None:
        cfg = ScraperGuardConfig(
            storage=StorageConfig(backend="jsonl", connection="/tmp/events")
        )
        with pytest.raises(NotImplementedError, match="JSONL"):
            get_storage_backend(cfg)
