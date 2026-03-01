"""Observer layer — framework-specific hooks that intercept scraper output.

Integrations capture raw HTML, extracted data, and run metadata without
modifying scraper behavior. Each integration adapts to its framework's
lifecycle (Scrapy middleware, Playwright page hooks, etc.).
"""
