"""Tests for null ratio drift detection."""

from __future__ import annotations

import pytest

from scraperguard.core.schema.drift import (
    DriftEvent,
    compute_baseline_ratios,
    detect_null_drift,
    run_drift_analysis,
)
from scraperguard.storage.models import ValidationResult
from scraperguard.storage.sqlite import SQLiteBackend


def _make_result(
    null_ratios: dict[str, float],
    url: str = "https://example.com/products",
    schema_name: str = "ProductSchema",
    run_id: str = "run-1",
) -> ValidationResult:
    """Helper to create a ValidationResult with given null ratios."""
    return ValidationResult(
        run_id=run_id,
        url=url,
        schema_name=schema_name,
        total_items=100,
        passed_count=90,
        failed_count=10,
        field_failures=[],
        null_ratios=null_ratios,
    )


class TestComputeBaselineRatios:
    def test_compute_baseline_single_result(self) -> None:
        results = [_make_result({"price": 0.03, "title": 0.0})]
        baseline = compute_baseline_ratios(results)
        assert baseline == {"price": 0.03, "title": 0.0}

    def test_compute_baseline_multiple_results(self) -> None:
        results = [
            _make_result({"price": 0.02}),
            _make_result({"price": 0.04}),
            _make_result({"price": 0.03}),
        ]
        baseline = compute_baseline_ratios(results)
        assert baseline["price"] == pytest.approx(0.03)

    def test_compute_baseline_empty(self) -> None:
        assert compute_baseline_ratios([]) == {}


class TestDetectNullDrift:
    def test_detect_drift_above_threshold(self) -> None:
        events = detect_null_drift(
            current_ratios={"price": 0.82},
            baseline_ratios={"price": 0.03},
        )
        assert len(events) == 1
        event = events[0]
        assert event.field_name == "price"
        assert event.delta == pytest.approx(0.79)
        assert event.severity == "critical"

    def test_detect_drift_below_threshold(self) -> None:
        events = detect_null_drift(
            current_ratios={"price": 0.05},
            baseline_ratios={"price": 0.03},
        )
        assert len(events) == 0

    def test_detect_drift_severity_levels(self) -> None:
        # delta 0.55 -> critical
        events = detect_null_drift(
            current_ratios={"a": 0.60},
            baseline_ratios={"a": 0.05},
        )
        assert events[0].severity == "critical"

        # delta 0.35 -> warning
        events = detect_null_drift(
            current_ratios={"a": 0.40},
            baseline_ratios={"a": 0.05},
        )
        assert events[0].severity == "warning"

        # delta 0.18 -> info
        events = detect_null_drift(
            current_ratios={"a": 0.20},
            baseline_ratios={"a": 0.02},
        )
        assert events[0].severity == "info"

    def test_detect_drift_negative_delta(self) -> None:
        events = detect_null_drift(
            current_ratios={"price": 0.01},
            baseline_ratios={"price": 0.30},
        )
        assert len(events) == 1
        event = events[0]
        assert event.delta == pytest.approx(-0.29)
        assert event.current_ratio == 0.01
        assert event.baseline_ratio == 0.30

    def test_detect_drift_new_field_skipped(self) -> None:
        events = detect_null_drift(
            current_ratios={"new_field": 0.50},
            baseline_ratios={"price": 0.03},
        )
        assert len(events) == 0

    def test_detect_drift_sorted_by_severity(self) -> None:
        events = detect_null_drift(
            current_ratios={"a": 0.20, "b": 0.60, "c": 0.40},
            baseline_ratios={"a": 0.02, "b": 0.02, "c": 0.02},
        )
        deltas = [abs(e.delta) for e in events]
        assert deltas == sorted(deltas, reverse=True)

    def test_detect_drift_message_format(self) -> None:
        events = detect_null_drift(
            current_ratios={"price": 0.82},
            baseline_ratios={"price": 0.03},
        )
        msg = events[0].message
        assert "price" in msg
        assert "3.0%" in msg
        assert "82.0%" in msg
        assert "+" in msg

        # Negative delta message
        events = detect_null_drift(
            current_ratios={"price": 0.01},
            baseline_ratios={"price": 0.30},
        )
        msg = events[0].message
        assert "decreased" in msg
        assert "-" in msg


class TestRunDriftAnalysis:
    def test_run_drift_analysis_integration(self) -> None:
        storage = SQLiteBackend(":memory:")
        run = storage.create_run("test-scraper")

        # Save 3 historical results with low null ratios
        for i in range(3):
            result = _make_result(
                {"price": 0.03, "title": 0.01},
                run_id=run.id,
            )
            storage.save_validation_result(result)

        # Current result with high null ratios
        current = _make_result(
            {"price": 0.85, "title": 0.70},
            run_id=run.id,
        )

        events = run_drift_analysis(current, storage)
        assert len(events) == 2
        # Sorted by abs(delta) descending
        assert events[0].field_name == "price"
        assert events[0].severity == "critical"
        assert events[1].field_name == "title"
        assert events[1].severity == "critical"

    def test_run_drift_analysis_first_run(self) -> None:
        storage = SQLiteBackend(":memory:")
        storage.create_run("test-scraper")

        current = _make_result({"price": 0.85})
        events = run_drift_analysis(current, storage)
        assert events == []

    def test_run_drift_analysis_custom_threshold(self) -> None:
        storage = SQLiteBackend(":memory:")
        run = storage.create_run("test-scraper")

        # Save a historical result with price at 0.03
        result = _make_result({"price": 0.03}, run_id=run.id)
        storage.save_validation_result(result)

        # Current has price at 0.10 — delta is 0.07
        # Default threshold (0.15) would miss this, but 0.05 catches it
        current = _make_result({"price": 0.10}, run_id=run.id)

        events_default = run_drift_analysis(current, storage, threshold=0.15)
        assert len(events_default) == 0

        events_sensitive = run_drift_analysis(current, storage, threshold=0.05)
        assert len(events_sensitive) == 1
        assert events_sensitive[0].field_name == "price"
        assert events_sensitive[0].severity == "info"
