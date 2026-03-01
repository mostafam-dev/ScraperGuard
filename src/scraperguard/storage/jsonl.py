"""JSONL storage backend — lightweight, human-readable event log.

Appends events as newline-delimited JSON. Useful for debugging,
export, and environments where no database is available.
"""

from __future__ import annotations

from typing import Any

from scraperguard.storage.base import StorageBackend
from scraperguard.storage.models import RunMetadata, Snapshot, ValidationResult


class JSONLBackend(StorageBackend):
    """JSONL file-backed storage for snapshots and events."""

    def __init__(self, directory: str = ".scraperguard") -> None:
        self.directory = directory

    def create_run(self, scraper_name: str, config: dict[str, Any] | None = None) -> RunMetadata:
        raise NotImplementedError

    def update_run_status(self, run_id: str, status: str) -> None:
        raise NotImplementedError

    def list_runs(self, limit: int = 20) -> list[RunMetadata]:
        raise NotImplementedError

    def get_run(self, run_id: str) -> RunMetadata | None:
        raise NotImplementedError

    def save_snapshot(self, snapshot: Snapshot) -> None:
        raise NotImplementedError

    def get_snapshot_by_id(self, snapshot_id: str) -> Snapshot | None:
        raise NotImplementedError

    def get_latest_snapshot(self, url: str) -> Snapshot | None:
        raise NotImplementedError

    def list_snapshots(self, url: str, limit: int = 10) -> list[Snapshot]:
        raise NotImplementedError

    def save_validation_result(self, result: ValidationResult) -> None:
        raise NotImplementedError

    def get_latest_validation_result(self, url: str, schema_name: str) -> ValidationResult | None:
        raise NotImplementedError

    def get_latest_validation_result_by_url(self, url: str) -> ValidationResult | None:
        raise NotImplementedError

    def list_validation_results(
        self, url: str, schema_name: str, limit: int = 10
    ) -> list[ValidationResult]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
