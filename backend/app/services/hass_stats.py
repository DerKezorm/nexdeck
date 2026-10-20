"""What Home Assistant remembers: long-term statistics of sensors and the history of thermostats.

Only read, never written, and nothing of it is kept in nexdeck beyond a
minute's cache. Two sources, as Home Assistant itself has them:

* **Long-term statistics** (``recorder/statistics_during_period``) for every
  sensor with a state class: a mean, low and high per hour, kept for good, and
  per five minutes for the last days; for a counter (``total_increasing``) the
  change per hour. A house of 232 lamps had 1238 statistics, 92 of them
  temperatures going back a year (measured 20.10.2026, Home Assistant 2026.10).
* **History** (``history/history_during_period``): every state as it changed,
  kept for ten days unless the recorder is told otherwise. It is what a sensor
  without a state class has, and what a thermostat's target and heating times
  are read from: of 26 thermostats in that house, 14 said when they heat
  (``hvac_action``).

A day begins at midnight in the house's time zone (``get_config``), not the
server's: a wall in Berlin served from a container in UTC still starts today
at 0:00.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import hass_registry

#: The periods a card may show, and how long each reaches back.
PERIODS = {"24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7), "30d": dt.timedelta(days=30), "1y": dt.timedelta(days=365)}
#: The two of the comparison: today against yesterday, this week against the last.
COMPARE = ("day", "week")
#: The step of the points, by period and by whether the sensor measures or counts.
#: Five minutes is what Home Assistant keeps for ten days; an hour, a day, a week and a month for good.
STEPS = {
    "mean": {"24h": "5minute", "7d": "hour", "30d": "day", "1y": "week", "day": "5minute", "week": "hour"},
    "sum": {"24h": "hour", "7d": "day", "30d": "day", "1y": "month", "day": "hour", "week": "day"},
}
#: How long the list of statistics and an answer are kept.
CATALOGUE_SECONDS = 600
ANSWER_SECONDS = 60
#: What a thermostat says while it heats.
HEATING = ("heating", "preheating")


def tz(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return dt.UTC


# ---------------------------------------------------------------------------
# Time: periods and the steps inside them
# ---------------------------------------------------------------------------


def _local_midnight(moment: dt.datetime, zone: dt.tzinfo) -> dt.datetime:
    local = moment.astimezone(zone)
    return dt.datetime(local.year, local.month, local.day, tzinfo=zone)


def _midnight(moment: dt.datetime, zone: dt.tzinfo) -> dt.datetime:
    return _local_midnight(moment, zone).astimezone(dt.UTC)


def floor(moment: dt.datetime, step: str, zone: dt.tzinfo) -> dt.datetime:
    """The start of the step a moment falls into: five minutes and hours by the clock, days and longer by the house's calendar."""
    if step == "5minute":
        return moment.replace(minute=moment.minute - moment.minute % 5, second=0, microsecond=0)
    if step == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    midnight = _local_midnight(moment, zone)
    # In UTC from here: two times of the same zone subtract by the wall clock, and a day of 25 hours would be 24.
    if step == "day":
        return midnight.astimezone(dt.UTC)
    if step == "week":
        return (midnight - dt.timedelta(days=midnight.weekday())).astimezone(dt.UTC)
    return midnight.replace(day=1).astimezone(dt.UTC)


def following(start: dt.datetime, step: str, zone: dt.tzinfo) -> dt.datetime:
    """The start of the next step; a day is a calendar day, 23 or 25 hours when the clocks change."""
    if step == "5minute":
        return start + dt.timedelta(minutes=5)
    if step == "hour":
        return start + dt.timedelta(hours=1)
    local = start.astimezone(zone)
    if step == "day":
        nxt = local.date() + dt.timedelta(days=1)
    elif step == "week":
        nxt = local.date() + dt.timedelta(days=7)
    else:
        nxt = (local.date().replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone).astimezone(dt.UTC)


def steps(start: dt.datetime, end: dt.datetime, step: str, zone: dt.tzinfo) -> list[dt.datetime]:
    """Every step that begins before ``end``, from the one ``start`` falls into."""
    found, at = [], floor(start, step, zone)
    while at < end:
        found.append(at)
        at = following(at, step, zone)
    return found


def window(period: str, now: dt.datetime, zone: dt.tzinfo) -> tuple[dt.datetime, dt.datetime, dt.datetime | None]:
    """Where a period starts and ends, and where the one it is compared with starts (for ``day`` and ``week``).

    A comparison shows the whole day or week, the part still to come empty, so
    yesterday's evening stands beside where today's will be.
    """
    if period in COMPARE:
        start = floor(now, "day" if period == "day" else "week", zone)
        end = following(start, period, zone)
        before = floor(start - dt.timedelta(hours=1), period, zone)
        return start, end, before
    return now - PERIODS[period], now, None


def _ms(moment: dt.datetime) -> int:
    return int(moment.timestamp() * 1000)


def _moment(value: Any) -> dt.datetime | None:
    """A time as Home Assistant writes it: milliseconds in statistics, seconds in history, or ISO text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000 if value > 1e11 else value, dt.UTC)
    if isinstance(value, str):
        try:
            moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# ---------------------------------------------------------------------------
# Which sensors there are
# ---------------------------------------------------------------------------


def kind_of(meta: dict[str, Any] | None) -> str | None:
    """``sum`` for a counter, ``mean`` for a measurement, None for a sensor without statistics."""
    if not meta:
        return None
    if meta.get("has_sum"):
        return "sum"
    if meta.get("has_mean") or meta.get("mean_type"):
        return "mean"
    return None


def pick_sensors(entities: list[dict[str, Any]], devices: list[dict[str, Any]], areas: list[dict[str, Any]],
                 states: dict[str, dict[str, Any]], catalogue: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The sensors a statistics card can show: those with statistics, and those with a number now.

    A sensor with long-term statistics reaches back as far as Home Assistant
    keeps them; one without, only as far as its history (``source``). Text
    sensors (a washing machine's programme) have neither a line nor a bar.
    """
    found = []
    for entry, state, named in hass_registry._offered(entities, devices, areas, states, "sensor"):
        meta = catalogue.get(named["entity_id"])
        kind = kind_of(meta)
        reading = hass_registry.sensor_state(state)
        if kind is None and reading["current"] is None:
            continue
        attributes = state.get("attributes") or {}
        found.append({**named, **reading,
                      "unit": reading["unit"] or str((meta or {}).get("display_unit_of_measurement") or (meta or {}).get("statistics_unit_of_measurement") or ""),
                      "device_class": str(attributes.get("device_class") or entry.get("device_class") or entry.get("original_device_class") or ""),
                      "kind": kind or "mean", "source": "statistics" if kind else "history"})
    return hass_registry._by_name(found)


async def catalogue(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False, now: float | None = None) -> dict[str, dict[str, Any]]:
    """Every statistic Home Assistant keeps, by its id; kept ten minutes."""
    if demo:
        return demo_catalogue()
    now = time.monotonic() if now is None else now
    kept = cache.get("hass_statistic_ids")
    if kept is None or kept[0] < now:
        answer = (await hass_registry._ask(config, [{"type": "recorder/list_statistic_ids"}]))[0] or []
        kept = (now + CATALOGUE_SECONDS, {str(one.get("statistic_id")): one for one in answer if isinstance(one, dict)})
        cache["hass_statistic_ids"] = kept
    return kept[1]


async def sensors(config: dict[str, Any], cache: dict[str, Any], *, demo: bool = False) -> list[dict[str, Any]]:
    entities, devices, areas, states, _unit = await hass_registry.house(config, cache, demo=demo)
    return pick_sensors(entities, devices, areas, states, await catalogue(config, cache, demo=demo))


# ---------------------------------------------------------------------------
# From what Home Assistant answers to points
# ---------------------------------------------------------------------------


def from_statistics(rows: list[dict[str, Any]], kind: str) -> list[list[Any]]:
    """``[start, mean, low, high]`` per step, or ``[start, change]`` for a counter; steps without a value are left out."""
    points = []
    for row in rows or []:
        start = _moment(row.get("start"))
        if start is None:
            continue
        if kind == "sum":
            change = _number(row.get("change"))
            if change is not None:
                points.append([_ms(start), round(change, 3)])
            continue
        mean = _number(row.get("mean"))
        low, high = _number(row.get("min")), _number(row.get("max"))
        if mean is None:
            mean = (low + high) / 2 if low is not None and high is not None else low if low is not None else high
        if mean is None:
            continue
        points.append([_ms(start), round(mean, 2), round(low if low is not None else mean, 2), round(high if high is not None else mean, 2)])
    return points


