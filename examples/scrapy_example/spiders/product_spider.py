"""Example Scrapy spider with ScraperGuard monitoring."""

import scrapy


class ProductSpider(scrapy.Spider):
    name = "products"
    start_urls = ["https://example.com/products"]

    def parse(self, response):
        for product in response.css(".product"):
            yield {
                "title": product.css("h1::text").get(),
                "price": float(product.css(".price::text").get(0)),
                "availability": bool(product.css(".in-stock")),
                "rating": float(product.css(".rating::attr(data-value)").get(0)),
            }
