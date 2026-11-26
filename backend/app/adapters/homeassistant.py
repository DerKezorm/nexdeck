"""Home Assistant: any entity as a widget, services as actions.

State comes from the WebSocket listener in ``services.hass_ws`` when it is
connected (instant, no polling) and from the REST API otherwise.
"""

from __future__ import annotations

import datetime as dt
import math
import time
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    timeline,
)

TOGGLE_DOMAINS = {"light", "switch", "input_boolean", "fan", "automation", "humidifier", "siren"}
RUN_DOMAINS = {"scene": ("turn_on", "Activate"), "script": ("turn_on", "Run"), "button": ("press", "Press"), "input_button": ("press", "Press")}
COVER = {"cover": (("open_cover", "Open"), ("close_cover", "Close"))}
LOCK = {"lock": (("lock", "Lock"), ("unlock", "Unlock"))}


def entity_status(domain: str, state: str) -> str:
    if state in ("unavailable", "unknown"):
        return "unknown"
    if domain in ("binary_sensor",) and state == "on":
        return "warn"
    if domain in ("alarm_control_panel",) and state in ("triggered",):
        return "bad"
    return "ok"


def actions_for(entity_id: str, state: str) -> list[Action]:
    domain = entity_id.split(".", 1)[0]
    if domain in TOGGLE_DOMAINS:
        service, label, icon = ("turn_off", "Turn off", "power") if state == "on" else ("turn_on", "Turn on", "power")
        return [Action(id=f"{domain}.{service}", label=label, icon=icon, params={"entity_id": entity_id})]
    if domain in RUN_DOMAINS:
        service, label = RUN_DOMAINS[domain]
        return [Action(id=f"{domain}.{service}", label=label, icon="play", params={"entity_id": entity_id})]
    if domain in COVER:
        return [Action(id=f"cover.{s}", label=lab, icon="chevrons-up-down", params={"entity_id": entity_id}) for s, lab in COVER[domain]]
    if domain in LOCK:
        return [Action(id=f"lock.{s}", label=lab, icon="lock", confirm=s == "unlock", params={"entity_id": entity_id}) for s, lab in LOCK[domain]]
    return []


#: What the summary card can make of several entities (#82).
AGGREGATIONS = (("sum", "Sum"), ("mean", "Average"), ("min", "Lowest"), ("max", "Highest"), ("count", "Count"),
                ("count_on", "Count of those on or open"))
