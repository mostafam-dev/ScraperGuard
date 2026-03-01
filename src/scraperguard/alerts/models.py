"""Alert data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Alert:
    """A structured alert to be dispatched across channels."""

    severity: str  # "info" | "warning" | "critical"
    title: str
    message: str
    scraper_name: str
    url: str
    run_id: str
    timestamp: datetime = field(default_factory=_utcnow)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON transport."""
        return {
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "scraper_name": self.scraper_name,
            "url": self.url,
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }
