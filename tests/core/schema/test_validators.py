"""Tests for the validators module."""

from __future__ import annotations

import pytest

from scraperguard.core.schema.base import BaseSchema
from scraperguard.core.schema.validators import validators


class ProductSchema(BaseSchema):
    price: float = validators.range(min=0.01)
    rating: float = validators.range(min=0, max=5)


class TestRangeValidator:
    def test_valid_item_passes(self):
        ok, errs = ProductSchema.validate_item({"price": 29.99, "rating": 4.5})
        assert ok is True
        assert errs == []

    def test_negative_price_fails(self):
        ok, errs = ProductSchema.validate_item({"price": -1, "rating": 4.5})
        assert ok is False
        assert len(errs) == 1
        assert errs[0].field_name == "price"

    def test_minimum_price_passes(self):
        ok, errs = ProductSchema.validate_item({"price": 0.01, "rating": 4.5})
        assert ok is True

    def test_zero_price_fails(self):
        ok, errs = ProductSchema.validate_item({"price": 0.0, "rating": 4.5})
        assert ok is False
        assert errs[0].field_name == "price"

    def test_rating_above_max_fails(self):
        ok, errs = ProductSchema.validate_item({"price": 1.0, "rating": 6})
        assert ok is False
        assert errs[0].field_name == "rating"

    def test_rating_at_max_passes(self):
        ok, errs = ProductSchema.validate_item({"price": 1.0, "rating": 5})
        assert ok is True

    def test_rating_at_min_passes(self):
        ok, errs = ProductSchema.validate_item({"price": 1.0, "rating": 0})
        assert ok is True

    def test_batch_validation(self):
        items = [
            {"price": 10.0, "rating": 4.0},
            {"price": -1, "rating": 4.0},
            {"price": 10.0, "rating": 6},
        ]
        result = ProductSchema.validate_batch(items)
        assert result.total_items == 3
        assert result.passed_count == 1
        assert result.failed_count == 2
