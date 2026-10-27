"""Homebridge: whether it runs, what its plugins want, and the state of the accessories it bridges to HomeKit.

Measured on 27.10.2026 against Homebridge 2.4.0 with Homebridge UI 5.29.0
(``homebridge/homebridge``) and the plugin homebridge-dummy 2.1.3, which gave
a switch, a lamp, an outlet, a temperature and a contact sensor: first start
before the setup wizard, a user made by the wizard, the sign-in with a right
and a wrong password, no token and a made-up one, and a switch turned on.

⚠️ A wrong password and a user that does not exist are both 403 "Forbidden",
not 401. A missing or made-up token is 401. Before the setup wizard has made
the first user, every sign-in is 403 too.

⚠️ The token lives eight hours (``expires_in`` 28800). It is kept and renewed
shortly before it runs out, and once more when a card is turned down with 401
(Homebridge restarts with a new secret now and then). Cards of one connection
refresh within the same second, so only one of them signs in.

⚠️ ``/api/accessories`` answers only when Homebridge runs in insecure mode
(``-I``, which the Docker image and the hb-service installs use by default). It
lists services, not accessories: one bridge with a thermostat that also
measures humidity is two entries, and the bridge itself is one more
(``ProtocolInformation``, left out here).

⚠️ ``values`` holds numbers for booleans: ``{"On": 1}``. ``ContactSensorState``
is 0 for a closed contact and 1 for an open one, the other way round from what
the word "detected" suggests.

⚠️ A made-up ``uniqueId`` on ``PUT /api/accessories/{id}`` is 400, not 404.

⚠️ ``/api/status/homebridge`` says ``{"status": "ok"}`` here, and the UI's own
code also knows ``up``, ``pending`` and ``down``.

⚠️ When the UI runs without a sign-in (``formAuth: false`` in
``/api/auth/settings``) the token is asked for with a POST to ``/api/auth/noauth``
and no body. Not measured, from the UI's source and documentation.
"""

from __future__ import annotations

import asyncio
import time
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
    base_url,
    duration_short,
    measured,
    path_segment,
)

ADDRESS_HINT = "Check the URL; it is the address Homebridge's web interface opens at, usually port 8581."
#: How long a refused sign-in is remembered, so a wrong password is not tried every refresh.
REFUSAL_SECONDS = 300
#: Renew a token this long before it runs out.
RENEW_BEFORE = 120
#: What Homebridge calls a good state.
UP = ("ok", "up")
#: Services that are the bridge itself, not something in the house.
NOT_AN_ACCESSORY = ("ProtocolInformation", "AccessoryInformation")
OPEN_CLOSED = {0: "Closed", 1: "Open"}
LOCKS = {0: "Unlocked", 1: "Locked", 2: "Jammed", 3: "Unknown"}
#: What a sensor says when it is triggered and when it is not, with the colour of the first.
TRIGGERS = {
    "MotionDetected": ("Motion", "Clear", "warn"),
    "OccupancyDetected": ("Occupied", "Empty", "ok"),
    "LeakDetected": ("Leak", "Dry", "bad"),
    "SmokeDetected": ("Smoke", "Clear", "bad"),
    "CarbonMonoxideDetected": ("Carbon monoxide", "Clear", "bad"),
    "CarbonDioxideDetected": ("Carbon dioxide", "Clear", "bad"),
}
SWITCHES = ("Switch", "Outlet", "Lightbulb", "Fan", "Fanv2")


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _shown(accessory: dict[str, Any]) -> tuple[str, str, float | None, str]:
    """What an accessory says: the text, its colour, a number for the history and its unit."""
    values = accessory.get("values") if isinstance(accessory.get("values"), dict) else {}
    on = values.get("On")
    if "CurrentTemperature" in values and _number(values["CurrentTemperature"]) is not None:
        number = round(float(values["CurrentTemperature"]), 1)
        return f"{number} °C", "ok", number, "°C"
    if "CurrentRelativeHumidity" in values and _number(values["CurrentRelativeHumidity"]) is not None:
        number = round(float(values["CurrentRelativeHumidity"]), 1)
        return f"{number:g} %", "ok", number, "%"
    if "ContactSensorState" in values:
        return OPEN_CLOSED.get(int(values["ContactSensorState"] or 0), "Open"), "ok", None, ""
    for key, (yes, no, colour) in TRIGGERS.items():
        if key in values:
            triggered = bool(values[key])
            return (yes if triggered else no), (colour if triggered else "ok"), None, ""
    if "LockCurrentState" in values:
        state = int(values["LockCurrentState"] or 0)
        return LOCKS.get(state, "Unknown"), "bad" if state == 2 else "ok", None, ""
    if "CurrentPosition" in values and _number(values["CurrentPosition"]) is not None:
        number = float(values["CurrentPosition"])
        return f"{number:g}%", "ok", number, "%"
    if on is not None:
        brightness = _number(values.get("Brightness"))
        if on and brightness is not None:
            return f"{brightness:g}%", "ok", brightness, "%"
        return ("On" if on else "Off"), "ok", None, ""
    if "Active" in values:
        return ("On" if values["Active"] else "Off"), "ok", None, ""
    first = next(iter(values.items()), None)
    if first is None:
        return "?", "unknown", None, ""
    number = _number(first[1])
    return (f"{number:g}" if number is not None else str(first[1])), "ok", number, ""


