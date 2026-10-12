"""FortiGate: the firewall's load, its interfaces, its IPsec tunnels and its cluster (issue #41).

FortiOS answers under ``/api/v2/monitor/`` to a REST API administrator's
token, sent as a bearer token and never in the address, where it would end
up in every log on the way. The administrator needs read access only, and
nexdeck's address among its trusted hosts.

Every answer wraps its ``results`` in an envelope that also carries the
serial number and the FortiOS version, so the version costs no request of
its own.

⚠️ Written against public sources (Fortinet's administration guide and the
monitoring plugins of Linuxfabrik, which read the same endpoints), not yet
against a FortiGate. Hence beta. Read only: no tunnel is brought down and no
interface switched off from a card.
"""

from __future__ import annotations

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
    base_url,
    gauge_view_field,
    human_bytes,
    measured,
    percent_primary,
    status_from_percent,
)


class FortigateAdapter(Adapter):
    kind = "fortigate"
    label = "FortiGate"
    category = "network"
    description = "Load, sessions, interfaces, IPsec tunnels and the HA cluster of a FortiGate."
    icon = "fortinet"
    beta = True
    docs_url = "https://docs.fortinet.com/document/fortigate/7.6.0/administration-guide/399023/rest-api-administrator"
    keywords = ("Fortinet", "FortiOS")
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://fortigate.example.com"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Of a REST API administrator with a read-only profile."),
        Field("vdom", "VDOM", placeholder="root", help="Empty means the FortiGate's own default."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True, help="On by default: most firewalls answer with their own certificate."),
    )
    guide = (
        "In FortiOS, create an administrator profile with read access only.",
        "Under System, Administrators, create a REST API admin with that profile.",
        "Enter nexdeck's address under Trusted hosts, then copy the token: FortiOS shows it once.",
    )
    widgets = (
        WidgetType(
            kind="system",
            label="System",
            description="Processor, memory, sessions and the FortiOS version.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("cpu", "memory", "sessions"),
            # The number is already a share of the machine; no ceiling needed.
            options=(gauge_view_field(),),
        ),
        WidgetType(
            kind="interfaces",
            label="Interfaces",
            description="One line per interface with its link, address, speed and traffic.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("interfaces_down",),
            options=(
                Field("names", "Interfaces", placeholder="wan1, wan2",
                      help="Names, separated by commas. Only these are shown, and one of them without a link turns the card red. Empty shows all."),
                Field("limit", "Entries", type="number", default=12),
            ),
        ),
        WidgetType(
            kind="ipsec",
            label="IPsec tunnels",
            description="Every IPsec tunnel with its state, remote gateway and traffic.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("tunnels_down",),
        ),
        WidgetType(
            kind="ha",
            label="HA cluster",
            description="The members of the cluster, which one is primary, and whether they are in sync.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=120,
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> dict[str, Any]:
        query = dict(params or {})
        vdom = str(config.get("vdom") or "").strip()
        if vdom:
            query["vdom"] = vdom
        payload = await ctx.get_json(
            f"{base_url(config)}/api/v2/monitor{path}",
            headers={"Authorization": f"Bearer {config.get('token') or ''}", "Accept": "application/json"},
            params=query or None,
            verify=not config.get("insecure", True),
            cache_seconds=cache,
        )
        if not isinstance(payload, dict):
            raise AdapterError("The FortiGate answered with something other than an object.", code="unexpected_answer")
        if str(payload.get("status") or "success") != "success":
            raise AdapterError(f"FortiOS refused {path}: {payload.get('status')}.", code="fortios_error",
                               hint="Check the administrator profile and the VDOM.")
        return payload

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await self._get(config, ctx, "/system/status", cache=0)
        results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
        model = results.get("model") or " ".join(str(part) for part in (results.get("model_name"), results.get("model_number")) if part) or "FortiGate"
        return f"{model} answers, FortiOS {payload.get('version') or '?'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "interfaces":
            return await self._interfaces(config, ctx, options)
        if widget_kind == "ipsec":
            return await self._ipsec(config, ctx)
        if widget_kind == "ha":
            return await self._ha(config, ctx)
        return await self._system(config, ctx)

    async def _system(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        payload = await self._get(config, ctx, "/system/resource/usage", {"interval": "1-min"})
        usage = payload.get("results") if isinstance(payload.get("results"), dict) else {}
        cpu, memory, sessions = _current(usage, "cpu"), _current(usage, "mem"), _current(usage, "session")
        worst = max((value for value in (cpu, memory) if value is not None), default=None)
        secondary: list[dict[str, Any]] = [
            {"label": "Memory", "value": round(memory) if memory is not None else None, "unit": "%" if memory is not None else ""},
            {"label": "Sessions", "value": int(sessions) if sessions is not None else None},
        ]
        if payload.get("version"):
            secondary.append({"label": "FortiOS", "value": str(payload["version"])})
        return WidgetData(
            status=status_from_percent(worst),
            primary=percent_primary("CPU", round(cpu) if cpu is not None else None),
            secondary=secondary,
            metrics=measured({"cpu": cpu, "memory": memory, "sessions": sessions}),
        )

    async def _interfaces(self, config: dict[str, Any], ctx: Context, options: dict[str, Any]) -> WidgetData:
        payload = await self._get(config, ctx, "/system/interface/select")
        raw = payload.get("results")
        # A dictionary by name in every answer seen; a list would carry the same rows.
        rows = list(raw.values()) if isinstance(raw, dict) else list(raw or [])
        wanted = [name.strip() for name in str(options.get("names") or "").split(",") if name.strip()]
        if wanted:
            by_name = {str(row.get("name") or ""): row for row in rows if isinstance(row, dict)}
            rows = [by_name.get(name) or {"name": name, "missing": True} for name in wanted]
        limit = max(1, min(50, int(options.get("limit") or 12)))
        items = []
        down = 0
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "?")
            alias = str(row.get("alias") or "").strip()
            if row.get("missing"):
                down += 1
                items.append({"title": name, "subtitle": "Not on this FortiGate", "value": "?", "status": "bad"})
                continue
            up = bool(row.get("link"))
            # Only an interface somebody named is expected to have a link; a
            # free port of the internal switch is not a fault.
            if not up and wanted:
                down += 1
            parts = []
            if row.get("ip") and str(row.get("ip")) != "0.0.0.0":
                parts.append(f"{row['ip']}/{row['mask']}" if row.get("mask") not in (None, "") else str(row["ip"]))
            if up and row.get("speed"):
                parts.append(f"{_number(row.get('speed'))} Mbit/s")
            if row.get("rx_bytes") is not None or row.get("tx_bytes") is not None:
                parts.append(f"↓ {human_bytes(_number(row.get('rx_bytes')))} ↑ {human_bytes(_number(row.get('tx_bytes')))}")
            errors = _number(row.get("rx_errors")) + _number(row.get("tx_errors"))
            if errors:
                parts.append(f"{errors} errors")
            items.append({
                "title": f"{name} ({alias})" if alias and alias != name else name,
                "subtitle": " · ".join(parts),
                "value": "up" if up else "down",
                "status": "ok" if up else ("bad" if wanted else "unknown"),
            })
        return WidgetData(
            status="bad" if down else "ok",
            items=items,
            secondary=[{"label": "Up", "value": sum(1 for item in items if item["value"] == "up")}, {"label": "Down", "value": down}] if wanted else [],
            metrics={"interfaces_down": float(down)},
            meta={"empty": "No interfaces."},
        )

    async def _ipsec(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        payload = await self._get(config, ctx, "/vpn/ipsec")
        items = []
        down = 0
        for tunnel in payload.get("results") or []:
            if not isinstance(tunnel, dict):
                continue
            selectors = [one for one in tunnel.get("proxyid") or [] if isinstance(one, dict)]
            # The template of a dial-up tunnel stands in the list without a
            # selector of its own; its clients are the tunnels that count.
            if not selectors and str(tunnel.get("type") or "") == "dialup":
                continue
            up_count = sum(1 for one in selectors if str(one.get("status") or "").lower() == "up")
            whole = up_count == len(selectors) and up_count > 0
            if not up_count:
                down += 1
            parts = [str(tunnel.get("rgwy") or "")]
            parts.append(f"↓ {human_bytes(_number(tunnel.get('incoming_bytes')))} ↑ {human_bytes(_number(tunnel.get('outgoing_bytes')))}")
            value = "up" if whole else (f"{up_count} of {len(selectors)} up" if up_count else "down")
            items.append({
                "title": str(tunnel.get("name") or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "value": value,
                "status": "ok" if whole else ("warn" if up_count else "bad"),
            })
        items.sort(key=lambda item: {"bad": 0, "warn": 1}.get(item["status"], 2))
        return WidgetData(
            status="bad" if down else ("warn" if any(item["status"] == "warn" for item in items) else "ok"),
            items=items,
            secondary=[{"label": "Up", "value": sum(1 for item in items if item["status"] == "ok")}, {"label": "Down", "value": down}],
            metrics={"tunnels_down": float(down)},
            meta={"empty": "No IPsec tunnels."},
        )

    async def _ha(self, config: dict[str, Any], ctx: Context) -> WidgetData:
        try:
            payload = await self._get(config, ctx, "/system/ha-peer", cache=60)
        except AuthFailed:
            raise
        except AdapterError:
            # A FortiGate on its own answers the cluster question with an error.
            payload = {"results": []}
        members = [one for one in payload.get("results") or [] if isinstance(one, dict)]
        if not members:
            return WidgetData(items=[], meta={"empty": "This FortiGate is not in a cluster."})
        in_sync = await self._in_sync(config, ctx)
        items = []
        for member in members:
            primary = bool(member.get("primary") or member.get("master") or member.get("is_manage_primary"))
            parts = [str(member.get("serial_no") or "")]
            if member.get("priority") is not None:
                parts.append(f"priority {member['priority']}")
            items.append({
                "title": str(member.get("hostname") or member.get("serial_no") or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "value": "Primary" if primary else "Secondary",
                "status": "ok",
            })
        items.sort(key=lambda item: 0 if item["value"] == "Primary" else 1)
        secondary: list[dict[str, Any]] = [{"label": "Members", "value": len(items)}]
        if in_sync is not None:
            secondary.append({"label": "Sync", "value": "in sync" if in_sync else "out of sync"})
        return WidgetData(status="warn" if in_sync is False else "ok", items=items, secondary=secondary)

    async def _in_sync(self, config: dict[str, Any], ctx: Context) -> bool | None:
        """Whether every member holds the same configuration, or ``None`` when the FortiGate does not say."""
        try:
            payload = await self._get(config, ctx, "/system/ha-checksums", cache=60)
        except AuthFailed:
            raise
        except AdapterError:
            return None
        sums = []
        for member in payload.get("results") or []:
            checksum = member.get("checksum") if isinstance(member, dict) else None
            if isinstance(checksum, dict) and checksum.get("all"):
                sums.append(str(checksum["all"]))
        return len(set(sums)) == 1 if len(sums) >= 2 else None

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "interfaces":
            lte_down = fake.flicker("fortigate-wan2", tick, 0.1)
            rows = [
                ("wan1 (Fibre)", "203.0.113.24/29 · 1000 Mbit/s · ↓ 1.2 TB ↑ 210.4 GB", True),
                ("wan2 (LTE)", "198.51.100.7/30 · 100 Mbit/s · ↓ 12.8 GB ↑ 3.1 GB", not lte_down),
                ("internal", "192.168.1.1/24 · 1000 Mbit/s · ↓ 640.2 GB ↑ 1.4 TB", True),
            ]
            return WidgetData(
                status="bad" if lte_down else "ok",
                items=[{"title": title, "subtitle": subtitle, "value": "up" if up else "down", "status": "ok" if up else "bad"} for title, subtitle, up in rows],
                secondary=[{"label": "Up", "value": 2 if lte_down else 3}, {"label": "Down", "value": 1 if lte_down else 0}],
                metrics={"interfaces_down": 1.0 if lte_down else 0.0},
            )
        if widget_kind == "ipsec":
            return WidgetData(
                status="ok",
                items=[
                    {"title": "to-branch", "subtitle": "198.51.100.40 · ↓ 48.2 GB ↑ 31.7 GB", "value": "up", "status": "ok"},
                    {"title": "to-datacentre", "subtitle": "203.0.113.90 · ↓ 3.4 TB ↑ 1.1 TB", "value": "up", "status": "ok"},
                ],
                secondary=[{"label": "Up", "value": 2}, {"label": "Down", "value": 0}],
                metrics={"tunnels_down": 0.0},
            )
        if widget_kind == "ha":
            return WidgetData(status="ok", items=[
                {"title": "fw-office-a", "subtitle": "FGT60FTK00000001 · priority 200", "value": "Primary", "status": "ok"},
                {"title": "fw-office-b", "subtitle": "FGT60FTK00000002 · priority 100", "value": "Secondary", "status": "ok"},
            ], secondary=[{"label": "Members", "value": 2}, {"label": "Sync", "value": "in sync"}])
        cpu = fake.walk("fortigate-cpu", tick, 3, 38)
        memory = fake.walk("fortigate-mem", tick, 41, 58)
        sessions = int(fake.walk("fortigate-sessions", tick, 900, 4200))
        return WidgetData(
            status=status_from_percent(max(cpu, memory)),
            primary={"label": "CPU", "value": round(cpu), "unit": "%"},
            secondary=[{"label": "Memory", "value": round(memory), "unit": "%"}, {"label": "Sessions", "value": sessions}, {"label": "FortiOS", "value": "v7.4.8"}],
            metrics={"cpu": cpu, "memory": memory, "sessions": float(sessions)},
        )


def _current(usage: dict[str, Any], resource: str) -> float | None:
    """The reading of one resource: ``results[resource][0].current``."""
    rows = usage.get(resource)
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    value = rows[0].get("current")
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _number(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


ADAPTER = FortigateAdapter()
