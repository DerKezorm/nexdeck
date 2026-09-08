"""Speedtest Tracker: the latest measurement and its history."""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    as_gauge,
    base_url,
    gauge_fields,
    measured,
)


def _mbps(data: dict[str, Any], what: str) -> float | None:
    """Megabits per second, read from whichever field the instance sends.

    ⚠️ This used to take one number and guess its unit by its size: above
    100000 it was divided by 125000, below it was passed through. A line that
    genuinely measures under 0.8 Mbit/s therefore came out as "90000 Mbps",
    and the same number meant two different things depending on where the
    needle happened to be.

    The unit follows the field instead. ``download_bits`` is bits per second
    and ``download`` is the bytes per second Ookla itself reports; the API
    documentation names no units, but the field names do, and the response
    carries ``download_bits_human`` beside them. Read the wrong way round a
    number is now wrong everywhere, which is something somebody notices, not
    wrong only at one end of the scale.
    """
    for field, per_mbit in ((f"{what}_bits", 1e6), (what, 125_000.0)):
        value = data.get(field)
        if value is None:
            continue
        try:
            return round(float(value) / per_mbit, 1)
        except (TypeError, ValueError):
            return None
    return None


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
        WidgetType(kind="latest", label="Latest result", description="Download, upload and ping of the newest test.",
                   renderer="value", default_size=(2, 2), refresh_seconds=300, metrics=("download", "upload", "ping"),
                   options=gauge_fields("What your line is supposed to deliver, in Mbps.", "1000")),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}", "Accept": "application/json"}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        """Is the address right and the token good?

        ⚠️ Asked of the list, not of ``results/latest``. A Speedtest Tracker
        that has not measured yet has no latest result and answers 404, and
        nexdeck said "check the URL; the address may point at the wrong
        service" about an address that was right. That is the state of every
        fresh installation, and it sends people looking for a mistake they did
        not make.

        The status code alone answers the question, so the body does not
        matter: 200 means reachable and allowed, 401 means the token, 404
        means the address. An empty list is a fine 200.
        """
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1/results", headers=self._headers(config),
            verify=not config.get("insecure"), cache_seconds=0,
        )
        if response.status_code >= 400:
            raise AdapterError(f"Speedtest Tracker answered with HTTP {response.status_code}.", code="http_error")
        return "Speedtest Tracker answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        payload = await ctx.get_json(f"{base_url(config)}/api/v1/results/latest", headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=60)
        data = payload.get("data") or payload
        if not isinstance(data, dict):
            raise AdapterError("Speedtest Tracker returned no result yet.", code="no_result")
        download = _mbps(data, "download")
        upload = _mbps(data, "upload")
        ping = round(float(data["ping"]), 1) if data.get("ping") is not None else None
        # ⚠️ "successful" is not in the answer at all, so the default carries
        # this line. The field that is there is "healthy", and it is null.
        # Rewriting this to "healthy" without telling "key missing" from "key
        # is null" turns a working card into a permanently yellow one.
        ok = data.get("status", "completed") == "completed" and data.get("successful", True)
        card = WidgetData(
            status="ok" if ok else "warn",
            primary={"label": "Download", "value": download, "unit": "Mbps"},
            secondary=[{"label": "Upload", "value": upload, "unit": "Mbps"}, {"label": "Ping", "value": ping, "unit": "ms"}, {"label": "Tested", "value": str(data.get("created_at", ""))[:16].replace("T", " ")}],
            metrics=measured({"download": download, "upload": upload, "ping": ping}),
        )
        return as_gauge(card, options)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        download = fake.walk("st-down", tick, 880, 960, period=1200)
        upload = fake.walk("st-up", tick, 44, 51, period=1200)
        ping = fake.walk("st-ping", tick, 7, 12, period=600)
        card = WidgetData(primary={"label": "Download", "value": download, "unit": "Mbps"},
                          secondary=[{"label": "Upload", "value": upload, "unit": "Mbps"}, {"label": "Ping", "value": ping, "unit": "ms"}, {"label": "Tested", "value": "today 06:00"}],
                          metrics={"download": download, "upload": upload, "ping": ping})
        return as_gauge(card, options)


ADAPTER = SpeedtestAdapter()
