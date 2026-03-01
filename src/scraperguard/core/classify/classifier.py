"""Failure classifier — rule-based root cause attribution.

Consumes DOM diff reports, validation results, and selector tracking outputs.
Applies deterministic rules to identify root causes and returns classifications
with confidence scores. No ML — fully debuggable and testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from scraperguard.core.dom_diff.differ import ChangeType, DOMChange
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus
from scraperguard.storage.models import ValidationResult


class FailureType(StrEnum):
    """Known failure root causes."""

    SELECTOR_BREAK = "selector_break"
    DOM_RESTRUCTURE = "dom_restructure"
    CAPTCHA_INJECTION = "captcha_injection"
    JS_CHALLENGE = "js_challenge"
    RATE_LIMIT = "rate_limit"
    AB_VARIANT = "ab_variant"
    PARTIAL_EXTRACTION = "partial_extraction"
    EMPTY_RESPONSE = "empty_response"
    UNKNOWN = "unknown"


@dataclass
class Classification:
    """Result of failure classification for a single run."""

    failure_type: FailureType
    confidence: float  # 0.0 - 1.0
    evidence: list[str]
    affected_fields: list[str]
    recommended_action: str
    severity: str  # "critical", "warning", "info"


@dataclass
class ClassificationInput:
    """Bundles all inputs the classifier needs."""

    validation_result: ValidationResult | None = None
    dom_changes: list[DOMChange] = field(default_factory=list)
    selector_statuses: list[SelectorStatus] = field(default_factory=list)
    raw_html: str | None = None
    http_status: int | None = None
    response_size_bytes: int | None = None


# ---------------------------------------------------------------------------
# Private rule functions
# ---------------------------------------------------------------------------

_CAPTCHA_SIGNATURES = [
    "g-recaptcha",
    "h-captcha",
    "captcha-container",
    "recaptcha/api.js",
    "hcaptcha.com",
    "challenge-platform",
    "cf-challenge",
]


def _check_empty_response(inp: ClassificationInput) -> Classification | None:
    if inp.raw_html is None or len(inp.raw_html.strip()) < 100:
        n = 0 if inp.raw_html is None else len(inp.raw_html.strip())
        return Classification(
            failure_type=FailureType.EMPTY_RESPONSE,
            confidence=0.95,
            evidence=[f"Response body is empty or near-empty ({n} bytes)"],
            affected_fields=[],
            recommended_action="Check if the target URL is accessible and returning content",
            severity="critical",
        )
    return None


def _check_captcha(inp: ClassificationInput) -> Classification | None:
    if not inp.raw_html:
        return None
    html_lower = inp.raw_html.lower()
    found = [sig for sig in _CAPTCHA_SIGNATURES if sig.lower() in html_lower]
    if not found:
        return None
    confidence = 0.92 if len(found) >= 2 else 0.75
    return Classification(
        failure_type=FailureType.CAPTCHA_INJECTION,
        confidence=confidence,
        evidence=[f"Found CAPTCHA signature: '{sig}'" for sig in found],
        affected_fields=[],
        recommended_action=(
            "Target site is serving a CAPTCHA."
            " Consider using a CAPTCHA-solving service or rotating IP addresses."
        ),
        severity="critical",
    )


def _extract_visible_text(html: str) -> str:
    """Extract approximate visible text from raw HTML."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove all tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _count_script_tags(html: str) -> int:
    return len(re.findall(r"<script", html, re.IGNORECASE))


def _check_js_challenge(inp: ClassificationInput) -> Classification | None:
    if not inp.raw_html:
        return None
    visible_text = _extract_visible_text(inp.raw_html)
    script_count = _count_script_tags(inp.raw_html)
    if len(visible_text) < 50 and script_count > 0:
        return Classification(
            failure_type=FailureType.JS_CHALLENGE,
            confidence=0.80,
            evidence=[
                f"Page has minimal text content ({len(visible_text)} chars)"
                f" but contains {script_count} script tags",
            ],
            affected_fields=[],
            recommended_action=(
                "Page requires JavaScript rendering."
                " Use a browser-based scraper (Playwright, Selenium)."
            ),
            severity="critical",
        )
    return None


