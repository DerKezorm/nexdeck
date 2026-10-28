"""Wazuh: how many agents report in, which ones do not, and whether the manager's own daemons run.

Written on 27.10.2026 from the documentation of the Wazuh server API
(https://documentation.wazuh.com/current/user-manual/api/), **without a Wazuh to measure
against**: a Wazuh manager with its indexer and dashboard is too heavy for the test machine.
Nothing here is confirmed; the adapter is a beta and the answers in its tests are written after
the documentation.

- The API is on the manager, port 55000 over https with the certificate Wazuh made itself, so a
  connection to it usually needs "Ignore TLS errors". Not the dashboard (443) and not the indexer
  (9200), where the alerts live: the manager API does not hold them.
- Signing in: ``POST /security/user/authenticate?raw=true`` with basic authentication answers the
  token as plain text (a JWT, valid 900 seconds by default). Every other call carries
  ``Authorization: Bearer <token>``. A wrong password is 401 ``Invalid credentials``; an old token 401
  as well, so a 401 with a token that was kept signs in once more before it is believed.
  The user of the dashboard (``wazuh-wui``) is not the one to use: make one with the role
  ``readonly`` (or ``agents_readonly`` and ``cluster_readonly``).
- ``GET /agents/summary/status``: ``data.connection`` counts ``active``, ``disconnected``,
  ``never_connected``, ``pending`` and ``total``.
- ``GET /agents?status=disconnected,never_connected,pending`` lists them in
  ``data.affected_items`` (``id``, ``name``, ``ip``, ``status``, ``lastKeepAlive``, ``os.name``).
- ``GET /manager/status``: ``data.affected_items[0]`` maps each daemon (``wazuh-analysisd``,
  ``wazuh-remoted``, ...) to ``running``, ``stopped`` or ``failed``. Some daemons are stopped on
  purpose (``wazuh-agentlessd``, ``wazuh-integratord`` ...), so only ``failed`` and a stopped core
  daemon count.
- ``GET /`` answers the API's ``api_version`` and ``hostname`` after signing in.
"""

from __future__ import annotations

import time
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    ring_of,
)

TOKEN = "wazuh-token"
#: Wazuh's token lives 15 minutes by default; nexdeck signs in again after 12.
TOKEN_SECONDS = 12 * 60
#: The daemons a manager cannot do without; the others may be switched off on purpose.
CORE = ("wazuh-analysisd", "wazuh-remoted", "wazuh-modulesd", "wazuh-db", "wazuh-execd", "wazuh-apid")
NOT_ACTIVE = "disconnected,never_connected,pending"
STATE_WORD = {"disconnected": "Disconnected", "never_connected": "Never connected", "pending": "Pending", "active": "Active"}
STATE_COLOUR = {"disconnected": "bad", "never_connected": "warn", "pending": "warn", "active": "ok"}


