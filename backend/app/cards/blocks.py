"""The building blocks of a card put together by hand (KARTEN-7): what a definition may say about them.

A card of the form ``builder`` is a stack of blocks. Twelve kinds in four groups: layout (``row``, ``column``,
``divider``), content (``text``, ``value``, ``badge``, ``symbol``, ``image``), data (``progress``, ``sparkline``,
``list``) and action (``button``). Every setting has a fixed set of steps and a default, colours are the theme's and
nexdeck's own, and there is no HTML, no CSS and no free size: whatever the author writes, the card stays a card of
nexdeck. A card can come from the shop, so the limits are narrow: 100 blocks, 6 levels, 50 rows.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticCustomError

from .schema import Label, Part, Val, ValueRef, _local_text

#: The most blocks a card has, counted through every row, column and list (KARTEN-7 AC-5).
MAX_BLOCKS = 100
#: The most levels: the blocks of the card are the first.
MAX_DEPTH = 6
#: A word on a card: a heading, a name, a short sentence.
BlockText = _local_text(200)

#: The colours of a block. The theme's (accent, green, yellow, red, muted, text) and nexdeck's own tokens; never a free colour.
COLORS = ("text", "accent", "green", "yellow", "red", "muted", "blue", "violet", "pink", "orange")
SIZES = ("xs", "s", "m", "l", "xl")
GAPS = ("none", "s", "m", "l")
ALIGNS = ("start", "center", "end", "between")
HEIGHTS = ("s", "m", "l")
#: The twelve kinds, in the order of their four groups.
GROUPS: dict[str, tuple[str, ...]] = {
    "layout": ("row", "column", "divider"),
    "content": ("text", "value", "badge", "symbol", "image"),
    "data": ("progress", "sparkline", "list"),
    "action": ("button",),
}
KINDS = tuple(kind for kinds in GROUPS.values() for kind in kinds)
#: The kinds that hold others.
HOLDERS = ("row", "column")
#: What a sparkline records its number under, in front of the block's id.
METRIC_PREFIX = "b_"

Color = Literal["text", "accent", "green", "yellow", "red", "muted", "blue", "violet", "pink", "orange"]
Step = Literal["xs", "s", "m", "l", "xl"]
Gap = Literal["none", "s", "m", "l"]
Align = Literal["start", "center", "end", "between"]
Height = Literal["s", "m", "l"]
BlockId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,29}$")]


class _Block(Part):
    id: BlockId | None = Field(default=None, description="A short name, to point at the block: the main value, a sparkline's history. Once per card.")


def _exactly_one(block: Any, *names: str) -> None:
    if sum(getattr(block, name) is not None for name in names) != 1:
        raise PydanticCustomError("card_one_of", "Give exactly one of {names}.", {"names": ", ".join(names)})


class RowBlock(_Block):
    """Blocks side by side; they wrap onto a new line when the card is narrow."""

    type: Literal["row"]
    children: list[Block] = Field(default_factory=list)
    gap: Gap = "m"
    align: Align = "start"
    wrap: bool = True


class ColumnBlock(_Block):
    """Blocks one under the other."""

    type: Literal["column"]
    children: list[Block] = Field(default_factory=list)
    gap: Gap = "m"


class DividerBlock(_Block):
    type: Literal["divider"]


class TextBlock(_Block):
    """A text of the author, or a value of the answers shown as a line."""

    type: Literal["text"]
    text: BlockText | None = Field(default=None, description="A text, or one per language such as {en: Hello, de: Hallo}.")
    value: ValueRef | None = Field(default=None, description="A value of the answers, shown as text. Give this or text.")
    size: Step = "m"
    weight: Literal["normal", "bold"] = "normal"
    color: Color = "text"

    @model_validator(mode="after")
    def _one_source(self) -> TextBlock:
        _exactly_one(self, "text", "value")
        return self


class ValueBlock(Val):
    """A value with its label, unit and rules, the way a card of one number shows it. The fields of a value stand right here."""

    type: Literal["value"]
    id: BlockId | None = Field(default=None, description="A short name, to point at the block: the main value of the card. Once per card.")
    size: Step = "l"
    color: Color = "text"


class BadgeBlock(_Block):
    """A small label; the rules of its value colour it."""

    type: Literal["badge"]
    text: BlockText | None = None
    value: ValueRef | None = None
    color: Color = "muted"

    @model_validator(mode="after")
    def _one_source(self) -> BadgeBlock:
        _exactly_one(self, "text", "value")
        return self


class SymbolBlock(_Block):
    type: Literal["symbol"]
    icon: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")] = Field(description="A Lucide icon, such as server or flame.")
    color: Color = "text"
    size: Step = "m"


class ImageBlock(_Block):
    """A picture the answers name: an address with http or https, or a path on the connection."""

    type: Literal["image"]
    src: ValueRef
    height: Height = "m"


class ProgressBlock(_Block):
    """A bar for a value out of a largest value, 100 unless said otherwise."""

    type: Literal["progress"]
    value: ValueRef
    max: float | ValueRef = Field(default=100, description="The value that fills the bar: a number, or a value of the answers.")
    color: Color = "accent"

    @field_validator("max")
    @classmethod
    def _above_zero(cls, found: Any) -> Any:
        if isinstance(found, float | int) and not isinstance(found, bool) and not found > 0:
            raise PydanticCustomError("card_out_of_range", "This is outside what is allowed (above 0).", {"bound": 0})
        return found


class SparklineBlock(_Block):
    """The course of a number over the last hours, drawn from what the card recorded; the id names the history."""

    type: Literal["sparkline"]
    id: BlockId = Field(description="Required: the history is kept under it.")  # type: ignore[assignment]
    value: ValueRef


class ListBlock(_Block):
    """The same blocks for every row of the card's ``rows``, at most 50."""

    type: Literal["list"]
    item: list[Block] = Field(min_length=1, description="The blocks of one row. Paths in them are read inside the row. No list in here.")
    empty: Label | None = Field(default=None, description="What the list says when there are no rows. Left out, it says Nothing here.")


