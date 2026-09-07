"""Metric history: raw samples for an hour, minute averages for a day.

The collector calls ``record`` with whatever numeric metrics a widget
reported. ``condense`` folds raw samples older than the raw window into
minute rows and deletes what is older than the minute window. Sparklines
query ``series``.
"""

from __future__ import annotations

import time
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import HistoryMinute, HistorySample

#: What a sparkline can draw. The browser keeps this many anyway.
MAX_POINTS = 240


def key_for(widget_id: int, metric: str) -> str:
    return f"{widget_id}:{metric}"


def record(db: Session, widget_id: int, metrics: dict[str, float], ts: int | None = None) -> None:
    if not metrics:
        return
    now = ts or int(time.time())
    db.add_all(
        HistorySample(key=key_for(widget_id, name), ts=now, value=float(value))
        for name, value in metrics.items()
        if isinstance(value, (int, float))
    )


def condense(db: Session, now: int | None = None) -> None:
    """Fold old raw samples into minute rows and prune both tables."""
    settings = get_settings()
    now = now or int(time.time())
    raw_cutoff = now - settings.history_raw_hours * 3600
    minute_cutoff = now - settings.history_minute_hours * 3600

    rows = db.execute(
        select(HistorySample.key, HistorySample.ts, HistorySample.value).where(HistorySample.ts <= raw_cutoff)
    ).all()
    buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
    for key, ts, value in rows:
        buckets[(key, ts - ts % 60)].append(value)

    if buckets:
        existing = {
            (row.key, row.ts): row
            for row in db.scalars(
                select(HistoryMinute).where(
                    HistoryMinute.ts >= min(ts for _, ts in buckets),
                    HistoryMinute.key.in_({k for k, _ in buckets}),
                )
            )
        }
        for (key, minute), values in buckets.items():
            row = existing.get((key, minute))
            if row is None:
                db.add(
                    HistoryMinute(
                        key=key, ts=minute, avg=sum(values) / len(values),
                        min=min(values), max=max(values), count=len(values),
                    )
                )
            else:
                total = row.avg * row.count + sum(values)
                row.count += len(values)
                row.avg = total / row.count
                row.min = min(row.min, *values)
                row.max = max(row.max, *values)
        db.execute(delete(HistorySample).where(HistorySample.ts <= raw_cutoff))

    db.execute(delete(HistoryMinute).where(HistoryMinute.ts <= minute_cutoff))


def series_for(db: Session, widget_ids: list[int], metric: str, hours: float = 24) -> dict[int, list[tuple[int, float]]]:
    """The same as ``series``, for many cards at once.

    ⚠️ Two queries in total instead of two per card. Opening a board with
    thirty cards that have a reachability check meant sixty round trips to
    SQLite before the first byte went out, and every one of them asked the
    same two tables for a different key.
    """
    if not widget_ids:
        return {}
    keys = {key_for(widget_id, metric): widget_id for widget_id in widget_ids}
    since = int(time.time() - hours * 3600)
    gathered: dict[int, list[tuple[int, float]]] = {widget_id: [] for widget_id in widget_ids}
    for table, column in ((HistoryMinute, HistoryMinute.avg), (HistorySample, HistorySample.value)):
        rows = db.execute(
            select(table.key, table.ts, column)
            .where(table.key.in_(keys), table.ts >= since)
            .order_by(table.ts)
        ).all()
        for key, ts, value in rows:
            gathered[keys[key]].append((int(ts), float(value)))
    return {widget_id: _thinned(points) for widget_id, points in gathered.items()}


def _thinned(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """⚠️ A sparkline is a hundred and twenty points wide. Twenty-four hours of
    minute rows is fifteen hundred, and a board asks for fifty metrics at once:
    a megabyte and a half of JSON, of which the browser keeps eight percent.
    Thin it here, evenly, so the shape survives and the payload does not.
    """
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[int(index * step)] for index in range(MAX_POINTS)] + points[-1:]


def series(db: Session, widget_id: int, metric: str, hours: float = 24) -> list[tuple[int, float]]:
    """``[(ts, value)]`` oldest first: minute averages, then raw samples."""
    key = key_for(widget_id, metric)
    since = int(time.time() - hours * 3600)
    minutes = db.execute(
        select(HistoryMinute.ts, HistoryMinute.avg)
        .where(HistoryMinute.key == key, HistoryMinute.ts >= since)
        .order_by(HistoryMinute.ts)
    ).all()
    raw = db.execute(
        select(HistorySample.ts, HistorySample.value)
        .where(HistorySample.key == key, HistorySample.ts >= since)
        .order_by(HistorySample.ts)
    ).all()
    points = [(int(ts), float(v)) for ts, v in minutes] + [(int(ts), float(v)) for ts, v in raw]
    # ⚠️ A sparkline is a hundred and twenty points wide. Twenty-four hours of
    # minute rows is fifteen hundred, and a board asks for fifty metrics at
    # once: a megabyte and a half of JSON, of which the browser keeps eight
    # percent. Thin it here, evenly, so the shape survives and the payload does
    # not.
    if len(points) > MAX_POINTS:
        step = len(points) / MAX_POINTS
        points = [points[int(index * step)] for index in range(MAX_POINTS)] + points[-1:]
    return points


def forget_widget(db: Session, widget_id: int) -> None:
    prefix = f"{widget_id}:%"
    db.execute(delete(HistorySample).where(HistorySample.key.like(prefix)))
    db.execute(delete(HistoryMinute).where(HistoryMinute.key.like(prefix)))


def sample_count(db: Session) -> int:
    return int(db.scalar(select(func.count(HistorySample.id))) or 0)
