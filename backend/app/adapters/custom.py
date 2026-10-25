"""Cards the administrator describes as data: one adapter, four forms.

A custom card is a definition (``cards/schema.py``) saved in the database. The widget carries the short name of the
definition in its ``card`` option and sits on a connection of one of the kinds the definition names. ``fetch`` asks that
connection the definition's requests, through the guard rails of ``cards/source.py`` and with the connection's own
credentials, lets the pipeline pick and calculate, and hands the finished values to the renderers every other card
uses. The texts stay the author's own (``meta.custom``): nexdeck's table of translations is never applied to them.
"""

from __future__ import annotations

import math
from typing import Any

from ..cards import images, pipeline, source, store
from ..db import db_session
from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType

#: A custom card asks its connection at most this often (KARTEN-2 AC-9).
MIN_REFRESH_SECONDS = 10
#: The metrics a card of several numbers records, one per place.
STAT_METRICS = tuple(f"stat{number}" for number in range(1, 7))

CARD = Field(
    "card",
    "Card",
    required=True,
    placeholder="queue-size",
    help="The short name of the card, as saved under System > Cards.",
)


def _kind(kind: str, label: str, description: str, renderer: str, **more: Any) -> WidgetType:
    return WidgetType(kind=kind, label=label, description=description, renderer=renderer, options=(CARD,), refresh_seconds=30, **more)


def definition_of(options: dict[str, Any]) -> Any:
    """The saved definition a widget points at, or the error the card shows (KARTEN-1 EC)."""
    slug = str(options.get("card") or "").strip()
    with db_session() as db:
        entry = store.get(db, slug) if slug else None
    if entry is None:
        raise AdapterError(
            "Definition missing. The card is no longer saved.",
            code="definition_missing",
            hint="The card was deleted or renamed. Pick another one in the card's settings.",
        )
    return entry.definition


def name_of(options: dict[str, Any]) -> str:
    """The name the author gave the card, English first: what a card is called until somebody renames it."""
    try:
        name = definition_of(options).name
    except AdapterError:
        return ""
    return name if isinstance(name, str) else (name.get("en") or next(iter(name.values()), ""))


