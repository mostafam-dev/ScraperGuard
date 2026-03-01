"""SQLite storage backend — local development and single-node deployments.

File-based storage suitable for development, testing, and small-scale
production. Zero external dependencies beyond the Python stdlib.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from scraperguard.storage.base import StorageBackend
from scraperguard.storage.models import (
    RunMetadata,
    Snapshot,
    SnapshotMetadata,
    ValidationResult,
    field_failure_from_dict,
    run_metadata_from_dict,
    snapshot_from_dict,
    snapshot_metadata_from_dict,
    validation_result_from_dict,
)


class SQLiteBackend(StorageBackend):
    """SQLite-backed storage for runs, snapshots, and validation results."""

    def __init__(self, db_path: str = "scraperguard.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        cursor = self._conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                scraper_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                config TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id),
                url TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                normalized_html TEXT NOT NULL,
                raw_html TEXT,
                extracted_items TEXT NOT NULL,
                metadata TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_url_timestamp "
            "ON snapshots(url, timestamp DESC)"
        )

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS validation_results (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id),
                url TEXT NOT NULL,
                schema_name TEXT NOT NULL,
                total_items INTEGER NOT NULL,
                passed_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                field_failures TEXT NOT NULL,
                null_ratios TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_vr_url_schema_timestamp "
            "ON validation_results(url, schema_name, timestamp DESC)"
        )

        self._conn.commit()

    # -- Run management -----------------------------------------------------

    def create_run(self, scraper_name: str, config: dict | None = None) -> RunMetadata:
        run = RunMetadata(scraper_name=scraper_name, config=config or {})
        self._conn.execute(
            "INSERT INTO runs (id, scraper_name, timestamp, config, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                run.id,
                run.scraper_name,
                run.timestamp.isoformat(),
                json.dumps(run.config),
                run.status,
            ),
        )
        self._conn.commit()
        return run

    def update_run_status(self, run_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ? WHERE id = ?",
            (status, run_id),
        )
        self._conn.commit()

    def list_runs(self, limit: int = 20) -> list[RunMetadata]:
        cursor = self._conn.execute(
            "SELECT id, scraper_name, timestamp, config, status FROM runs "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [
            run_metadata_from_dict({
                "id": row["id"],
                "scraper_name": row["scraper_name"],
                "timestamp": row["timestamp"],
                "config": json.loads(row["config"]),
                "status": row["status"],
            })
            for row in cursor.fetchall()
        ]

    def get_run(self, run_id: str) -> RunMetadata | None:
        cursor = self._conn.execute(
            "SELECT id, scraper_name, timestamp, config, status FROM runs WHERE id = ?",
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return run_metadata_from_dict({
            "id": row["id"],
            "scraper_name": row["scraper_name"],
            "timestamp": row["timestamp"],
            "config": json.loads(row["config"]),
            "status": row["status"],
        })

    # -- Snapshot persistence -----------------------------------------------

    def save_snapshot(self, snapshot: Snapshot) -> None:
        d = snapshot.to_dict()
        self._conn.execute(
            "INSERT INTO snapshots "
            "(id, run_id, url, fingerprint, normalized_html, raw_html, "
            "extracted_items, metadata, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                d["id"],
                d["run_id"],
                d["url"],
                d["fingerprint"],
                d["normalized_html"],
                d["raw_html"],
                json.dumps(d["extracted_items"]),
                json.dumps(d["metadata"]),
                d["timestamp"],
            ),
        )
        self._conn.commit()

    def _row_to_snapshot(self, row: sqlite3.Row) -> Snapshot:
        return snapshot_from_dict({
            "id": row["id"],
            "run_id": row["run_id"],
            "url": row["url"],
            "fingerprint": row["fingerprint"],
            "normalized_html": row["normalized_html"],
            "raw_html": row["raw_html"],
            "extracted_items": json.loads(row["extracted_items"]),
            "metadata": json.loads(row["metadata"]),
            "timestamp": row["timestamp"],
        })

    def get_snapshot_by_id(self, snapshot_id: str) -> Snapshot | None:
        cursor = self._conn.execute(
            "SELECT * FROM snapshots WHERE id = ?",
            (snapshot_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def get_latest_snapshot(self, url: str) -> Snapshot | None:
        cursor = self._conn.execute(
            "SELECT * FROM snapshots WHERE url = ? ORDER BY timestamp DESC LIMIT 1",
            (url,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def list_snapshots(self, url: str, limit: int = 10) -> list[Snapshot]:
        cursor = self._conn.execute(
            "SELECT * FROM snapshots WHERE url = ? ORDER BY timestamp DESC LIMIT ?",
            (url, limit),
        )
        return [self._row_to_snapshot(row) for row in cursor.fetchall()]

    # -- Validation result persistence --------------------------------------

    def save_validation_result(self, result: ValidationResult) -> None:
        d = result.to_dict()
        self._conn.execute(
            "INSERT INTO validation_results "
            "(id, run_id, url, schema_name, total_items, passed_count, "
            "failed_count, field_failures, null_ratios, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                d["id"],
                d["run_id"],
                d["url"],
                d["schema_name"],
                d["total_items"],
                d["passed_count"],
                d["failed_count"],
                json.dumps(d["field_failures"]),
                json.dumps(d["null_ratios"]),
                d["timestamp"],
            ),
        )
        self._conn.commit()

    def _row_to_validation_result(self, row: sqlite3.Row) -> ValidationResult:
        return validation_result_from_dict({
            "id": row["id"],
            "run_id": row["run_id"],
            "url": row["url"],
            "schema_name": row["schema_name"],
            "total_items": row["total_items"],
            "passed_count": row["passed_count"],
            "failed_count": row["failed_count"],
            "field_failures": json.loads(row["field_failures"]),
            "null_ratios": json.loads(row["null_ratios"]),
            "timestamp": row["timestamp"],
        })

    def get_latest_validation_result(
        self, url: str, schema_name: str
    ) -> ValidationResult | None:
        cursor = self._conn.execute(
            "SELECT * FROM validation_results "
            "WHERE url = ? AND schema_name = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (url, schema_name),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_validation_result(row)

    def get_latest_validation_result_by_url(self, url: str) -> ValidationResult | None:
        cursor = self._conn.execute(
            "SELECT * FROM validation_results "
            "WHERE url = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (url,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_validation_result(row)

    def list_validation_results(
        self, url: str, schema_name: str, limit: int = 10
    ) -> list[ValidationResult]:
        cursor = self._conn.execute(
            "SELECT * FROM validation_results "
            "WHERE url = ? AND schema_name = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (url, schema_name, limit),
        )
        return [self._row_to_validation_result(row) for row in cursor.fetchall()]
