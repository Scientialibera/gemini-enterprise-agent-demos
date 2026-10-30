"""Send a report email from a Gmail account, using an app password from Secret Manager.

Gemini Enterprise's Gmail connector needs a Google Workspace account; this path
works with any Gmail account that has 2-Step Verification and an app password.
The password never reaches the runtime's environment: ``GMAIL_APP_PASSWORD_SECRET``
names the secret, read under the agent's own identity.
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from gemini_shared.secrets import read_secret

LOGGER = logging.getLogger(__name__)

SENDER_ENV = "GMAIL_SENDER"
SENDER_NAME_ENV = "GMAIL_SENDER_NAME"
PASSWORD_SECRET_ENV = "GMAIL_APP_PASSWORD_SECRET"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
MAX_RECIPIENTS = 10
EMAIL_PATTERN = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    content: bytes
    mime_type: str


def clean_recipients(recipients: list[str] | str) -> list[str]:
    """Split, trim and validate addresses; raise ValueError on a bad one."""
    if isinstance(recipients, str):
        recipients = re.split(r"[,;\s]+", recipients)
    cleaned = []
    for address in recipients:
        address = address.strip().strip("<>").lower()
        if not address:
            continue
        if not EMAIL_PATTERN.fullmatch(address):
            raise ValueError(f"'{address}' is not a valid email address.")
        if address not in cleaned:
            cleaned.append(address)
    if not cleaned:
        raise ValueError("At least one recipient email address is required.")
    if len(cleaned) > MAX_RECIPIENTS:
        raise ValueError(f"At most {MAX_RECIPIENTS} recipients are allowed.")
    return cleaned


def send_email(
    recipients: list[str] | str,
    subject: str,
    html_body: str,
    text_body: str,
    attachments: tuple[Attachment, ...] = (),
) -> dict[str, object]:
    """Send one message; return the recipients and Message-ID."""
    to = clean_recipients(recipients)
    sender = os.getenv(SENDER_ENV, "").strip()
    if not sender:
        raise RuntimeError(f"{SENDER_ENV} must name the Gmail address that sends reports.")
    password = read_secret(PASSWORD_SECRET_ENV).replace(" ", "")

    message = EmailMessage()
    message["From"] = formataddr((os.getenv(SENDER_NAME_ENV, "").strip() or sender, sender))
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message_id = make_msgid(domain=sender.split("@")[-1])
    message["Message-ID"] = message_id
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    for attachment in attachments:
        main, _, sub = attachment.mime_type.partition("/")
        message.add_attachment(
            attachment.content, maintype=main, subtype=sub, filename=attachment.filename
        )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=60) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)
    LOGGER.info("Report email sent to %s recipient(s)", len(to))
    return {"recipients": to, "message_id": message_id.strip("<>")}
