"""Notices and notifications.

``emit`` writes a notice into the in-app centre, pushes it to open browsers
and hands it to every channel that subscribed to the event. Delivery runs in
the background; a failing channel records its error and never blocks the
caller.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ..db import db_session
from ..models import Notice, NotificationChannel, Role, Subscription, User
from .sse import hub, user_topic

logger = logging.getLogger("nexdeck.notify")

EVENTS: dict[str, str] = {
    "outage": "A service stopped answering",
    "recovery": "A service is back",
    "action_failed": "An action failed",
    "action_done": "An action succeeded",
    "request_new": "A new media request",
    "download_done": "A download finished",
    "test": "Test message",
}


@dataclass(frozen=True)
class Message:
    event: str
    title: str
    body: str
    level: str = "info"
    link: str = ""


def emit(event: str, title: str, body: str = "", *, level: str = "info", link: str = "",
         user_ids: list[int] | None = None) -> None:
    """Create notices and dispatch channels. Safe to call from anywhere in the loop."""
    message = Message(event=event, title=title[:200], body=body, level=level, link=link)
    targets: list[int] = []
    with db_session() as db:
        if user_ids is None:
            targets = list(db.scalars(select(User.id).where(User.role == Role.admin.value, User.disabled.is_(False))))
        else:
            targets = list(user_ids)
        notices = []
        for user_id in targets:
            notice = Notice(user_id=user_id, event=event, level=level, title=message.title, body=body, link=link)
            db.add(notice)
            notices.append(notice)
        db.flush()
        payloads = [(n.user_id, notice_payload(n)) for n in notices]
    for user_id, payload in payloads:
        hub.publish(user_topic(user_id), "notice", payload)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(dispatch(message, targets))


def notice_payload(notice: Notice) -> dict[str, Any]:
    return {
        "id": notice.id,
        "event": notice.event,
        "level": notice.level,
        "title": notice.title,
        "body": notice.body,
        "link": notice.link,
        "created_at": notice.created_at.isoformat() if notice.created_at else None,
        "read_at": notice.read_at.isoformat() if notice.read_at else None,
    }


async def dispatch(message: Message, user_ids: list[int]) -> None:
    from .channels import send_to_channel

    with db_session() as db:
        channels = list(
            db.scalars(
                select(NotificationChannel)
                .join(Subscription, Subscription.channel_id == NotificationChannel.id)
                .where(
                    NotificationChannel.enabled.is_(True),
                    NotificationChannel.user_id.in_(user_ids),
                    Subscription.event == message.event,
                )
                .distinct()
            )
        )
        jobs = [(c.id, c.kind, c.user_id) for c in channels]
    for channel_id, _kind, _user in jobs:
        try:
            await send_to_channel(channel_id, message)
        except Exception as error:  # noqa: BLE001
            logger.warning("Channel %s failed: %s", channel_id, error)
            with db_session() as db:
                channel = db.get(NotificationChannel, channel_id)
                if channel is not None:
                    channel.last_error = str(error)[:300]
