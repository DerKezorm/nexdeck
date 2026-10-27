"""AMP (CubeCoders): the game server instances, their state and players.

AMP's API is a JSON-over-POST interface: ``POST {url}/API/{Module}/{Method}``.
``Core/Login`` takes the user name and password and answers a ``sessionID``,
which every later call carries as ``SESSIONID`` in its body. The instances
are those of ``ADSModule/GetInstances``, the instance manager; each can be
started and stopped through ``ADSModule/StartInstance`` and ``StopInstance``.

Not measured. AMP needs a licence to run, so it was not started; everything
here follows CubeCoders' API documentation and what its client libraries
do, and none of it was seen against a server. The places most likely to differ:

* The answer of ``GetInstances`` is read as a list of instance managers that
  each hold ``AvailableInstances``, and also as a plain list of instances.
* ``AppState`` numbers (20 ready, 0 stopped, 100 failed ...) are AMP's.
* A call with a session that ran out answers 200 with a ``Title`` of
  "Unauthorized Access"; the session is then fetched again once.
"""

from __future__ import annotations

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
    path_segment,
)

#: AMP's application states, by number.
STATES = {0: "Stopped", 5: "Starting", 7: "Starting", 10: "Starting", 20: "Running", 30: "Restarting", 40: "Stopping",
          45: "Stopping", 50: "Sleeping", 60: "Waiting", 70: "Installing", 75: "Updating", 80: "Waiting for input",
          100: "Failed", 200: "Suspended", 250: "Maintenance"}
RUNNING = {20, 30, 50, 60, 80}
STOPPED = {0, 100}


def instances_of(body: Any) -> list[dict[str, Any]]:
    """Every instance in the answer of GetInstances, whether it is nested under its manager or not."""
    found: list[dict[str, Any]] = []
    for one in body if isinstance(body, list) else []:
        if not isinstance(one, dict):
            continue
        if isinstance(one.get("AvailableInstances"), list):
            found += [inner for inner in one["AvailableInstances"] if isinstance(inner, dict)]
        else:
            found.append(one)
    return [one for one in found if one.get("InstanceName") or one.get("InstanceID")]


def metric(instance: dict[str, Any], name: str) -> tuple[float | None, float | None]:
    value = (instance.get("Metrics") or {}).get(name)
    if not isinstance(value, dict):
        return None, None
    raw, top = value.get("RawValue"), value.get("MaxValue")
    return (float(raw) if isinstance(raw, int | float) else None, float(top) if isinstance(top, int | float) and top > 0 else None)


