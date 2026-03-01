"""Health score computation.

Computes a composite 0-100 health score for each scraper run by combining:
- Schema compliance (% of items passing validation)
- Extraction completeness (% of expected fields extracted)
- Selector stability (match rate vs historical baseline)
- Structural stability (impact of DOM changes)

The score is the primary top-level signal surfaced in the CLI, API, and alerts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from scraperguard.core.classify.classifier import Classification
from scraperguard.core.dom_diff.differ import DOMChange
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus
from scraperguard.core.schema.drift import DriftEvent
from scraperguard.storage.models import ValidationResult


@dataclass
class HealthComponent:
    """A single scored component of the health report."""

    name: str
    score: float  # 0.0 to 1.0
    weight: float  # 0.0 to 1.0
    details: str

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class HealthScoreWeights:
    """Configurable weights for health score components. Must sum to 1.0."""

    schema_compliance: float = 0.30
    extraction_completeness: float = 0.30
    selector_stability: float = 0.25
    structural_stability: float = 0.15


@dataclass
class HealthReport:
    """Result of a health score computation for a single scraper run."""

    overall_score: int  # 0 to 100
    status: str  # "healthy", "degraded", "critical", "unknown"
    components: list[HealthComponent]
    classifications: list[Classification]
    drift_events: list[DriftEvent]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    run_id: str = ""
    url: str = ""


def compute_schema_compliance(
    validation_result: ValidationResult | None,
    weight: float = 0.35,
) -> HealthComponent:
    """Score based on ratio of items passing schema validation."""
    if validation_result is None:
        return HealthComponent(
            name="Schema Compliance",
            score=1.0,
            weight=weight,
            details="No schema validation configured",
        )

    total = validation_result.total_items
    if total == 0:
        score = 1.0
    else:
        score = validation_result.passed_count / total

    pct = round(score * 100, 1)
    return HealthComponent(
        name="Schema Compliance",
        score=score,
        weight=weight,
        details=f"{validation_result.passed_count}/{total} items passed schema validation ({pct}%)",
    )


def compute_extraction_completeness(
    validation_result: ValidationResult | None,
    weight: float = 0.30,
) -> HealthComponent:
    """Score based on average field completeness (1 - null_ratio per field)."""
    if validation_result is None:
        return HealthComponent(
            name="Extraction Completeness",
            score=1.0,
            weight=weight,
            details="No schema validation configured",
        )

    null_ratios = validation_result.null_ratios
    if not null_ratios:
        return HealthComponent(
            name="Extraction Completeness",
            score=1.0,
            weight=weight,
            details="No fields tracked",
        )

    completeness = {f: 1.0 - r for f, r in null_ratios.items()}
    avg = sum(completeness.values()) / len(completeness)
    weakest_field = min(completeness, key=completeness.get)  # type: ignore[arg-type]
    weakest_val = completeness[weakest_field]
    weakest_pct = round(weakest_val * 100, 1)

    # Blend average (60%) with worst-field (40%) so a single severely broken
    # field isn't hidden by healthy siblings.
    score = 0.6 * avg + 0.4 * weakest_val
    score_pct = round(score * 100, 1)

    return HealthComponent(
        name="Extraction Completeness",
        score=score,
        weight=weight,
        details=f"Field completeness: {score_pct}%. Weakest: {weakest_field} at {weakest_pct}%",
    )


def compute_selector_stability(
    selector_statuses: list[SelectorStatus],
    weight: float = 0.20,
) -> HealthComponent:
    """Score based on ratio of stable/improved selectors."""
    if not selector_statuses:
        return HealthComponent(
            name="Selector Stability",
            score=1.0,
            weight=weight,
            details="No selectors tracked",
        )

    total = len(selector_statuses)
    good = sum(1 for s in selector_statuses if s.status in ("stable", "improved"))
    broken = [s.selector for s in selector_statuses if s.status == "broken"]
    score = good / total

    broken_str = ", ".join(broken) if broken else "none"
    return HealthComponent(
        name="Selector Stability",
        score=score,
        weight=weight,
        details=f"{good}/{total} selectors stable. Broken: {broken_str}",
    )


def compute_structural_stability(
    dom_changes: list[DOMChange],
    weight: float = 0.15,
) -> HealthComponent:
    """Score based on severity of DOM structural changes."""
    if not dom_changes:
        return HealthComponent(
            name="Structural Stability",
            score=1.0,
            weight=weight,
            details="No structural changes detected",
        )

    deductions = {"high": 0.25, "medium": 0.10, "low": 0.03}
    score = 1.0
    high = medium = low = 0
    for change in dom_changes:
        sev = change.severity
        if sev == "high":
            high += 1
        elif sev == "medium":
            medium += 1
        else:
            low += 1
        score -= deductions.get(sev, 0.0)

    score = max(score, 0.0)
    return HealthComponent(
        name="Structural Stability",
        score=score,
        weight=weight,
        details=(
            f"{len(dom_changes)} structural changes detected"
            f" ({high} high, {medium} medium, {low} low severity)"
        ),
    )


def compute_health_score(
    validation_result: ValidationResult | None,
    selector_statuses: list[SelectorStatus],
    dom_changes: list[DOMChange],
    classifications: list[Classification],
    drift_events: list[DriftEvent],
    run_id: str = "",
    url: str = "",
    weights: HealthScoreWeights | None = None,
) -> HealthReport:
    """Compute a composite health score from all signals."""
    if weights is None:
        weights = HealthScoreWeights()

    components = [
        compute_schema_compliance(validation_result, weights.schema_compliance),
        compute_extraction_completeness(validation_result, weights.extraction_completeness),
        compute_selector_stability(selector_statuses, weights.selector_stability),
        compute_structural_stability(dom_changes, weights.structural_stability),
    ]

    raw = sum(c.weighted_score for c in components) * 100
    overall_score = max(0, min(100, round(raw)))

    # Determine status
    no_data = validation_result is None and not selector_statuses and not dom_changes
    if no_data:
        status = "unknown"
    elif overall_score >= 80:
        status = "healthy"
    elif overall_score >= 50:
        status = "degraded"
    else:
        status = "critical"

    return HealthReport(
        overall_score=overall_score,
        status=status,
        components=components,
        classifications=classifications,
        drift_events=drift_events,
        run_id=run_id,
        url=url,
    )


def format_health_report(report: HealthReport) -> str:
    """Format a HealthReport as a human-readable boxed text report."""
    lines: list[str] = []
    lines.append(f"Health Score: {report.overall_score}/100 ({report.status})")
    lines.append("")

    for comp in report.components:
        pct = round(comp.score * 100, 1)
        lines.append(f"{comp.name}: {pct}%")
        lines.append(f"  {comp.details}")
        lines.append("")

    if report.classifications:
        lines.append("Failures:")
        for c in report.classifications:
            lines.append(f"  [{c.severity}] {c.failure_type.value}: {c.recommended_action}")
        lines.append("")

    if report.drift_events:
        lines.append("Drift Alerts:")
        for d in report.drift_events:
            lines.append(f"  [{d.severity}] {d.field_name}: {d.message}")
        lines.append("")

    # Remove trailing blank line
    while lines and lines[-1] == "":
        lines.pop()

    # Compute box width
    max_len = max(len(line) for line in lines)
    width = max_len + 4  # 2 chars padding each side

    top = "\u2554" + "\u2550" * width + "\u2557"
    sep = "\u2560" + "\u2550" * width + "\u2563"
    bot = "\u255a" + "\u2550" * width + "\u255d"

    result = [top]
    for i, line in enumerate(lines):
        padded = f"\u2551  {line}{' ' * (width - len(line) - 2)}\u2551"
        result.append(padded)
        if i == 0:
            result.append(sep)

    result.append(bot)
    return "\n".join(result)
