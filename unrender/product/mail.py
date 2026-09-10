"""TLS-only transactional account email; links keep secrets out of HTTP logs."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from unrender.product.config import Settings

logger = logging.getLogger("unrender.mail")


def send_account_email(settings: Settings, recipient: str, purpose: str, token: str) -> bool:
    action = "Verify your email" if purpose == "verify" else "Reset your password"
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = f"Unrender: {action.lower()}"
    message.set_content(
        f"{action} for your Unrender workspace:\n\n"
        f"{settings.base_url}/account#account={purpose}&token={token}\n\n"
        "This link expires in 30 minutes and can be used once. "
        "If you did not request it, ignore this email."
    )
    context = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, 465, timeout=10, context=context) as smtp:
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, 587, timeout=10) as smtp:
                smtp.starttls(context=context)
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        # A generic response avoids revealing whether an address has an account.
        logger.error("account_email_delivery_failed")
        return False
    return True
