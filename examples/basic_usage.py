#!/usr/bin/env python3
"""Basic ScraperGuard usage example.

Run with: python examples/basic_usage.py
"""

from datetime import datetime, timezone

from scraperguard.core.classify.classifier import ClassificationInput, classify_failure
from scraperguard.core.dom_diff.differ import diff_trees
from scraperguard.core.dom_diff.parser import parse_to_tree
from scraperguard.core.dom_diff.selector_tracker import track_selectors
from scraperguard.core.schema.base import BaseSchema
from scraperguard.core.schema.validators import validators
from scraperguard.core.snapshot.capture import capture_snapshot
from scraperguard.health import compute_health_score, format_health_report
from scraperguard.storage.models import SnapshotMetadata
from scraperguard.storage.sqlite import SQLiteBackend


# 1. Define your schema
class ProductSchema(BaseSchema):
    title: str
    price: float = validators.range(min=0.01)
    availability: bool
    rating: float = validators.range(min=0, max=5)


def main() -> None:
    # 2. Create storage (in-memory for this demo)
    storage = SQLiteBackend(":memory:")
    run = storage.create_run("demo_spider")

    # 3. Mock HTML from the target page
    html = """
    <html><body>
      <div class="product">
        <h1 class="title">Widget Pro</h1>
        <span class="price">29.99</span>
        <span class="stock">In Stock</span>
      </div>
      <div class="product">
        <h1 class="title">Gadget X</h1>
        <span class="price"></span>
        <span class="stock">Out of Stock</span>
      </div>
    </body></html>
    """

    # 4. Mock extracted items (some valid, some with issues)
    items = [
        {"title": "Widget Pro", "price": 29.99, "availability": True, "rating": 4.5},
        {"title": "Gadget X", "price": None, "availability": False, "rating": 3.2},
        {"title": "Thingamajig", "price": 15.00, "availability": True, "rating": 4.0},
        {"title": "Doohickey", "price": None, "availability": True, "rating": None},
    ]

    # 5. Capture snapshot
    metadata = SnapshotMetadata(
        http_status=200,
        latency_ms=123.4,
        timestamp=datetime.now(timezone.utc),
        headers={"content-type": "text/html"},
        response_size_bytes=len(html.encode()),
    )
    snapshot = capture_snapshot(
        url="https://example.com/products",
        raw_html=html,
        extracted_items=items,
        metadata=metadata,
        storage=storage,
        run_id=run.id,
    )
    print(f"Captured snapshot: {snapshot.id[:8]}...")
    print(f"Fingerprint: {snapshot.fingerprint[:16]}...")

    # 6. Validate items against schema
    result = ProductSchema.validate_batch(items, run_id=run.id, url="https://example.com/products")
    storage.save_validation_result(result)
    print(f"\nValidation: {result.passed_count}/{result.total_items} passed")
    for ff in result.field_failures:
        print(f"  {ff.field_name} ({ff.failure_type}): {ff.count}")
    print(f"Null ratios: { {k: f'{v:.0%}' for k, v in result.null_ratios.items()} }")

    # 7. Track selectors
    tree = parse_to_tree(snapshot.normalized_html)
    selectors = [".product", ".price", ".title", ".stock"]
    selector_statuses = track_selectors(tree, None, selectors)
    print("\nSelector tracking:")
    for ss in selector_statuses:
        print(f"  [{ss.status}] {ss.message}")

    # 8. Classify failures
    classifications = classify_failure(ClassificationInput(
        validation_result=result,
        dom_changes=[],
        selector_statuses=selector_statuses,
        raw_html=html,
        http_status=200,
        response_size_bytes=len(html.encode()),
    ))

    # 9. Compute health score
    report = compute_health_score(
        validation_result=result,
        selector_statuses=selector_statuses,
        dom_changes=[],
        classifications=classifications,
        drift_events=[],
        run_id=run.id,
        url="https://example.com/products",
    )

    # 10. Print report
    print()
    print(format_health_report(report))

    storage.update_run_status(run.id, "completed")


if __name__ == "__main__":
    main()
