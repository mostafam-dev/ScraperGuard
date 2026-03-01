# Contributing to ScraperGuard

Thanks for your interest in contributing to ScraperGuard!

## Development Setup

1. Clone the repository:

```bash
git clone https://github.com/mostafam-dev/scraperguard.git
cd scraperguard
```

2. Install in development mode:

```bash
pip install -e ".[dev]"
```

Or with uv:

```bash
uv sync --extra dev
```

3. Verify the installation:

```bash
pytest
scraperguard --help
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=scraperguard --cov-report=term-missing

# Run a specific test file
pytest tests/test_health.py

# Run tests matching a pattern
pytest -k "test_schema"
```

## Code Style

We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check for lint errors
ruff check src/ tests/

# Auto-fix lint errors
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/
```

Configuration is in `pyproject.toml` under `[tool.ruff]`.

## Type Checking

We use [mypy](https://mypy.readthedocs.io/) for static type checking:

```bash
mypy src/scraperguard/
```

Configuration is in `pyproject.toml` under `[tool.mypy]`.

## Submitting Changes

1. Fork the repository and create a feature branch:

```bash
git checkout -b feature/my-feature
```

2. Make your changes, ensuring:
   - All tests pass (`pytest`)
   - Code is formatted (`ruff format`)
   - No lint errors (`ruff check`)
   - Types check cleanly (`mypy src/scraperguard/`)

3. Write tests for new functionality.

4. Commit with a clear message describing the change.

5. Open a pull request against the `main` branch.

## Project Structure

```
src/scraperguard/       # Main package source
tests/                  # Test suite (mirrors src/ structure)
examples/               # Working examples and configs
docs/                   # Documentation
```

## Reporting Issues

Please open an issue on GitHub with:
- A clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Python version and OS
