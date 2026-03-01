"""ScraperGuard — observability and reliability layer for web scraping pipelines.

Detects when scrapers silently break and explains why. Provides schema validation,
structural DOM diffing, failure classification, and drift tracking.
"""

__version__ = "0.1.0"

from scraperguard.health import HealthReport, compute_health_score, format_health_report

__all__ = [
    "HealthReport",
    "compute_health_score",
    "format_health_report",
]
