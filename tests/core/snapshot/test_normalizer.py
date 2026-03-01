"""Tests for the HTML normalization engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraperguard.core.snapshot.normalizer import (
    NormalizationError,
    extract_text_content,
    normalize_html,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Noise removal
# ---------------------------------------------------------------------------


class TestRemovesScriptTags:
    def test_removes_script_tags(self) -> None:
        html = """<html><body>
            <script>var x = 1;</script>
            <p>Hello</p>
            <script src="https://cdn.example.com/app.js"></script>
            <script type="text/javascript">
                document.write('injected');
            </script>
        </body></html>"""
        result = normalize_html(html)
        assert "<script" not in result
        assert "var x" not in result
        assert "document.write" not in result
        assert "Hello" in result


class TestRemovesStyleTags:
    def test_removes_style_tags(self) -> None:
        html = """<html><body>
            <style>.red { color: red; }</style>
            <p>Visible</p>
            <style type="text/css">body { margin: 0; }</style>
        </body></html>"""
        result = normalize_html(html)
        assert "<style" not in result
        assert "color: red" not in result
        assert "Visible" in result


class TestRemovesComments:
    def test_removes_comments(self) -> None:
        html = """<html>
        <!-- top comment -->
        <body>
            <!-- before paragraph -->
            <p>Text</p>
            <!-- after paragraph -->
            <div>More<!-- inline comment -->text</div>
        </body></html>"""
        result = normalize_html(html)
        assert "<!--" not in result
        assert "top comment" not in result
        assert "before paragraph" not in result
        assert "after paragraph" not in result
        assert "inline comment" not in result
        assert "Text" in result


class TestRemovesNoscript:
    def test_removes_noscript(self) -> None:
        html = """<html><body>
            <noscript>
                <p>Please enable JavaScript</p>
                <iframe src="https://tracking.example.com"></iframe>
            </noscript>
            <p>Content</p>
        </body></html>"""
        result = normalize_html(html)
        assert "<noscript" not in result
        assert "Please enable" not in result
        assert "Content" in result


# ---------------------------------------------------------------------------
# Attribute removal
# ---------------------------------------------------------------------------


class TestRemovesEventHandlerAttributes:
    def test_removes_event_handler_attributes(self) -> None:
        html = """<html><body>
            <button onclick="alert('hi')" onload="init()" onmouseover="hover()">Click</button>
        </body></html>"""
        result = normalize_html(html)
        assert "onclick" not in result
        assert "onload" not in result
        assert "onmouseover" not in result
        assert "<button" in result
        assert "Click" in result


class TestRemovesNoisyDataAttributes:
    def test_removes_noisy_data_attributes(self) -> None:
        html = """<html><body>
            <div data-analytics="page-view" data-tracking="cta" data-gtm-id="GTM-123">
                Content
            </div>
        </body></html>"""
        result = normalize_html(html)
        assert "data-analytics" not in result
        assert "data-tracking" not in result
        assert "data-gtm-id" not in result
        assert "Content" in result


class TestKeepsSemanticDataAttributes:
    def test_keeps_semantic_data_attributes(self) -> None:
        html = """<html><body>
            <div data-price="29.99" data-product="widget" data-available="true"
                 data-id="SKU-100">
                Widget
            </div>
        </body></html>"""
        result = normalize_html(html)
        assert 'data-price="29.99"' in result
        assert 'data-product="widget"' in result
        assert 'data-available="true"' in result
        assert 'data-id="SKU-100"' in result


class TestRemovesInlineStyles:
    def test_removes_inline_styles(self) -> None:
        html = """<html><body>
            <p style="color: red; font-weight: bold;">Styled</p>
            <div style="display: none;">Hidden</div>
        </body></html>"""
        result = normalize_html(html)
        assert "style=" not in result
        assert "Styled" in result


# ---------------------------------------------------------------------------
# Whitespace normalization
# ---------------------------------------------------------------------------


class TestNormalizesWhitespace:
    def test_normalizes_whitespace(self) -> None:
        html = """<html><body>
            <p>  Multiple   spaces   here  </p>
            <p>Tabs\there\tand\there</p>
            <p>New
            lines
            everywhere</p>
        </body></html>"""
        result = normalize_html(html)
        assert "Multiple spaces here" in result
        assert "Tabs here and here" in result
        assert "New lines everywhere" in result


# ---------------------------------------------------------------------------
# Empty element removal
# ---------------------------------------------------------------------------


class TestRemovesEmptyElements:
    def test_removes_empty_elements(self) -> None:
        html = """<html><body>
            <div></div>
            <span></span>
            <img src="photo.jpg" alt="photo">
            <table><tr><td></td></tr></table>
        </body></html>"""
        result = normalize_html(html)
        # Empty div and span should be gone
        assert "<div></div>" not in result
        assert "<span></span>" not in result
        # Void element img preserved
        assert "<img" in result
        # Empty td preserved
        assert "<td>" in result or "<td " in result


# ---------------------------------------------------------------------------
# Determinism and robustness
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_determinism(self) -> None:
        html = """<html><body>
            <div class="product" data-analytics="view" style="color:red">
                <script>var x=1;</script>
                <!-- comment -->
                <h1>Title</h1>
                <p onclick="track()">  Some   text  </p>
                <span data-price="9.99">$9.99</span>
            </div>
        </body></html>"""
        first = normalize_html(html)
        for _ in range(99):
            assert normalize_html(html) == first


class TestHandlesMalformedHtml:
    def test_handles_malformed_html(self) -> None:
        html = """<div><p>Unclosed paragraph
            <table><tr><td>Nested<table><tr><td>Deep</td></table>
            <b>Bold without close
            <img src=x alt=y>
            <span>Missing end"""
        result = normalize_html(html)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should not crash and should contain some content
        assert "Unclosed paragraph" in result or "Nested" in result


class TestHandlesEmptyInput:
    def test_handles_empty_input(self) -> None:
        assert normalize_html("") == ""
        assert normalize_html("   ") == ""
        assert normalize_html("\n\t") == ""


class TestHandlesNoiseOnlyHtml:
    def test_handles_noise_only_html(self) -> None:
        html = """<html><body>
            <script>var tracking = true;</script>
            <style>.hidden { display: none; }</style>
            <!-- only a comment -->
            <noscript>Fallback</noscript>
        </body></html>"""
        result = normalize_html(html)
        assert isinstance(result, str)
        # Should not crash; may return minimal skeleton or empty-ish result
        assert "<script" not in result
        assert "<style" not in result


# ---------------------------------------------------------------------------
# Fixture-based integration tests
# ---------------------------------------------------------------------------


class TestRealFixtureNormal:
    def test_real_fixture_normal(self) -> None:
        raw = (FIXTURES / "product_page_normal.html").read_text()
        result = normalize_html(raw)

        # Noise removed
        assert "<script" not in result
        assert "<style" not in result
        assert "<!--" not in result
        assert "<noscript" not in result

        # data-tracking / data-analytics removed
        assert "data-tracking" not in result
        assert "data-analytics" not in result

        # Structural content preserved
        assert "Wireless Bluetooth Headphones" in result
        assert "product-title" in result
        assert "price-tag" in result
        assert "$79.99" in result
        assert "In Stock" in result
        assert "spec-table" in result
        assert "review-block" in result


class TestRealFixtureChanged:
    def test_real_fixture_changed(self) -> None:
        raw = (FIXTURES / "product_page_changed.html").read_text()
        result = normalize_html(raw)

        # Noise removed
        assert "<script" not in result
        assert "<style" not in result

        # Structural change preserved: data-price div exists
        assert 'data-price="79.99"' in result
        assert "new-price" in result

        # data-available is a kept attribute
        assert 'data-available="true"' in result

        # Core content intact
        assert "Wireless Bluetooth Headphones" in result
        assert "features-grid" in result


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


class TestExtractTextContent:
    def test_extract_text_content(self) -> None:
        html = """<html><body>
            <h1>Title</h1>
            <p>First paragraph.</p>
            <p>Second <strong>bold</strong> paragraph.</p>
        </body></html>"""
        normalized = normalize_html(html)
        text = extract_text_content(normalized)
        assert "Title" in text
        assert "First paragraph." in text
        assert "bold" in text
        assert "<" not in text
        assert ">" not in text

    def test_extract_text_content_empty(self) -> None:
        assert extract_text_content("") == ""
