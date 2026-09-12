"""The adapter contract.

An adapter knows one service: which connection fields it needs, which widgets
it offers, how to fetch their data, which actions it can run and what fake
data it produces in demo mode. Everything an adapter returns is a
``WidgetData``: a small, service-independent shape that the frontend renders
with a handful of renderers. That is what makes thirty integrations
maintainable by one person.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel
from pydantic import Field as PydanticField

logger = logging.getLogger("nexdeck.adapters")

#: ``integrations`` is a list of connection numbers. Its ``options`` name the
#: kinds that may be picked; the server checks both the kind and whether the
#: person editing may build on that connection at all.
FieldType = Literal["text", "password", "url", "number", "bool", "select", "integrations",
                    "textarea", "timezone", "items", "choices", "colour", "board", "pictures"]
#: ``items`` picks among the rows a card is showing; ``choices`` picks among
#: values the service itself hands out, through ``Adapter.choices``;
#: ``board`` picks one of this installation's own boards, which no service
#: knows about; ``pictures`` is a list somebody builds by uploading files
#: or naming addresses, not a text field with a syntax.
Status = Literal["ok", "warn", "bad", "unknown"]


@dataclass(frozen=True)
class Field:
    """One configuration field of an integration or a widget."""

    name: str
    label: str
    type: FieldType = "text"
    required: bool = False
    secret: bool = False
    default: Any = None
    help: str = ""
    placeholder: str = ""
    options: tuple[tuple[str, str], ...] = ()
    #: A frontend helper drawn under the field, such as ``plex-signin``.
    helper: str = ""
    #: For a ``choices`` field: which other option names the integration whose
    #: list this is. Empty means the widget's own integration, which is what
    #: every such field meant until a card could point at somebody else's.
    from_field: str = ""
    #: Show this field only while another option has a given value, as
    #: ``(name, value)``.
    #:
    #: ⚠️ An option that does nothing must not be on screen. The volume card
    #: in its dial view still offered "usage bar" and "percentage", which are
    #: parts of a list row, and a dial has no rows: three switches that moved
    #: and changed nothing.
    only_when: tuple[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "secret": self.secret,
            "default": self.default,
            "help": self.help,
            "placeholder": self.placeholder,
            "options": [{"value": v, "label": lab} for v, lab in self.options],
            "helper": self.helper,
            "from_field": self.from_field,
            "only_when": list(self.only_when) if self.only_when else None,
        }


#: How small each drawing is still usable at, in grid cells.
#:
#: ⚠️ Set per renderer, not per widget. Until 06.09.2026 the grid used a
#: card's *default* size as its floor, so ``min_size`` did nothing and nobody
#: noticed that 56 value cards claimed to work at one cell by one and 88 lists
#: at two by one. The moment the floor became real, the weather card drew its
#: sun on top of its own temperature. A number needs room for its label and
#: its chips; a list needs room for two rows; a cover needs to be a cover.
RENDERER_MIN: dict[str, tuple[int, int]] = {
    "app": (1, 1),
    "button": (1, 1),
    "image": (1, 1),
    "wol": (1, 1),
    "clock": (2, 1),
    "text": (2, 1),
    "search": (2, 1),
    "value": (2, 2),
    "gauge": (2, 2),
    "list": (2, 2),
    "bookmarks": (2, 2),
    "camera": (2, 2),
    "iframe": (2, 2),
    "counters": (2, 2),
    "ask": (2, 2),
    "ring": (2, 2),
    "stats": (3, 2),
    "feed": (3, 2),
    "calendar": (3, 2),
    "nowplaying": (3, 2),
    # Two by two holds a cover with its play button on it; the rest of the
    # player grows in as the card does.
    "player": (2, 2),
    "weather": (3, 2),
    "posters": (3, 2),
    "chart": (3, 2),
    "log": (3, 2),
    "timeline": (3, 2),
    "bars": (3, 2),
}
#: For a renderer nobody listed. Two by two is the smallest that holds a title
#: and a line under it without one sitting on the other.
DEFAULT_MIN = (2, 2)


@dataclass(frozen=True)
class WidgetType:
    """One widget an adapter offers."""

    kind: str
    label: str
    description: str
    #: Which frontend renderer draws the data.
    renderer: str
    default_size: tuple[int, int] = (3, 2)
    min_size: tuple[int, int] = (2, 1)
    options: tuple[Field, ...] = ()
    refresh_seconds: int = 30
    #: Metric names this widget records for sparklines.
    metrics: tuple[str, ...] = ()
    #: True for widgets that need no server refresh: clocks, notes, bookmarks,
    #: embedded pages and app tiles draw themselves from their options.
    client_only: bool = False
    #: The pieces of itself this widget can be told to leave out, as
    #: ``(key, label)``. One tick box per entry appears in the widget settings
    #: by itself, so an adapter declares the list and nothing else.
    #:
    #: ⚠️ All of them start ticked. A card that arrives empty and has to be
    #: filled in leaves people guessing what it could show; a card that shows
    #: everything and lets you take pieces away does not.
    #:
    #: A key names either a row (a ``secondary`` entry tagged ``part``) or a
    #: field inside a list item (``cpu``, ``subtitle``, ``value``). Both shapes
    #: occur, and ``keep_parts`` handles both.
    parts: tuple[tuple[str, str], ...] = ()
    #: When the tick boxes made from ``parts`` are worth showing at all.
    parts_only_when: tuple[str, str] | None = None
    #: True when this card's fetch can hand out slices that form a whole.
    #:
    #: ⚠️ Declared, never guessed. A ring says "these are the parts of one
    #: thing", and most cards carry numbers that are not that: Pi-hole's card
    #: shows queries, blocked and clients, and a ring of those three draws a
    #: whole nobody has. So the arithmetic stays in the fetch, which is the
    #: only place that knows what the whole is, and this flag only decides
    #: whether the choice appears at all.
    ring: bool = False

    def __post_init__(self) -> None:
        """Never smaller than the drawing can bear.

        An adapter may ask for more than the floor when its own card needs it;
        it cannot ask for less, because the floor is about the renderer and
        the renderer is not the adapter's to know.
        """
        floor = RENDERER_MIN.get(self.renderer, DEFAULT_MIN)
        raised = (max(self.min_size[0], floor[0]), max(self.min_size[1], floor[1]))
        if raised != tuple(self.min_size):
            object.__setattr__(self, "min_size", raised)
        # A default below the floor would be a card that opens broken.
        grown = (max(self.default_size[0], raised[0]), max(self.default_size[1], raised[1]))
        if grown != tuple(self.default_size):
            object.__setattr__(self, "default_size", grown)
        # The tick boxes are made from ``parts``, not written out by hand.
        # Thirty adapters writing the same list is twenty-nine chances to
        # write it differently and one to forget it.
        # ⚠️ Every list card can be told which rows to show. One rule
        # here rather than a field written into thirty adapters, twenty-nine
        # of which would word it differently.
        if self.renderer == "list" and not any(field.name == ITEM_PICKER for field in self.options):
            object.__setattr__(self, "options", (*self.options, item_picker_field()))
        # The same argument as the tick boxes above, for the drawing itself:
        # a list can be drawn as bars, and a card that says what its slices
        # are can be drawn as a ring. Written here once rather than into the
        # eighty list cards, which is eighty chances to word it differently.
        extra: tuple[tuple[str, str], ...] = ()
        if self.renderer == "list":
            extra += (("bars", "Bars"),)
        if self.ring:
            extra += (("ring", "A ring"),)
        # ⚠️ Two metrics or more, because that is the whole argument for the
        # drawing: a card that records `wan_down` and `wan_up` stores both and
        # could only ever show one of them, and the two put side by side on
        # separate cards had separate scales. One metric already has its
        # sparkline inside the card it belongs to.
        if len(self.metrics) >= 2 and self.renderer != "chart" and not self.client_only:
            extra += (("chart", "A chart"),)
        if extra:
            object.__setattr__(self, "options", offer_views(self.options, self.renderer, extra))
        if self.parts:
            existing = {field.name for field in self.options}
            made = tuple(
                Field(part_option(key), label, type="bool", default=True, only_when=self.parts_only_when)
                for key, label in self.parts
                if part_option(key) not in existing
            )
            object.__setattr__(self, "options", tuple(self.options) + made)

    def to_dict(self, adapter_kind: str) -> dict[str, Any]:
        return {
            "kind": f"{adapter_kind}.{self.kind}",
            "label": self.label,
            "description": self.description,
            "renderer": self.renderer,
            "default_size": list(self.default_size),
            "min_size": list(self.min_size),
            "options": [f.to_dict() for f in self.options],
            "refresh_seconds": self.refresh_seconds,
            "metrics": list(self.metrics),
            "client_only": self.client_only,
        }


def saveable(path: str, name: str, size: float | None = None) -> dict[str, Any]:
    """A file a row offers to save, put on the row as ``file``.

    ⚠️ The path is an allowlist entry, not a parameter. Whoever may look at
    the board may ask the server for a file the card named, and for nothing
    else: the download address checks the path against the rows the card last
    delivered, the way an action is checked against what it last offered. Left
    open, it would be "fetch any path from this service with the server's
    credentials", handed to every kiosk display in the house.
    """
    return {"path": path, "name": name, **({"size": float(size)} if size else {})}


class Choice(BaseModel):
    """One entry of a pick list a card offers with an action."""

    value: str
    label: str


class Ask(BaseModel):
    """A blank in an action, filled in by whoever presses the button.

    ⚠️ The third case, and the one the guard of 0.2.0 was written against. An
    action reaches the adapter only because the card put it in its last answer
    with exactly those parameters, and a blank has no fixed value to compare.
    The card therefore says here which parameter is blank and what may go in
    it: everything else about the action still has to match what was offered,
    and a value that does not fit this declaration never reaches the adapter.

    ⚠️ **A pick list is the ordinary case, free text the exception.** It was
    the other way round for one release, and that was wrong: with ``choice``
    the card hands the permitted values over in its own answer, so the guard
    can check the pressed value against them exactly as it checks a fixed
    parameter. ``text`` and ``url`` are what is left when nobody can say in
    advance what the value will be, and only then is a rule needed instead of
    a list.

    That is also why an action may carry several. The first version allowed
    one, on the grounds that two blanks would be a form; that reasoning holds
    for free text and not for lists. Approving a request in Nexview needs two
    at once, a target folder and a quality profile, and one without the other
    is not a smaller question but an unanswerable one.
    """

    #: The parameter the chosen or typed value is passed as.
    name: str
    label: str
    #: ``choice`` picks from ``options``; ``url`` is checked the way a
    #: member-supplied address is checked everywhere else in nexdeck: http or
    #: https, a host, and nothing that only answers to the server itself.
    kind: Literal["text", "url", "choice"] = "text"
    #: For ``choice``: what may be picked. Delivered with the card's answer,
    #: which is what lets the guard check the pressed value against it.
    options: list[Choice] = PydanticField(default_factory=list)
    placeholder: str = ""
    max_length: int = 400


def fill_in(ask: Ask, value: Any) -> str:
    """What the filled-in value must look like before an adapter sees it.

    Refuses rather than trims, apart from surrounding blanks: a silently
    shortened address is a download of something else.
    """
    if not isinstance(value, str):
        raise AdapterError("This action needs a value.", code="bad_value")
    text = value.strip()
    if not text:
        raise AdapterError("This action needs a value.", code="bad_value")
    if ask.kind == "choice":
        # ⚠️ Against the list the card handed over with the action, not
        # against a list fetched now. What was on screen is what may be
        # pressed, which is the same rule the fixed parameters follow.
        if text not in {one.value for one in ask.options}:
            raise AdapterError("That is not one of the values this card offered.", code="bad_value")
        return text
    if len(text) > ask.max_length:
        raise AdapterError(
            f"That is longer than the {ask.max_length} characters this field takes.", code="bad_value")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise AdapterError("That contains characters a field like this never has.", code="bad_value")
    if ask.kind == "url":
        if "://" not in text:
            raise AdapterError("That is not an address: it starts with http:// or https://.", code="bad_value")
        guard_member_target(text)
    return text


class Action(BaseModel):
    id: str
    label: str
    icon: str = ""
    confirm: bool = False
    danger: bool = False
    params: dict[str, Any] = PydanticField(default_factory=dict)
    #: The parameters whoever presses this button fills in themselves.
    asks: list[Ask] = PydanticField(default_factory=list)


@dataclass(frozen=True)
class Deed:
    """One action a card of its own may be pointed at.

    ⚠️ An allowlist, and deliberately short. Every other action in nexdeck is
    reachable only because the card that offers it put it in its last answer,
    which is the guard from 0.2.0; a button carries no such answer, so what a
    button may reach is written down here instead. An adapter that declares
    nothing can be looked at from a button and not touched.
    """

    #: The widget kind whose ``action`` handles it.
    widget_kind: str
    id: str
    label: str
    #: The field whose ``choices`` name what it acts on, and the parameter it
    #: is passed as. Empty when the action needs no target.
    target_field: str = ""
    #: What to call that target on screen, in the adapter's own word.
    target_label: str = "Target"
    icon: str = "zap"


class WidgetData(BaseModel):
    """What every widget fetch returns."""

    status: Status = "ok"
    #: ``{"label": str, "value": number|str, "unit": str, "format": str}``
    primary: dict[str, Any] | None = None
    secondary: list[dict[str, Any]] = PydanticField(default_factory=list)
    items: list[dict[str, Any]] = PydanticField(default_factory=list)
    actions: list[Action] = PydanticField(default_factory=list)
    #: Numeric samples recorded for history and sparklines.
    metrics: dict[str, float] = PydanticField(default_factory=dict)
    link: str | None = None
    meta: dict[str, Any] = PydanticField(default_factory=dict)
    error: str | None = None
    updated_at: float = PydanticField(default_factory=time.time)


class Detected(BaseModel):
    """Something an adapter noticed between two fetches, worth telling about.

    ⚠️ Only what the adapter *knows*, never what it guesses. "A download
    finished" is true when an item that was almost done is gone; "a download
    was removed" is what the same disappearance means at ten per cent, and
    saying the first about the second is worse than saying nothing.
    """

    event: str
    title: str
    body: str = ""
    level: Status = "ok"
    #: Two of the same thing inside this many seconds count as one. A card
    #: that refreshes every thirty seconds must not send the same line twice.
    quiet_seconds: float = 900.0
    #: What makes this one distinct from the next. Defaults to event + title.
    key: str = ""

    def dedupe_key(self) -> str:
        return self.key or f"{self.event}:{self.title}"


# ---------------------------------------------------------------------------
# Which pieces of a card are shown
# ---------------------------------------------------------------------------


#: What may stand in a single segment of a path we build ourselves.
_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def path_segment(value: Any, what: str) -> str:
    """A value on its way into an address, or an error.

    ⚠️ httpx normalises a path before it sends it, and a question mark ends it.
    Measured with the pinned 0.28.1: ``/containers/../volumes/prune?x=/start``
    goes out as ``/volumes/prune``. Anything that reaches an engine, a
    hypervisor or a management API through a path we assemble has to be a
    single segment and nothing else.

    The name of a container comes from the foreign service, not from us, so
    this is not only about what a caller sends: a container called ``..`` would
    be offered by the card like any other.
    """
    text = str(value or "")
    if not _PATH_SEGMENT.match(text):
        raise AdapterError(f"{what} is not a name this can be used with.", code="bad_param")
    return text


def part_option(key: str) -> str:
    """The option name behind a part. One place, so nobody spells it twice."""
    return f"show_{key}"


def part_on(options: dict[str, Any], key: str) -> bool:
    """Is this piece switched on? Missing means yes."""
    return options.get(part_option(key)) is not False


def join_parts(options: dict[str, Any], *pieces: tuple[str, Any]) -> str:
    """One line built from the pieces that are switched on.

    For a card that writes several facts into one subtitle. Without this the
    adapter would have to test each tick box by hand, and a line assembled by
    hand is a line that ends up with a stray separator in it.
    """
    return " · ".join(str(value) for key, value in pieces if value and part_on(options, key))


#: Every list card offers it, so an adapter does not have to think about it.
ITEM_PICKER = "only_items"


def item_picker_field() -> Field:
    return Field(
        ITEM_PICKER, "Entries", type="items",
        help="Nothing picked means all of them, so a new entry appears by itself.",
    )


#: Where the settings sheet finds every row, including the hidden ones.
ALL_ITEMS = "all_items"


def keep_items(data: WidgetData, options: dict[str, Any], *, remember_all: bool = False) -> WidgetData:
    """Keep only the rows that were picked.

    ⚠️ An empty list means all of them. The rows come from the service, so
    a new disk or a new container turns up on its own; a picker that stored
    "these five" would quietly hide the sixth, which is the one worth seeing.

    Matched by title, not by id. A container keeps its name and gets a new id
    every time it is recreated, and the title is what the person ticked.
    """
    if remember_all and ALL_ITEMS not in (data.meta or {}):
        # ⚠️ Written down before anything is dropped, and only for the
        # settings sheet. The tick boxes are made from the rows the card
        # shows, so switching one off took its own box away with it and there
        # was no way back. The boards do not get this: it is a second copy of
        # every title on every refresh, for a question only the sheet asks.
        #
        # ⚠️ And never over one that is already there. An adapter that filters
        # its own rows before this runs, because it needs them narrowed before
        # it can draw, has already written down what it saw first, and by here
        # that is more than is left.
        data.meta = {**(data.meta or {}), ALL_ITEMS: [str(item.get("title") or "") for item in data.items]}
    wanted = options.get(ITEM_PICKER)
    if not isinstance(wanted, list) or not wanted:
        return data
    keep = {str(one) for one in wanted}
    data.items = [item for item in data.items if str(item.get("title") or "") in keep]
    return data


def keep_parts(data: WidgetData, parts: tuple[tuple[str, str], ...], options: dict[str, Any]) -> WidgetData:
    """Take out the pieces this card was told to leave out.

    Applied once by the collector, so an adapter declares its parts and stops
    thinking about them.

    ⚠️ The metrics are untouched. What a card draws and what it records
    are different questions, and a graph with a hole in it because somebody
    hid a row for a week is not what anybody meant by hiding a row.
    """
    off = {key for key, _label in parts if not part_on(options, key)}
    if not off:
        return data

    data.secondary = [row for row in data.secondary if str(row.get("part") or "") not in off]
    if data.primary and str(data.primary.get("part") or "") in off:
        # ⚠️ A stats card whose first row is gone must not go blank: the
        # next row moves up. Dropping the primary and leaving the rest would
        # look like the service stopped answering.
        data.primary = data.secondary.pop(0) if data.secondary else None

    for item in data.items:
        for key in off:
            item.pop(key, None)
    return data


#: The two options a card needs to be able to draw itself as a dial.
#:
#: ⚠️ A dial without a maximum is a lie: it claims a share of something. A
#: card that measures megabytes per second has no ceiling of its own, so the
#: operator names one, and until they do the card stays a number.
def gauge_fields(what: str, placeholder: str = "") -> tuple[Field, ...]:
    return (
        Field("view", "View", type="select", default="value",
              options=(("value", "The number"), ("gauge", "A dial")),
              help="A dial needs to know what counts as full."),
        Field("gauge_max", "Full at", type="number", placeholder=placeholder,
              help=f"{what} Leave empty and the card stays a number."),
    )


def gauge_view_field() -> Field:
    """For a card whose number is already a share of something."""
    return Field("view", "View", type="select", default="value",
                 options=(("value", "The number"), ("gauge", "A dial")))


def offer_views(options: tuple[Field, ...], renderer: str,
                extra: tuple[tuple[str, str], ...]) -> tuple[Field, ...]:
    """Add drawings to a card's View field, making the field if it has none.

    ⚠️ One option name for every drawing, because ``as_gauge`` has read
    ``view`` since the dial existed. A second name would mean two cards on the
    same board answering the same question differently, and the settings sheet
    showing both.
    """
    # What the card already is, named as the operator sees it. "The number"
    # under a card that draws a dial would be a third thing on a list of two.
    own = ("value", {"list": "Rows", "gauge": "A dial", "stats": "The rows"}.get(renderer, "The number"))
    for index, one in enumerate(options):
        if one.name != "view":
            continue
        known = {value for value, _ in one.options}
        added = tuple(pair for pair in extra if pair[0] not in known)
        if not added:
            return options
        grown = replace(one, options=(*one.options, *added))
        return (*options[:index], grown, *options[index + 1:])
    return (*options, Field("view", "View", type="select", default="value",
                            options=(own, *extra)))


def gauge_pick_field(parts: tuple[tuple[str, str], ...]) -> Field:
    """Which of several rows the needle follows.

    ⚠️ A dial shows one number and these cards carry four. Taking the
    first row silently would mean the dial changes meaning the day somebody
    hides a row, and nobody would connect the two.
    """
    return Field(
        "gauge_part", "Dial shows", type="select", default=parts[0][0],
        options=tuple(parts),
        only_when=("view", "gauge"),
    )


def pick_gauge_row(data: WidgetData, options: dict[str, Any]) -> WidgetData:
    """Move the chosen row to the front, so the dial draws that one."""
    wanted = str(options.get("gauge_part") or "").strip()
    if not wanted or str(options.get("view") or "value") != "gauge":
        return data
    if str((data.primary or {}).get("part") or "") == wanted:
        return data
    for index, row in enumerate(data.secondary):
        if str(row.get("part") or "") == wanted:
            data.secondary = [*data.secondary[:index], *data.secondary[index + 1:]]
            if data.primary:
                data.secondary.insert(0, data.primary)
            data.primary = row
            return data
    return data


def as_gauge(data: WidgetData, options: dict[str, Any], maximum: float | None = None) -> WidgetData:
    """Turn a measured number into a share of something, if asked and possible.

    Returns the card unchanged when the view was not asked for, or when there
    is no ceiling to measure against. Silently drawing an empty dial would be
    worse than drawing the number that was asked for.
    """
    if str(options.get("view") or "value") != "gauge":
        return data
    # Applied once, centrally, by the collector. An adapter that also calls it
    # must not turn its own percentage into a percentage of a percentage.
    if (data.meta or {}).get("renderer") == "gauge":
        return data
    value = (data.primary or {}).get("value")
    ceiling = maximum
    #: Whether anybody actually named a ceiling. A card that measures a
    #: percentage has one by arithmetic, and "35% of 100%" is a sentence about
    #: nothing, so that kind is not written down.
    named = ceiling is not None
    if ceiling is None and str((data.primary or {}).get("unit") or "") == "%":
        # Already a share of something; the card said so with its unit.
        ceiling = 100.0
    if ceiling is None:
        try:
            ceiling = float(options.get("gauge_max") or 0) or None
        except (TypeError, ValueError):
            ceiling = None
    if ceiling is None or ceiling <= 0 or not isinstance(value, (int, float)):
        return data
    named = named or bool(str(options.get("gauge_max") or "").strip())
    share = max(0.0, min(100.0, float(value) / ceiling * 100))
    # ⚠️ The number itself stays where it was. A dial that replaces
    # "38 MB/s" with "42%" answers a question nobody asked: the share is how
    # far round the needle goes, not what the card is for.
    dial: dict[str, Any] = {"share": round(share, 1)}
    if named:
        dial["max"] = ceiling
    data.meta = {**(data.meta or {}), "renderer": "gauge", "gauge": dial}
    return data


def timeline(
    *lines: tuple[str, str, list[tuple[float, float | None]]],
    unit: str = "",
    shape: str = "line",
) -> dict[str, Any]:
    """A history the card brings with it, rather than one nexdeck collected.

    ⚠️ The renderer's own series stop after 24 hours, because that is how long
    ``history.py`` keeps minute rows. A service that has kept months of its own
    can hand them over instead, and this is the shape it hands them in: one
    entry per line, each a list of ``(seconds since the epoch, value)``.

    A point whose value is ``None`` is a gap and is drawn as one. That is the
    same rule as everywhere else: a measurement that did not happen is not a
    zero, and a line that dips to the floor over a failed run would be a
    picture of an outage that never was.
    """
    return {
        "shape": shape if shape in ("line", "bars") else "line",
        "unit": unit,
        "lines": [
            {"key": key, "label": label,
             "points": [[float(at), None if value is None else float(value)] for at, value in points]}
            for key, label, points in lines
            if points
        ],
    }


def ring_of(*slices: tuple[str, Any]) -> list[dict[str, Any]]:
    """The pieces of one whole, in the order they should be drawn.

    ⚠️ A piece whose number is unknown is left out, not counted as nought.
    ``percent`` and ``measured`` were taught that in 0.2.0 and a ring is the
    same argument twice over: a missing slice makes every other slice bigger,
    so the drawing would be wrong rather than incomplete.
    """
    return [
        {"label": label, "value": float(value)}
        for label, value in slices
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) >= 0
    ]


def as_bars(data: WidgetData, options: dict[str, Any]) -> WidgetData:
    """Draw a list's rows as bars, when the rows carry numbers to compare.

    ⚠️ Refuses rather than draws nothing. Half the list cards carry a text
    where the number would be ("2.5 s", "3 days ago"), and a bar chart of
    those is a column of empty tracks that looks like the service stopped
    answering. Such a card stays a list, and the operator sees why: the rows
    are still there.
    """
    if str(options.get("view") or "value") != "bars":
        return data
    numbers = [
        float(row["value"]) for row in data.items
        if isinstance(row.get("value"), (int, float)) and not isinstance(row.get("value"), bool)
    ]
    # Two, because one bar is always full and says nothing about anything.
    if len(numbers) < 2 or max(numbers) <= 0:
        return data
    data.meta = {**(data.meta or {}), "renderer": "bars"}
    return data


def as_chart(data: WidgetData, options: dict[str, Any]) -> WidgetData:
    """Draw the card's own history instead of its number, when asked.

    ⚠️ Refuses while the card is measuring fewer than two things right now.
    The choice is offered because the widget *declares* two metrics, but an
    adapter reports what it found: a Docker host with nothing running reports
    one, and a chart of one line is the sparkline the card already had, minus
    the number it sat under.
    """
    if str(options.get("view") or "value") != "chart":
        return data
    if len(data.metrics) < 2:
        return data
    data.meta = {**(data.meta or {}), "renderer": "chart"}
    return data


def as_ring(data: WidgetData, options: dict[str, Any]) -> WidgetData:
    """Draw the slices the fetch worked out, when the card is asked to be one.

    ⚠️ The slices are never taken from ``secondary``. Those rows are whatever
    the card had room for, and adding them up gives a whole that does not
    exist: Pi-hole's are queries, blocked and clients, and blocked is already
    inside queries. Only the fetch knows the arithmetic, so only the fetch
    writes ``meta["ring"]``; a card that has not written one stays what it is.
    """
    if str(options.get("view") or "value") != "ring":
        return data
    slices = [
        piece for piece in ((data.meta or {}).get("ring") or [])
        if isinstance(piece, dict)
        and isinstance(piece.get("value"), (int, float))
        and not isinstance(piece.get("value"), bool)
        and float(piece["value"]) >= 0
    ]
    if len(slices) < 2 or sum(float(piece["value"]) for piece in slices) <= 0:
        return data
    data.meta = {**(data.meta or {}), "renderer": "ring", "ring": slices}
    return data


def shape_for_display(data: WidgetData, adapter: Adapter, widget_kind: str, options: dict[str, Any],
                      *, for_settings: bool = False) -> WidgetData:
    """Everything that happens to a card between the service and the screen.

    ⚠️ One function, because there are two ways to a card: the collector
    that refreshes it and the preview the settings sheet asks for. The passes
    hung on the collector alone, so switching a piece off changed nothing in
    the sheet until the page was reloaded, and building a card meant guessing
    and pressing F5.
    """
    try:
        widget = adapter.widget(widget_kind)
    except KeyError:
        return data
    data = keep_parts(data, widget.parts, options)
    data = keep_items(data, options, remember_all=for_settings)
    data = pick_gauge_row(data, options)
    data = as_bars(data, options)
    data = as_ring(data, options)
    data = as_chart(data, options)
    return as_gauge(data, options)


class AdapterError(Exception):
    """A readable failure: what went wrong, and what the operator can do."""

    def __init__(self, message: str, *, code: str = "adapter_error", hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


class AuthFailed(AdapterError):
    def __init__(self, message: str = "The service rejected the credentials.") -> None:
        super().__init__(message, code="auth_failed", hint="Check the API key or the password.")


class Unreachable(AdapterError):
    def __init__(self, message: str = "The service could not be reached.") -> None:
        super().__init__(message, code="unreachable", hint="Check the URL and the network.")


#: Addresses that answer only to the machine itself and hand out credentials.
#: 169.254.169.254 is the metadata service of AWS, Google, Azure, Hetzner and
#: DigitalOcean; fd00:ec2::254 is the same thing over IPv6. No card wants them,
#: and a widget option is enough to point the server at one.
FORBIDDEN_HOSTS = frozenset({
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.goog",
    "fd00:ec2::254",
    "[fd00:ec2::254]",
})


def _address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _is_link_local(host: str) -> bool:
    """169.254.0.0/16 and fe80::/10: never a service, on any installation."""
    parsed = _address(host)
    return parsed is not None and parsed.is_link_local


def _is_loopback(host: str) -> bool:
    """127.0.0.0/8, ::1, and the names that mean loopback by definition.

    ⚠️ Only literal addresses were read, so ``http://localhost:8000`` walked
    through the member rule until 12.09.2026. ``localhost`` and every name
    under it are loopback by RFC 6761 without asking any DNS, which keeps this
    free of the lookup ``guard_outbound`` explains it cannot afford.
    """
    name = host.strip("[]").rstrip(".").lower()
    if name == "localhost" or name.endswith(".localhost"):
        return True
    parsed = _address(host)
    return parsed is not None and parsed.is_loopback


def _barred_message(what: str) -> AdapterError:
    return AdapterError(
        f"{what} is not an address nexdeck calls.",
        code="forbidden_host",
        hint="Loopback and the link-local range are barred: the first is nexdeck itself and whatever else "
             "listens beside it, the second hands out the host's credentials on every cloud. "
             "NEXDECK_ALLOW_LOOPBACK_TARGETS=1 lifts it.",
    )


def guard_outbound(url: str) -> None:
    """Refuse an address that is never a service of the house.

    ⚠️ This used to compare the host against five spellings of the metadata
    address and nothing else, so ``127.0.0.1`` walked straight through. A
    notification channel takes an address from any member and reports the
    answer back, which made that field a way of asking what else listens next
    to the server.

    ⚠️ What this does **not** do is look up what a name points at.
    ``localtest.me`` resolves to 127.0.0.1 and gets through. Checking would
    mean a second name lookup in front of every single request, on top of the
    one the connection makes anyway. Measured on 07.09.2026: a name with a dot
    that does not exist costs about 50 ms, a bare name like ``radarr`` costs
    **2.7 s**, because Windows falls back to LLMNR and NetBIOS. A guard that
    puts seconds in front of every card is worse than the hole it closes, and
    the hole needs an attacker who already controls a DNS record.
    """

    split = urlsplit(url if "://" in url else f"http://{url}")
    if split.scheme not in ("http", "https"):
        raise AdapterError(
            f"nexdeck speaks http and https, not {split.scheme or 'that'}.",
            code="bad_scheme",
            hint="A service address starts with http:// or https://.",
        )
    host = (split.hostname or "").lower()
    if not host:
        raise AdapterError("That address names no host.", code="bad_url")
    if host.strip("[]") in {entry.strip("[]") for entry in FORBIDDEN_HOSTS}:
        raise _barred_message("That address")
    if _is_link_local(host):
        raise _barred_message(f"{host} ")


def guard_member_target(url: str) -> None:
    """The same, plus loopback, for an address a member typed in.

    ⚠️ Loopback is barred here and nowhere else, and the difference is who put
    the address there. An administrator pointing a connection at
    ``http://127.0.0.1:7878`` is an ordinary Radarr on a host-network install,
    and a test has said so since before this guard existed. A member typing
    the same thing into a notification channel is asking the server what else
    is listening beside it, and getting the answer back as an HTTP status.

    ``NEXDECK_ALLOW_LOOPBACK_TARGETS=1`` lifts it for the operator who really
    does run a notification service next to nexdeck.
    """
    from ..config import get_settings

    guard_outbound(url)
    if get_settings().allow_loopback_targets:
        return
    host = (urlsplit(url if "://" in url else f"http://{url}").hostname or "").lower()
    if _is_loopback(host):
        raise _barred_message(f"{host} ")


async def _guard_hook(request: Any) -> None:
    """Every request a shared client makes, redirects included."""
    guard_outbound(str(request.url))


async def _member_guard_hook(request: Any) -> None:
    """The same, with the member rule, for a client that follows an address a member typed."""
    guard_member_target(str(request.url))


def outbound_client(*, guard: bool = True, member: bool = False, keep_cookies: bool = False, **kwargs: Any) -> httpx.AsyncClient:
    """The only place an outbound client is built.

    ⚠️ The guard hangs on the client, not on the call, because httpx runs a
    request hook for every hop of a redirect as well. Checking only the address
    somebody typed leaves the second one open, and a service that answers 302
    decides where the third request goes. Measured with the pinned httpx: the
    hook sees both hops and an error inside it ends the request.

    ``member=True`` puts the member rule on every hop, loopback included. Where
    a member typed the first address, a redirect from a server of their own
    led on to 127.0.0.1: the address they typed was checked, the one it pointed
    at was not. Found on 12.09.2026.

    ``guard=False`` is for a client that does not speak to the network by name,
    which today is the Docker socket and nothing else.
    """
    if guard:
        hooks = dict(kwargs.pop("event_hooks", None) or {})
        hooks["request"] = [*hooks.get("request", []), _member_guard_hook if member else _guard_hook]
        kwargs["event_hooks"] = hooks
    if not keep_cookies:
        # ⚠️ No cookie jar unless a client asks for one. httpx keeps every
        # Set-Cookie, and the collector shares one client across every
        # connection, so a session cookie one connection's answer set went along
        # with the next request to the same host, whatever credentials that one
        # carried: on What's Up Docker a wrong password got in. A client built
        # for one connection that signs in with a cookie passes keep_cookies.
        from http.cookiejar import CookieJar, DefaultCookiePolicy

        kwargs.setdefault("cookies", CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])))
    # The only place in the code that may build one of these directly, which is
    # what the guard test in test_guards.py holds everyone else to.
    return httpx.AsyncClient(**kwargs)


_member_clients: dict[bool, httpx.AsyncClient] = {}


def member_client(verify: bool = True) -> httpx.AsyncClient:
    """One client per TLS mode for addresses a member typed, kept for the life of the process."""
    client = _member_clients.get(verify)
    if client is None or client.is_closed:
        client = outbound_client(member=True, verify=verify, follow_redirects=True)
        _member_clients[verify] = client
    return client


#: How many responses one integration may keep. Ten widgets on one service
#: with a handful of addresses each stay well under it.
MAX_CACHED_RESPONSES = 64
CACHE_PREFIX = "resp:"


_relaxed: httpx.AsyncClient | None = None


def _relaxed_client() -> httpx.AsyncClient:
    """One client for every call that was told to ignore TLS errors.

    ⚠️ This used to be ``async with outbound_client(verify=False)`` per call,
    so a service with a self-signed certificate paid a fresh TCP connection and
    a fresh handshake for every single request a card made. The verifying path
    has had a shared client from the start; this is the same thing for the
    other half.
    """
    global _relaxed
    if _relaxed is None or _relaxed.is_closed:
        _relaxed = outbound_client(verify=False, follow_redirects=True)
    return _relaxed


async def close_relaxed_client() -> None:
    global _relaxed
    if _relaxed is not None and not _relaxed.is_closed:
        await _relaxed.aclose()
    _relaxed = None


#: The largest answer a service may give a card.
#:
#: ⚠️ There was no ceiling. The whole body is read into memory and parsed, so a
#: service that answers with a hundred megabytes of JSON, or an address that
#: turns out to be a file server, took the process with it. Nothing a card
#: reads is anywhere near this: the largest measured answer in this codebase is
#: a Jellyfin library listing at a few megabytes.
MAX_ANSWER_BYTES = 32 * 1024 * 1024


def _refuse_a_giant_answer(url: str, response: httpx.Response) -> None:
    size = len(response.content)
    if size > MAX_ANSWER_BYTES:
        raise AdapterError(
            f"The service answered with {size // (1024 * 1024)} MB, which is more than a card reads.",
            code="answer_too_large",
            hint="Check that the address points at the service's API and not at a file.",
        )


class Context:
    """What an adapter gets besides its configuration.

    ``fetch_json`` caches GET responses for a few seconds per integration, so
    ten widgets on the same Radarr cause one request, not ten.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        integration_id: int | None = None,
        widget_id: int | None = None,
        cache: dict[str, Any] | None = None,
        resolve_integration: Any = None,
    ) -> None:
        self.client = client
        self.integration_id = integration_id
        self.widget_id = widget_id
        #: Per-integration memory for adapters (auth tickets, cookies, indexes).
        self.cache: dict[str, Any] = cache if cache is not None else {}
        #: ``async (integration_id) -> (adapter, config, Context)`` for widgets
        #: that combine several integrations, such as the calendar.
        self.resolve_integration = resolve_integration

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        content: bytes | None = None,
        timeout: float = 15.0,
        verify: bool = True,
        auth: tuple[str, str] | None = None,
        cache_seconds: float = 0,
        auth_errors: bool = True,
        member: bool = False,
    ) -> httpx.Response:
        """Fetch, with 401 and 403 turned into a readable refusal.

        ``auth_errors=False`` hands those two back as ordinary answers. Some
        services use 403 for something else entirely: GitHub uses it for the
        hourly limit, and "the service rejected the credentials" is wrong and
        unhelpful for a card that has no credentials at all.

        ``member=True`` is for an address a member typed into a card. It goes
        through a client with the member rule on every hop of a redirect, not
        through the shared one that serves the administrator's connections.
        """
        if member:
            guard_member_target(url)
        else:
            guard_outbound(url)
        key = ""
        if method.upper() == "GET" and cache_seconds > 0:
            key = CACHE_PREFIX + hashlib.sha1(
                json.dumps([url, params, headers], sort_keys=True, default=str).encode()
            ).hexdigest()
            hit = self.cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        try:
            if member:
                response = await member_client(verify).request(
                    method, url, headers=headers, params=params, json=json_body,
                    data=data, content=content, timeout=timeout, auth=auth,
                )
            elif verify:
                response = await self.client.request(
                    method, url, headers=headers, params=params, json=json_body,
                    data=data, content=content, timeout=timeout, auth=auth,
                )
            else:
                response = await _relaxed_client().request(
                    method, url, headers=headers, params=params, json=json_body,
                    data=data, content=content, timeout=timeout, auth=auth,
                )
        except httpx.TimeoutException as error:
            raise Unreachable("The service did not answer in time.") from error
        except httpx.HTTPError as error:
            raise Unreachable(f"The service could not be reached: {error.__class__.__name__}.") from error
        if auth_errors and response.status_code in (401, 403):
            raise AuthFailed()
        _refuse_a_giant_answer(url, response)
        if key:
            self._remember(key, time.monotonic() + cache_seconds, response)
        return response

    def forget_answers(self) -> None:
        """Drop every remembered answer of this connection, after something changed at the service.

        ⚠️ For writes a card makes itself. A playlist renamed a second ago must
        not come back under its old name for the two minutes its list is kept.
        """
        for name in [key for key in self.cache if key.startswith(CACHE_PREFIX)]:
            self.cache.pop(name, None)

    def _remember(self, key: str, until: float, response: httpx.Response) -> None:
        """Keep a response, and keep the cache from becoming the leak.

        ⚠️ Nothing used to remove an entry. An expired one was skipped on read
        and then sat there holding its whole body. Adapters whose address
        carries a date or a timestamp made a new key every time, so the cache
        only ever grew: a Plex history card wrote a few hundred megabytes a day
        into a dict nobody could reach.
        """
        now = time.monotonic()
        self.cache[key] = (until, response)
        stale = [name for name, entry in self.cache.items()
                 if name.startswith(CACHE_PREFIX) and isinstance(entry, tuple) and entry[0] <= now]
        for name in stale:
            self.cache.pop(name, None)
        kept = [name for name in self.cache if name.startswith(CACHE_PREFIX)]
        if len(kept) > MAX_CACHED_RESPONSES:
            # Oldest expiry first; the newest entries are the ones in use.
            for name in sorted(kept, key=lambda name: self.cache[name][0])[: len(kept) - MAX_CACHED_RESPONSES]:
                self.cache.pop(name, None)

    async def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 15.0,
        verify: bool = True,
        auth: tuple[str, str] | None = None,
        cache_seconds: float = 5,
    ) -> Any:
        response = await self.request(
            "GET", url, headers=headers, params=params, timeout=timeout, verify=verify,
            auth=auth, cache_seconds=cache_seconds,
        )
        if response.status_code >= 400:
            raise AdapterError(
                f"The service answered with HTTP {response.status_code}.",
                code="http_error",
                hint="Check the URL; the address may point at the wrong service.",
            )
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError(
                "The service did not answer with JSON.",
                code="not_json",
                hint="The URL probably points at a login page or a reverse proxy.",
            ) from error