def _name(accessory: dict[str, Any]) -> str:
    return str(accessory.get("serviceName") or (accessory.get("accessoryInformation") or {}).get("Name") or accessory.get("type") or "?")


def _toggle(accessory: dict[str, Any]) -> list[Action]:
    """A switch to press, on a service that has an On that can be written."""
    if accessory.get("type") not in SWITCHES or not accessory.get("uniqueId"):
        return []
    writable = any(isinstance(c, dict) and c.get("type") == "On" and c.get("canWrite") for c in accessory.get("serviceCharacteristics") or [])
    if not writable:
        return []
    on = bool((accessory.get("values") or {}).get("On"))
    return [Action(id="off" if on else "on", label="Turn off" if on else "Turn on", icon="power", confirm=True,
                   params={"accessory": str(accessory["uniqueId"])})]


class HomebridgeAdapter(Adapter):
    kind = "homebridge"
    label = "Homebridge"
    category = "other"
    description = "Whether Homebridge runs, which plugins have an update, and the state of the accessories it gives to HomeKit, with a switch where it is one."
    icon = "homebridge"
    beta = True
    docs_url = "https://github.com/homebridge/homebridge-config-ui-x/wiki/Homebridge-UI-API"
    keywords = ("HomeKit", "smart home")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://homebridge:8581"),
        Field("username", "User", help="The user of Homebridge's web interface. Empty if it runs without a sign-in."),
        Field("password", "Password", type="password", secret=True,
              help="Homebridge's two-factor sign-in is not spoken here; use a user that has none."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status", label="Homebridge",
            description="Whether Homebridge runs, its version, the load and memory of the machine it runs on, and how long it has been up.",
            renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("cpu", "memory"),
            parts=(("version", "Version"), ("cpu", "Load"), ("memory", "Memory"), ("uptime", "Up for")),
        ),
        WidgetType(
            kind="plugins", label="Plugins",
            description="The installed plugins, those with an update first.",
            renderer="list", default_size=(3, 3), refresh_seconds=3600,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="accessories", label="Accessories",
            description="The state of the accessories Homebridge gives to HomeKit, with a switch on those that are one. Needs insecure mode, which Homebridge's Docker image and hb-service use.",
            renderer="list", default_size=(3, 3), refresh_seconds=30,
            options=(Field("limit", "Entries", type="number", default=12),),
        ),
        WidgetType(
            kind="accessory", label="Accessory",
            description="One accessory as a big number with its history, or as a switch. Use it for a temperature, a humidity or a light.",
            renderer="value", default_size=(2, 2), refresh_seconds=30, metrics=("value",),
            options=(Field("accessory", "Accessory", type="choices", required=True),),
        ),
    )

    # -- talking to Homebridge -----------------------------------------------

    def _signs_in(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("username") or "").strip())

    async def _raw(self, config: dict[str, Any], ctx: Context, method: str, path: str, *, token: str = "", json_body: Any = None,
                   cache: float = 0) -> Any:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return await ctx.request(
            method, f"{base_url(config)}/api{path}", headers=headers, json_body=json_body, verify=not config.get("insecure"),
            timeout=15.0, cache_seconds=cache if method == "GET" else 0, auth_errors=False)

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        """The bearer token, signing in when there is none worth keeping.

        ⚠️ One sign-in at a time per connection, and a refusal is remembered for a while: a wrong password tried on
        every refresh of every card is how an account gets locked.
        """
        kept = ctx.cache.get("homebridge_token")
        if kept and not force and kept[0] > time.monotonic():
            return str(kept[1])
        lock = ctx.cache.setdefault("homebridge_login_lock", asyncio.Lock())
        async with lock:
            kept = ctx.cache.get("homebridge_token")
            if kept and not force and kept[0] > time.monotonic():
                return str(kept[1])
            refused = ctx.cache.get("homebridge_refused")
            if refused and refused[0] > time.monotonic():
                raise AuthFailed(str(refused[1]))
            if self._signs_in(config):
                response = await self._raw(config, ctx, "POST", "/auth/login", json_body={
                    "username": str(config.get("username") or "").strip(), "password": str(config.get("password") or "")})
            else:
                settings = await self._raw(config, ctx, "GET", "/auth/settings")
                try:
                    form = settings.json().get("formAuth", True) if settings.status_code == 200 else True
                except (ValueError, AttributeError):
                    form = True
                if form:
                    error = AuthFailed("Homebridge asks for a sign-in.")
                    error.hint = "Fill in the user and the password of Homebridge's web interface."
                    raise error
                response = await self._raw(config, ctx, "POST", "/auth/noauth")
            if response.status_code in (401, 403):
                message = "Homebridge turned the user or the password down."
                ctx.cache["homebridge_refused"] = (time.monotonic() + REFUSAL_SECONDS, message)
                error = AuthFailed(message)
                error.hint = "Check the user and the password; before the setup wizard has made a first user nothing signs in."
                raise error
            if response.status_code == 412:
                raise AdapterError("This user has two-factor sign-in on.", code="two_factor",
                                   hint="Make a user without it for nexdeck in Homebridge under Users.")
            if response.status_code >= 400:
                raise AdapterError(f"Homebridge answered the sign-in with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
            try:
                body = response.json()
                token = str(body["access_token"])
                lifetime = float(body.get("expires_in") or 3600)
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise AdapterError("This address answers the sign-in, but not the way Homebridge does.", code="not_homebridge",
                                   hint=ADDRESS_HINT) from error
            ctx.cache.pop("homebridge_refused", None)
            ctx.cache["homebridge_token"] = (time.monotonic() + max(60.0, lifetime - RENEW_BEFORE), token)
            return token

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, path: str, *, json_body: Any = None, cache: float = 0,
                    retry: bool = True) -> Any:
        token = await self._token(config, ctx)
        response = await self._raw(config, ctx, method, path, token=token, json_body=json_body, cache=cache)
        if response.status_code == 401 and retry:
            # A token from before Homebridge restarted is turned down like a made-up one.
            ctx.forget_answers()
            await self._token(config, ctx, force=True)
            return await self._call(config, ctx, method, path, json_body=json_body, cache=0, retry=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Homebridge turned this user down.")
        if response.status_code >= 400:
            message = ""
            try:
                body = response.json()
                message = str(body.get("message") if isinstance(body, dict) else "")
            except ValueError:
                pass
            raise AdapterError(f"Homebridge answered with HTTP {response.status_code}{': ' + message if message else ''}.",
                               code="http_error", hint=ADDRESS_HINT)
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than Homebridge.", code="not_homebridge", hint=ADDRESS_HINT) from error

    async def _accessories(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        listed = await self._call(config, ctx, "GET", "/accessories", cache=5)
        if not isinstance(listed, list):
            raise AdapterError("This address answers, but not the way Homebridge does.", code="not_homebridge", hint=ADDRESS_HINT)
        return [one for one in listed if isinstance(one, dict) and one.get("type") not in NOT_AN_ACCESSORY]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        response = await self._raw(config, ctx, "GET", "/auth/settings")
        try:
            env = response.json().get("env") if response.status_code == 200 else None
        except ValueError:
            env = None
        if not isinstance(env, dict) or "packageVersion" not in env:
            raise AdapterError("This address answers, but not the way Homebridge's web interface does.", code="not_homebridge", hint=ADDRESS_HINT)
        status = await self._call(config, ctx, "GET", "/status/homebridge")
        word = str(status.get("status") if isinstance(status, dict) else "") or "unknown"
        return f"Homebridge {env.get('homebridgeVersion') or '?'} answers, web interface {env['packageVersion']}. Status: {word}."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        response = await self._raw(config, ctx, "GET", "/auth/settings", cache=60)
        try:
            return str(response.json()["env"]["homebridgeVersion"]) if response.status_code == 200 else None
        except (ValueError, KeyError, TypeError):
            return None

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "accessory":
            return await super().choices(field, config, ctx)
        return sorted(((str(one["uniqueId"]), f"{_name(one)} ({one.get('humanType') or one.get('type')})")
                       for one in await self._accessories(config, ctx) if one.get("uniqueId")), key=lambda pair: pair[1].lower())

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        return [("demo-temp", "Living room temperature (Temperature Sensor)"), ("demo-lamp", "Lamp (Lightbulb)")] if field == "accessory" else []

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "status":
            async def get(path: str) -> Any:
                return await self._call(config, ctx, "GET", path, cache=10)
            status, version, cpu, ram, uptime = await asyncio.gather(
                get("/status/homebridge"), get("/status/homebridge-version"), get("/status/cpu"), get("/status/ram"),
                get("/status/uptime"))
            return self._status_card(status, version, cpu, ram, uptime)
        if widget_kind == "plugins":
            return self._plugins_card(await self._call(config, ctx, "GET", "/plugins", cache=300), options)
        accessories = await self._accessories(config, ctx)
        if widget_kind == "accessories":
            return self._accessories_card(accessories, options)
        wanted = path_segment(options.get("accessory"), "The accessory")
        one = next((item for item in accessories if item.get("uniqueId") == wanted), None)
        if one is None:
            raise AdapterError("Homebridge has no such accessory any more.", code="no_accessory",
                               hint="Pick the accessory again in the card's settings; an accessory that was added again gets a new number.")
        return self._accessory_card(one)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("on", "off"):
            raise AdapterError("Unknown accessory action.", code="no_such_action")
        unique = path_segment(params.get("accessory"), "The accessory")
        await self._call(config, ctx, "PUT", f"/accessories/{unique}", json_body={"characteristicType": "On", "value": action_id == "on"})
        ctx.forget_answers()
        return "Switched on." if action_id == "on" else "Switched off."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _status_card(status: Any, version: Any, cpu: Any, ram: Any, uptime: Any) -> WidgetData:
        word = str(status.get("status") if isinstance(status, dict) else "").lower()
        running = "Running" if word in UP else "Starting" if word == "pending" else "Stopped" if word == "down" else "Unknown"
        colour = "ok" if word in UP else "warn" if word == "pending" else "bad" if word == "down" else "unknown"
        installed = str(version.get("installedVersion") or "") if isinstance(version, dict) else ""
        load = _number(cpu.get("currentLoad")) if isinstance(cpu, dict) else None
        memory = ram.get("mem") if isinstance(ram, dict) and isinstance(ram.get("mem"), dict) else {}
        total, available = _number(memory.get("total")), _number(memory.get("available"))
        used = round((total - available) / total * 100, 1) if total and available is not None else None
        seconds = _number((uptime.get("time") or {}).get("uptime")) if isinstance(uptime, dict) and isinstance(uptime.get("time"), dict) else None
        behind = isinstance(version, dict) and bool(version.get("updateAvailable"))
        secondary: list[dict[str, Any]] = []
        if installed:
            secondary.append({"label": "Version", "value": f"{installed} → {version.get('latestVersion')}" if behind else installed, "part": "version"})
        if load is not None:
            secondary.append({"label": "Load", "value": f"{load:.0f} %", "part": "cpu"})
        if used is not None:
            secondary.append({"label": "Memory", "value": f"{used:.0f} %", "part": "memory"})
        if seconds is not None:
            secondary.append({"label": "Up for", "value": duration_short(seconds), "part": "uptime"})
        return WidgetData(
            status=colour,
            primary={"label": "Homebridge", "value": running},
            secondary=secondary,
            metrics=measured({"cpu": round(load, 1) if load is not None else None, "memory": used}),
        )

    @staticmethod
    def _plugins_card(plugins: Any, options: dict[str, Any]) -> WidgetData:
        try:
            limit = max(1, min(50, int(options.get("limit") or 10)))
        except (TypeError, ValueError):
            limit = 10
        listed = [one for one in plugins if isinstance(one, dict)] if isinstance(plugins, list) else []
        listed.sort(key=lambda one: (not one.get("updateAvailable"), str(one.get("displayName") or one.get("name")).lower()))
        rows = []
        for one in listed[:limit]:
            behind = bool(one.get("updateAvailable"))
            installed = str(one.get("installedVersion") or "")
            rows.append({
                "id": one.get("name"), "title": str(one.get("displayName") or one.get("name") or "?"),
                "subtitle": f"{installed} → {one.get('latestVersion')}" if behind else installed,
                "value": "Update" if behind else ("Disabled" if one.get("disabled") else ""),
                "status": "warn" if behind else "unknown" if one.get("disabled") else "ok",
            })
        waiting = sum(1 for one in listed if one.get("updateAvailable"))
        return WidgetData(
            status="warn" if waiting else "ok", items=rows,
            secondary=[{"label": "Plugins", "value": len(listed)}, *([{"label": "Updates", "value": waiting}] if waiting else [])],
            meta={"empty": "No plugin installed."},
        )

    @staticmethod
    def _accessories_card(accessories: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        try:
            limit = max(1, min(100, int(options.get("limit") or 12)))
        except (TypeError, ValueError):
            limit = 12
        ordered = sorted(accessories, key=lambda one: _name(one).lower())
        rows = []
        for one in ordered[:limit]:
            text, colour, _, _ = _shown(one)
            rows.append({"id": one.get("uniqueId"), "title": _name(one), "subtitle": str(one.get("humanType") or ""), "value": text,
                         "status": colour, "actions": _toggle(one)})
        return WidgetData(items=rows, secondary=[{"label": "Accessories", "value": len(accessories)}],
                          meta={"empty": "No accessory. Homebridge has to run in insecure mode for this card.", "actions_visible": True})

    @staticmethod
    def _accessory_card(one: dict[str, Any]) -> WidgetData:
        text, colour, number, unit = _shown(one)
        primary: dict[str, Any] = {"label": _name(one), "value": number, "unit": unit} if number is not None and unit else {"label": _name(one), "value": text}
        return WidgetData(status=colour, primary=primary, actions=_toggle(one), metrics=measured({"value": number}))

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "status":
            return self._status_card(
                {"status": "ok"}, {"installedVersion": "2.4.0", "latestVersion": "2.4.0", "updateAvailable": False},
                {"currentLoad": fake.walk("homebridge-cpu", tick, 2, 38)}, {"mem": {"total": 8_000, "available": 8_000 - fake.walk("homebridge-mem", tick, 1_200, 2_400)}},
                {"time": {"uptime": 86_400 * 12 + tick * 30}})
        if widget_kind == "plugins":
            return self._plugins_card([
                {"name": "homebridge-config-ui-x", "displayName": "Homebridge UI", "installedVersion": "5.29.0", "latestVersion": "5.30.1", "updateAvailable": True},
                {"name": "homebridge-hue", "displayName": "Hue", "installedVersion": "0.14.2", "latestVersion": "0.14.2"},
                {"name": "homebridge-dummy", "displayName": "Dummy", "installedVersion": "2.1.3", "latestVersion": "2.1.3"},
            ], options)
        temperature = fake.walk("homebridge-temp", tick, 19.5, 23.5, period=500)
        lamp = 1 if fake.flicker("homebridge-lamp", tick, 0.6) else 0
        accessories = [
            {"uniqueId": unique, "type": kind, "humanType": human, "serviceName": name, "values": values, "serviceCharacteristics": writable}
            for unique, kind, human, name, values, writable in (
                ("demo-lamp", "Lightbulb", "Lightbulb", "Lamp", {"On": lamp, "Brightness": 60}, [{"type": "On", "canWrite": True}]),
                ("demo-temp", "TemperatureSensor", "Temperature Sensor", "Living room temperature", {"CurrentTemperature": temperature}, []),
                ("demo-door", "ContactSensor", "Contact Sensor", "Front door", {"ContactSensorState": 0}, []),
                ("demo-outlet", "Outlet", "Outlet", "Wall outlet", {"On": 1}, [{"type": "On", "canWrite": True}]),
            )
        ]
        if widget_kind == "accessories":
            return self._accessories_card(accessories, options)
        return self._accessory_card(next((one for one in accessories if one["uniqueId"] == options.get("accessory")), accessories[1]))


ADAPTER = HomebridgeAdapter()
