"""Any JSON API as a widget: a URL, a path per value, a unit and thresholds."""

from __future__ import annotations

from typing import Any

from ..services.jsonpath import PathError, as_number, extract
from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


def parse_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip()] = value.strip()
    return headers


class JsonApiAdapter(Adapter):
    kind = "jsonapi"
    label = "JSON API"
    category = "generic"
    description = "Reads values from any HTTP API that answers with JSON."
    icon = "json"
    beta = False
    fields = (
        Field("url", "Base URL", type="url", required=True, placeholder="https://service.example.com/api"),
        Field("token", "Bearer token", type="password", secret=True, help="Sent as Authorization: Bearer. Leave empty if not needed."),
        Field("headers", "Extra headers", type="textarea", help="One per line, Name: Value. A header value is stored as entered.", placeholder="X-Api-Key: abc"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="value",
            label="Value",
            description="One number or text from the response, with unit and thresholds.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            metrics=("value",),
            options=(
                Field("path", "Request path", placeholder="/status", help="Appended to the base URL. Empty means the base URL itself."),
                Field("value_path", "Value path", required=True, placeholder="data.temperature", help="Dots for fields, [0] for list elements."),
                Field("label", "Label", placeholder="Temperature"),
                Field("unit", "Unit", placeholder="°C"),
                Field("decimals", "Decimals", type="number", default=1),
                Field("warn_above", "Warn above", type="number"),
                Field("bad_above", "Alarm above", type="number"),
                Field("warn_below", "Warn below", type="number"),
                Field("bad_below", "Alarm below", type="number"),
            ),
        ),
        WidgetType(
            kind="list",
            label="List",
            description="A list from an array in the response.",
            renderer="list",
            default_size=(3, 3),
            options=(
                Field("path", "Request path", placeholder="/items"),
                Field("items_path", "Items path", required=True, placeholder="data.items", help="Path to the array."),
                Field("title_path", "Title field", required=True, placeholder="name"),
                Field("subtitle_path", "Subtitle field", placeholder="description"),
                Field("value_path", "Value field", placeholder="count"),
                Field("limit", "Entries", type="number", default=10),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await self._get(config, "", ctx)
        kind = "list" if isinstance(payload, list) else "object"
        return f"Reachable, the base URL answers with a JSON {kind}."

    async def _get(self, config: dict[str, Any], path: str, ctx: Context) -> Any:
        url = base_url(config)
        if path:
            url = url + ("" if path.startswith("/") else "/") + path if not path.startswith("http") else path
        headers = parse_headers(config.get("headers") or "")
        if config.get("token"):
            headers["Authorization"] = f"Bearer {config['token']}"
        return await ctx.get_json(url, headers=headers, verify=not config.get("insecure"), cache_seconds=5)

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        payload = await self._get(config, str(options.get("path") or ""), ctx)
        try:
            if widget_kind == "value":
                return self._value(payload, options)
            return self._list(payload, options)
        except PathError as error:
            raise AdapterError(str(error), code="path_error", hint="Check the path in the widget settings.") from error

    def _value(self, payload: Any, options: dict[str, Any]) -> WidgetData:
        raw = extract(payload, str(options.get("value_path") or ""))
        number = as_number(raw)
        status = "ok"
        metrics: dict[str, float] = {}
        value: Any = raw
        if number is not None:
            decimals = int(options.get("decimals") or 0)
            value = round(number, decimals) if decimals else int(round(number))
            metrics["value"] = number
            status = threshold_status(number, options)
        elif isinstance(raw, (dict, list)):
            value = str(raw)[:60]
        return WidgetData(
            status=status,
            primary={"label": options.get("label") or "", "value": value, "unit": options.get("unit") or ""},
            metrics=metrics,
        )

    def _list(self, payload: Any, options: dict[str, Any]) -> WidgetData:
        rows = extract(payload, str(options.get("items_path") or ""))
        if not isinstance(rows, list):
            raise PathError("The items path does not point at a list.")
        limit = max(1, min(100, int(options.get("limit") or 10)))
        items = []
        for row in rows[:limit]:
            item = {"title": str(_safe(row, options.get("title_path")))}
            if options.get("subtitle_path"):
                item["subtitle"] = str(_safe(row, options["subtitle_path"]))
            if options.get("value_path"):
                item["value"] = _safe(row, options["value_path"])
            items.append(item)
        return WidgetData(items=items, secondary=[{"label": "Total", "value": len(rows)}])

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "value":
            number = fake.walk("jsonapi", tick, 18, 31)
            return WidgetData(
                status=threshold_status(number, options),
                primary={"label": options.get("label") or "Server room", "value": number, "unit": options.get("unit") or "°C"},
                metrics={"value": number},
            )
        return WidgetData(items=[
            {"title": "backup-nightly", "subtitle": "finished 02:14", "value": "ok"},
            {"title": "certificates", "subtitle": "renewed 12 days ago", "value": 4},
            {"title": "snapshots", "subtitle": "last 03:00", "value": 17},
        ], secondary=[{"label": "Total", "value": 3}])


def _safe(row: Any, path: Any) -> Any:
    try:
        return extract(row, str(path or ""))
    except PathError:
        return ""


def threshold_status(number: float, options: dict[str, Any]) -> str:
    def limit(name: str) -> float | None:
        value = options.get(name)
        return None if value in (None, "") else float(value)

    bad_above, warn_above = limit("bad_above"), limit("warn_above")
    bad_below, warn_below = limit("bad_below"), limit("warn_below")
    if bad_above is not None and number > bad_above:
        return "bad"
    if bad_below is not None and number < bad_below:
        return "bad"
    if warn_above is not None and number > warn_above:
        return "warn"
    if warn_below is not None and number < warn_below:
        return "warn"
    return "ok"


ADAPTER = JsonApiAdapter()