def base_url(config: dict[str, Any], key: str = "url") -> str:
    """The configured URL without a trailing slash."""
    return str(config.get(key, "")).strip().rstrip("/")


@dataclass
class MediaSource:
    """An image or a live stream the server fetches from a service on a widget's behalf."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    #: How long the server may keep an image; 0 means every request goes to the service.
    cache_seconds: float = 3600
    media_type: str = ""


class Adapter:
    """Base class. Subclasses set the class attributes and override the hooks."""

    kind: str = ""
    label: str = ""
    category: str = "other"
    description: str = ""
    #: Icon name in dashboard-icons, e.g. ``radarr``.
    icon: str = ""
    #: True until someone confirms the adapter against a live instance.
    beta: bool = True
    docs_url: str = ""
    fields: tuple[Field, ...] = ()
    widgets: tuple[WidgetType, ...] = ()
    #: Adapters without a connection (clock, notes) set this to False.
    needs_integration: bool = True

    def widget(self, kind: str) -> WidgetType:
        for w in self.widgets:
            if w.kind == kind:
                return w
        raise KeyError(kind)

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    def image_headers(self, config: dict[str, Any]) -> dict[str, str]:
        """Headers for fetching a service's images (posters, thumbnails) through the server.

        Adapters put an image behind ``proxy:/path`` instead of a full address,
        so a token never travels into an image URL in the browser.
        """
        return {}

    async def image_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """Where an image behind ``proxy:/path`` really comes from.

        The default fetches the path from the service with ``image_headers`` and
        lets the server keep it for an hour. Adapters whose images need a
        session token or must stay fresh (camera snapshots) override this.
        """
        return MediaSource(url=f"{base_url(config)}{path}", headers=self.image_headers(config))

    async def stream_source(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> MediaSource:
        """Where a widget's live video comes from; only camera adapters have one."""
        raise AdapterError("This widget has no live stream.", code="no_stream")

    async def file_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """Where a file a row offers to save really comes from.

        Same shape as :meth:`image_source`, and the same reason: the server
        fetches with the service's credentials, so the browser never sees them
        and never has to reach the service at all. On a homelab where nexdeck
        is the only thing published, that is the difference between a link that
        works from outside and one that does not.
        """
        return MediaSource(url=f"{base_url(config)}{path}", headers=self.image_headers(config))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "icon": self.icon,
            "beta": self.beta,
            "docs_url": self.docs_url,
            "needs_integration": self.needs_integration,
            "fields": [f.to_dict() for f in self.fields],
            "widgets": [w.to_dict(self.kind) for w in self.widgets],
        }

    # -- hooks ---------------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        """Check the connection; return a short human-readable result."""
        raise NotImplementedError

    async def fetch(
        self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context
    ) -> WidgetData:
        raise NotImplementedError

    async def action(
        self,
        widget_kind: str,
        action_id: str,
        params: dict[str, Any],
        config: dict[str, Any],
        options: dict[str, Any],
        ctx: Context,
    ) -> str:
        raise AdapterError("This widget has no actions.", code="no_such_action")

    #: What a button card may ask this adapter to do. Empty for almost every
    #: adapter, and that is the point: see :class:`Deed`.
    deeds: tuple[Deed, ...] = ()

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        """What to offer in a field whose answers come from the service.

        ⚠️ Values, not guesses. A field like "which switch" cannot be written
        into the spec, because the answer lives on the console. Typing a name
        instead works until there are fourteen of them.

        Returns ``(value, label)`` pairs. An adapter that has no such field
        says so by returning nothing.

        ``deed`` is answered here for every adapter: it is the allowlist of
        actions a button may be pointed at, and it comes from the class rather
        than from the service.
        """
        if field == "deed":
            return [(one.id, one.label) for one in self.deeds]
        if field == "target":
            # What the one declared action acts on. ⚠️ Refuses rather than
            # guesses when there is more than one: the caller asked for "the
            # target" and two deeds have two different ones, so the day a
            # second deed appears this has to be told which, not left to pick.
            with_target = [one for one in self.deeds if one.target_field]
            if len(with_target) != 1:
                return []
            return await self.choices(with_target[0].target_field, config, ctx)
        return []

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        """The same list, for a connection that points nowhere.

        ⚠️ A demo connection has an address like ``demo.invalid``, so asking
        the service is asking nothing: the dropdown came back empty and said
        "this connection offers nothing", which is exactly what a demo Plex
        looks like from the outside and exactly not what it is. The demo data
        already contains the answer; this hands it over.
        """
        return []

    def deed(self, deed_id: str) -> Deed | None:
        """The declared action with this id, or nothing.

        ⚠️ The only way a button reaches an action. An id that is not in
        ``deeds`` is refused, whatever a card's saved options say, because the
        options are written by whoever may edit the board and the declaration
        is written here.
        """
        return next((one for one in self.deeds if one.id == deed_id), None)

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """What happened between the last fetch and this one.

        The collector holds both and asks after every successful fetch. Most
        adapters know of nothing; those that do put the knowledge here, where
        the service is understood, rather than in a rule the collector guesses
        at from the outside.
        """
        return []

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        raise NotImplementedError

    async def close(self, config: dict[str, Any], ctx: Context) -> None:
        """Hand back a session the adapter holds at the service; called when the server stops.

        Devices that count sessions (Reolink) fill up otherwise, one restart at a time.
        """
        return None

    def secret_field_names(self) -> set[str]:
        return {f.name for f in self.fields if f.secret}


