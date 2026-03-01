"""Tests for scraperguard.core.dom_diff.selector_tracker."""

from pathlib import Path

from scraperguard.core.dom_diff.parser import parse_to_tree
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus, track_selectors
from scraperguard.core.snapshot.normalizer import normalize_html

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _make_tree(html: str):
    return parse_to_tree(html)


def _simple_tree_with_spans(n: int) -> str:
    spans = "".join(f"<span>s{i}</span>" for i in range(n))
    return f"<html><body><div>{spans}</div></body></html>"


def test_track_stable_selector():
    html = _simple_tree_with_spans(3)
    current = _make_tree(html)
    previous = _make_tree(html)
    results = track_selectors(current, previous, ["span"])
    assert len(results) == 1
    assert results[0].status == "stable"
    assert results[0].current_matches == 3
    assert results[0].previous_matches == 3
    assert "unchanged" in results[0].message


def test_track_broken_selector():
    prev_html = '<html><body><span class="target">x</span></body></html>'
    curr_html = "<html><body><div>replaced</div></body></html>"
    results = track_selectors(_make_tree(curr_html), _make_tree(prev_html), [".target"])
    assert results[0].status == "broken"
    assert results[0].current_matches == 0
    assert results[0].previous_matches == 1
    assert "was 1" in results[0].message


def test_track_degraded_selector():
    prev_html = _simple_tree_with_spans(5)
    curr_html = _simple_tree_with_spans(2)
    results = track_selectors(_make_tree(curr_html), _make_tree(prev_html), ["span"])
    assert results[0].status == "degraded"
    assert results[0].current_matches == 2
    assert results[0].previous_matches == 5


def test_track_improved_selector():
    prev_html = _simple_tree_with_spans(1)
    curr_html = _simple_tree_with_spans(3)
    results = track_selectors(_make_tree(curr_html), _make_tree(prev_html), ["span"])
    assert results[0].status == "improved"
    assert results[0].current_matches == 3
    assert results[0].previous_matches == 1


def test_track_new_selector():
    curr_html = _simple_tree_with_spans(2)
    results = track_selectors(_make_tree(curr_html), None, ["span"])
    assert results[0].status == "new"
    assert results[0].previous_matches is None
    assert "first run" in results[0].message


def test_track_multiple_selectors():
    prev_html = (
        '<html><body>'
        '<span class="a">1</span>'
        '<span class="b">2</span><span class="b">3</span>'
        '<div class="c">4</div>'
        '</body></html>'
    )
    curr_html = (
        '<html><body>'
        '<span class="a">1</span>'
        '<span class="b">2</span><span class="b">3</span><span class="b">4</span>'
        '</body></html>'
    )
    results = track_selectors(
        _make_tree(curr_html),
        _make_tree(prev_html),
        [".a", ".b", ".c", "span"],
    )
    statuses = {r.selector: r.status for r in results}
    assert statuses[".a"] == "stable"
    assert statuses[".b"] == "improved"
    assert statuses[".c"] == "broken"
    assert statuses["span"] == "improved"


def test_track_with_real_fixtures():
    normal_html = (FIXTURES_DIR / "product_page_normal.html").read_text()
    changed_html = (FIXTURES_DIR / "product_page_changed.html").read_text()

    normal_normalized = normalize_html(normal_html)
    changed_normalized = normalize_html(changed_html)

    prev_tree = parse_to_tree(normal_normalized)
    curr_tree = parse_to_tree(changed_normalized)

    selectors = [".price-tag", ".price-tag span", ".availability", "div.product-container h1"]
    results = track_selectors(curr_tree, prev_tree, selectors)

    status_map = {r.selector: r for r in results}

    # .price-tag was <span class="price-tag"> in normal, replaced with <div class="new-price"> in changed
    assert status_map[".price-tag"].status == "broken"

    # .price-tag span — .price-tag had no nested span in normal (price-tag IS the span),
    # so this was 0 in both trees → "stable" (never matched)
    # If .price-tag itself is broken, a descendant selector within it also finds nothing
    assert status_map[".price-tag span"].current_matches == 0

    # .availability — was <span class="availability in-stock">, replaced with <div class="stock-status">
    assert status_map[".availability"].status == "broken"

    # div.product-container h1 — still present in both versions
    assert status_map["div.product-container h1"].status == "stable"
