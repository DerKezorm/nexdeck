"""Speedtest Tracker: the latest measurement and its history."""

from __future__ import annotations

import time
from datetime import UTC, datetime
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
    timeline,
)


def _when(row: dict[str, Any]) -> float | None:
    """When a measurement was taken, as seconds since the epoch.

    ⚠️ The tracker writes "2026-09-08 19:05:51" without a zone. It is UTC, and
    reading it as local time would move every point by the offset and put
    tonight's measurements in the future.
    """
    text = str(row.get("created_at") or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=moment.tzinfo or UTC).timestamp()


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
    #: Confirmed against a live Speedtest Tracker on 2026-09-08: the
    #: connection test, the latest result and the history card. ⚠️ Only two
    #: measurements were in it, so the history was proved to page and to
    #: find the newest end, not to look right over a long period.
    beta = False
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
        WidgetType(
            kind="history", label="History",
            description="Download and upload over a period, as a line or as bars.",
            renderer="timeline", default_size=(4, 3), min_size=(3, 2), refresh_seconds=900,
            options=(
                Field("days", "Period", type="select", default="7",
                      options=(("1", "24 hours"), ("7", "7 days"), ("30", "30 days"), ("90", "90 days"))),
                Field("shape", "Shape", type="select", default="line",
                      options=(("line", "A line"), ("bars", "Bars"))),
                Field("show", "Show", type="select", default="both",
                      options=(("both", "Download and upload"), ("download", "Download only"), ("upload", "Upload only"))),
            ),
        ),
    )

    #: What one page of the result list holds. ⚠️ Measured on 08.09.2026:
    #: ``per_page`` is ignored, 5 and 500 both answer with 25. A card that
    #: asked once and drew what came back would quietly show the last 25
    #: measurements and call them 30 days.
    PAGE = 25
    #: How many pages one card may ask for. 90 days at a test every six hours
    #: is 360 points, and nobody reads more than that on a card this size.
    MAX_PAGES = 15

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
        if widget_kind == "history":
            return await self._history(config, options, ctx)
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

    async def _history(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """Download and upload over a period, from the tracker's own records.

        ⚠️ Paged, because the tracker ignores ``per_page``: asking for 500
        answers with 25 either way, so a card that read one page would show the
        last 25 measurements and label them 90 days. It walks pages until the
        entries are older than the period or the last page is reached.
        """
        days = max(1, int(options.get("days") or 7))
        cutoff = time.time() - days * 86400

        async def page_of(number: int) -> tuple[list[dict[str, Any]], int]:
            payload = await ctx.get_json(
                f"{base_url(config)}/api/v1/results", params={"page": number},
                headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=300,
            )
            here = [one for one in (payload.get("data") or []) if isinstance(one, dict)]
            return here, int((payload.get("meta") or {}).get("last_page") or number)

        first_page, last_page = await page_of(1)
        rows = list(first_page)
        if last_page > 1:
            # ⚠️ Which end the newest measurements are on is not documented and
            # could not be measured: the tracker this was written against holds
            # two results on one page. So it is asked rather than assumed. The
            # answer decides which way to walk, and walking the wrong way would
            # draw the oldest 375 measurements and call them "the last 7 days".
            far_page, _ = await page_of(last_page)
            rows += far_page
            newest_here = max((at for one in first_page if (at := _when(one))), default=0.0)
            newest_there = max((at for one in far_page if (at := _when(one))), default=0.0)
            descending = newest_here >= newest_there
            walk = range(2, last_page) if descending else range(last_page - 1, 1, -1)
            for taken, number in enumerate(walk):
                if taken >= self.MAX_PAGES - 2:
                    break
                here, _ = await page_of(number)
                rows += here
                oldest = min((at for one in here if (at := _when(one))), default=None)
                if oldest is not None and oldest < cutoff:
                    break

        wanted = str(options.get("show") or "both")
        inside = sorted(
            ((at, one) for one in rows if (at := _when(one)) and at >= cutoff),
            key=lambda pair: pair[0],
        )
        if not inside:
            return WidgetData(status="unknown", meta={"empty": "No measurement in this period"})

        def series(field: str) -> list[tuple[float, float | None]]:
            # A failed run is a gap, not a nought: a line dipping to the floor
            # would draw an outage that never happened.
            return [(at, _mbps(one, field)) for at, one in inside]

        lines = []
        if wanted in ("both", "download"):
            lines.append(("download", "Download", series("download")))
        if wanted in ("both", "upload"):
            lines.append(("upload", "Upload", series("upload")))

        newest = inside[-1][1]
        down, up = _mbps(newest, "download"), _mbps(newest, "upload")
        return WidgetData(
            primary={"label": "Download", "value": down, "unit": "Mbps"},
            secondary=[
                {"label": "Upload", "value": up, "unit": "Mbps"},
                {"label": "Measurements", "value": len(inside)},
            ],
            metrics=measured({"download": down, "upload": up}),
            meta=timeline(*lines, unit="Mbps", shape=str(options.get("shape") or "line")),
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "history":
            days = max(1, int(options.get("days") or 7))
            # One test every six hours, which is the usual schedule.
            steps = min(360, days * 4)
            now = time.time()
            def made(seed: str, low: float, high: float) -> list[tuple[float, float | None]]:
                points: list[tuple[float, float | None]] = []
                for step in range(steps):
                    at = now - (steps - 1 - step) * 21600
                    # ⚠️ Every twentieth run failed. A demo of a line that never
                    # breaks would not show what a gap looks like, and the gap
                    # is the part that has to be right.
                    value = None if step % 20 == 7 else fake.walk(f"{seed}{step}", tick, low, high, period=900)
                    points.append((at, value))
                return points
            wanted = str(options.get("show") or "both")
            lines = []
            if wanted in ("both", "download"):
                lines.append(("download", "Download", made("st-h-down", 820, 960)))
            if wanted in ("both", "upload"):
                lines.append(("upload", "Upload", made("st-h-up", 41, 52)))
            newest = [value for _at, value in lines[0][2] if value is not None][-1]
            return WidgetData(
                primary={"label": "Download" if wanted != "upload" else "Upload", "value": newest, "unit": "Mbps"},
                secondary=[{"label": "Measurements", "value": steps}],
                metrics={"download": newest},
                meta=timeline(*lines, unit="Mbps", shape=str(options.get("shape") or "line")),
            )
        download = fake.walk("st-down", tick, 880, 960, period=1200)
        upload = fake.walk("st-up", tick, 44, 51, period=1200)
        ping = fake.walk("st-ping", tick, 7, 12, period=600)
        card = WidgetData(primary={"label": "Download", "value": download, "unit": "Mbps"},
                          secondary=[{"label": "Upload", "value": upload, "unit": "Mbps"}, {"label": "Ping", "value": ping, "unit": "ms"}, {"label": "Tested", "value": "today 06:00"}],
                          metrics={"download": download, "upload": upload, "ping": ping})
        return as_gauge(card, options)


ADAPTER = SpeedtestAdapter()
