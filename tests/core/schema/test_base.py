from __future__ import annotations

import pytest

from scraperguard.core.schema.base import BaseSchema, SchemaValidationError
from scraperguard.storage.models import FieldFailure


class ProductSchema(BaseSchema):
    title: str
    price: float
    availability: bool
    rating: float | None = None


def _valid_item(**overrides: object) -> dict:
    base = {"title": "Widget", "price": 9.99, "availability": True, "rating": 4.5}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# validate_item
# ---------------------------------------------------------------------------


class TestValidateItem:
    def test_validate_item_valid(self) -> None:
        ok, failures = ProductSchema.validate_item(_valid_item())
        assert ok is True
        assert failures == []

    def test_validate_item_missing_required(self) -> None:
        item = _valid_item()
        del item["price"]
        ok, failures = ProductSchema.validate_item(item)
        assert ok is False
        assert len(failures) == 1
        assert failures[0].field_name == "price"
        assert failures[0].failure_type == "missing"
        assert failures[0].count == 1

    def test_validate_item_wrong_type(self) -> None:
        ok, failures = ProductSchema.validate_item(_valid_item(price="not_a_number"))
        assert ok is False
        types = [f.failure_type for f in failures if f.field_name == "price"]
        assert "type_mismatch" in types

    def test_validate_item_null_required(self) -> None:
        ok, failures = ProductSchema.validate_item(_valid_item(price=None))
        assert ok is False
        types = [f.failure_type for f in failures if f.field_name == "price"]
        assert len(types) == 1
        # Pydantic may report this as type_mismatch (float vs None) — accept either
        assert types[0] in ("null", "type_mismatch")

    def test_validate_item_optional_null(self) -> None:
        ok, failures = ProductSchema.validate_item(_valid_item(rating=None))
        assert ok is True
        assert failures == []

    def test_validate_item_extra_fields_ignored(self) -> None:
        ok, failures = ProductSchema.validate_item(_valid_item(color="red"))
        assert ok is True
        assert failures == []


# ---------------------------------------------------------------------------
# validate_batch
# ---------------------------------------------------------------------------


class TestValidateBatch:
    def test_validate_batch_all_valid(self) -> None:
        items = [_valid_item() for _ in range(10)]
        result = ProductSchema.validate_batch(items)
        assert result.total_items == 10
        assert result.passed_count == 10
        assert result.failed_count == 0
        assert result.field_failures == []

    def test_validate_batch_mixed(self) -> None:
        valid = [_valid_item() for _ in range(10)]
        missing_price = [_valid_item() for _ in range(3)]
        for item in missing_price:
            del item["price"]
        wrong_title = [_valid_item(title=12345) for _ in range(2)]
        items = valid + missing_price + wrong_title

        result = ProductSchema.validate_batch(items)
        assert result.total_items == 15
        assert result.passed_count == 10
        assert result.failed_count == 5

        failure_map = {
            (f.field_name, f.failure_type): f.count for f in result.field_failures
        }
        assert failure_map[("price", "missing")] == 3
        assert failure_map[("title", "type_mismatch")] == 2

    def test_validate_batch_null_ratios_computed(self) -> None:
        items = [_valid_item() for _ in range(20)]
        for i in range(4):
            items[i]["price"] = None
        result = ProductSchema.validate_batch(items)

        assert result.null_ratios["price"] == pytest.approx(0.2)
        assert result.null_ratios["title"] == pytest.approx(0.0)
        # All schema fields present
        for field in ProductSchema.get_field_names():
            assert field in result.null_ratios

    def test_validate_batch_null_ratios_missing_field(self) -> None:
        items = [_valid_item() for _ in range(10)]
        for i in range(3):
            del items[i]["price"]
        result = ProductSchema.validate_batch(items)
        assert result.null_ratios["price"] == pytest.approx(0.3)

    def test_validate_batch_empty_list(self) -> None:
        result = ProductSchema.validate_batch([])
        assert result.total_items == 0
        assert result.passed_count == 0
        assert result.failed_count == 0
        for field in ProductSchema.get_field_names():
            assert result.null_ratios[field] == 0.0

    def test_validate_batch_sets_metadata(self) -> None:
        result = ProductSchema.validate_batch(
            [_valid_item()], run_id="run-123", url="https://example.com"
        )
        assert result.run_id == "run-123"
        assert result.url == "https://example.com"
        assert result.schema_name == "ProductSchema"

    def test_validate_batch_not_a_list_raises(self) -> None:
        with pytest.raises(SchemaValidationError):
            ProductSchema.validate_batch("not a list")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Field introspection
# ---------------------------------------------------------------------------


class TestFieldIntrospection:
    def test_get_field_names(self) -> None:
        assert ProductSchema.get_field_names() == [
            "title",
            "price",
            "availability",
            "rating",
        ]

    def test_get_required_fields(self) -> None:
        assert ProductSchema.get_required_fields() == [
            "title",
            "price",
            "availability",
        ]

    def test_get_optional_fields(self) -> None:
        assert ProductSchema.get_optional_fields() == ["rating"]
