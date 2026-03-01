"""Schema validation engine — Pydantic + JSON Schema enforcement.

This subpackage provides:
- BaseSchema class for defining expected scraper output structure
- Built-in validators (range, pattern, cardinality)
- Null drift detection across item batches
- Type checking and field completeness verification
"""

from scraperguard.core.schema.base import BaseSchema, SchemaValidationError
from scraperguard.core.schema.drift import DriftEvent, detect_null_drift, run_drift_analysis
from scraperguard.core.schema.validators import validators

__all__ = [
    "BaseSchema",
    "DriftEvent",
    "SchemaValidationError",
    "detect_null_drift",
    "run_drift_analysis",
    "validators",
]
