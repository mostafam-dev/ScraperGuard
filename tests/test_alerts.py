"""Tests for the alerting system."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from scraperguard.alerts.dispatcher import AlertManager
from scraperguard.alerts.email_alert import EmailDispatcher
from scraperguard.alerts.models import Alert
from scraperguard.alerts.slack import SlackDispatcher
from scraperguard.alerts.webhook import WebhookDispatcher
from scraperguard.config import AlertThresholds


def _make_alert(severity: str = "critical") -> Alert:
    return Alert(
        severity=severity,
        title="Selector break detected",
        message="The selector '.price-tag span' returned 0 matches.",
        scraper_name="price_spider",
        url="https://example.com/products",
        run_id="run-abc-123",
        timestamp=datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        details={"selector": ".price-tag span", "match_count": 0},
    )


class TestAlertCreation:
    def test_alert_creation(self) -> None:
        alert = _make_alert()
        assert alert.severity == "critical"
        assert alert.title == "Selector break detected"
        assert alert.message == "The selector '.price-tag span' returned 0 matches."
        assert alert.scraper_name == "price_spider"
        assert alert.url == "https://example.com/products"
        assert alert.run_id == "run-abc-123"
        assert alert.timestamp == datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert alert.details == {"selector": ".price-tag span", "match_count": 0}

    def test_alert_to_dict(self) -> None:
        alert = _make_alert()
        d = alert.to_dict()
        assert d["severity"] == "critical"
        assert d["timestamp"] == "2025-03-01T12:00:00+00:00"
        assert d["details"]["match_count"] == 0


class TestAlertManagerFiltering:
    def test_filters_out_info_when_threshold_is_warning(self) -> None:
        thresholds = AlertThresholds(schema_failure="warning")
        manager = AlertManager(dispatchers=[], thresholds=thresholds)

        assert manager.should_alert(_make_alert(severity="info")) is False
        assert manager.should_alert(_make_alert(severity="warning")) is True
        assert manager.should_alert(_make_alert(severity="critical")) is True

    def test_filters_out_info_and_warning_when_threshold_is_critical(self) -> None:
        thresholds = AlertThresholds(schema_failure="critical")
        manager = AlertManager(dispatchers=[], thresholds=thresholds)

        assert manager.should_alert(_make_alert(severity="info")) is False
        assert manager.should_alert(_make_alert(severity="warning")) is False
        assert manager.should_alert(_make_alert(severity="critical")) is True

    def test_allows_everything_when_threshold_is_info(self) -> None:
        thresholds = AlertThresholds(schema_failure="info")
        manager = AlertManager(dispatchers=[], thresholds=thresholds)

        assert manager.should_alert(_make_alert(severity="info")) is True
        assert manager.should_alert(_make_alert(severity="warning")) is True
        assert manager.should_alert(_make_alert(severity="critical")) is True

    def test_dispatch_returns_empty_when_filtered(self) -> None:
        thresholds = AlertThresholds(schema_failure="critical")
        manager = AlertManager(dispatchers=[], thresholds=thresholds)

        result = manager.dispatch(_make_alert(severity="info"))
        assert result == {}


class TestSlackDispatcher:
    def test_formats_block_kit_payload(self) -> None:
        dispatcher = SlackDispatcher(webhook_url="https://hooks.slack.test/xyz")
        alert = _make_alert()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("scraperguard.alerts.slack.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = dispatcher.send(alert)

        assert result is True
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))

        # Verify Block Kit structure
        assert "blocks" in payload
        blocks = payload["blocks"]
        assert len(blocks) == 3

        # Title block with emoji
        assert blocks[0]["type"] == "section"
        assert ":red_circle:" in blocks[0]["text"]["text"]
        assert "*Selector break detected*" in blocks[0]["text"]["text"]

        # Message block
        assert blocks[1]["type"] == "section"
        assert "'.price-tag span'" in blocks[1]["text"]["text"]

        # Fields block
        fields = blocks[2]["fields"]
        assert len(fields) == 4
        field_texts = [f["text"] for f in fields]
        assert any("price_spider" in t for t in field_texts)
        assert any("critical" in t for t in field_texts)

    def test_returns_false_on_error(self) -> None:
        dispatcher = SlackDispatcher(webhook_url="https://hooks.slack.test/xyz")

        with patch(
            "scraperguard.alerts.slack.urllib.request.urlopen",
            side_effect=ConnectionError("Network unreachable"),
        ):
            result = dispatcher.send(_make_alert())

        assert result is False


class TestWebhookDispatcher:
    def test_sends_json_payload(self) -> None:
        dispatcher = WebhookDispatcher(
            url="https://webhooks.example.com/alert",
            headers={"X-Api-Key": "secret"},
        )
        alert = _make_alert()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("scraperguard.alerts.webhook.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = dispatcher.send(alert)

        assert result is True
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))

        assert payload["severity"] == "critical"
        assert payload["title"] == "Selector break detected"
        assert payload["scraper_name"] == "price_spider"
        assert payload["url"] == "https://example.com/products"
        assert payload["run_id"] == "run-abc-123"

        # Verify custom header was included
        assert req.get_header("X-api-key") == "secret"

    def test_returns_false_on_error(self) -> None:
        dispatcher = WebhookDispatcher(url="https://webhooks.example.com/alert")

        with patch(
            "scraperguard.alerts.webhook.urllib.request.urlopen",
            side_effect=TimeoutError("Connection timed out"),
        ):
            result = dispatcher.send(_make_alert())

        assert result is False


class TestEmailDispatcher:
    def test_email_dispatcher_formats_message(self) -> None:
        dispatcher = EmailDispatcher(
            smtp_host="smtp.test.local",
            smtp_port=587,
            sender="alerts@scraperguard.test",
            recipients=["ops@example.com", "dev@example.com"],
            username="user",
            password="pass",
            use_tls=True,
        )
        alert = _make_alert()

        mock_smtp_instance = MagicMock()
        with patch("scraperguard.alerts.email_alert.smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
            result = dispatcher.send(alert)

        assert result is True

        # Verify SMTP was constructed with correct host/port
        mock_smtp_cls.assert_called_once_with("smtp.test.local", 587)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("user", "pass")

        # Verify sendmail was called with correct sender and recipients
        send_args = mock_smtp_instance.sendmail.call_args
        assert send_args[0][0] == "alerts@scraperguard.test"
        assert send_args[0][1] == ["ops@example.com", "dev@example.com"]

        # Verify email content
        email_body = send_args[0][2]
        assert "[ScraperGuard/CRITICAL] Selector break detected" in email_body
        assert "alerts@scraperguard.test" in email_body
        assert "ops@example.com" in email_body
        assert "price_spider" in email_body
        assert "https://example.com/products" in email_body
        assert "run-abc-123" in email_body
        assert "The selector '.price-tag span' returned 0 matches." in email_body

        mock_smtp_instance.quit.assert_called_once()

    def test_email_dispatcher_returns_false_on_smtp_error(self) -> None:
        dispatcher = EmailDispatcher(
            smtp_host="smtp.test.local",
            smtp_port=587,
            sender="alerts@scraperguard.test",
            recipients=["ops@example.com"],
        )

        with patch(
            "scraperguard.alerts.email_alert.smtplib.SMTP",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            result = dispatcher.send(_make_alert())

        assert result is False


class TestAlertManagerDispatch:
    def test_dispatch_sends_to_all_dispatchers(self) -> None:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        slack = SlackDispatcher(webhook_url="https://hooks.slack.test/xyz")
        webhook = WebhookDispatcher(url="https://webhooks.example.com/alert")
        thresholds = AlertThresholds(schema_failure="warning")
        manager = AlertManager(dispatchers=[slack, webhook], thresholds=thresholds)

        with patch("scraperguard.alerts.slack.urllib.request.urlopen", return_value=mock_response), \
             patch("scraperguard.alerts.webhook.urllib.request.urlopen", return_value=mock_response):
            results = manager.dispatch(_make_alert(severity="critical"))

        assert results == {"slack": True, "webhook": True}
