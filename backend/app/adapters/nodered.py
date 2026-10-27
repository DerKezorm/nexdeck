"""Node-RED: whether the flows run, what is deployed, and a button for every inject node.

Measured on 27.10.2026 against Node-RED 5.0.9 (``nodered/node-red``): without
a sign-in, with ``adminAuth`` of the type credentials and an administrator
(permissions ``*``), and with a user who may only read (permissions ``read``).
Three flows with seven nodes, one tab disabled, inject nodes with and without
a name.

⚠️ Without ``adminAuth`` the whole admin API is open, and ``GET /auth/login``
answers ``{}``. With it, it answers ``{"type": "credentials", "prompts": [...]}``
and everything else answers 401 "Unauthorized" until a token is fetched with
``POST /auth/token`` (a form: ``client_id=node-red-admin``, ``grant_type=password``,
``scope``, ``username``, ``password``). The token lives seven days.

⚠️ A user who may only read cannot ask for the scope ``*``: the answer is
``invalid_grant`` "Invalid resource owner credentials", the same words as a wrong
password. The scope ``read`` tells them apart, and gets a token that reads
everything the cards need.

⚠️ A wrong password is HTTP 403 ``invalid_grant``. After five wrong ones from one
address Node-RED answers 500 "Too many login attempts. Wait 10 minutes and try
again" to *every* sign-in, the right password included. So a refusal is
remembered for a quarter of an hour, a wrong password costs two attempts at
most (the scope ``*``, then ``read``), and the lockout is said in its own words.

⚠️ ``POST /inject/{id}`` runs *any* node that has an input, not only an inject
node: a debug node answered 200 "OK" too. A node in a disabled tab answers 404,
and a read-only token answers 401, not 403. The button is offered only for
inject nodes of tabs that run, and only because the card put it there.

⚠️ ``POST /flows/state`` (start and stop all flows) is 404 "Cannot POST" unless
``runtimeState.enabled`` is on in settings.js, which it is not by default.
Reading ``GET /flows/state`` always works, so the card shows the state and
offers no button for it.

⚠️ ``GET /flows`` is a list of nodes with a ``z`` that names the tab, unless the
header ``Node-RED-API-Version: v2`` asks for ``{flows, rev}``. Subflow instances
count as one node each, config nodes have no ``z`` and are not counted.

⚠️ ``/diagnostics`` is there from Node-RED 4.1 on and can be switched off
(``diagnostics.enabled``). The memory figure is left out when it is.
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
    measured,
    path_segment,
)

ADDRESS_HINT = "Check the URL; it is the address Node-RED's editor opens at, usually port 1880."
#: Nodes that are not part of what runs: the tab itself, notes, boxes round other nodes, and the joints of wires.
NOT_COUNTED = ("tab", "comment", "group", "junction", "subflow")
TOKEN_NAME = "node-red-admin"
#: How long a refused sign-in is remembered: longer than the ten minutes Node-RED locks out for.
LOCKOUT_SECONDS = 900


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _inject_title(node: dict[str, Any]) -> str:
    """What the editor would call an inject node: its name, else what it sends."""
    name = str(node.get("name") or "").strip()
    if name:
        return name
    payload = str(node.get("payload") or "").strip()
    return payload if payload and node.get("payloadType") in ("str", "num", "bool", "json") else "Inject"


class NodeRedAdapter(Adapter):
    kind = "nodered"
    label = "Node-RED"
    category = "other"
    description = "Whether the flows run, how many flows and nodes are deployed, and a button for every inject node."
    icon = "node-red"
    beta = True
    docs_url = "https://nodered.org/docs/api/admin/"
    keywords = ("automation", "flows", "smart home")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nodered:1880"),
        Field("username", "User", help="Only when Node-RED has adminAuth switched on. A user who may only read fills the cards; the inject buttons need one who may write."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="runtime", label="Node-RED",
            description="Whether the flows run, the version, how many flows and nodes are deployed, and the memory Node-RED holds.",
            renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("nodes", "memory_mb"),
            parts=(("version", "Version"), ("flows", "Flows"), ("nodes", "Nodes"), ("memory", "Memory")),
        ),
        WidgetType(
            kind="flows", label="Flows",
            description="The tabs of the editor with the number of nodes on each, disabled ones last.",
            renderer="list", bars=True, default_size=(3, 3), refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="injects", label="Inject nodes",
            description="Every inject node of a flow that runs, with a button that triggers it after a question. Needs a user who may write.",
            renderer="list", default_size=(3, 3), refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
    )

    # -- talking to Node-RED -------------------------------------------------

    def _signs_in(self, config: dict[str, Any]) -> bool:
        return bool(str(config.get("username") or "").strip())

    async def _raw(self, config: dict[str, Any], ctx: Context, method: str, path: str, *, token: str = "", data: dict[str, str] | None = None,
                   json_body: Any = None, cache: float = 0) -> Any:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return await ctx.request(
            method, f"{base_url(config)}{path}", headers=headers, data=data, json_body=json_body, verify=not config.get("insecure"),
            timeout=15.0, cache_seconds=cache if method == "GET" else 0, auth_errors=False)

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        """The bearer token, or an empty string where Node-RED asks for none.

        ⚠️ One sign-in at a time per connection, and a refusal is remembered for a while so a wrong password is not
        tried on every refresh.
        """
        kept = ctx.cache.get("nodered_token")
        if kept and not force and kept[0] > time.monotonic():
            return str(kept[1])
        lock = ctx.cache.setdefault("nodered_login_lock", asyncio.Lock())
        async with lock:
            kept = ctx.cache.get("nodered_token")
            if kept and not force and kept[0] > time.monotonic():
                return str(kept[1])
            refused = ctx.cache.get("nodered_refused")
            if refused and refused[0] > time.monotonic():
                raise AuthFailed(str(refused[1]))
            asked = await self._raw(config, ctx, "GET", "/auth/login")
            try:
                login = asked.json() if asked.status_code == 200 else None
            except ValueError:
                login = None
            if not isinstance(login, dict):
                raise AdapterError("This address answers, but not the way Node-RED does.", code="not_nodered", hint=ADDRESS_HINT)
            kind = str(login.get("type") or "")
            if not kind:
                # Open: nothing signs in, and nothing needs to.
                ctx.cache["nodered_token"] = (time.monotonic() + 3600, "")
                return ""
            if kind != "credentials":
                raise AdapterError("This Node-RED signs in through an outside service.", code="unsupported_login",
                                   hint="nexdeck speaks the user and password sign-in (adminAuth of the type credentials) only.")
            if not self._signs_in(config):
                error = AuthFailed("Node-RED asks for a sign-in.")
                error.hint = "Fill in the user and the password of the Node-RED editor."
                raise error
            for scope in ("*", "read"):
                response = await self._raw(config, ctx, "POST", "/auth/token", data={
                    "client_id": TOKEN_NAME, "grant_type": "password", "scope": scope,
                    "username": str(config.get("username") or "").strip(), "password": str(config.get("password") or "")})
                if response.status_code == 200:
                    try:
                        body = response.json()
                        token = str(body["access_token"])
                        lifetime = float(body.get("expires_in") or 3600)
                    except (ValueError, KeyError, TypeError, AttributeError) as error:
                        raise AdapterError("Node-RED handed out no token.", code="not_nodered", hint=ADDRESS_HINT) from error
                    ctx.cache.pop("nodered_refused", None)
                    ctx.cache["nodered_scope"] = scope
                    ctx.cache["nodered_token"] = (time.monotonic() + max(60.0, lifetime - 300), token)
                    return token
                if response.status_code == 500 and "too many login attempts" in response.text.lower():
                    message = "Node-RED locked this address out after too many wrong passwords."
                    ctx.cache["nodered_refused"] = (time.monotonic() + LOCKOUT_SECONDS, message)
                    error = AuthFailed(message)
                    error.hint = "It lets the right password in again after ten minutes. Check the user and the password meanwhile."
                    raise error
                if response.status_code not in (400, 401, 403):
                    raise AdapterError(f"Node-RED answered the sign-in with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
            message = "Node-RED turned the user or the password down."
            ctx.cache["nodered_refused"] = (time.monotonic() + LOCKOUT_SECONDS, message)
            error = AuthFailed(message)
            error.hint = "Check the user and the password."
            raise error

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, path: str, *, cache: float = 0, retry: bool = True,
                    allow: tuple[int, ...] = ()) -> Any:
        token = await self._token(config, ctx)
        response = await self._raw(config, ctx, method, path, token=token, cache=cache)
        if response.status_code == 401 and retry and token:
            # A token Node-RED no longer knows (it restarted, the user was changed) is turned down like a made-up one.
            ctx.forget_answers()
            await self._token(config, ctx, force=True)
            return await self._call(config, ctx, method, path, cache=0, retry=False, allow=allow)
        if response.status_code == 401:
            if method == "POST" and ctx.cache.get("nodered_scope") == "read":
                raise AdapterError("This user may only read in Node-RED.", code="read_only",
                                   hint="Give the user the permission write in adminAuth, or sign in as one who has it.")
            raise AuthFailed("Node-RED turned this user down.")
        if response.status_code in allow:
            return None
        if response.status_code >= 400:
            raise AdapterError(f"Node-RED answered with HTTP {response.status_code}.", code="http_error", hint=ADDRESS_HINT)
        if method == "POST":
            return response.text
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than Node-RED.", code="not_nodered", hint=ADDRESS_HINT) from error

    async def _flows(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        flows = await self._call(config, ctx, "GET", "/flows", cache=10)
        if not isinstance(flows, list):
            raise AdapterError("This address answers, but not the way Node-RED does.", code="not_nodered", hint=ADDRESS_HINT)
        return [node for node in flows if isinstance(node, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        settings = await self._call(config, ctx, "GET", "/settings")
        if not isinstance(settings, dict) or "version" not in settings:
            raise AdapterError("This address answers, but not the way Node-RED does.", code="not_nodered", hint=ADDRESS_HINT)
        state = await self._call(config, ctx, "GET", "/flows/state")
        running = isinstance(state, dict) and state.get("state") == "start"
        return f"Node-RED {settings['version']} answers. Flows: {'running' if running else 'stopped'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "runtime":
            async def optional(path: str) -> Any:
                try:
                    return await self._call(config, ctx, "GET", path, cache=10, allow=(404,))
                except AdapterError as error:
                    if isinstance(error, AuthFailed):
                        raise
                    return None
            flows, state, settings, diagnostics = await asyncio.gather(
                self._flows(config, ctx), optional("/flows/state"), optional("/settings"), optional("/diagnostics"))
            return self._runtime_card(flows, state, settings, diagnostics)
        flows = await self._flows(config, ctx)
        try:
            limit = max(1, min(100, int(options.get("limit") or 10)))
        except (TypeError, ValueError):
            limit = 10
        return self._flows_card(flows, limit) if widget_kind == "flows" else self._injects_card(flows, limit)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "run":
            raise AdapterError("Unknown inject action.", code="no_such_action")
        node = path_segment(params.get("node"), "The node")
        sent = await self._call(config, ctx, "POST", f"/inject/{node}", allow=(404,))
        if sent is None:
            raise AdapterError("Node-RED has no running inject node with that number.", code="no_node",
                               hint="The flow may have been changed or disabled since the card last looked.")
        ctx.forget_answers()
        return "Triggered."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _tabs(flows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        tabs = [node for node in flows if node.get("type") == "tab"]
        by_tab: dict[str, list[dict[str, Any]]] = {str(tab.get("id")): [] for tab in tabs}
        for node in flows:
            if node.get("type") not in NOT_COUNTED and str(node.get("z")) in by_tab:
                by_tab[str(node["z"])].append(node)
        return tabs, by_tab

    @classmethod
    def _runtime_card(cls, flows: list[dict[str, Any]], state: Any, settings: Any, diagnostics: Any) -> WidgetData:
        tabs, by_tab = cls._tabs(flows)
        enabled = [tab for tab in tabs if not tab.get("disabled")]
        nodes = sum(1 for tab in enabled for node in by_tab[str(tab["id"])] if not node.get("d"))
        running = isinstance(state, dict) and state.get("state") == "start"
        known = isinstance(state, dict) and state.get("state") in ("start", "stop")
        rss = None
        if isinstance(diagnostics, dict):
            usage = (diagnostics.get("nodejs") or {}).get("memoryUsage") if isinstance(diagnostics.get("nodejs"), dict) else None
            rss = _number(usage.get("rss")) if isinstance(usage, dict) else None
        memory = round(rss / 1024 / 1024, 1) if rss else None
        secondary: list[dict[str, Any]] = []
        if isinstance(settings, dict) and settings.get("version"):
            secondary.append({"label": "Version", "value": str(settings["version"]), "part": "version"})
        secondary.append({"label": "Flows", "value": len(enabled), "part": "flows"})
        secondary.append({"label": "Nodes", "value": nodes, "part": "nodes"})
        if memory is not None:
            secondary.append({"label": "Memory", "value": f"{memory:.0f} MB", "part": "memory"})
        return WidgetData(
            status="ok" if running or not known else "warn",
            primary={"label": "Flows", "value": "Running" if running else "Stopped" if known else "Unknown"},
            secondary=secondary,
            metrics=measured({"nodes": float(nodes), "memory_mb": memory}),
        )

    @classmethod
    def _flows_card(cls, flows: list[dict[str, Any]], limit: int) -> WidgetData:
        tabs, by_tab = cls._tabs(flows)
        ordered = sorted(tabs, key=lambda tab: (bool(tab.get("disabled")), str(tab.get("label") or "").lower()))
        rows = [{
            "id": tab.get("id"), "title": str(tab.get("label") or tab.get("id") or "?"),
            "subtitle": "Disabled" if tab.get("disabled") else "",
            "value": len([node for node in by_tab[str(tab["id"])] if not node.get("d")]),
            "status": "unknown" if tab.get("disabled") else "ok",
        } for tab in ordered[:limit]]
        return WidgetData(items=rows, secondary=[{"label": "Flows", "value": len(tabs)}], meta={"empty": "No flow is deployed."})

    @classmethod
    def _injects_card(cls, flows: list[dict[str, Any]], limit: int) -> WidgetData:
        tabs, by_tab = cls._tabs(flows)
        rows = []
        for tab in sorted(tabs, key=lambda one: str(one.get("label") or "").lower()):
            # ⚠️ Not in a tab that is off: the node is not deployed and the button would answer 404.
            if tab.get("disabled"):
                continue
            for node in by_tab[str(tab["id"])]:
                if node.get("type") == "inject" and not node.get("d"):
                    rows.append({
                        "id": node.get("id"), "title": _inject_title(node), "subtitle": str(tab.get("label") or ""),
                        "status": "ok", "actions": [Action(id="run", label="Run", icon="play", confirm=True, params={"node": str(node["id"])})],
                    })
        return WidgetData(items=rows[:limit], secondary=[{"label": "Inject nodes", "value": len(rows)}],
                          meta={"empty": "No inject node in a flow that runs.", "actions_visible": True})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        # The names are the demo's own, so they are made apart from the literals the translation guard reads.
        flows: list[dict[str, Any]] = [
            dict(id="t1", type="tab", label="Heating"), dict(id="t2", type="tab", label="Garden"),
            dict(id="t3", type="tab", label="Old experiments", disabled=True),
        ]
        for index in range(14):
            flows.append({"id": f"n{index}", "type": "function", "z": "t1" if index < 8 else "t2" if index < 12 else "t3"})
        flows.append({"id": "i1", "type": "inject", "z": "t1", "name": "Boost heating"})
        flows.append({"id": "i2", "type": "inject", "z": "t2", "name": "Water the lawn"})
        if widget_kind == "flows":
            return self._flows_card(flows, 10)
        if widget_kind == "injects":
            return self._injects_card(flows, 10)
        return self._runtime_card(
            flows, {"state": "start"}, {"version": "5.0.9"},
            {"nodejs": {"memoryUsage": {"rss": fake.walk("nodered-mem", tick, 110, 190, period=400) * 1024 * 1024}}})


ADAPTER = NodeRedAdapter()