#: States that count as "on" for ``count_on``: a switch or lamp that is on, a window or door sensor that is open.
ON_STATES = {"on", "open", "opening", "unlocked"}
#: The periods of the history card, and how long each reaches back.
HISTORY_RANGES = {"1h": dt.timedelta(hours=1), "6h": dt.timedelta(hours=6), "24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7)}
#: How many points one line of the history card draws, whatever the period.
HISTORY_POINTS = 120
#: Entities one summary or history card may name. A card is not a report.
MOST_ENTITIES = 50
MOST_LINES = 8


def entity_lines(options: dict[str, Any], name: str = "entity_ids") -> list[tuple[str, str]]:
    """``(entity_id, label)`` per line of a card's list; a line may name its label after a ``|``."""
    found: list[tuple[str, str]] = []
    for line in str(options.get(name) or "").splitlines():
        entity_id, _, label = line.partition("|")
        entity_id = entity_id.strip()
        if entity_id and entity_id not in [one for one, _ in found]:
            found.append((entity_id, label.strip()))
    return found


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def aggregate(how: str, states: list[str]) -> float | None:
    """One number out of the states of several entities; None when there is nothing to make it of."""
    if how == "count":
        return float(len(states))
    if how == "count_on":
        return float(sum(1 for state in states if state in ON_STATES))
    numbers = [number for state in states if (number := as_float(state)) is not None]
    if not numbers:
        return None
    if how == "sum":
        return sum(numbers)
    if how == "min":
        return min(numbers)
    if how == "max":
        return max(numbers)
    return sum(numbers) / len(numbers)


def history_points(changes: list[tuple[float, float | None]], start: float, end: float, count: int = HISTORY_POINTS) -> list[tuple[float, float | None]]:
    """A line of ``count`` points out of the changes Home Assistant recorded.

    A state holds until the next change: a step with no change in it carries
    the last value on, so a thermostat that sat at 21 degrees all night is a
    flat line, not a gap. A step with changes in it shows their mean. Before the
    first known value, and where the state was not a number (unavailable), the
    line has a gap.
    """
    step = (end - start) / count
    points: list[tuple[float, float | None]] = []
    ordered = sorted(changes, key=lambda pair: pair[0])
    index, last = 0, None
    while index < len(ordered) and ordered[index][0] <= start:
        last = ordered[index][1]
        index += 1
    for number in range(count):
        top = start + (number + 1) * step
        inside: list[float | None] = []
        while index < len(ordered) and ordered[index][0] <= top:
            inside.append(ordered[index][1])
            index += 1
        if inside:
            last = inside[-1]
            known = [value for value in inside if value is not None]
            value = sum(known) / len(known) if known else None
        else:
            value = last
        points.append((top, value))
    return points


def decimals(options: dict[str, Any]) -> int | None:
    """How many decimals the card was asked to show, or None for the usual way (#78). A form stores numbers as floats."""
    raw = options.get("decimals")
    if raw is None or raw == "":
        return None
    try:
        return max(0, min(6, int(float(raw))))
    except (TypeError, ValueError):
        return None


class HomeAssistantAdapter(Adapter):
    kind = "homeassistant"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Home Assistant"
    category = "monitoring"
    description = "Any entity as a value or list, switches and scenes as actions, live over WebSocket."
    icon = "home-assistant"
    docs_url = "https://developers.home-assistant.io/docs/api/rest/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://homeassistant:8123"),
        Field("token", "Long-lived access token", type="password", secret=True, required=True, help="Profile > Security > Long-lived access tokens"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="entity",
            label="Entity",
            description="One entity as a big value, with its unit and an on/off action where it applies.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("value",),
            options=(
                Field("entity_id", "Entity ID", required=True, placeholder="sensor.living_room_temperature"),
                Field("label", "Label", placeholder="Living room"),
                Field("attribute", "Attribute instead of state", placeholder="temperature", help="Leave empty to show the state."),
                Field("decimals", "Decimals", type="number", help="Leave empty for as many as the value needs, one below 10."),
            ),
        ),
        WidgetType(
            kind="entities",
            label="Entity list",
            description="Several entities in a list, each with state and action.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=30,
            options=(Field("entity_ids", "Entity IDs", type="textarea", required=True, help="One per line.", placeholder="light.kitchen\nswitch.garden_pump\nsensor.energy_today"),),
        ),
        WidgetType(
            kind="summary",
            label="Several entities as one number",
            description="The sum, average, lowest or highest of several entities, or how many of them are on or open.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("value",),
            options=(
                Field("entity_ids", "Entity IDs", type="textarea", required=True,
                      help="One per line. A group stands for the entities in it.",
                      placeholder="sensor.plug_1_power\nsensor.plug_2_power\ngroup.windows"),
                Field("aggregation", "Calculate", type="select", default="sum", options=AGGREGATIONS),
                Field("label", "Label", placeholder="Power of the plugs"),
                Field("unit", "Unit", placeholder="W", help="Leave empty to take the unit of the entities, when they share one."),
                Field("decimals", "Decimals", type="number", help="Leave empty for as many as the value needs, one below 10."),
            ),
        ),
        WidgetType(
            kind="history",
            label="History chart",
            description="Several entities as lines over the last hour, six hours, day or week, from Home Assistant's history.",
            renderer="timeline",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=300,
            options=(
                Field("entity_ids", "Entity IDs", type="textarea", required=True,
                      help="One per line, up to eight. A name after a | labels the line.",
                      placeholder="sensor.indoor_temperature | Indoor\nsensor.outdoor_temperature | Outdoor"),
                Field("range", "Period", type="select", default="24h",
                      options=(("1h", "1 hour"), ("6h", "6 hours"), ("24h", "24 hours"), ("7d", "7 days"))),
                Field("shape", "Shape", type="select", default="line", options=(("line", "A line"), ("bars", "Bars"))),
            ),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('token', '')}", "Content-Type": "application/json"}

    async def state_of(self, entity_id: str, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        live = ctx.cache.get("hass_states")
        if isinstance(live, dict) and entity_id in live:
            return live[entity_id]
        return await ctx.get_json(f"{base_url(config)}/api/states/{entity_id}", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=5)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await ctx.get_json(f"{base_url(config)}/api/config", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=0)
        return f"Home Assistant {payload.get('version', '?')} ({payload.get('location_name', '?')}) answers."

    async def states(self, config: dict[str, Any], ctx: Context) -> dict[str, dict[str, Any]]:
        """Every state by its entity: from the live connection when it is there, else one REST call for all."""
        live = ctx.cache.get("hass_states")
        if isinstance(live, dict) and live:
            return live
        answer = await ctx.get_json(f"{base_url(config)}/api/states", headers=self._headers(config),
                                    verify=not config.get("insecure"), cache_seconds=10)
        return {str(one.get("entity_id")): one for one in answer or [] if isinstance(one, dict)}

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            return await self._summary(config, options, ctx)
        if widget_kind == "history":
            return await self._history(config, options, ctx)
        if widget_kind == "entity":
            entity_id = str(options.get("entity_id") or "").strip()
            if not entity_id:
                raise AdapterError("No entity ID is set.", code="missing_entity")
            entity = await self.state_of(entity_id, config, ctx)
            return self._entity_widget(entity, options)
        ids = [line.strip() for line in str(options.get("entity_ids") or "").splitlines() if line.strip()]
        if not ids:
            raise AdapterError("No entity IDs are set.", code="missing_entity")
        items = []
        for entity_id in ids:
            try:
                entity = await self.state_of(entity_id, config, ctx)
            except AdapterError:
                items.append({"id": entity_id, "title": entity_id, "subtitle": "not found", "status": "unknown"})
                continue
            attributes = entity.get("attributes") or {}
            state = str(entity.get("state", "?"))
            unit = attributes.get("unit_of_measurement", "")
            items.append({
                "id": entity_id,
                "title": attributes.get("friendly_name") or entity_id,
                "subtitle": entity_id,
                "value": f"{state} {unit}".strip(),
                "status": entity_status(entity_id.split(".", 1)[0], state),
                "actions": [a.model_dump() for a in actions_for(entity_id, state)],
            })
        return WidgetData(items=items)

    def _entity_widget(self, entity: dict[str, Any], options: dict[str, Any]) -> WidgetData:
        attributes = entity.get("attributes") or {}
        entity_id = entity.get("entity_id", "")
        raw = attributes.get(options["attribute"]) if options.get("attribute") else entity.get("state")
        unit = attributes.get("unit_of_measurement", "") if not options.get("attribute") else ""
        metrics: dict[str, float] = {}
        value: Any = raw
        places = decimals(options)
        try:
            number = float(raw)
            metrics["value"] = number
            value = round(number, 2 if places is None else places)
            value = int(value) if float(value).is_integer() else value
        except (TypeError, ValueError):
            value = str(raw)
        state = str(entity.get("state", ""))
        primary = {"label": options.get("label") or attributes.get("friendly_name") or entity_id, "value": value, "unit": unit}
        if places is not None and "value" in metrics:
            primary["decimals"] = places
        return WidgetData(
            status=entity_status(entity_id.split(".", 1)[0], state),
            primary=primary,
            secondary=[{"label": "Updated", "value": str(entity.get("last_changed", ""))[11:16]}],
            metrics=metrics,
            actions=actions_for(entity_id, state),
            meta={"entity_id": entity_id},
        )

    async def _summary(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """Several entities as one number (#82): a group stands for its members, one level deep."""
        named = [entity_id for entity_id, _ in entity_lines(options)]
        if not named:
            raise AdapterError("No entity IDs are set.", code="missing_entity")
        every = await self.states(config, ctx)
        wanted: list[str] = []
        missing: list[str] = []
        for entity_id in named:
            state = every.get(entity_id)
            if state is None:
                missing.append(entity_id)
                continue
            members = (state.get("attributes") or {}).get("entity_id")
            if isinstance(members, list) and members:
                wanted += [str(one) for one in members if str(one) not in wanted]
            elif entity_id not in wanted:
                wanted.append(entity_id)
        wanted = wanted[:MOST_ENTITIES]
        how = str(options.get("aggregation") or "sum")
        how = how if how in dict(AGGREGATIONS) else "sum"
        # Unavailable and unknown are left out of every calculation: a plug that dropped off is not a plug at 0 W.
        usable = [state for entity_id in wanted if (state := every.get(entity_id)) and str(state.get("state")) not in ("unavailable", "unknown")]
        result = aggregate(how, [str(state.get("state")) for state in usable])
        units = {str((state.get("attributes") or {}).get("unit_of_measurement") or "") for state in usable}
        unit = str(options.get("unit") or "") or (units.pop() if len(units) == 1 and how not in ("count", "count_on") else "")
        places = decimals(options)
        primary: dict[str, Any] = {"label": options.get("label") or dict(AGGREGATIONS)[how], "value": None, "unit": unit}
        metrics: dict[str, float] = {}
        if result is not None:
            metrics["value"] = result
            value = round(result, 2 if places is None else places)
            primary["value"] = int(value) if float(value).is_integer() else value
            if places is not None:
                primary["decimals"] = places
        status = "ok" if result is not None else "unknown"
        if missing or len(usable) < len(wanted):
            status = "warn" if result is not None else "unknown"
        secondary = [{"label": "Entities", "value": f"{len(usable)} of {len(wanted)}"}]
        if missing:
            secondary.append({"label": "Not found", "value": ", ".join(missing[:3]) + (" …" if len(missing) > 3 else "")})
        return WidgetData(status=status, primary=primary, secondary=secondary, metrics=metrics)

    async def _history(self, config: dict[str, Any], options: dict[str, Any], ctx: Context, *, now: float | None = None) -> WidgetData:
        """Several entities as lines over a period, from Home Assistant's history (#82).

        ``/api/history/period`` with ``minimal_response``: one list per entity,
        its state at the start of the period first, then every change. Home
        Assistant keeps that history ten days unless its recorder is told
        otherwise, which is why the longest period is a week.
        """
        lines = entity_lines(options)[:MOST_LINES]
        if not lines:
            raise AdapterError("No entity IDs are set.", code="missing_entity")
        period = str(options.get("range") or "24h")
        reach = HISTORY_RANGES.get(period, HISTORY_RANGES["24h"])
        end = dt.datetime.fromtimestamp(time.time() if now is None else now, dt.UTC)
        start = end - reach
        answer = await ctx.get_json(
            f"{base_url(config)}/api/history/period/{start.isoformat(timespec='seconds')}",
            params={"filter_entity_id": ",".join(entity_id for entity_id, _ in lines), "end_time": end.isoformat(timespec="seconds"),
                    "minimal_response": "", "no_attributes": "", "significant_changes_only": "0"},
            headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=60,
        )
        found: dict[str, list[dict[str, Any]]] = {}
        for rows in answer or []:
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                found[str(rows[0].get("entity_id"))] = rows
        every = await self.states(config, ctx)
        drawn = []
        units: set[str] = set()
        first_value: float | None = None
        first_label = ""
        for entity_id, label in lines:
            rows = found.get(entity_id) or []
            changes = []
            for row in rows:
                at = row.get("last_changed") or row.get("last_updated")
                try:
                    moment = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                changes.append((moment, as_float(row.get("state"))))
            state = every.get(entity_id) or {}
            attributes = state.get("attributes") or {}
            name = label or str(attributes.get("friendly_name") or entity_id)
            if not changes:
                continue
            units.add(str(attributes.get("unit_of_measurement") or ""))
            points = history_points(changes, start.timestamp(), end.timestamp())
            drawn.append((entity_id, name, points))
            if first_value is None:
                first_value = as_float(state.get("state"))
                first_label = name
        if not drawn:
            return WidgetData(status="unknown", meta={"empty": "No history in this period"})
        unit = units.pop() if len(units) == 1 else ""
        primary = {"label": first_label, "value": None if first_value is None else round(first_value, 2), "unit": unit}
        missing = [entity_id for entity_id, _ in lines if entity_id not in {one for one, _, _ in drawn}]
        secondary = [{"label": "Not found", "value": ", ".join(missing[:3])}] if missing else []
        return WidgetData(status="warn" if missing else "ok", primary=primary, secondary=secondary,
                          meta=timeline(*drawn, unit=unit, shape=str(options.get("shape") or "line")))

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if "." not in action_id:
            raise AdapterError("Unknown action.", code="no_such_action")
        domain, service = action_id.split(".", 1)
        entity_id = str(params.get("entity_id") or "")
        if not entity_id:
            raise AdapterError("No entity was named.", code="missing_param")
        response = await ctx.request("POST", f"{base_url(config)}/api/services/{domain}/{service}", json_body={"entity_id": entity_id}, headers=self._headers(config), verify=not config.get("insecure"))
        if response.status_code >= 400:
            raise AdapterError(f"Home Assistant answered with HTTP {response.status_code}.", code="http_error")
        return f"{domain}.{service} called for {entity_id}."

    async def impact(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        """What a scene, a group, a script or an automation would set off, read from its own state."""
        entity_id = str(params.get("entity_id") or "")
        domain = entity_id.split(".", 1)[0]
        if domain not in ("scene", "group", "script", "automation"):
            return []
        state = await self.state_of(entity_id, config, ctx)
        attributes = (state.get("attributes") or {}) if isinstance(state, dict) else {}
        facts: list[dict[str, Any]] = []
        members = attributes.get("entity_id")
        if isinstance(members, list) and members:
            facts.append({"fact": "devices", "count": len(members), "names": [str(one) for one in members[:6]]})
        if attributes.get("last_triggered"):
            facts.append({"fact": "last_run", "at": str(attributes["last_triggered"])})
        return facts

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "summary":
            power = round(sum(fake.walk(f"ha-plug{n}", tick, 4, 140, period=600) for n in range(6)), 1)
            return WidgetData(primary={"label": options.get("label") or "Power of the plugs", "value": power, "unit": "W"},
                              secondary=[{"label": "Entities", "value": "6 of 6"}], metrics={"value": power})
        if widget_kind == "history":
            now = time.time()
            reach = HISTORY_RANGES.get(str(options.get("range") or "24h"), HISTORY_RANGES["24h"]).total_seconds()
            step = reach / HISTORY_POINTS
            indoor = [(now - reach + (n + 1) * step, round(21 + math.sin(n / 19) * 0.8, 1)) for n in range(HISTORY_POINTS)]
            outdoor = [(now - reach + (n + 1) * step, round(7 + math.sin(n / 19 - 1) * 4, 1)) for n in range(HISTORY_POINTS)]
            return WidgetData(primary={"label": "Indoor", "value": indoor[-1][1], "unit": "°C"},
                              meta=timeline(("sensor.indoor", "Indoor", indoor), ("sensor.outdoor", "Outdoor", outdoor), unit="°C",
                                            shape=str(options.get("shape") or "line")))
        if widget_kind == "entity":
            temperature = fake.walk("ha-temp", tick, 20.5, 23.1, period=900)
            return WidgetData(primary={"label": options.get("label") or "Living room", "value": temperature, "unit": "°C"},
                              secondary=[{"label": "Updated", "value": "just now"}], metrics={"value": temperature},
                              actions=[Action(id="scene.turn_on", label="Evening scene", icon="lamp", params={"entity_id": "scene.evening"})])
        entities = [("light.kitchen", "Kitchen", "on" if fake.flicker("k", tick, 0.5) else "off", ""), ("switch.garden_pump", "Garden pump", "off", ""), ("sensor.energy_today", "Energy today", f"{fake.walk('e', tick, 4, 19, period=2000):.1f}", "kWh"), ("binary_sensor.front_door", "Front door", "off", ""), ("cover.garage", "Garage", "closed", "")]
        items = [{"id": i, "title": n, "subtitle": i, "value": f"{s} {u}".strip(), "status": entity_status(i.split('.')[0], s), "actions": [a.model_dump() for a in actions_for(i, s)]} for i, n, s, u in entities]
        return WidgetData(items=items)


ADAPTER = HomeAssistantAdapter()
