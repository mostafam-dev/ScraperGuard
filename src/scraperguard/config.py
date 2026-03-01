"""Configuration loading and management.

Loads scraperguard.yaml configuration with 12-factor compatible environment
variable interpolation. Provides typed configuration dataclasses and a
factory function for the storage backend.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from scraperguard.storage.base import StorageBackend

# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SchemaConfig:
    """Schema validation settings."""

    strict: bool = True
    null_drift_threshold: float = 0.15


@dataclass
class StorageConfig:
    """Storage backend settings."""

    backend: str = "sqlite"  # "sqlite" | "postgres" | "jsonl"
    connection: str = "scraperguard.db"


@dataclass
class SlackAlertConfig:
    """Slack alert channel settings."""

    enabled: bool = False
    webhook: str = ""


@dataclass
class AlertThresholds:
    """Alert severity thresholds."""

    health_score: int = 60
    schema_failure: str = "critical"  # "critical" | "warning" | "info"
    selector_break: str = "warning"


@dataclass
class AlertsConfig:
    """Alerting configuration."""

    slack: SlackAlertConfig = field(default_factory=SlackAlertConfig)
    email_enabled: bool = False
    webhook_url: str = ""
    thresholds: AlertThresholds = field(default_factory=AlertThresholds)


@dataclass
class SnapshotConfig:
    """Snapshot storage settings."""

    store_raw_html: bool = False
    retention_days: int = 30


@dataclass
class ScraperGuardConfig:
    """Top-level application configuration."""

    schema: SchemaConfig = field(default_factory=SchemaConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    snapshots: SnapshotConfig = field(default_factory=SnapshotConfig)


# ---------------------------------------------------------------------------
# Environment variable interpolation
# ---------------------------------------------------------------------------

_ENV_VAR_PATTERN = re.compile(r"^\$\{([^}]+)\}$")


def _interpolate_env_vars(data: Any) -> Any:
    """Recursively replace ${VAR_NAME} strings with environment variable values."""
    if isinstance(data, str):
        match = _ENV_VAR_PATTERN.match(data)
        if match:
            return os.environ.get(match.group(1), "")
        return data
    if isinstance(data, dict):
        return {k: _interpolate_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_interpolate_env_vars(item) for item in data]
    return data


# ---------------------------------------------------------------------------
# Config merging helpers
# ---------------------------------------------------------------------------


def _merge_schema(raw: dict) -> SchemaConfig:
    cfg = SchemaConfig()
    if "strict" in raw:
        cfg.strict = raw["strict"]
    if "null_drift_threshold" in raw:
        cfg.null_drift_threshold = float(raw["null_drift_threshold"])
    return cfg


def _merge_storage(raw: dict) -> StorageConfig:
    cfg = StorageConfig()
    if "backend" in raw:
        cfg.backend = raw["backend"]
    if "connection" in raw:
        cfg.connection = raw["connection"]
    return cfg


def _merge_slack(raw: dict) -> SlackAlertConfig:
    cfg = SlackAlertConfig()
    if "enabled" in raw:
        cfg.enabled = raw["enabled"]
    if "webhook" in raw:
        cfg.webhook = raw["webhook"]
    return cfg


def _merge_thresholds(raw: dict) -> AlertThresholds:
    cfg = AlertThresholds()
    if "health_score" in raw:
        cfg.health_score = int(raw["health_score"])
    if "schema_failure" in raw:
        cfg.schema_failure = raw["schema_failure"]
    if "selector_break" in raw:
        cfg.selector_break = raw["selector_break"]
    return cfg


def _merge_alerts(raw: dict) -> AlertsConfig:
    cfg = AlertsConfig()
    if "slack" in raw:
        cfg.slack = _merge_slack(raw["slack"])
    if "email_enabled" in raw:
        cfg.email_enabled = raw["email_enabled"]
    if "webhook_url" in raw:
        cfg.webhook_url = raw["webhook_url"]
    if "thresholds" in raw:
        cfg.thresholds = _merge_thresholds(raw["thresholds"])
    return cfg


def _merge_snapshots(raw: dict) -> SnapshotConfig:
    cfg = SnapshotConfig()
    if "store_raw_html" in raw:
        cfg.store_raw_html = raw["store_raw_html"]
    if "retention_days" in raw:
        cfg.retention_days = int(raw["retention_days"])
    return cfg


def _merge_config(raw: dict) -> ScraperGuardConfig:
    """Merge a raw YAML dict into a ScraperGuardConfig, keeping defaults for missing fields."""
    cfg = ScraperGuardConfig()
    if "schema" in raw:
        cfg.schema = _merge_schema(raw["schema"])
    if "storage" in raw:
        cfg.storage = _merge_storage(raw["storage"])
    if "alerts" in raw:
        cfg.alerts = _merge_alerts(raw["alerts"])
    if "snapshots" in raw:
        cfg.snapshots = _merge_snapshots(raw["snapshots"])
    return cfg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: str | None = None) -> ScraperGuardConfig:
    """Load configuration from a YAML file with environment variable interpolation.

    Resolution order:
      1. Explicit *path* argument
      2. SCRAPERGUARD_CONFIG environment variable
      3. scraperguard.yaml in the current working directory
      4. scraperguard.yml in the current working directory
      5. Default ScraperGuardConfig() if nothing is found

    Any string value in the YAML matching ``${VAR_NAME}`` is replaced with
    the value of the corresponding environment variable (empty string if unset).

    Args:
        path: Optional explicit path to a YAML config file.

    Returns:
        Fully resolved ScraperGuardConfig instance.
    """
    config_path: Path | None = None

    if path is not None:
        config_path = Path(path)
    elif "SCRAPERGUARD_CONFIG" in os.environ:
        config_path = Path(os.environ["SCRAPERGUARD_CONFIG"])
    else:
        for name in ("scraperguard.yaml", "scraperguard.yml"):
            candidate = Path.cwd() / name
            if candidate.is_file():
                config_path = candidate
                break

    if config_path is None or not config_path.is_file():
        return ScraperGuardConfig()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return ScraperGuardConfig()

    raw = _interpolate_env_vars(raw)
    return _merge_config(raw)


def get_storage_backend(config: ScraperGuardConfig) -> StorageBackend:
    """Return a StorageBackend instance based on the configuration.

    Args:
        config: The application configuration.

    Returns:
        A concrete StorageBackend.

    Raises:
        NotImplementedError: If the configured backend is not yet implemented.
    """
    backend = config.storage.backend

    if backend == "sqlite":
        from scraperguard.storage.sqlite import SQLiteBackend

        return SQLiteBackend(db_path=config.storage.connection)

    if backend == "postgres":
        raise NotImplementedError("PostgreSQL backend not yet implemented")

    if backend == "jsonl":
        raise NotImplementedError("JSONL backend not yet implemented")

    raise ValueError(f"Unknown storage backend: {backend!r}")
