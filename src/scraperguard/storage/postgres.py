"""PostgreSQL storage backend — production-grade persistence.

Uses psycopg (sync) or asyncpg (async) for snapshot and event storage.
Intended for production deployments with high write throughput.
"""

from __future__ import annotations

from scraperguard.storage.base import StorageBackend


class PostgresBackend(StorageBackend):
    """PostgreSQL-backed storage for snapshots and events."""

    def __init__(self, connection_url: str) -> None:
        self.connection_url = connection_url

    def store_snapshot(self, snapshot: object) -> None:
        raise NotImplementedError

    def get_latest_snapshot(self, url: str) -> object | None:
        raise NotImplementedError

    def get_snapshots(self, url: str, limit: int = 10) -> list:
        raise NotImplementedError

    def store_event(self, event: dict) -> None:
        raise NotImplementedError

    def get_events(self, url: str, limit: int = 100) -> list[dict]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
