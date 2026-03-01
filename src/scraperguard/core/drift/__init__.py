"""Time-series drift tracking and stability analysis.

Builds long-term reliability profiles per site by tracking:
- Field stability scores over time
- Selector lifespan distributions
- Per-domain volatility indices
- Historical break patterns and change frequency
"""

from scraperguard.core.drift.tracker import DriftTracker

__all__ = ["DriftTracker"]
