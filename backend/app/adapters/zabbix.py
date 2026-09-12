"""Zabbix: open problems, the most severe first, and a button to acknowledge one.

Measured against Zabbix 7.4.14 (server, web interface and agent 2 on
PostgreSQL 16) on 11.09.2026, with a trapper item on a test host, three
triggers on it of severity warning, high and disaster, a value pushed with
``history.push``, and the "agent is not available" problem the built-in
server host raises by itself.

⚠️ Every answer is HTTP 200, a refusal too: a missing or made-up token gets
``{"error": {"code": -32602, "data": "Not authorized."}}``. The status code
says nothing; the body is the only thing there is.

⚠️ The token goes in ``Authorization: Bearer``. The ``auth`` field in the body
is gone: -32600 "unexpected parameter auth". And ``apiinfo.version`` refuses
the header: "must be called without authorization header".

⚠️ ``problem.get`` knows no host and sorts by ``eventid`` alone ("value must
be eventid" for ``clock``). The hosts come from ``event.get`` with
``selectHosts``, and the severity order is made here.

⚠️ A user with the plain User role and read permission on a host group sees
that group's problems and may acknowledge them; closing one needs write
permission. An event id the user cannot see and one that does not exist get
the same -32500 "No permissions to referred object or it does not exist!".
Acknowledging an acknowledged problem answers like the first time. A role
without "Acknowledge problems" gets -32500 'Incorrect value for field "action":
no permissions to acknowledge problems.'

⚠️ ``problem.get`` hands out suppressed problems unless told
``suppressed: false``. Suppressing lands a few seconds after the call, and an
unsuppress sent before that is skipped without a word.

⚠️ ``clock`` is a string of seconds, ``"1789159415"``.
"""

from __future__ import annotations

import re
import time
from typing import Any

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
)

SEVERITY_WORD = {5: "Disaster", 4: "High", 3: "Average", 2: "Warning", 1: "Information", 0: "Not classified"}
EVENT_ID = re.compile(r"^\d{1,20}$")


def _severity(problem: dict[str, Any]) -> int:
    try:
        return max(0, min(5, int(problem.get("severity") or 0)))
    except (TypeError, ValueError):
        return 0


