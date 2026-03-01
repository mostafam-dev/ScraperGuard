"""Pluggable storage backends — PostgreSQL, SQLite, JSONL.

All backends implement a common StorageBackend interface for persisting
snapshots, validation results, diff reports, and drift events.
The active backend is selected via configuration.
"""

from scraperguard.storage.base import StorageBackend
from scraperguard.storage.models import (
    FieldFailure,
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
from scraperguard.storage.sqlite import SQLiteBackend

__all__ = [
    "StorageBackend",
    "SQLiteBackend",
    "FieldFailure",
    "RunMetadata",
    "Snapshot",
    "SnapshotMetadata",
    "ValidationResult",
    "field_failure_from_dict",
    "run_metadata_from_dict",
    "snapshot_from_dict",
    "snapshot_metadata_from_dict",
    "validation_result_from_dict",
]
