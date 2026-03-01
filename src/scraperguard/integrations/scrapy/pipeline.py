"""Scrapy item pipeline — validates extracted items against a ScraperGuard schema.

Runs after item extraction. Collects items into batches per URL and validates
them against the configured schema, recording validation results and
triggering drift analysis, DOM diffing, failure classification, and health scoring.
"""

from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from scraperguard.core.classify.classifier import ClassificationInput, classify_failure
from scraperguard.core.dom_diff.differ import diff_trees
from scraperguard.core.dom_diff.parser import parse_to_tree
from scraperguard.core.dom_diff.selector_tracker import SelectorStatus, track_selectors
from scraperguard.core.schema.drift import DriftEvent, run_drift_analysis
from scraperguard.core.snapshot.capture import capture_snapshot, should_diff
from scraperguard.health import compute_health_score, format_health_report
from scraperguard.integrations.scrapy import signals
from scraperguard.storage.models import SnapshotMetadata

if TYPE_CHECKING:
    from scrapy import Spider
    from scrapy.crawler import Crawler

    from scraperguard.core.schema.base import BaseSchema
    from scraperguard.storage.base import StorageBackend

logger = logging.getLogger(__name__)


def _import_class(dotted_path: str) -> type[Any]:
    """Dynamically import a class from a dotted module path.

    Example: ``"myproject.schemas.ProductSchema"`` imports and returns
    the ``ProductSchema`` class from ``myproject.schemas``.
    """
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ImportError(f"Invalid dotted path: {dotted_path!r}")
    module = importlib.import_module(module_path)
    cls: type[Any] = getattr(module, class_name)
    return cls


