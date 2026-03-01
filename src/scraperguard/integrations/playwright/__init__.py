"""Playwright integration — page hooks and snapshot capture.

Provides an async context manager that wraps Playwright page interactions,
capturing page state via page.content() after navigation and validating
extracted data against a schema.

Usage:
    from scraperguard.integrations.playwright import observe

    async with observe(page, storage=storage, run_id=run_id) as observer:
        await page.goto(url)
        data = await extract(page)
        observer.set_items(data)
"""

try:
    from scraperguard.integrations.playwright.observer import (
        PageObserver,
        capture_page,
        observe,
    )
except ImportError:
    raise ImportError(
        "Playwright integration requires playwright. "
        "Install it with: pip install scraperguard[playwright]"
    )

__all__ = ["PageObserver", "capture_page", "observe"]
