"""The installation's mail server.

One place where nexdeck itself can send an e-mail, as opposed to the e-mail
notification channel: a channel belongs to whoever set it up and carries its
own server, while a password reset has to go out before anyone is signed in.

The password is stored encrypted, like every other secret, and never leaves
the server: the settings hand out ``********`` and take it back unchanged.
"""

from __future__ import annotations

import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from sqlalchemy.orm import Session as DbSessionType

from ..crypto import decrypt, encrypt
from ..models import Setting

logger = logging.getLogger("nexdeck.mail")

KEY = "smtp"
TIMEOUT = 20.0
MASK = "********"

#: Good enough to catch a typo, not a parser for the mail standard.
ADDRESS = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")

DEFAULTS: dict[str, Any] = {
    "host": "",
    "port": 587,
    "security": "starttls",
    "username": "",
    "password": "",
    "from_address": "",
    "from_name": "nexdeck",
}


class MailError(Exception):
    """Sending did not work; the router turns it into an answer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def valid_address(value: str) -> bool:
    return bool(ADDRESS.match(value.strip()))


def stored(db: DbSessionType, key: str = KEY) -> dict[str, Any]:
    row = db.get(Setting, key)
    return {**DEFAULTS, **(dict(row.value) if row is not None else {})}


def public(db: DbSessionType) -> dict[str, Any]:
    """What the settings page gets: everything but the password itself."""
    config = stored(db)
    config["password"] = MASK if config.get("password") else ""
    config["configured"] = bool(config.get("host"))
    return config


def save(db: DbSessionType, incoming: dict[str, Any]) -> dict[str, Any]:
    config = stored(db)
    for field, value in incoming.items():
        if field not in DEFAULTS:
            continue
        if field == "password":
            # Nothing, or the mask coming back: keep what is stored.
            if value in (None, "", MASK):
                continue
            config["password"] = encrypt(str(value))
        else:
            config[field] = value
    for field in ("host", "username", "from_address", "from_name"):
        config[field] = str(config[field]).strip()
    if config["host"] and not config["from_address"]:
        raise MailError("no_sender", "A from address is needed to send mail.")
    if config["from_address"] and not valid_address(config["from_address"]):
        raise MailError("bad_address", "The from address does not look like an e-mail address.")
    db.merge(Setting(key=KEY, value=config))
    db.commit()
    return public(db)


def configured(db: DbSessionType) -> bool:
    return bool(stored(db).get("host"))


def send(config: dict[str, Any], to_address: str, subject: str, body: str) -> None:
    """Send one mail through the configured server.

    Takes the configuration, not the database session: this blocks on the
    network and belongs in a worker thread, and a session must not travel
    into one. Read it with ``stored`` first.
    """
    if not config["host"]:
        raise MailError("not_configured", "No mail server is set up yet.")
    if not valid_address(to_address):
        raise MailError("bad_address", "That does not look like an e-mail address.")

    mail = EmailMessage()
    mail["Subject"] = subject
    mail["From"] = formataddr((config["from_name"] or "nexdeck", config["from_address"]))
    mail["To"] = to_address
    mail.set_content(body)

    port = int(config["port"] or 587)
    security = config["security"] or "starttls"
    try:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(config["host"], port, timeout=TIMEOUT)
        else:
            server = smtplib.SMTP(config["host"], port, timeout=TIMEOUT)
        with server:
            if security == "starttls":
                server.starttls()
            if config["username"]:
                server.login(config["username"], decrypt(config["password"]) if config["password"] else "")
            server.send_message(mail)
    except (OSError, smtplib.SMTPException) as failure:
        logger.warning("Sending mail through %s failed: %s", config["host"], failure)
        raise MailError("send_failed", f"The mail server refused the message: {failure}") from failure