def sizes_of(options: dict[str, Any], default: tuple[int, int], smallest: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """The size a card is made at and the smallest it may be: what the definition asks for, never below the form's floor (KARTEN-6 AC-10)."""
    try:
        definition = definition_of(options)
    except AdapterError:
        return default, smallest
    minimum = (max(smallest[0], definition.min_size.w), max(smallest[1], definition.min_size.h)) if definition.min_size else smallest
    wanted = (definition.size.w, definition.size.h) if definition.size else default
    return (max(wanted[0], minimum[0]), max(wanted[1], minimum[1])), minimum


def _number(shown: pipeline.Shown) -> float | int | None:
    """The value as a number to draw, rounded the way the author asked; ``None`` for a word, a date or nothing."""
    value = shown.value
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    rounded = round(value, shown.digits if shown.digits is not None else 2)
    return int(rounded) if rounded == int(rounded) and abs(rounded) < 1e15 else rounded


def _cell(shown: pipeline.Shown) -> dict[str, Any]:
    """One finished value in the shape of ``primary`` and of a row of ``secondary``.

    ``text`` is what the server worked out; the browser formats numbers and times itself in the language of whoever
    looks (``formatShown``), and picks the label and the unit out of the languages the author wrote.
    """
    number = _number(shown)
    return {
        "label": shown.label or "",
        "value": number if number is not None else shown.value,
        "unit": "%" if shown.format == "percent" else (shown.unit or ""),
        "format": shown.format,
        "digits": shown.digits,
        "text": shown.text,
    }


def _worst(*levels: str | None) -> str:
    found = [level for level in levels if level in pipeline.RANK]
    return max(found, key=pipeline.RANK.__getitem__) if found else "ok"


def _cells(row: pipeline.Row, order: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """The cells of a row whose text depends on the language of the viewer: numbers, times, and anything with a unit."""
    cells: dict[str, dict[str, Any]] = {}
    for name in order:
        shown = getattr(row, name)
        if shown is not None and shown.value is not None and (shown.format != "text" or shown.unit):
            cells[name] = {"value": shown.value, "text": shown.text, "format": shown.format, "digits": shown.digits, "unit": shown.unit or ""}
    return cells


def _row_item(row: pipeline.Row, base: str, *, pictures: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": row.title.text,
        "subtitle": row.subtitle.text if row.subtitle is not None and row.subtitle.value is not None else "",
        "value": row.value.text if row.value is not None and row.value.value is not None else "",
        "status": row.status or "ok",
    }
    # ⚠️ http and https only. The service's data names the link, and a relative address would lead into nexdeck itself.
    if row.link and row.link.lower().startswith(("http://", "https://")):
        item["url"] = row.link
    if pictures and row.image:
        art = images.reference(row.image, base)
        if art:
            item["art"] = art
    cells = _cells(row, ("title", "subtitle", "value"))
    if cells:
        item["shown"] = cells
    return item


def present(definition: Any, result: pipeline.Result, *, base: str = "", pictures: bool = True) -> WidgetData:
    """What the renderers read, made from the finished values of the pipeline (KARTEN-6)."""
    meta: dict[str, Any] = {"custom": True}
    if definition.form == "value":
        assert result.value is not None
        primary = _cell(result.value)
        metrics = {"value": float(primary["value"])} if isinstance(primary["value"], int | float) and not isinstance(primary["value"], bool) else {}
        return WidgetData(status=_worst(result.value.status, result.status), primary=primary, metrics=metrics, meta=meta)
    if definition.form == "stats":
        cells = [_cell(one) for one in result.stats]
        metrics: dict[str, float] = {}
        for index, cell in enumerate(cells):
            cell["metric"] = STAT_METRICS[index]
            if isinstance(cell["value"], int | float) and not isinstance(cell["value"], bool):
                metrics[STAT_METRICS[index]] = float(cell["value"])
        status = _worst(result.status, *(one.status for one in result.stats))
        return WidgetData(status=status, primary=cells[0] if cells else None, secondary=cells[1:], metrics=metrics, meta=meta)
    meta["empty"] = getattr(definition, "empty", None)
    items = [_row_item(row, base, pictures=pictures) for row in result.rows]
    return WidgetData(status=_worst(result.status), items=items, meta=meta)


class CustomAdapter(Adapter):
    kind = "custom"
    label = "Custom card"
    category = "generic"
    description = "A card described as data: which requests to ask a connection, which values to show, and when to turn yellow or red."
    icon = "lucide:layout-dashboard"
    # Not a connection of its own: the card sits on a connection of another kind, the one its definition names.
    needs_integration = True
    fields = ()
    widgets = (
        _kind("value", "Custom number", "One value from the answers of a connection, with unit, history and colour.", "value",
              default_size=(2, 2), min_size=(1, 1), metrics=("value",)),
        _kind("stats", "Custom numbers", "Two to six values from the answers of a connection, side by side.", "stats",
              default_size=(3, 2), metrics=STAT_METRICS),
        _kind("list", "Custom list", "Rows from a list in the answers of a connection, with title, value, status and link.", "list",
              default_size=(3, 3)),
        _kind("posters", "Custom pictures", "A wall of pictures with titles from a list in the answers of a connection.", "posters",
              default_size=(4, 3), min_size=(2, 2)),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        raise AdapterError("A custom card has no connection of its own.", code="no_connection_of_its_own")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        definition = definition_of(options)
        if ctx.resolve_integration is None or ctx.integration_id is None:
            raise AdapterError("The connection of this card is missing.", code="no_integration", hint="Pick a connection in the card's settings.")
        real, real_config, real_ctx = await ctx.resolve_integration(ctx.integration_id)
        if definition.form != widget_kind:
            raise AdapterError(
                "The card was changed to another form since it was placed.",
                code="form_changed",
                hint="Place the card again from the library.",
            )
        if real.kind not in definition.requires:
            raise AdapterError(
                f"This card does not read through a {real.label} connection.",
                code="kind_mismatch",
                hint="Pick a connection of a kind the card names.",
            )
        answers = {request.id: await source.fetch_source(real, real_config, real_ctx, request) for request in definition.requests}
        return present(definition, pipeline.run(definition, answers), base=real.raw_base(real_config))

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        """The author's own example answers, asking no service (KARTEN-2 AC-13); none, and the card says so (KARTEN-1 AC-11)."""
        definition = definition_of(options)
        answers = pipeline.demo_answers(definition)
        if answers is None:
            raise AdapterError(
                "No demo data. The card has no example answers.",
                code="no_demo_data",
                hint="The author gave the card no example answers, so it shows nothing in demo mode.",
            )
        return present(definition, pipeline.run(definition, answers), pictures=False)


ADAPTER = CustomAdapter()
