# ScraperGuard

**Production-grade observability and reliability layer for web scraping pipelines.**

ScraperGuard detects when scrapers silently break — and explains why.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-scraperguard-orange.svg)](https://pypi.org/project/scraperguard/)


---

## The Problem

Web scrapers don't crash. They **silently drift**.

An HTTP `200 OK` doesn't mean your data is correct. In production, scraper failures look like this:

- A CSS selector still matches — but the value is wrong
- A field exists — but is now `null` in 80% of responses
- A layout variant appears — and extraction accuracy drops to 60%
- Your pipeline keeps running — shipping corrupted data downstream for days

Most scraping tools focus on **extraction**. Nothing focuses on **correctness**.

**ScraperGuard fills that gap.**

---

## What It Does

| Capability               | What Others Do                   | What ScraperGuard Does                                                                   |
| ------------------------ | -------------------------------- | ---------------------------------------------------------------------------------------- |
| **Change Detection**     | Compare raw HTML / rendered text | Structural DOM diffing — detects element removal, attribute shifts, reordering           |
| **Validation**           | `HTTP 200` = success             | Schema-level enforcement — missing fields, null drift, type mismatches, range violations |
| **Failure Diagnosis**    | "Scraper failed"                 | Root-cause attribution — selector break, CAPTCHA, JS challenge, A/B variant              |
| **Reliability Tracking** | Job succeeded / failed           | Health scores, field completeness, selector stability, structural stability              |

---

## Quick Demo (2 Minutes)

**Scenario:** You monitor product prices on an e-commerce site. The site silently redesigns their price element. 80% of prices go null, a key selector breaks, and the DOM shifts structurally.

**1. Define your schema:**

```python
from scraperguard.schema import BaseSchema, validators

class ProductSchema(BaseSchema):
    title: str
    price: float = validators.range(min=0.01)
    availability: bool
    rating: float = validators.range(min=0, max=5)
```

**2. Run your scraper through ScraperGuard:**

```bash
scraperguard run https://shop.example.com/products --schema product_schema.py --selectors ".price-tag,.product-title"
```

**3. ScraperGuard catches what your scraper missed:**

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║  Health Score: 38/100 (critical)                                                     ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                      ║
║  Schema Compliance: 20.0%                                                            ║
║    6/30 items passed schema validation (20.0%)                                       ║
║                                                                                      ║
║  Extraction Completeness: 56.0%                                                      ║
║    Field completeness: 56.0%. Weakest: price at 20.0%                                ║
║                                                                                      ║
║  Selector Stability: 50.0%                                                           ║
║    1/2 selectors stable. Broken: .price-tag                                          ║
║                                                                                      ║
║  Structural Stability: 15.0%                                                         ║
║    4 structural changes detected (3 high, 1 medium, 0 low severity)                  ║
║                                                                                      ║
║  Failures:                                                                           ║
║    [critical] selector_break: Update broken selectors: ['.price-tag']                ║
║                                                                                      ║
║  Drift Alerts:                                                                       ║
║    [critical] price: Field 'price' null ratio increased from 3.3% to 80.0% (+76.7%)  ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

**Without ScraperGuard:** Your pipeline ships bad data for days.
**With ScraperGuard:** You know within minutes, with an exact diagnosis.

---

## System Architecture

```
                        ┌─────────────────────────────────────┐
                        │          Your Scraper               │
                        │   (Scrapy / Playwright / Custom)    │
                        └──────────────┬──────────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────────────┐
                        │      Observer Layer                  │
                        │  ┌────────────┐  ┌────────────────┐  │
                        │  │  Scrapy    │  │  Playwright    │  │
                        │  │ Middleware │  │  Page Observer │  │
                        │  └─────┬──────┘  └──────┬─────────┘  │
                        │        └────────┬───────┘            │
                        └─────────────────┼────────────────────┘
                                          │
                                          ▼
               ┌─────────────────────────────────────────────────────────┐
               │                  Core Engine                            │
               │                                                         │
               │  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
               │  │  Snapshot     │  │  Schema       │  │  DOM Diff   │  │
               │  │  Capture      │  │  Validator    │  │  Engine     │  │
               │  │               │  │               │  │             │  │
               │  │ • Normalize   │  │ • Pydantic    │  │ • Tree diff │  │
               │  │ • Fingerprint │  │ • Null drift  │  │ • Selector  │  │
               │  │ • Metadata    │  │ • Range/type  │  │   tracking  │  │
               │  └──────┬────────┘  └──────┬────────┘  └──────┬──────┘  │
               │         │                  │                  │         │
               │         └────────┬─────────┴────────┬─────────┘         │
               │                  ▼                  ▼                   │
               │   ┌───────────────────┐  ┌──────────────────────────┐   │
               │   │ Drift Detection   │  │ Failure Classifier       │   │
               │   │                   │  │                          │   │
               │   │ • Null ratio      │  │ • Selector break         │   │
               │   │   baselines       │  │ • CAPTCHA / JS challenge │   │
               │   │ • Historical      │  │ • Rate limit             │   │
               │   │   comparison      │  │ • A/B layout variant     │   │
               │   └────────┬──────────┘  └───────────┬──────────────┘   │
               │            └───────────┬─────────────┘                  │
               └────────────────────────┼────────────────────────────────┘
                                        │
                            ┌───────────┼───────────┐
                            ▼           ▼           ▼
                   ┌────────────┐  ┌───────────┐ ┌───────────────┐
                   │  Storage   │  │ Alerting  │ │  API          │
                   │            │  │           │ │  (FastAPI)    │
                   │ • SQLite   │  │ • Slack   │ │               │
                   │            │  │ • Webhook │ │ • Health view │
                   │            │  │           │ │ • Reports     │
                   └────────────┘  └───────────┘ └───────────────┘
```

---

## How It Works Internally

This section explains the pipeline for engineers reviewing the codebase.

### Step 1: Observation

The Observer Layer intercepts scraper output without modifying behavior. For Scrapy, this is a downloader middleware that captures raw responses and metadata. For Playwright, it captures page state via `page.content()` after navigation. The observer captures three things: the raw HTML response, the extracted structured data, and run metadata (URL, timestamp, latency, HTTP headers, response size).

### Step 2: Snapshot & Normalization

Raw HTML is normalized into a canonical DOM tree using `lxml`. This strips non-structural noise — scripts, styles, event handlers, tracking attributes, inline styles, comments — so that comparisons are deterministic. Each snapshot is fingerprinted twice: a content hash (SHA-256 of normalized HTML) and a structural hash (SHA-256 of tag-nesting skeleton only). Snapshots are stored with their structured data counterpart via pluggable storage backends.

### Step 3: Schema Validation

Extracted data is validated against user-defined Pydantic schemas. The validator computes null ratios per field across the batch, compares against historical baselines, and flags statistical deviations. A field returning `null` in 3% of items last week but 80% today triggers a `null_drift` event with severity scoring. Field validators like `validators.range(min=0.01)` enforce value constraints beyond type checking.

### Step 4: Structural Diffing

The current DOM snapshot is compared against the previous snapshot. The diff engine operates on the normalized tree, not raw HTML. It detects node removal, insertion, structural reordering, attribute mutations, tag changes, and text changes. Each change is scored by severity (`high`, `medium`, `low`) and tracked alongside CSS selector status.

### Step 5: Failure Classification

Changes and validation failures are fed into the Failure Classifier. This is rule-based and deterministic — no ML. It maps patterns to root causes: if a selector returns zero matches but the page loaded successfully, that's a `SELECTOR_BREAK`. If the response body contains known CAPTCHA signatures, that's `CAPTCHA_INJECTION`. If the response is near-empty, that's `EMPTY_RESPONSE`. Each classification includes a confidence score and recommended action.

### Step 6: Drift Detection

Current validation results are compared against historical baselines stored in the database. The drift detector computes average null ratios over the last N runs, then flags significant deviations. Severity levels: `critical` (delta > 0.5), `warning` (delta > 0.3), `info` (delta > 0.15).

### Step 7: Output

Everything converges into three outputs: a health score (0–100) per scraper run, structured alerts dispatched via Slack/webhook when thresholds are breached, and CLI/API reports for debugging.

---

## Core Features

### Schema Validation Engine

```python
from scraperguard.schema import BaseSchema, validators

class ProductSchema(BaseSchema):
    title: str
    price: float = validators.range(min=0.01)
    availability: bool
    rating: float = validators.range(min=0, max=5)
```

Detects missing fields, type mismatches, null ratio drift, and value range violations. Built on Pydantic v2 with custom field validators.

### Structural DOM Diffing

Compares normalized DOM trees, not raw HTML. Detects removed/added nodes, attribute changes, tag changes, structural reordering, and text mutations.

```json
{
  "change_type": "node_removed",
  "path": "body > div.product > span.price-tag",
  "severity": "high",
  "message": "Node removed: span.price-tag at body > div.product > span.price-tag",
  "affected_selectors": [".price-tag"]
}
```

### Root-Cause Failure Attribution

Automatically classifies every failure:

| Classification        | Signal                                             |
| --------------------- | -------------------------------------------------- |
| `SELECTOR_BREAK`      | Selector returns 0 matches, page loads normally    |
| `DOM_RESTRUCTURE`     | 5+ high-severity changes or 3+ node removals       |
| `CAPTCHA_INJECTION`   | Known CAPTCHA signatures in response body          |
| `JS_CHALLENGE`        | Minimal visible text with script-heavy response    |
| `RATE_LIMIT`          | HTTP 429/403 or rate-limit message in body         |
| `AB_VARIANT`          | Partial selector failure with moderate DOM changes |
| `PARTIAL_EXTRACTION`  | Some items valid, others fail validation           |
| `EMPTY_RESPONSE`      | Response body is empty or near-empty (< 100 bytes) |

### Health Score

Every run produces a composite health score (0–100) from four weighted components:

- **Schema Compliance** (30%) — % of items passing full schema validation
- **Extraction Completeness** (30%) — per-field completeness (1 - null_ratio), penalizing the weakest field
- **Selector Stability** (25%) — % of tracked selectors that are stable or improved
- **Structural Stability** (15%) — deductions from high/medium/low severity DOM changes

Status levels: **healthy** (80+), **degraded** (50–79), **critical** (< 50).

### Null Drift Detection

Compares current null ratios against historical baselines (last 5 runs by default). Flags fields where null rates have spiked significantly, with severity levels based on the magnitude of change.

---

## Integration

ScraperGuard is **drop-in, not invasive**.

### Scrapy

```python
# settings.py
DOWNLOADER_MIDDLEWARES = {
    "scraperguard.integrations.scrapy.ObserverMiddleware": 543,
}
ITEM_PIPELINES = {
    "scraperguard.integrations.scrapy.ValidationPipeline": 300,
}
SCRAPERGUARD_SCHEMA = "myproject.schemas.ProductSchema"
```

### Playwright

```python
from scraperguard.integrations.playwright import observe

async with observe(page, storage=storage, run_id=run_id, schema=ProductSchema) as observer:
    await page.goto(url)
    data = await extract(page)
    observer.set_items(data)
# On exit, ScraperGuard captures the page and runs the full pipeline
```

One-shot convenience function:

```python
from scraperguard.integrations.playwright import capture_page

report = await capture_page(page, storage=storage, run_id=run_id, items=data, schema=ProductSchema)
print(report.overall_score)  # e.g. 85
```

### CLI

```bash
# Run analysis on a URL
scraperguard run https://example.com/products --schema product_schema.py

# Run analysis on a JSON file with pre-extracted data
scraperguard run data.json --schema product_schema.py --selectors ".price,.title"

# Validate latest snapshot against a schema
scraperguard validate --url https://example.com --schema product_schema.py

# Compare last 2 DOM snapshots
scraperguard diff --url https://example.com --last 2

# Export health report as JSON
scraperguard report --url https://example.com --format json

# Start the FastAPI dashboard
scraperguard serve --host 0.0.0.0 --port 8000
```

---

## Configuration

```yaml
# scraperguard.yaml
schema:
  strict: true
  null_drift_threshold: 0.15

storage:
  backend: sqlite  # sqlite is the currently supported backend
  connection: scraperguard.db

alerts:
  slack:
    enabled: true
    webhook: ${SLACK_WEBHOOK_URL}
  email_enabled: false
  webhook_url: ""
  thresholds:
    health_score: 60
    schema_failure: critical
    selector_break: warning

snapshots:
  store_raw_html: false
  retention_days: 30
```

12-factor compatible. All string values support `${ENV_VAR}` interpolation.

---

## Project Structure

```
src/scraperguard/
├── core/
│   ├── snapshot/          # DOM capture, normalization, fingerprinting
│   ├── schema/            # Pydantic validation engine + drift detection
│   ├── dom_diff/          # Structural tree diffing, selector tracking
│   ├── drift/             # Time-series drift tracking interface
│   └── classify/          # Rule-based failure attribution
├── integrations/
│   ├── scrapy/            # Middleware + item pipeline
│   └── playwright/        # Page observer + capture
├── alerts/                # Slack, email, webhook dispatchers
├── storage/               # SQLite backend + abstract interface
├── api/                   # FastAPI app factory + routes
├── cli/                   # Click-based CLI (run, validate, diff, report, serve)
├── schema.py              # Convenience re-exports
├── health.py              # Health score computation
└── config.py              # YAML config loading

tests/                     # Unit + integration test suite
docs/                      # Architecture docs + usage guides
examples/                  # Working example scrapers + configs
```

---

## Installation

From source:

```bash
git clone https://github.com/mostafam-dev/scraperguard.git
cd scraperguard
pip install -e .
```

With optional extras:

```bash
pip install -e ".[dev]"         # pytest, ruff, mypy
pip install -e ".[api]"         # FastAPI + uvicorn
pip install -e ".[scrapy]"      # Scrapy integration
pip install -e ".[playwright]"  # Playwright integration
```

Docker:

```bash
docker build -t scraperguard .
docker run -p 8000:8000 scraperguard
```

---

## Use Cases

**E-commerce price monitoring** — Detect when price selectors break before shipping wrong prices to pricing engines.

**AI/ML data pipelines** — Enforce schema guarantees on training data collected via scraping. Catch data quality regressions before they affect model performance.

**Competitive intelligence** — Monitor structural changes across competitor sites. Get alerted when layouts change and extraction degrades.

**Large-scale scraping infrastructure** — Add observability across hundreds of spiders. Track which scrapers are degrading, which sites are volatile, and where to invest maintenance effort.

---

## Tech Stack

| Layer             | Technology           |
| ----------------- | -------------------- |
| Language          | Python 3.11+         |
| DOM Parsing       | lxml                 |
| Schema Validation | Pydantic v2          |
| Storage           | SQLite               |
| API               | FastAPI              |
| CLI               | Click                |
| CI                | GitHub Actions       |
| Packaging         | Docker               |

---

## Roadmap

### v1.0 — Core Engine _(current)_

- Schema validation engine with null drift detection
- Structural DOM diffing with selector tracking
- Rule-based failure classification (8 failure types)
- CLI interface (run, validate, diff, report, serve)
- Scrapy middleware + item pipeline integration
- Playwright observer integration
- SQLite storage backend
- Health scoring (4-component weighted)
- Slack + webhook alerting
- FastAPI REST API
- YAML configuration with env var interpolation
- GitHub Actions CI
- Docker support

### v1.1 — Storage & Schema

- PostgreSQL storage backend
- JSONL export backend
- JSON Schema support (currently Pydantic only)
- Selector replacement suggestions
- Historical drift tracking (field stability, selector lifespan)

### v1.2 — Dashboard & Visibility

- Dashboard web UI with drift charts
- Per-scraper detail view with field-level breakdowns
- Domain volatility scoring
- Mean time to failure metrics
- Anomaly detection (statistical)
- Prometheus metrics export for Grafana integration

### v2.0 — Intelligence Layer

- Selector auto-repair suggestions
- Distributed run support for multi-node scraping
- Proxy anomaly detection
- LLM-assisted diff explanation (optional, not core)

### Future — Platform

- Read-only SaaS demo deployment
- Multi-tenant support
- Playwright trace viewer integration
- Plugin system for custom validators and classifiers

---

## Design Decisions

**Why rule-based classification, not ML?** Determinism matters more than cleverness. Rule-based classifiers are debuggable, testable, and predictable. ML can be layered on later for edge cases without replacing the core.

**Why not build a scraper?** The ecosystem has plenty of scraping tools. What's missing is the reliability layer between scraping and data consumption. ScraperGuard is infrastructure, not extraction.

**Why schema-first?** Because `HTTP 200` is not a success metric. Data teams care about field completeness and type correctness, not status codes. Schema validation is the real contract.

**Why store DOM snapshots?** Without a baseline, you can't diff. Without diffs, you can't attribute failures. Snapshots are the foundation that makes everything else possible.

---

## Learn More

For in-depth tutorials, architecture deep dives, and a structured learning track on scraper reliability, see the [ScraperGuard resource series on Scrapem](https://scrapem.com/projects/scraperguard).

---

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/mostafam-dev/scraperguard.git
cd scraperguard
pip install -e ".[dev]"
pytest
```

---

## License

MIT
