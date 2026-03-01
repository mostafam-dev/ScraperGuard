"""Tests for HTML and structural fingerprinting."""

from scraperguard.core.snapshot.fingerprint import (
    are_structurally_identical,
    fingerprint_html,
    fingerprint_structure,
)


class TestFingerprintHtml:
    def test_deterministic(self):
        """Same input produces same hash every time."""
        html = "<div><h1>Hello</h1><p>World</p></div>"
        expected = fingerprint_html(html)
        for _ in range(50):
            assert fingerprint_html(html) == expected

    def test_changes_with_content(self):
        """Same structure but different text produces different fingerprints."""
        html_a = "<div><span>Price: $79</span></div>"
        html_b = "<div><span>Price: $80</span></div>"
        assert fingerprint_html(html_a) != fingerprint_html(html_b)

    def test_empty_input(self):
        """Empty string produces consistent hash (SHA-256 of empty bytes)."""
        expected = "e3b0c44298fc1c149afbf4c8996fb924" \
                   "27ae41e4649b934ca495991b7852b855"
        result = fingerprint_html("")
        assert result == expected
        # Confirm determinism
        assert fingerprint_html("") == expected


class TestFingerprintStructure:
    def test_ignores_text(self):
        """Same structure with different text produces same structure fingerprint."""
        html_a = "<div><span>Price: $79</span><p>In stock</p></div>"
        html_b = "<div><span>Price: $80</span><p>Out of stock</p></div>"
        assert fingerprint_structure(html_a) == fingerprint_structure(html_b)

    def test_detects_structural_change(self):
        """Replacing a div with a section changes the structure fingerprint."""
        html_a = "<div><div>content</div></div>"
        html_b = "<div><section>content</section></div>"
        assert fingerprint_structure(html_a) != fingerprint_structure(html_b)

    def test_empty_input(self):
        """Empty string produces consistent hash."""
        expected = "e3b0c44298fc1c149afbf4c8996fb924" \
                   "27ae41e4649b934ca495991b7852b855"
        assert fingerprint_structure("") == expected


class TestAreStructurallyIdentical:
    def test_identical(self):
        assert are_structurally_identical("abc123", "abc123") is True

    def test_different(self):
        assert are_structurally_identical("abc123", "def456") is False
