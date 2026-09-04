"""Home Assistant: any entity as a widget, services as actions.

State comes from the WebSocket listener in ``services.hass_ws`` when it is
connected (instant, no polling) and from the REST API otherwise.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Action, Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url

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


class HomeAssistantAdapter(Adapter):
    kind = "homeassistant"
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

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
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
        try:
            number = float(raw)
            metrics["value"] = number
            value = round(number, 2) if not float(number).is_integer() else int(number)
        except (TypeError, ValueError):
            value = str(raw)
        state = str(entity.get("state", ""))
        return WidgetData(
            status=entity_status(entity_id.split(".", 1)[0], state),
            primary={"label": options.get("label") or attributes.get("friendly_name") or entity_id, "value": value, "unit": unit},
            secondary=[{"label": "Updated", "value": str(entity.get("last_changed", ""))[11:16]}],
            metrics=metrics,
            actions=actions_for(entity_id, state),
            meta={"entity_id": entity_id},
        )

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

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "entity":
            temperature = fake.walk("ha-temp", tick, 20.5, 23.1, period=900)
            return WidgetData(primary={"label": options.get("label") or "Living room", "value": temperature, "unit": "°C"},
                              secondary=[{"label": "Updated", "value": "just now"}], metrics={"value": temperature},
                              actions=[Action(id="scene.turn_on", label="Evening scene", icon="lamp", params={"entity_id": "scene.evening"})])
        entities = [("light.kitchen", "Kitchen", "on" if fake.flicker("k", tick, 0.5) else "off", ""), ("switch.garden_pump", "Garden pump", "off", ""), ("sensor.energy_today", "Energy today", f"{fake.walk('e', tick, 4, 19, period=2000):.1f}", "kWh"), ("binary_sensor.front_door", "Front door", "off", ""), ("cover.garage", "Garage", "closed", "")]
        items = [{"id": i, "title": n, "subtitle": i, "value": f"{s} {u}".strip(), "status": entity_status(i.split('.')[0], s), "actions": [a.model_dump() for a in actions_for(i, s)]} for i, n, s, u in entities]
        return WidgetData(items=items)


ADAPTER = HomeAssistantAdapter()
