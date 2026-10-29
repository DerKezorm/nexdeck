"""Buttons of a custom card (KARTEN-8): what a definition may say about them.

A button is one request that changes something at the service of the card: a method (never GET, the card reads
already), a path underneath the connection's address, and optionally a body. Values of the answers go in through
placeholders: ``{hash}`` reads a field of the row the button hangs on (``where: row``) or of the answers (``where:
card``), ``{ask.minutes}`` is a blank whoever presses the button fills in. A card can come from the shop, so what a
button may say is narrow: no headers, no host, no credentials, no free placeholders.
"""

from __future__ import annotations

import json
import math
import re
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import BeforeValidator, Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticCustomError

from ..adapters.base import AdapterError
from .formula import compile_ref
from .schema import LABEL_MAX, Label, Part, _local_text, lenient_reading, stays_underneath

#: The most buttons a card has (KARTEN-8 AC-10).
MAX_BUTTONS = 10
#: The most blanks one button leaves.
MAX_ASKS = 5
#: A body: at most this deep (the object itself is the first level) and this many keys and list entries together.
MAX_BODY_DEPTH = 3
MAX_BODY_KEYS = 30
#: The longest text in a body, before the values go in.
MAX_BODY_TEXT = 500
#: The longest free text a blank takes, and the one it takes when the author says nothing.
MAX_ASK_TEXT = 400
DEFAULT_ASK_TEXT = 100
MAX_CHOICES = 30
#: The methods a button may use. GET has no business here: the card reads already.
METHODS = ("POST", "PUT", "PATCH", "DELETE")
#: The forms whose rows a button may hang on. The one place to name another form that has rows.
ROW_FORMS = frozenset({"list", "posters"})
#: What the id of an action made from a button starts with.
ACTION_PREFIX = "button:"
#: What the parameter of a blank is called in the action, in front of its name: a blank never meets a field of the data.
ASK_PREFIX = "ask."

NAME = r"^[a-z][a-z0-9_]{0,29}$"
#: A placeholder that reads the data: a plain name, or up to five of them joined by dots.
DATA_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,4}$")
ASK_PLACE = re.compile(r"^ask\.([a-z][a-z0-9_]{0,29})$")
BRACES = re.compile(r"\{([^{}]*)\}")
#: What a button says, never empty; the question of a blank may be a little longer.
ButtonLabel = _local_text(LABEL_MAX, blank_ok=False)
Question = _local_text(80, blank_ok=False)


def places(text: str) -> list[str]:
    """The placeholders in a text, in order (``ask.x`` for a blank). Raises ``ValueError`` for anything else in braces."""
    found: list[str] = []
    for match in BRACES.finditer(text):
        inner = match.group(1)
        # ``ask.`` is kept for the blanks: a field of the data called ``ask`` is read as ``{ask}`` alone.
        if not (ASK_PLACE.match(inner) or (DATA_PATH.match(inner) and not inner.startswith("ask."))):
            raise ValueError(inner)
        found.append(inner)
    if "{" in BRACES.sub("", text) or "}" in BRACES.sub("", text):
        raise ValueError(text)
    return found


def _placeholders_or_refuse(text: str) -> list[str]:
    try:
        return places(text)
    except ValueError:
        raise PydanticCustomError(
            "card_bad_placeholder",
            "A placeholder is a field name in braces, such as {id} or {item.hash}, or a blank, such as {ask.minutes}. Braces stand for nothing else.",
        ) from None


def ask_name(place: str) -> str | None:
    """The name of the blank a placeholder stands for, ``None`` for one that reads the data."""
    found = ASK_PLACE.match(place)
    return found.group(1) if found else None


def body_leaves(body: Any, path: tuple[str | int, ...] = ()) -> list[tuple[tuple[str | int, ...], Any]]:
    """Every value of a body that is no object and no list, with its place."""
    if isinstance(body, dict):
        return [leaf for key, child in body.items() for leaf in body_leaves(child, (*path, key))]
    if isinstance(body, list):
        return [leaf for index, child in enumerate(body) for leaf in body_leaves(child, (*path, index))]
    return [(path, body)]


BODY_RULE = (
    "A body is an object of at most 3 levels and 30 keys and list entries together; its values are text, numbers, "
    "true, false or null, and a body sent as a form is flat."
)
ASK_RULE = "A blank of the type number takes min, max and step (min not above max), text takes max_length, and choice needs options."