class WazuhAdapter(Adapter):
    kind = "wazuh"
    label = "Wazuh"
    category = "monitoring"
    description = "How many Wazuh agents report in, which ones do not, and whether the manager's daemons run."
    icon = "wazuh"
    #: Built from the documentation of the server API on 2026-10-27; a Wazuh was too heavy for the test machine.
    beta = True
    docs_url = "https://documentation.wazuh.com/current/user-manual/api/"
    keywords = ("siem", "xdr", "security")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://wazuh:55000", help="The manager's API on port 55000, not the dashboard."),
        Field("username", "User name", required=True, help="A user of the API with a read-only role. Not the dashboard's wazuh-wui."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False, help="The API ships with a certificate Wazuh made itself."),
    )
    widgets = (
        WidgetType(kind="agents", label="Agents", description="How many agents are active, and which are disconnected, never connected or pending, as a ring.",
                   renderer="value", default_size=(2, 2), refresh_seconds=120, metrics=("inactive",), ring=True),
        WidgetType(kind="silent", label="Agents not reporting", description="The agents that are not active, disconnected ones first, with when they last reported.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("inactive",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="manager", label="Manager", description="Whether the manager's daemons run; red when one has failed.",
                   renderer="value", default_size=(2, 2), refresh_seconds=300, metrics=("down",)),
    )

    # -- talking to the manager ----------------------------------------------

    async def _token(self, config: dict[str, Any], ctx: Context, fresh: bool = False) -> str:
        kept = ctx.cache.get(TOKEN)
        if not fresh and isinstance(kept, tuple) and kept[0] > time.monotonic():
            return kept[1]
        response = await ctx.request("POST", f"{base_url(config)}/security/user/authenticate", params={"raw": "true"},
                                     auth=(str(config.get("username") or ""), str(config.get("password") or "")),
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Wazuh rejected the user name or the password.")
        if response.status_code >= 400 or not response.text.strip():
            raise AdapterError(f"Wazuh answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL: the manager's API is https on port 55000.")
        token = response.text.strip().strip('"')
        ctx.cache[TOKEN] = (time.monotonic() + TOKEN_SECONDS, token)
        return token

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in (0, 1):
            token = await self._token(config, ctx, fresh=attempt == 1)
            response = await ctx.request("GET", f"{base_url(config)}{path}", params=params, headers={"Authorization": f"Bearer {token}"},
                                         verify=not config.get("insecure"), auth_errors=False, cache_seconds=10)
            if response.status_code != 401 or attempt == 1:
                break
            # ⚠️ The refusal itself was remembered for ten seconds with the other answers; asking again would read it back.
            ctx.forget_answers()
        if response.status_code in (401, 403):
            raise AuthFailed("Wazuh rejected the token." if response.status_code == 401 else "This Wazuh user may not read that.")
        if response.status_code >= 400:
            raise AdapterError(f"Wazuh answered with HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Wazuh did not answer with JSON.", code="not_json", hint="The URL probably points at the dashboard, not the API on port 55000.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way the Wazuh API does.", code="not_wazuh")
        return answer.get("data") if "data" in answer else answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._json(config, ctx, "/")
        counts = ((await self._json(config, ctx, "/agents/summary/status")) or {}).get("connection") or {}
        version = str((info or {}).get("api_version") or "").lstrip("v")
        return f"Wazuh {version} answers, {counts.get('total', '?')} agents." if version else f"Wazuh answers, {counts.get('total', '?')} agents."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "manager":
            items = ((await self._json(config, ctx, "/manager/status")) or {}).get("affected_items") or [{}]
            return self._manager(items[0] if isinstance(items[0], dict) else {})
        counts = ((await self._json(config, ctx, "/agents/summary/status")) or {}).get("connection") or {}
        if widget_kind == "agents":
            return self._agents(counts)
        listed = await self._json(config, ctx, "/agents", params={"status": NOT_ACTIVE, "limit": 100, "select": "id,name,ip,status,lastKeepAlive,os.name"})
        return self._silent((listed or {}).get("affected_items") or [], counts, max(1, int(options.get("limit") or 10)))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _agents(counts: dict[str, Any]) -> WidgetData:
        active, total = int(counts.get("active") or 0), int(counts.get("total") or 0)
        gone, never, pending = (int(counts.get(key) or 0) for key in ("disconnected", "never_connected", "pending"))
        inactive = gone + never + pending
        return WidgetData(
            status="bad" if gone else "warn" if inactive else "ok" if total else "unknown",
            primary={"label": "Agents active", "value": active, "unit": f"/ {total}"},
            secondary=[row for row in ({"label": "Disconnected", "value": gone}, {"label": "Never connected", "value": never}, {"label": "Pending", "value": pending}) if row["value"]],
            meta={"ring": ring_of(("Active", active), ("Disconnected", gone), ("Never connected", never), ("Pending", pending))},
            metrics={"inactive": float(inactive)},
        )

    @staticmethod
    def _silent(agents: list[dict[str, Any]], counts: dict[str, Any], limit: int, now: float | None = None) -> WidgetData:
        rows = []
        for agent in agents:
            status = str(agent.get("status") or "")
            os_name = (agent.get("os") or {}).get("name") if isinstance(agent.get("os"), dict) else ""
            rows.append({
                "title": str(agent.get("name") or agent.get("id") or "?"),
                "subtitle": " · ".join(part for part in (STATE_WORD.get(status, status), str(agent.get("ip") or ""), str(os_name or "")) if part),
                "status": STATE_COLOUR.get(status, "unknown"),
                "value": ago(agent.get("lastKeepAlive"), now=now) if status == "disconnected" else "",
            })
        rows.sort(key=lambda row: ({"bad": 0, "warn": 1}.get(row["status"], 2), row["title"].lower()))
        gone = sum(1 for row in rows if row["status"] == "bad")
        inactive = sum(int(counts.get(key) or 0) for key in ("disconnected", "never_connected", "pending")) or len(rows)
        return WidgetData(status="bad" if gone else "warn" if rows else "ok", items=rows[:limit],
                          secondary=[{"label": "Not reporting", "value": inactive}], meta={"empty": "Every agent is reporting."},
                          metrics={"inactive": float(inactive)})

    @staticmethod
    def _manager(daemons: dict[str, Any]) -> WidgetData:
        failed = sorted(name for name, state in daemons.items() if state == "failed")
        stopped = sorted(name for name in CORE if name in daemons and daemons[name] != "running" and name not in failed)
        down = len(failed) + len(stopped)
        reason = ", ".join(f"{name.removeprefix('wazuh-')}" for name in failed + stopped)
        return WidgetData(
            status="bad" if failed else "warn" if stopped else "ok" if daemons else "unknown",
            primary={"label": "Daemons running", "value": sum(1 for state in daemons.values() if state == "running"), "unit": f"/ {len(daemons)}"},
            secondary=[{"label": "Not running", "value": reason}] if down else [],
            meta={"status_reason": f"Not running: {reason}" if down else ""},
            metrics={"down": float(down)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        silent = fake.flicker("wazuh-web", tick, 0.5)
        counts = {"active": 11 - int(silent), "disconnected": int(silent), "never_connected": 1, "pending": 0, "total": 12}
        if widget_kind == "manager":
            return self._manager({"wazuh-analysisd": "running", "wazuh-remoted": "running", "wazuh-modulesd": "running", "wazuh-db": "running",
                                  "wazuh-execd": "running", "wazuh-apid": "running", "wazuh-agentlessd": "stopped"})
        if widget_kind == "silent":
            now = time.time()
            agents = [{"name": "laptop", "ip": "192.0.2.31", "status": "never_connected", "os": {"name": "Ubuntu"}}]
            if silent:
                agents.append({"name": "web-01", "ip": "192.0.2.10", "status": "disconnected", "os": {"name": "Debian"}, "lastKeepAlive": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 7200))})
            return self._silent(agents, counts, 10, now=now)
        return self._agents(counts)


ADAPTER = WazuhAdapter()
