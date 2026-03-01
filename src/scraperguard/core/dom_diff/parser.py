"""DOM tree parser — converts normalized HTML into a tree for structural comparison.

Operates on the OUTPUT of the normalizer (clean, deterministic HTML),
not raw HTML. Produces a DOMNode tree that can be compared, diffed,
and queried with simplified CSS selectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lxml.html


@dataclass
class DOMNode:
    """A node in the parsed DOM tree."""

    tag: str
    attributes: dict[str, str] = field(default_factory=dict)
    children: list[DOMNode] = field(default_factory=list)
    text: str = ""
    tail: str = ""
    depth: int = 0
    path: str = ""


def _tag_with_classes(tag: str, attributes: dict[str, str]) -> str:
    """Build a CSS-like tag identifier: tag.class1.class2 (classes sorted)."""
    cls = attributes.get("class", "")
    if cls:
        classes = sorted(cls.split())
        return tag + "." + ".".join(classes)
    return tag


def _build_tree(element: lxml.html.HtmlElement, depth: int, parent_path: str) -> DOMNode:
    """Recursively convert an lxml element into a DOMNode."""
    tag = element.tag.lower() if isinstance(element.tag, str) else str(element.tag)
    attributes = dict(sorted(element.attrib.items()))
    twc = _tag_with_classes(tag, attributes)
    path = f"{parent_path} > {twc}" if parent_path else twc
    text = (element.text or "").strip()
    tail = (element.tail or "").strip()

    children = []
    for child in element:
        if isinstance(child.tag, str):
            children.append(_build_tree(child, depth + 1, path))

    return DOMNode(
        tag=tag,
        attributes=attributes,
        children=children,
        text=text,
        tail=tail,
        depth=depth,
        path=path,
    )


def parse_to_tree(normalized_html: str) -> DOMNode:
    """Parse normalized HTML into a DOMNode tree.

    Args:
        normalized_html: Output of the normalizer (clean HTML string).

    Returns:
        Root DOMNode of the parsed tree.
    """
    element = lxml.html.fromstring(normalized_html)
    return _build_tree(element, depth=0, parent_path="")


def tree_to_signature(node: DOMNode) -> str:
    """Produce a structural signature of the tree (tags and nesting only).

    Format: "tag(child1,child2,...)" recursively.
    Example: "html(body(div(h1,span,span),div(span)))"
    """
    if not node.children:
        return node.tag
    child_sigs = ",".join(tree_to_signature(c) for c in node.children)
    return f"{node.tag}({child_sigs})"


# ---------------------------------------------------------------------------
# Simplified CSS selector matching
# ---------------------------------------------------------------------------


def _parse_simple_selector(sel: str) -> tuple[str | None, list[str]]:
    """Parse a single simple selector like 'div.price-tag' into (tag, [classes]).

    Returns (tag_or_None, list_of_classes).
    """
    parts = sel.split(".")
    tag = parts[0] if parts[0] else None
    classes = [p for p in parts[1:] if p]
    return tag, classes


def _node_matches_simple(node: DOMNode, tag: str | None, classes: list[str]) -> bool:
    """Check if a single node matches a simple selector (tag + classes)."""
    if tag and node.tag != tag:
        return False
    if classes:
        node_classes = set(node.attributes.get("class", "").split())
        for cls in classes:
            if cls not in node_classes:
                return False
    return True


def _tokenize_selector(selector: str) -> list[str]:
    """Split a selector string into tokens: simple selectors, '>', and implicit descendant.

    Returns a list like ['div.product', '>', 'span'] or ['div.product', ' ', 'span'].
    """
    tokens: list[str] = []
    parts = selector.split()
    for part in parts:
        if part == ">":
            # Replace any trailing implicit-descendant with direct-child
            if tokens and tokens[-1] == " ":
                tokens[-1] = ">"
            else:
                tokens.append(">")
        else:
            if tokens and tokens[-1] not in (">", " ") and tokens[-1] != "":
                tokens.append(" ")
            tokens.append(part)
    return tokens


def find_nodes_by_selector(tree: DOMNode, selector: str) -> list[DOMNode]:
    """Find nodes matching a simplified CSS selector.

    Supports:
    - Tag selectors: "div", "span"
    - Class selectors: ".price-tag"
    - Combined: "div.price-tag"
    - Descendant: "div.price-section span"
    - Direct child: "div.price-section > span"

    Args:
        tree: Root DOMNode to search.
        selector: CSS selector string.

    Returns:
        List of matching DOMNode instances.
    """
    tokens = _tokenize_selector(selector)
    if not tokens:
        return []

    # Parse each simple selector token
    selectors: list[tuple[str, str | None, list[str]]] = []
    # selectors = list of (combinator, tag, classes)
    # First token has no combinator
    tag, classes = _parse_simple_selector(tokens[0])
    selectors.append(("", tag, classes))

    i = 1
    while i < len(tokens):
        if tokens[i] in (">", " "):
            combinator = tokens[i]
            i += 1
            if i < len(tokens):
                tag, classes = _parse_simple_selector(tokens[i])
                selectors.append((combinator, tag, classes))
            i += 1
        else:
            tag, classes = _parse_simple_selector(tokens[i])
            selectors.append((" ", tag, classes))
            i += 1

    def _collect_all_nodes(node: DOMNode) -> list[DOMNode]:
        """Collect all nodes in the tree (pre-order)."""
        result = [node]
        for child in node.children:
            result.extend(_collect_all_nodes(child))
        return result

    def _is_ancestor(ancestor: DOMNode, node: DOMNode) -> bool:
        """Check if ancestor's path is a prefix of node's path and depths differ."""
        return node.path.startswith(ancestor.path + " > ") and node.depth > ancestor.depth

    def _is_direct_parent(parent: DOMNode, child: DOMNode) -> bool:
        """Check if parent is the direct parent of child."""
        return child.depth == parent.depth + 1 and child.path.startswith(parent.path + " > ")

    all_nodes = _collect_all_nodes(tree)

    # Start with nodes matching first selector
    _, first_tag, first_classes = selectors[0]
    candidates = [n for n in all_nodes if _node_matches_simple(n, first_tag, first_classes)]

    # Apply each subsequent selector with its combinator
    for combinator, stag, sclasses in selectors[1:]:
        next_candidates = []
        for candidate in candidates:
            for node in all_nodes:
                if not _node_matches_simple(node, stag, sclasses):
                    continue
                if combinator == " " and _is_ancestor(candidate, node):
                    next_candidates.append(node)
                elif combinator == ">" and _is_direct_parent(candidate, node):
                    next_candidates.append(node)
        # Deduplicate while preserving order
        seen: set[int] = set()
        deduped = []
        for n in next_candidates:
            nid = id(n)
            if nid not in seen:
                seen.add(nid)
                deduped.append(n)
        candidates = deduped

    return candidates


def count_selector_matches(tree: DOMNode, selector: str) -> int:
    """Count nodes matching a CSS selector.

    Convenience wrapper around :func:`find_nodes_by_selector`.
    """
    return len(find_nodes_by_selector(tree, selector))
