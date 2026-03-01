"""Structural DOM diffing engine.

Compares normalized DOM trees (not raw HTML) to detect:
- Node removal and insertion
- Structural reordering
- Attribute mutations
- Selector invalidation
- A/B layout variant detection

Each change is scored by severity and mapped to affected data fields.
"""

from scraperguard.core.dom_diff.differ import (
    ChangeType,
    DiffReport,
    DOMChange,
    diff_summary,
    diff_trees,
    map_changes_to_selectors,
)
from scraperguard.core.dom_diff.parser import (
    DOMNode,
    count_selector_matches,
    find_nodes_by_selector,
    parse_to_tree,
    tree_to_signature,
)
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus, track_selectors

__all__ = [
    "ChangeType",
    "DOMChange",
    "DOMNode",
    "DiffReport",
    "SelectorStatus",
    "count_selector_matches",
    "diff_summary",
    "diff_trees",
    "find_nodes_by_selector",
    "map_changes_to_selectors",
    "parse_to_tree",
    "track_selectors",
    "tree_to_signature",
]
