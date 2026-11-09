"""Any JSON API as a widget: a URL, a path per value, a unit and thresholds."""

from __future__ import annotations

import re
from typing import Any

from ..cards.formula import Formula, FormulaError, Ref, _scan_reference, compile_formula, evaluate
from ..services.jsonpath import PathError, as_number, extract
from . import demo as fake
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType, base_url


def join_path(base: str, path: str) -> str:
    """The request path, always underneath the base URL.

    ⚠️ A path beginning with ``http`` used to replace the whole address, and
    the bearer token and the extra headers were still sent with it. The path
    is a widget option, so anyone who could edit the card could point it at a
    server of their own and read the token out of their own access log. The
    address belongs to the connection, which only an administrator sets.
    """
    path = (path or "").strip()
    if not path:
        return base
    # A leading "//" would be read as a new host, and "\" as one on Windows.
    path = path.lstrip("/\\")
    if not path:
        return base
    return base.rstrip("/") + "/" + path


#: A long text on the card breaks onto further lines instead of ending in "…" (#63).
WRAP = Field("wrap", "Wrap long text", type="bool", default=False,
             help="Long text breaks onto further lines instead of being cut short.")

#: As many badges as the foot of a card shows.
MAX_BADGES = 4

#: A formula over what the card read, the formulas of custom cards (``cards/formula.py``) with one word more:
#: ``value`` is what the path found, ``{field}`` another field of the same response or entry (#67).
CALCULATE_VALUE = Field("calculate", "Calculate", placeholder="value * 9 / 5 + 32",
                        help="Optional. A formula over the value: value * 9 / 5 + 32 turns °C into °F. "
                             "+ - * /, brackets, round, abs, min and max; {field} reads another field of the response.")
CALCULATE_LIST = Field("calculate", "Calculate", placeholder="value * 9 / 5 + 32",
                       help="Optional. A formula over each entry's value: value / 1024 turns KB into MB. "
                            "+ - * /, brackets, round, abs, min and max; {field} reads another field of the entry.")

#: The reference ``value`` becomes inside a formula; a name no response uses.
_VALUE_REF = "__value__"
_VALUE_WORD = re.compile(r"(?<![A-Za-z0-9_.])value(?![A-Za-z0-9_(])")


def compile_calculation(text: Any) -> Formula | None:
    """The formula of a card's "Calculate", or ``None`` when there is none.

    ⚠️ Never ``eval``: the parser of the custom cards, which knows numbers,
    references, ``+ - * /``, comparisons and four functions and nothing else.
    The word ``value`` outside braces stands for what the path found; inside
    braces a name is a field of the response, so ``{data.value}`` stays one.
    """
    text = str(text or "").strip()
    if not text:
        return None
    try:
        parts, index = [], 0
        while index < len(text):
            brace = text.find("{", index)
            stop = len(text) if brace < 0 else brace
            parts.append(_VALUE_WORD.sub("{" + _VALUE_REF + "}", text[index:stop]))
            if brace < 0:
                break
            end = _scan_reference(text, brace)
            parts.append(text[brace : end + 1])
            index = end + 1
        return compile_formula("".join(parts))
    except FormulaError as error:
        raise AdapterError(f"The formula in Calculate cannot be read: {error.message}", code="formula_error",
                           hint="Write it like value * 9 / 5 + 32.") from error


def calculated(formula: Formula, raw: Any, scope: Any) -> Any:
    """The formula's result for one value: a number, ``True``/``False`` for a comparison, ``None`` when it has none.

    ``value`` is the number the path found (``"21,5"`` counts, as everywhere on these cards); a field in braces is
    looked up in ``scope``, the whole response or the entry of a list.
    """
    number = as_number(raw)

    def resolve(ref: Ref) -> Any:
        if ref.expression == _VALUE_REF:
            return number if number is not None else raw
        return ref.search(scope)

    return evaluate(formula, resolve)


def _tidy(result: Any) -> Any:
    """A result as a list shows it: a whole number without ".0", a fraction to two places, a comparison as a word."""
    if isinstance(result, bool):
        return "true" if result else "false"
    if isinstance(result, float):
        return int(result) if result.is_integer() else round(result, 2)
    return result


