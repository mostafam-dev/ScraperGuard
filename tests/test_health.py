"""Tests for the health score computation module."""

from __future__ import annotations

from scraperguard.core.classify.classifier import Classification, FailureType
from scraperguard.core.dom_diff.differ import ChangeType, DOMChange
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus
from scraperguard.core.schema.drift import DriftEvent
from scraperguard.health import (
    HealthScoreWeights,
    compute_extraction_completeness,
    compute_health_score,
    compute_schema_compliance,
    compute_selector_stability,
    compute_structural_stability,
    format_health_report,
)
from scraperguard.storage.models import ValidationResult


def _make_validation(
    total: int = 100,
    passed: int = 100,
    null_ratios: dict[str, float] | None = None,
) -> ValidationResult:
    return ValidationResult(
        run_id="run-1",
        url="https://example.com",
        schema_name="test",
        total_items=total,
        passed_count=passed,
        failed_count=total - passed,
        field_failures=[],
        null_ratios=null_ratios or {},
    )


def _make_selector(selector: str, status: str) -> SelectorStatus:
    return SelectorStatus(
        selector=selector,
        current_matches=5 if status != "broken" else 0,
        previous_matches=5,
        status=status,
        message=f"Selector {selector} is {status}",
    )


def _make_dom_change(severity: str) -> DOMChange:
    return DOMChange(
        change_type=ChangeType.NODE_REMOVED,
        path="/html/body/div",
        severity=severity,
    )


def _make_classification(
    failure_type: FailureType = FailureType.SELECTOR_BREAK,
    severity: str = "critical",
) -> Classification:
    return Classification(
        failure_type=failure_type,
        confidence=0.9,
        evidence=["selector .price not found"],
        affected_fields=["price"],
        recommended_action="Update selector for .price",
        severity=severity,
    )


def _make_drift_event(
    field_name: str = "price",
    severity: str = "warning",
) -> DriftEvent:
    return DriftEvent(
        field_name=field_name,
        current_ratio=0.4,
        baseline_ratio=0.1,
        delta=0.3,
        severity=severity,
        message=f"Null ratio for {field_name} increased from 10% to 40%",
    )


class TestPerfectHealthScore:
    def test_perfect_health_score(self):
        vr = _make_validation(total=100, passed=100, null_ratios={"price": 0.0, "title": 0.0})
        selectors = [_make_selector(f"sel{i}", "stable") for i in range(4)]
        report = compute_health_score(
            validation_result=vr,
            selector_statuses=selectors,
            dom_changes=[],
            classifications=[],
            drift_events=[],
        )
        assert report.overall_score >= 95
        assert report.status == "healthy"


class TestCriticalHealthScore:
    def test_critical_health_score(self):
        vr = _make_validation(total=100, passed=10, null_ratios={"price": 0.9, "title": 0.8})
        selectors = [
            _make_selector("sel0", "broken"),
            _make_selector("sel1", "broken"),
            _make_selector("sel2", "broken"),
            _make_selector("sel3", "stable"),
        ]
        dom_changes = [_make_dom_change("high") for _ in range(5)]
        report = compute_health_score(
            validation_result=vr,
            selector_statuses=selectors,
            dom_changes=dom_changes,
            classifications=[],
            drift_events=[],
        )
        assert report.overall_score < 50
        assert report.status == "critical"


class TestDegradedHealthScore:
    def test_degraded_health_score(self):
        vr = _make_validation(total=100, passed=70, null_ratios={"price": 0.3, "title": 0.1})
        selectors = [
            _make_selector("sel0", "stable"),
            _make_selector("sel1", "stable"),
            _make_selector("sel2", "broken"),
        ]
        dom_changes = [_make_dom_change("medium"), _make_dom_change("low")]
        report = compute_health_score(
            validation_result=vr,
            selector_statuses=selectors,
            dom_changes=dom_changes,
            classifications=[],
            drift_events=[],
        )
        assert 50 <= report.overall_score < 80
        assert report.status == "degraded"


class TestSchemaComplianceComponent:
    def test_schema_compliance_component(self):
        vr = _make_validation(total=100, passed=80)
        comp = compute_schema_compliance(vr)
        assert comp.score == 0.8
        assert "80/100" in comp.details


