"""Forecasts (roadmap M4): when a volume is full, when a number reaches its red, whether a backup gets slower.

A straight line through the last 30 days of hour rows, carried on to the
limit. No learning, no seasons: a volume that fills by a steady amount a
day is the case that matters, and a line says it plainly enough to be
checked by eye on the card's chart.

Three kinds:

* ``full``: a share of a volume, pool, disk or datastore reaches 100 %
  (``history.FILL_ROWS`` and ``FILL_METRICS``).
* ``level``: a card's number reaches the "Red from" line drawn for it, or
  "Yellow from" where only that one is drawn.
* ``slower``: a backup takes longer week by week (``duration:`` rows).

A forecast is shown on the card while it is within half a year and the line
fits the points well; one that fits badly says nothing rather than guess.
``full`` and ``level`` are told once when they fall under 14 days, through
the bell, the channels and the chronicle, and again only after they rose
above 21 days.

Worked out once an hour (``round``), never on a fetch: a fetch reads the
result from memory (``of``).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.base import level_lines, low_is_bad
from ..db import db_session
from ..models import Integration, Setting, Widget
from . import chronicle, history
from .state import live

logger = logging.getLogger("nexdeck.forecast")

WINDOW_DAYS = 30
#: Less than this much history and the line is a guess.
MIN_SPAN_DAYS = 3.0
MIN_POINTS = 24
#: How well the line has to fit the points (R²) before it is shown.
MIN_FIT = 0.6
SHOW_WITHIN_DAYS = 180
TELL_WITHIN_DAYS = 14
#: Told again only once it went back above this, so a line that wobbles
#: around 14 days is told once, not every hour.
REARM_DAYS = 21
#: A backup is called slower from this much more a week, and at least a minute.
SLOWER_SHARE = 0.03
SLOWER_SECONDS = 60
TOLD = "forecast.told"
#: Cards with a share of something filling up as one of their own numbers.
FILL_METRICS = {"immich.storage": "used_percent", "nextcloud.storage": "used_percent",
                "frigate.status": "storage_percent", "pbs.datastores": "fullest"}

_known: dict[int, dict[str, Any]] = {}


def of(widget_id: int) -> dict[str, Any] | None:
    """The forecast a card shows, as last worked out."""
    return _known.get(widget_id)


def fit(points: list[tuple[int, float]]) -> tuple[float, float, float] | None:
    """``(slope a day, value now, R²)`` of the line through the points, or None when there is too little to go on."""
    if len(points) < MIN_POINTS or (points[-1][0] - points[0][0]) / 86400 < MIN_SPAN_DAYS:
        return None
    now = time.time()
    xs = [(ts - now) / 86400 for ts, _ in points]
    ys = [value for _, value in points]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if not spread:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread
    at_now = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for y in ys)
    rest = sum((y - (at_now + slope * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    return slope, at_now, (1 - rest / total) if total else 0.0


def _towards(points: list[tuple[int, float]], limit: float, rising: bool) -> tuple[float, float, float] | None:
    """``(days, slope, now)`` until the line reaches the limit, when it heads there and fits."""
    found = fit(points)
    if found is None:
        return None
    slope, now, quality = found
    gap = (limit - now) if rising else (now - limit)
    pace = slope if rising else -slope
    if gap <= 0 or pace <= 0 or quality < MIN_FIT:
        return None
    days = gap / pace
    return (days, slope, now) if days <= SHOW_WITHIN_DAYS else None


def _points(db: Session, widget_id: int, metric: str, days: float = WINDOW_DAYS) -> list[tuple[int, float]]:
    return [(ts, avg) for ts, avg, _low, _high in history.series_long(db, widget_id, metric, days)]


def work_out(db: Session, widget: Widget, data: Any) -> dict[str, Any] | None:
    """The soonest forecast of one card, or None."""
    if data is None or data.error:
        return None
    found: list[dict[str, Any]] = []
    now = time.time()

    def full(metric: str, row: str | None) -> None:
        reached = _towards(_points(db, widget.id, metric), 100.0, rising=True)
        if reached:
            days, slope, value = reached
            found.append({"kind": "full", "metric": metric, "row": row, "days": round(days, 1), "at": now + days * 86400,
                          "limit": 100.0, "slope": slope, "now": value})

    if widget.kind in history.FILL_ROWS:
        for row in data.items:
            if isinstance(row, dict) and row.get("title") and isinstance(row.get("progress"), (int, float)):
                full(f"fill:{str(row['title'])[:90]}", str(row["title"]))
    if widget.kind in FILL_METRICS and FILL_METRICS[widget.kind] in (data.metrics or {}):
        full(FILL_METRICS[widget.kind], None)

    options = dict(widget.options or {})
    warn, bad = level_lines(options)
    value = (data.primary or {}).get("value")
    if (warn is not None or bad is not None) and isinstance(value, (int, float)) and not isinstance(value, bool):
        line, limit = ("bad", bad) if bad is not None else ("warn", warn)
        rising = not low_is_bad(options)
        metric = str((data.primary or {}).get("metric") or "") or (history.HEADLINE if not data.metrics else "")
        if not metric:
            # Most cards do not name which of their numbers is the big one; the
            # one with the same value is, when exactly one has it.
            same = [name for name, number in (data.metrics or {}).items() if number == value]
            metric = same[0] if len(same) == 1 else ""
        still_short = value < limit if rising else value > limit
        if metric and still_short:
            reached = _towards(_points(db, widget.id, metric), float(limit), rising)
            if reached:
                days, slope, at = reached
                found.append({"kind": "level", "metric": metric, "row": None, "line": line, "days": round(days, 1),
                              "at": now + days * 86400, "limit": float(limit), "slope": slope, "now": at})

    if widget.kind in history.DURATION_ROWS:
        for row in data.items:
            if not (isinstance(row, dict) and row.get("title") and row.get("duration")):
                continue
            metric = f"duration:{str(row['title'])[:90]}"
            line = fit(_points(db, widget.id, metric, 60))
            if line is None:
                continue
            slope, at, quality = line
            week = slope * 7
            if quality >= MIN_FIT and week >= max(SLOWER_SECONDS, SLOWER_SHARE * at):
                found.append({"kind": "slower", "metric": metric, "row": str(row["title"]), "per_week": round(week), "now": at})

    timed = [one for one in found if one["kind"] != "slower"]
    if timed:
        return min(timed, key=lambda one: one["days"])
    return max(found, key=lambda one: one["per_week"]) if found else None


def _told(db: Session) -> dict[str, bool]:
    row = db.get(Setting, TOLD)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def _keep_told(db: Session, told: dict[str, bool]) -> None:
    row = db.get(Setting, TOLD)
    if row is None:
        db.add(Setting(key=TOLD, value=told))
    else:
        row.value = told


def _name(widget: Widget, found: dict[str, Any]) -> str:
    title = widget.title or widget.kind
    return f"{found['row']} ({title})" if found.get("row") else title


def _tell(widget: Widget, found: dict[str, Any]) -> None:
    from .notify import emit

    days = max(1, round(found["days"]))
    name = _name(widget, found)
    if found["kind"] == "full":
        title = f"{name} is full in about {days} days"
    else:
        title = f"{name} reaches {'red' if found['line'] == 'bad' else 'yellow'} in about {days} days"
    body = f"At the pace of the last {WINDOW_DAYS} days, from {found['now']:.1f} now."
    emit("forecast", title, body, level="warn", integration_id=widget.integration_id)
    chronicle.record("forecast", level="warn", widget_id=widget.id, integration_id=widget.integration_id, name=name,
                     before=found["kind"] if found["kind"] == "full" else found["line"], after=str(days), detail=body)


def round_once() -> int:
    """Work out every card's forecast, tell the ones that fell under 14 days. Returns how many cards have one."""
    with db_session() as db:
        demo = {row.id for row in db.scalars(select(Integration).where(Integration.demo.is_(True)))}
        told = _told(db)
        known: dict[int, dict[str, Any]] = {}
        for widget in db.scalars(select(Widget)):
            data = live.get(widget.id)
            try:
                found = work_out(db, widget, data)
            except Exception:  # noqa: BLE001 - one card that cannot be worked out must not stop the others
                logger.exception("The forecast of card %s could not be worked out.", widget.id)
                continue
            for key in [one for one in told if one.startswith(f"{widget.id}:")]:
                # Rearmed once it went back above the line, or when it is gone.
                if found is None or f"{widget.id}:{found['metric']}" != key or found.get("days", 0) > REARM_DAYS:
                    told.pop(key)
            if found is None:
                continue
            key = f"{widget.id}:{found['metric']}"
            if found["kind"] != "slower" and found["days"] < TELL_WITHIN_DAYS and widget.integration_id not in demo:
                if key not in told:
                    _tell(widget, found)
                    told[key] = True
                found["told"] = True
            known[widget.id] = found
        _keep_told(db, told)
    _known.clear()
    _known.update(known)
    return len(known)


def forget() -> None:
    """For tests: nothing worked out yet."""
    _known.clear()