def _body_refused() -> PydanticCustomError:
    return PydanticCustomError("card_button_body", BODY_RULE)


def _size(body: Any, depth: int) -> int:
    """How many keys and list entries a body has; refuses one that is too deep or holds something that is no JSON."""
    if isinstance(body, dict | list):
        if depth > MAX_BODY_DEPTH:
            raise _body_refused()
        children = list(body.values()) if isinstance(body, dict) else body
        return len(children) + sum(_size(child, depth + 1) for child in children)
    if (isinstance(body, float) and not math.isfinite(body)) or (body is not None and not isinstance(body, str | int | float | bool)):
        raise _body_refused()
    if isinstance(body, str) and len(body) > MAX_BODY_TEXT:
        raise PydanticCustomError("card_too_long", "This is {length} characters long, the limit is {limit}.", {"length": len(body), "limit": MAX_BODY_TEXT})
    return 0


def _upper(value: Any) -> Any:
    return value.upper() if isinstance(value, str) else value


def _choice_value(value: Any) -> Any:
    """A choice is passed on as text; a whole number written bare is the same value."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


class Choice(Part):
    value: Annotated[str, BeforeValidator(_choice_value), StringConstraints(min_length=1, max_length=200)]
    label: Label


class ButtonAsk(Part):
    """A blank whoever presses the button fills in: a number in a range, a short text, or one of a list."""

    name: Annotated[str, StringConstraints(pattern=NAME)] = Field(description="Used in the button as {ask.<name>}.")
    label: Question = Field(description="The question, such as How many minutes?")
    type: Literal["number", "text", "choice"]
    min: float | None = Field(default=None, description="number: the smallest value.")
    max: float | None = Field(default=None, description="number: the largest value.")
    step: float | None = Field(default=None, gt=0, description="number: the steps between values; a whole step takes whole numbers only.")
    max_length: int | None = Field(default=None, ge=1, le=MAX_ASK_TEXT, description="text: the most characters, 100 when left out.")
    options: list[Choice] | None = Field(default=None, min_length=1, max_length=MAX_CHOICES, description="choice: what may be picked.")

    @model_validator(mode="after")
    def _fits_its_type(self) -> ButtonAsk:
        own = {"number": ("min", "max", "step"), "text": ("max_length",), "choice": ("options",)}
        foreign = [name for kind, names in own.items() if kind != self.type for name in names if getattr(self, name) is not None]
        upside_down = self.min is not None and self.max is not None and self.min > self.max
        if foreign or (self.type == "choice" and not self.options) or upside_down:
            raise PydanticCustomError("card_button_ask", ASK_RULE)
        return self


class Button(Part):
    """One button: what it is called, where it hangs, and the one request it makes."""

    id: Annotated[str, StringConstraints(pattern=NAME)]
    label: ButtonLabel
    icon: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")] | None = Field(default=None, description="A Lucide icon, such as pause or trash.")
    where: Literal["card", "row"] = Field(default="card", description="On the card, or on every row of a list or of pictures.")
    method: Annotated[Literal["POST", "PUT", "PATCH", "DELETE"], BeforeValidator(_upper)] = Field(description="POST, PUT, PATCH or DELETE.")
    path: Annotated[str, StringConstraints(min_length=1, max_length=500)] = Field(
        description="Underneath the connection's address, such as /api/v2/torrents/pause. Placeholders such as {id} take values of the data."
    )
    send: Literal["json", "form"] = Field(default="json", description="How the body goes: as JSON, or as a form (a flat body).")
    body: dict[str, Any] | None = Field(
        default=None,
        description="What is sent. A value that is exactly a placeholder keeps its type (a number stays a number); "
        "a placeholder inside a text is put in as text. At most 3 levels and 30 keys.",
    )
    confirm: bool = Field(default=False, description="Ask before it runs.")
    danger: bool = Field(default=False, description="Red, and asks twice before it runs.")
    asks: list[ButtonAsk] = Field(default_factory=list, max_length=MAX_ASKS, description="Blanks whoever presses the button fills in.")
    answer: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = Field(
        default=None, description="A JMESPath expression in the service's answer whose value is shown instead of Done."
    )

    @field_validator("path")
    @classmethod
    def _path_stays_underneath_the_connection(cls, path: str) -> str:
        _placeholders_or_refuse(path)
        # ⚠️ Checked with every placeholder standing for a plain value: what the data puts in is checked when it goes in.
        if not stays_underneath(BRACES.sub("x", path)):
            raise PydanticCustomError(
                "card_bad_path", "The path must start with a single / and name no host; it is always underneath the connection's address."
            )
        return path

    @field_validator("body")
    @classmethod
    def _body_is_small_and_plain(cls, body: dict[str, Any] | None) -> dict[str, Any] | None:
        if body is None:
            return None
        if _size(body, 1) > MAX_BODY_KEYS:
            raise _body_refused()
        for _place, leaf in body_leaves(body):
            if isinstance(leaf, str):
                _placeholders_or_refuse(leaf)
        return body

    @model_validator(mode="after")
    def _a_form_is_flat(self) -> Button:
        if self.send == "form" and self.body and any(isinstance(value, dict | list) for value in self.body.values()):
            raise _body_refused()
        names = [ask.name for ask in self.asks]
        if len(set(names)) != len(names):
            twice = next(n for n in names if names.count(n) > 1)
            raise PydanticCustomError("card_duplicate_button", "Two buttons, or two blanks of one button, share the name {id}.", {"id": twice})
        return self

    def placeholders(self) -> list[tuple[tuple[str | int, ...], str]]:
        """Every placeholder of the button with its place in the button (``("path",)`` or ``("body", "hashes")``)."""
        found = [(("path",), place) for place in places(self.path)]
        for where, leaf in body_leaves(self.body or {}):
            if isinstance(leaf, str):
                found += [(("body", *where), place) for place in places(leaf)]
        return found


def too_many(buttons: Any) -> Any:
    """More than ten buttons are refused with a code of their own, before each of them is looked at (AC-10)."""
    if isinstance(buttons, list) and len(buttons) > MAX_BUTTONS:
        raise PydanticCustomError(
            "card_too_many_buttons", "A card has at most {limit} buttons; this one has {count}.", {"limit": MAX_BUTTONS, "count": len(buttons)}
        )
    return buttons


Buttons = Annotated[list[Button], BeforeValidator(too_many)]


def has_rows(definition: Any) -> bool:
    """Whether a card has rows a button can hang on: a list or pictures, or a card of blocks with a list in it."""
    return definition.form in ROW_FORMS or (definition.form == "builder" and definition.holds_list())


def problems(definition: Any) -> list[tuple[tuple[str | int, ...], str, str, dict[str, Any]]]:
    """What a schema cannot say about the buttons of a card: ``(place, code, message, params)``."""
    found: list[tuple[tuple[str | int, ...], str, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for index, button in enumerate(getattr(definition, "buttons", None) or []):
        here: tuple[str | int, ...] = ("buttons", index)
        if button.id in seen:
            found.append(((*here, "id"), "card_duplicate_button", f"Two buttons, or two blanks of one button, share the name {button.id}.", {"id": button.id}))
        seen.add(button.id)
        if button.where == "row" and not has_rows(definition):
            found.append(((*here, "where"), "card_button_no_rows", "A button on every row needs rows: a list or pictures.", {}))
        declared = {ask.name for ask in button.asks}
        for place, name in button.placeholders():
            blank = ask_name(name)
            if blank is not None and blank not in declared:
                found.append(((*here, *place), "card_unknown_ask", f"The button has no blank called {blank}; declare it under asks.", {"name": blank}))
    return found


# -- offering: the values of the data a button takes ------------------------------

#: What a value of the data may be to go into a button: text, a number, true or false, or nothing.
PLAIN = (str, int, float, bool, type(None))
#: What a value never has when it goes into an address (EC-1); ``..`` is looked for on its own.
NOT_IN_AN_ADDRESS = re.compile(r"[/\\?#%\s\x00-\x1f\x7f]")


def walk(data: Any, path: str) -> tuple[bool, Any]:
    """The value at a dotted path, and whether it is there at all: a field that holds ``null`` is there."""
    cursor = data
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return False, None
        cursor = cursor[part]
    return True, cursor


def as_text(value: Any) -> str:
    """A value of the data written into a text: ``true``, ``false`` and numbers as JSON writes them, nothing as nothing."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value)
    return str(value)


