"""Maintenance that comes back every week (issue #62).

"Every Sunday from 03:00 for two hours the NAS makes its backup and restarts."
A plan says that once, and shortly before every start it writes an ordinary
maintenance stretch for that time. Everything that already knows maintenance
(the bell, the channels, the outages, the availability bars, the chronicle
and the line on the card) treats it like one set by hand, and "End now" on
the card ends this week's stretch without touching the plan.

The stretch is written ``LEAD`` ahead, because the rounds come every half minute
and a service that goes down in the first seconds of its window must already
be quiet. It holds nothing back before its start: every query asks for
``starts_at <= now``.

The time is the clock of the browser it was set in. A server in a container
often runs on UTC while the person who sets "03:00" means their own night,
and the zone keeps it at 03:00 across summer time as well.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Maintenance, MaintenancePlan, utcnow
from .maintenance import Refused, boards_touched, check_target, target_name

logger = logging.getLogger("nexdeck.maintenance")

#: How long before its start a stretch is written: several rounds of half a minute, so a slow one does not make it late.
LEAD = timedelta(seconds=150)
#: The longest a weekly window may last. Longer, and it would run into itself.
LONGEST_MINUTES = 24 * 60
#: How many plans one connection or tile may have; more is a sign of a mistake.
MOST_PLANS = 10
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def zone_of(name: str) -> tzinfo | None:
    """The zone of that name, or None for the server's own clock."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _at(day: date, starts: str, zone: tzinfo | None) -> datetime:
    hour, minute = (int(part) for part in starts.split(":"))
    naive = datetime.combine(day, time(hour, minute))
    # Without a zone the server's own local time, which is what the daily report goes by too.
    return naive.replace(tzinfo=zone) if zone is not None else naive.astimezone()


def windows(plan: MaintenancePlan, first: date, last: date) -> list[tuple[datetime, datetime]]:
    """The windows of a plan that begin on the days from ``first`` to ``last``, in the plan's zone."""
    zone = zone_of(plan.zone)
    out = []
    day = first
    while day <= last:
        if day.weekday() in (plan.days or []):
            began = _at(day, plan.starts, zone)
            out.append((began, began + timedelta(minutes=plan.minutes)))
        day += timedelta(days=1)
    return out


def _today(plan: MaintenancePlan, moment: datetime) -> date:
    zone = zone_of(plan.zone)
    return (moment.astimezone(zone) if zone is not None else moment.astimezone()).date()


def due(plan: MaintenancePlan, now: datetime) -> list[tuple[datetime, datetime]]:
    """The windows that have begun or begin within ``LEAD``, and are not over."""
    today = _today(plan, now)
    # A window lasts a day at most, so yesterday's may still run.
    return [(began, ends) for began, ends in windows(plan, today - timedelta(days=1), today + timedelta(days=1))
            if began <= now + LEAD and ends > now]


def next_window(plan: MaintenancePlan, now: datetime) -> tuple[datetime, datetime] | None:
    """The next window that has not begun yet."""
    today = _today(plan, now)
    ahead = [window for window in windows(plan, today, today + timedelta(days=8)) if window[0] > now]
    return ahead[0] if ahead else None


def write_due(db: Session, now: datetime | None = None) -> list[Maintenance]:
    """Write the stretch of every window that is due and not written yet. Returns the new ones.

    A window is written once: a stretch ended early with "End now" stays ended
    and is not written again.
    """
    moment = now or utcnow()
    made = []
    for plan in db.scalars(select(MaintenancePlan)):
        for began, ends in due(plan, moment):
            written = db.scalar(select(Maintenance.id).where(
                Maintenance.plan_id == plan.id,
                Maintenance.starts_at > began - timedelta(seconds=1),
                Maintenance.starts_at < began + timedelta(seconds=1),
            ).limit(1))
            if written is not None:
                continue
            row = Maintenance(integration_id=plan.integration_id, widget_id=plan.widget_id, starts_at=began,
                              ends_at=ends, created_by=plan.created_by, plan_id=plan.id)
            db.add(row)
            made.append(row)
    if made:
        db.flush()
    return made


#: The planned stretches whose beginning was told: a chronicle line and a fresh look of the boards, once each.
_told: set[int] = set()
#: When this process began. A stretch that was running before it was told by the one before.
_since_boot = utcnow()


def tell_begun(db: Session, made: list[Maintenance], now: datetime | None = None) -> set[int]:
    """Give each planned stretch that holds now its chronicle line, once. Returns the boards to look again.

    Called by the rounds and right after a plan is made or changed, so a
    plan set inside its window holds at once. A stretch that ran before this
    process started was told before the restart, unless it was only written
    now, because nexdeck was not running when it began.
    """
    from . import chronicle

    moment = now or utcnow()
    running = list(db.scalars(select(Maintenance).where(
        Maintenance.plan_id.is_not(None), Maintenance.starts_at <= moment, Maintenance.ends_at > moment,
    ).order_by(Maintenance.starts_at)))
    fresh = {row.id for row in made}
    boards: set[int] = set()
    for row in running:
        if row.id in _told:
            continue
        _told.add(row.id)
        if row.starts_at < _since_boot and row.id not in fresh:
            continue
        name = target_name(db, integration_id=row.integration_id, widget_id=row.widget_id)
        chronicle.record("maintenance", level="info", integration_id=row.integration_id, widget_id=row.widget_id,
                         name=name, after=row.ends_at.isoformat(), at=row.starts_at, db=db)
        logger.info("Weekly maintenance for %r began, until %s.", name, row.ends_at.isoformat())
        boards |= boards_touched(db, row)
    _told.intersection_update({row.id for row in running})
    return boards


