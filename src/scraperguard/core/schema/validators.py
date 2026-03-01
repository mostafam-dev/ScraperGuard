"""Built-in field validators for schema definitions.

Provides declarative validators that attach to BaseSchema fields:
- range(min, max) — enforce numeric bounds
- pattern(regex) — enforce string format
- cardinality(min, max) — enforce list length constraints
- not_null() — field must never be None

Example:
    class ProductSchema(BaseSchema):
        price: float = validators.range(min=0.01)
        sku: str = validators.pattern(r"^[A-Z]{2}-\\d{6}$")
"""

from __future__ import annotations

from pydantic import Field


class _Validators:
    """Namespace for built-in validator constructors."""

    @staticmethod
    def range(*, min: float | None = None, max: float | None = None) -> object:
        """Enforce numeric bounds on a field.

        Args:
            min: Minimum acceptable value (inclusive).
            max: Maximum acceptable value (inclusive).
        """
        kwargs: dict = {}
        if min is not None:
            kwargs["ge"] = min
        if max is not None:
            kwargs["le"] = max
        return Field(**kwargs)

    @staticmethod
    def pattern(regex: str) -> object:
        """Enforce a regex pattern on a string field.

        Args:
            regex: Regular expression the field value must match.
        """
        return Field(pattern=regex)

    @staticmethod
    def cardinality(*, min: int = 0, max: int | None = None) -> object:
        """Enforce length constraints on list fields.

        Args:
            min: Minimum number of elements.
            max: Maximum number of elements.
        """
        kwargs: dict = {}
        if min:
            kwargs["min_length"] = min
        if max is not None:
            kwargs["max_length"] = max
        return Field(**kwargs)

    @staticmethod
    def not_null() -> object:
        """Enforce that a field is never None, even if the type allows it."""
        return Field(json_schema_extra={"not_null": True})


validators = _Validators()
