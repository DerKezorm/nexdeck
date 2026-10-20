"""Pulse: what Pulse watches on Proxmox, Docker and the rest, and what needs a look (issue #47).

Pulse (rcourtman/Pulse) keeps one picture of the whole fleet. It hands it to
dashboards through ``GET /api/state/summary``, which needs an API token with
the scope ``monitoring:read`` and nothing more; the active alerts come from
``GET /api/alerts/active`` under the same scope. The token rides in
``X-API-Token``. The cards only read.

⚠️ The summary grew. Pulse 6.0 to 6.4 answer with the counts alone (alerts,
nodes, VMs, containers, Docker hosts); 6.5.0 added ``verdicts`` and
``attention``, the fleet health in six words and the resources that need a
look, worst first and at most 30. On an older Pulse the overview shows the
counts and the attention card says what it needs.

⚠️ ``containers`` in the summary are Proxmox's LXC. Docker's containers are
counted per entry of ``dockerHosts``; a Pulse that watches only Docker says
``"containers": 0``.

⚠️ ``off`` is a powered-off workload and is neutral in Pulse, so it never
colours a card here either; Pulse leaves ``ok`` and ``off`` out of the
attention list. A stopped Docker container is ``off`` and still raises a
warning alert of type ``docker-container-state``. ``stale`` and ``unknown``
mean Pulse has no fresh reading, which is not the same as healthy.

⚠️ For a Docker container the alert's ``node`` is the agent's hostname, which
is a container ID when the agent runs in one; ``metadata.hostName`` carries
the name Pulse shows.

Written against Pulse's own sources (``internal/api/state_summary.go``,
``internal/unifiedresources/health.go``, ``internal/alerts/model.go``,
v6.5.0, October 2026) and run against a fresh Pulse 6.5.0 on 20.10.2026 with
one Docker agent (67 containers, 19 of them stopped), a token with
``monitoring:read``, one with ``settings:read`` alone (403 ``missing_scope``)
and a wrong one (401 "Invalid API token"). Not yet against Proxmox, hence beta.
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

#: The verdicts the attention list can carry, worst first, and the colour each
#: gives a row. Pulse leaves ``ok`` and ``off`` out of that list.
VERDICT_ORDER = ("critical", "attention", "stale", "unknown")
VERDICT_STATUS = {"critical": "bad", "attention": "warn", "stale": "unknown", "unknown": "unknown"}
VERDICT_WORD = {"critical": "Critical", "attention": "Needs attention", "stale": "Stale", "unknown": "Unknown"}
#: Why a resource got its verdict, from ``health.go``; anything new is shown as Pulse names it.
REASON_WORD = {
    "offline": "Offline",
    "critical_alert": "Critical alert",
    "warning_alert": "Warning",
    "availability_failed": "Check failed",
    "critical_incident": "Incident",
    "resource_risk": "At risk",
    "backup_stale": "Backup is old",
    "telemetry_stale": "No fresh data",
    "telemetry_missing": "No data",
    "powered_off": "Powered off",
    "degraded": "Degraded",
    "status_unknown": "State unknown",
}
#: The resource types of ``/api/resources``, as a person would say them.
TYPE_WORD = {
    "agent": "Server",
    "node": "Node",
    "vm": "VM",
    "system-container": "LXC",
    "app-container": "Container",
    "docker-service": "Docker service",
    "storage": "Storage",
    "pbs": "Backup server",
    "pmg": "Mail gateway",
    "k8s-cluster": "Kubernetes cluster",
    "k8s-node": "Kubernetes node",
    "pod": "Pod",
    "k8s-deployment": "Deployment",
    "physical_disk": "Disk",
    "ceph": "Ceph",
}


class PulseAdapter(Adapter):
    kind = "pulse"
    label = "Pulse"
    category = "monitoring"
    description = "What Pulse watches on Proxmox, Docker and the rest, and what needs a look."
    icon = "pulse"
    beta = True
    docs_url = "https://github.com/rcourtman/Pulse/blob/main/docs/API.md"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://pulse:7655"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="In Pulse under Settings, API Access, with the scope monitoring:read."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In Pulse, open Settings, then API Access, and create a token.",
        "Pick the preset Kiosk / Monitoring, which gives it monitoring:read alone. The cards write nothing.",
        "Copy the token right away: Pulse shows it only once.",
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Pulse overview",
            description="Active alerts, nodes, VMs and containers, and how many resources need a look.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("alerts", "critical", "attention"),
        ),
        WidgetType(
            kind="attention",
            label="Needs a look",
            description="The resources Pulse is not happy with, worst first, with the reason. Pulse 6.5 or newer.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="alerts",
            label="Active alerts",
            description="Critical alerts and warnings, critical first, with how long each has been open.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("critical", "warning"),
            options=(
                Field("limit", "Entries", type="number", default=8),
                Field("acknowledged", "Show acknowledged alerts", type="bool", default=True),
            ),
        ),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}",
            headers={"X-API-Token": str(config.get("token") or ""), "Accept": "application/json"},
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code == 401:
            raise AuthFailed("Pulse does not know this token.")
        if response.status_code == 403:
            raise AdapterError("The token may not read what Pulse watches.", code="missing_scope",
                               hint="Give the token the scope monitoring:read in Pulse under Settings, API Access.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Pulse does.", code="not_pulse",
                               hint="Pulse 6.0 or newer is needed, at its own address, usually on port 7655.")
        if response.status_code >= 400:
            raise AdapterError(f"Pulse answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Pulse did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Pulse.") from error

    async def _summary(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> dict[str, Any]:
        answer = await self._json(config, ctx, "/api/state/summary", cache=cache)
        if not isinstance(answer, dict) or "activeAlerts" not in answer:
            raise AdapterError("This address answers, but not the way Pulse does.", code="not_pulse",
                               hint="Pulse 6.0 or newer is needed, at its own address, usually on port 7655.")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        summary = await self._summary(config, ctx, cache=0)
        verdicts = summary.get("verdicts")
        if isinstance(verdicts, dict):
            return f"Pulse answers and watches {sum(_count(value) for value in verdicts.values())} resources."
        return "Pulse answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "alerts":
            answer = await self._json(config, ctx, "/api/alerts/active")
            if not isinstance(answer, list):
                raise AdapterError("This address answers, but not the way Pulse does.", code="not_pulse")
            return self.alerts_card(answer, options, base_url(config))
        summary = await self._summary(config, ctx)
        if widget_kind == "attention":
            return self.attention_card(summary, options, base_url(config))
        return self.overview_card(summary, base_url(config))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def overview_card(summary: dict[str, Any], link: str | None = None) -> WidgetData:
        alerts = _count(summary.get("activeAlerts"))
        verdicts = summary.get("verdicts") if isinstance(summary.get("verdicts"), dict) else None
        docker_hosts = [host for host in summary.get("dockerHosts") or [] if isinstance(host, dict)]
        # ``containers`` are Proxmox's LXC; Docker's are counted per Docker host.
        counted = [
            ("Nodes", _count(summary.get("nodes"))),
            ("VMs", _count(summary.get("vms"))),
            ("LXC containers", _count(summary.get("containers"))),
            ("Docker containers", sum(_count(host.get("containers")) for host in docker_hosts)),
        ]
        # A Pulse that watches only Docker would otherwise show three zeros.
        secondary: list[dict[str, Any]] = [{"label": label, "value": value} for label, value in counted if value] or [
            {"label": "Nodes", "value": 0}]
        metrics = {"alerts": float(alerts)}
        if verdicts is None:
            # Pulse before 6.5 only counts the alerts, not how bad they are.
            status = "warn" if alerts else "ok"
        else:
            critical = _count(verdicts.get("critical"))
            attention = _count(verdicts.get("attention"))
            unclear = _count(verdicts.get("stale")) + _count(verdicts.get("unknown"))
            if critical:
                secondary.insert(0, {"label": "Critical", "value": critical})
            if attention:
                secondary.insert(1 if critical else 0, {"label": "Needs attention", "value": attention})
            if unclear:
                secondary.append({"label": "No fresh data", "value": unclear})
            metrics |= {"critical": float(critical), "attention": float(attention)}
            status = "bad" if critical else "warn" if attention or alerts else "ok"
        return WidgetData(
            status=status,
            primary={"label": "Active alerts", "value": alerts},
            secondary=secondary,
            metrics=metrics,
            link=link,
        )

    @staticmethod
    def attention_card(summary: dict[str, Any], options: dict[str, Any], link: str | None = None) -> WidgetData:
        if not isinstance(summary.get("verdicts"), dict):
            return WidgetData(
                status="unknown",
                link=link,
                meta={"empty": "This card needs Pulse 6.5 or newer."},
            )
        rows = [row for row in summary.get("attention") or [] if isinstance(row, dict)]
        rank = {verdict: index for index, verdict in enumerate(VERDICT_ORDER)}
        rows.sort(key=lambda row: rank.get(str(row.get("verdict") or "unknown"), len(VERDICT_ORDER)))
        limit = max(1, min(30, int(options.get("limit") or 8)))
        items = []
        for row in rows[:limit]:
            verdict = str(row.get("verdict") or "unknown")
            kind = str(row.get("type") or "")
            items.append({
                "title": str(row.get("name") or row.get("id") or "?"),
                "subtitle": " · ".join(piece for piece in (TYPE_WORD.get(kind, kind.replace("-", " ").replace("_", " ")), _reason(row.get("topReason"))) if piece),
                "value": VERDICT_WORD.get(verdict, verdict),
                "status": VERDICT_STATUS.get(verdict, "unknown"),
            })
        worst = [VERDICT_STATUS.get(str(row.get("verdict") or "unknown"), "unknown") for row in rows]
        verdicts = summary["verdicts"]
        return WidgetData(
            # Without a fresh reading Pulse cannot say a resource is fine, so neither does the card.
            status="bad" if "bad" in worst else "warn" if "warn" in worst else "unknown" if worst else "ok",
            items=items,
            secondary=[
                {"label": "OK", "value": _count(verdicts.get("ok"))},
                {"label": "Off", "value": _count(verdicts.get("off"))},
            ],
            link=link,
            meta={"empty": "Nothing needs a look."},
        )

    @staticmethod
    def alerts_card(alerts: list[Any], options: dict[str, Any], link: str | None = None, now: float | None = None) -> WidgetData:
        shown_acknowledged = options.get("acknowledged", True) is not False
        raised = [one for one in alerts if isinstance(one, dict)]
        if not shown_acknowledged:
            raised = [one for one in raised if not one.get("acknowledged")]
        raised.sort(key=lambda one: (0 if _is_critical(one) else 1, bool(one.get("acknowledged")), str(one.get("startTime") or "")))
        limit = max(1, min(50, int(options.get("limit") or 8)))
        items = []
        for one in raised[:limit]:
            # For a Docker container ``node`` is the agent's hostname, often a container ID; the host's name is in the metadata.
            meta = one.get("metadata") if isinstance(one.get("metadata"), dict) else {}
            where = str(meta.get("hostName") or one.get("nodeDisplayName") or one.get("node") or "")
            subtitle = [str(one.get("message") or one.get("type") or "")]
            if where and where != one.get("resourceName"):
                subtitle.append(where)
            if one.get("acknowledged"):
                subtitle.append("Acknowledged")
            items.append({
                "title": str(one.get("resourceName") or one.get("resourceId") or "?"),
                "subtitle": " · ".join(piece for piece in subtitle if piece),
                "value": _since(one.get("startTime"), now),
                "status": "bad" if _is_critical(one) else "warn",
            })
        open_ones = [one for one in raised if not one.get("acknowledged")]
        critical = sum(1 for one in raised if _is_critical(one))
        warning = len(raised) - critical
        return WidgetData(
            status="bad" if any(_is_critical(one) for one in open_ones) else "warn" if open_ones else "ok",
            items=items,
            secondary=[{"label": "Critical", "value": critical}, {"label": "Warning", "value": warning}],
            metrics={"critical": float(critical), "warning": float(warning)},
            link=link,
            meta={"empty": "No alert is raised."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        busy = fake.flicker("pulse-busy", tick, 0.3)
        attention = [
            {"id": "vm:pve1:104", "name": "backup-runner", "type": "vm", "platformType": "proxmox",
             "verdict": "attention", "topReason": {"code": "backup_stale", "detail": "9d"}},
            {"id": "storage:pve2:local-zfs", "name": "local-zfs", "type": "storage", "platformType": "proxmox",
             "verdict": "attention", "topReason": {"code": "warning_alert", "detail": "disk"}},
        ]
        if busy:
            attention.insert(0, {"id": "agent:pve3", "name": "pve3", "type": "agent", "platformType": "proxmox",
                                 "verdict": "critical", "topReason": {"code": "offline"}})
        summary = {
            "activeAlerts": 2 + (1 if busy else 0), "nodes": 3, "vms": 14, "containers": 22,
            "dockerHosts": [{"name": "docker-live", "containers": 31}],
            "verdicts": {"ok": 52, "attention": 2, "critical": 1 if busy else 0, "stale": 0, "off": 4, "unknown": 0},
            "attention": attention,
        }
        if widget_kind == "attention":
            return self.attention_card(summary, options)
        if widget_kind == "alerts":
            now = time.time()
            alerts = [
                {"id": "a1", "type": "disk", "level": "warning", "resourceName": "local-zfs", "node": "pve2",
                 "message": f"Disk usage at {fake.walk('pulse-disk', tick, 86, 91):.0f}%", "startTime": now - 5400},
                {"id": "a2", "type": "memory", "level": "warning", "resourceName": "jellyfin", "node": "pve1",
                 "message": "Memory usage at 88%", "startTime": now - 1300, "acknowledged": True},
            ]
            if busy:
                alerts.append({"id": "a3", "type": "offline", "level": "critical", "resourceName": "pve3", "node": "pve3",
                               "message": "Node is offline", "startTime": now - 240})
            return self.alerts_card(alerts, options, now=now)
        return self.overview_card(summary)


def _is_critical(alert: dict[str, Any]) -> bool:
    return str(alert.get("level") or "").strip().lower() == "critical"


def _reason(raw: Any) -> str:
    if not isinstance(raw, dict) or not raw.get("code"):
        return ""
    code = str(raw["code"])
    word = REASON_WORD.get(code, code.replace("_", " ").capitalize())
    detail = str(raw.get("detail") or "").strip()
    return f"{word} · {detail}" if detail else word


def _since(moment: Any, now: float | None) -> str:
    # Go writes an unset time as the year 1, which would read as 739,000 days.
    if isinstance(moment, str) and moment.startswith("0001-"):
        return ""
    return ago(moment, now=now)


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


ADAPTER = PulseAdapter()
