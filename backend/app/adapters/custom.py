"""Cards the administrator describes as data: one adapter, five forms.

A custom card is a definition (``cards/schema.py``) saved in the database. The widget carries the short name of the
definition in its ``card`` option and sits on a connection of one of the kinds the definition names. ``fetch`` asks that
connection the definition's requests, through the guard rails of ``cards/source.py`` and with the connection's own
credentials, lets the pipeline pick and calculate, and hands the finished values to the renderers every other card
uses. The texts stay the author's own (``meta.custom``): nexdeck's table of translations is never applied to them.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from ..cards import blocks, buttons, images, pipeline, source, store
from ..db import db_session
from .base import (
    Action,
    Adapter,
    AdapterError,
    Ask,
    AuthFailed,
    Choice,
    Context,
    Field,
    WidgetData,
    WidgetType,
    fill_in,
)

#: A custom card asks its connection at most this often (KARTEN-2 AC-9).
MIN_REFRESH_SECONDS = 10
#: The metrics a card of several numbers records, one per place.
STAT_METRICS = tuple(f"stat{number}" for number in range(1, 7))

CARD = Field(
    "card",
    "Card",
    required=True,
    placeholder="queue-size",
    help="The card this one shows, as saved under System > Custom cards.",
    # The settings sheet shows the name of the card instead of a text field.
    helper="custom-card",
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


def plain(text: Any) -> str:
    """A text of the author as one string, English first, for a place that has no language of its own to pick."""
    if isinstance(text, dict):
        return str(text.get("en") or next(iter(text.values()), ""))
    return "" if text is None else str(text)


def name_of(options: dict[str, Any]) -> str:
    """The name the author gave the card, English first: what a card is called until somebody renames it."""
    try:
        name = definition_of(options).name
    except AdapterError:
        return ""
    return plain(name)


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


def _ask(ask: buttons.ButtonAsk) -> Ask:
    """A blank of a button as the blank of any other action (``base.Ask``), under ``ask.<name>`` so that it never meets a field of the data."""
    return Ask(
        name=buttons.ASK_PREFIX + ask.name,
        label=ask.label,
        kind=ask.type,
        options=[Choice(value=one.value, label=one.label) for one in ask.options or []],
        max_length=ask.max_length or buttons.DEFAULT_ASK_TEXT,
        min=ask.min,
        max=ask.max,
        step=ask.step,
    )


def _action(button: buttons.Button, values: dict[str, Any]) -> Action:
    """A button of the author as an action like every other one (KARTEN-8, one way for all actions).

    ``params`` are the values of the data the button takes, exactly as the answer had them: the guard of the collector
    lets through only what was offered, and a press with other values never reaches :meth:`CustomAdapter.action`.
    """
    return Action(
        id=buttons.ACTION_PREFIX + button.id,
        label=button.label,
        icon=button.icon or "",
        # ⚠️ Dangerous includes asking first: the second question is the browser's, after the first.
        confirm=button.confirm or button.danger,
        danger=button.danger,
        params=dict(values),
        asks=[_ask(one) for one in button.asks],
    )


def _row_item(row: pipeline.Row, base: str, *, pictures: bool, on_rows: tuple[buttons.Button, ...] = ()) -> dict[str, Any]:
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
        art = images.reference(row.image, base, named=row.image_named)
        if art:
            item["art"] = art
    cells = _cells(row, ("title", "subtitle", "value"))
    if cells:
        item["shown"] = cells
    offered = [_action(one, row.buttons[one.id]).model_dump() for one in on_rows if one.id in row.buttons]
    if offered:
        item["actions"] = offered
    return item


#: What a rule says, as the browser of a card of blocks knows it.
BLOCK_STATUS = {"ok": "ok", "warn": "warn", "bad": "error"}


def _block_value(shown: pipeline.Shown | None, fixed: Any = None, *, written: bool = True) -> dict[str, Any] | None:
    """One value of a block as it is drawn, ``None`` where there is nothing to show (KARTEN-7 EC-1).

    A text the author wrote stands as English (or the first language written) and, written in several languages, carries
    them all in ``local`` for the browser to pick from. A unit goes behind the text; a percentage already has its sign.
    A number, a date or anything with a unit also carries ``cell`` (value, format, digits, unit in every language written)
    for the browser to write in the language and zone of its viewer; ``text`` is what a browser without it would show.
    A bar and a line draw the number and have no words to write (``written=False``).
    """
    if shown is None:
        if fixed is None or fixed == "":
            return None
        out: dict[str, Any] = {"text": plain(fixed)}
        if isinstance(fixed, dict):
            out["local"] = fixed
        return out
    if shown.value is None:
        return None
    text = shown.text
    unit = plain(shown.unit)
    if unit and shown.format != "percent":
        text = f"{text} {unit}"
    out = {"text": text}
    number = _number(shown)
    if number is not None:
        out["number"] = number
    # ⚠️ Numbers and times in the language and zone of whoever looks: the browser writes them from this, as for a cell of a list.
    if written and (shown.format != "text" or shown.unit):
        out["cell"] = {
            "value": number if number is not None else shown.value,
            "text": shown.text,
            "format": shown.format,
            "digits": shown.digits,
            "unit": shown.unit or "",
        }
    if shown.status in BLOCK_STATUS:
        out["status"] = BLOCK_STATUS[shown.status]
    return out


def _statuses(tree: list[dict[str, Any]]) -> Iterator[str]:
    """The colours the rules of the values of a card of blocks came to, leaving out the rows of its lists."""
    for node in tree:
        shown = node.get("value")
        if isinstance(shown, pipeline.Shown) and shown.status:
            yield shown.status
        if node["type"] in blocks.HOLDERS:
            yield from _statuses(node["children"])


def _metrics_of(tree: list[dict[str, Any]]) -> Iterator[tuple[str, float]]:
    """The number of every sparkline: what the card records under ``b_<id>``."""
    for node in tree:
        if node["type"] == "sparkline":
            number = _number(node["value"])
            if number is not None:
                yield node["metric"], float(number)
        if node["type"] in blocks.HOLDERS:
            yield from _metrics_of(node["children"])


def _texts(nodes: list[dict[str, Any]]) -> Iterator[str]:
    """The words of a row, first to last: the title its item carries."""
    for node in nodes:
        shown = node.get("value")
        if isinstance(shown, pipeline.Shown) and shown.value is not None:
            yield shown.text
        if node["type"] in blocks.HOLDERS:
            yield from _texts(node["children"])


class _Blocks:
    """The worked out blocks of a card as the browser draws them (``meta.blocks``), with the actions they offer."""

    def __init__(self, definition: Any, base: str, pictures: bool, widget_id: int | None) -> None:
        self.buttons = {one.id: one for one in definition.buttons}
        self.base, self.pictures, self.widget_id = base, pictures, widget_id
        #: The buttons on the card that a block draws; and the rows of the lists, as items with the buttons on them.
        self.on_card: dict[str, Action] = {}
        self.items: list[dict[str, Any]] = []

    def picture(self, node: dict[str, Any]) -> str | None:
        if not self.pictures or not node["link"]:
            return None
        art = images.reference(node["link"], self.base, named=node["named"])
        if not art:
            return None
        # Where the browser asks for it: the image route of this card, which adds the connection's own credentials.
        return f"/api/v1/widgets/{self.widget_id}/image?path={quote(art[6:], safe='')}" if self.widget_id is not None else art

    def draw(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.one(node) for node in nodes]

    def one(self, node: dict[str, Any]) -> dict[str, Any]:
        kind = node["type"]
        out: dict[str, Any] = {"type": kind}
        if node["id"] is not None:
            out["id"] = node["id"]
        if kind in blocks.HOLDERS:
            out["gap"] = node["gap"]
            if kind == "row":
                out["align"], out["wrap"] = node["align"], node["wrap"]
            out["children"] = self.draw(node["children"])
        elif kind in ("text", "badge"):
            out["value"] = _block_value(node["value"], node["fixed"])
            out["color"] = node["color"]
            if kind == "text":
                out["size"], out["weight"] = node["size"], node["weight"]
        elif kind == "value":
            shown = node["value"]
            if shown.label is not None:
                out["label"] = shown.label
            out.update(value=_block_value(shown), size=node["size"], color=node["color"])
        elif kind == "symbol":
            out.update(icon=node["icon"], color=node["color"], size=node["size"])
        elif kind == "image":
            out.update(src=self.picture(node), height=node["height"])
        elif kind == "progress":
            out.update(value=_block_value(node["value"], written=False), max=node["max"], color=node["color"])
        elif kind == "sparkline":
            out.update(value=_block_value(node["value"], written=False), metric=node["metric"])
        elif kind == "list":
            out["rows"] = [self.row(one) for one in node["rows"]]
            if node["empty"] is not None:
                out["empty"] = node["empty"]
        elif kind == "button":
            out["action"] = self.action(node)
        return out

    def action(self, node: dict[str, Any]) -> dict[str, Any] | None:
        button = self.buttons.get(node["button"])
        if button is None or node["values"] is None:
            return None
        made = _action(button, node["values"])
        if button.where == "card":
            self.on_card.setdefault(button.id, made)
        return made.model_dump()

    def row(self, row: dict[str, Any]) -> dict[str, Any]:
        drawn = self.draw(row["blocks"])
        offered = [_action(self.buttons[name], values).model_dump() for name, values in row["buttons"].items()]
        # The row is an item as well: the guard of the collector knows the buttons on rows by the items of a card.
        self.items.append({"title": next(iter(_texts(row["blocks"])), ""), **({"actions": offered} if offered else {})})
        return {"blocks": drawn, **({"actions": offered} if offered else {})}


def _present_blocks(definition: Any, result: pipeline.Result, *, base: str, pictures: bool, widget_id: int | None) -> WidgetData:
    """A card of blocks: the tree to draw, the main value for the tile, the history of its sparklines (KARTEN-7)."""
    drawn = _Blocks(definition, base, pictures, widget_id)
    meta: dict[str, Any] = {"custom": True, "blocks": drawn.draw(result.tree)}
    metrics: dict[str, float] = dict(_metrics_of(result.tree))
    primary = None
    if result.value is not None:
        primary = _cell(result.value)
        if isinstance(primary["value"], int | float) and not isinstance(primary["value"], bool):
            metrics["value"] = float(primary["value"])
    status = _worst(result.status, *_statuses(result.tree))
    return WidgetData(status=status, primary=primary, metrics=metrics, items=drawn.items, meta=meta, actions=list(drawn.on_card.values()))


def present(
    definition: Any, result: pipeline.Result, *, base: str = "", pictures: bool = True, widget_id: int | None = None
) -> WidgetData:
    """What the renderers read, made from the finished values of the pipeline (KARTEN-6), with the buttons (KARTEN-8).

    ``widget_id`` is the card the pictures of a card of blocks are asked of; without it (a preview) they keep the
    address ``proxy:…`` for whoever knows where to ask.
    """
    if definition.form == "builder":
        return _present_blocks(definition, result, base=base, pictures=pictures, widget_id=widget_id)
    meta: dict[str, Any] = {"custom": True}
    every = tuple(getattr(definition, "buttons", None) or ())
    actions = [_action(one, result.buttons[one.id]) for one in every if one.where == "card" and one.id in result.buttons]
    if definition.form == "value":
        assert result.value is not None
        primary = _cell(result.value)
        metrics = {"value": float(primary["value"])} if isinstance(primary["value"], int | float) and not isinstance(primary["value"], bool) else {}
        return WidgetData(status=_worst(result.value.status, result.status), primary=primary, metrics=metrics, meta=meta, actions=actions)
    if definition.form == "stats":
        cells = [_cell(one) for one in result.stats]
        metrics: dict[str, float] = {}
        for index, cell in enumerate(cells):
            cell["metric"] = STAT_METRICS[index]
            if isinstance(cell["value"], int | float) and not isinstance(cell["value"], bool):
                metrics[STAT_METRICS[index]] = float(cell["value"])
        status = _worst(result.status, *(one.status for one in result.stats))
        return WidgetData(status=status, primary=cells[0] if cells else None, secondary=cells[1:], metrics=metrics, meta=meta, actions=actions)
    meta["empty"] = getattr(definition, "empty", None)
    on_rows = tuple(one for one in every if one.where == "row")
    items = [_row_item(row, base, pictures=pictures, on_rows=on_rows) for row in result.rows]
    return WidgetData(status=_worst(result.status), items=items, meta=meta, actions=actions)


class CustomAdapter(Adapter):
    kind = "custom"
    label = "Custom card"
    category = "generic"
    description = "A card described as data: which requests to ask a connection, which values to show, and when to turn yellow or red."
    icon = "lucide:layout-dashboard"
    # A card someone wrote is theirs, not a service nexdeck has yet to confirm: no beta mark on it.
    beta = False
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
        _kind("builder", "Custom layout", "A card put together from blocks: rows, columns, text, values, bars, pictures, lists and buttons.", "builder",
              default_size=(3, 3), min_size=(2, 2)),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        raise AdapterError("A custom card has no connection of its own.", code="no_connection_of_its_own")

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        definition = definition_of(options)
        real, real_config, real_ctx = await self._connection(definition, widget_kind, ctx)
        answers = {request.id: await source.fetch_source(real, real_config, real_ctx, request) for request in definition.requests}
        # ⚠️ In a thread of its own: a path or a filter over a large answer cannot be interrupted, and on the event loop it
        # would hold every other card and request still while it runs (KARTEN-5 AC-11, found in the review, 25.10.2026).
        result = await asyncio.to_thread(pipeline.run, definition, answers)
        return present(definition, result, base=real.raw_base(real_config), widget_id=ctx.widget_id)

    async def action(
        self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context
    ) -> str:
        """One press of a button of the card: one request to the card's connection (KARTEN-8, decisions 3, 4, 7, 8).

        The guard of the collector let through only a button the card offered, with exactly the values it offered. The
        definition is read again here: a button removed since is no longer offered, a path changed since is the new
        path with the values that were offered.
        """
        if not action_id.startswith(buttons.ACTION_PREFIX):
            raise AdapterError("This widget has no actions.", code="no_such_action")
        definition = definition_of(options)
        button = next((one for one in definition.buttons if buttons.ACTION_PREFIX + one.id == action_id), None)
        if button is None:
            raise buttons.no_longer_offered()
        # ⚠️ The blanks are checked against the definition as it is now, not as it was when the button was shown: a range
        # or a list of choices that was narrowed since is the one that counts (EC-9).
        params = dict(params)
        for ask in button.asks:
            key = buttons.ASK_PREFIX + ask.name
            if key not in params:
                raise buttons.no_longer_offered()
            params[key] = fill_in(_ask(ask), params[key])
        real, real_config, real_ctx = await self._connection(definition, widget_kind, ctx)
        path, body = buttons.press(button, params)
        try:
            response = await real.raw_act(
                button.method, path, real_config, real_ctx,
                json_body=body if button.send == "json" else None,
                form=body if button.send == "form" else None,
            )
        finally:
            # Whatever came back, the service may have changed: the next read asks again instead of answering from memory.
            real_ctx.forget_answers()
        if response.status_code in (401, 403):
            raise AuthFailed(status=response.status_code)
        if response.status_code >= 400:
            raise AdapterError(f"The service answered HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json() if button.answer is not None and response.content else None
        except (ValueError, RecursionError):
            answer = None  # no JSON, or nested deeper than it can be read: nothing of it is shown
        return buttons.answer_text(button, answer)

    async def _connection(self, definition: Any, widget_kind: str, ctx: Context) -> tuple[Adapter, dict[str, Any], Context]:
        """The connection the card reads through and its buttons act on, after the checks every read and press passes."""
        if ctx.resolve_integration is None or ctx.integration_id is None:
            raise AdapterError(
                "Connection missing. The connection of this card was deleted.", code="connection_missing", hint="Pick a connection in the card's settings."
            )
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
        return real, real_config, real_ctx

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