async def hand_back(adapter: Adapter, config: dict[str, Any], ctx: Context) -> None:
    """Let an adapter log out of whatever ``ctx`` holds, briefly, and never fail what it follows.

    ⚠️ Everything that opens a context and lets it go has to come past here: the
    Test button, a dropdown asked of the service, a connection saved or deleted,
    the server stopping. On 11.09.2026 three of those simply dropped the
    context, and every press of Test cost a seat at a Reolink hub for an hour.
    """
    try:
        await asyncio.wait_for(adapter.close(config, ctx), timeout=3)
    except Exception:  # noqa: BLE001 - a goodbye that fails must not fail the answer it follows
        logger.debug("%s could not hand back its session.", adapter.kind)


# ---------------------------------------------------------------------------
# Small helpers shared by adapters
# ---------------------------------------------------------------------------


def human_bytes(value: float | int | None) -> str:
    if value is None:
        return "?"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def human_rate(bytes_per_second: float | None) -> str:
    if bytes_per_second is None:
        return "?"
    return human_bytes(bytes_per_second) + "/s"


def percent(part: float | None, whole: float | None) -> float | None:
    """A share of a whole, or ``None`` when there is nothing to divide by.

    ⚠️ This used to answer 0.0 to "I do not know", and it is the common root of
    a handful of cards that reported a healthy nothing: Nextcloud stood at 0
    percent used because the disk size was missing, the UPS card showed a
    charge of 0 percent because the UPS does not report one, and the UniFi
    statistics went into the history as a measured zero whenever the query
    failed. Zero is a number a service can genuinely report, so "unknown" has
    to be something else, and a card that does not know says so.
    """
    if not whole or part is None:
        return None
    return round(100.0 * float(part) / float(whole), 1)