def changes(rows: list[dict[str, Any]], read) -> list[tuple[dt.datetime, Any]]:
    """The moments a history row says something changed, with what ``read`` takes from it, oldest first."""
    found = []
    for row in rows or []:
        moment = _moment(row.get("lu") if "lu" in row else row.get("last_updated") or row.get("last_changed"))
        if moment is not None:
            found.append((moment, read(row)))
    found.sort(key=lambda one: one[0])
    return found


def from_history(found: list[tuple[dt.datetime, float | None]], start: dt.datetime, end: dt.datetime, step: str,
                 zone: dt.tzinfo) -> list[list[Any]]:
    """Points like ``from_statistics`` from the changes of a history, weighing each value by how long it stood.

    A value holds until the next change: a sensor that read 21 at nine and
    nothing since still reads 21 at noon. The first row of a history is the
    state at its start, however long before it was set.
    """
    points = []
    marks = steps(start, end, step, zone)
    index, value = 0, None
    for at in marks:
        until = min(following(at, step, zone), end)
        while index < len(found) and found[index][0] <= at:
            value = found[index][1]
            index += 1
        seen, weighed, total = [], 0.0, 0.0
        moment = at
        if value is not None:
            seen.append(value)
        scan = index
        while scan < len(found) and found[scan][0] < until:
            if value is not None:
                weighed += value * (found[scan][0] - moment).total_seconds()
                total += (found[scan][0] - moment).total_seconds()
            moment, value = found[scan][0], found[scan][1]
            if value is not None:
                seen.append(value)
            scan += 1
        index = scan
        if value is not None:
            weighed += value * (until - moment).total_seconds()
            total += (until - moment).total_seconds()
        if not seen:
            continue
        mean = weighed / total if total > 0 else seen[-1]
        points.append([_ms(at), round(mean, 2), round(min(seen), 2), round(max(seen), 2)])
    return points


def summary(points: list[list[Any]], kind: str) -> dict[str, Any]:
    """Low and high with when, and the mean, of a run of points; for a counter the total and the mean per step."""
    if not points:
        return {"low": None, "high": None, "mean": None, "total": None}
    if kind == "sum":
        total = sum(point[1] for point in points)
        return {"low": None, "high": None, "mean": round(total / len(points), 3), "total": round(total, 3)}
    low = min(points, key=lambda point: point[2])
    high = max(points, key=lambda point: point[3])
    return {"low": [low[2], low[0]], "high": [high[3], high[0]],
            "mean": round(sum(point[1] for point in points) / len(points), 2), "total": None}


def _statistics_command(ids: list[str], start: dt.datetime, end: dt.datetime, step: str, kind: str) -> dict[str, Any]:
    return {"type": "recorder/statistics_during_period", "start_time": start.isoformat(), "end_time": end.isoformat(),
            "statistic_ids": ids, "period": step, "types": ["change"] if kind == "sum" else ["mean", "min", "max"]}


def _history_command(ids: list[str], start: dt.datetime, end: dt.datetime, attributes: bool) -> dict[str, Any]:
    return {"type": "history/history_during_period", "start_time": start.isoformat(), "end_time": end.isoformat(),
            "entity_ids": ids, "minimal_response": not attributes, "no_attributes": not attributes,
            "significant_changes_only": False}


# ---------------------------------------------------------------------------
# A card's series
# ---------------------------------------------------------------------------


