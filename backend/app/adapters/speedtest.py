"""Speedtest Tracker: the latest measurement and its history."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


def _mbps(value: Any) -> float:
    """Speedtest Tracker reports bytes per second in ``download``; some versions Mbps in ``download_bits``."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(number / 125000, 1) if number > 100000 else round(number, 1)


class SpeedtestAdapter(Adapter):
    kind = "speedtest"
    label = "Speedtest Tracker"
    category = "network"
    description = "Latest download, upload and ping, with a sparkline of the day."
    icon = "speedtest-tracker"
    docs_url = "https://docs.speedtest-tracker.dev/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://speedtest:8080"),
        Field("api_key", "API token", type="password", secret=True, required=True, help="Settings > API Tokens"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="latest", label="Latest result", description="Download, upload and ping of the newest test.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=300, metrics=("download", "upload", "ping")),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}", "Accept": "application/json"}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await ctx.get_json(f"{base_url(config)}/api/v1/results/latest", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=0)
        data = payload.get("data") or payload
        return f"Speedtest Tracker answers, latest test from {str(data.get('created_at', '?'))[:16]}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        payload = await ctx.get_json(f"{base_url(config)}/api/v1/results/latest", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=60)
        data = payload.get("data") or payload
        if not isinstance(data, dict):
            raise AdapterError("Speedtest Tracker returned no result yet.", code="no_result")
        download = _mbps(data.get("download_bits") or data.get("download"))
        upload = _mbps(data.get("upload_bits") or data.get("upload"))
        ping = round(float(data.get("ping") or 0), 1)
        ok = data.get("status", "completed") == "completed" and data.get("successful", True)
        return WidgetData(
            status="ok" if ok else "warn",
            primary={"label": "Download", "value": download, "unit": "Mbps"},
            secondary=[{"label": "Upload", "value": upload, "unit": "Mbps"}, {"label": "Ping", "value": ping, "unit": "ms"}, {"label": "Tested", "value": str(data.get("created_at", ""))[:16].replace("T", " ")}],
            metrics={"download": download, "upload": upload, "ping": ping},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        download = fake.walk("st-down", tick, 880, 960, period=1200)
        upload = fake.walk("st-up", tick, 44, 51, period=1200)
        ping = fake.walk("st-ping", tick, 7, 12, period=600)
        return WidgetData(primary={"label": "Download", "value": download, "unit": "Mbps"},
                          secondary=[{"label": "Upload", "value": upload, "unit": "Mbps"}, {"label": "Ping", "value": ping, "unit": "ms"}, {"label": "Tested", "value": "today 06:00"}],
                          metrics={"download": download, "upload": upload, "ping": ping})


ADAPTER = SpeedtestAdapter()
