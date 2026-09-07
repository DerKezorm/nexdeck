"""The adapter contract.

An adapter knows one service: which connection fields it needs, which widgets
it offers, how to fetch their data, which actions it can run and what fake
data it produces in demo mode. Everything an adapter returns is a
``WidgetData``: a small, service-independent shape that the frontend renders
with a handful of renderers. That is what makes thirty integrations
maintainable by one person.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import time
from dataclasses import dataclass, field
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
                    "textarea", "timezone", "items", "choices", "colour"]
#: ``items`` picks among the rows a card is showing; ``choices`` picks among
#: values the service itself hands out, through ``Adapter.choices``.
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
    "stats": (3, 2),
    "feed": (3, 2),
    "calendar": (3, 2),
    "nowplaying": (3, 2),
    "weather": (3, 2),
    "posters": (3, 2),
    "chart": (3, 2),
    "log": (3, 2),
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


class Action(BaseModel):
    id: str
    label: str
    icon: str = ""
    confirm: bool = False
    danger: bool = False
    params: dict[str, Any] = PydanticField(default_factory=dict)


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


def outbound_client(*, guard: bool = True, **kwargs: Any) -> httpx.AsyncClient:
    """The only place an outbound client is built.

    ⚠️ The guard hangs on the client, not on the call, because httpx runs a
    request hook for every hop of a redirect as well. Checking only the address
    somebody typed leaves the second one open, and a service that answers 302
    decides where the third request goes. Measured with the pinned httpx: the
    hook sees both hops and an error inside it ends the request.

    ``guard=False`` is for a client that does not speak to the network by name,
    which today is the Docker socket and nothing else.
    """
    if guard:
        hooks = dict(kwargs.pop("event_hooks", None) or {})
        hooks["request"] = [*hooks.get("request", []), _guard_hook]
        kwargs["event_hooks"] = hooks
    # The only place in the code that may build one of these directly, which is
    # what the guard test in test_guards.py holds everyone else to.
    return httpx.AsyncClient(**kwargs)


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
    ) -> httpx.Response:
        """Fetch, with 401 and 403 turned into a readable refusal.

        ``auth_errors=False`` hands those two back as ordinary answers. Some
        services use 403 for something else entirely: GitHub uses it for the
        hourly limit, and "the service rejected the credentials" is wrong and
        unhelpful for a card that has no credentials at all.
        """
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
            if verify:
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

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        """What to offer in a field whose answers come from the service.

        ⚠️ Values, not guesses. A field like "which switch" cannot be written
        into the spec, because the answer lives on the console. Typing a name
        instead works until there are fourteen of them.

        Returns ``(value, label)`` pairs. An adapter that has no such field
        says so by returning nothing.
        """
        return []

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


@dataclass
class Series:
    """A tiny helper for adapters that build several list items."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, **item: Any) -> None:
        self.items.append(item)
