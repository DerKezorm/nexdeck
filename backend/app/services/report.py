"""The daily report: what happened since yesterday, and what is still red.

Two ways out, from one summary. A card ("Daily report") shows it on a board,
for the board's owner like the attention card. A message goes once a day, at
the time set under Notifications, to every channel that subscribed to "The
daily report". Nobody gets one without subscribing: a message every morning
that was never asked for is the quickest way to make all of them unread.

The summary reads the chronicle and the bell; it asks no service anything.

Also here, because it runs on the same clock: every six hours each connection
is asked which version it runs, so a service that was updated shows up in the
chronicle even when nobody opened the page that lists the versions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.base import Context
from ..db import db_session
from ..models import (
    Integration,
    Notice,
    NotificationChannel,
    Page,
    Setting,
    Subscription,
    User,
    Widget,
    utcnow,
)
from . import chronicle
from .state import level_of, live

logger = logging.getLogger("nexdeck.report")

SETTING = "daily_report"
DEFAULT_TIME = "07:00"
#: How often the running versions are asked, in seconds.
VERSION_ROUND = 6 * 3600


def stored(db: Session) -> dict[str, Any]:
    setting = db.get(Setting, SETTING)
    value = dict(setting.value or {}) if setting is not None else {}
    return {"time": value.get("time") or DEFAULT_TIME, "sent": value.get("sent") or ""}


def store(db: Session, **changes: Any) -> dict[str, Any]:
    value = {**stored(db), **changes}
    setting = db.get(Setting, SETTING)
    if setting is None:
        db.add(Setting(key=SETTING, value=value))
    else:
        setting.value = value
    return value


def parse_time(text: str) -> tuple[int, int] | None:
    try:
        hours, minutes = (int(part) for part in str(text).split(":"))
    except ValueError:
        return None
    return (hours, minutes) if 0 <= hours < 24 and 0 <= minutes < 60 else None


# -- the summary ----------------------------------------------------------------


def summary(db: Session, *, user: User | None = None, boards: set[int] | None = None, owner_id: int | None = None,
            hours: int = 24) -> dict[str, Any]:
    """What happened in the last ``hours`` and what is red now, as one account or as some boards see it."""
    since = utcnow() - timedelta(hours=hours)
    lines = chronicle.query(db, user=user, boards=boards, since=since, limit=500,
                            kinds=("card", "outage", "version", "container_recreated", "container_restarted"))
    outages = sorted({line.name for line in lines if line.kind == "outage"})
    red = sorted({line.name for line in lines if line.kind == "card" and line.after == "bad"})
    versions = [{"name": line.name, "before": line.before, "after": line.after} for line in lines if line.kind == "version"]
    containers = sorted({line.name for line in lines if line.kind == "container_recreated"})
    restarted = sorted({line.name for line in lines if line.kind == "container_restarted"})
    reader = user.id if user is not None else owner_id
    backups: list[str] = []
    if reader is not None:
        backups = [notice.title for notice in db.scalars(
            select(Notice).where(Notice.user_id == reader, Notice.created_at >= since,
                                 Notice.event.in_(("backup_failed", "backup_stale"))).order_by(Notice.created_at.desc()).limit(10))]
    return {
        "since": since.isoformat(), "outages": outages, "red": red, "versions": versions,
        "containers": containers, "restarted": restarted, "backups": backups,
        "now_red": now_red(db, user=user, boards=boards),
    }


def now_red(db: Session, *, user: User | None = None, boards: set[int] | None = None) -> list[str]:
    """The cards that are red right now, on the boards this account or this card looks at."""
    from ..deps import board_permission
    from ..models import Board

    if boards is None:
        boards = {board.id for board in db.scalars(select(Board)) if user is not None and board_permission(db, board, user) is not None}
    names = []
    for widget_id, title, kind in db.execute(
        select(Widget.id, Widget.title, Widget.kind).join(Page, Widget.page_id == Page.id).where(Page.board_id.in_(list(boards) or [-1]))
    ):
        data = live.get(widget_id)
        if kind not in ("core.problems", "core.report", "core.chronicle") and data is not None and level_of(data) == "bad":
            names.append(title or kind)
    return sorted(set(names))


def quiet(found: dict[str, Any]) -> bool:
    return not any(found[key] for key in ("outages", "red", "versions", "containers", "restarted", "backups", "now_red"))


def words(found: dict[str, Any]) -> tuple[str, str]:
    """The message: a title that says the most, and a line for each kind of news."""
    parts = []
    if found["outages"]:
        parts.append(f"{len(found['outages'])} outage(s)")
    if found["now_red"]:
        parts.append(f"{len(found['now_red'])} still red")
    if found["versions"] or found["containers"]:
        parts.append(f"{len(found['versions']) + len(found['containers'])} update(s)")
    title = "Daily report: " + (", ".join(parts) if parts else "all quiet")
    lines = []
    if found["now_red"]:
        lines.append("Red now: " + ", ".join(found["now_red"]))
    if found["outages"]:
        lines.append("Outages: " + ", ".join(found["outages"]))
    if found["red"]:
        lines.append("Turned red: " + ", ".join(found["red"]))
    if found["backups"]:
        lines.append("Backups: " + "; ".join(found["backups"]))
    if found["versions"]:
        lines.append("New versions: " + ", ".join(f"{one['name']} {one['before']} → {one['after']}" for one in found["versions"]))
    if found["containers"]:
        lines.append("Containers created anew: " + ", ".join(found["containers"]))
    if found["restarted"]:
        lines.append("Containers restarted: " + ", ".join(found["restarted"]))
    if not lines:
        lines.append("Nothing happened since yesterday, and nothing is red.")
    return title, "\n".join(lines)


# -- sending ----------------------------------------------------------------------


def due(now: datetime, setting: dict[str, Any]) -> bool:
    """Whether today's report is to go: the time has come and today's has not gone yet."""
    when = parse_time(setting["time"]) or (7, 0)
    return (now.hour, now.minute) >= when and setting["sent"] != now.date().isoformat()


async def send_due(now: datetime | None = None) -> int:
    """Send today's report to whoever subscribed, once. Returns how many accounts got one."""
    from .channels import send_to_channel
    from .notify import Message

    moment = now or datetime.now().astimezone()
    with db_session() as db:
        setting = stored(db)
        if not due(moment, setting):
            return 0
        store(db, sent=moment.date().isoformat())
        jobs: list[tuple[int, str, str]] = []
        channels = list(db.scalars(
            select(NotificationChannel).join(Subscription, Subscription.channel_id == NotificationChannel.id)
            .where(NotificationChannel.enabled.is_(True), Subscription.event == "daily_report")
        ))
        for user_id in sorted({channel.user_id for channel in channels}):
            user = db.get(User, user_id)
            if user is None or user.disabled:
                continue
            title, body = words(summary(db, user=user))
            jobs.extend((channel.id, title, body) for channel in channels if channel.user_id == user_id)
    for channel_id, title, body in jobs:
        try:
            await send_to_channel(channel_id, Message(event="daily_report", title=title, body=body, level="info"))
        except Exception as failure:  # noqa: BLE001 - one channel that fails must not keep the report from the others
            logger.warning("The daily report could not go out on channel %s: %s", channel_id, failure)
    if jobs:
        logger.info("The daily report went to %d channel(s).", len(jobs))
    return len({channel for channel, _title, _body in jobs})


