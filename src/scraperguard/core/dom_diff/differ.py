"""Tree diffing — structural comparison of normalized DOM snapshots.

Compares two DOMNode trees and produces a structured list of changes.
This is a tree-level structural comparison, not a text diff.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from scraperguard.core.dom_diff.parser import DOMNode, find_nodes_by_selector


class ChangeType(str, Enum):
    """Categories of structural DOM changes."""

    NODE_REMOVED = "node_removed"
    NODE_ADDED = "node_added"
    NODE_MOVED = "node_moved"
    TAG_CHANGED = "tag_changed"
    ATTRIBUTES_CHANGED = "attributes_changed"
    CHILDREN_REORDERED = "children_reordered"
    TEXT_CHANGED = "text_changed"


# Keep old names around so existing imports from __init__.py don't break.
# DiffReport is referenced by the classifier stub (as object type hint in docstring only).
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class DOMChange:
    """A single detected structural change between two DOM trees."""

    change_type: ChangeType
    path: str
    severity: str  # "high", "medium", "low"
    details: dict = field(default_factory=dict)
    affected_selectors: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class DiffReport:
    """Legacy wrapper kept for backward compatibility."""

    changes: list[DOMChange] = field(default_factory=list)
    severity_summary: dict[str, int] = field(default_factory=dict)
    structural_similarity: float = 1.0


Change = DOMChange  # alias


# ---------------------------------------------------------------------------
# Similarity scoring for child matching
# ---------------------------------------------------------------------------

def _node_classes(node: DOMNode) -> set[str]:
    cls = node.attributes.get("class", "")
    return set(cls.split()) if cls else set()


def _similarity(a: DOMNode, b: DOMNode) -> float:
    if a.tag != b.tag:
        return 0.0
    if _node_classes(a) == _node_classes(b):
        return 1.0
    return 0.5


# ---------------------------------------------------------------------------
# Core diffing
# ---------------------------------------------------------------------------

def _diff_nodes(before: DOMNode, after: DOMNode, changes: list[DOMChange]) -> None:
    """Recursively compare two nodes and collect changes."""
    # Tag change
    if before.tag != after.tag:
        changes.append(DOMChange(
            change_type=ChangeType.TAG_CHANGED,
            path=before.path,
            severity="high",
            details={"old_tag": before.tag, "new_tag": after.tag},
            message=f"Element at {before.path} changed from '{before.tag}' to '{after.tag}'",
        ))

    # Attribute change
    if before.attributes != after.attributes:
        added = {k: after.attributes[k] for k in after.attributes if k not in before.attributes}
        removed = {k: before.attributes[k] for k in before.attributes if k not in after.attributes}
        modified = {
            k: {"old": before.attributes[k], "new": after.attributes[k]}
            for k in before.attributes
            if k in after.attributes and before.attributes[k] != after.attributes[k]
        }
        details = {}
        if added:
            details["added"] = added
        if removed:
            details["removed"] = removed
        if modified:
            details["modified"] = modified

        class_changed = (
            "class" in added or "class" in removed or "class" in modified
        )
        severity = "high" if class_changed else "medium"

        parts: list[str] = []
        if added:
            parts.append(f"added {list(added.keys())}")
        if removed:
            parts.append(f"removed {list(removed.keys())}")
        if modified:
            parts.append(f"modified {list(modified.keys())}")
        summary = ", ".join(parts)

        changes.append(DOMChange(
            change_type=ChangeType.ATTRIBUTES_CHANGED,
            path=before.path,
            severity=severity,
            details=details,
            message=f"Attributes changed at {before.path}: {summary}",
        ))

    # Text change
    if before.text != after.text:
        changes.append(DOMChange(
            change_type=ChangeType.TEXT_CHANGED,
            path=before.path,
            severity="low",
            details={"old_text": before.text, "new_text": after.text},
            message=f"Text content changed at {before.path}",
        ))

    # Compare children
    _diff_children(before, after, changes)


def _diff_children(before: DOMNode, after: DOMNode, changes: list[DOMChange]) -> None:
    """Match and compare children lists."""
    before_children = before.children
    after_children = after.children

    if not before_children and not after_children:
        return

    # Greedy matching: for each before-child, find best match in after-children
    used_after: set[int] = set()
    matches: list[tuple[int, int]] = []  # (before_idx, after_idx)

    for bi, bchild in enumerate(before_children):
        best_score = 0.0
        best_ai = -1
        for ai, achild in enumerate(after_children):
            if ai in used_after:
                continue
            score = _similarity(bchild, achild)
            if score > best_score:
                best_score = score
                best_ai = ai
        if best_score >= 0.3 and best_ai >= 0:
            matches.append((bi, best_ai))
            used_after.add(best_ai)

    matched_before = {bi for bi, _ in matches}
    matched_after = {ai for _, ai in matches}

    # Unmatched before children -> NODE_REMOVED
    for bi, bchild in enumerate(before_children):
        if bi not in matched_before:
            changes.append(DOMChange(
                change_type=ChangeType.NODE_REMOVED,
                path=bchild.path,
                severity="high",
                details={"tag": bchild.tag},
                message=f"Element '{bchild.tag}' at {bchild.path} was removed",
            ))

    # Unmatched after children -> NODE_ADDED
    for ai, achild in enumerate(after_children):
        if ai not in matched_after:
            changes.append(DOMChange(
                change_type=ChangeType.NODE_ADDED,
                path=achild.path,
                severity="medium",
                details={"tag": achild.tag},
                message=f"New element '{achild.tag}' added at {achild.path}",
            ))

    # Check reordering among matched pairs
    if len(matches) >= 2:
        after_indices = [ai for _, ai in matches]
        # If after-indices are not monotonically increasing, children were reordered
        if any(after_indices[i] > after_indices[i + 1] for i in range(len(after_indices) - 1)):
            changes.append(DOMChange(
                change_type=ChangeType.CHILDREN_REORDERED,
                path=before.path,
                severity="medium",
                details={
                    "before_order": [before_children[bi].tag for bi, _ in matches],
                    "after_order": [after_children[ai].tag for _, ai in sorted(matches, key=lambda m: m[1])],
                },
                message=f"Children reordered at {before.path}",
            ))

    # Recurse into matched pairs
    for bi, ai in matches:
        _diff_nodes(before_children[bi], after_children[ai], changes)


def diff_trees(before: DOMNode, after: DOMNode) -> list[DOMChange]:
    """Compare two DOMNode trees and produce a structured list of changes.

    Args:
        before: The baseline DOM tree.
        after: The current DOM tree to compare against.

    Returns:
        List of DOMChange instances, sorted by severity (high first).
    """
    changes: list[DOMChange] = []
    _diff_nodes(before, after, changes)
    changes.sort(key=lambda c: _SEVERITY_ORDER.get(c.severity, 99))
    return changes


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def diff_summary(changes: list[DOMChange]) -> dict:
    """Return a summary dict of the changes."""
    severity_counts = Counter(c.severity for c in changes)
    type_counts = Counter(c.change_type.value for c in changes)
    path_counts = Counter(c.path for c in changes)
    most_affected = [path for path, _ in path_counts.most_common(5)]

    return {
        "total_changes": len(changes),
        "high_severity": severity_counts.get("high", 0),
        "medium_severity": severity_counts.get("medium", 0),
        "low_severity": severity_counts.get("low", 0),
        "change_types": dict(type_counts),
        "most_affected_paths": most_affected,
    }


# ---------------------------------------------------------------------------
# Selector mapping
# ---------------------------------------------------------------------------

def map_changes_to_selectors(
    changes: list[DOMChange],
    selectors: list[str],
    tree: DOMNode,
) -> list[DOMChange]:
    """Populate affected_selectors on each change based on selector relevance.

    A change affects a selector if:
    - The changed element's path contains the selector's target class or tag.
    - The changed element is an ancestor of nodes that the selector would match.
    """
    # Pre-resolve which nodes each selector matches
    selector_nodes: dict[str, list[DOMNode]] = {}
    for sel in selectors:
        selector_nodes[sel] = find_nodes_by_selector(tree, sel)

    for change in changes:
        affected: list[str] = []
        for sel in selectors:
            # Extract classes and tags from selector for path-based check
            sel_parts = sel.replace(".", " .").replace(">", " ").split()
            path_match = False
            for part in sel_parts:
                part = part.strip()
                if not part:
                    continue
                if part.startswith("."):
                    # Class-based: check if class name appears in the changed path
                    cls_name = part[1:]
                    if cls_name and cls_name in change.path:
                        path_match = True
                        break
                else:
                    # Tag-based: less specific, check if tag appears as a segment
                    if part in change.path.split():
                        path_match = True
                        break

            if path_match:
                affected.append(sel)
                continue

            # Ancestor check: is the changed path a prefix of any matched node's path?
            for node in selector_nodes.get(sel, []):
                if node.path.startswith(change.path + " > ") or node.path == change.path:
                    affected.append(sel)
                    break

        change.affected_selectors = affected

    return changes
