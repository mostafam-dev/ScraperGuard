"""Email alert dispatcher — sends alerts via SMTP."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

from scraperguard.alerts.base import AlertDispatcher

if TYPE_CHECKING:
    from scraperguard.alerts.models import Alert


class EmailDispatcher(AlertDispatcher):
    """Dispatches alerts via email using SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        sender: str,
        recipients: list[str],
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender = sender
        self.recipients = recipients
        self.username = username
        self.password = password
        self.use_tls = use_tls

    @property
    def name(self) -> str:
        return "email"

    def _build_body(self, alert: Alert) -> str:
        lines = [
            f"Severity: {alert.severity}",
            f"Scraper: {alert.scraper_name}",
            f"URL: {alert.url}",
            f"Run ID: {alert.run_id}",
            f"Timestamp: {alert.timestamp.isoformat()}",
            "",
            alert.message,
        ]
        if alert.details:
            lines.append("")
            lines.append("Details:")
            for key, value in alert.details.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    def send(self, alert: Alert) -> bool:
        """Send a plain-text email with alert details.

        Returns True if the email was sent successfully, False on any error.
        """
        try:
            msg = MIMEText(self._build_body(alert))
            msg["Subject"] = f"[ScraperGuard/{alert.severity.upper()}] {alert.title}"
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)

            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)

            if self.username and self.password:
                server.login(self.username, self.password)

            server.sendmail(self.sender, self.recipients, msg.as_string())
            server.quit()
            return True
        except Exception:
            return False
