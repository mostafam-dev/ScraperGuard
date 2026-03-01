"""Playwright page observer — async context manager for observation.

Wraps Playwright page interactions to capture DOM state after navigation.
The context manager yields a PageObserver handle that stores extracted items
and triggers the full ScraperGuard pipeline on exit.

All ScraperGuard failures are caught internally — the observer never crashes
the user's Playwright script.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from scraperguard.core.classify.classifier import ClassificationInput, classify_failure
from scraperguard.core.dom_diff.differ import diff_trees
from scraperguard.core.dom_diff.parser import parse_to_tree
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus, track_selectors
from scraperguard.core.schema.drift import DriftEvent, run_drift_analysis
from scraperguard.core.snapshot.capture import capture_snapshot, should_diff
from scraperguard.health import HealthReport, compute_health_score
from scraperguard.storage.models import SnapshotMetadata

if TYPE_CHECKING:
    from scraperguard.config import ScraperGuardConfig
    from scraperguard.core.schema.base import BaseSchema
    from scraperguard.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class PageObserver:
    """Handle for a Playwright page observation.

    Captures ``page.content()`` on context exit, runs the full ScraperGuard
    analysis pipeline, and stores a health report accessible via
    :meth:`get_health_report`.

    Args:
        page: A Playwright ``Page`` object.
        storage: The storage backend to persist results.
        run_id: Identifier for the current scraper run.
        config: Optional ScraperGuard configuration.
        selectors: Optional CSS selectors to track across snapshots.
        schema: Optional BaseSchema subclass for item validation.
    """

    def __init__(
        self,
        page: object,
        storage: StorageBackend,
        run_id: str,
        config: ScraperGuardConfig | None = None,
        selectors: list[str] | None = None,
        schema: type[BaseSchema] | None = None,
    ) -> None:
        self._page = page
        self._storage = storage
        self._run_id = run_id
        self._config = config
        self._selectors = selectors or []
        self._schema = schema

        self._items: list[dict[str, Any]] = []
        self._url_override: str | None = None
        self._health_report: HealthReport | None = None
        self._start_time: float = 0.0
        self._raw_html: str = ""

    # -- Public setters ------------------------------------------------------

    def set_items(self, items: list[dict[str, Any]]) -> None:
        """Store extracted items for validation in the ``__aexit__`` phase.

        Args:
            items: List of dicts representing extracted data.
        """
        self._items = list(items)

    def set_url(self, url: str) -> None:
        """Override the URL used for snapshot storage.

        Useful for SPAs where ``page.url`` may not reflect the real content URL.

        Args:
            url: The URL to associate with the snapshot.
        """
        self._url_override = url

    def get_health_report(self) -> HealthReport | None:
        """Return the computed health report after context exit.

        Returns ``None`` if called before the context manager exits.
        """
        return self._health_report

    # -- Async context manager -----------------------------------------------

    async def __aenter__(self) -> PageObserver:
        self._start_time = time.monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        try:
            await self._run_pipeline()
        except Exception:
            logger.exception("ScraperGuard: Playwright observer pipeline failed")
        # Never suppress user exceptions
        return False

    # -- Pipeline ------------------------------------------------------------

    async def _run_pipeline(self) -> None:
        """Execute the full ScraperGuard analysis pipeline."""
        # --- Capture page state ---
        self._raw_html = await self._page.content()  # type: ignore[attr-defined]
        latency_ms = (time.monotonic() - self._start_time) * 1000

        url = self._url_override or self._page.url  # type: ignore[attr-defined]

        metadata = SnapshotMetadata(
            http_status=200,
            latency_ms=latency_ms,
            timestamp=datetime.now(UTC),
            headers={},
            response_size_bytes=len(self._raw_html.encode("utf-8")),
        )

        store_raw_html = False
        if self._config and hasattr(self._config, "snapshots"):
            store_raw_html = self._config.snapshots.store_raw_html

        # --- a) Capture snapshot ---
        snapshot = capture_snapshot(
            url=url,
            raw_html=self._raw_html,
            extracted_items=self._items,
            metadata=metadata,
            storage=self._storage,
            store_raw_html=store_raw_html,
            run_id=self._run_id,
        )

        # --- b) Schema validation + drift ---
        validation_result = None
        drift_events: list[DriftEvent] = []
        if self._schema is not None and self._items:
            try:
                validation_result = self._schema.validate_batch(
                    self._items,
                    run_id=self._run_id,
                    url=url,
                )
                # Run drift analysis BEFORE saving so current result
                # doesn't pollute the historical baseline.
                try:
                    threshold = 0.15
                    if self._config and hasattr(self._config, "schema"):
                        threshold = self._config.schema.null_drift_threshold
                    drift_events = run_drift_analysis(
                        validation_result,
                        self._storage,
                        threshold=threshold,
                    )
                except Exception:
                    logger.exception("ScraperGuard: Drift analysis failed for %s", url)
                self._storage.save_validation_result(validation_result)
            except Exception:
                logger.exception("ScraperGuard: Schema validation failed for %s", url)

        # --- d) DOM diff ---
        dom_changes: list[Any] = []
        try:
            snapshots = self._storage.list_snapshots(url, limit=2)
            prev_snapshot = None
            for s in snapshots:
                if s.id != snapshot.id:
                    prev_snapshot = s
                    break

            if prev_snapshot and should_diff(snapshot.fingerprint, prev_snapshot.fingerprint):
                before_tree = parse_to_tree(prev_snapshot.normalized_html)
                after_tree = parse_to_tree(snapshot.normalized_html)
                dom_changes = diff_trees(before_tree, after_tree)
        except Exception:
            logger.exception("ScraperGuard: DOM diff failed for %s", url)

        # --- e) Selector tracking ---
        selector_statuses: list[SelectorStatus] = []
        if self._selectors:
            try:
                current_tree = parse_to_tree(snapshot.normalized_html)
                prev_tree = None
                snapshots = self._storage.list_snapshots(url, limit=2)
                for s in snapshots:
                    if s.id != snapshot.id:
                        prev_tree = parse_to_tree(s.normalized_html)
                        break
                selector_statuses = track_selectors(current_tree, prev_tree, self._selectors)
            except Exception:
                logger.exception("ScraperGuard: Selector tracking failed for %s", url)

        # --- f) Failure classification ---
        classifications = []
        try:
            classifications = classify_failure(
                ClassificationInput(
                    validation_result=validation_result,
                    dom_changes=dom_changes,
                    selector_statuses=selector_statuses,
                    raw_html=self._raw_html or None,
                    http_status=metadata.http_status,
                    response_size_bytes=metadata.response_size_bytes,
                )
            )
        except Exception:
            logger.exception("ScraperGuard: Failure classification failed for %s", url)

        # --- g) Health score ---
        try:
            self._health_report = compute_health_score(
                validation_result=validation_result,
                selector_statuses=selector_statuses,
                dom_changes=dom_changes,
                classifications=classifications,
                drift_events=drift_events,
                run_id=self._run_id,
                url=url,
            )
        except Exception:
            logger.exception("ScraperGuard: Health score computation failed for %s", url)


@asynccontextmanager
async def observe(
    page: object,
    storage: StorageBackend,
    run_id: str,
    config: ScraperGuardConfig | None = None,
    selectors: list[str] | None = None,
    schema: type[BaseSchema] | None = None,
) -> AsyncGenerator[PageObserver, None]:
    """Async context manager that observes a Playwright page.

    Captures page state on exit and runs the full ScraperGuard analysis
    pipeline. All internal failures are caught — ScraperGuard never crashes
    the user's Playwright script.

    Usage::

        async with observe(page, storage=storage, run_id=run_id) as observer:
            await page.goto(url)
            data = await extract(page)
            observer.set_items(data)
        # On exit, ScraperGuard automatically captures snapshot and runs analysis

    Args:
        page: A Playwright ``Page`` object.
        storage: The storage backend to persist results.
        run_id: Identifier for the current scraper run.
        config: Optional ScraperGuard configuration.
        selectors: Optional CSS selectors to track across snapshots.
        schema: Optional BaseSchema subclass for item validation.

    Yields:
        :class:`PageObserver` handle for setting items and URL overrides.
    """
    observer = PageObserver(
        page=page,
        storage=storage,
        run_id=run_id,
        config=config,
        selectors=selectors,
        schema=schema,
    )
    async with observer:
        yield observer


async def capture_page(
    page: object,
    storage: StorageBackend,
    run_id: str,
    items: list[dict[str, Any]] | None = None,
    schema: type[BaseSchema] | None = None,
    selectors: list[str] | None = None,
) -> HealthReport | None:
    """One-shot convenience function for capturing a Playwright page.

    Captures the current page state, runs the full ScraperGuard pipeline,
    and returns the health report.

    Args:
        page: A Playwright ``Page`` object.
        storage: The storage backend to persist results.
        run_id: Identifier for the current scraper run.
        items: Optional extracted items for schema validation.
        schema: Optional BaseSchema subclass for item validation.
        selectors: Optional CSS selectors to track across snapshots.

    Returns:
        A :class:`~scraperguard.health.HealthReport`, or ``None`` if the
        pipeline fails entirely.
    """
    try:
        observer = PageObserver(
            page=page,
            storage=storage,
            run_id=run_id,
            selectors=selectors,
            schema=schema,
        )
        if items:
            observer.set_items(items)
        async with observer:
            pass
        return observer.get_health_report()
    except Exception:
        logger.exception("ScraperGuard: capture_page failed")
        return None
