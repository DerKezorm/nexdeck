"""Proxmox Backup Server: how full the datastores are, and did the jobs run.

⚠️ The token header is not the one Proxmox VE uses. PBS wants
``PBSAPIToken=user@realm!name:secret`` with a colon before the secret, VE
wants ``PVEAPIToken=...=secret`` with an equals sign. Mixing them up gives a
401 that says nothing.

The token needs DatastoreAudit on /datastore, or the usage answer arrives
with the names and no numbers, and Sys.Audit on /system, or the task list
comes back empty because the token owns no tasks of its own.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    measured,
    percent,
    percent_text,
    status_from_percent,
    worst,
)


class PbsAdapter(Adapter):
    kind = "pbs"
    label = "Proxmox Backup Server"
    category = "nas"
    description = "Datastores with their free space, the host, and how the last jobs ended."
    icon = "proxmox-backup-server"
    docs_url = "https://pbs.proxmox.com/docs/api-viewer/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="https://pbs.example.com:8007"),
        Field("token_id", "Token ID", required=True, placeholder="monitor@pbs!nexdeck", help="user@realm!name, from Access Control > API Token."),
        Field("secret", "Token secret", type="password", secret=True, required=True),
        Field("node", "Node", default="localhost", help="The name of the node; localhost works on a single server."),
        Field("insecure", "Ignore TLS errors", type="bool", default=True, help="On by default: PBS answers with its own certificate."),
    )
    widgets = (
        WidgetType(
            kind="datastores",
            label="Datastores",
            description="One line per datastore with how full it is.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("fullest", "datastores"),
        ),
        WidgetType(
            kind="system",
            label="Host",
            description="CPU, memory, root file system and uptime of the backup server.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=60,
            metrics=("cpu", "memory"),
        ),
        WidgetType(
            kind="tasks",
            label="Tasks",
            description="The last jobs and how they ended.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("failed",),
            options=(Field("limit", "Entries", type="number", default=8), Field("only_errors", "Only failures", type="bool", default=False)),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 60) -> Any:
        payload = await ctx.get_json(
            f"{base_url(config)}/api2/json{path}",
            headers={"Authorization": f"PBSAPIToken={config.get('token_id') or ''}:{config.get('secret') or ''}"},
            params=params,
            verify=not config.get("insecure", True),
            cache_seconds=cache,
        )
        return (payload or {}).get("data")

    def _node(self, config: dict[str, Any]) -> str:
        return str(config.get("node") or "localhost").strip() or "localhost"

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        stores = await self._get(config, ctx, "/status/datastore-usage", cache=0)
        return f"Proxmox Backup Server answers with {len(stores) if isinstance(stores, list) else 0} datastores."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "system":
            status = await self._get(config, ctx, f"/nodes/{self._node(config)}/status", cache=60) or {}
            memory = status.get("memory") or {}
            root = status.get("root") or {}
            cpu = round(float(status.get("cpu") or 0) * 100, 1)
            memory_share = percent(memory.get("used"), memory.get("total"))
            root_share = percent(root.get("used"), root.get("total"))
            return WidgetData(
                status=status_from_percent(worst(cpu, memory_share, root_share)),
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[
                    {"label": "Memory", "value": memory_share, "unit": "%"},
                    {"label": "Root", "value": root_share, "unit": "%"},
                    {"label": "Uptime", "value": duration_short(float(status.get("uptime") or 0))},
                ],
                metrics=measured({"cpu": cpu, "memory": memory_share}),
            )

        if widget_kind == "tasks":
            limit = int(options.get("limit") or 8)
            params: dict[str, Any] = {"limit": limit, "start": 0}
            if options.get("only_errors"):
                params["errors"] = 1
            rows = await self._get(config, ctx, f"/nodes/{self._node(config)}/tasks", params, cache=300) or []
            items = []
            failed = 0
            for entry in rows if isinstance(rows, list) else []:
                ended = entry.get("status")
                running = not entry.get("endtime")
                good = str(ended or "") == "OK"
                if ended and not good:
                    failed += 1
                items.append({
                    "title": str(entry.get("worker_id") or entry.get("worker_type") or "?"),
                    # PBS says "OK" or the error itself; both belong on the card.
                    "subtitle": str(entry.get("worker_type") or ""),
                    "value": "" if running else ("" if good else str(ended)[:40]),
                    "status": "unknown" if running else ("ok" if good else "bad"),
                })
            return WidgetData(
                status="bad" if failed else "ok",
                items=items,
                secondary=[{"label": "Failed jobs", "value": failed}, {"label": "Tasks", "value": len(items)}],
                metrics={"failed": float(failed)},
                meta={"empty": "No task."},
            )

        stores = await self._get(config, ctx, "/status/datastore-usage", cache=300) or []
        items = []
        fullest: float | None = None
        for store in stores if isinstance(stores, list) else []:
            total = store.get("total")
            used = store.get("used")
            share = percent(used, total)
            if share is None:
                # No Datastore.Audit on this store: the name comes, the numbers do not.
                items.append({"title": str(store.get("store") or "?"), "subtitle": str(store.get("error") or ""), "status": "unknown"})
                continue
            fullest = worst(fullest, share)
            items.append({
                "title": str(store.get("store") or "?"),
                "subtitle": f"{human_bytes(used)} / {human_bytes(total)}",
                "progress": share,
                "value": percent_text(share, 1),
                "status": status_from_percent(share),
            })
        items.sort(key=lambda item: -float(item.get("progress") or 0))
        return WidgetData(
            status=status_from_percent(fullest),
            items=items,
            secondary=[{"label": "Datastores", "value": len(items)}, {"label": "Fullest", "value": percent_text(fullest, 1)}],
            metrics=measured({"fullest": fullest, "datastores": float(len(items))}),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "system":
            cpu = fake.walk("pbs-cpu", tick, 2, 34)
            memory_share = fake.walk("pbs-mem", tick, 28, 61)
            return WidgetData(
                status=status_from_percent(worst(cpu, memory_share)),
                primary={"label": "CPU", "value": cpu, "unit": "%"},
                secondary=[
                    {"label": "Memory", "value": memory_share, "unit": "%"},
                    {"label": "Root", "value": 41.0, "unit": "%"},
                    {"label": "Uptime", "value": "34d 2h"},
                ],
                metrics={"cpu": cpu, "memory": memory_share},
            )

        if widget_kind == "tasks":
            broken = fake.flicker("pbs-task", tick, 0.2)
            rows = [
                ("vm/104", "backup", "OK"),
                ("store-main", "garbage_collection", "OK"),
                ("vm/117", "backup", "connection error" if broken else "OK"),
                ("store-main", "verify", "OK"),
            ]
            if options.get("only_errors"):
                rows = [row for row in rows if row[2] != "OK"] or [("vm/117", "backup", "connection error")]
            items = [
                {
                    "title": what,
                    "subtitle": kind,
                    "value": "" if ended == "OK" else ended,
                    "status": "ok" if ended == "OK" else "bad",
                }
                for what, kind, ended in rows[: int(options.get("limit") or 8)]
            ]
            failed = sum(1 for item in items if item["status"] == "bad")
            return WidgetData(
                status="bad" if failed else "ok",
                items=items,
                secondary=[{"label": "Failed jobs", "value": failed}, {"label": "Tasks", "value": len(items)}],
                metrics={"failed": float(failed)},
                meta={"empty": "No task."},
            )

        stores = [
            ("main", 18_800_000_000_000, 24_000_000_000_000),
            ("offsite", 6_100_000_000_000, 12_000_000_000_000),
        ]
        items = []
        fullest: float | None = None
        for name, used, total in stores:
            share = percent(used + fake.counter(name, tick, 0, 2e8), total)
            fullest = worst(fullest, share)
            items.append({
                "title": name,
                "subtitle": f"{human_bytes(used)} / {human_bytes(total)}",
                "progress": share,
                "value": percent_text(share, 1),
                "status": status_from_percent(share),
            })
        items.sort(key=lambda item: -float(item.get("progress") or 0))
        return WidgetData(
            status=status_from_percent(fullest),
            items=items,
            secondary=[{"label": "Datastores", "value": len(items)}, {"label": "Fullest", "value": percent_text(fullest, 1)}],
            metrics=measured({"fullest": fullest, "datastores": float(len(items))}),
        )


ADAPTER = PbsAdapter()