def _check_rate_limit(inp: ClassificationInput) -> Classification | None:
    if inp.http_status == 429:
        return Classification(
            failure_type=FailureType.RATE_LIMIT,
            confidence=0.95,
            evidence=[f"HTTP status {inp.http_status}"],
            affected_fields=[],
            recommended_action="Reduce request frequency or implement request throttling.",
            severity="critical",
        )
    if inp.http_status == 403:
        return Classification(
            failure_type=FailureType.RATE_LIMIT,
            confidence=0.70,
            evidence=[f"HTTP status {inp.http_status}"],
            affected_fields=[],
            recommended_action="Reduce request frequency or implement request throttling.",
            severity="warning",
        )
    if inp.raw_html:
        html_lower = inp.raw_html.lower()
        if "rate limit" in html_lower or "too many requests" in html_lower:
            return Classification(
                failure_type=FailureType.RATE_LIMIT,
                confidence=0.60,
                evidence=["Response contains rate limit message"],
                affected_fields=[],
                recommended_action="Reduce request frequency or implement request throttling.",
                severity="warning",
            )
    return None


def _infer_affected_fields(selector: str) -> list[str]:
    """Infer field names from a selector using simple substring matching."""
    fields: list[str] = []
    # Extract class names and id fragments from the selector
    parts = re.findall(r"[\w-]+", selector)
    # Common field name patterns
    common_fields = [
        "price",
        "title",
        "name",
        "description",
        "image",
        "url",
        "rating",
        "review",
        "stock",
        "availability",
        "category",
        "brand",
        "sku",
    ]
    for part in parts:
        part_lower = part.lower()
        for field_name in common_fields:
            if field_name in part_lower and field_name not in fields:
                fields.append(field_name)
    return fields


def _check_selector_break(inp: ClassificationInput) -> Classification | None:
    broken = [s for s in inp.selector_statuses if s.status == "broken"]
    if not broken:
        return None

    evidence = [
        f"Selector '{s.selector}' returned 0 matches (was {s.previous_matches})" for s in broken
    ]

    affected_fields: list[str] = []
    for s in broken:
        for f in _infer_affected_fields(s.selector):
            if f not in affected_fields:
                affected_fields.append(f)

    # Higher confidence if broken selectors correlate with high null ratios
    has_validation_correlation = False
    if inp.validation_result and inp.validation_result.null_ratios:
        for f in affected_fields:
            if inp.validation_result.null_ratios.get(f, 0.0) > 0.5:
                has_validation_correlation = True
                break

    confidence = 0.90 if has_validation_correlation else 0.70

    broken_selectors = [s.selector for s in broken]

    # Determine severity based on required fields
    severity = "warning"
    if inp.validation_result:
        # If any affected field has failures, treat as critical
        failed_field_names = {ff.field_name for ff in inp.validation_result.field_failures}
        if affected_fields and any(f in failed_field_names for f in affected_fields):
            severity = "critical"
        elif inp.validation_result.failed_count > 0:
            severity = "critical"

    return Classification(
        failure_type=FailureType.SELECTOR_BREAK,
        confidence=confidence,
        evidence=evidence,
        affected_fields=affected_fields,
        recommended_action=f"Update broken selectors: {broken_selectors}",
        severity=severity,
    )


def _check_dom_restructure(inp: ClassificationInput) -> Classification | None:
    if not inp.dom_changes:
        return None

    high_severity = [c for c in inp.dom_changes if c.severity == "high"]
    node_removed = [c for c in inp.dom_changes if c.change_type == ChangeType.NODE_REMOVED]
    tag_changed = [c for c in inp.dom_changes if c.change_type == ChangeType.TAG_CHANGED]

    high_count = len(high_severity)
    total = len(inp.dom_changes)

    if high_count >= 5 or len(node_removed) >= 3 or len(tag_changed) >= 2:
        if total >= 10:
            confidence = 0.85
            severity = "critical"
        elif high_count >= 5:
            confidence = 0.70
            severity = "warning"
        else:
            confidence = 0.60
            severity = "warning"

        return Classification(
            failure_type=FailureType.DOM_RESTRUCTURE,
            confidence=confidence,
            evidence=[
                f"Detected {total} structural DOM changes ({high_count} high severity)",
            ],
            affected_fields=[],
            recommended_action=(
                "Major structural change detected. Review page layout and update scraper selectors."
            ),
            severity=severity,
        )
    return None


