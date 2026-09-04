"""Prometheus: one PromQL query as a value with history, or as a list."""

from __future__ import annotations

from typing import Any

from ..services.jsonpath import as_number
from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url
from .jsonapi import threshold_status


class PrometheusAdapter(Adapter):
    kind = "prometheus"
    label = "Prometheus"
    category = "monitoring"
    description = "Any PromQL query as a number with a sparkline, or as a list of series."
    icon = "prometheus"
    docs_url = "https://prometheus.io/docs/prometheus/latest/querying/api/"
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
    )

    async def _query(self, config: dict[str, Any], ctx: Context, query: str) -> list[dict[str, Any]]:
        auth = (str(config["username"]), str(config.get("password") or "")) if config.get("username") else None
        payload = await ctx.get_json(f"{base_url(config)}/api/v1/query", params={"query": query}, auth=auth, verify=not config.get("insecure"), cache_seconds=5)
        if payload.get("status") != "success":
            raise AdapterError(str(payload.get("error") or "Prometheus rejected the query."), code="query_error")
        return (payload.get("data") or {}).get("result") or []

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        result = await self._query(config, ctx, "up")
        return f"Prometheus answers, {len(result)} targets in `up`."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        query = str(options.get("query") or "").strip()
        if not query:
            raise AdapterError("No query is set.", code="missing_query")
        result = await self._query(config, ctx, query)
        decimals = int(options.get("decimals") or 0)
        if widget_kind == "query":
            if not result:
                raise AdapterError("The query returned no series.", code="empty_result", hint="Try it in the Prometheus UI first.")
            number = as_number((result[0].get("value") or [None, None])[1])
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
            number = as_number((series.get("value") or [None, None])[1])
            items.append({"title": metric.get(name) or metric.get("__name__") or "?", "subtitle": ", ".join(f"{k}={v}" for k, v in metric.items() if k not in (name, "__name__"))[:80],
                          "value": f"{round(number, decimals) if number is not None else '?'} {options.get('unit') or ''}".strip()})
        return WidgetData(items=items)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "series":
            return WidgetData(items=[{"title": f"node{i}:9100", "subtitle": "job=node", "value": f"{fake.walk(f'p{i}', tick, 3, 60):.1f} %"} for i in range(1, 5)])
        value = fake.walk("prom", tick, 12, 48)
        return WidgetData(status=threshold_status(value, options), primary={"label": options.get("label") or "CPU", "value": value, "unit": options.get("unit") or "%"}, metrics={"value": value})


ADAPTER = PrometheusAdapter()
