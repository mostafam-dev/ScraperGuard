"""Base schema class for defining expected scraper output.

Users subclass BaseSchema to declare the fields their scraper should produce.
The validator uses these definitions to check extracted data against expectations,
computing per-field null ratios and comparing against historical baselines.

Example:
    class ProductSchema(BaseSchema):
        title: str
        price: float
        availability: bool
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ValidationError

from scraperguard.storage.models import FieldFailure, ValidationResult


class SchemaValidationError(Exception):
    """Raised when schema validation encounters an unrecoverable error."""


_PYDANTIC_TYPE_TO_FAILURE = {
    "missing": "missing",
    "value_error.missing": "missing",
    "none_not_allowed": "null",
}


def _map_error_type(pydantic_type: str) -> str:
    if pydantic_type in _PYDANTIC_TYPE_TO_FAILURE:
        return _PYDANTIC_TYPE_TO_FAILURE[pydantic_type]
    if "missing" in pydantic_type:
        return "missing"
    if "none" in pydantic_type.lower():
        return "null"
    if "type" in pydantic_type or "parsing" in pydantic_type:
        return "type_mismatch"
    return "validation_error"


class BaseSchema(BaseModel):
    """Base class for scraper output schemas."""

    @classmethod
    def validate_item(cls, item: dict[str, Any]) -> tuple[bool, list[FieldFailure]]:
        """Validate a single item against the schema."""
        try:
            cls.model_validate(item)
            return (True, [])
        except ValidationError as exc:
            failures = []
            for error in exc.errors():
                field_name = str(error["loc"][0]) if error["loc"] else "unknown"
                failure_type = _map_error_type(error["type"])
                failures.append(
                    FieldFailure(
                        field_name=field_name,
                        failure_type=failure_type,
                        count=1,
                    )
                )
            return (False, failures)

    @classmethod
    def validate_batch(
        cls,
        items: list[dict[str, Any]],
        run_id: str = "",
        url: str = "",
    ) -> ValidationResult:
        """Validate a list of extracted items against the schema."""
        if not isinstance(items, list):
            raise SchemaValidationError(f"items must be a list, got {type(items).__name__}")

        all_fields = cls.get_field_names()
        total_items = len(items)
        passed_count = 0
        failed_count = 0

        # (field_name, failure_type) -> count
        failure_counts: dict[tuple[str, str], int] = defaultdict(int)
        # field_name -> null/missing count
        null_counts: dict[str, int] = defaultdict(int)

        for item in items:
            ok, failures = cls.validate_item(item)
            if ok:
                passed_count += 1
            else:
                failed_count += 1
                for f in failures:
                    failure_counts[(f.field_name, f.failure_type)] += 1

            # Compute null/missing for every field
            for field_name in all_fields:
                if field_name not in item or item[field_name] is None:
                    null_counts[field_name] += 1

        # Build aggregated FieldFailure list
        field_failures = [
            FieldFailure(field_name=fname, failure_type=ftype, count=count)
            for (fname, ftype), count in failure_counts.items()
        ]

        # Compute null ratios
        if total_items == 0:
            null_ratios = {f: 0.0 for f in all_fields}
        else:
            null_ratios = {f: null_counts[f] / total_items for f in all_fields}

        return ValidationResult(
            run_id=run_id,
            url=url,
            schema_name=cls.__name__,
            total_items=total_items,
            passed_count=passed_count,
            failed_count=failed_count,
            field_failures=field_failures,
            null_ratios=null_ratios,
        )

    @classmethod
    def get_field_names(cls) -> list[str]:
        """Return list of all field names defined in the schema."""
        return list(cls.model_fields.keys())

    @classmethod
    def get_required_fields(cls) -> list[str]:
        """Return list of required field names."""
        return [name for name, info in cls.model_fields.items() if info.is_required()]

    @classmethod
    def get_optional_fields(cls) -> list[str]:
        """Return list of optional field names."""
        return [name for name, info in cls.model_fields.items() if not info.is_required()]
