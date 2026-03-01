"""Drift tracker — time-series stability analysis for scraper reliability.

Appends validation and diff results to the event store, then computes
running statistics: field stability, selector lifespan, domain volatility,
and mean time to failure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DriftStats:
    """Aggregated drift statistics for a URL or domain."""

    field_stability: dict[str, float]  # field name -> stability score 0-1
    selector_lifespans: dict[str, int]  # selector -> average runs before break
    domain_volatility: float  # 0 = stable, 1 = highly volatile
    mean_time_to_failure: float | None  # average runs between breaks
    change_frequency_days: float | None  # estimated days between structural changes


class DriftTracker:
    """Manages drift state and computes stability metrics.

    Receives events from the validation and diff engines, persists
    them to the event store, and provides statistical queries.
    """

    def record_event(self, url: str, event: dict) -> None:
        """Append a validation or diff event to the time-series store.

        Args:
            url: The URL this event pertains to.
            event: Structured event data (validation result, diff report, etc.).
        """
        raise NotImplementedError

    def get_stats(self, url: str) -> DriftStats:
        """Compute current drift statistics for a URL.

        Args:
            url: The URL to analyze.

        Returns:
            DriftStats with stability scores and trend data.
        """
        raise NotImplementedError

    def get_domain_stats(self, domain: str) -> DriftStats:
        """Compute aggregated drift statistics across all URLs for a domain.

        Args:
            domain: The domain (e.g., "example.com") to analyze.

        Returns:
            DriftStats aggregated across all tracked URLs under this domain.
        """
        raise NotImplementedError