class TestExtractionCompletenessComponent:
    def test_extraction_completeness_component(self):
        vr = _make_validation(null_ratios={"price": 0.5, "title": 0.0})
        comp = compute_extraction_completeness(vr)
        # avg=0.75, weakest=0.5, score = 0.6*0.75 + 0.4*0.5 = 0.65
        assert abs(comp.score - 0.65) < 0.001
        assert "price" in comp.details


class TestSelectorStabilityComponent:
    def test_selector_stability_component(self):
        selectors = [
            _make_selector("a", "stable"),
            _make_selector("b", "stable"),
            _make_selector("c", "stable"),
            _make_selector("d", "broken"),
        ]
        comp = compute_selector_stability(selectors)
        assert comp.score == 0.75
        assert "3/4" in comp.details
        assert "d" in comp.details


class TestStructuralStabilityDeductions:
    def test_structural_stability_deductions(self):
        changes = (
            [_make_dom_change("high") for _ in range(2)]
            + [_make_dom_change("medium") for _ in range(3)]
        )
        comp = compute_structural_stability(changes)
        # 1.0 - 2*0.25 - 3*0.10 = 1.0 - 0.50 - 0.30 = 0.20
        assert abs(comp.score - 0.20) < 0.001


class TestStructuralStabilityFloor:
    def test_structural_stability_floor(self):
        changes = [_make_dom_change("high") for _ in range(20)]
        comp = compute_structural_stability(changes)
        assert comp.score == 0.0


class TestCustomWeights:
    def test_custom_weights(self):
        vr = _make_validation(total=100, passed=100, null_ratios={"price": 0.0})
        selectors = [_make_selector("a", "broken")]
        # With default weights selector_stability=0.20, score would include 0 * 0.20
        # With custom weights where selector has higher weight, score changes
        default_report = compute_health_score(
            validation_result=vr,
            selector_statuses=selectors,
            dom_changes=[],
            classifications=[],
            drift_events=[],
        )
        custom_weights = HealthScoreWeights(
            schema_compliance=0.10,
            extraction_completeness=0.10,
            selector_stability=0.70,
            structural_stability=0.10,
        )
        custom_report = compute_health_score(
            validation_result=vr,
            selector_statuses=selectors,
            dom_changes=[],
            classifications=[],
            drift_events=[],
            weights=custom_weights,
        )
        # Broken selector penalized much more with higher weight
        assert custom_report.overall_score < default_report.overall_score


class TestNoDataUnknown:
    def test_no_data_unknown(self):
        report = compute_health_score(
            validation_result=None,
            selector_statuses=[],
            dom_changes=[],
            classifications=[],
            drift_events=[],
        )
        assert report.status == "unknown"


class TestFormatHealthReport:
    def test_format_health_report(self):
        vr = _make_validation(total=100, passed=90, null_ratios={"price": 0.1})
        report = compute_health_score(
            validation_result=vr,
            selector_statuses=[_make_selector("a", "stable")],
            dom_changes=[],
            classifications=[],
            drift_events=[],
        )
        output = format_health_report(report)
        assert f"{report.overall_score}/100" in output
        assert report.status in output
        assert "Schema Compliance" in output
        assert "Extraction Completeness" in output
        assert "Selector Stability" in output
        assert "Structural Stability" in output
        # Box drawing chars
        assert "\u2554" in output
        assert "\u255a" in output


class TestHealthReportIncludesClassifications:
    def test_health_report_includes_classifications(self):
        classifications = [_make_classification()]
        report = compute_health_score(
            validation_result=_make_validation(),
            selector_statuses=[],
            dom_changes=[],
            classifications=classifications,
            drift_events=[],
        )
        assert report.classifications == classifications
        output = format_health_report(report)
        assert "Failures:" in output
        assert "selector_break" in output
        assert "Update selector for .price" in output


class TestHealthReportIncludesDriftEvents:
    def test_health_report_includes_drift_events(self):
        drift_events = [_make_drift_event()]
        report = compute_health_score(
            validation_result=_make_validation(),
            selector_statuses=[],
            dom_changes=[],
            classifications=[],
            drift_events=drift_events,
        )
        assert report.drift_events == drift_events
        output = format_health_report(report)
        assert "Drift Alerts:" in output
        assert "price" in output
