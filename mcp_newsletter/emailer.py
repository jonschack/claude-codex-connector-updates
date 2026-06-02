from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Optional


DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 465


class EmailConfigError(RuntimeError):
    pass


def _require(name: str, value: Optional[str]) -> str:
    if not value:
        raise EmailConfigError(f"{name} is required (set the {name} environment variable)")
    return value


def send_daily_report(
    root: Path,
    run_date: str,
    to_addr: Optional[str] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    smtp_host: str = DEFAULT_SMTP_HOST,
    smtp_port: int = DEFAULT_SMTP_PORT,
) -> str:
    to_addr = _require("MCP_NEWSLETTER_EMAIL_TO", to_addr or os.environ.get("MCP_NEWSLETTER_EMAIL_TO"))
    smtp_user = _require("MCP_NEWSLETTER_SMTP_USER", smtp_user or os.environ.get("MCP_NEWSLETTER_SMTP_USER"))
    smtp_password = _require(
        "MCP_NEWSLETTER_SMTP_PASSWORD",
        smtp_password or os.environ.get("MCP_NEWSLETTER_SMTP_PASSWORD"),
    )

    report_path = root / "reports" / f"{run_date}.md"
    if not report_path.exists():
        raise EmailConfigError(f"report not found: {report_path}")
    body = report_path.read_text(encoding="utf-8")

    _smtp_send(
        subject=f"MCP Write-Capability Report: {run_date}",
        body=body,
        to_addr=to_addr,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
    )
    return f"Sent {report_path.name} to {to_addr}"


def _smtp_send(
    subject: str,
    body: str,
    to_addr: str,
    smtp_user: str,
    smtp_password: str,
    smtp_host: str = DEFAULT_SMTP_HOST,
    smtp_port: int = DEFAULT_SMTP_PORT,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = to_addr
    message.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as smtp:
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)


def send_alert(
    subject: str,
    body: str,
    to_addr: Optional[str] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    smtp_host: str = DEFAULT_SMTP_HOST,
    smtp_port: int = DEFAULT_SMTP_PORT,
) -> str:
    """Send a one-off alert (e.g. a degraded-pipeline notification).

    Reuses the same SMTP wiring/credentials as the daily report; raises
    EmailConfigError when credentials are absent so callers can no-op cleanly.
    """
    to_addr = _require("MCP_NEWSLETTER_EMAIL_TO", to_addr or os.environ.get("MCP_NEWSLETTER_EMAIL_TO"))
    smtp_user = _require("MCP_NEWSLETTER_SMTP_USER", smtp_user or os.environ.get("MCP_NEWSLETTER_SMTP_USER"))
    smtp_password = _require(
        "MCP_NEWSLETTER_SMTP_PASSWORD",
        smtp_password or os.environ.get("MCP_NEWSLETTER_SMTP_PASSWORD"),
    )
    _smtp_send(
        subject=subject,
        body=body,
        to_addr=to_addr,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
    )
    return f"Sent alert to {to_addr}"
