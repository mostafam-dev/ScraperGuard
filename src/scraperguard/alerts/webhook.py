"""Generic webhook alert dispatcher — POSTs JSON alerts to a URL."""

from __future__ import annotations

import json
import urllib.request
from typing import TYPE_CHECKING, Any

from scraperguard.alerts.base import AlertDispatcher

if TYPE_CHECKING:
    from scraperguard.alerts.models import Alert


class WebhookDispatcher(AlertDispatcher):
    """Dispatches alerts as JSON POST requests to a configurable URL."""

    def __init__(self, url: str, headers: dict[str, Any] | None = None) -> None:
        self.url = url
        self.headers = headers or {}

    @property
    def name(self) -> str:
        return "webhook"

    def send(self, alert: Alert) -> bool:
        """POST the alert as JSON to the webhook URL.

        Returns True on HTTP 200, False on any error.
        """
        try:
            data = json.dumps(alert.to_dict()).encode("utf-8")
            req_headers = {"Content-Type": "application/json", **self.headers}
            req = urllib.request.Request(
                self.url,
                data=data,
                headers=req_headers,
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                return bool(resp.status == 200)
        except Exception:
            return False
