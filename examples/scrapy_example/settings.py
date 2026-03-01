"""Scrapy settings showing ScraperGuard integration."""

BOT_NAME = "example_spider"
SPIDER_MODULES = ["spiders"]

# ScraperGuard integration
DOWNLOADER_MIDDLEWARES = {
    "scraperguard.integrations.scrapy.ObserverMiddleware": 543,
}
ITEM_PIPELINES = {
    "scraperguard.integrations.scrapy.ValidationPipeline": 300,
}

# ScraperGuard schema (dotted import path to a BaseSchema subclass)
SCRAPERGUARD_SCHEMA = "schemas.ProductSchema"
