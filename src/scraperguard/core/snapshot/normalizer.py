"""HTML normalization engine — produces clean, deterministic structural HTML.

Takes raw, messy, real-world HTML and produces a canonical representation
suitable for comparison and fingerprinting. This is the foundation that
DOM diffing depends on — if normalization isn't deterministic, everything
downstream breaks.
"""

from __future__ import annotations

import re

import lxml.html
from lxml.html import HtmlElement, tostring


# ---------------------------------------------------------------------------
# Configurable attribute removal / retention patterns
# ---------------------------------------------------------------------------

# data- attribute suffixes that are noise (tracking, analytics, framework)
REMOVE_DATA_SUFFIXES: frozenset[str] = frozenset({
    "analytics",
    "tracking",
    "gtm",
    "reactid",
    "testid",
    "timestamp",
    "session",
    "token",
    "nonce",
    "csrf",
})

# Attribute names unconditionally removed
REMOVE_ATTRIBUTE_NAMES: frozenset[str] = frozenset({
    "style",
    "jsaction",
    "jscontroller",
    "jsmodel",
    "jsname",
})

# data- attributes explicitly kept (structural / semantic meaning)
KEEP_DATA_ATTRIBUTES: frozenset[str] = frozenset({
    "data-price",
    "data-product",
    "data-id",
    "data-sku",
    "data-category",
    "data-available",
    "data-rating",
    "data-name",
    "data-value",
    "data-type",
    "data-status",
})

# HTML void / self-closing elements that are meaningful when empty
VOID_ELEMENTS: frozenset[str] = frozenset({
    "img", "br", "hr", "input", "meta", "link",
    "area", "base", "col", "embed", "source", "track", "wbr",
})

# Elements that are semantically meaningful even when empty
KEEP_EMPTY_ELEMENTS: frozenset[str] = frozenset({
    "td", "th", "li",
})

# Tags whose entire subtree is noise
NOISE_TAGS: frozenset[str] = frozenset({
    "script", "style", "noscript",
})

_EVENT_HANDLER_RE = re.compile(r"^on[a-z]+$")
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class NormalizationError(Exception):
    """Raised when HTML cannot be parsed."""

    def __init__(self, message: str, raw_html_length: int, original_error: Exception) -> None:
        super().__init__(message)
        self.raw_html_length = raw_html_length
        self.original_error = original_error


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _should_remove_attribute(name: str) -> bool:
    """Return True if *name* should be stripped from elements."""
    # Event handlers: onclick, onload, …
    if _EVENT_HANDLER_RE.match(name):
        return True

    # Unconditionally removed names
    if name in REMOVE_ATTRIBUTE_NAMES:
        return True

    # data-* attribute logic
    if name.startswith("data-"):
        # Explicitly kept?
        if name in KEEP_DATA_ATTRIBUTES:
            return False
        # Check if the suffix after "data-" starts with a noisy prefix
        suffix = name[5:]  # strip "data-"
        for noisy in REMOVE_DATA_SUFFIXES:
            if suffix == noisy or suffix.startswith(noisy + "-") or suffix.startswith(noisy + "_"):
                return True

    return False


def _strip_noise_elements(tree: HtmlElement) -> None:
    """Remove script, style, noscript, comments, and processing instructions."""
    # Collect removals first to avoid mutating during iteration
    to_remove: list[object] = []

    for element in tree.iter():
        if isinstance(element.tag, str) and element.tag in NOISE_TAGS:
            to_remove.append(element)
        elif callable(element.tag):
            # lxml uses callable tags for Comment and ProcessingInstruction
            to_remove.append(element)

    for element in to_remove:
        parent = element.getparent()
        if parent is not None:
            # Preserve tail text (text after the removed element)
            if element.tail and element.tail.strip():
                prev = element.getprevious()
                if prev is not None:
                    prev.tail = (prev.tail or "") + element.tail
                else:
                    parent.text = (parent.text or "") + element.tail
            parent.remove(element)


def _strip_noisy_attributes(tree: HtmlElement) -> None:
    """Remove tracking / event-handler / style attributes from all elements."""
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        to_drop = [attr for attr in element.attrib if _should_remove_attribute(attr)]
        for attr in to_drop:
            del element.attrib[attr]


def _normalize_whitespace(tree: HtmlElement) -> None:
    """Collapse whitespace in text and tail nodes."""
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        if element.text:
            element.text = _WHITESPACE_RE.sub(" ", element.text).strip()
            if not element.text:
                element.text = None
        if element.tail:
            element.tail = _WHITESPACE_RE.sub(" ", element.tail).strip()
            if not element.tail:
                element.tail = None


def _remove_empty_elements(tree: HtmlElement) -> None:
    """Remove elements that are empty after cleanup (no children, no text).

    Void elements and semantically meaningful empties are preserved.
    Multiple passes handle nested empties.
    """
    changed = True
    while changed:
        changed = False
        for element in list(tree.iter()):
            if not isinstance(element.tag, str):
                continue
            tag = element.tag.lower()
            if tag in VOID_ELEMENTS or tag in KEEP_EMPTY_ELEMENTS:
                continue
            if element is tree:
                continue
            has_children = len(element) > 0
            has_text = bool(element.text and element.text.strip())
            if not has_children and not has_text:
                parent = element.getparent()
                if parent is not None:
                    if element.tail and element.tail.strip():
                        prev = element.getprevious()
                        if prev is not None:
                            prev.tail = (prev.tail or "") + " " + element.tail
                        else:
                            parent.text = (parent.text or "") + " " + element.tail
                    parent.remove(element)
                    changed = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_html(raw_html: str) -> str:
    """Parse and normalize raw HTML into a clean, deterministic string.

    Steps:
        1. Parse with lxml (fallback to document_fromstring)
        2. Remove noise elements (script, style, noscript, comments, PIs)
        3. Remove noisy attributes (tracking, event handlers, inline styles)
        4. Normalize whitespace in text nodes
        5. Remove empty structural elements
        6. Serialize to string

    Args:
        raw_html: Raw HTML string from a page response.

    Returns:
        Normalized HTML string.

    Raises:
        NormalizationError: If lxml cannot parse the HTML at all.
    """
    if not raw_html or not raw_html.strip():
        return ""

    # Parse
    tree: HtmlElement
    try:
        tree = lxml.html.fromstring(raw_html)
    except Exception as first_err:
        try:
            tree = lxml.html.document_fromstring(raw_html)
        except Exception as second_err:
            raise NormalizationError(
                f"Failed to parse HTML ({second_err})",
                raw_html_length=len(raw_html),
                original_error=second_err,
            ) from first_err

    # Ensure we work on an HtmlElement tree root
    # document_fromstring may return an <html> element directly — that's fine.

    _strip_noise_elements(tree)
    _strip_noisy_attributes(tree)
    _normalize_whitespace(tree)
    _remove_empty_elements(tree)

    result = tostring(tree, encoding="unicode", method="html")
    return result.strip()


def extract_text_content(html: str) -> str:
    """Extract all visible text from normalized HTML.

    Args:
        html: Normalized HTML string (output of :func:`normalize_html`).

    Returns:
        Concatenated visible text with single-space separation.
    """
    if not html or not html.strip():
        return ""

    tree = lxml.html.fromstring(html)
    texts: list[str] = []
    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        if element.text and element.text.strip():
            texts.append(element.text.strip())
        if element.tail and element.tail.strip():
            texts.append(element.tail.strip())
    return " ".join(texts)
