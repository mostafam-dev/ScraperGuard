"""CLI entry point — Click command group for ScraperGuard.

Commands:
    scraperguard run <target>        Run scraper with monitoring
    scraperguard validate            Validate extracted data against a schema
    scraperguard diff                Compare recent DOM snapshots
    scraperguard report              Export a health report
    scraperguard serve               Start the dashboard API server
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import click

from scraperguard.cli.utils import SchemaLoadError, load_schema_from_file
from scraperguard.config import get_storage_backend, load_config
from scraperguard.core.classify.classifier import (
    ClassificationInput,
    classify_failure,
)
from scraperguard.core.dom_diff.differ import diff_trees
from scraperguard.core.dom_diff.parser import parse_to_tree
from scraperguard.core.dom_diff.selector_tracker import track_selectors
from scraperguard.core.schema.drift import run_drift_analysis
from scraperguard.core.snapshot.capture import capture_snapshot, should_diff
from scraperguard.health import compute_health_score, format_health_report
from scraperguard.storage.models import SnapshotMetadata


def _fetch_url(url: str) -> tuple[str, int, dict, float]:
    """Fetch a URL and return (html, status, headers, latency_ms)."""
    start = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "ScraperGuard/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
        status = resp.status
        headers = dict(resp.headers)
    latency_ms = (time.monotonic() - start) * 1000
    return html, status, headers, latency_ms


@click.group()
@click.version_option(package_name="scraperguard")
def cli() -> None:
    """ScraperGuard — Production-grade reliability layer for web scrapers."""


@cli.command()
@click.argument("target")
@click.option("--schema", default=None, help="Path to a Python file with a BaseSchema subclass.")
@click.option(
    "--config", "config_path", default=None,
    help="Path to scraperguard.yaml config file.",
)
@click.option("--run-id", default=None, help="Run ID to group with (creates new if not provided).")
@click.option("--selectors", default=None, help="Comma-separated CSS selectors to track.")
@click.option("--store-raw-html", is_flag=True, default=False, help="Store raw HTML in snapshot.")
def run(
    target: str,
    schema: str | None,
    config_path: str | None,
    run_id: str | None,
    selectors: str | None,
    store_raw_html: bool,
) -> None:
    """Run scraper analysis on a TARGET (URL or JSON file path)."""
    # a) Load config
    cfg = load_config(config_path)

    # b) Initialize storage
    storage = get_storage_backend(cfg)

    # c) Create or use run
    if run_id:
        run_meta = storage.get_run(run_id)
        if run_meta is None:
            click.echo(f"Error: Run ID '{run_id}' not found.", err=True)
            raise SystemExit(1)
    else:
        run_meta = storage.create_run(scraper_name="cli")

    try:
        # d) Get HTML and items
        url: str
        html: str
        items: list[dict]
        http_status: int = 200
        headers: dict = {}
        latency_ms: float = 0.0

        if target.startswith("http://") or target.startswith("https://"):
            url = target
            items = []
            try:
                html, http_status, headers, latency_ms = _fetch_url(url)
            except Exception as exc:
                click.echo(f"Error fetching URL: {exc}", err=True)
                storage.update_run_status(run_meta.id, "failed")
                raise SystemExit(1)
        else:
            # JSON file path
            target_path = Path(target)
            if not target_path.is_file():
                click.echo(f"Error: File not found: {target}", err=True)
                storage.update_run_status(run_meta.id, "failed")
                raise SystemExit(1)
            try:
                data = json.loads(target_path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                click.echo(f"Error reading JSON file: {exc}", err=True)
                storage.update_run_status(run_meta.id, "failed")
                raise SystemExit(1)
            url = data.get("url", "")
            html = data.get("html", "")
            items = data.get("items", [])

        # e) Capture snapshot
        metadata = SnapshotMetadata(
            http_status=http_status,
            latency_ms=latency_ms,
            timestamp=datetime.now(UTC),
            headers=headers,
            response_size_bytes=len(html.encode("utf-8")),
        )
        snapshot = capture_snapshot(
            url=url,
            raw_html=html,
            extracted_items=items,
            metadata=metadata,
            storage=storage,
            store_raw_html=store_raw_html or cfg.snapshots.store_raw_html,
            run_id=run_meta.id,
        )

        validation_result = None
        drift_events = []
        selector_statuses = []
        dom_changes = []

        # f) Schema validation + drift
        if schema:
            try:
                schema_cls = load_schema_from_file(schema)
                validation_result = schema_cls.validate_batch(
                    items, run_id=run_meta.id, url=url,
                )
                try:
                    drift_events = run_drift_analysis(
                        validation_result, storage,
                        threshold=cfg.schema.null_drift_threshold,
                    )
                except Exception as exc:
                    click.echo(f"Warning: Drift analysis failed: {exc}", err=True)
                storage.save_validation_result(validation_result)
                click.echo(
                    f"Schema validation: "
                    f"{validation_result.passed_count}/{validation_result.total_items} passed"
                )
            except SchemaLoadError as exc:
                click.echo(f"Warning: Schema load failed: {exc}", err=True)
            except Exception as exc:
                click.echo(f"Warning: Schema validation failed: {exc}", err=True)

        # g) Selector tracking
        selector_list = [s.strip() for s in selectors.split(",") if s.strip()] if selectors else []
        if selector_list:
            try:
                current_tree = parse_to_tree(snapshot.normalized_html)
                # get_latest_snapshot might return the one we just saved; get the one before
                snapshots = storage.list_snapshots(url, limit=2)
                prev_tree = None
                for s in snapshots:
                    if s.id != snapshot.id:
                        prev_tree = parse_to_tree(s.normalized_html)
                        break
                selector_statuses = track_selectors(current_tree, prev_tree, selector_list)
                click.echo("Selector tracking:")
                for ss in selector_statuses:
                    click.echo(f"  [{ss.status}] {ss.message}")
            except Exception as exc:
                click.echo(f"Warning: Selector tracking failed: {exc}", err=True)

        # h) DOM diff
        if not selector_list:
            # Still try DOM diff if previous snapshot exists with different fingerprint
            try:
                snapshots = storage.list_snapshots(url, limit=2)
                prev_snapshot_obj = None
                for s in snapshots:
                    if s.id != snapshot.id:
                        prev_snapshot_obj = s
                        break
                if prev_snapshot_obj and should_diff(
                    snapshot.fingerprint, prev_snapshot_obj.fingerprint,
                ):
                    before_tree = parse_to_tree(prev_snapshot_obj.normalized_html)
                    after_tree = parse_to_tree(snapshot.normalized_html)
                    dom_changes = diff_trees(before_tree, after_tree)
            except Exception as exc:
                click.echo(f"Warning: DOM diff failed: {exc}", err=True)
        else:
            # Already have trees from selector tracking
            try:
                snapshots = storage.list_snapshots(url, limit=2)
                prev_snapshot_obj = None
                for s in snapshots:
                    if s.id != snapshot.id:
                        prev_snapshot_obj = s
                        break
                if prev_snapshot_obj and should_diff(
                    snapshot.fingerprint, prev_snapshot_obj.fingerprint,
                ):
                    before_tree = parse_to_tree(prev_snapshot_obj.normalized_html)
                    after_tree = parse_to_tree(snapshot.normalized_html)
                    dom_changes = diff_trees(before_tree, after_tree)
            except Exception as exc:
                click.echo(f"Warning: DOM diff failed: {exc}", err=True)

        # i) Failure classification
        classifications = classify_failure(ClassificationInput(
            validation_result=validation_result,
            dom_changes=dom_changes,
            selector_statuses=selector_statuses,
            raw_html=html,
            http_status=http_status,
            response_size_bytes=len(html.encode("utf-8")),
        ))

        # j) Health score
        report = compute_health_score(
            validation_result=validation_result,
            selector_statuses=selector_statuses,
            dom_changes=dom_changes,
            classifications=classifications,
            drift_events=drift_events,
            run_id=run_meta.id,
            url=url,
        )

        # k) Alerting
        dispatchers = []
        if cfg.alerts.slack.enabled and cfg.alerts.slack.webhook:
            from scraperguard.alerts.slack import SlackDispatcher
            dispatchers.append(SlackDispatcher(cfg.alerts.slack.webhook))
        if cfg.alerts.webhook_url:
            from scraperguard.alerts.webhook import WebhookDispatcher
            dispatchers.append(WebhookDispatcher(cfg.alerts.webhook_url))
        if dispatchers:
            from scraperguard.alerts.dispatcher import AlertManager
            from scraperguard.alerts.models import Alert
            alert_mgr = AlertManager(dispatchers, cfg.alerts.thresholds)
            for c in classifications:
                if c.severity in ("critical", "warning"):
                    alert = Alert(
                        severity=c.severity,
                        title=f"{c.failure_type.value} detected",
                        message=c.recommended_action,
                        scraper_name="cli",
                        url=url,
                        run_id=run_meta.id,
                    )
                    results = alert_mgr.dispatch(alert)
                    for name, ok in results.items():
                        click.echo(f"Alert sent to {name}: {'OK' if ok else 'FAILED'}")

        # l) Print report
        click.echo("")
        click.echo(format_health_report(report))

        # m) Update run status
        storage.update_run_status(run_meta.id, "completed")

    except SystemExit:
        raise
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        storage.update_run_status(run_meta.id, "failed")
        raise SystemExit(1)


@cli.command()
@click.option("--url", required=True, help="URL to validate (retrieves latest snapshot).")
@click.option("--schema", "schema_path", required=True, help="Path to schema Python file.")
@click.option("--run-id", default=None, help="Validate a specific run instead of latest.")
@click.option("--threshold", default=None, type=float, help="Null drift threshold override.")
def validate(url: str, schema_path: str, run_id: str | None, threshold: float | None) -> None:
    """Validate extracted data against a schema."""
    # a) Load config, init storage
    cfg = load_config()
    storage = get_storage_backend(cfg)

    # b) Get snapshot
    if run_id:
        snapshots = storage.list_snapshots(url, limit=100)
        snapshot = next((s for s in snapshots if s.run_id == run_id), None)
    else:
        snapshot = storage.get_latest_snapshot(url)

    if snapshot is None:
        click.echo(f"Error: No snapshot found for URL '{url}'.", err=True)
        if run_id:
            click.echo(f"No snapshot matches run_id='{run_id}'.", err=True)
        click.echo("Run 'scraperguard run' first to capture a snapshot.", err=True)
        raise SystemExit(1)

    # d) Load schema
    try:
        schema_cls = load_schema_from_file(schema_path)
    except SchemaLoadError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)

    # e) Validate
    validation_result = schema_cls.validate_batch(
        snapshot.extracted_items,
        run_id=snapshot.run_id,
        url=url,
    )

    # f) Save result
    storage.save_validation_result(validation_result)

    # g) Drift analysis
    drift_threshold = threshold if threshold is not None else cfg.schema.null_drift_threshold
    drift_events = run_drift_analysis(validation_result, storage, threshold=drift_threshold)

    # h) Print summary
    click.echo(f"Validation Summary for {url}")
    click.echo(f"  Total items: {validation_result.total_items}")
    click.echo(f"  Passed: {validation_result.passed_count}")
    click.echo(f"  Failed: {validation_result.failed_count}")

    if validation_result.field_failures:
        click.echo("")
        click.echo("Per-field failures:")
        for ff in validation_result.field_failures:
            click.echo(f"  {ff.field_name} ({ff.failure_type}): {ff.count}")

    if drift_events:
        click.echo("")
        click.echo("Drift events:")
        for d in drift_events:
            click.echo(f"  [{d.severity}] {d.message}")


@cli.command()
@click.option("--url", required=True, help="URL to compare snapshots for.")
@click.option("--last", default=2, type=int, help="Number of recent snapshots to compare.")
@click.option("--selectors", default=None, help="Comma-separated CSS selectors to track.")
def diff(url: str, last: int, selectors: str | None) -> None:
    """Compare recent DOM snapshots for structural changes."""
    # a) Load config, init storage
    cfg = load_config()
    storage = get_storage_backend(cfg)

    # b) Get snapshots
    snapshots = storage.list_snapshots(url, limit=last)

    # c) Check minimum
    if len(snapshots) < 2:
        click.echo(f"Error: Need at least 2 snapshots to diff, found {len(snapshots)}.", err=True)
        click.echo(f"Run 'scraperguard run' to capture more snapshots for {url}.", err=True)
        raise SystemExit(1)

    # d) Compare two most recent
    newest = snapshots[0]
    previous = snapshots[1]

    after_tree = parse_to_tree(newest.normalized_html)
    before_tree = parse_to_tree(previous.normalized_html)
    changes = diff_trees(before_tree, after_tree)

    # Selector tracking
    selector_list = [s.strip() for s in selectors.split(",") if s.strip()] if selectors else []
    selector_statuses = []
    if selector_list:
        selector_statuses = track_selectors(after_tree, before_tree, selector_list)

    # e) Print diff summary
    click.echo(f"DOM Diff: {url}")
    click.echo(f"  Comparing snapshot {newest.id[:8]} vs {previous.id[:8]}")
    click.echo(f"  Total changes: {len(changes)}")

    if changes:
        high = sum(1 for c in changes if c.severity == "high")
        medium = sum(1 for c in changes if c.severity == "medium")
        low = sum(1 for c in changes if c.severity == "low")
        click.echo(f"  Severity: {high} high, {medium} medium, {low} low")
        click.echo("")
        click.echo("Changes:")
        for c in changes:
            click.echo(f"  [{c.severity}] {c.message}")

    if selector_statuses:
        click.echo("")
        click.echo("Selector Status:")
        for ss in selector_statuses:
            click.echo(f"  [{ss.status}] {ss.message}")

    # f) Timeline for --last > 2
    if last > 2 and len(snapshots) > 2:
        click.echo("")
        click.echo("Fingerprint Timeline:")
        for s in snapshots:
            click.echo(f"  {s.timestamp.isoformat()}: {s.fingerprint[:16]}...")


@cli.command()
@click.option("--url", required=True, help="URL to report on.")
@click.option("--run-id", default=None, help="Report on a specific run ID.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "json", "csv"]),
    default="text",
    help="Output format.",
)
def report(url: str, run_id: str | None, fmt: str) -> None:
    """Export a health report for monitored scrapers."""
    # a) Load config, init storage
    cfg = load_config()
    storage = get_storage_backend(cfg)

    # b) Get snapshot and validation result
    if run_id:
        snapshots = storage.list_snapshots(url, limit=100)
        snapshot = next((s for s in snapshots if s.run_id == run_id), None)
    else:
        snapshot = storage.get_latest_snapshot(url)

    if snapshot is None:
        click.echo(f"Error: No snapshot found for URL '{url}'.", err=True)
        raise SystemExit(1)

    # Try to find a validation result
    validation_result = None
    try:
        validation_result = storage.get_latest_validation_result_by_url(url)
    except Exception:
        pass

    # c) Compute health score
    health_report = compute_health_score(
        validation_result=validation_result,
        selector_statuses=[],
        dom_changes=[],
        classifications=[],
        drift_events=[],
        run_id=snapshot.run_id,
        url=url,
    )

    # d/e/f) Output
    if fmt == "text":
        click.echo(format_health_report(health_report))
    elif fmt == "json":
        report_dict = {
            "url": health_report.url,
            "overall_score": health_report.overall_score,
            "status": health_report.status,
            "run_id": health_report.run_id,
            "timestamp": health_report.timestamp.isoformat(),
            "components": [
                {
                    "name": c.name,
                    "score": c.score,
                    "weight": c.weight,
                    "details": c.details,
                }
                for c in health_report.components
            ],
        }
        click.echo(json.dumps(report_dict, indent=2))
    elif fmt == "csv":
        # Find component scores
        comp_map = {c.name: c.score for c in health_report.components}
        schema_compliance = comp_map.get("Schema Compliance", "")
        extraction_completeness = comp_map.get("Extraction Completeness", "")
        selector_stability = comp_map.get("Selector Stability", "")
        click.echo("url,score,status,schema_compliance,extraction_completeness,selector_stability,timestamp")
        click.echo(
            f"{url},{health_report.overall_score},{health_report.status},"
            f"{schema_compliance},{extraction_completeness},{selector_stability},"
            f"{health_report.timestamp.isoformat()}"
        )


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", default=8000, type=int, help="Port number.")
def serve(host: str, port: int) -> None:
    """Start the ScraperGuard dashboard API server."""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "Error: uvicorn not installed. "
            "Install API dependencies: pip install scraperguard[api]",
            err=True,
        )
        raise SystemExit(1)

    from scraperguard.api.app import create_app

    app = create_app()
    click.echo(f"Starting ScraperGuard dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
