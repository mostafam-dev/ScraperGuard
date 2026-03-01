"""Tests for the rule-based failure classifier."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraperguard.core.classify.classifier import (
    Classification,
    ClassificationInput,
    FailureType,
    classify_and_summarize,
    classify_failure,
)
from scraperguard.core.dom_diff.differ import ChangeType, DOMChange
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus
from scraperguard.storage.models import FieldFailure, ValidationResult

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"

# HTML that is long enough (>100 chars stripped) to avoid triggering EMPTY_RESPONSE
_NORMAL_HTML = (
    "<html><body><p>"
    + "Normal page content. " * 10
    + "</p></body></html>"
)


def _make_validation_result(
    total_items: int = 10,
    passed_count: int = 10,
    failed_count: int = 0,
    field_failures: list[FieldFailure] | None = None,
    null_ratios: dict[str, float] | None = None,
) -> ValidationResult:
    return ValidationResult(
        run_id="test-run",
        url="https://example.com",
        schema_name="TestSchema",
        total_items=total_items,
        passed_count=passed_count,
        failed_count=failed_count,
        field_failures=field_failures or [],
        null_ratios=null_ratios or {},
    )


def _make_dom_change(
    change_type: ChangeType = ChangeType.NODE_REMOVED,
    severity: str = "high",
) -> DOMChange:
    return DOMChange(
        change_type=change_type,
        path="html > body > div",
        severity=severity,
        message="test change",
    )


def _make_selector_status(
    selector: str = ".product-title",
    current_matches: int = 0,
    previous_matches: int = 10,
    status: str = "broken",
) -> SelectorStatus:
    return SelectorStatus(
        selector=selector,
        current_matches=current_matches,
        previous_matches=previous_matches,
        status=status,
        message=f"Selector '{selector}' matches {current_matches} nodes (was {previous_matches})",
    )


class TestEmptyResponse:
    def test_classify_empty_response(self):
        inp = ClassificationInput(raw_html="")
        results = classify_failure(inp)
        assert len(results) >= 1
        empty = [r for r in results if r.failure_type == FailureType.EMPTY_RESPONSE]
        assert len(empty) == 1
        assert empty[0].confidence == pytest.approx(0.95)
        assert empty[0].severity == "critical"

    def test_classify_empty_response_none(self):
        inp = ClassificationInput(raw_html=None)
        results = classify_failure(inp)
        empty = [r for r in results if r.failure_type == FailureType.EMPTY_RESPONSE]
        assert len(empty) == 1
        assert empty[0].confidence == pytest.approx(0.95)


class TestCaptcha:
    def test_classify_captcha_recaptcha(self):
        html = """
        <html><body>
        <div class="g-recaptcha" data-sitekey="abc"></div>
        <script src="https://www.google.com/recaptcha/api.js"></script>
        <p>Please verify you are human</p>
        </body></html>
        """
        inp = ClassificationInput(raw_html=html)
        results = classify_failure(inp)
        captcha = [r for r in results if r.failure_type == FailureType.CAPTCHA_INJECTION]
        assert len(captcha) == 1
        assert captcha[0].confidence == pytest.approx(0.92)
        assert captcha[0].severity == "critical"
        # Should have found both g-recaptcha and recaptcha/api.js
        assert len(captcha[0].evidence) >= 2

    def test_classify_captcha_single_signal(self):
        html = """
        <html><body>
        <div class="h-captcha"></div>
        <p>Some other content here that is long enough to not be empty</p>
        </body></html>
        """
        inp = ClassificationInput(raw_html=html)
        results = classify_failure(inp)
        captcha = [r for r in results if r.failure_type == FailureType.CAPTCHA_INJECTION]
        assert len(captcha) == 1
        assert captcha[0].confidence == pytest.approx(0.75)
        assert captcha[0].confidence < 0.92  # Less than multi-signal


class TestJsChallenge:
    def test_classify_js_challenge(self):
        html = """
        <html><head>
        <script src="challenge.js"></script>
        <script>var x = 1;</script>
        </head><body></body></html>
        """
        inp = ClassificationInput(raw_html=html)
        results = classify_failure(inp)
        js = [r for r in results if r.failure_type == FailureType.JS_CHALLENGE]
        assert len(js) == 1
        assert js[0].confidence == pytest.approx(0.80)
        assert js[0].severity == "critical"
        assert "script tags" in js[0].evidence[0]


class TestRateLimit:
    def test_classify_rate_limit_429(self):
        inp = ClassificationInput(
            raw_html="<html><body>Too many requests</body></html>",
            http_status=429,
        )
        results = classify_failure(inp)
        rl = [r for r in results if r.failure_type == FailureType.RATE_LIMIT]
        assert len(rl) == 1
        assert rl[0].confidence == pytest.approx(0.95)
        assert rl[0].severity == "critical"

    def test_classify_rate_limit_403(self):
        inp = ClassificationInput(
            raw_html="<html><body>Forbidden access to this resource</body></html>",
            http_status=403,
        )
        results = classify_failure(inp)
        rl = [r for r in results if r.failure_type == FailureType.RATE_LIMIT]
        assert len(rl) == 1
        assert rl[0].confidence == pytest.approx(0.70)
        assert rl[0].severity == "warning"


class TestSelectorBreak:
    def test_classify_selector_break(self):
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            selector_statuses=[
                _make_selector_status(".product-title", 0, 10, "broken"),
                _make_selector_status(".product-image", 5, 5, "stable"),
            ],
        )
        results = classify_failure(inp)
        sb = [r for r in results if r.failure_type == FailureType.SELECTOR_BREAK]
        assert len(sb) == 1
        assert sb[0].confidence == pytest.approx(0.70)  # No validation correlation
        assert "product-title" in sb[0].evidence[0]

    def test_classify_selector_break_with_validation(self):
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            selector_statuses=[
                _make_selector_status(".price-tag", 0, 10, "broken"),
            ],
            validation_result=_make_validation_result(
                total_items=10,
                passed_count=5,
                failed_count=5,
                field_failures=[FieldFailure(field_name="price", failure_type="null", count=5)],
                null_ratios={"price": 0.8, "title": 0.0},
            ),
        )
        results = classify_failure(inp)
        sb = [r for r in results if r.failure_type == FailureType.SELECTOR_BREAK]
        assert len(sb) == 1
        assert sb[0].confidence == pytest.approx(0.90)  # With validation correlation
        assert "price" in sb[0].affected_fields


class TestDomRestructure:
    def test_classify_dom_restructure(self):
        # 10+ high severity changes → confidence 0.85, critical
        changes = [_make_dom_change(ChangeType.NODE_REMOVED, "high") for _ in range(12)]
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            dom_changes=changes,
        )
        results = classify_failure(inp)
        dr = [r for r in results if r.failure_type == FailureType.DOM_RESTRUCTURE]
        assert len(dr) == 1
        assert dr[0].confidence == pytest.approx(0.85)
        assert dr[0].severity == "critical"


class TestAbVariant:
    def test_classify_ab_variant(self):
        # Few broken selectors + moderate high-severity changes
        selectors = [
            _make_selector_status(".title", 0, 10, "broken"),
            _make_selector_status(".price", 5, 5, "stable"),
            _make_selector_status(".image", 5, 5, "stable"),
            _make_selector_status(".desc", 5, 5, "stable"),
            _make_selector_status(".rating", 5, 5, "stable"),
        ]
        changes = [_make_dom_change(ChangeType.NODE_REMOVED, "high") for _ in range(3)]
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            selector_statuses=selectors,
            dom_changes=changes,
        )
        results = classify_failure(inp)
        ab = [r for r in results if r.failure_type == FailureType.AB_VARIANT]
        assert len(ab) == 1
        assert ab[0].confidence == pytest.approx(0.55)
        assert ab[0].severity == "info"


class TestPartialExtraction:
    def test_classify_partial_extraction(self):
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            validation_result=_make_validation_result(
                total_items=20,
                passed_count=15,
                failed_count=5,
                field_failures=[FieldFailure(field_name="price", failure_type="null", count=5)],
            ),
        )
        results = classify_failure(inp)
        pe = [r for r in results if r.failure_type == FailureType.PARTIAL_EXTRACTION]
        assert len(pe) == 1
        assert pe[0].confidence == pytest.approx(0.65)
        assert pe[0].severity == "warning"
        assert "5/20" in pe[0].evidence[0]


class TestMultipleClassifications:
    def test_classify_multiple_simultaneous(self):
        """Input triggers both SELECTOR_BREAK and PARTIAL_EXTRACTION."""
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            selector_statuses=[
                _make_selector_status(".product-title", 0, 10, "broken"),
            ],
            validation_result=_make_validation_result(
                total_items=20,
                passed_count=15,
                failed_count=5,
            ),
        )
        results = classify_failure(inp)
        types = {r.failure_type for r in results}
        assert FailureType.SELECTOR_BREAK in types
        assert FailureType.PARTIAL_EXTRACTION in types

    def test_classify_sorted_by_confidence(self):
        """Multiple classifications returned in confidence descending order."""
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            selector_statuses=[
                _make_selector_status(".product-title", 0, 10, "broken"),
            ],
            validation_result=_make_validation_result(
                total_items=20,
                passed_count=15,
                failed_count=5,
            ),
        )
        results = classify_failure(inp)
        assert len(results) >= 2
        for i in range(len(results) - 1):
            assert results[i].confidence >= results[i + 1].confidence


class TestUnknownFallback:
    def test_classify_unknown_fallback(self):
        """Failures exist but no rules match → UNKNOWN classification."""
        # Validation failures but with raw_html long enough, no captcha/JS/rate-limit signals,
        # no broken selectors, no DOM changes, and failed_count >= 50% so partial_extraction won't trigger
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            validation_result=_make_validation_result(
                total_items=10,
                passed_count=2,
                failed_count=8,  # >= 50%, so partial_extraction won't fire
            ),
        )
        results = classify_failure(inp)
        assert len(results) == 1
        assert results[0].failure_type == FailureType.UNKNOWN
        assert results[0].confidence == pytest.approx(0.3)


class TestCleanRun:
    def test_classify_clean_run(self):
        """No failures, no changes, no broken selectors → empty list."""
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            validation_result=_make_validation_result(
                total_items=10,
                passed_count=10,
                failed_count=0,
            ),
            selector_statuses=[
                _make_selector_status(".title", 10, 10, "stable"),
            ],
            dom_changes=[],
        )
        results = classify_failure(inp)
        assert results == []


class TestClassifyAndSummarize:
    def test_classify_and_summarize(self):
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            http_status=429,
            selector_statuses=[
                _make_selector_status(".product-title", 0, 10, "broken"),
            ],
        )
        summary = classify_and_summarize(inp)
        assert summary["primary_failure"] is not None
        assert summary["total_classifications"] >= 2
        assert summary["highest_severity"] == "critical"
        assert isinstance(summary["all_classifications"], list)
        assert isinstance(summary["recommended_actions"], list)
        assert len(summary["recommended_actions"]) >= 1
        # Verify dict structure
        primary = summary["primary_failure"]
        assert "failure_type" in primary
        assert "confidence" in primary
        assert "evidence" in primary
        assert "severity" in primary

    def test_classify_and_summarize_empty(self):
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
        )
        summary = classify_and_summarize(inp)
        assert summary["primary_failure"] is None
        assert summary["total_classifications"] == 0
        assert summary["highest_severity"] is None


class TestCaptchaFixture:
    def test_with_captcha_fixture(self):
        fixture_path = FIXTURES_DIR / "product_page_captcha.html"
        html = fixture_path.read_text()
        inp = ClassificationInput(raw_html=html)
        results = classify_failure(inp)
        captcha = [r for r in results if r.failure_type == FailureType.CAPTCHA_INJECTION]
        assert len(captcha) == 1
        assert captcha[0].confidence >= 0.75


class TestAffectedFieldsInferred:
    def test_affected_fields_inferred(self):
        """Broken selector '.price-tag' → affected_fields includes 'price'."""
        inp = ClassificationInput(
            raw_html=_NORMAL_HTML,
            selector_statuses=[
                _make_selector_status(".price-tag", 0, 10, "broken"),
            ],
        )
        results = classify_failure(inp)
        sb = [r for r in results if r.failure_type == FailureType.SELECTOR_BREAK]
        assert len(sb) == 1
        assert "price" in sb[0].affected_fields
