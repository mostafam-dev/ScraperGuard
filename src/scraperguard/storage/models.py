"""Pure data containers for the storage layer.

These dataclasses represent the core domain objects persisted by storage
backends. They carry no business logic, validation logic, or database
logic — only structure and serialization helpers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RunMetadata
# ---------------------------------------------------------------------------


@dataclass
class RunMetadata:
    """Metadata for a single scraper run."""

    scraper_name: str
    id: str = field(default_factory=_uuid4)
    timestamp: datetime = field(default_factory=_utcnow)
    config: dict = field(default_factory=dict)
    status: str = "running"  # "running" | "completed" | "failed"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scraper_name": self.scraper_name,
            "timestamp": self.timestamp.isoformat(),
            "config": self.config,
            "status": self.status,
        }


def run_metadata_from_dict(data: dict) -> RunMetadata:
    """Reconstruct a RunMetadata from a plain dict."""
    return RunMetadata(
        id=data["id"],
        scraper_name=data["scraper_name"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        config=data.get("config", {}),
        status=data.get("status", "running"),
    )


# ---------------------------------------------------------------------------
# SnapshotMetadata
# ---------------------------------------------------------------------------


@dataclass
class SnapshotMetadata:
    """HTTP-level metadata captured alongside a DOM snapshot."""

    http_status: int
    latency_ms: float
    timestamp: datetime
    headers: dict
    response_size_bytes: int

    def to_dict(self) -> dict:
        return {
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "headers": self.headers,
            "response_size_bytes": self.response_size_bytes,
        }


def snapshot_metadata_from_dict(data: dict) -> SnapshotMetadata:
    """Reconstruct a SnapshotMetadata from a plain dict."""
    return SnapshotMetadata(
        http_status=data["http_status"],
        latency_ms=data["latency_ms"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        headers=data.get("headers", {}),
        response_size_bytes=data["response_size_bytes"],
    )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass
class Snapshot:
    """Immutable record of a single page observation."""

    run_id: str
    url: str
    normalized_html: str
    fingerprint: str
    metadata: SnapshotMetadata
    id: str = field(default_factory=_uuid4)
    raw_html: str | None = None
    extracted_items: list[dict] = field(default_factory=list)
    timestamp: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "url": self.url,
            "normalized_html": self.normalized_html,
            "fingerprint": self.fingerprint,
            "raw_html": self.raw_html,
            "extracted_items": self.extracted_items,
            "metadata": self.metadata.to_dict(),
            "timestamp": self.timestamp.isoformat(),
        }

    def to_summary_dict(self) -> dict:
        """Lightweight dict excluding large HTML fields."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "url": self.url,
            "fingerprint": self.fingerprint,
            "extracted_items": self.extracted_items,
            "metadata": self.metadata.to_dict(),
            "timestamp": self.timestamp.isoformat(),
        }


def snapshot_from_dict(data: dict) -> Snapshot:
    """Reconstruct a Snapshot from a plain dict."""
    return Snapshot(
        id=data["id"],
        run_id=data["run_id"],
        url=data["url"],
        normalized_html=data["normalized_html"],
        fingerprint=data["fingerprint"],
        raw_html=data.get("raw_html"),
        extracted_items=data.get("extracted_items", []),
        metadata=snapshot_metadata_from_dict(data["metadata"]),
        timestamp=datetime.fromisoformat(data["timestamp"]),
    )


# ---------------------------------------------------------------------------
# FieldFailure
# ---------------------------------------------------------------------------


@dataclass
class FieldFailure:
    """A single field-level validation failure."""

    field_name: str
    failure_type: str  # "missing" | "type_mismatch" | "null" | "out_of_range"
    count: int

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "failure_type": self.failure_type,
            "count": self.count,
        }


def field_failure_from_dict(data: dict) -> FieldFailure:
    """Reconstruct a FieldFailure from a plain dict."""
    return FieldFailure(
        field_name=data["field_name"],
        failure_type=data["failure_type"],
        count=data["count"],
    )


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Result of schema validation for a batch of extracted items."""

    run_id: str
    url: str
    schema_name: str
    total_items: int
    passed_count: int
    failed_count: int
    field_failures: list[FieldFailure]
    null_ratios: dict[str, float]
    id: str = field(default_factory=_uuid4)
    timestamp: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "url": self.url,
            "schema_name": self.schema_name,
            "total_items": self.total_items,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "field_failures": [f.to_dict() for f in self.field_failures],
            "null_ratios": self.null_ratios,
            "timestamp": self.timestamp.isoformat(),
        }


def validation_result_from_dict(data: dict) -> ValidationResult:
    """Reconstruct a ValidationResult from a plain dict."""
    return ValidationResult(
        id=data["id"],
        run_id=data["run_id"],
        url=data["url"],
        schema_name=data["schema_name"],
        total_items=data["total_items"],
        passed_count=data["passed_count"],
        failed_count=data["failed_count"],
        field_failures=[field_failure_from_dict(f) for f in data.get("field_failures", [])],
        null_ratios=data.get("null_ratios", {}),
        timestamp=datetime.fromisoformat(data["timestamp"]),
    )
