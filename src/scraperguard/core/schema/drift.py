"""Null ratio drift detection across validation runs.

Compares current null ratios against historical baselines to detect
significant shifts. A field going from 3% null to 80% null is an early
warning that the scraper or the target site broke.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scraperguard.storage.models import ValidationResult

if TYPE_CHECKING:
    from scraperguard.storage.base import StorageBackend


@dataclass
class DriftEvent:
    """A detected shift in null ratio for a single field."""

    field_name: str
    current_ratio: float
    baseline_ratio: float
    delta: float
    severity: str  # "info" | "warning" | "critical"
    message: str


def compute_baseline_ratios(
    validation_results: list[ValidationResult],
) -> dict[str, float]:
    """Compute average null ratios across historical validation results.

    Args:
        validation_results: Historical results ordered newest first.

    Returns:
        Mapping of field name to average null ratio. Empty dict if no
        results are provided.
    """
    if not validation_results:
        return {}

    field_sums: dict[str, float] = defaultdict(float)
    field_counts: dict[str, int] = defaultdict(int)

    for result in validation_results:
        for field_name, ratio in result.null_ratios.items():
            field_sums[field_name] += ratio
            field_counts[field_name] += 1

    return {
        field_name: field_sums[field_name] / field_counts[field_name]
        for field_name in field_sums
    }


def detect_null_drift(
    current_ratios: dict[str, float],
    baseline_ratios: dict[str, float],
    threshold: float = 0.15,
) -> list[DriftEvent]:
    """Compare current null ratios against baseline and flag significant shifts.

    Args:
        current_ratios: Per-field null ratios from the current run.
        baseline_ratios: Per-field average null ratios from historical runs.
        threshold: Minimum absolute delta to report. Defaults to 0.15.

    Returns:
        List of DriftEvents sorted by abs(delta) descending.
    """
    events: list[DriftEvent] = []

    for field_name, current in current_ratios.items():
        if field_name not in baseline_ratios:
            continue

        baseline = baseline_ratios[field_name]
        delta = current - baseline

        if abs(delta) <= threshold:
            continue

        if abs(delta) > 0.5:
            severity = "critical"
        elif abs(delta) > 0.3:
            severity = "warning"
        else:
            severity = "info"

        if delta > 0:
            message = (
                f"Field '{field_name}' null ratio increased from "
                f"{baseline:.1%} to {current:.1%} (+{delta:.1%})"
            )
        else:
            message = (
                f"Field '{field_name}' null ratio decreased from "
                f"{baseline:.1%} to {current:.1%} ({delta:.1%})"
            )

        events.append(
            DriftEvent(
                field_name=field_name,
                current_ratio=current,
                baseline_ratio=baseline,
                delta=delta,
                severity=severity,
                message=message,
            )
        )

    events.sort(key=lambda e: abs(e.delta), reverse=True)
    return events


def run_drift_analysis(
    current_result: ValidationResult,
    storage: StorageBackend,
    baseline_count: int = 5,
    threshold: float = 0.15,
) -> list[DriftEvent]:
    """Run end-to-end drift analysis for a validation result.

    Retrieves historical results from storage, computes baselines, and
    detects drift against the current result's null ratios.

    Args:
        current_result: The validation result from the current run.
        storage: Storage backend to retrieve historical results from.
        baseline_count: Number of historical results to average over.
        threshold: Minimum absolute delta to report.

    Returns:
        List of DriftEvents sorted by abs(delta) descending, or empty
        list if no historical data exists.
    """
    historical = storage.list_validation_results(
        url=current_result.url,
        schema_name=current_result.schema_name,
        limit=baseline_count,
    )

    if not historical:
        return []

    baseline = compute_baseline_ratios(historical)
    return detect_null_drift(current_result.null_ratios, baseline, threshold)
