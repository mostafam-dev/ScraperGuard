"""Selector tracking — monitors CSS selector match counts across snapshots.

Compares selector match counts between a current and previous DOM tree
to detect breakage, degradation, and improvements in scraper selectors.
"""

from __future__ import annotations

from dataclasses import dataclass

from scraperguard.core.dom_diff.parser import DOMNode, count_selector_matches


@dataclass
class SelectorStatus:
    """Status of a tracked CSS selector between two snapshots."""

    selector: str
    current_matches: int
    previous_matches: int | None
    status: str  # "stable", "degraded", "broken", "new", "improved"
    message: str


def _determine_status(current: int, previous: int | None) -> str:
    if previous is None:
        return "new"
    if current == 0 and previous > 0:
        return "broken"
    if current < previous and current > 0:
        return "degraded"
    if current > previous:
        return "improved"
    return "stable"


def _build_message(selector: str, status: str, current: int, previous: int | None) -> str:
    if status == "new":
        return f"Selector '{selector}' matches {current} nodes (first run)"
    if status == "stable":
        return f"Selector '{selector}' matches {current} nodes (unchanged)"
    if status == "broken":
        return f"Selector '{selector}' matches 0 nodes (was {previous})"
    # degraded or improved
    return f"Selector '{selector}' matches {current} nodes (was {previous})"


def track_selectors(
    current_tree: DOMNode,
    previous_tree: DOMNode | None,
    selectors: list[str],
) -> list[SelectorStatus]:
    """Track selector match counts between current and previous trees.

    Args:
        current_tree: The current parsed DOM tree.
        previous_tree: The previous parsed DOM tree, or None for first run.
        selectors: CSS selectors to track.

    Returns:
        List of SelectorStatus for each selector.
    """
    results: list[SelectorStatus] = []
    for selector in selectors:
        current_count = count_selector_matches(current_tree, selector)
        previous_count = count_selector_matches(previous_tree, selector) if previous_tree else None
        status = _determine_status(current_count, previous_count)
        message = _build_message(selector, status, current_count, previous_count)
        results.append(SelectorStatus(
            selector=selector,
            current_matches=current_count,
            previous_matches=previous_count,
            status=status,
            message=message,
        ))
    return results
