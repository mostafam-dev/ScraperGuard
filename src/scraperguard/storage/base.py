"""Storage backend interface.

Defines the contract that all storage backends (Postgres, SQLite, JSONL)
must implement. Covers run management, snapshot persistence, validation
result storage, and query operations needed by the drift tracker and API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scraperguard.storage.models import RunMetadata, Snapshot, ValidationResult


class StorageBackend(ABC):
    """Abstract base for all storage backends.

    Every backend must implement all methods. List and get_latest methods
    return results ordered newest-first (by timestamp descending).
    Methods that look up a single record return None when nothing is found.
    """

    # -- Run management -----------------------------------------------------

    @abstractmethod
    def create_run(self, scraper_name: str, config: dict | None = None) -> RunMetadata:
        """Create a new run record and return it.

        Generates a UUID4 id, sets status to "running", and persists the run.

        Args:
            scraper_name: Identifier for the scraper being executed.
            config: Optional configuration snapshot captured at run start.

        Returns:
            The newly created RunMetadata with a generated id and timestamp.
        """

    @abstractmethod
    def update_run_status(self, run_id: str, status: str) -> None:
        """Update the status of an existing run.

        Args:
            run_id: UUID of the run to update.
            status: New status value — one of "running", "completed", "failed".
        """

    @abstractmethod
    def list_runs(self, limit: int = 20) -> list[RunMetadata]:
        """Retrieve recent runs, newest first.

        Args:
            limit: Maximum number of runs to return. Defaults to 20.

        Returns:
            A list of RunMetadata ordered by timestamp descending.
        """

    @abstractmethod
    def get_run(self, run_id: str) -> RunMetadata | None:
        """Retrieve a run by its id.

        Args:
            run_id: UUID of the run to look up.

        Returns:
            The RunMetadata if found, or None if no run exists with that id.
        """

    # -- Snapshot persistence -----------------------------------------------

    @abstractmethod
    def save_snapshot(self, snapshot: Snapshot) -> None:
        """Persist a DOM snapshot.

        The snapshot's id, run_id, url, and timestamp must already be set.
        The backend stores the full record including normalized_html,
        fingerprint, raw_html (if present), extracted_items, and metadata.

        Args:
            snapshot: The fully populated Snapshot to store.
        """

    @abstractmethod
    def get_snapshot_by_id(self, snapshot_id: str) -> Snapshot | None:
        """Retrieve a single snapshot by its unique id.

        Args:
            snapshot_id: UUID of the snapshot.

        Returns:
            The Snapshot if found, or None if no snapshot exists with that id.
        """

    @abstractmethod
    def get_latest_snapshot(self, url: str) -> Snapshot | None:
        """Retrieve the most recent snapshot for a given URL.

        "Most recent" is determined by the snapshot's timestamp field,
        ordered descending.

        Args:
            url: The page URL to look up.

        Returns:
            The newest Snapshot for that URL, or None if no snapshots exist.
        """

    @abstractmethod
    def list_snapshots(self, url: str, limit: int = 10) -> list[Snapshot]:
        """Retrieve recent snapshots for a URL, newest first.

        Args:
            url: The page URL to filter by.
            limit: Maximum number of snapshots to return. Defaults to 10.

        Returns:
            A list of Snapshots ordered by timestamp descending,
            up to *limit* entries. Returns an empty list if none exist.
        """

    # -- Validation result persistence --------------------------------------

    @abstractmethod
    def save_validation_result(self, result: ValidationResult) -> None:
        """Persist a validation result.

        The result's id, run_id, url, schema_name, and timestamp must
        already be set. The backend stores the full record including
        pass/fail counts, field_failures, and null_ratios.

        Args:
            result: The fully populated ValidationResult to store.
        """

    @abstractmethod
    def get_latest_validation_result(
        self, url: str, schema_name: str
    ) -> ValidationResult | None:
        """Retrieve the most recent validation result for a URL and schema.

        "Most recent" is determined by the result's timestamp field,
        ordered descending.

        Args:
            url: The page URL to filter by.
            schema_name: The schema name to filter by.

        Returns:
            The newest ValidationResult matching the filters,
            or None if no results exist.
        """

    @abstractmethod
    def get_latest_validation_result_by_url(self, url: str) -> ValidationResult | None:
        """Retrieve the most recent validation result for a URL, any schema.

        Args:
            url: The page URL to filter by.

        Returns:
            The newest ValidationResult for that URL regardless of schema name,
            or None if no results exist.
        """

    @abstractmethod
    def list_validation_results(
        self, url: str, schema_name: str, limit: int = 10
    ) -> list[ValidationResult]:
        """Retrieve recent validation results for a URL and schema, newest first.

        Args:
            url: The page URL to filter by.
            schema_name: The schema name to filter by.
            limit: Maximum number of results to return. Defaults to 10.

        Returns:
            A list of ValidationResults ordered by timestamp descending,
            up to *limit* entries. Returns an empty list if none exist.
        """
