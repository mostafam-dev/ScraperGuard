"""DOM capture, normalization, and fingerprinting.

This subpackage is responsible for:
- Capturing raw HTML and converting it to a canonical DOM tree via lxml
- Stripping non-structural noise (whitespace, comments, inline scripts)
- Computing structural fingerprints for snapshot identity
- Storing snapshots with associated metadata (URL, timestamp, headers)
"""

from scraperguard.core.snapshot.capture import capture_snapshot, should_diff
from scraperguard.core.snapshot.fingerprint import fingerprint_html, fingerprint_structure
from scraperguard.core.snapshot.normalizer import (
    NormalizationError,
    extract_text_content,
    normalize_html,
)

__all__ = [
    "NormalizationError",
    "capture_snapshot",
    "extract_text_content",
    "fingerprint_html",
    "fingerprint_structure",
    "normalize_html",
    "should_diff",
]