class ButtonBlock(_Block):
    """A button of the card's ``buttons``, by its id: on the card, or on every row of a list."""

    type: Literal["button"]
    button: BlockId = Field(description="The id of one of the buttons of the card.")


Block = Annotated[
    RowBlock | ColumnBlock | DividerBlock | TextBlock | ValueBlock | BadgeBlock | SymbolBlock | ImageBlock | ProgressBlock | SparklineBlock | ListBlock | ButtonBlock,
    Field(discriminator="type"),
]

for _model in (RowBlock, ColumnBlock, ListBlock):
    _model.model_rebuild()


def _counted(blocks: Any) -> tuple[int, int]:
    """How many blocks a raw list holds in all and how deep it goes, without recursion: nobody can make this loop long."""
    count, deepest = 0, 0
    pending: list[tuple[Any, int]] = [(blocks, 1)]
    while pending:
        here, depth = pending.pop()
        if not isinstance(here, list):
            continue
        for one in here:
            count += 1
            deepest = max(deepest, depth)
            if isinstance(one, dict):
                for name in ("children", "item"):
                    pending.append((one.get(name), depth + 1))
    return count, deepest


def limited(blocks: Any) -> Any:
    """More than 100 blocks, or more than six levels, are refused with a code of their own, before any of them is looked at (AC-5)."""
    count, deepest = _counted(blocks)
    if count > MAX_BLOCKS:
        raise PydanticCustomError("card_too_many_blocks", "A card has at most {limit} blocks; this one has {count}.", {"limit": MAX_BLOCKS, "count": count})
    if deepest > MAX_DEPTH:
        raise PydanticCustomError("card_blocks_too_deep", "Blocks go at most {limit} levels deep; this card goes {depth}.", {"limit": MAX_DEPTH, "depth": deepest})
    return blocks


Blocks = Annotated[list[Block], BeforeValidator(limited), Field(min_length=1)]

Place = tuple[str | int, ...]


def children_of(block: Any) -> list[tuple[str, list[Any]]]:
    """The lists of blocks a block holds, by the field they stand in."""
    if block.type in HOLDERS:
        return [("children", block.children)]
    if block.type == "list":
        return [("item", block.item)]
    return []


def walk(blocks: list[Any], place: Place = ("blocks",), *, in_list: bool = False) -> list[tuple[Place, Any, bool]]:
    """Every block with its place in the definition and whether it stands inside a list, in the order they are written."""
    found: list[tuple[Place, Any, bool]] = []
    for index, block in enumerate(blocks):
        here = (*place, index)
        found.append((here, block, in_list))
        for name, inner in children_of(block):
            found += walk(inner, (*here, name), in_list=in_list or block.type == "list")
    return found


def holds_list(blocks: list[Any]) -> bool:
    return any(block.type == "list" for _place, block, _in in walk(blocks))


def problems(definition: Any) -> list[tuple[Place, str, str, dict[str, Any]]]:
    """What a schema cannot say about the blocks of a card: ``(place, code, message, params)``."""
    found: list[tuple[Place, str, str, dict[str, Any]]] = []
    if getattr(definition, "form", None) != "builder":
        return found
    every = walk(definition.blocks)
    seen: set[str] = set()
    for place, block, in_list in every:
        if block.id is not None:
            if block.id in seen:
                found.append(((*place, "id"), "card_duplicate_block", f"Two blocks share the id {block.id}.", {"id": block.id}))
            seen.add(block.id)
        if block.type == "list" and in_list:
            found.append((place, "card_list_in_list", "A list cannot stand inside a list.", {}))
        if block.type == "sparkline" and in_list:
            found.append((place, "card_sparkline_in_list", "A sparkline draws the history of the card, not of a row: put it outside the list.", {}))
        if block.type == "button":
            one = next((candidate for candidate in definition.buttons if candidate.id == block.button), None)
            if one is None:
                found.append(((*place, "button"), "card_unknown_button", f"The card has no button called {block.button}; declare it under buttons.", {"id": block.button}))
            elif one.where == "row" and not in_list:
                found.append(((*place, "button"), "card_button_outside_list", "A button on every row belongs inside a list.", {"id": block.button}))
    if holds_list(definition.blocks) and definition.rows is None:
        place = next(place for place, block, _in in every if block.type == "list")
        found.append((place, "card_list_needs_rows", "A list needs rows: say where they are in the answers.", {}))
    if definition.main is not None:
        wanted = [block for _place, block, in_list in every if block.type == "value" and block.id == definition.main and not in_list]
        if not wanted:
            found.append((("main",), "card_main_unknown", f"The main value {definition.main} is no value block with that id.", {"id": definition.main}))
    return found