async def series(config: dict[str, Any], cache: dict[str, Any], wanted: list[dict[str, Any] | None], period: str, *,
                 demo: bool = False, now: dt.datetime | None = None) -> dict[str, Any]:
    """The points of each sensor a card names, for one period, with what the card writes under them.

    ``wanted`` is the card's sensors as offered (``pick_sensors``), or None
    for one Home Assistant no longer has. A comparison brings the period
    before as ``previous``, its times moved onto this one so they overlay.
    """
    now = now or dt.datetime.now(dt.UTC)
    zone = tz("Europe/Berlin" if demo else hass_registry.zone(cache))
    start, end, before = window(period, now, zone)
    key = f"hass_stats:{period}:" + ",".join(str((one or {}).get("entity_id")) for one in wanted)
    kept = cache.get(key)
    if kept is not None and kept[0] > time.monotonic():
        return kept[1]

    commands: list[dict[str, Any]] = []
    plan: list[tuple[int, str, Any]] = []  # which command answers which sensor, and how
    for number, sensor in enumerate(wanted):
        if not sensor:
            continue
        kind, step = sensor["kind"], STEPS[sensor["kind"]][period]
        reach = before or start
        if sensor["source"] == "statistics":
            plan.append((number, "statistics", len(commands)))
            commands.append(_statistics_command([sensor["entity_id"]], reach, end, step, kind))
        else:
            plan.append((number, "history", len(commands)))
            commands.append(_history_command([sensor["entity_id"]], reach, min(end, now), False))
    if demo:
        answers = [demo_answer(command, now) for command in commands]
    else:
        answers = await hass_registry._ask(config, commands) if commands else []

    out = []
    for number, sensor in enumerate(wanted):
        if not sensor:
            out.append({"missing": True})
            continue
        kind, step = sensor["kind"], STEPS[sensor["kind"]][period]
        how, index = next((how, index) for at, how, index in plan if at == number)
        answer = answers[index] or {}
        if how == "statistics":
            points = from_statistics(answer.get(sensor["entity_id"]) or [], kind)
        else:
            found = changes(answer.get(sensor["entity_id"]) or [], lambda row: _number(row.get("s") if "s" in row else row.get("state")))
            points = from_history(found, before or start, min(end, now), step, zone)
        line = {"rid": sensor["rid"], "entity_id": sensor["entity_id"], "name": sensor["name"], "unit": sensor["unit"],
                "kind": kind, "source": sensor["source"], "current": sensor["current"], "unavailable": sensor["unavailable"],
                "missing": False, "step": step}
        if before is not None:
            shift = _ms(start) - _ms(before)
            now_points = [point for point in points if point[0] >= _ms(start)]
            then = [[point[0] + shift, *point[1:]] for point in points if point[0] < _ms(start)]
            line.update(points=now_points, previous=then, previous_summary=summary(then, kind))
            points = now_points
        else:
            # A counter counts whole steps, today's so far the last of them: seven bars for seven days, not eight
            # with a part of the first. A measurement runs from where the period begins.
            first = following(floor(start, step, zone), step, zone) if kind == "sum" else floor(start, step, zone)
            points = [point for point in points if point[0] >= _ms(first)]
            line["points"] = points
        line.update(summary(points, kind))
        if kind == "sum" and points:
            line["latest"] = points[-1][1]
        out.append(line)
    result = {"period": period, "start": _ms(start), "end": _ms(end), "now": _ms(now), "zone": str(zone), "series": out}
    cache[key] = (time.monotonic() + ANSWER_SECONDS, result)
    return result


# ---------------------------------------------------------------------------
# A thermostat's history
# ---------------------------------------------------------------------------


def heating_spans(found: list[tuple[dt.datetime, Any]], start: dt.datetime, end: dt.datetime) -> list[list[int]]:
    """When a thermostat said it heats, as ``[from, to]`` inside ``start`` to ``end``."""
    spans, since = [], None
    for moment, action in found:
        heating = action in HEATING
        if heating and since is None:
            since = max(moment, start)
        elif not heating and since is not None:
            if moment > start:
                spans.append([_ms(since), _ms(min(moment, end))])
            since = None
    if since is not None and since < end:
        spans.append([_ms(since), _ms(end)])
    return [span for span in spans if span[1] > span[0]]


def _heated(spans: list[list[int]], start: dt.datetime, end: dt.datetime) -> int:
    lo, hi = _ms(start), _ms(end)
    return sum(max(0, min(span[1], hi) - max(span[0], lo)) for span in spans) // 1000


