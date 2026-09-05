"""Scrutiny: the state of every single disk.

nexdeck reads pools, volumes and arrays, but never the disk underneath. The
S.M.A.R.T. values are the only numbers in a homelab that announce a failure
before it happens, which makes this the one widget worth a red dot.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, base_url, human_bytes

#: Scrutiny's own verdict per device: 0 passed, 1 failed by S.M.A.R.T., 2 failed by Scrutiny's rules.
VERDICT = {0: "ok", 1: "bad", 2: "warn"}
#: Above this a disk is warm enough to say so.
WARM_CELSIUS = 45
HOT_CELSIUS = 55


class ScrutinyAdapter(Adapter):
    kind = "scrutiny"
    label = "Scrutiny"
    category = "monitoring"
    description = "S.M.A.R.T. state, temperature and hours of every disk."
    icon = "scrutiny"
    docs_url = "https://github.com/AnalogJ/scrutiny"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://scrutiny:8080"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="disks",
            label="Disks",
            description="One line per disk with temperature and verdict, the bad ones first.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("failing", "hottest"),
            options=(Field("limit", "Entries", type="number", default=10),),
        ),
        WidgetType(
            kind="summary",
            label="Disk health",
            description="How many disks are fine, how many are not, and how warm the warmest is.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("failing", "hottest"),
        ),
    )

    async def _summary(self, config: dict[str, Any], ctx: Context, cache: float = 120) -> dict[str, Any]:
        payload = await ctx.get_json(
            f"{base_url(config)}/api/summary",
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )
        data = (payload or {}).get("data") or {}
        return data.get("summary") or {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        summary = await self._summary(config, ctx, cache=0)
        return f"Scrutiny answers with {len(summary)} disks."

    def _rows(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for entry in summary.values():
            device = entry.get("device") or {}
            smart = entry.get("smart") or {}
            temperature = smart.get("temp")
            status = VERDICT.get(int(device.get("device_status") or 0), "warn")
            if status == "ok" and isinstance(temperature, int | float) and temperature >= HOT_CELSIUS:
                status = "warn"
            name = device.get("device_name") or device.get("serial_number") or "?"
            model = device.get("model_name") or ""
            hours = smart.get("power_on_hours")
            rows.append({
                "title": f"{name} {model}".strip(),
                "subtitle": f"{human_bytes(device.get('capacity'))} · {int(hours) // 24 if hours else '?'} d",
                "value": f"{int(temperature)} °C" if isinstance(temperature, int | float) else "?",
                "status": status,
                "temperature": float(temperature) if isinstance(temperature, int | float) else 0.0,
            })
        rows.sort(key=lambda row: (0 if row["status"] == "bad" else (1 if row["status"] == "warn" else 2), -row["temperature"]))
        return rows

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        summary = await self._summary(config, ctx)
        rows = self._rows(summary)
        failing = sum(1 for row in rows if row["status"] == "bad")
        warm = sum(1 for row in rows if row["status"] == "warn")
        hottest = max((row["temperature"] for row in rows), default=0.0)
        status = "bad" if failing else ("warn" if warm else "ok")

        if widget_kind == "summary":
            return WidgetData(
                status=status,
                primary={"label": "Disks", "value": len(rows)},
                secondary=[
                    {"label": "Failing", "value": failing},
                    {"label": "Warm", "value": warm},
                    {"label": "Hottest", "value": f"{int(hottest)} °C" if hottest else "?"},
                ],
                metrics={"failing": float(failing), "hottest": hottest},
            )

        limit = int(options.get("limit") or 10)
        return WidgetData(
            status=status,
            items=[{key: value for key, value in row.items() if key != "temperature"} for row in rows[:limit]],
            secondary=[{"label": "Disks", "value": len(rows)}, {"label": "Failing", "value": failing}],
            metrics={"failing": float(failing), "hottest": hottest},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        failing = 1 if fake.flicker("scrutiny-fail", tick, 0.1) else 0
        disks = [
            ("sda", "Example SSD 1TB", 1.0e12, 12800, fake.walk("scrutiny-t1", tick, 31, 39)),
            ("sdb", "Example HDD 8TB", 8.0e12, 34100, fake.walk("scrutiny-t2", tick, 38, 47)),
            ("sdc", "Example HDD 8TB", 8.0e12, 33900, fake.walk("scrutiny-t3", tick, 40, 52)),
            ("nvme0", "Example NVMe 2TB", 2.0e12, 9400, fake.walk("scrutiny-t4", tick, 33, 44)),
        ]
        rows = []
        for index, (name, model, capacity, hours, temperature) in enumerate(disks):
            status = "bad" if failing and index == 2 else ("warn" if temperature >= WARM_CELSIUS else "ok")
            rows.append({
                "title": f"{name} {model}",
                "subtitle": f"{human_bytes(capacity)} · {hours // 24} d",
                "value": f"{int(temperature)} °C",
                "status": status,
                "temperature": temperature,
            })
        rows.sort(key=lambda row: (0 if row["status"] == "bad" else (1 if row["status"] == "warn" else 2), -row["temperature"]))
        warm = sum(1 for row in rows if row["status"] == "warn")
        hottest = max(row["temperature"] for row in rows)
        status = "bad" if failing else ("warn" if warm else "ok")
        if widget_kind == "summary":
            return WidgetData(
                status=status,
                primary={"label": "Disks", "value": len(rows)},
                secondary=[
                    {"label": "Failing", "value": failing},
                    {"label": "Warm", "value": warm},
                    {"label": "Hottest", "value": f"{int(hottest)} °C"},
                ],
                metrics={"failing": float(failing), "hottest": hottest},
            )
        return WidgetData(
            status=status,
            items=[{key: value for key, value in row.items() if key != "temperature"} for row in rows],
            secondary=[{"label": "Disks", "value": len(rows)}, {"label": "Failing", "value": failing}],
            metrics={"failing": float(failing), "hottest": hottest},
        )


ADAPTER = ScrutinyAdapter()
