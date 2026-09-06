"""The installation's mail server: read it, change it, try it out."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from ..deps import AdminUser, DbSession, error
from ..schemas import MailTestBody, SmtpBody
from ..services import mail

router = APIRouter(prefix="/api/v1/settings/mail", tags=["system"])

logger = logging.getLogger("nexdeck.mail")


@router.get("", summary="Read the mail server settings")
def read(admin: AdminUser, db: DbSession) -> dict:
    """The password comes back masked; it never leaves the server."""
    return mail.public(db)


@router.put("", summary="Change the mail server settings")
def write(body: SmtpBody, admin: AdminUser, db: DbSession) -> dict:
    try:
        saved = mail.save(db, body.model_dump())
        # No values: the settings hold the password of the mail account.
        logger.info("The mail server settings were changed by %s.", admin.username)
        return saved
    except mail.MailError as failure:
        raise error(failure.code, failure.message) from failure


@router.post("/test", summary="Send a test message")
async def test(body: MailTestBody, admin: AdminUser, db: DbSession) -> dict:
    """Goes to the address given, or to the administrator's own."""
    to_address = body.to_address.strip() or admin.email
    if not to_address:
        raise error("no_recipient", "Give an address, or store one in your profile first.")
    config = mail.stored(db)
    try:
        # Blocking network work; the event loop must not wait on it.
        await asyncio.to_thread(mail.send, config, to_address, "nexdeck test message", "This is the test message from your nexdeck installation. The mail server works.")
    except mail.MailError as failure:
        raise error(failure.code, failure.message) from failure
    logger.info("A test message was sent to %s by %s.", to_address, admin.username)
    return {"sent": True, "to_address": to_address}
