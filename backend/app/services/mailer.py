"""Outgoing email. SMTP (stdlib smtplib) when SMTP_HOST is set; otherwise the message is written to the log (development/test) and kept in
OUTBOX so tests can read it. Message bodies contain single-use links, so they are never logged in production."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Settings, get_settings
from app.core.logging import log

logger = logging.getLogger("raven.mail")
OUTBOX: list[dict[str, str]] = []  # only filled when SMTP is not configured and the app is not in production


def send_email(to: str, subject: str, body: str, s: Settings | None = None) -> bool:
    """Returns True if the message was handed to a transport. Never raises: a mail failure must not break the request."""
    s = s or get_settings()
    if not s.smtp_host:
        if s.is_production:
            log(logger, "email_not_sent", logging.ERROR, reason="SMTP_HOST is not configured")
            return False
        OUTBOX.append({"to": to, "subject": subject, "body": body})
        del OUTBOX[:-200]
        log(logger, "email_outbox", logging.INFO, to=to, subject=subject, body=body)
        return True
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log(logger, "email_failed", logging.ERROR, error_type=type(exc).__name__)
        return False
