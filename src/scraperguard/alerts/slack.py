"""Slack alert dispatcher — sends alerts via Slack incoming webhooks."""

from __future__ import annotations

import json
import urllib.request
from typing import TYPE_CHECKING

from scraperguard.alerts.base import AlertDispatcher

if TYPE_CHECKING:
    from scraperguard.alerts.models import Alert

_SEVERITY_EMOJI = {
    "critical": ":red_circle:",
    "warning": ":warning:",
    "info": ":information_source:",
}


class SlackDispatcher(AlertDispatcher):
    """Dispatches alerts to a Slack channel via incoming webhook URL."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    @property
    def name(self) -> str:
        return "slack"

    def _build_payload(self, alert: Alert) -> dict:
        emoji = _SEVERITY_EMOJI.get(alert.severity, ":grey_question:")
        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{emoji} *{alert.title}*",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": alert.message,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Scraper:*\n{alert.scraper_name}"},
                        {"type": "mrkdwn", "text": f"*Severity:*\n{alert.severity}"},
                        {"type": "mrkdwn", "text": f"*URL:*\n{alert.url}"},
                        {"type": "mrkdwn", "text": f"*Timestamp:*\n{alert.timestamp.isoformat()}"},
                    ],
                },
            ],
        }

    def send(self, alert: Alert) -> bool:
        """Post a formatted Block Kit message to Slack.

        Returns True on HTTP 200, False on any error.
        """
        try:
            payload = self._build_payload(alert)
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                return resp.status == 200
        except Exception:
            return False
