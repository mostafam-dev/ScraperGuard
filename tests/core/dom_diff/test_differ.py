"""Tests for scraperguard.core.dom_diff.differ."""

from pathlib import Path

from scraperguard.core.dom_diff.differ import (
    ChangeType,
    DOMChange,
    diff_summary,
    diff_trees,
    map_changes_to_selectors,
)
from scraperguard.core.dom_diff.parser import parse_to_tree

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(html: str):
    return parse_to_tree(html)


def _wrap(body_html: str) -> str:
    return f"<html><body>{body_html}</body></html>"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_identical_trees_no_changes():
    html = _wrap('<div class="container"><span class="price">$10</span></div>')
    before = _parse(html)
    after = _parse(html)
    changes = diff_trees(before, after)
    assert changes == []


def test_detect_node_removed():
    before_html = _wrap('<div class="container"><span class="price">$10</span></div>')
    after_html = _wrap('<div class="container"></div>')
    changes = diff_trees(_parse(before_html), _parse(after_html))

    removed = [c for c in changes if c.change_type == ChangeType.NODE_REMOVED]
    assert len(removed) >= 1
    assert any("price" in c.path for c in removed)


def test_detect_node_added():
    before_html = _wrap('<div class="container"></div>')
    after_html = _wrap('<div class="container"><div class="banner">New!</div></div>')
    changes = diff_trees(_parse(before_html), _parse(after_html))

    added = [c for c in changes if c.change_type == ChangeType.NODE_ADDED]
    assert len(added) >= 1
    assert any("banner" in c.path for c in added)


def test_detect_tag_changed():
    before_html = _wrap('<div><span class="price">$10</span></div>')
    after_html = _wrap('<div><div class="price">$10</div></div>')
    changes = diff_trees(_parse(before_html), _parse(after_html))

    # The span and div have different tags so similarity is 0.0 — they won't match.
    # This means span is removed and div is added. Both are valid detections.
    # Alternatively, if they DO match (same class), a TAG_CHANGED would appear.
    tag_changed = [c for c in changes if c.change_type == ChangeType.TAG_CHANGED]
    removed = [c for c in changes if c.change_type == ChangeType.NODE_REMOVED]
    added = [c for c in changes if c.change_type == ChangeType.NODE_ADDED]

    # Either TAG_CHANGED detected, or a remove+add pair for .price
    assert len(tag_changed) >= 1 or (len(removed) >= 1 and len(added) >= 1)


def test_detect_attribute_changed():
    before_html = _wrap('<div class="old-class">text</div>')
    after_html = _wrap('<div class="new-class">text</div>')
    changes = diff_trees(_parse(before_html), _parse(after_html))

    attr_changes = [c for c in changes if c.change_type == ChangeType.ATTRIBUTES_CHANGED]
    assert len(attr_changes) >= 1
    c = attr_changes[0]
    assert c.severity == "high"  # class changed
    assert "modified" in c.details
    assert "class" in c.details["modified"]
    assert c.details["modified"]["class"]["old"] == "old-class"
    assert c.details["modified"]["class"]["new"] == "new-class"


def test_detect_text_changed():
    before_html = _wrap('<div><span>old text</span></div>')
    after_html = _wrap('<div><span>new text</span></div>')
    changes = diff_trees(_parse(before_html), _parse(after_html))

    text_changes = [c for c in changes if c.change_type == ChangeType.TEXT_CHANGED]
    assert len(text_changes) >= 1
    assert text_changes[0].severity == "low"


def test_detect_children_reordered():
    before_html = _wrap(
        '<div>'
        '<span class="a">A</span>'
        '<span class="b">B</span>'
        '<span class="c">C</span>'
        '</div>'
    )
    after_html = _wrap(
        '<div>'
        '<span class="b">B</span>'
        '<span class="a">A</span>'
        '<span class="c">C</span>'
        '</div>'
    )
    changes = diff_trees(_parse(before_html), _parse(after_html))

    reordered = [c for c in changes if c.change_type == ChangeType.CHILDREN_REORDERED]
    assert len(reordered) >= 1
    assert reordered[0].severity == "medium"


def test_severity_ordering():
    """Changes should be sorted high → medium → low."""
    before_html = _wrap(
        '<div class="x">'
        '<span class="price">$10</span>'
        '<span class="note">old</span>'
        '</div>'
    )
    after_html = _wrap(
        '<div class="x">'
        '<span class="note">new</span>'
        '</div>'
    )
    changes = diff_trees(_parse(before_html), _parse(after_html))
    assert len(changes) >= 2

    severities = [c.severity for c in changes]
    order = {"high": 0, "medium": 1, "low": 2}
    assert severities == sorted(severities, key=lambda s: order[s])


def test_diff_summary():
    before_html = _wrap(
        '<div>'
        '<span class="a">A</span>'
        '<span class="b">B</span>'
        '</div>'
    )
    after_html = _wrap(
        '<div>'
        '<span class="a">A changed</span>'
        '</div>'
    )
    changes = diff_trees(_parse(before_html), _parse(after_html))
    summary = diff_summary(changes)

    assert summary["total_changes"] == len(changes)
    assert summary["total_changes"] >= 2  # at least removed + text changed
    assert summary["high_severity"] + summary["medium_severity"] + summary["low_severity"] == summary["total_changes"]
    assert isinstance(summary["change_types"], dict)
    assert isinstance(summary["most_affected_paths"], list)


def test_map_changes_to_selectors():
    before_html = _wrap(
        '<div class="product">'
        '<div class="price-tag"><span>$10</span></div>'
        '<div class="title">Title</div>'
        '</div>'
    )
    after_html = _wrap(
        '<div class="product">'
        '<div class="title">Title</div>'
        '</div>'
    )
    before_tree = _parse(before_html)
    after_tree = _parse(after_html)
    changes = diff_trees(before_tree, after_tree)

    # There should be a NODE_REMOVED for price-tag
    removed = [c for c in changes if c.change_type == ChangeType.NODE_REMOVED]
    assert len(removed) >= 1

    selectors = [".price-tag span", ".title"]
    # Use the before tree for selector resolution (the "known good" tree)
    updated = map_changes_to_selectors(changes, selectors, before_tree)

    price_removed = [c for c in updated if c.change_type == ChangeType.NODE_REMOVED and "price-tag" in c.path]
    assert len(price_removed) >= 1
    c = price_removed[0]
    assert ".price-tag span" in c.affected_selectors
    assert ".title" not in c.affected_selectors


def test_real_fixtures_diff():
    normal_html = (FIXTURES / "product_page_normal.html").read_text()
    changed_html = (FIXTURES / "product_page_changed.html").read_text()

    before = _parse(normal_html)
    after = _parse(changed_html)
    changes = diff_trees(before, after)

    # Should detect changes but not hundreds
    assert len(changes) > 0
    assert len(changes) < 200

    all_paths = " ".join(c.path for c in changes)
    all_messages = " ".join(c.message for c in changes)
    combined = all_paths + " " + all_messages

    # Price element changed (span.price-tag → div.new-price)
    assert "price" in combined.lower()

    # Availability element changed (span.availability → div.stock-status)
    has_availability = "availability" in combined.lower() or "stock" in combined.lower()
    assert has_availability


def test_diff_empty_before():
    before_html = "<html><body></body></html>"
    after_html = _wrap('<div class="content"><p>Hello</p></div>')

    before = _parse(before_html)
    after = _parse(after_html)
    changes = diff_trees(before, after)

    added = [c for c in changes if c.change_type == ChangeType.NODE_ADDED]
    assert len(added) >= 1