def publish(boards: set[int]) -> None:
    """The cards fetch themselves again and show the line, now that the stretch holds."""
    from .sse import board_topic, hub

    for board_id in sorted(boards):
        hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})


def _clean(days: list[int], starts: str, minutes: int, zone: str) -> tuple[list[int], str, int, str]:
    wanted = sorted(set(days))
    if not wanted or any(day not in range(7) for day in wanted):
        raise Refused("bad_days", "Choose at least one day of the week.")
    if not _CLOCK.match(starts or ""):
        raise Refused("bad_time", "The start is a time like 03:00.")
    if not 1 <= minutes <= LONGEST_MINUTES:
        raise Refused("bad_length", "A weekly maintenance lasts from one minute to a day.")
    zone = (zone or "").strip()
    if zone and zone_of(zone) is None:
        raise Refused("bad_zone", f"The time zone {zone!r} is not known here.")
    return wanted, starts, minutes, zone


def create(db: Session, *, integration_id: int | None, widget_id: int | None, days: list[int], starts: str,
           minutes: int, zone: str, user_id: int | None) -> MaintenancePlan:
    check_target(db, integration_id=integration_id, widget_id=widget_id)
    days, starts, minutes, zone = _clean(days, starts, minutes, zone)
    if len(for_target(db, integration_id=integration_id, widget_id=widget_id)) >= MOST_PLANS:
        raise Refused("too_many_plans", f"There are {MOST_PLANS} weekly maintenances for this already.")
    plan = MaintenancePlan(integration_id=integration_id, widget_id=widget_id, days=days, starts=starts,
                           minutes=minutes, zone=zone, created_by=user_id)
    db.add(plan)
    db.flush()
    return plan


def _drop_unbegun(db: Session, plan: MaintenancePlan, now: datetime) -> None:
    """Stretches of the plan written ahead that have not begun: they belong to the old times."""
    db.execute(delete(Maintenance).where(Maintenance.plan_id == plan.id, Maintenance.starts_at > now))


def change(db: Session, plan: MaintenancePlan, *, days: list[int], starts: str, minutes: int, zone: str,
           now: datetime | None = None) -> MaintenancePlan:
    """New times for a plan. A window running now runs to its end; the next one follows the new times."""
    plan.days, plan.starts, plan.minutes, plan.zone = _clean(days, starts, minutes, zone)
    _drop_unbegun(db, plan, now or utcnow())
    db.flush()
    return plan


def remove(db: Session, plan: MaintenancePlan, now: datetime | None = None) -> None:
    """Drop a plan. A window running now runs to its end, and the past ones stay for the availability bars."""
    _drop_unbegun(db, plan, now or utcnow())
    db.delete(plan)
    db.flush()


def for_target(db: Session, *, integration_id: int | None = None, widget_id: int | None = None) -> list[MaintenancePlan]:
    query = select(MaintenancePlan).order_by(MaintenancePlan.id)
    if integration_id is not None:
        query = query.where(MaintenancePlan.integration_id == integration_id)
    if widget_id is not None:
        query = query.where(MaintenancePlan.widget_id == widget_id)
    return list(db.scalars(query))


def view(db: Session, plan: MaintenancePlan, now: datetime | None = None) -> dict[str, Any]:
    upcoming = next_window(plan, now or utcnow())
    return {
        "id": plan.id,
        "integration_id": plan.integration_id,
        "widget_id": plan.widget_id,
        "name": target_name(db, integration_id=plan.integration_id, widget_id=plan.widget_id),
        "days": list(plan.days or []),
        "starts": plan.starts,
        "minutes": plan.minutes,
        "zone": plan.zone,
        "next_starts_at": upcoming[0].isoformat() if upcoming else None,
        "next_ends_at": upcoming[1].isoformat() if upcoming else None,
    }


#: How often the plans are looked at. A round of their own, so a long forecast never makes a window late.
ROUND_SECONDS = 30


async def rounds() -> None:
    """Every half minute: write what is due, tell what began.

    The first round comes half a minute after the start, like the other
    rounds, which wait as well. ``LEAD`` is long enough that a window is
    still written before it begins, unless nexdeck starts in its last half
    minute before.
    """
    import asyncio

    while True:
        await asyncio.sleep(ROUND_SECONDS)
        try:
            await asyncio.to_thread(round_once)
        except Exception:  # noqa: BLE001 - the next round tries again; a plan must not stop the loop
            logger.exception("The weekly maintenance round failed.")


def round_once(now: datetime | None = None) -> set[int]:
    """One round: write what is due and tell what began. Returns the boards that were told to look again."""
    from ..db import db_session

    moment = now or utcnow()
    with db_session() as db:
        boards = tell_begun(db, write_due(db, moment), moment)
    publish(boards)
    return boards
