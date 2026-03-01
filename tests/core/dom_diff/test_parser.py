"""Tests for scraperguard.core.dom_diff.parser."""

from scraperguard.core.dom_diff.parser import (
    DOMNode,
    count_selector_matches,
    find_nodes_by_selector,
    parse_to_tree,
    tree_to_signature,
)


# ---------------------------------------------------------------------------
# parse_to_tree tests
# ---------------------------------------------------------------------------

def test_parse_simple_html():
    html = "<html><body><div><span>hello</span></div></body></html>"
    tree = parse_to_tree(html)

    assert tree.tag == "html"
    assert len(tree.children) == 1

    body = tree.children[0]
    assert body.tag == "body"
    assert len(body.children) == 1

    div = body.children[0]
    assert div.tag == "div"
    assert len(div.children) == 1

    span = div.children[0]
    assert span.tag == "span"
    assert span.text == "hello"


def test_parse_preserves_attributes():
    html = '<html><body><div class="container" id="main">text</div></body></html>'
    tree = parse_to_tree(html)
    div = tree.children[0].children[0]  # body > div
    assert div.attributes["class"] == "container"
    assert div.attributes["id"] == "main"


def test_parse_depth_tracking():
    html = "<html><body><div><span>x</span></div></body></html>"
    tree = parse_to_tree(html)
    assert tree.depth == 0  # html
    assert tree.children[0].depth == 1  # body
    assert tree.children[0].children[0].depth == 2  # div
    assert tree.children[0].children[0].children[0].depth == 3  # span


def test_parse_path_generation():
    html = '<html><body><div class="product"><span class="price">$9</span></div></body></html>'
    tree = parse_to_tree(html)
    span = tree.children[0].children[0].children[0]  # body > div.product > span.price
    assert span.path == "html > body > div.product > span.price"


def test_parse_classes_sorted_in_path():
    html = '<html><body><div class="beta alpha">x</div></body></html>'
    tree = parse_to_tree(html)
    div = tree.children[0].children[0]  # body > div
    assert "div.alpha.beta" in div.path


def test_tree_to_signature():
    html = "<html><body><div><h1>Title</h1><span>a</span><span>b</span></div><div><span>c</span></div></body></html>"
    tree = parse_to_tree(html)
    sig = tree_to_signature(tree)
    assert sig == "html(body(div(h1,span,span),div(span)))"


def test_tree_to_signature_deterministic():
    html = "<html><body><div><h1>Title</h1><span>a</span></div></body></html>"
    sig1 = tree_to_signature(parse_to_tree(html))
    sig2 = tree_to_signature(parse_to_tree(html))
    assert sig1 == sig2


# ---------------------------------------------------------------------------
# find_nodes_by_selector tests
# ---------------------------------------------------------------------------

def test_find_by_tag():
    html = "<html><body><div><span>a</span><span>b</span></div><span>c</span></body></html>"
    tree = parse_to_tree(html)
    results = find_nodes_by_selector(tree, "span")
    assert len(results) == 3


def test_find_by_class():
    html = '<html><body><span class="price-tag">$10</span><span>other</span></body></html>'
    tree = parse_to_tree(html)
    results = find_nodes_by_selector(tree, ".price-tag")
    assert len(results) == 1
    assert results[0].text == "$10"


def test_find_by_tag_and_class():
    html = '<html><body><span class="price">$10</span><div class="price">x</div></body></html>'
    tree = parse_to_tree(html)
    results = find_nodes_by_selector(tree, "span.price")
    assert len(results) == 1
    assert results[0].tag == "span"


def test_find_descendant_selector():
    html = (
        '<html><body>'
        '<div class="product"><span>inside</span></div>'
        '<span>outside</span>'
        '</body></html>'
    )
    tree = parse_to_tree(html)
    results = find_nodes_by_selector(tree, "div.product span")
    assert len(results) == 1
    assert results[0].text == "inside"


def test_find_direct_child_selector():
    html = (
        '<html><body>'
        '<div class="product"><span>direct</span><div><span>nested</span></div></div>'
        '</body></html>'
    )
    tree = parse_to_tree(html)
    results = find_nodes_by_selector(tree, "div.product > span")
    assert len(results) == 1
    assert results[0].text == "direct"


def test_find_no_matches():
    html = "<html><body><div>text</div></body></html>"
    tree = parse_to_tree(html)
    results = find_nodes_by_selector(tree, "span.nonexistent")
    assert results == []


def test_count_selector_matches():
    html = "<html><body><span>a</span><span>b</span><div>c</div></body></html>"
    tree = parse_to_tree(html)
    assert count_selector_matches(tree, "span") == 2
    assert count_selector_matches(tree, "span") == len(find_nodes_by_selector(tree, "span"))
