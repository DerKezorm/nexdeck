"""openHAB: which things are online, what the rules are doing, and the state of any item.

Measured on 27.10.2026 against openHAB 5.2.3 (``openhab/openhab``) with the
NTP binding installed: things that were online, offline after a failed lookup
and disabled, a working and a broken rule, and items of the types Switch,
Dimmer, Contact, String, Group, Number:Temperature and Number:Power, with and
without a token and with a wrong one.

⚠️ Reading needs less than it looks like. ``/rest/`` and ``/rest/items`` answer
without a token on a fresh installation, but ``/rest/things``, ``/rest/rules``
and ``/rest/systeminfo`` answer 401 "Authentication required" to everybody who
is not an administrator. The cards that need a token say so; the ones that read
items work without one.

⚠️ A missing token and a wrong one are both 401. The message tells them apart:
"Authentication required" against "Invalid credentials".

⚠️ A quantity item's state already carries its unit: ``"21.5 °C"``, ``"412 W"``.
The label of an item made in a file carries the display pattern in brackets
(``"Power [%.0f W]"``), which is no part of the name.

⚠️ A thing that was switched off is ``UNINITIALIZED`` with the detail
``DISABLED``, which is a choice and not a fault. Every other ``UNINITIALIZED``
is one (a missing handler, a wrong configuration). A thing that lost its device
is ``OFFLINE`` with ``COMMUNICATION_ERROR`` and the binding's own words in
``description``.

⚠️ An item nobody has set is ``NULL``, and one whose binding lost its value
``UNDEF``. Neither is a number, a switch position or a zero.

⚠️ ``POST /rest/items/{name}`` with the plain text ``ON`` is a command, and
answers 200 with an empty body. Only a Switch is offered one here.
"""

from __future__ import annotations

import re
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    measured,
    path_segment,
)

TOKEN_HINT = "Make an API token in openHAB under your profile (bottom left), API Tokens, as an administrator."
ADDRESS_HINT = "Check the URL; it is the address openHAB's web interface opens at, usually port 8080."
#: The fields of an item the cards read, so a big installation does not send every metadata block.
ITEM_FIELDS = "name,label,type,state,category,groupNames,stateDescription,editable"
#: What an item says in words.
WORDS = {"ON": "On", "OFF": "Off", "OPEN": "Open", "CLOSED": "Closed", "NULL": "?", "UNDEF": "?"}
PLAYER = {"PLAY": "Playing", "PAUSE": "Paused", "NEXT": "Next", "PREVIOUS": "Previous"}
NUMBER = re.compile(r"^(-?\d+(?:\.\d+)?)(?:\s+(.+))?$")
PATTERN = re.compile(r"\s*\[[^\]]*\]\s*$")


def _clean(label: Any, name: str) -> str:
    """The label without the display pattern in brackets, or the name when there is none."""
    return PATTERN.sub("", str(label or "")).strip() or name


def _kind(item: dict[str, Any]) -> str:
    return str(item.get("type") or "").split(":", 1)[0]


def _show(item: dict[str, Any]) -> str:
    """The state of an item as a short text."""
    state = str(item.get("state") if item.get("state") is not None else "").strip()
    if state in WORDS:
        return WORDS[state]
    kind = _kind(item)
    if kind in ("Dimmer", "Rollershutter") and NUMBER.match(state):
        return f"{state}%"
    if kind == "Player":
        return PLAYER.get(state, state.title())
    found = NUMBER.match(state)
    if found and "." in found.group(1):
        # A binding may send twelve decimals.
        number = f"{float(found.group(1)):.2f}".rstrip("0").rstrip(".")
        return f"{number} {found.group(2)}" if found.group(2) else number
    return state if len(state) <= 60 else state[:57] + "..."


def _number(item: dict[str, Any]) -> tuple[float, str] | None:
    """A number and its unit, for an item that has one."""
    found = NUMBER.match(str(item.get("state") or "").strip())
    if not found or _kind(item) in ("Switch", "Contact", "String", "DateTime", "Player"):
        return None
    return float(found.group(1)), (found.group(2) or ("%" if _kind(item) in ("Dimmer", "Rollershutter") else ""))


def _thing_word(thing: dict[str, Any]) -> tuple[str, str]:
    """A thing's state as the card's word and its colour."""
    info = thing.get("statusInfo") if isinstance(thing.get("statusInfo"), dict) else {}
    status, detail = str(info.get("status") or ""), str(info.get("statusDetail") or "")
    if status == "ONLINE":
        return "Online", "ok"
    if status == "OFFLINE":
        return "Offline", "bad"
    if status == "UNINITIALIZED":
        return ("Disabled", "unknown") if detail == "DISABLED" else ("Not started", "bad")
    if status == "INITIALIZING":
        return "Starting", "warn"
    if status in ("REMOVING", "REMOVED"):
        return "Removed", "unknown"
    return "Unknown", "warn"


