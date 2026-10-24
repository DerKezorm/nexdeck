"""Maintenance: a connection or one app tile that is expected to be away for a while.

An administrator says "the Synology is updated until ten", and for that long
nothing about it is told: no notice in the bell, nothing on a channel, no
outage opened. The cards keep showing what they read, with a grey line that
says why nobody was told. The availability bars draw the stretch grey and
leave it out of the share of time a service was up.

⚠️ One thing stays loud: a service that rejects its credentials. Somebody
who updates a NAS expects it to be gone for a while, not to come back with
a token that no longer works, and that is exactly what a quiet hour would
otherwise hide until the next morning.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Integration, Maintenance, Page, Widget, utcnow

logger = logging.getLogger("nexdeck.maintenance")

#: The longest stretch that can be set at once. A week covers a holiday with
#: the lab switched off; anything longer is a connection to switch off or mute.
LONGEST = timedelta(days=7)
#: News that is told during maintenance all the same.
STAYS_LOUD = frozenset({"auth_rejected"})


class Refused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now(now: datetime | None) -> datetime:
    return now if now is not None else utcnow()


def active(db: Session, now: datetime | None = None) -> list[Maintenance]:
    """Every stretch that is running right now."""
    moment = _now(now)
    return list(db.scalars(
        select(Maintenance).where(Maintenance.starts_at <= moment, Maintenance.ends_at > moment).order_by(Maintenance.ends_at)
    ))


def covering(db: Session, *, integration_id: int | None = None, widget_id: int | None = None,
             now: datetime | None = None) -> Maintenance | None:
    """The running stretch for this connection or this tile, the one that ends last."""
    wanted = []
    if integration_id is not None:
        wanted.append(Maintenance.integration_id == integration_id)
    if widget_id is not None:
        wanted.append(Maintenance.widget_id == widget_id)
    if not wanted:
        return None
    moment = _now(now)
    return db.scalar(
        select(Maintenance).where(or_(*wanted), Maintenance.starts_at <= moment, Maintenance.ends_at > moment)
        .order_by(Maintenance.ends_at.desc()).limit(1)
    )


def is_quiet(db: Session, event: str, *, integration_id: int | None = None, widget_id: int | None = None) -> bool:
    """Whether news of this kind about this connection or tile is held back now."""
    if event in STAYS_LOUD:
        return False
    return covering(db, integration_id=integration_id, widget_id=widget_id) is not None


def until_by_card(db: Session, widgets: list[Widget], now: datetime | None = None) -> dict[int, Maintenance]:
    """The running stretch of each card that is in one, the one that ends last.

    One query for a whole board: a card is in maintenance through its own
    stretch (an app tile) or through the one of its connection.
    """
    running = active(db, now)
    if not running:
        return {}
    by_integration: dict[int, Maintenance] = {}
    by_widget: dict[int, Maintenance] = {}
    for row in running:
        if row.integration_id is not None and (row.integration_id not in by_integration or row.ends_at > by_integration[row.integration_id].ends_at):
            by_integration[row.integration_id] = row
        if row.widget_id is not None and (row.widget_id not in by_widget or row.ends_at > by_widget[row.widget_id].ends_at):
            by_widget[row.widget_id] = row
    out: dict[int, Maintenance] = {}
    for widget in widgets:
        mine = [one for one in (by_widget.get(widget.id), by_integration.get(widget.integration_id or -1)) if one is not None]
        if mine:
            out[widget.id] = max(mine, key=lambda one: one.ends_at)
    return out


def view(db: Session, row: Maintenance, now: datetime | None = None) -> dict[str, Any]:
    moment = _now(now)
    name = ""
    if row.integration_id is not None:
        integration = db.get(Integration, row.integration_id)
        name = integration.name if integration is not None else ""
    elif row.widget_id is not None:
        widget = db.get(Widget, row.widget_id)
        name = (widget.title or "App tile") if widget is not None else ""
    return {
        "id": row.id,
        "integration_id": row.integration_id,
        "widget_id": row.widget_id,
        "name": name,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat(),
        "active": row.starts_at <= moment < row.ends_at,
    }


def start(db: Session, *, integration_id: int | None, widget_id: int | None, ends_at: datetime,
          user_id: int | None, now: datetime | None = None) -> Maintenance:
    """Begin a stretch now, or move the end of the one already running for the same thing."""
    moment = _now(now)
    if (integration_id is None) == (widget_id is None):
        raise Refused("bad_target", "Name either a connection or an app tile.")
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=UTC)
    if ends_at <= moment + timedelta(minutes=1):
        raise Refused("ends_in_the_past", "The end has to lie in the future.")
    if ends_at - moment > LONGEST:
        raise Refused("too_long", "Maintenance lasts a week at most. A connection that is away for longer can be switched off.")
    if integration_id is not None and db.get(Integration, integration_id) is None:
        raise Refused("not_found", "No such connection.")
    if widget_id is not None:
        widget = db.get(Widget, widget_id)
        # Only an app tile stands on its own; any other card is in maintenance with its connection.
        if widget is None or widget.kind != "core.app":
            raise Refused("not_an_app", "Only an app tile has a maintenance of its own; other cards follow their connection.")
    running = covering(db, integration_id=integration_id, widget_id=widget_id, now=moment)
    if running is not None and running.integration_id == integration_id and running.widget_id == widget_id:
        running.ends_at = ends_at
        return running
    row = Maintenance(integration_id=integration_id, widget_id=widget_id, starts_at=moment, ends_at=ends_at, created_by=user_id)
    db.add(row)
    db.flush()
    return row


def end(row: Maintenance, now: datetime | None = None) -> None:
    """Stop a stretch now. One that is over already stays as it was."""
    moment = _now(now)
    if row.ends_at > moment:
        row.ends_at = max(moment, row.starts_at)


def boards_touched(db: Session, row: Maintenance) -> set[int]:
    """The boards with a card this stretch is about, so each fetches itself again."""
    query = select(Page.board_id).join(Widget, Widget.page_id == Page.id)
    if row.integration_id is not None:
        query = query.where(Widget.integration_id == row.integration_id)
    else:
        query = query.where(Widget.id == row.widget_id)
    return set(db.scalars(query))


def spans_by_widget(db: Session, widgets: dict[int, int | None], start: float, end: float) -> dict[int, list[tuple[float, float]]]:
    """For each card (``{widget id: connection id}``), the stretches between ``start`` and ``end``, merged."""
    if not widgets:
        return {}
    integrations = {one for one in widgets.values() if one is not None}
    rows = db.execute(
        select(Maintenance.integration_id, Maintenance.widget_id, Maintenance.starts_at, Maintenance.ends_at).where(
            or_(Maintenance.widget_id.in_(list(widgets)), Maintenance.integration_id.in_(list(integrations) or [-1])),
            Maintenance.ends_at > datetime.fromtimestamp(start, UTC),
            Maintenance.starts_at < datetime.fromtimestamp(end, UTC),
        )
    ).all()
    out: dict[int, list[tuple[float, float]]] = {}
    for widget_id, integration_id in widgets.items():
        mine = sorted(
            (max(row.starts_at.timestamp(), start), min(row.ends_at.timestamp(), end))
            for row in rows
            if row.widget_id == widget_id or (integration_id is not None and row.integration_id == integration_id)
        )
        merged: list[tuple[float, float]] = []
        for began, until in mine:
            if merged and began <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], until))
            else:
                merged.append((began, until))
        if merged:
            out[widget_id] = merged
    return out


def overlap(spans: list[tuple[float, float]], left: float, right: float) -> float:
    """How much of ``left`` to ``right`` the (merged) spans cover."""
    return sum(max(0.0, min(right, until) - max(left, began)) for began, until in spans)
