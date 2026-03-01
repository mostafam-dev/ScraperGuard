# ScraperGuard Architecture

## System Overview

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
                    │  │ Middleware │  │  Page Hooks    │  │
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
           │  └──────┬────────┘  └──────┬────────┘  └──────┬──────┘  │
           │         └────────┬─────────┴────────┬─────────┘         │
           │                  ▼                  ▼                   │
           │   ┌───────────────────┐  ┌──────────────────────────┐   │
           │   │ Drift Tracker     │  │ Failure Classifier       │   │
           │   └────────┬──────────┘  └───────────┬──────────────┘   │
           │            └───────────┬─────────────┘                  │
           └────────────────────────┼────────────────────────────────┘
                                    │
                        ┌───────────┼───────────┐
                        ▼           ▼           ▼
               ┌────────────┐  ┌───────────┐ ┌───────────────┐
               │  Storage   │  │ Alerting  │ │  Dashboard    │
               │            │  │           │ │  (FastAPI)    │
               │ • SQLite   │  │ • Slack   │ │               │
               │ • Postgres │  │ • Webhook │ │ • Health view │
               │ • JSONL    │  │ • Email   │ │ • Drift chart │
               └────────────┘  └───────────┘ └───────────────┘
```

## Pipeline Steps

### Step 1: Observation

The Observer Layer intercepts scraper output without modifying behavior. For Scrapy, this is a middleware that hooks into response processing. For Playwright, it captures page state via `page.content()` after navigation. The observer captures three things: the raw HTML response, the extracted structured data, and run metadata (URL, timestamp, latency, HTTP headers, response fingerprint).

### Step 2: Snapshot & Normalization

The snapshot capture normalizes the raw HTML into a canonical DOM tree using lxml. This strips non-structural noise (whitespace, comments, inline scripts, tracking attributes) so that comparisons are deterministic. Each snapshot is fingerprinted (content hash + structural hash) and stored with its structured data counterpart.

Key modules:
- `core/snapshot/capture.py` — Snapshot creation and persistence
- `core/snapshot/normalizer.py` — HTML normalization (strip scripts, styles, event handlers)
- `core/snapshot/fingerprint.py` — SHA-256 content and structural fingerprinting

### Step 3: Schema Validation

The extracted data is validated against user-defined Pydantic schemas. The validator computes null ratios per field across the batch, compares against historical baselines, and flags statistical deviations. A field returning null in 3% of items last week but 82% today triggers a null_drift event with severity scoring.

Key modules:
- `core/schema/base.py` — BaseSchema class with validate_item() and validate_batch()
- `core/schema/drift.py` — Null ratio drift detection
- `core/schema/validators.py` — Built-in field validators (range, pattern, etc.)

### Step 4: Structural Diffing

The current DOM snapshot is compared against the previous snapshot. The diff engine operates on the normalized tree, not raw HTML. It detects node removal, structural reordering, attribute mutations, and selector invalidation. Each change is scored by severity (high/medium/low) and mapped to affected CSS selectors.

Key modules:
- `core/dom_diff/parser.py` — DOM tree parsing and CSS selector matching
- `core/dom_diff/differ.py` — Tree diffing algorithm
- `core/dom_diff/selector_tracker.py` — Selector status tracking across snapshots

### Step 5: Failure Classification

Changes and validation failures are fed into the Failure Classifier. This is rule-based and deterministic. It maps patterns to root causes:

| Classification      | Signal                                             |
| ------------------- | -------------------------------------------------- |
| SELECTOR_BREAK      | Selector returns 0 matches, page loads normally    |
| DOM_RESTRUCTURE     | Multiple selectors break, high structural changes  |
| CAPTCHA_INJECTION   | Known CAPTCHA signatures in response body          |
| JS_CHALLENGE        | Empty body with script-only response               |
| RATE_LIMIT          | HTTP 429 or rate-limit response patterns           |
| AB_VARIANT          | Partial selector match, moderate structural changes|

Key module: `core/classify/classifier.py`

### Step 6: Health Scoring

All signals converge into a composite health score (0-100):

| Component                | Weight | Source                                 |
| ------------------------ | ------ | -------------------------------------- |
| Schema Compliance        | 30%    | % of items passing validation          |
| Extraction Completeness  | 30%    | Field completeness (1 - null_ratio)    |
| Selector Stability       | 25%    | % of selectors stable/improved         |
| Structural Stability     | 15%    | Deductions from DOM changes            |

Status levels: healthy (80+), degraded (50-79), critical (<50).

Key module: `health.py`

### Step 7: Output

Results are dispatched to:
- **CLI** — Boxed text health report
- **Storage** — SQLite/PostgreSQL for historical tracking
- **Alerts** — Slack, webhook, or email when thresholds are breached
- **API** — FastAPI dashboard for drill-down debugging

## Storage Architecture

Storage backends implement a common `StorageBackend` interface:

- **SQLite** (`storage/sqlite.py`) — Default for local development. WAL mode, foreign keys.
- **PostgreSQL** (`storage/postgres.py`) — Production-grade. (Planned)
- **JSONL** (`storage/jsonl.py`) — Lightweight export format. (Planned)

Data model:
- **RunMetadata** — Scraper run lifecycle (id, scraper name, timestamp, status)
- **Snapshot** — Normalized HTML + fingerprint + extracted items
- **ValidationResult** — Per-batch validation with field failures and null ratios

## Project Structure

```
src/scraperguard/
├── __init__.py              # Package entry, version
├── health.py                # Health score computation
├── config.py                # YAML config loading
├── schema.py                # Convenience re-exports
├── cli/                     # Click CLI commands
├── core/
│   ├── snapshot/            # DOM capture, normalization, fingerprinting
│   ├── schema/              # Pydantic validation, drift detection
│   ├── dom_diff/            # Structural diffing, selector tracking
│   ├── classify/            # Rule-based failure classification
│   └── drift/               # Time-series analysis (planned)
├── storage/                 # Backend implementations
├── alerts/                  # Slack, webhook, email dispatchers
├── api/                     # FastAPI dashboard
└── integrations/
    ├── scrapy/              # Middleware + pipeline
    └── playwright/          # Page observer
```
