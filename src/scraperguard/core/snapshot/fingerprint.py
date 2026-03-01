"""HTML and structural fingerprinting for change detection.

Provides two levels of fingerprinting:
- **HTML fingerprint**: SHA-256 of the full normalized HTML. Changes when
  ANY content changes (text, attributes, structure).
- **Structure fingerprint**: SHA-256 of the tag-nesting skeleton only.
  Changes only when DOM elements are added, removed, or moved — NOT when
  text content or attribute values change.

The structure fingerprint is what triggers DOM diffing. You don't want to
run an expensive tree diff just because a price went from $79 to $80.
"""

from __future__ import annotations

import hashlib

import lxml.html
from lxml.html import HtmlElement


def fingerprint_html(normalized_html: str) -> str:
    """SHA-256 hex digest of the normalized HTML string.

    Args:
        normalized_html: Output of :func:`normalize_html`.

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(normalized_html.encode("utf-8")).hexdigest()


def _build_structure_string(element: HtmlElement) -> str:
    """Recursively build a tag-nesting representation of the DOM tree.

    Produces strings like ``html(body(div(h1,span,span),div(span)))``
    where only tag names and their parent/child/sibling relationships
    are captured. Text content and attribute values are ignored.
    """
    if not isinstance(element.tag, str):
        return ""

    children_parts: list[str] = []
    for child in element:
        part = _build_structure_string(child)
        if part:
            children_parts.append(part)

    tag = element.tag.lower()
    if children_parts:
        return f"{tag}({','.join(children_parts)})"
    return tag


def fingerprint_structure(normalized_html: str) -> str:
    """SHA-256 hex digest of the tag-nesting skeleton.

    Parses the normalized HTML, walks the tree, builds a string
    representation of tag names and their nesting, then hashes it.
    Two pages with identical DOM structure but different text content
    will produce the same structure fingerprint.

    Args:
        normalized_html: Output of :func:`normalize_html`.

    Returns:
        64-character lowercase hex string.
    """
    if not normalized_html:
        return hashlib.sha256(b"").hexdigest()

    tree = lxml.html.fromstring(normalized_html)
    structure = _build_structure_string(tree)
    return hashlib.sha256(structure.encode("utf-8")).hexdigest()


def are_structurally_identical(fingerprint_a: str, fingerprint_b: str) -> bool:
    """Return True if two structure fingerprints are identical.

    Exists as a named function for readability in calling code.
    """
    return fingerprint_a == fingerprint_b
