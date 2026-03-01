# Getting Started with ScraperGuard

## Installation

```bash
pip install scraperguard
```

For development:

```bash
git clone https://github.com/mostafam-dev/scraperguard.git
cd scraperguard
pip install -e ".[dev]"
```

## First Run

### 1. Define a Schema

Create a Python file defining your expected scraper output:

```python
# product_schema.py
from scraperguard.schema import BaseSchema, validators

class ProductSchema(BaseSchema):
    title: str
    price: float = validators.range(min=0.01)
    availability: bool
    rating: float = validators.range(min=0, max=5)
```

### 2. Run ScraperGuard

Point ScraperGuard at a URL or JSON file with extracted data:

```bash
# Monitor a live URL
scraperguard run https://example.com/products --schema product_schema.py

# Analyze a JSON file with pre-extracted data
scraperguard run data.json --schema product_schema.py
```

The JSON file format:

```json
{
  "url": "https://example.com/products",
  "html": "<html>...</html>",
  "items": [
    {"title": "Widget", "price": 29.99, "availability": true, "rating": 4.5}
  ]
}
```

### 3. View Results

ScraperGuard outputs a health report:

```
Health Score: 85/100 (healthy)

Schema Compliance: 95.0%
  95/100 items passed schema validation (95.0%)

Extraction Completeness: 90.0%
  Field completeness: 90.0%. Weakest: price at 80.0%

Selector Stability: 100.0%
  No selectors tracked

Structural Stability: 100.0%
  No structural changes detected
```

### 4. Track Selectors

Monitor specific CSS selectors across runs:

```bash
scraperguard run https://example.com --schema product_schema.py --selectors ".price,.title,.rating"
```

### 5. Compare Snapshots

View structural changes between runs:

```bash
scraperguard diff --url https://example.com --last 2
```

### 6. Export Reports

```bash
scraperguard report --url https://example.com --format json
scraperguard report --url https://example.com --format csv
```

## Integration

### Scrapy

Add to your `settings.py`:

```python
DOWNLOADER_MIDDLEWARES = {
    'scraperguard.integrations.scrapy.ObserverMiddleware': 543,
}
ITEM_PIPELINES = {
    'scraperguard.integrations.scrapy.ValidationPipeline': 300,
}
SCRAPERGUARD_SCHEMA = "myproject.schemas.ProductSchema"
```

### Playwright

```python
from scraperguard.integrations.playwright import observe

async with observe(page, storage=storage, run_id=run_id) as observer:
    await page.goto(url)
    data = await extract(page)
    observer.set_items(data)
```

## Configuration

Create `scraperguard.yaml` in your project root. See `examples/scraperguard.yaml` for a fully commented example.

## Next Steps

- See `examples/basic_usage.py` for a self-contained programmatic example
- See `docs/architecture.md` for how ScraperGuard works internally
- Run `scraperguard --help` for all CLI options