def _check_ab_variant(inp: ClassificationInput) -> Classification | None:
    if not inp.selector_statuses:
        return None

    total_count = len(inp.selector_statuses)
    broken_count = len([s for s in inp.selector_statuses if s.status == "broken"])

    if broken_count == 0 or total_count == 0:
        return None

    if broken_count >= total_count * 0.3:
        return None

    high_severity = [c for c in inp.dom_changes if c.severity == "high"]
    high_count = len(high_severity)

    if 2 <= high_count <= 8:
        return Classification(
            failure_type=FailureType.AB_VARIANT,
            confidence=0.55,
            evidence=[
                f"Partial selector failure ({broken_count}/{total_count})"
                " with moderate structural changes suggests A/B variant",
            ],
            affected_fields=[],
            recommended_action="Possible A/B test variant. Monitor over multiple runs to confirm.",
            severity="info",
        )
    return None


def _check_partial_extraction(inp: ClassificationInput) -> Classification | None:
    if not inp.validation_result:
        return None

    vr = inp.validation_result
    if vr.failed_count > 0 and vr.total_items > 0 and vr.failed_count < vr.total_items * 0.5:
        return Classification(
            failure_type=FailureType.PARTIAL_EXTRACTION,
            confidence=0.65,
            evidence=[f"{vr.failed_count}/{vr.total_items} items failed validation"],
            affected_fields=[],
            recommended_action=(
                "Partial extraction failure."
                " Some items are extracting correctly. Check specific failure patterns."
            ),
            severity="warning",
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_failure(inp: ClassificationInput) -> list[Classification]:
    """Run all classification rules and return matching classifications.

    Returns every matching classification, sorted by confidence descending.
    Multiple classifications can apply simultaneously.
    """
    checks = [
        _check_empty_response,
        _check_captcha,
        _check_js_challenge,
        _check_rate_limit,
        _check_selector_break,
        _check_dom_restructure,
        _check_ab_variant,
        _check_partial_extraction,
    ]

    results: list[Classification] = []
    for check in checks:
        result = check(inp)
        if result is not None:
            results.append(result)

    # Fallback to UNKNOWN if no rules matched but failures exist
    if not results:
        has_failures = False
        if inp.validation_result and inp.validation_result.failed_count > 0:
            has_failures = True
        if any(s.status == "broken" for s in inp.selector_statuses):
            has_failures = True

        if has_failures:
            results.append(
                Classification(
                    failure_type=FailureType.UNKNOWN,
                    confidence=0.3,
                    evidence=["No specific failure pattern matched"],
                    affected_fields=[],
                    recommended_action="Manual investigation recommended.",
                    severity="warning",
                )
            )

    results.sort(key=lambda c: c.confidence, reverse=True)
    return results


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def classify_and_summarize(inp: ClassificationInput) -> dict[str, Any]:
    """Run classify_failure and return a summary dict."""
    classifications = classify_failure(inp)

    if not classifications:
        return {
            "primary_failure": None,
            "all_classifications": [],
            "total_classifications": 0,
            "highest_severity": None,
            "recommended_actions": [],
        }

    def _to_dict(c: Classification) -> dict[str, Any]:
        return {
            "failure_type": c.failure_type.value,
            "confidence": c.confidence,
            "evidence": c.evidence,
            "affected_fields": c.affected_fields,
            "recommended_action": c.recommended_action,
            "severity": c.severity,
        }

    all_dicts = [_to_dict(c) for c in classifications]

    # Determine highest severity
    highest_severity = min(
        (c.severity for c in classifications),
        key=lambda s: _SEVERITY_ORDER.get(s, 99),
    )

    # Deduplicated recommended actions
    seen: set[str] = set()
    actions: list[str] = []
    for c in classifications:
        if c.recommended_action not in seen:
            seen.add(c.recommended_action)
            actions.append(c.recommended_action)

    return {
        "primary_failure": all_dicts[0],
        "all_classifications": all_dicts,
        "total_classifications": len(classifications),
        "highest_severity": highest_severity,
        "recommended_actions": actions,
    }
