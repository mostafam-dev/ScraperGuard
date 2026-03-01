"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from scraperguard.api.routes import router
from scraperguard.config import ScraperGuardConfig, get_storage_backend

logger = logging.getLogger("scraperguard.api")


def create_app(config: ScraperGuardConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Initializes the storage backend from config and registers all API routes.

    Args:
        config: Application configuration. Uses defaults if None.

    Returns:
        Configured FastAPI instance.
    """
    if config is None:
        config = ScraperGuardConfig()

    app = FastAPI(
        title="ScraperGuard",
        description="Scraper reliability monitoring API",
    )

    # CORS middleware — allow all origins for now
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler — return JSON instead of HTML
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )

    # Request logging middleware
    @app.middleware("http")
    async def _request_logging_middleware(request: Request, call_next: Any) -> Any:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    app.state.storage = get_storage_backend(config)
    app.include_router(router)

    return app
