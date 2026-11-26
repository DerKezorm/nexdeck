"""Prometheus: one PromQL query as a value with history, or as a list, or several queries as curves on one chart."""

from __future__ import annotations

import math
import re
import time
from typing import Any

from ..services.jsonpath import as_number
from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url, timeline
from .jsonapi import threshold_status

#: As many curves as one chart can tell apart: the cards draw six colours, and past that the lines are a tangle.
MAX_LINES = 6
#: The stretches the chart card offers, in seconds. The step is worked out from them so that each curve has about two
#: hundred and forty points, never closer than fifteen seconds, which is the scrape interval Prometheus ships with.
RANGES = {"30m": 1800, "6h": 21600, "24h": 86400}
POINTS = 240
SHORTEST_STEP = 15
#: The colours a curve may be given: the ones a card's own colour offers (``CARD_COLOURS`` in ``services/boards.py``)
#: without the logo's, or one of one's own written as #rrggbb. Anything else draws in the card's next colour.
CURVE_COLOURS = frozenset({"accent", "blue", "violet", "pink", "red", "orange", "yellow", "green"})
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

#: The chart ends at this moment, rounded down to a whole step; the tests set it.
clock = time.time


def split_line(line: str) -> list[str]:
    """One line of the chart card's queries, cut at every ``|`` that is not inside a quoted string.

    ⚠️ Not ``str.split``: PromQL writes alternatives into its regular expressions, ``{mode=~"user|system"}``, and a
    plain split cut such a query in two and drew neither half.
    """
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for char in line:
        if quote:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\" and quote != "`":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
            current.append(char)
        elif char == "|":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return parts


def parse_queries(text: str) -> list[dict[str, str]]:
    """The curves of a chart card: one per line, ``Label | PromQL | colour | unit``.

    A line without a ``|`` is a query on its own. A colour that is neither one of :data:`CURVE_COLOURS` nor #rrggbb is
    dropped, not refused: the curve still draws, in the card's next colour. Empty lines are skipped, and lines past
    :data:`MAX_LINES` are left out.
    """
    queries: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = split_line(line)
        label, query = ("", parts[0]) if len(parts) == 1 else (parts[0], parts[1])
        if not query:
            continue
        colour = parts[2] if len(parts) > 2 else ""
        if colour not in CURVE_COLOURS and not _HEX.match(colour):
            colour = ""
        queries.append({"label": label, "query": query, "colour": colour, "unit": parts[3] if len(parts) > 3 else ""})
    return queries[:MAX_LINES]


def stretch(options: dict[str, Any], now: float) -> tuple[int, int, int]:
    """Start, end and step of the chart in whole seconds, the end rounded down to a step.

    Rounded so that two cards asking within the same step ask the same question, and the curves do not shift by a
    few seconds from one refresh to the next.
    """
    seconds = RANGES.get(str(options.get("range") or "6h"), RANGES["6h"])
    step = max(SHORTEST_STEP, seconds // POINTS)
    end = int(now) // step * step
    return end - seconds, end, step


def reading(value: Any) -> float | None:
    """A sample as Prometheus writes it, a number in a string. NaN and the infinities are no reading."""
    number = as_number(value)
    return number if number is not None and math.isfinite(number) else None


def with_gaps(values: Any, step: int) -> list[tuple[float, float | None]]:
    """The samples of one series, with a gap wherever Prometheus had nothing for a step or more.

    Prometheus leaves a step out when the series had no sample there (a target that was down, a series that began
    later), and a line drawn straight across that would show an outage as a smooth ramp.
    """
    points: list[tuple[float, float | None]] = []
    for pair in values if isinstance(values, list) else []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        at = as_number(pair[0])
        if at is None:
            continue
        if points and at - points[-1][0] > step * 1.5:
            points.append((points[-1][0] + step, None))
        points.append((at, reading(pair[1])))
    return points


def series_names(label: str, query: str, metrics: list[dict[str, Any]]) -> list[str]:
    """What each series of one query is called on the chart.

    One series takes the line's label, else the metric's name, else the query itself. Several are told apart by the
    labels in which they differ (``CPU node1``, ``CPU node2``): the labels they share say nothing about which is which.
    """
    if len(metrics) == 1:
        return [label or str(metrics[0].get("__name__") or "") or query[:60]]
    keys = sorted({key for metric in metrics for key in metric if key != "__name__"})
    differing = [key for key in keys if len({str(metric.get(key, "")) for metric in metrics}) > 1]
    names = []
    for index, metric in enumerate(metrics):
        told = ", ".join(str(metric[key]) for key in differing if metric.get(key)) or str(index + 1)
        names.append(f"{label} {told}".strip())
    return names


class PrometheusAdapter(Adapter):
    kind = "prometheus"
    label = "Prometheus"
    category = "monitoring"
    description = "Any PromQL query as a number with a sparkline, as a list of series, or several queries as curves on one chart."
    icon = "prometheus"
    docs_url = "https://prometheus.io/docs/prometheus/latest/querying/api/"
    #: Seen against a live Prometheus (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://prometheus:9090"),
        Field("username", "User name", help="Only behind basic authentication."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="query",
            label="Query value",
            description="A PromQL query that returns one number, drawn with its sparkline.",
            renderer="chart",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("value",),
            options=(
                Field("query", "PromQL", type="textarea", required=True, placeholder='100 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100'),
                Field("label", "Label", placeholder="CPU"),
                Field("unit", "Unit", placeholder="%"),
                Field("decimals", "Decimals", type="number", default=1),
                Field("warn_above", "Warn above", type="number"),
                Field("bad_above", "Alarm above", type="number"),
            ),
        ),
        WidgetType(
            kind="series",
            label="Query list",
            description="A query with several series, one row per label value.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            options=(
                Field("query", "PromQL", type="textarea", required=True, placeholder="up"),
                Field("label_name", "Label for the row title", default="instance"),
                Field("unit", "Unit"),
                Field("decimals", "Decimals", type="number", default=1),
                Field("limit", "Rows", type="number", default=10),
            ),
        ),
        # Issue #81: several queries as curves over one stretch of time, read from Prometheus' own history, so the
        # chart is full the moment the card appears. The first curve's latest value is the big number above it.
        WidgetType(
            kind="chart",
            label="Several queries",
            description="Up to six PromQL queries as curves on one chart, with Prometheus' own history. The first one's latest value is the big number.",
            renderer="timeline",
            default_size=(4, 3),
            min_size=(3, 2),
            refresh_seconds=60,
            options=(
                Field("queries", "Queries", type="textarea", required=True,
                      placeholder='CPU | 100 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100 | accent | %\n'
                                  "Memory | 100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) | violet | %",
                      help="One curve per line: label | PromQL | colour | unit. Colour and unit may be left out; a colour is "
                           "accent, blue, violet, pink, red, orange, yellow, green or #rrggbb. A query with several series "
                           "draws one curve for each. Six curves at most."),
                Field("range", "Chart shows", type="select", default="6h",
                      options=(("30m", "The last 30 minutes"), ("6h", "The last 6 hours"), ("24h", "The last 24 hours"))),
                Field("decimals", "Decimals", type="number", default=1),
                Field("warn_above", "Warn above", type="number", help="Compared with the first curve's latest value; drawn as a dashed line."),
                Field("bad_above", "Alarm above", type="number", help="Compared with the first curve's latest value; drawn as a dashed line."),
            ),
        ),
    )

    @staticmethod
    def _auth(config: dict[str, Any]) -> tuple[str, str] | None:
        return (str(config["username"]), str(config.get("password") or "")) if config.get("username") else None

    async def _query(self, config: dict[str, Any], ctx: Context, query: str) -> list[dict[str, Any]]:
        payload = await ctx.get_json(f"{base_url(config)}/api/v1/query", params={"query": query}, auth=self._auth(config), verify=not config.get("insecure"), cache_seconds=5)
        if payload.get("status") != "success":
            raise AdapterError(str(payload.get("error") or "Prometheus rejected the query."), code="query_error")
        return (payload.get("data") or {}).get("result") or []

    async def _range(self, config: dict[str, Any], ctx: Context, query: str, start: int, end: int, step: int) -> list[dict[str, Any]]:
        """The series of one query over the chart's stretch.

        ⚠️ Read past an HTTP error. A query Prometheus cannot parse comes back as 400, one that fails while it runs as
        422 and a timeout as 503, each with the reason in the body; ``get_json`` would have said only "HTTP 400".
        """
        response = await ctx.request("GET", f"{base_url(config)}/api/v1/query_range",
                                     params={"query": query, "start": start, "end": end, "step": step},
                                     auth=self._auth(config), verify=not config.get("insecure"), cache_seconds=5)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            if response.status_code >= 400:
                raise AdapterError(f"The service answered with HTTP {response.status_code}.", code="http_error",
                                   hint="Check the URL; the address may point at the wrong service.")
            raise AdapterError("The service did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.")
        if payload.get("status") != "success":
            raise AdapterError(str(payload.get("error") or "Prometheus rejected the query."), code="query_error")
        data = payload.get("data") or {}
        result = data.get("result") or []
        if data.get("resultType") != "matrix" or not isinstance(result, list):
            raise AdapterError("Prometheus did not answer with a series over time.", code="not_a_series")
        return [series for series in result if isinstance(series, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        result = await self._query(config, ctx, "up")
        return f"Prometheus answers, {len(result)} targets in `up`."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "chart":
            return await self._chart(config, options, ctx)
        query = str(options.get("query") or "").strip()
        if not query:
            raise AdapterError("No query is set.", code="missing_query")
        result = await self._query(config, ctx, query)
        decimals = int(options.get("decimals") or 0)
        if widget_kind == "query":
            if not result:
                raise AdapterError("The query returned no series.", code="empty_result", hint="Try it in the Prometheus UI first.")
            number = reading((result[0].get("value") or [None, None])[1])
            if number is None:
                raise AdapterError("The query did not return a number.", code="not_a_number")
            return WidgetData(
                status=threshold_status(number, options),
                primary={"label": options.get("label") or "", "value": round(number, decimals), "unit": options.get("unit") or ""},
                metrics={"value": number},
            )
        name = str(options.get("label_name") or "instance")
        items = []
        for series in result[: int(options.get("limit") or 10)]:
            metric = series.get("metric") or {}
            number = reading((series.get("value") or [None, None])[1])
            items.append({"title": metric.get(name) or metric.get("__name__") or "?", "subtitle": ", ".join(f"{k}={v}" for k, v in metric.items() if k not in (name, "__name__"))[:80],
                          "value": f"{round(number, decimals) if number is not None else '?'} {options.get('unit') or ''}".strip()})
        return WidgetData(items=items)

    async def _chart(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """Every query of the card over the same stretch, one curve per series.

        A query that fails or finds nothing does not take the others down: it is named under the chart with its
        reason, and the card turns yellow. Only when every query fails is the card an error.
        """
        queries = parse_queries(str(options.get("queries") or ""))
        if not queries:
            raise AdapterError("No query is set.", code="missing_query")
        start, end, step = stretch(options, clock())
        lines: list[tuple[str, str, list[tuple[float, float | None]]]] = []
        looks: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        first_error: AdapterError | None = None
        for number, asked in enumerate(queries):
            try:
                result = await self._range(config, ctx, asked["query"], start, end, step)
            except AdapterError as error:
                # Nobody at the address, or the password refused: every other query would fail the same way.
                if error.code in ("unreachable", "auth_failed"):
                    raise
                first_error = first_error or error
                failed.append({"label": asked["label"] or asked["query"][:60], "error": error.message})
                continue
            drawn = [(series.get("metric") or {}, with_gaps(series.get("values"), step)) for series in result]
            drawn = [(metric, points) for metric, points in drawn if any(value is not None for _at, value in points)]
            if not drawn:
                failed.append({"label": asked["label"] or asked["query"][:60], "error": "The query returned no series."})
                continue
            for index, (name, (_metric, points)) in enumerate(zip(series_names(asked["label"], asked["query"], [metric for metric, _ in drawn]), drawn, strict=True)):
                if len(lines) >= MAX_LINES:
                    break
                lines.append((f"q{number}s{index}", name, points))
                # The colour asked for goes to the query's first series; the others take the card's next colours.
                looks.append({"colour": asked["colour"] if index == 0 else "", "unit": asked["unit"]})
        if not lines:
            if first_error is not None:
                raise first_error
            raise AdapterError("The queries returned no series.", code="empty_result", hint="Try them in the Prometheus UI first.")
        meta = timeline(*lines, unit=looks[0]["unit"])
        # Each curve says its unit, even an empty one: the card's unit belongs to the first and is no default for the rest.
        for line, look in zip(meta["lines"], looks, strict=True):
            line["unit"] = look["unit"]
            if look["colour"]:
                line["colour"] = look["colour"]
        meta["marks"] = marks(options)
        if failed:
            meta["failed"] = failed
        latest = next(value for _at, value in reversed(lines[0][2]) if value is not None)
        decimals = int(options.get("decimals") or 0)
        status = threshold_status(latest, options)
        return WidgetData(
            status="warn" if failed and status == "ok" else status,
            primary={"label": lines[0][1], "value": round(latest, decimals), "unit": looks[0]["unit"]},
            meta=meta,
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "series":
            return WidgetData(items=[{"title": f"node{i}:9100", "subtitle": "job=node", "value": f"{fake.walk(f'p{i}', tick, 3, 60):.1f} %"} for i in range(1, 5)])
        if widget_kind == "chart":
            start, end, step = stretch(options, time.time())
            curves = (("CPU", "%", 12, 48), ("Memory", "%", 55, 70), ("Load", "", 0.4, 2.5))
            lines = [
                (f"q{index}s0", label, [(at, fake.walk(f"prom-{label}", at // step, low, high, period=40)) for at in range(start + step, end + 1, step)])
                for index, (label, _unit, low, high) in enumerate(curves)
            ]
            meta = timeline(*lines, unit="%")
            for line, (_label, unit, _low, _high) in zip(meta["lines"], curves, strict=True):
                line["unit"] = unit
            meta["marks"] = marks(options)
            latest = lines[0][2][-1][1] or 0.0
            return WidgetData(status=threshold_status(latest, options), primary={"label": "CPU", "value": round(latest, 1), "unit": "%"}, meta=meta)
        value = fake.walk("prom", tick, 12, 48)
        return WidgetData(status=threshold_status(value, options), primary={"label": options.get("label") or "CPU", "value": value, "unit": options.get("unit") or "%"}, metrics={"value": value})


def marks(options: dict[str, Any]) -> list[dict[str, Any]]:
    """The thresholds of the chart card, drawn on it as dashed lines in the colour they turn the card."""
    drawn = []
    for name, status in (("warn_above", "warn"), ("bad_above", "bad")):
        value = as_number(options.get(name))
        if value is not None and math.isfinite(value):
            drawn.append({"value": value, "status": status})
    return drawn


ADAPTER = PrometheusAdapter()