async def climate_history(config: dict[str, Any], cache: dict[str, Any], thermostat: dict[str, Any], sensor: dict[str, Any] | None,
                          period: str, *, demo: bool = False, now: dt.datetime | None = None) -> dict[str, Any]:
    """Room, target and heating times of one thermostat over 24 hours or a week, and the day in numbers.

    The room is read by the sensor the page names for it where there is one
    (its statistics), else by the thermostat itself (its history). The target
    is a step line, empty while the thermostat is off. ``heating`` is None for
    a thermostat that never says whether it heats, not an empty list: the
    page then says so rather than drawing a day without heating.
    """
    now = now or dt.datetime.now(dt.UTC)
    zone = tz("Europe/Berlin" if demo else hass_registry.zone(cache))
    start = now - PERIODS[period]
    today = _midnight(now, zone)
    yesterday = _midnight(today - dt.timedelta(hours=1), zone)
    reach = min(start, yesterday)
    key = f"hass_climate_history:{period}:{thermostat['entity_id']}:{(sensor or {}).get('entity_id')}"
    kept = cache.get(key)
    if kept is not None and kept[0] > time.monotonic():
        return kept[1]
    step = STEPS["mean"][period if period == "7d" else "24h"]
    commands = [_history_command([thermostat["entity_id"]], reach, now, True)]
    if sensor and sensor.get("source") == "statistics":
        commands.append(_statistics_command([sensor["entity_id"]], reach, now, step, "mean"))
    elif sensor:
        commands.append(_history_command([sensor["entity_id"]], reach, now, False))
    if demo:
        answers = [demo_answer(command, now) for command in commands]
    else:
        answers = await hass_registry._ask(config, commands)

    rows = (answers[0] or {}).get(thermostat["entity_id"]) or []
    attributes = changes(rows, lambda row: (row.get("s") if "s" in row else row.get("state"), row.get("a") if "a" in row else row.get("attributes") or {}))
    # In a compressed history a row without attributes keeps those before it.
    held: dict[str, Any] = {}
    states = []
    for moment, (value, given) in attributes:
        if given:
            held = given
        states.append((moment, value, held))
    if sensor is None:
        room = from_history([(moment, _number(given.get("current_temperature"))) for moment, _value, given in states], reach, now, step, zone)
    elif sensor.get("source") == "statistics":
        room = from_statistics((answers[1] or {}).get(sensor["entity_id"]) or [], "mean")
    else:
        found = changes((answers[1] or {}).get(sensor["entity_id"]) or [], lambda row: _number(row.get("s") if "s" in row else row.get("state")))
        room = from_history(found, reach, now, step, zone)

    target: list[list[Any]] = []
    for moment, value, given in states:
        number = None if value in ("off", "unavailable", "unknown") else _number(given.get("temperature"))
        if target and target[-1][1] == number:
            continue
        target.append([_ms(max(moment, start)), number])
    # Only the last change before the start counts, moved onto the start.
    while len(target) > 1 and target[1][0] <= _ms(start):
        target.pop(0)

    says = any("hvac_action" in given for _moment, _value, given in states)
    actions = [(moment, given.get("hvac_action")) for moment, _value, given in states]
    spans = heating_spans(actions, reach, now) if says else None
    shown = [point for point in room if point[0] >= _ms(floor(start, step, zone))]
    so_far = [point for point in room if point[0] >= _ms(today)]
    result = {
        "period": period, "start": _ms(start), "end": _ms(now), "zone": str(zone), "step": step, "room": shown,
        "target": target, "heating": [span for span in spans if span[1] > _ms(start)] if spans is not None else None,
        "today": {"low": min((point[2] for point in so_far), default=None), "high": max((point[3] for point in so_far), default=None),
                  "heated": _heated(spans, today, now) if spans is not None else None},
        "yesterday": {"heated": _heated(spans, yesterday, today) if spans is not None else None},
        "sensor": (sensor or {}).get("entity_id"),
    }
    cache[key] = (time.monotonic() + ANSWER_SECONDS, result)
    return result


# ---------------------------------------------------------------------------
# The demo house remembers too
# ---------------------------------------------------------------------------


#: Each demo sensor's middle, its swing over a day and its noise; a counter's kWh per hour.
DEMO_SENSORS = {
    "sensor.living_room_temperature": (21.0, 0.9, 0.15),
    "sensor.bedroom_temperature": (18.6, 0.7, 0.15),
    "sensor.living_room_humidity": (50.0, 5.0, 1.0),
    "sensor.outdoor_temperature": (9.0, 4.0, 0.6),
    "sensor.house_energy": (0.3, 0.25, 0.08),
}


def demo_catalogue() -> dict[str, dict[str, Any]]:
    units = {"sensor.living_room_humidity": "%", "sensor.house_energy": "kWh"}
    return {entity_id: {"statistic_id": entity_id, "source": "recorder", "has_mean": entity_id != "sensor.house_energy",
                        "has_sum": entity_id == "sensor.house_energy", "statistics_unit_of_measurement": units.get(entity_id, "°C")}
            for entity_id in DEMO_SENSORS}


def _wobble(entity_id: str, moment: dt.datetime) -> float:
    """Between -1 and 1, the same for the same sensor and moment, so a demo card does not jump when it is read again."""
    digest = hashlib.sha256(f"{entity_id}{int(moment.timestamp())}".encode()).digest()
    return digest[0] / 127.5 - 1


