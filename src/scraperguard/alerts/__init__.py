"""Alert dispatchers — Slack, email, and webhook notification channels.

Sends structured alerts when health scores drop below thresholds,
schema drift is detected, or selectors break. Each channel implements
a common AlertDispatcher interface.
"""

from scraperguard.alerts.base import AlertDispatcher
from scraperguard.alerts.dispatcher import AlertManager
from scraperguard.alerts.email_alert import EmailDispatcher
from scraperguard.alerts.models import Alert
from scraperguard.alerts.slack import SlackDispatcher
from scraperguard.alerts.webhook import WebhookDispatcher

__all__ = [
    "Alert",
    "AlertDispatcher",
    "AlertManager",
    "EmailDispatcher",
    "SlackDispatcher",
    "WebhookDispatcher",
]
