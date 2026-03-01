"""Base alert dispatcher interface.

All alert channels (Slack, email, webhook) implement this interface.
The alerting system evaluates thresholds and dispatches to all
configured channels.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scraperguard.alerts.models import Alert


class AlertDispatcher(ABC):
    """Base class for alert channel implementations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this dispatcher (e.g. 'slack', 'webhook')."""

    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """Dispatch an alert through this channel.

        Args:
            alert: The structured alert to send.

        Returns:
            True if the alert was sent successfully, False otherwise.
            Implementations must never raise — alert failures should not
            crash the scraping pipeline.
        """
