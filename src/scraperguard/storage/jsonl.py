"""JSONL storage backend — lightweight, human-readable event log.

Appends events as newline-delimited JSON. Useful for debugging,
export, and environments where no database is available.
"""

from __future__ import annotations

from scraperguard.storage.base import StorageBackend


class JSONLBackend(StorageBackend):
    """JSONL file-backed storage for snapshots and events."""

    def __init__(self, directory: str = ".scraperguard") -> None:
        self.directory = directory

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
