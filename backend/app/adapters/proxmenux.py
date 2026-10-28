"""ProxMenux Monitor: the health findings of a Proxmox host, which the Proxmox API does not have.

ProxMenux itself is a menu of shell scripts for setting up a Proxmox host and
has nothing to ask. Its optional **Monitor** is a small web service on port
8008 of the host (``/api/...``, a Flask application) that checks the host on
its own and keeps a list of persistent findings: a disk that reports
SMART errors, a service that keeps failing, a storage that is nearly full.
That list, and its verdict, are what this adapter reads. Guests, nodes and
storage are the Proxmox adapter's business and are not repeated here.

Not measured: the Monitor lives on a Proxmox host, which was not at hand. The
shapes follow the project's README (``AppImage/README.md``) for ``/api/system``
and ``/api/health``, and its source for ``/api/health/status`` and
``/api/health/active-errors`` (read to learn the field names, nothing taken).
When login is switched on in the Monitor, every call but ``/api/health`` and
``/api/auth/*`` needs a long-lived token as a bearer token.
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
    ago,
    base_url,
    duration_short,
    measured,
    status_from_percent,
)

VERDICTS = {"OK": "ok", "WARNING": "warn", "CRITICAL": "bad"}
WORDS = {"ok": "Healthy", "warn": "Warning", "bad": "Critical"}


def level_of(word: Any) -> str:
    """ok, warn or bad from the Monitor's OK, WARNING or CRITICAL; anything unknown is a warning."""
    return VERDICTS.get(str(word or "").upper(), "warn")