def _detail(thing: dict[str, Any]) -> str:
    info = thing.get("statusInfo") if isinstance(thing.get("statusInfo"), dict) else {}
    detail = str(info.get("statusDetail") or "")
    words = "" if detail in ("", "NONE", "DISABLED") else detail.replace("_", " ").capitalize()
    description = " ".join(str(info.get("description") or "").split())
    if len(description) > 100:
        description = description[:97] + "..."
    return " · ".join(part for part in (words, description) if part)


class OpenHabAdapter(Adapter):
    kind = "openhab"
    label = "openHAB"
    category = "other"
    description = "Which things are online, whether the rules run, and the state of any item, with a switch where it is one."
    icon = "openhab"
    beta = True
    docs_url = "https://www.openhab.org/docs/configuration/restdocs.html"
    keywords = ("smart home", "home automation")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://openhab:8080"),
        Field("token", "API token", type="password", secret=True,
              help="From your profile in openHAB, API Tokens, as an administrator. Items can be read without one, things and rules cannot."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview", label="openHAB overview",
            description="How many things are online and offline, how many items and rules there are, and whether a rule failed to start. Needs a token.",
            renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("things_online", "things_offline"),
            parts=(("offline", "Offline"), ("items", "Items"), ("rules", "Rules")),
        ),
        WidgetType(
            kind="trouble", label="Things needing a look",
            description="The things that are offline, did not start or are still starting, worst first, with the reason. Disabled ones come last. Needs a token.",
            renderer="list", default_size=(3, 3), refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="items", label="Items",
            description="The state of your items, with a switch on those that are one. Name a group to show only its items.",
            renderer="list", default_size=(3, 3), refresh_seconds=30,
            options=(
                Field("group", "Group", help="The name of a group; empty shows every item that is not a group."),
                Field("limit", "Entries", type="number", default=12),
            ),
        ),
        WidgetType(
            kind="item", label="Item",
            description="One item as a big number with its history, or as a switch. Use it for power, temperature or a light.",
            renderer="value", default_size=(2, 2), refresh_seconds=30, metrics=("value",),
            options=(Field("item", "Item", type="choices", required=True),),
        ),
    )

    # -- talking to openHAB --------------------------------------------------

    async def _call(self, config: dict[str, Any], ctx: Context, path: str, *, method: str = "GET", body: str | None = None,
                    allow: tuple[int, ...] = (), cache: float = 0) -> Any:
        token = str(config.get("token") or "").strip()
        headers = {"Accept": "application/json"}
        if token:
            headers["X-OPENHAB-TOKEN"] = token
        if body is not None:
            headers["Content-Type"] = "text/plain"
        response = await ctx.request(
            method, f"{base_url(config)}/rest{path}", headers=headers, content=body.encode() if body is not None else None,
            verify=not config.get("insecure"), timeout=10.0, cache_seconds=cache if method == "GET" else 0, auth_errors=False)
        if response.status_code in (401, 403):
            raise self._refused(response, bool(token))
        if response.status_code >= 400 and response.status_code not in allow:
            raise AdapterError(f"openHAB answered with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
        if response.status_code in allow and response.status_code >= 400:
            return None
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than openHAB.", code="not_openhab", hint=ADDRESS_HINT) from error

    @staticmethod
    def _refused(response: Any, had_token: bool) -> AdapterError:
        """Say which refusal it was.

        ⚠️ No token and a wrong token are both 401; only the text differs. A token of a user without the
        administrator role is 403.
        """
        try:
            text = str(response.json().get("error", {}).get("message") or "")
        except (ValueError, AttributeError):
            text = ""
        if response.status_code == 403:
            error: AdapterError = AdapterError("This token's user may not read that.", code="forbidden",
                                               hint="Make the token as an administrator; things and rules are for administrators only.")
        elif not had_token:
            error = AuthFailed("This needs an API token.")
            error.hint = TOKEN_HINT
        elif "invalid" in text.lower():
            error = AuthFailed("openHAB does not know this API token.")
            error.hint = TOKEN_HINT
        else:
            error = AuthFailed("openHAB asked for a sign-in this token does not give.")
            error.hint = TOKEN_HINT
        return error

    async def _things(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        things = await self._call(config, ctx, "/things", cache=10)
        if not isinstance(things, list):
            raise AdapterError("This address answers, but not the way openHAB does.", code="not_openhab", hint=ADDRESS_HINT)
        return [thing for thing in things if isinstance(thing, dict)]

    async def _items(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        items = await self._call(config, ctx, f"/items?fields={ITEM_FIELDS}", cache=5)
        if not isinstance(items, list):
            raise AdapterError("This address answers, but not the way openHAB does.", code="not_openhab", hint=ADDRESS_HINT)
        return [item for item in items if isinstance(item, dict) and item.get("name")]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        root = await self._call(config, ctx, "/")
        runtime = root.get("runtimeInfo") if isinstance(root, dict) and isinstance(root.get("runtimeInfo"), dict) else None
        if runtime is None:
            raise AdapterError("This address answers, but not the way openHAB does.", code="not_openhab", hint=ADDRESS_HINT)
        name = f"openHAB {runtime['version']}" if runtime.get("version") else "openHAB"
        items = await self._items(config, ctx)
        if not str(config.get("token") or "").strip():
            return f"{name} answers with {len(items)} items. Add an API token to read things and rules."
        # A wrong token must fail here and not on the first card.
        things = await self._things(config, ctx)
        return f"{name} answers with {len(things)} things and {len(items)} items."

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "item":
            return await super().choices(field, config, ctx)
        items = await self._items(config, ctx)
        return sorted(((str(item["name"]), f"{_clean(item.get('label'), str(item['name']))} ({item['name']})")
                       for item in items if item.get("type") != "Group"), key=lambda pair: pair[1].lower())

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        return [("Living_Temp", "Living room temperature (Living_Temp)"), ("Power_Now", "Power (Power_Now)")] if field == "item" else []

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "overview":
            return self._overview(await self._things(config, ctx), len(await self._items(config, ctx)),
                                  await self._call(config, ctx, "/rules", cache=10))
        if widget_kind == "trouble":
            return self._trouble(await self._things(config, ctx), options)
        if widget_kind == "items":
            return self._items_card(await self._items(config, ctx), options)
        name = path_segment(options.get("item"), "The item")
        item = await self._call(config, ctx, f"/items/{name}?recursive=false", allow=(404,), cache=3)
        if item is None:
            raise AdapterError(f"openHAB has no item called {name}.", code="no_item", hint="Pick the item again in the card's settings.")
        return self._item_card(item)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("on", "off"):
            raise AdapterError("Unknown item action.", code="no_such_action")
        name = path_segment(params.get("item"), "The item")
        await self._call(config, ctx, f"/items/{name}", method="POST", body=action_id.upper())
        ctx.forget_answers()
        return "Switched on." if action_id == "on" else "Switched off."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _overview(things: list[dict[str, Any]], items: int, rules: Any) -> WidgetData:
        words = [_thing_word(thing) for thing in things]
        online = sum(1 for word, _ in words if word == "Online")
        offline = sum(1 for word, colour in words if colour == "bad")
        waiting = sum(1 for word, colour in words if colour == "warn")
        rule_list = [rule for rule in rules if isinstance(rule, dict)] if isinstance(rules, list) else []
        # ⚠️ A disabled rule is UNINITIALIZED too, and is a choice.
        broken = sum(1 for rule in rule_list if isinstance(rule.get("status"), dict)
                     and rule["status"].get("status") == "UNINITIALIZED" and rule["status"].get("statusDetail") != "DISABLED")
        secondary: list[dict[str, Any]] = [{"label": "Offline", "value": offline, "part": "offline"},
                                           {"label": "Items", "value": items, "part": "items"},
                                           {"label": "Rules", "value": len(rule_list), "part": "rules"}]
        if broken:
            secondary.append({"label": "Rules not running", "value": broken, "part": "rules"})
        return WidgetData(
            status="bad" if offline else "warn" if waiting or broken else "ok",
            primary={"label": "Things online", "value": online},
            secondary=secondary,
            metrics={"things_online": float(online), "things_offline": float(offline)},
        )

    @staticmethod
    def _trouble(things: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        try:
            limit = max(1, min(50, int(options.get("limit") or 8)))
        except (TypeError, ValueError):
            limit = 8
        order = {"bad": 0, "warn": 1, "unknown": 2}
        rows = []
        for thing in things:
            word, colour = _thing_word(thing)
            if colour == "ok":
                continue
            rows.append((order.get(colour, 3), str(thing.get("label") or thing.get("UID") or "?"), {
                "id": thing.get("UID"), "title": str(thing.get("label") or thing.get("UID") or "?"),
                "subtitle": _detail(thing), "value": word, "status": colour}))
        rows.sort(key=lambda row: (row[0], row[1].lower()))
        offline = sum(1 for row in rows if row[2]["status"] == "bad")
        return WidgetData(
            status="bad" if offline else "warn" if any(row[2]["status"] == "warn" for row in rows) else "ok",
            items=[row[2] for row in rows[:limit]],
            secondary=[{"label": "Things", "value": len(things)}],
            meta={"empty": "All things are online."},
        )

    @staticmethod
    def _row_actions(item: dict[str, Any]) -> list[Action]:
        if item.get("type") != "Switch" or item.get("editable") is False:
            return []
        on = str(item.get("state")) == "ON"
        return [Action(id="off" if on else "on", label="Turn off" if on else "Turn on", icon="power", confirm=True,
                       params={"item": str(item["name"])})]

    @classmethod
    def _items_card(cls, items: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        group = str(options.get("group") or "").strip()
        try:
            limit = max(1, min(100, int(options.get("limit") or 12)))
        except (TypeError, ValueError):
            limit = 12
        if group:
            chosen = [item for item in items if group in (item.get("groupNames") or [])]
        else:
            chosen = [item for item in items if item.get("type") != "Group"]
        chosen.sort(key=lambda item: _clean(item.get("label"), str(item["name"])).lower())
        rows = []
        for item in chosen[:limit]:
            name = str(item["name"])
            unknown = str(item.get("state")) in ("NULL", "UNDEF", "None", "")
            rows.append({
                "id": name, "title": _clean(item.get("label"), name), "value": _show(item),
                "status": "unknown" if unknown else "ok", "actions": cls._row_actions(item),
            })
        return WidgetData(
            items=rows, secondary=[{"label": "Items", "value": len(chosen)}],
            meta={"empty": "No item matches.", "actions_visible": True},
        )

    @classmethod
    def _item_card(cls, item: dict[str, Any]) -> WidgetData:
        name = str(item.get("name") or "?")
        title = _clean(item.get("label"), name)
        unknown = str(item.get("state")) in ("NULL", "UNDEF")
        found = _number(item)
        secondary: list[dict[str, Any]] = []
        changed = item.get("lastStateChange")
        if isinstance(changed, int | float) and changed > 0:
            # Milliseconds since the epoch.
            moment = ago(changed / 1000)
            if moment:
                secondary.append({"label": "Changed", "value": moment})
        if found is not None and not unknown:
            primary: dict[str, Any] = {"label": title, "value": round(found[0], 2), "unit": found[1]}
        else:
            primary = {"label": title, "value": _show(item)}
        return WidgetData(
            status="unknown" if unknown else "ok", primary=primary, secondary=secondary,
            actions=cls._row_actions(item), metrics=measured({"value": found[0] if found is not None and not unknown else None}),
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        offline = 1 if fake.flicker("openhab-offline", tick, 0.5) else 0
        # Built from tuples: the names are the demo's own, and a card's words are what the translation tables are for.
        things = [
            {"UID": uid, "label": name, "statusInfo": {"status": status, "statusDetail": detail, "description": why}}
            for uid, name, status, detail, why in (
                ("hue:bridge:1", "Hue bridge", "ONLINE", "NONE", ""),
                ("zwave:node:7", "Hall motion sensor", "ONLINE", "NONE", ""),
                ("mqtt:topic:3", "Garage door", "OFFLINE" if offline else "ONLINE", "COMMUNICATION_ERROR" if offline else "NONE",
                 "Connection to the broker lost" if offline else ""),
                ("ntp:ntp:old", "Old time server", "UNINITIALIZED", "DISABLED", ""),
            )
        ]
        power = round(fake.walk("openhab-power", tick, 180, 2400, period=300))
        temp = fake.walk("openhab-temp", tick, 19.5, 23.5, period=500)
        light = "ON" if fake.flicker("openhab-light", tick, 0.6) else "OFF"
        items = [
            {"name": name, "label": label, "type": kind, "state": state, "editable": editable}
            for name, label, kind, state, editable in (
                ("Living_Light", "Living room light", "Switch", light, True),
                ("Living_Temp", "Living room temperature [%.1f °C]", "Number:Temperature", f"{temp} °C", False),
                ("Power_Now", "Power [%.0f W]", "Number:Power", f"{power} W", False),
                ("Front_Door", "Front door", "Contact", "CLOSED", False),
                ("Bedroom_Dimmer", "Bedroom lamp", "Dimmer", "35", True),
            )
        ]
        if widget_kind == "overview":
            return self._overview(things, 64, [{"status": {"status": "IDLE"}}] * 11)
        if widget_kind == "trouble":
            return self._trouble(things, options)
        if widget_kind == "items":
            return self._items_card(items, options)
        card = self._item_card(next((item for item in items if item["name"] == options.get("item")), items[2]))
        card.secondary = [{"label": "Changed", "value": f"{1 + tick % 50} min"}]
        return card


ADAPTER = OpenHabAdapter()
