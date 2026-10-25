"""Metric history: raw samples for an hour, minutes for a day, hours for 90 days, days for two years.

The collector calls ``record`` with whatever numeric metrics a widget
reported. ``condense`` folds raw samples older than the raw window into
minute rows, every hour that is complete into an hour row and every day
into a day row (roadmap M4), and deletes what is past its window.
Sparklines query ``series``, the long charts and the forecasts
``series_long``.

⚠️ An hour is folded once, when its minutes are all there, and a day once,
when its hours are. Where the folding stands is kept in the setting
``history.folded``; folding again what was folded would count it twice.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..adapters.base import WidgetData
from ..config import get_settings
from ..models import HistoryDay, HistoryHour, HistoryMinute, HistorySample, Setting

#: What a sparkline can draw. The browser keeps this many anyway.
MAX_POINTS = 240
#: The name a card's big number is kept under when its adapter declares no metric.
HEADLINE = "headline"
#: What a long chart is sent at most; a year of days fits, 30 days of hours are paired up.
MAX_LONG_POINTS = 400
FOLDED = "history.folded"
#: Cards whose rows are things that fill up: each row's share is kept as ``fill:<row>``.
FILL_ROWS = frozenset({"synology.volumes", "truenas.pools", "glances.disks", "pbs.datastores",
                       "openmediavault.filesystems", "nexcrate.storage", "unraid.array"})
#: Cards whose rows are backups with how long the last run took (``duration``, seconds): kept as ``duration:<row>``.
DURATION_ROWS = frozenset({"backrest.plans", "kopia.sources", "duplicati.backups"})


def key_for(widget_id: int, metric: str) -> str:
    return f"{widget_id}:{metric}"


def recorded(data: WidgetData | None) -> dict[str, float]:
    """What is written down for a card: the metrics its adapter declares, or else its big number.

    A value card without a declared metric showed a bare number and never a
    line under it, although the number moved all day. Its headline is kept
    now, under ``headline``. Only a real number: a version string or a
    yes/no would draw nothing worth seeing. An answer with an error keeps
    nothing, or a failed fetch would draw a dip to zero.

    ⚠️ The browser applies the same rule to the answers it is pushed,
    ``recordedMetrics`` in ``frontend/src/lib/recorded.ts``.
    """
    if data is None or data.error:
        return {}
    if data.metrics:
        return data.metrics
    value = (data.primary or {}).get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {HEADLINE: float(value)}
    return {}


def extras(kind: str, data: WidgetData | None) -> dict[str, float]:
    """What a card's rows say that a chart of the card never shows, kept for the forecasts.

    The share of each volume, pool or disk, and how long each backup took.
    Kept beside the card's own metrics, never among them: a sparkline of
    ``fill:Volume 1`` would be a line nobody asked for.
    """
    if data is None or data.error:
        return {}
    found: dict[str, float] = {}
    for row in data.items:
        if not isinstance(row, dict) or not row.get("title"):
            continue
        name = str(row["title"])[:90]
        progress = row.get("progress")
        if kind in FILL_ROWS and isinstance(progress, (int, float)) and not isinstance(progress, bool):
            found[f"fill:{name}"] = float(progress)
        duration = row.get("duration")
        if kind in DURATION_ROWS and isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
            found[f"duration:{name}"] = float(duration)
    return found


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

    # The hours and days before the minutes go: they are folded from them.
    folded = _folded(db)
    hour_end = raw_cutoff - raw_cutoff % 3600
    hour_start = folded.get("hour") or hour_end - settings.history_minute_hours * 3600
    if hour_start < hour_end:
        _fold(db, HistoryMinute, HistoryHour, hour_start, hour_end, lambda ts: ts - ts % 3600)
        folded["hour"] = hour_end
    day_end = local_midnight(folded.get("hour") or hour_end)
    day_start = folded.get("day") or _first_day(db)
    if day_start is not None and day_start < day_end:
        _fold(db, HistoryHour, HistoryDay, day_start, day_end, local_midnight)
        folded["day"] = day_end
    _keep_folded(db, folded)

    db.execute(delete(HistoryMinute).where(HistoryMinute.ts <= minute_cutoff))
    db.execute(delete(HistoryHour).where(HistoryHour.ts < now - settings.history_hour_days * 86400))
    db.execute(delete(HistoryDay).where(HistoryDay.ts < now - settings.history_day_days * 86400))


def local_midnight(ts: int) -> int:
    """The start of the day ``ts`` falls in, on the clock of the house (``TZ``).

    ⚠️ Naive local time, not an aware one: an aware time keeps the offset of
    the moment it was made from, and on the day the clocks change that put
    midnight an hour off. Found on 25.10.2026, the day summer time ended.
    """
    return int(datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def _folded(db: Session) -> dict[str, int]:
    row = db.get(Setting, FOLDED)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return {key: int(value[key]) for key in ("hour", "day") if isinstance(value.get(key), (int, float))}


def _keep_folded(db: Session, folded: dict[str, int]) -> None:
    row = db.get(Setting, FOLDED)
    if row is None:
        db.add(Setting(key=FOLDED, value=dict(folded)))
    else:
        row.value = dict(folded)


def _first_day(db: Session) -> int | None:
    db.flush()
    first = db.scalar(select(func.min(HistoryHour.ts)))
    return local_midnight(int(first)) if first is not None else None


def _fold(db: Session, source: Any, target: Any, start: int, end: int, bucket: Any) -> None:
    """Rows of ``source`` in ``[start, end)`` into one row of ``target`` per key and bucket, weighted by their count."""
    db.flush()
    sums: dict[tuple[str, int], list[float]] = {}
    for key, ts, avg, low, high, count in db.execute(
        select(source.key, source.ts, source.avg, source.min, source.max, source.count)
        .where(source.ts >= start, source.ts < end)
    ):
        weight = max(1, int(count or 1))
        slot = sums.setdefault((key, bucket(int(ts))), [0.0, 0.0, math.inf, -math.inf])
        slot[0] += float(avg) * weight
        slot[1] += weight
        slot[2] = min(slot[2], float(low))
        slot[3] = max(slot[3], float(high))
    if not sums:
        return
    existing = {(row.key, row.ts): row for row in db.scalars(
        select(target).where(target.ts >= bucket(start), target.ts < end, target.key.in_({key for key, _ in sums}))
    )}
    for (key, ts), (total, weight, low, high) in sums.items():
        row = existing.get((key, ts))
        if row is None:
            db.add(target(key=key, ts=ts, avg=total / weight, min=low, max=high, count=int(weight)))
        else:
            # A bucket that began before the last fold (a day half folded at
            # yesterday's run) takes the new part on top of the old.
            together = row.count + weight
            row.avg = (row.avg * row.count + total) / together
            row.min, row.max, row.count = min(row.min, low), max(row.max, high), int(together)


def series_long(db: Session, widget_id: int, metric: str, days: float) -> list[tuple[int, float, float, float]]:
    """``[(ts, avg, min, max)]`` oldest first: hours up to 30 days, days beyond, the part not folded yet from the finer rows."""
    key = key_for(widget_id, metric)
    since = int(time.time() - days * 86400)
    coarse, size = (HistoryHour, 3600) if days <= 30 else (HistoryDay, 86400)
    bucket = (lambda ts: ts - ts % 3600) if size == 3600 else local_midnight
    points: dict[int, list[float]] = {}
    for ts, avg, low, high, count in db.execute(
        select(coarse.ts, coarse.avg, coarse.min, coarse.max, coarse.count).where(coarse.key == key, coarse.ts >= bucket(since))
    ):
        weight = float(max(1, count))
        points[int(ts)] = [float(avg) * weight, weight, float(low), float(high)]
    covered = (max(points) + size) if points else bucket(since)
    finer: list[tuple[int, float, float, float, int]] = []
    if size == 86400:
        finer += [(int(ts), float(a), float(lo), float(hi), int(c)) for ts, a, lo, hi, c in db.execute(
            select(HistoryHour.ts, HistoryHour.avg, HistoryHour.min, HistoryHour.max, HistoryHour.count)
            .where(HistoryHour.key == key, HistoryHour.ts >= covered))]
        covered = max([covered, *[ts + 3600 for ts, *_ in finer]])
    finer += [(int(ts), float(a), float(lo), float(hi), int(c)) for ts, a, lo, hi, c in db.execute(
        select(HistoryMinute.ts, HistoryMinute.avg, HistoryMinute.min, HistoryMinute.max, HistoryMinute.count)
        .where(HistoryMinute.key == key, HistoryMinute.ts >= covered))]
    finer += [(int(ts), float(v), float(v), float(v), 1) for ts, v in db.execute(
        select(HistorySample.ts, HistorySample.value).where(HistorySample.key == key, HistorySample.ts >= covered))]
    for ts, avg, low, high, count in finer:
        slot = points.setdefault(bucket(ts), [0.0, 0.0, math.inf, -math.inf])
        weight = max(1, count)
        slot[0] += avg * weight
        slot[1] += weight
        slot[2] = min(slot[2], low)
        slot[3] = max(slot[3], high)
    rows = [(ts, total / weight, low, high) for ts, (total, weight, low, high) in sorted(points.items()) if weight]
    return _paired(rows, MAX_LONG_POINTS)


def _paired(rows: list[tuple[int, float, float, float]], limit: int) -> list[tuple[int, float, float, float]]:
    """Neighbours folded together until it fits, so the lowest and the highest survive; a picked point would lose them."""
    if len(rows) <= limit:
        return rows
    size = math.ceil(len(rows) / limit)
    out = []
    for at in range(0, len(rows), size):
        group = rows[at:at + size]
        out.append((group[0][0], sum(row[1] for row in group) / len(group), min(row[2] for row in group), max(row[3] for row in group)))
    return out


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
    for table in (HistorySample, HistoryMinute, HistoryHour, HistoryDay):
        db.execute(delete(table).where(table.key.like(prefix)))


def sample_count(db: Session) -> int:
    return int(db.scalar(select(func.count(HistorySample.id))) or 0)