def demo_value(entity_id: str, moment: dt.datetime, now: dt.datetime | None = None) -> float:
    """A demo sensor's value at a moment; with ``now``, moved so that it ends where the sensor's state stands."""
    if now is not None and entity_id != "sensor.house_energy":
        state = hass_registry.demo_registry()[3].get(entity_id) or {}
        stands = _number(state.get("state"))
        if stands is not None:
            return demo_value(entity_id, moment) + stands - demo_value(entity_id, now)
    middle, swing, noise = DEMO_SENSORS.get(entity_id, (20.0, 1.0, 0.2))
    local = moment.astimezone(tz("Europe/Berlin"))
    hour = local.hour + local.minute / 60
    if entity_id == "sensor.house_energy":
        # Morning and evening, little at night.
        shape = math.exp(-((hour - 7.5) ** 2) / 3) + 1.4 * math.exp(-((hour - 19) ** 2) / 5)
        return max(0.05, middle * 0.4 + swing * shape + noise * _wobble(entity_id, moment))
    days = moment.timestamp() / 86400
    seasonal = -2.5 * math.cos((days - 20) / 365 * 2 * math.pi) if entity_id == "sensor.outdoor_temperature" else 0
    return middle + seasonal + swing * math.sin((hour - 9) / 24 * 2 * math.pi) + noise * _wobble(entity_id, moment)


def _demo_target(moment: dt.datetime) -> float:
    """The demo living room's target at a moment: 21.5 from six in the morning to ten at night, 18 otherwise."""
    local = moment.astimezone(tz("Europe/Berlin"))
    return 21.5 if 6 <= local.hour < 22 else 18.0


def demo_answer(command: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    """What Home Assistant would answer the demo house: statistics or a history, made up but the same each time."""
    zone = tz("Europe/Berlin")
    start = _moment(command["start_time"]) or now
    end = min(_moment(command.get("end_time")) or now, now)
    answer: dict[str, Any] = {}
    if command["type"] == "recorder/statistics_during_period":
        step = command["period"]
        for entity_id in command["statistic_ids"]:
            rows: list[dict[str, Any]] = []
            for at in steps(start, end, step, zone):
                until = following(at, step, zone)
                # An hour is in the statistics once it is over; a day, a week or a month so far is made of its hours, as in Home Assistant.
                if until > now:
                    until = floor(now, "hour", zone) if step in ("day", "week", "month") else at
                    if until <= at:
                        break
                samples = [demo_value(entity_id, at + (until - at) * (k / 6), now) for k in range(6)]
                if "change" in command["types"]:
                    hours = (until - at).total_seconds() / 3600
                    rows.append({"start": _ms(at), "end": _ms(until), "change": round(sum(samples) / len(samples) * hours, 3)})
                else:
                    rows.append({"start": _ms(at), "end": _ms(until), "mean": round(sum(samples) / len(samples), 2),
                                 "min": round(min(samples), 2), "max": round(max(samples), 2)})
            answer[entity_id] = rows
        return answer
    for entity_id in command["entity_ids"]:
        rows = []
        at = start.replace(minute=start.minute - start.minute % 15, second=0, microsecond=0)
        if entity_id == "climate.living_room":
            # Heats while the room is more than a little under the target, as a valve does.
            # Always from the same midnight, so the 24 hours and the week tell of the same day.
            room, heating = 19.0, False
            at = floor(now - dt.timedelta(days=8), "day", zone).astimezone(dt.UTC)
            while at <= end:
                target = _demo_target(at)
                heating = room < target - 0.3 or (heating and room < target + 0.2)
                room = max(16.5, room + (0.35 if heating else -0.08))
                if at >= start - dt.timedelta(minutes=15):
                    rows.append({"s": "heat", "lu": at.timestamp(), "a": {
                        "temperature": target, "current_temperature": round(room, 1), "hvac_action": "heating" if heating else "idle"}})
                at += dt.timedelta(minutes=15)
        elif entity_id.startswith("climate."):
            while at <= end:
                rows.append({"s": "off", "lu": at.timestamp(), "a": {"temperature": 17, "current_temperature": round(demo_value("sensor.bedroom_temperature", at), 1),
                                                                       "hvac_action": "off"}})
                at += dt.timedelta(hours=1)
        else:
            while at <= end:
                rows.append({"s": f"{demo_value(entity_id, at, now):.1f}", "lu": at.timestamp()})
                at += dt.timedelta(minutes=10)
        answer[entity_id] = rows
    return answer
