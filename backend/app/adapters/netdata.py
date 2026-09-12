"""Netdata: which alerts are raised on which node, and how loaded each node is.

Measured against Netdata 2.11.0 on 11.09.2026, with a parent and one child
streaming to it, two test alerts in ``health.d`` (one that always warns on
``system.load``, one that is always critical on ``system.cpu``), and the child
stopped once and started again.

⚠️ The agent's API asks for no credentials. A made-up bearer token is ignored
and gets 200 like no token at all. Bearer protection exists only for agents
claimed to Netdata Cloud, whose token comes from the cloud, so the cards send
none. The one refusal seen was ``/api/v1/manage/health``: 451 "You need to be
authorized to access this resource".

⚠️ ``/api/v1/alarms`` covers only the node it is asked on; on a parent that is
the parent alone. ``/api/v3/alerts?status=raised&options=instances,values``
answers for every node that streams to it, each instance with a node index
``ni`` into the ``nodes`` list of the same answer. Nothing raised is
``"alert_instances": []``.

⚠️ A child that stops streaming turns ``stale`` within seconds, its health
becomes ``{"status": "disabled"}`` and its raised alerts are gone from the
list. An alert card alone looks calmer the moment a machine goes away, so the
node card says Stale and the overview counts the nodes that report.

⚠️ ``/api/v3/data`` grouped by node names its columns by machine GUID, and
each cell is ``[value, anomaly rate, annotations]`` as ``result.point`` says.
A stale node still gets a value from the minute before it went away, so the
card shows no load for it.
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
)

#: The two states ``status=raised`` hands out, worst first.
SEVERITY = {"CRITICAL": 0, "WARNING": 1}
STATE_WORD = {"CRITICAL": "Critical", "WARNING": "Warning"}
NODE_WORD = {"reachable": "Online", "stale": "Stale", "offline": "Offline"}
STATUS_ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}


def _number(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _reading(value: float | None, units: str) -> str:
    """``5.27 %``, ``1.01 load``: what the alert measured, as Netdata names the unit."""
    if value is None:
        return ""
    number = f"{value:.2f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:.0f}"
    return f"{number} {units}".strip()


def _alert_counts(node: dict[str, Any]) -> tuple[int, int]:
    health = node.get("health") if isinstance(node.get("health"), dict) else {}
    alerts = health.get("alerts") if isinstance(health.get("alerts"), dict) else {}
    return int(_number(alerts.get("critical")) or 0), int(_number(alerts.get("warning")) or 0)


class NetdataAdapter(Adapter):
    kind = "netdata"
    label = "Netdata"
    category = "monitoring"
    description = "Raised alerts on every node, and how loaded each node is."
    icon = "netdata"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://learn.netdata.cloud/docs/developer-and-contributor-corner/rest-api/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://netdata:19999",
              help="The agent, or the parent the other nodes stream to; a parent answers for all of them."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="alerts", label="Raised alerts", description="Critical alerts and warnings on every node, critical first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("critical", "warning"),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="nodes", label="Load per node", description="The load of every node over the last minute, with its state and its worst alert.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60,
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Alerts", description="Raised alerts, how many of them are critical, and how many nodes report.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("critical", "warning")),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}", params=params,
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # 451 is what the agent answered where it wanted a sign-in.
        if response.status_code in (401, 403, 451):
            raise AuthFailed("Netdata refused the request. Bearer protection may be on, or a proxy in front of the agent wants a sign-in.")
        if response.status_code >= 400:
            raise AdapterError(f"Netdata answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of the agent itself, usually on port 19999.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Netdata did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than a Netdata agent.") from error

    async def _nodes(self, config: dict[str, Any], ctx: Context, cache: float = 10) -> list[dict[str, Any]]:
        answer = await self._json(config, ctx, "/api/v3/nodes", cache=cache)
        if not isinstance(answer, dict) or not isinstance(answer.get("nodes"), list):
            raise AdapterError("This address answers, but not the way Netdata does.", code="not_netdata")
        return [one for one in answer["nodes"] if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        nodes = await self._nodes(config, ctx, cache=0)
        version = next((str(one.get("v") or "") for one in nodes if one.get("ni") == 0), "") or "?"
        return f"Netdata {version} answers with {len(nodes)} nodes."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "alerts":
            answer = await self._json(config, ctx, "/api/v3/alerts", {"status": "raised", "options": "instances,values"})
            if not isinstance(answer, dict) or not isinstance(answer.get("nodes"), list):
                raise AdapterError("This address answers, but not the way Netdata does.", code="not_netdata")
            return self._alerts(answer, options, time.time())
        nodes = await self._nodes(config, ctx)
        if widget_kind == "summary":
            return self._summary(nodes)
        answer = await self._json(config, ctx, "/api/v3/data", {
            "scope_contexts": "system.load", "dimensions": "load1", "group_by": "node",
            "after": -60, "points": 1, "time_group": "average", "format": "json2",
        })
        return self._node_list(nodes, self.loads_of(answer), options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def loads_of(answer: Any) -> dict[str, float]:
        """The newest load per machine GUID out of a data query grouped by node."""
        result = answer.get("result") if isinstance(answer, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("labels"), list) or not result.get("data"):
            return {}
        latest = result["data"][-1]
        index = int(_number((result.get("point") or {}).get("value")) or 0)
        loads: dict[str, float] = {}
        for guid, cell in zip(result["labels"][1:], latest[1:] if isinstance(latest, list) else [], strict=False):
            value = _number(cell[index] if isinstance(cell, list) and len(cell) > index else cell)
            if value is not None:
                loads[str(guid)] = value
        return loads

    @staticmethod
    def _alerts(answer: dict[str, Any], options: dict[str, Any], now: float) -> WidgetData:
        names = {one.get("ni"): str(one.get("nm") or "") for one in answer.get("nodes") or [] if isinstance(one, dict)}
        raised = [one for one in answer.get("alert_instances") or [] if isinstance(one, dict) and one.get("st") in SEVERITY]
        raised.sort(key=lambda one: (SEVERITY[one["st"]], -(_number(one.get("tr_t")) or 0), str(one.get("nm") or "")))
        items = []
        for one in raised[: int(options.get("limit") or 10)]:
            pieces = (STATE_WORD[one["st"]], names.get(one.get("ni"), ""), _reading(_number(one.get("v")), str(one.get("units") or "")))
            items.append({
                "title": str(one.get("nm") or "?"),
                "subtitle": " · ".join(piece for piece in pieces if piece),
                "status": "bad" if one["st"] == "CRITICAL" else "warn",
                "value": ago(one.get("tr_t"), now=now),
            })
        critical = sum(1 for one in raised if one["st"] == "CRITICAL")
        warning = len(raised) - critical
        return WidgetData(
            status="bad" if critical else "warn" if warning else "ok",
            items=items,
            secondary=[{"label": "Critical", "value": critical}, {"label": "Warning", "value": warning}],
            meta={"empty": "No alert is raised."},
            metrics={"critical": float(critical), "warning": float(warning)},
        )

    @staticmethod
    def _node_list(nodes: list[dict[str, Any]], loads: dict[str, float], options: dict[str, Any]) -> WidgetData:
        rows = []
        for node in nodes:
            state = str(node.get("state") or "")
            reachable = state == "reachable"
            critical, warning = _alert_counts(node)
            load = loads.get(str(node.get("mg") or "")) if reachable else None
            cores = _number((node.get("hw") or {}).get("cpus")) if isinstance(node.get("hw"), dict) else None
            if not reachable or critical:
                status = "bad"
            elif warning or (load is not None and cores and load > cores):
                status = "warn"
            else:
                status = "ok"
            worst = "Critical" if critical else "Warning" if warning else ""
            rows.append((reachable, STATUS_ORDER[status], -(load or 0.0), {
                "title": str(node.get("nm") or "?"),
                "subtitle": " · ".join(piece for piece in (NODE_WORD.get(state, "Unknown"), worst if reachable else "") if piece),
                "status": status,
                "value": f"{load:.2f}" if load is not None else "",
            }))
        # A node that went away first, then the worst, then the busiest.
        rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]["title"]))
        items = [row[3] for row in rows]
        reporting = sum(1 for node in nodes if node.get("state") == "reachable")
        return WidgetData(
            status="bad" if any(item["status"] == "bad" for item in items) else "warn" if any(item["status"] == "warn" for item in items) else "ok",
            items=items[: int(options.get("limit") or 10)],
            secondary=[{"label": "Nodes online", "value": f"{reporting}/{len(nodes)}"}],
            meta={"empty": "No nodes yet."},
        )

    @staticmethod
    def _summary(nodes: list[dict[str, Any]]) -> WidgetData:
        counts = [_alert_counts(node) for node in nodes if node.get("state") == "reachable"]
        critical = sum(one[0] for one in counts)
        warning = sum(one[1] for one in counts)
        reporting = len(counts)
        return WidgetData(
            status="bad" if critical or reporting < len(nodes) else "warn" if warning else "ok",
            primary={"label": "Raised alerts", "value": critical + warning},
            secondary=[{"label": "Critical", "value": critical}, {"label": "Nodes online", "value": f"{reporting}/{len(nodes)}"}],
            metrics={"critical": float(critical), "warning": float(warning)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        busy = fake.flicker("netdata-busy", tick, 0.3)
        gone = fake.flicker("netdata-gone", tick, 0.1)
        names = ("pve", "nas", "backup")
        nodes = [
            {"mg": f"guid-{name}", "nm": name, "ni": index, "hw": {"cpus": "4"},
             "state": "stale" if gone and name == "backup" else "reachable",
             "health": {"status": "disabled"} if gone and name == "backup" else
             {"status": "online", "alerts": {"critical": 1 if busy and name == "nas" else 0, "warning": 1 if name == "pve" else 0}}}
            for index, name in enumerate(names)
        ]
        if widget_kind == "summary":
            return self._summary(nodes)
        if widget_kind == "nodes":
            loads = {"guid-pve": fake.walk("netdata-pve", tick, 0.6, 3.2), "guid-nas": fake.walk("netdata-nas", tick, 0.2, 5.1),
                     "guid-backup": fake.walk("netdata-backup", tick, 0.1, 0.9)}
            return self._node_list(nodes, loads, options)
        instances = [{"ni": 0, "nm": "10min_cpu_usage", "st": "WARNING", "units": "%", "v": fake.walk("netdata-cpu", tick, 76, 88), "tr_t": now - 1500}]
        if busy:
            instances.append({"ni": 1, "nm": "disk_space_usage", "st": "CRITICAL", "units": "%", "v": 97.4, "tr_t": now - 420})
        return self._alerts({"nodes": [{"ni": node["ni"], "nm": node["nm"]} for node in nodes], "alert_instances": instances}, options, now)


ADAPTER = NetdataAdapter()