def fits_an_address(value: Any) -> bool:
    """A value that may stand in the path of a button: not empty, one plain piece, nothing that ends or climbs a path.

    ⚠️ A single ``.`` is a segment the client drops when it builds the address: ``/torrents/.`` goes out as ``/torrents``.
    What stands in for a dot (``．．``, ``‥``) is refused as well: a server that normalises reads it as ``..`` (S4).
    """
    text = as_text(value)
    read = lenient_reading(text) if text else None
    return bool(text) and read is not None and text != "." and read != "." and ".." not in text + read and not NOT_IN_AN_ADDRESS.search(text)


def offered_values(button: Button, find: Any) -> dict[str, Any] | None:
    """The values a button takes from the data, by placeholder, or ``None`` when it cannot be offered with this data.

    ``find(path)`` gives ``(found, value)``. A placeholder whose field is missing, holds an object or a list, or holds a
    value that cannot go into an address where the path needs it, means no button (EC-1): it is never drawn, so it
    cannot be pressed.
    """
    values: dict[str, Any] = {}
    in_the_path = set(places(button.path))
    for _where, place in button.placeholders():
        if ask_name(place) is not None or place in values:
            continue
        found, value = find(place)
        if not found or not isinstance(value, PLAIN) or (isinstance(value, float) and not math.isfinite(value)):
            return None
        values[place] = value
    if any(not fits_an_address(values[place]) for place in in_the_path if place in values):
        return None
    return values


