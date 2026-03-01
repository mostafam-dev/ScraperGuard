"""Scrapy downloader middleware — intercepts responses for snapshot capture.

Hooks into the Scrapy request/response lifecycle to capture raw HTML
and response metadata. Forwards everything to the snapshot engine
without modifying the response or altering spider behavior.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from scraperguard.config import ScraperGuardConfig, get_storage_backend, load_config
from scraperguard.storage.models import SnapshotMetadata

if TYPE_CHECKING:
    from scrapy import Spider
    from scrapy.crawler import Crawler
    from scrapy.http import Request, Response

    from scraperguard.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class ScraperGuardObserverMiddleware:
    """Scrapy middleware that observes responses for ScraperGuard analysis.

    Captures the raw HTML body and response metadata (URL, status, headers,
    timestamp) on every response, storing them in ``request.meta`` for the
    :class:`~scraperguard.integrations.scrapy.pipeline.ScraperGuardValidationPipeline`
    to consume later.

    Does not modify requests or responses — purely observational.
    """

    def __init__(
        self,
        config: ScraperGuardConfig,
        storage: StorageBackend,
        run_id: str,
        store_raw_html: bool = False,
        selectors: list[str] | None = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.run_id = run_id
        self.store_raw_html = store_raw_html
        self.selectors = selectors or []
        # Shared state: maps url -> (raw_html, SnapshotMetadata)
        # The pipeline reads from this dict in close_spider.
        self._captured: dict[str, tuple[str, SnapshotMetadata]] = {}

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> ScraperGuardObserverMiddleware:
        """Instantiate from a Scrapy crawler, reading ScraperGuard settings.

        Reads the following from ``crawler.settings``:

        - ``SCRAPERGUARD_CONFIG_PATH`` (str, optional): Path to scraperguard.yaml.
        - ``SCRAPERGUARD_SELECTORS`` (list[str], optional): CSS selectors to track.
        - ``SCRAPERGUARD_STORE_RAW_HTML`` (bool, default False): Whether to persist raw HTML.
        """
        try:
            config_path = crawler.settings.get("SCRAPERGUARD_CONFIG_PATH", None)
            config = load_config(config_path)

            selectors = crawler.settings.getlist("SCRAPERGUARD_SELECTORS", [])
            store_raw_html = crawler.settings.getbool("SCRAPERGUARD_STORE_RAW_HTML", False)

            storage = get_storage_backend(config)
            run_meta = storage.create_run(scraper_name="scrapy")
            run_id = run_meta.id

            instance = cls(
                config=config,
                storage=storage,
                run_id=run_id,
                store_raw_html=store_raw_html,
                selectors=selectors,
            )

            # Connect spider_closed signal
            from scrapy import signals as scrapy_signals

            crawler.signals.connect(instance.spider_closed, signal=scrapy_signals.spider_closed)

            return instance
        except Exception:
            logger.exception("ScraperGuard: Failed to initialize middleware, creating no-op instance")
            # Return a minimal instance that will pass-through everything
            instance = cls.__new__(cls)
            instance.config = ScraperGuardConfig()
            instance.storage = None  # type: ignore[assignment]
            instance.run_id = ""
            instance.store_raw_html = False
            instance.selectors = []
            instance._captured = {}
            return instance

    def process_response(self, request: Request, response: Response, spider: Spider) -> Response:
        """Capture response HTML and metadata, then pass through unchanged.

        Stores the raw HTML and a :class:`SnapshotMetadata` in
        ``request.meta['scraperguard_html']`` and
        ``request.meta['scraperguard_metadata']`` so the validation
        pipeline can retrieve them later.
        """
        try:
            raw_html = response.text

            latency_ms = 0.0
            if "scraperguard_start_time" in request.meta:
                latency_ms = (time.monotonic() - request.meta["scraperguard_start_time"]) * 1000
            elif "download_latency" in request.meta:
                latency_ms = request.meta["download_latency"] * 1000

            headers_dict: dict[str, str] = {}
            if hasattr(response, "headers"):
                for key, values in response.headers.items():
                    if isinstance(key, bytes):
                        key = key.decode("utf-8", errors="replace")
                    if isinstance(values, list) and values:
                        val = values[0]
                    else:
                        val = values
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="replace")
                    headers_dict[key] = str(val)

            metadata = SnapshotMetadata(
                http_status=response.status,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
                headers=headers_dict,
                response_size_bytes=len(response.body),
            )

            request.meta["scraperguard_html"] = raw_html
            request.meta["scraperguard_metadata"] = metadata

            # Also store in middleware shared state for the pipeline
            self._captured[response.url] = (raw_html, metadata)

        except Exception:
            logger.exception("ScraperGuard: Error capturing response for %s", response.url)

        return response

    def spider_closed(self, spider: Spider, reason: str = "finished") -> None:
        """Update run status when the spider closes."""
        try:
            if self.storage is None:
                return
            status = "completed" if reason == "finished" else "failed"
            self.storage.update_run_status(self.run_id, status)
        except Exception:
            logger.exception("ScraperGuard: Error updating run status on spider close")


# Convenience alias
ObserverMiddleware = ScraperGuardObserverMiddleware
