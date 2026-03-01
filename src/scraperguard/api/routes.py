"""API route definitions for ScraperGuard."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

import scraperguard
from scraperguard.core.dom_diff.parser import parse_to_tree
from scraperguard.core.dom_diff.selector_tracker import track_selectors
from scraperguard.core.schema.drift import run_drift_analysis
from scraperguard.health import compute_health_score

router = APIRouter(prefix="/api")


def _get_storage(request: Request):
    return request.app.state.storage


@router.get("/health")
async def health() -> dict:
    """Service health check."""
    return {"status": "ok", "version": scraperguard.__version__}


@router.get("/runs")
async def list_runs(request: Request, limit: int = Query(default=20, ge=1)) -> dict:
    """List recent scraper runs."""
    storage = _get_storage(request)
    runs = storage.list_runs(limit=limit)
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> JSONResponse:
    """Get details for a specific run."""
    storage = _get_storage(request)
    run = storage.get_run(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"error": "Run not found"})
    return JSONResponse(content=run.to_dict())


@router.get("/snapshots")
async def list_snapshots(
    request: Request,
    url: str = Query(...),
    limit: int = Query(default=10, ge=1),
) -> dict:
    """List recent snapshots for a URL (lightweight, no HTML bodies)."""
    storage = _get_storage(request)
    snapshots = storage.list_snapshots(url, limit=limit)
    return {"snapshots": [s.to_summary_dict() for s in snapshots]}


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(
    snapshot_id: str,
    request: Request,
    include_raw: bool = Query(default=False),
) -> JSONResponse:
    """Get a single snapshot by ID."""
    storage = _get_storage(request)
    snapshot = storage.get_snapshot_by_id(snapshot_id)
    if snapshot is None:
        return JSONResponse(status_code=404, content={"error": "Snapshot not found"})
    d = snapshot.to_dict()
    if not include_raw:
        d.pop("raw_html", None)
    return JSONResponse(content=d)


@router.get("/validation/{url:path}")
async def list_validation_results(
    url: str,
    request: Request,
    schema_name: str = Query(...),
    limit: int = Query(default=10, ge=1),
) -> dict:
    """List validation result history for a URL and schema."""
    storage = _get_storage(request)
    results = storage.list_validation_results(url, schema_name, limit=limit)
    return {"results": [r.to_dict() for r in results]}


@router.get("/drift/{url:path}")
async def get_drift(
    url: str,
    request: Request,
    schema_name: str = Query(...),
    baseline_count: int = Query(default=5, ge=1),
    threshold: float = Query(default=0.15, ge=0.0),
) -> JSONResponse:
    """Get drift analysis for a URL and schema."""
    storage = _get_storage(request)
    latest = storage.get_latest_validation_result(url, schema_name)
    if latest is None:
        return JSONResponse(
            status_code=404,
            content={"error": "No validation results found for this URL and schema"},
        )
    events = run_drift_analysis(latest, storage, baseline_count=baseline_count, threshold=threshold)
    return JSONResponse(content={
        "drift_events": [asdict(e) for e in events],
        "baseline_count": baseline_count,
        "threshold": threshold,
    })


@router.get("/report/{run_id}")
async def get_report(
    run_id: str,
    request: Request,
    url: str | None = Query(default=None),
) -> JSONResponse:
    """Get a full health report for a run."""
    storage = _get_storage(request)
    run = storage.get_run(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"error": "Run not found"})

    # Get latest snapshot for the URL
    # If url not specified, find the first snapshot for this run
    if url is None:
        # Query snapshots associated with this run — we need to find a URL
        # The storage doesn't have a list-by-run method, so use the connection directly
        if hasattr(storage, '_conn'):
            cursor = storage._conn.execute(
                "SELECT url FROM snapshots WHERE run_id = ? LIMIT 1",
                (run_id,),
            )
            row = cursor.fetchone()
            if row:
                url = row["url"]

    if url is None:
        return JSONResponse(
            status_code=404,
            content={"error": "No snapshots found for this run"},
        )

    storage.get_latest_snapshot(url)
    validation_result = storage.get_latest_validation_result(url, schema_name="")
    # Try to find any schema name for this URL
    if validation_result is None and hasattr(storage, '_conn'):
        cursor = storage._conn.execute(
            "SELECT schema_name FROM validation_results"
            " WHERE url = ? ORDER BY timestamp DESC LIMIT 1",
            (url,),
        )
        row = cursor.fetchone()
        if row:
            validation_result = storage.get_latest_validation_result(url, row["schema_name"])

    drift_events = []
    if validation_result is not None:
        drift_events = run_drift_analysis(validation_result, storage)

    report = compute_health_score(
        validation_result=validation_result,
        selector_statuses=[],
        dom_changes=[],
        classifications=[],
        drift_events=drift_events,
        run_id=run_id,
        url=url,
    )

    return JSONResponse(content={
        "overall_score": report.overall_score,
        "status": report.status,
        "components": [
            {
                "name": c.name,
                "score": round(c.score, 4),
                "weight": c.weight,
                "details": c.details,
            }
            for c in report.components
        ],
        "drift_events": [asdict(e) for e in report.drift_events],
        "run_id": report.run_id,
        "url": report.url,
        "timestamp": report.timestamp.isoformat(),
    })


@router.get("/selectors/{url:path}")
async def get_selector_statuses(
    url: str,
    request: Request,
    selectors: str = Query(..., description="Comma-separated CSS selectors"),
) -> JSONResponse:
    """Track selector statuses across recent snapshots for a URL."""
    storage = _get_storage(request)
    snapshots = storage.list_snapshots(url, limit=2)
    if not snapshots:
        return JSONResponse(
            status_code=404,
            content={"error": "No snapshots found for this URL"},
        )

    selector_list = [s.strip() for s in selectors.split(",") if s.strip()]
    if not selector_list:
        return JSONResponse(
            status_code=400,
            content={"error": "No valid selectors provided"},
        )

    current_tree = parse_to_tree(snapshots[0].normalized_html)
    previous_tree = parse_to_tree(snapshots[1].normalized_html) if len(snapshots) > 1 else None

    statuses = track_selectors(current_tree, previous_tree, selector_list)
    return JSONResponse(content={
        "selector_statuses": [asdict(s) for s in statuses],
    })