class ProxMenuxAdapter(Adapter):
    kind = "proxmenux"
    label = "ProxMenux"
    category = "hosts"
    description = "The health verdict and the open findings of a Proxmox host, from the ProxMenux Monitor."
    icon = "proxmox"
    docs_url = "https://github.com/MacRimi/ProxMenux"
    #: Built from the project's README and source and not run against a Monitor; it stays beta until somebody confirms it on a host.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://pve:8008",
              help="The address of the ProxMenux Monitor on the Proxmox host, port 8008."),
        Field("token", "API token", type="password", secret=True,
              help="Only if login is switched on in the Monitor: a token from its Settings, under API Access Tokens. It lasts 365 days."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "Install the ProxMenux Monitor on the Proxmox host; it is an option of the ProxMenux menu and runs as the service proxmenux-monitor.",
        "If you switched on login, open the Monitor's Settings and create a token under API Access Tokens. It is shown once.",
    )
    widgets = (
        WidgetType(
            kind="health",
            label="Host health",
            description="The Monitor's verdict on the host, with how many checks are critical, warning and fine.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("critical", "warnings"),
        ),
        WidgetType(
            kind="findings",
            label="Open findings",
            description="What the Monitor has found and not yet seen resolved, the critical ones first, with its reason.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="host",
            label="Host",
            description="Processor, memory, temperature and uptime of the Proxmox host.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=60,
            metrics=("cpu", "memory", "temperature"),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        headers = {"Accept": "application/json"}
        if config.get("token"):
            headers["Authorization"] = f"Bearer {config['token']}"
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers=headers,
            verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("The ProxMenux Monitor wants a token." if not config.get("token")
                             else "The ProxMenux Monitor refused the token.")
        if response.status_code >= 400:
            raise AdapterError(f"The ProxMenux Monitor answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; the Monitor listens on port 8008 of the Proxmox host.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("The ProxMenux Monitor did not answer with JSON.", code="not_json",
                               hint="The URL probably points at another service.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/system-info", cache=0)
        status = await self._get(config, ctx, "/health/status", cache=0)
        name = (info or {}).get("hostname") if isinstance(info, dict) else None
        return f"ProxMenux Monitor answers, host {name or '?'}, {WORDS[level_of((status or {}).get('status'))].lower()}."

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        return None

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "findings":
            body = await self._get(config, ctx, "/health/active-errors")
            return self._findings((body or {}).get("errors") if isinstance(body, dict) else [], options)
        if widget_kind == "host":
            return self._host(await self._get(config, ctx, "/system"))
        return self._health(await self._get(config, ctx, "/health/status"))

    def _health(self, body: Any) -> WidgetData:
        body = body if isinstance(body, dict) else {}
        level = level_of(body.get("status"))
        critical = int(body.get("critical_count") or 0)
        warnings = int(body.get("warning_count") or 0)
        secondary = [
            {"label": "Critical", "value": critical},
            {"label": "Warnings", "value": warnings},
            {"label": "Fine", "value": int(body.get("ok_count") or 0)},
        ]
        return WidgetData(
            status=level,
            primary={"label": "Host", "value": WORDS[level]},
            secondary=secondary,
            metrics={"critical": float(critical), "warnings": float(warnings)},
            meta={"summary": str(body.get("summary") or "")} if body.get("summary") else {},
        )

    def _findings(self, errors: Any, options: dict[str, Any], now: float | None = None) -> WidgetData:
        rows = []
        for one in errors if isinstance(errors, list) else []:
            if not isinstance(one, dict):
                continue
            level = level_of(one.get("severity"))
            times = int(one.get("occurrence_count") or 0)
            # ⚠️ The Monitor writes its times as local clock readings without a zone
            # (``datetime.now().isoformat()``). Read as UTC they would be hours off, so
            # only a time that names its zone is turned into "ago".
            stamp = str(one.get("last_seen") or "")
            seen = ago(stamp, now) if stamp.endswith("Z") or "+" in stamp[10:] else ""
            parts = [str(one.get("category") or "").replace("_", " ").capitalize(), f"{times} times" if times > 1 else "",
                     f"seen {seen} ago" if seen else ""]
            rows.append((0 if level == "bad" else 1, {
                "title": " ".join(str(one.get("reason") or one.get("error_key") or "?").split())[:200],
                "subtitle": " · ".join(part for part in parts if part),
                "status": level,
                "value": "Critical" if level == "bad" else "Warning",
            }))
        rows.sort(key=lambda row: row[0])
        items = [item for _rank, item in rows][: int(options.get("limit") or 8)]
        worst = {item["status"] for item in items}
        return WidgetData(
            status="bad" if "bad" in worst else "warn" if "warn" in worst else "ok",
            items=items,
            secondary=[{"label": "Open findings", "value": len(rows)}],
        )

    def _host(self, body: Any) -> WidgetData:
        body = body if isinstance(body, dict) else {}
        cpu = body.get("cpu_usage")
        memory = body.get("memory_usage")
        temperature = body.get("temperature")
        worst = max((status_from_percent(value) for value in (cpu, memory) if isinstance(value, int | float)),
                    key=("ok", "warn", "bad").index, default="ok")
        secondary = []
        if isinstance(memory, int | float):
            secondary.append({"label": "Memory", "value": round(memory, 1), "unit": "%"})
        if isinstance(temperature, int | float) and temperature > 0:
            secondary.append({"label": "Temperature", "value": round(temperature, 1), "unit": "°C"})
        if isinstance(body.get("uptime"), int | float):
            secondary.append({"label": "Uptime", "value": duration_short(body["uptime"])})
        if body.get("pve_version"):
            secondary.append({"label": "Proxmox VE", "value": str(body["pve_version"])})
        return WidgetData(
            status=worst,
            primary={"label": "CPU", "value": round(cpu, 1), "unit": "%"} if isinstance(cpu, int | float) else None,
            secondary=secondary,
            metrics=measured({"cpu": cpu if isinstance(cpu, int | float) else None,
                              "memory": memory if isinstance(memory, int | float) else None,
                              "temperature": temperature if isinstance(temperature, int | float) and temperature > 0 else None}),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        broken = fake.flicker("proxmenux-finding", tick, 0.4)
        if widget_kind == "findings":
            errors = [{"category": "disks", "severity": "WARNING", "occurrence_count": 4,
                       "reason": "Disk /dev/sdb: reallocated sectors rising", "last_seen": "2026-10-27T12:00:00"}]
            if broken:
                errors.insert(0, {"category": "services", "severity": "CRITICAL", "occurrence_count": 1,
                                  "reason": "Service pve-cluster is not running", "last_seen": "2026-10-27T12:30:00"})
            return self._findings(errors, options, now=1793122800.0 + 3600)
        if widget_kind == "host":
            return self._host({"cpu_usage": fake.walk("proxmenux-cpu", tick, 4, 40), "memory_usage": fake.walk("proxmenux-mem", tick, 40, 62),
                               "temperature": fake.walk("proxmenux-temp", tick, 38, 52), "uptime": 345600 + tick * 30, "pve_version": "8.4.1"})
        return self._health({"status": "CRITICAL" if broken else "WARNING", "summary": "Findings need a look",
                             "critical_count": 1 if broken else 0, "warning_count": 1, "ok_count": 7})


ADAPTER = ProxMenuxAdapter()
