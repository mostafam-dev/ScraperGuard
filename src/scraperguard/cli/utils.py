"""CLI utility helpers."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from scraperguard.core.schema.base import BaseSchema


class SchemaLoadError(Exception):
    """Raised when a schema file cannot be loaded."""


def load_schema_from_file(path: str) -> type[BaseSchema]:
    """Dynamically import a Python file and find the first BaseSchema subclass.

    Args:
        path: Path to a Python file containing a BaseSchema subclass.

    Returns:
        The BaseSchema subclass found in the file.

    Raises:
        SchemaLoadError: If the file doesn't exist, can't be imported,
            or contains no BaseSchema subclass.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise SchemaLoadError(f"Schema file not found: {path}")

    module_name = f"_scraperguard_schema_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise SchemaLoadError(f"Cannot load Python module from: {path}")

    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SchemaLoadError(f"Error importing schema file {path}: {exc}") from exc

    # Find the first BaseSchema subclass (not BaseSchema itself)
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseSchema) and obj is not BaseSchema:
            return obj

    raise SchemaLoadError(
        f"No BaseSchema subclass found in {path}. "
        f"Define a class that inherits from scraperguard.core.schema.base.BaseSchema."
    )