# -- pressing: the request a button makes --------------------------------------------

#: The longest text of the service's answer a button shows (KARTEN-8 AC-9).
MAX_ANSWER_TEXT = 200


def no_longer_offered() -> AdapterError:
    """The row, the value or the button is gone since the card showed it (EC-3), or the values are not the offered ones (AC-8)."""
    return AdapterError(
        "No longer offered. The card changed since this button was shown.",
        code="no_longer_offered",
        hint="The card is reloaded; press the button again if it is still there.",
    )


def bad_value() -> AdapterError:
    return AdapterError("A value of this button cannot go into an address.", code="bad_value")


def press(button: Button, params: dict[str, Any]) -> tuple[str, Any]:
    """The path and the body of a press, from the definition as it is now and the values that were offered.

    ⚠️ Never text glued into JSON (EC-8): the body is built as an object and serialised once, when it is sent. A body
    value that is exactly one placeholder takes the value with its type; one with text around it takes the value as
    text. A value in the path is checked once more (EC-1) and written with every character outside letters, digits and
    ``-._~`` percent-encoded, so it is always one plain piece of the path.
    """

    def value_of(place: str) -> Any:
        blank = ask_name(place)
        key = ASK_PREFIX + blank if blank is not None else place
        if key not in params:
            # The definition asks for something the card did not offer: it was changed since.
            raise no_longer_offered()
        return params[key]

    def into_the_path(found: re.Match[str]) -> str:
        value = value_of(found.group(1))
        if not isinstance(value, PLAIN) or not fits_an_address(value):
            raise bad_value()
        return quote(as_text(value), safe="-._~")

    path = BRACES.sub(into_the_path, button.path)
    if not stays_underneath(path):
        raise bad_value()

    def filled(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: filled(child) for key, child in node.items()}
        if isinstance(node, list):
            return [filled(child) for child in node]
        if not isinstance(node, str):
            return node
        whole = BRACES.fullmatch(node)
        if whole is not None:
            return value_of(whole.group(1))
        return BRACES.sub(lambda found: as_text(value_of(found.group(1))), node)

    body = filled(button.body) if button.body is not None else None
    if body is not None and button.send == "form":
        body = {key: as_text(value) for key, value in body.items()}
    return path, body


def answer_text(button: Button, answer: Any) -> str:
    """What a pressed button says: the value the author named in the answer, cut to 200 characters, or ``Done`` (AC-9).

    The service's own words appear only when the definition names the field; never its error page, never anything else.
    """
    if button.answer is None or answer is None:
        return "Done"
    found = compile_ref(button.answer).search(answer)
    if found is None:
        return "Done"
    text = as_text(found) if isinstance(found, PLAIN) else json.dumps(found, ensure_ascii=False)
    text = " ".join("".join(char if char.isprintable() else " " for char in text).split())
    if not text:
        return "Done"
    return text if len(text) <= MAX_ANSWER_TEXT else text[: MAX_ANSWER_TEXT - 1] + "…"
