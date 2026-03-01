"""Snapshot capture — the main entry point for integrations.

Coordinates normalization, fingerprinting, model construction, and
persistence into a single ``capture_snapshot`` call.
"""

from __future__ import annotations

import uuid
from typing import Any

from scraperguard.core.snapshot.fingerprint import fingerprint_html, fingerprint_structure
from scraperguard.core.snapshot.normalizer import normalize_html
from scraperguard.storage.base import StorageBackend
from scraperguard.storage.models import Snapshot, SnapshotMetadata


def capture_snapshot(
    url: str,
    raw_html: str,
    extracted_items: list[dict[str, Any]],
    metadata: SnapshotMetadata,
    storage: StorageBackend,
    store_raw_html: bool = False,
    run_id: str = "",
) -> Snapshot:
    """Normalize, fingerprint, persist, and return a DOM snapshot.

    Args:
        url: The page URL that was scraped.
        raw_html: The raw HTML response body.
        extracted_items: Structured data extracted from the page.
        metadata: HTTP-level metadata (status, latency, headers, etc.).
        storage: The storage backend to persist the snapshot to.
        store_raw_html: If True, keep the raw HTML in the snapshot.
        run_id: Identifier for the current scraper run.

    Returns:
        The persisted Snapshot instance.
    """
    normalized = normalize_html(raw_html)
    html_fp = fingerprint_html(normalized)  # noqa: F841 — available for callers later
    structure_fp = fingerprint_structure(normalized)

    snapshot = Snapshot(
        id=str(uuid.uuid4()),
        run_id=run_id,
        url=url,
        normalized_html=normalized,
        fingerprint=structure_fp,
        raw_html=raw_html if store_raw_html else None,
        extracted_items=extracted_items,
        metadata=metadata,
    )

    storage.save_snapshot(snapshot)
    return snapshot


def should_diff(current_fingerprint: str, previous_fingerprint: str | None) -> bool:
    """Decide whether a DOM diff is needed.

    Returns True if the structure fingerprints differ (meaning the DOM
    changed and diffing is warranted). Also returns True when there is
    no previous fingerprint (first run) — callers should interpret this
    as "no diff possible", not "must diff".

    Args:
        current_fingerprint: Structure fingerprint of the current snapshot.
        previous_fingerprint: Structure fingerprint of the previous snapshot,
            or None if this is the first observation.

    Returns:
        True if a diff should be computed.
    """
    if previous_fingerprint is None:
        return True
    return current_fingerprint != previous_fingerprint
