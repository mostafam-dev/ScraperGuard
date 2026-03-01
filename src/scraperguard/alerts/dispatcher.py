"""Alert manager — dispatches alerts to all configured channels with threshold filtering."""

from __future__ import annotations

from scraperguard.alerts.base import AlertDispatcher
from scraperguard.alerts.models import Alert
from scraperguard.config import AlertThresholds

_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


class AlertManager:
    """Manages alert dispatch across multiple channels with severity filtering.

    Evaluates whether an alert's severity meets the configured threshold
    before dispatching to all registered AlertDispatcher instances.
    """

    def __init__(
        self,
        dispatchers: list[AlertDispatcher],
        thresholds: AlertThresholds,
    ) -> None:
        self.dispatchers = dispatchers
        self.thresholds = thresholds

    def should_alert(self, alert: Alert) -> bool:
        """Check if the alert severity meets the minimum threshold.

        The threshold is derived from AlertThresholds.schema_failure as the
        baseline severity level. Alerts at or above that level pass through.

        Returns:
            True if the alert should be dispatched, False if filtered out.
        """
        threshold_level = _SEVERITY_ORDER.get(self.thresholds.schema_failure, 0)
        alert_level = _SEVERITY_ORDER.get(alert.severity, 0)
        return alert_level >= threshold_level

    def dispatch(self, alert: Alert) -> dict[str, bool]:
        """Send an alert to all dispatchers if it meets the severity threshold.

        Args:
            alert: The alert to dispatch.

        Returns:
            Dict mapping dispatcher name to success boolean.
            Returns empty dict if the alert was filtered out.
        """
        if not self.should_alert(alert):
            return {}

        results: dict[str, bool] = {}
        for dispatcher in self.dispatchers:
            results[dispatcher.name] = dispatcher.send(alert)
        return results
