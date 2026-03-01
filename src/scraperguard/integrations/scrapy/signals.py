"""Custom Scrapy signals for ScraperGuard events.

These signals allow advanced users to hook custom behavior (e.g., send alerts,
log metrics) from within their Scrapy project when ScraperGuard detects issues.

Usage in a Scrapy extension or spider::

    from scraperguard.integrations.scrapy.signals import scraperguard_health_computed

    def handle_health(health_report, **kwargs):
        if health_report.status == "critical":
            send_alert(health_report)

    crawler.signals.connect(handle_health, signal=scraperguard_health_computed)
"""

from __future__ import annotations

# Fired after the health score is computed for a URL.
# kwargs: health_report (HealthReport), url (str)
scraperguard_health_computed = object()

# Fired when null ratio drift is detected on any field.
# kwargs: drift_events (list[DriftEvent]), url (str)
scraperguard_drift_detected = object()

# Fired when a tracked CSS selector returns zero matches.
# kwargs: selector_statuses (list[SelectorStatus]), url (str)
scraperguard_selector_broken = object()
