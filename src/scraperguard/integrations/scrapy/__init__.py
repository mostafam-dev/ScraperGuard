"""Scrapy integration — middleware and item pipeline.

Drop-in components for Scrapy projects:
- ObserverMiddleware: hooks into the downloader to capture raw responses
  and metadata without altering spider behavior.
- ValidationPipeline: validates items against a ScraperGuard schema
  and records results in the storage backend.

Usage in settings.py::

    DOWNLOADER_MIDDLEWARES = {
        'scraperguard.integrations.scrapy.ObserverMiddleware': 543,
    }
    ITEM_PIPELINES = {
        'scraperguard.integrations.scrapy.ValidationPipeline': 300,
    }
"""

try:
    from scraperguard.integrations.scrapy.middleware import (
        ObserverMiddleware,
        ScraperGuardObserverMiddleware,
    )
    from scraperguard.integrations.scrapy.pipeline import (
        ScraperGuardValidationPipeline,
        ValidationPipeline,
    )
except ImportError:
    raise ImportError(
        "Scrapy integration requires scrapy. Install it with: pip install scraperguard[scrapy]"
    )

from scraperguard.integrations.scrapy.signals import (
    scraperguard_drift_detected,
    scraperguard_health_computed,
    scraperguard_selector_broken,
)

__all__ = [
    "ObserverMiddleware",
    "ScraperGuardObserverMiddleware",
    "ValidationPipeline",
    "ScraperGuardValidationPipeline",
    "scraperguard_health_computed",
    "scraperguard_drift_detected",
    "scraperguard_selector_broken",
]