def _seconds(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _row_status(severity: int) -> str:
    return "bad" if severity >= 4 else "warn" if severity >= 2 else "unknown"


class ZabbixAdapter(Adapter):
    kind = "zabbix"
    label = "Zabbix"
    category = "monitoring"
    description = "Open problems, the most severe first, with a button to acknowledge them."
    icon = "zabbix"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://www.zabbix.com/documentation/current/en/manual/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://zabbix-web:8080",
              help="The address of the web interface, the one that serves api_jsonrpc.php."),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Users > API tokens. A user with read access to the host groups is enough, acknowledging included; the cards show the problems that user may see."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="problems", label="Problems", description="Open problems, the most severe and newest first, with a button to acknowledge each.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("problems", "unacknowledged"),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Open problems", description="How many problems are open, how many are high or worse, and how many nobody acknowledged.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("problems", "high_or_worse")),
    )

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, params: Any, *, token: bool = True) -> Any:
        headers = {"Authorization": f"Bearer {config.get('token') or ''}"} if token else {}
        response = await ctx.request(
            "POST", f"{base_url(config)}/api_jsonrpc.php", headers=headers,
            json_body={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
            verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Zabbix rejected the API token.")
        if response.status_code >= 400:
            raise AdapterError(f"Zabbix answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the web interface, with /zabbix if it lives there.")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Zabbix did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than the Zabbix web interface.") from error
        if not isinstance(answer, dict) or ("result" not in answer and "error" not in answer):
            raise AdapterError("This address answers, but not the way Zabbix does.", code="not_zabbix")
        error = answer.get("error")
        if isinstance(error, dict):
            detail = str(error.get("data") or error.get("message") or "")
            if detail.startswith("Not authorized"):
                raise AuthFailed("Zabbix rejected the API token.")
            raise AdapterError(f"Zabbix refused: {detail}", code="zabbix_error")
        return answer["result"]

    async def _problems(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        problems = await self._call(config, ctx, "problem.get", {
            "output": ["eventid", "clock", "name", "severity", "acknowledged"],
            # The problem view of Zabbix leaves suppressed problems out, and so does the card.
            "recent": False, "suppressed": False, "sortfield": ["eventid"], "sortorder": "DESC",
        })
        if not isinstance(problems, list):
            raise AdapterError("This address answers, but not the way Zabbix does.", code="not_zabbix")
        return [one for one in problems if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        # ⚠️ Without the header: this one method refuses it.
        version = await self._call(config, ctx, "apiinfo.version", {}, token=False)
        problems = await self._problems(config, ctx)
        return f"Zabbix {version} answers; {len(problems)} problems are open."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        problems = await self._problems(config, ctx)
        if widget_kind == "summary":
            return self._summary(problems)
        shown = self.ranked(problems)[: max(1, int(options.get("limit") or 10))]
        hosts: dict[str, str] = {}
        if shown:
            events = await self._call(config, ctx, "event.get", {
                "eventids": [str(one.get("eventid")) for one in shown], "output": ["eventid"], "selectHosts": ["name"],
            })
            hosts = self.hosts_of(events)
        return self._list(problems, shown, hosts, time.time())

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "acknowledge":
            raise AdapterError("Unknown problem action.", code="no_such_action")
        eventid = str(params.get("eventid") or "")
        if not EVENT_ID.match(eventid):
            raise AdapterError("That is not a problem this card showed.", code="bad_param")
        try:
            result = await self._call(config, ctx, "event.acknowledge", {"eventids": [eventid], "action": 2})
        except AuthFailed:
            raise
        except AdapterError as refused:
            if refused.code == "zabbix_error" and "does not exist" in refused.message:
                raise AdapterError("Zabbix has no such problem, or this token may not see it.", code="action_failed") from refused
            raise AdapterError(refused.message, code="action_failed",
                               hint="Acknowledging needs a user role that allows it.") from refused
        acknowledged = {str(one) for one in (result or {}).get("eventids") or []} if isinstance(result, dict) else set()
        if eventid not in acknowledged:
            raise AdapterError("Zabbix did not acknowledge the problem.", code="action_failed")
        return "Problem acknowledged."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def ranked(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The most severe first, and within one severity the newest first."""
        def eventid(problem: dict[str, Any]) -> int:
            text = str(problem.get("eventid") or "")
            return int(text) if text.isdigit() else 0

        return sorted(problems, key=lambda one: (-_severity(one), -eventid(one)))

    @staticmethod
    def hosts_of(events: Any) -> dict[str, str]:
        found: dict[str, str] = {}
        for event in events if isinstance(events, list) else []:
            if isinstance(event, dict):
                names = [str(host.get("name") or "") for host in event.get("hosts") or [] if isinstance(host, dict)]
                found[str(event.get("eventid"))] = ", ".join(name for name in names if name)
        return found

    @staticmethod
    def _list(problems: list[dict[str, Any]], shown: list[dict[str, Any]], hosts: dict[str, str], now: float) -> WidgetData:
        items = []
        for problem in shown:
            severity = _severity(problem)
            eventid = str(problem.get("eventid") or "")
            acknowledged = str(problem.get("acknowledged")) == "1"
            row: dict[str, Any] = {
                "title": str(problem.get("name") or "?"),
                "subtitle": " · ".join(piece for piece in (SEVERITY_WORD[severity], hosts.get(eventid, ""), "Acknowledged" if acknowledged else "") if piece),
                "status": _row_status(severity),
                # ⚠️ A string of seconds, "1789159415", which ago() would read as a date and give up on.
                "value": ago(_seconds(problem.get("clock")), now=now),
            }
            if not acknowledged and EVENT_ID.match(eventid):
                row["actions"] = [Action(id="acknowledge", label="Acknowledge", icon="check", confirm=True, params={"eventid": eventid})]
            items.append(row)
        unacknowledged = sum(1 for one in problems if str(one.get("acknowledged")) != "1")
        worst = max((_severity(one) for one in problems), default=-1)
        return WidgetData(
            status="ok" if worst < 2 else _row_status(worst),
            items=items,
            secondary=[{"label": "Open problems", "value": len(problems)}, {"label": "Unacknowledged", "value": unacknowledged}],
            # A wall display has no hovering, and acknowledging is the one thing to press here.
            meta={"empty": "No problem is open.", "actions_visible": True},
            metrics={"problems": float(len(problems)), "unacknowledged": float(unacknowledged)},
        )

    @staticmethod
    def _summary(problems: list[dict[str, Any]]) -> WidgetData:
        severe = sum(1 for one in problems if _severity(one) >= 4)
        unacknowledged = sum(1 for one in problems if str(one.get("acknowledged")) != "1")
        worst = max((_severity(one) for one in problems), default=-1)
        return WidgetData(
            status="ok" if worst < 2 else _row_status(worst),
            primary={"label": "Open problems", "value": len(problems)},
            secondary=[{"label": "High or worse", "value": severe}, {"label": "Unacknowledged", "value": unacknowledged}],
            metrics={"problems": float(len(problems)), "high_or_worse": float(severe)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        disk = tick % 5 != 0
        problems = [
            {"eventid": "4812", "clock": now - 600 - tick % 60, "name": "Linux: High CPU utilization (over 90% for 5m)", "severity": "3", "acknowledged": "0"},
            {"eventid": "4790", "clock": now - 5400, "name": "Interface eth0: Link down", "severity": "4", "acknowledged": "1"},
            {"eventid": "4755", "clock": now - 86400, "name": "Linux: Zabbix agent is not available (for 3m)", "severity": "3", "acknowledged": "0"},
        ]
        if disk:
            problems.append({"eventid": "4821", "clock": now - 180, "name": "/srv: Disk space is critically low (used > 90%)", "severity": "5", "acknowledged": "0"})
        if widget_kind == "summary":
            return self._summary(problems)
        hosts = {"4821": "nas", "4812": "pve", "4790": "switch-core", "4755": "backup"}
        shown = self.ranked(problems)[: int(options.get("limit") or 10)]
        return self._list(problems, shown, hosts, now)


ADAPTER = ZabbixAdapter()