async def read_versions() -> None:
    """Ask every connection which version it runs; the chronicle notes a change."""
    from ..adapters import get_adapter
    from . import versions
    from .collector import collector

    with db_session() as db:
        connections = [
            (one.id, one.kind)
            for one in db.scalars(select(Integration).where(Integration.enabled.is_(True), Integration.demo.is_(False)))
            if one.kind in _known_kinds() and get_adapter(one.kind).needs_integration
        ]
    if connections:
        await versions.read_many(connections, collector.resolve_integration, Context(collector.client, cache={}), allowed=False)


def _known_kinds() -> set[str]:
    from ..adapters import all_adapters

    return {adapter.kind for adapter in all_adapters() if adapter.kind != "core"}


#: How often the forecasts are worked out (roadmap M4); the first round comes a few minutes after the start.
FORECAST_ROUND = 3600


async def rounds() -> None:
    """Once a minute: the daily report when it is due and the MCP requests that ran out; every hour: the forecasts; every six hours: the versions."""
    last_versions = 0.0
    loop = asyncio.get_running_loop()
    # The first round once the cards have answered at least once.
    last_forecast = loop.time() - FORECAST_ROUND + 180
    while True:
        await asyncio.sleep(60)
        if loop.time() - last_forecast >= FORECAST_ROUND:
            last_forecast = loop.time()
            try:
                from . import forecast

                # ⚠️ In a thread: it reads a month of hour rows for every card that fills up.
                await asyncio.to_thread(forecast.round_once)
            except Exception:  # noqa: BLE001
                logger.exception("Working out the forecasts failed.")
            try:
                from . import dependencies

                await dependencies.discover()
            except Exception:  # noqa: BLE001
                logger.exception("Finding what runs where failed.")
        try:
            await send_due()
        except Exception:  # noqa: BLE001
            logger.exception("The daily report failed.")
        try:
            from . import mcp

            # Requests of AI programs that nobody answered run out after ten minutes, read or not.
            with db_session() as db:
                mcp.expire(db)
        except Exception:  # noqa: BLE001
            logger.exception("Ending the MCP requests that ran out failed.")
        if loop.time() - last_versions >= VERSION_ROUND:
            last_versions = loop.time()
            try:
                await read_versions()
            except Exception:  # noqa: BLE001
                logger.exception("Reading the versions failed.")