def parse_badges(text: str) -> list[tuple[str, str, str, str]]:
    """The badges of a value card: one per line, ``Label | path | unit | formula``.

    A line without a path is left out, and so is everything past the fourth:
    the card draws four and no more (issue #38). The formula is optional (#67).
    """
    badges: list[tuple[str, str, str, str]] = []
    for line in (text or "").splitlines():
        parts = [part.strip() for part in line.split("|", 3)]
        if len(parts) < 2 or not parts[1]:
            continue
        badges.append((parts[0], parts[1], parts[2] if len(parts) > 2 else "", parts[3] if len(parts) > 3 else ""))
    return badges[:MAX_BADGES]


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
        Field("headers", "Extra headers", secret=True, type="textarea", help="One per line, Name: Value. A header value is stored as entered.", placeholder="X-Api-Key: abc"),
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
                CALCULATE_VALUE,
                Field("decimals", "Decimals", type="number", default=1),
                Field("warn_above", "Warn above", type="number"),
                Field("bad_above", "Alarm above", type="number"),
                Field("warn_below", "Warn below", type="number"),
                Field("bad_below", "Alarm below", type="number"),
                Field("badges", "Badges", type="textarea", placeholder="Latest | release.latest\nDew point | dewp | °F | value * 9 / 5 + 32",
                      help="Small values at the foot of the card, one per line: label | value path | unit | formula. Up to four, from the same response; the formula is optional."),
                WRAP,
            ),
        ),
        WidgetType(
            kind="list",
            bars=True,
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
                CALCULATE_LIST,
                Field("limit", "Entries", type="number", default=10),
                WRAP,
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        payload = await self._get(config, "", ctx)
        kind = "list" if isinstance(payload, list) else "object"
        return f"Reachable, the base URL answers with a JSON {kind}."

    #: A custom card reads through a JSON API connection with its token and its extra headers (KARTEN-2 AC-3).

    @staticmethod
    def _headers(config: dict[str, Any]) -> dict[str, str]:
        headers = parse_headers(config.get("headers") or "")
        if config.get("token"):
            headers["Authorization"] = f"Bearer {config['token']}"
        return headers

    async def _get(self, config: dict[str, Any], path: str, ctx: Context) -> Any:
        url = join_path(base_url(config), path)
        return await ctx.get_json(url, headers=self._headers(config), verify=not config.get("insecure"), cache_seconds=5)

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
        formula = compile_calculation(options.get("calculate"))
        if formula is not None:
            # A comparison answers in words; a formula that finds nothing to work with shows "–", not the raw value.
            result = calculated(formula, raw, payload)
            raw = ("true" if result else "false") if isinstance(result, bool) else result
        number = as_number(raw)
        status = "ok"
        metrics: dict[str, float] = {}
        value = shown(raw, options)
        if number is not None:
            metrics["value"] = number
            status = threshold_status(number, options)
        return WidgetData(
            status=status,
            primary={"label": options.get("label") or "", "value": value, "unit": options.get("unit") or ""},
            secondary=badges(payload, options),
            metrics=metrics,
            meta=wrapped(options),
        )

    def _list(self, payload: Any, options: dict[str, Any]) -> WidgetData:
        rows = extract(payload, str(options.get("items_path") or ""))
        if not isinstance(rows, list):
            raise PathError("The items path does not point at a list.")
        limit = max(1, min(100, int(options.get("limit") or 10)))
        formula = compile_calculation(options.get("calculate"))
        items = []
        for row in rows[:limit]:
            item = {"title": str(_safe(row, options.get("title_path")))}
            if options.get("subtitle_path"):
                item["subtitle"] = str(_safe(row, options["subtitle_path"]))
            if options.get("value_path"):
                item["value"] = _safe(row, options["value_path"])
            if formula is not None:
                item["value"] = _tidy(calculated(formula, item.get("value"), row))
            items.append(item)
        return WidgetData(items=items, secondary=[{"label": "Total", "value": len(rows)}], meta=wrapped(options))

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "value":
            number = fake.walk("jsonapi", tick, 18, 31)
            # The preview shows what the formula makes of it, so °F reads as °F before the API is asked.
            formula = compile_calculation(options.get("calculate"))
            result = calculated(formula, number, {}) if formula is not None else number
            number = round(result, 1) if isinstance(result, float) else number
            return WidgetData(
                status=threshold_status(number, options),
                primary={"label": options.get("label") or "Server room", "value": number, "unit": options.get("unit") or "°C"},
                metrics={"value": number},
                meta=wrapped(options),
            )
        return WidgetData(meta=wrapped(options), items=[
            {"title": "backup-nightly", "subtitle": "finished 02:14", "value": "ok"},
            {"title": "certificates", "subtitle": "renewed 12 days ago", "value": 4},
            {"title": "snapshots", "subtitle": "last 03:00", "value": 17},
        ], secondary=[{"label": "Total", "value": 3}])


def wrapped(options: dict[str, Any]) -> dict[str, Any]:
    """Tells the card to break long text onto further lines, when the card asks for it (#63)."""
    return {"wrap": True} if options.get("wrap") else {}


def shown(raw: Any, options: dict[str, Any]) -> Any:
    """A value from the response as the card shows it: rounded, or cut short."""
    number = as_number(raw)
    if number is not None:
        decimals = int(options.get("decimals") or 0)
        return round(number, decimals) if decimals else int(round(number))
    if isinstance(raw, (dict, list)):
        return str(raw)[:60]
    return raw


def badges(payload: Any, options: dict[str, Any]) -> list[dict[str, Any]]:
    """The badges asked for in the card's settings, read from the same response.

    ⚠️ A badge whose path finds nothing shows an empty value and leaves the
    card standing. The main value is what the card is for; a release channel
    the service stopped sending must not turn the whole card into an error.

    ⚠️ Only a number the response sends as a number is rounded. Text stays as
    it came: the latest version "1.5" is not a reading, and with no decimals
    set it would have been shown as 2.
    """
    rows = []
    for label, path, unit, text in parse_badges(str(options.get("badges") or "")):
        try:
            raw = extract(payload, path)
        except PathError:
            raw = None
        formula = compile_calculation(text)
        if formula is not None:
            raw = calculated(formula, raw, payload)
        value: Any = raw
        if isinstance(raw, bool):
            value = "true" if raw else "false"
        elif isinstance(raw, (int, float)) or isinstance(raw, (dict, list)):
            value = shown(raw, options)
        rows.append({"label": label, "value": value, "unit": unit})
    return rows


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
