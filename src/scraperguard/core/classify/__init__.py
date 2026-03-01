"""Rule-based failure classification.

Deterministic classifier that maps observed patterns to root causes:
- SELECTOR_BREAK: selector returns 0 matches, page loads normally
- DOM_RESTRUCTURE: multiple selectors break, tree depth changes
- CAPTCHA_INJECTION: known CAPTCHA signatures in response body
- JS_CHALLENGE: empty body with script-only response
- RATE_LIMIT: HTTP 429 or known rate-limit patterns
- AB_VARIANT: partial selector match, layout fingerprint differs
- PARTIAL_EXTRACTION: some items valid, some not
- EMPTY_RESPONSE: empty or near-empty response body
"""

from scraperguard.core.classify.classifier import (
    Classification,
    ClassificationInput,
    FailureType,
    classify_and_summarize,
    classify_failure,
)

__all__ = [
    "FailureType",
    "Classification",
    "ClassificationInput",
    "classify_failure",
    "classify_and_summarize",
]