class ScraperGuardValidationPipeline:
    """Scrapy item pipeline that validates items through ScraperGuard.

    Accumulates items per URL, validates each batch against the
    configured :class:`~scraperguard.core.schema.base.BaseSchema`,
    records results, runs drift analysis, DOM diffing, failure
    classification, and health scoring.
    """

    def __init__(
        self,
        schema_cls: type[BaseSchema] | None,
        storage: StorageBackend | None,
        run_id: str,
        config: Any,
        selectors: list[str],
        store_raw_html: bool,
        crawler: Crawler | None = None,
    ) -> None:
        self.schema_cls = schema_cls
        self.storage = storage
        self.run_id = run_id
        self.config = config
        self.selectors = selectors
        self.store_raw_html = store_raw_html
        self.crawler = crawler
        self._items_by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> ScraperGuardValidationPipeline:
        """Instantiate from a Scrapy crawler, reading ScraperGuard settings.

        Reads the following from ``crawler.settings``:

        - ``SCRAPERGUARD_SCHEMA`` (str, optional): Dotted path to a
          :class:`BaseSchema` subclass (e.g. ``"myproject.schemas.ProductSchema"``).

        Shares storage backend and run_id with the
        :class:`~scraperguard.integrations.scrapy.middleware.ScraperGuardObserverMiddleware`
        via the crawler instance.
        """
        try:
            schema_dotted = crawler.settings.get("SCRAPERGUARD_SCHEMA", None)
            schema_cls = None
            if schema_dotted:
                schema_cls = _import_class(schema_dotted)

            # Get storage and run_id from the middleware (shared via crawler)
            middleware = cls._get_middleware(crawler)
            storage = middleware.storage if middleware else None
            run_id = middleware.run_id if middleware else ""
            config = middleware.config if middleware else None
            selectors = middleware.selectors if middleware else []
            store_raw_html = middleware.store_raw_html if middleware else False

            return cls(
                schema_cls=schema_cls,
                storage=storage,
                run_id=run_id,
                config=config,
                selectors=selectors,
                store_raw_html=store_raw_html,
                crawler=crawler,
            )
        except Exception:
            logger.exception("ScraperGuard: Failed to initialize pipeline")
            instance = cls(
                schema_cls=None,
                storage=None,
                run_id="",
                config=None,
                selectors=[],
                store_raw_html=False,
            )
            return instance

    @staticmethod
    def _get_middleware(crawler: Crawler) -> Any:
        """Retrieve the ObserverMiddleware instance from the crawler's middleware manager."""
        from scraperguard.integrations.scrapy.middleware import ScraperGuardObserverMiddleware

        try:
            if hasattr(crawler, "engine") and crawler.engine:
                dm = crawler.engine.downloader.middleware
                for mw in dm.middlewares:
                    if isinstance(mw, ScraperGuardObserverMiddleware):
                        return mw
        except Exception:
            pass

        # Fallback: check if middleware stored itself on the crawler
        return getattr(crawler, "_scraperguard_middleware", None)

    def open_spider(self, spider: Spider) -> None:
        """Initialize batch collection for a new spider run."""
        self._items_by_url = defaultdict(list)

    def process_item(self, item: Any, spider: Spider) -> Any:
        """Accumulate an item for batch validation.

        Extracts the URL from the item's ``url`` field, ``response_url``
        field, or falls back to the spider name. Converts the item to a
        dict and appends it to the per-URL buffer.

        Returns the item unchanged. ScraperGuard observes, it does not interfere.
        """
        try:
            item_dict = dict(item)

            # Determine URL for grouping
            url = (
                item_dict.get("url")
                or item_dict.get("response_url")
                or getattr(spider, "start_urls", ["unknown"])[0]
                if hasattr(spider, "start_urls") and spider.start_urls
                else "unknown"
            )
            if not isinstance(url, str):
                url = str(url)

            self._items_by_url[url].append(item_dict)
        except Exception:
            logger.exception("ScraperGuard: Error buffering item")

        return item

    def close_spider(self, spider: Spider) -> None:
        """Run the full ScraperGuard analysis pipeline on spider close.

        For each URL in the buffer:
        1. Capture snapshot with collected items
        2. Validate batch against schema
        3. Save validation result
        4. Run drift analysis
        5. Get previous snapshot, run DOM diff if fingerprint changed
        6. Track selectors if configured
        7. Run failure classifier
        8. Compute health score
        9. Log the health report summary
        10. Fire custom signals
        """
        if self.storage is None:
            logger.warning("ScraperGuard: No storage backend available, skipping analysis")
            return

        middleware = self._get_middleware(self.crawler) if self.crawler else None

        for url, items in self._items_by_url.items():
            try:
                self._analyze_url(url, items, spider, middleware)
            except Exception:
                logger.exception("ScraperGuard: Error analyzing URL %s", url)

    def _dispatch_alerts(
        self,
        classifications: list[Any],
        url: str,
        spider: Spider,
    ) -> None:
        """Send alerts for critical/warning classifications."""
        if not self.config or not hasattr(self.config, "alerts"):
            return
        alerts_cfg = self.config.alerts
        dispatchers: list[Any] = []
        try:
            if alerts_cfg.slack.enabled and alerts_cfg.slack.webhook:
                from scraperguard.alerts.slack import SlackDispatcher

                dispatchers.append(SlackDispatcher(alerts_cfg.slack.webhook))
            if alerts_cfg.webhook_url:
                from scraperguard.alerts.webhook import WebhookDispatcher

                dispatchers.append(WebhookDispatcher(alerts_cfg.webhook_url))
        except Exception:
            return
        if not dispatchers:
            return
        from scraperguard.alerts.dispatcher import AlertManager
        from scraperguard.alerts.models import Alert

        alert_mgr = AlertManager(dispatchers, alerts_cfg.thresholds)
        for c in classifications:
            if c.severity in ("critical", "warning"):
                alert = Alert(
                    severity=c.severity,
                    title=f"{c.failure_type.value} detected",
                    message=c.recommended_action,
                    scraper_name=getattr(spider, "name", "unknown"),
                    url=url,
                    run_id=self.run_id,
                )
                results = alert_mgr.dispatch(alert)
                for name, ok in results.items():
                    status = "OK" if ok else "FAILED"
                    spider.logger.info(
                        "ScraperGuard: Alert sent to %s: %s",
                        name,
                        status,
                    )

    def _analyze_url(
        self,
        url: str,
        items: list[dict[str, Any]],
        spider: Spider,
        middleware: Any,
    ) -> None:
        """Run the full analysis pipeline for a single URL."""
        assert self.storage is not None

        # --- a) Get raw HTML and metadata ---
        raw_html = ""
        metadata: SnapshotMetadata | None = None

        if middleware and hasattr(middleware, "_captured"):
            captured = middleware._captured.get(url)
            if captured:
                raw_html, metadata = captured

        if metadata is None:
            from datetime import UTC, datetime

            metadata = SnapshotMetadata(
                http_status=200,
                latency_ms=0.0,
                timestamp=datetime.now(UTC),
                headers={},
                response_size_bytes=len(raw_html.encode("utf-8")) if raw_html else 0,
            )

        # --- b) Capture snapshot ---
        snapshot = capture_snapshot(
            url=url,
            raw_html=raw_html,
            extracted_items=items,
            metadata=metadata,
            storage=self.storage,
            store_raw_html=self.store_raw_html,
            run_id=self.run_id,
        )

        # --- c) Schema validation + drift ---
        validation_result = None
        drift_events: list[DriftEvent] = []
        if self.schema_cls is not None:
            try:
                validation_result = self.schema_cls.validate_batch(
                    items,
                    run_id=self.run_id,
                    url=url,
                )
                # Run drift analysis BEFORE saving so current result
                # doesn't pollute the historical baseline.
                try:
                    threshold = 0.15
                    if self.config and hasattr(self.config, "schema"):
                        threshold = self.config.schema.null_drift_threshold
                    drift_events = run_drift_analysis(
                        validation_result,
                        self.storage,
                        threshold=threshold,
                    )
                    if drift_events and self.crawler:
                        try:
                            self.crawler.signals.send_catch_log(
                                signal=signals.scraperguard_drift_detected,
                                drift_events=drift_events,
                                url=url,
                            )
                        except Exception:
                            pass
                except Exception:
                    logger.exception("ScraperGuard: Drift analysis failed for %s", url)
                self.storage.save_validation_result(validation_result)
                spider.logger.info(
                    "ScraperGuard: Schema validation for %s: %d/%d passed",
                    url,
                    validation_result.passed_count,
                    validation_result.total_items,
                )
            except Exception:
                logger.exception("ScraperGuard: Schema validation failed for %s", url)

        # --- e) DOM diff ---
        dom_changes = []
        try:
            snapshots = self.storage.list_snapshots(url, limit=2)
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

        # --- f) Selector tracking ---
        selector_statuses: list[SelectorStatus] = []
        if self.selectors:
            try:
                current_tree = parse_to_tree(snapshot.normalized_html)
                prev_tree = None
                snapshots = self.storage.list_snapshots(url, limit=2)
                for s in snapshots:
                    if s.id != snapshot.id:
                        prev_tree = parse_to_tree(s.normalized_html)
                        break
                selector_statuses = track_selectors(current_tree, prev_tree, self.selectors)

                broken = [ss for ss in selector_statuses if ss.status == "broken"]
                if broken and self.crawler:
                    try:
                        self.crawler.signals.send_catch_log(
                            signal=signals.scraperguard_selector_broken,
                            selector_statuses=selector_statuses,
                            url=url,
                        )
                    except Exception:
                        pass
            except Exception:
                logger.exception("ScraperGuard: Selector tracking failed for %s", url)

        # --- g) Failure classification ---
        classifications = []
        try:
            classifications = classify_failure(
                ClassificationInput(
                    validation_result=validation_result,
                    dom_changes=dom_changes,
                    selector_statuses=selector_statuses,
                    raw_html=raw_html or None,
                    http_status=metadata.http_status if metadata else None,
                    response_size_bytes=metadata.response_size_bytes if metadata else None,
                )
            )
        except Exception:
            logger.exception("ScraperGuard: Failure classification failed for %s", url)

        # --- h) Health score ---
        try:
            report = compute_health_score(
                validation_result=validation_result,
                selector_statuses=selector_statuses,
                dom_changes=dom_changes,
                classifications=classifications,
                drift_events=drift_events,
                run_id=self.run_id,
                url=url,
            )

            spider.logger.info(
                "ScraperGuard: Health for %s: %d/100 (%s)",
                url,
                report.overall_score,
                report.status,
            )

            # Log full report at debug level
            spider.logger.debug(
                "ScraperGuard: Full report for %s:\n%s",
                url,
                format_health_report(report),
            )

            # --- Alert dispatch ---
            self._dispatch_alerts(classifications, url, spider)

            if self.crawler:
                try:
                    self.crawler.signals.send_catch_log(
                        signal=signals.scraperguard_health_computed,
                        health_report=report,
                        url=url,
                    )
                except Exception:
                    pass
        except Exception:
            logger.exception("ScraperGuard: Health score computation failed for %s", url)


# Convenience alias
ValidationPipeline = ScraperGuardValidationPipeline