def status_from_percent(value: float | None, warn: float = 80, bad: float = 95) -> Status:
    """A colour for a share. Nothing measured is nothing to colour green."""
    if value is None:
        return "unknown"
    if value >= bad:
        return "bad"
    if value >= warn:
        return "warn"
    return "ok"


def worst(*values: float | None) -> float | None:
    """The highest of the shares that are actually known.

    For the cards that colour themselves by whichever of CPU, memory and disk
    is worst. A missing one must not pull the answer down to zero, and all of
    them missing is not a zero either.
    """
    known = [value for value in values if value is not None]
    return max(known) if known else None


def percent_text(value: float | None, digits: int = 0) -> str:
    """A share for the eye: ``"73%"``, or ``"?"`` when nothing was measured."""
    return "?" if value is None else f"{value:.{digits}f}%"


def percent_primary(label: str, value: float | None) -> dict[str, Any]:
    """The big number of a card. Without a unit when there is no number: the
    frontend draws a dash for ``None`` and would otherwise put a "%" after it.
    """
    return {"label": label, "value": value, "unit": "%" if value is not None else ""}


def measured(values: dict[str, float | None]) -> dict[str, float]:
    """Only what was actually measured goes into the history.

    ⚠️ A failed query used to be written down as a zero, and a zero in the
    history is indistinguishable from a real one: the sparkline dips, the
    average drops, and nothing says the number was never taken.
    """
    return {name: value for name, value in values.items() if value is not None}


def duration_short(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def ago(moment: Any, now: float | None = None) -> str:
    """How long ago something happened: ``"12 min"``, ``"3 h"`` or ``"2 d"``.

    Takes an ISO time with ``Z`` or an offset, or seconds since the epoch, and
    answers ``""`` for anything it cannot read. A card then shows nothing
    rather than an age that is wrong. The words are units, not sentences, so
    they read the same in both languages.

    ``now`` in seconds since the epoch, for a card that works out other things
    against the same moment; a test that fixes it does not turn red the next day.
    """
    if moment is None or moment == "" or isinstance(moment, bool):
        return ""
    try:
        if isinstance(moment, int | float):
            when = datetime.fromtimestamp(float(moment), UTC)
        else:
            when = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return ""
    reference = datetime.fromtimestamp(now, UTC) if now is not None else datetime.now(UTC)
    seconds = max(0.0, (reference - when).total_seconds())
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h"
    return f"{int(seconds // 86400)} d"


@dataclass
class Series:
    """A tiny helper for adapters that build several list items."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, **item: Any) -> None:
        self.items.append(item)