class AMPAdapter(Adapter):
    kind = "amp"
    label = "AMP"
    category = "hosts"
    description = "The game server instances of an AMP panel: which run, who is playing, and buttons to start and stop them."
    icon = "amp"
    docs_url = "https://github.com/CubeCoders/AMP/wiki"
    #: Built from the documentation and not run against AMP (a licence is needed); it stays beta until somebody confirms it.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://amp:8080",
              help="The address of the AMP web interface."),
        Field("username", "User name", required=True, help="An AMP user. Its role decides which instances it sees."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In AMP create a user of its own for nexdeck under Configuration > User Management.",
        "Give its role only what is needed: viewing the instances, and starting and stopping them if the buttons should work. A user with two-factor sign-in cannot be used.",
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Overview",
            description="How many instances run, how many are stopped or failed, and how many players are on.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("running", "players"),
        ),
        WidgetType(
            kind="instances",
            label="Instances",
            description="Every instance with its state, players, processor and memory, and buttons to start or stop it.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=12),),
        ),
    )

    async def _login(self, config: dict[str, Any], ctx: Context) -> str:
        response = await ctx.request(
            "POST", f"{base_url(config)}/API/Core/Login",
            json_body={"username": str(config.get("username") or ""), "password": str(config.get("password") or ""),
                       "token": "", "rememberMe": False},
            headers={"Accept": "application/json"}, verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code >= 400:
            raise AdapterError(f"AMP answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the AMP web interface.")
        try:
            body = response.json()
        except ValueError as error:
            raise AdapterError("AMP did not answer with JSON.", code="not_json",
                               hint="The URL probably points at another service.") from error
        session = body.get("sessionID") if isinstance(body, dict) else None
        if not session:
            raise AuthFailed("AMP refused the user name or the password.")
        ctx.cache["amp.session"] = str(session)
        return str(session)

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, arguments: dict[str, Any] | None = None) -> Any:
        for attempt in range(2):
            session = ctx.cache.get("amp.session") or await self._login(config, ctx)
            response = await ctx.request(
                "POST", f"{base_url(config)}/API/{method}",
                json_body={**(arguments or {}), "SESSIONID": session},
                headers={"Accept": "application/json"}, verify=not config.get("insecure"), auth_errors=False,
            )
            if response.status_code >= 500:
                raise AdapterError(f"AMP answered with HTTP {response.status_code}.", code="http_error")
            try:
                body = response.json()
            except ValueError as error:
                raise AdapterError("AMP did not answer with JSON.", code="not_json",
                                   hint="The URL probably points at another service.") from error
            if response.status_code in (401, 403) or (isinstance(body, dict) and "unauthorized" in str(body.get("Title") or "").lower()):
                ctx.cache.pop("amp.session", None)
                if attempt == 0:
                    continue
                raise AuthFailed("AMP refused the session it had just handed out.")
            return body
        raise AuthFailed()

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        found = instances_of(await self._call(config, ctx, "ADSModule/GetInstances"))
        return f"AMP answers, {len(found)} instance(s)."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        return None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        found = instances_of(await self._call(config, ctx, "ADSModule/GetInstances"))
        return self._list(found, options) if widget_kind == "instances" else self._overview(found)

    @staticmethod
    def _state(instance: dict[str, Any]) -> int | None:
        if instance.get("Suspended"):
            return 200
        state = instance.get("AppState")
        if isinstance(state, int):
            return state
        return 20 if instance.get("Running") else 0 if instance.get("Running") is False else None

    def _overview(self, found: list[dict[str, Any]]) -> WidgetData:
        states = [self._state(one) for one in found]
        running = sum(1 for state in states if state in RUNNING)
        failed = sum(1 for state in states if state == 100)
        players = int(sum(metric(one, "Active Users")[0] or 0 for one in found))
        return WidgetData(
            status="bad" if failed else "ok",
            primary={"label": "Running", "value": running},
            secondary=[{"label": "Instances", "value": len(found)}, {"label": "Stopped", "value": sum(1 for state in states if state in STOPPED and state != 100)},
                       {"label": "Failed", "value": failed}, {"label": "Players", "value": players}],
            metrics={"running": float(running), "players": float(players)},
        )

    def _list(self, found: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        items = []
        for one in found:
            state = self._state(one)
            name = str(one.get("InstanceName") or "")
            players, top = metric(one, "Active Users")
            cpu, _ = metric(one, "CPU Usage")
            memory, memory_top = metric(one, "Memory Usage")
            parts = [str(one.get("Module") or "")]
            if state in RUNNING:
                if players is not None:
                    parts.append(f"{int(players)} of {int(top)} players" if top else f"{int(players)} players")
                if cpu is not None:
                    parts.append(f"CPU {cpu:.0f} %")
                if memory is not None:
                    parts.append(f"{memory:.0f} of {memory_top:.0f} MB" if memory_top else f"{memory:.0f} MB")
            actions = []
            if name and state in STOPPED:
                actions = [Action(id="start", label="Start", icon="play", confirm=True, params={"name": name})]
            elif name and state in RUNNING:
                actions = [Action(id="stop", label="Stop", icon="power", confirm=True, danger=True, params={"name": name})]
            items.append({
                "title": str(one.get("FriendlyName") or name or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "status": "bad" if state == 100 else "warn" if state not in RUNNING | STOPPED else "ok",
                "value": STATES.get(state, "Unknown") if state is not None else "Unknown",
                "actions": actions,
            })
        order = {"bad": 0, "warn": 1, "ok": 2}
        items.sort(key=lambda row: (order[row["status"]], row["value"] == "Stopped", row["title"].casefold()))
        states = {row["status"] for row in items}
        return WidgetData(
            status="bad" if "bad" in states else "warn" if "warn" in states else "ok",
            items=items[: int(options.get("limit") or 12)],
            secondary=[{"label": "Instances", "value": len(items)}],
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("start", "stop"):
            raise AdapterError("AMP has no such action.", code="no_such_action")
        name = path_segment(params.get("name"), "The instance")
        answer = await self._call(config, ctx, "ADSModule/StartInstance" if action_id == "start" else "ADSModule/StopInstance",
                                  {"InstanceName": name})
        if isinstance(answer, dict) and answer.get("Status") is False:
            raise AdapterError(f"AMP did not {action_id} the instance: {str(answer.get('Reason') or answer.get('Message') or '')[:160]}",
                               code="not_done", hint="The user may lack the right to control this instance.")
        ctx.forget_answers()
        return "The instance is starting." if action_id == "start" else "The instance is stopping."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        down = fake.flicker("amp-down", tick, 0.2)
        found = [
            {"InstanceName": "Survival01", "FriendlyName": "Survival", "Module": "Minecraft", "AppState": 20,
             "Metrics": {"Active Users": {"RawValue": int(fake.walk("amp-p1", tick, 0, 7)), "MaxValue": 20},
                         "CPU Usage": {"RawValue": fake.walk("amp-c1", tick, 6, 50), "MaxValue": 100},
                         "Memory Usage": {"RawValue": fake.walk("amp-m1", tick, 2200, 3600), "MaxValue": 4096}}},
            {"InstanceName": "Valheim01", "FriendlyName": "Valheim", "Module": "Valheim", "AppState": 100 if down else 20,
             "Metrics": {"Active Users": {"RawValue": 2, "MaxValue": 10}, "CPU Usage": {"RawValue": 21.0, "MaxValue": 100},
                         "Memory Usage": {"RawValue": 3100, "MaxValue": 8192}}},
            {"InstanceName": "Rust01", "FriendlyName": "Rust", "Module": "Rust", "AppState": 0, "Metrics": {}},
        ]
        return self._list(found, options) if widget_kind == "instances" else self._overview(found)


ADAPTER = AMPAdapter()
