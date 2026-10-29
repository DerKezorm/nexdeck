"""A card written, changed or translated by the provider of "Ask nexdeck" (KARTEN-17, KARTEN-18).

⚠️ Everything that leaves for the provider is built in **one** place, :func:`outbound`, so a test can read it whole:
the schema of a card (shortened), the forms and blocks, the administrator's own words, the kind of connection, the paths
nexdeck's own cards read from that kind (from the code, not from this installation), the chosen path, and the **shape** of the service's answer: for every node its path, its type and, for a list, its length.
No values. A key that is data itself (a hash, a host name, a number) becomes ``<key>``. Values of the answer go only
with the administrator's tick for this one request, cut like the examples of a card (10 entries, 200 characters).
Never: the address or the name of the connection, a credential, a host name or an address of the network: even with the tick
the values of fields named like a credential and anything that reads as a key are replaced by ``***``, addresses of the network
by ``192.0.2.1``, host names and the host of an address by ``example.com``, mail addresses by ``user@example.com``
(:func:`sendable`).

The provider is the one of the assistant (``providers.turn``); a card has none of its own. Its answer is checked like a
saved card (``load.load_definition``: schema, secrets, paths, limits). A card that fails is sent back once with its
problems; one that fails again is shown with them and nothing is taken over.
"""

from __future__ import annotations

import asyncio
import json
import re
import types
import typing
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import BaseModel

from .. import credential_names
from ..services.assistant import providers
from . import card_reads, credentials, demo, load, schema
from .load import Problem

MODES = ("new", "change", "translate")
#: Seconds the provider has for one answer; a test sets it short.
TIMEOUT_SECONDS = 150.0
#: The languages a translation fills in.
LANGUAGES = ("en", "de", "es", "fr", "it")
#: Lines of the shape of an answer; the rest is counted.
MAX_SHAPE_LINES = 400
#: Fields of one object that are named; the rest is counted.
MAX_SHAPE_FIELDS = 40
MAX_SHAPE_DEPTH = 8
#: With the tick: entries of a list and characters of a text that go along.
VALUE_ENTRIES = 10
VALUE_CHARS = 200
#: Paths of one kind that go along: what nexdeck's own cards read from it.
MAX_KNOWN_PATHS = 30

MISSING: Any = object()

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
_ADDRESS = re.compile(r"\b(https?)://[^\s/?#\"'<>]*([^\s?#\"'<>]*)(?:[?#][^\s\"'<>]*)?", re.IGNORECASE)
_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w])")
#: What stands in the place of a credential that would have gone with the tick.
MASK = "***"
_FENCE = re.compile(r"```(?:ya?ml)?[ \t]*\r?\n(.*?)```", re.DOTALL)
_LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
#: Words with which a provider says that the account is at its limit or empty.
_LIMIT_WORDS = re.compile(r"(?i)\b(credit|balance|billing|quota|rate.?limit|limit|insufficient|exceeded|overloaded|capacity)\b")

FORMS = {
    "value": "one big number or text with a label (value:)",
    "stats": "two to six small figures side by side (stats: [..])",
    "list": "rows with a title, a subtitle, a value and a colour (rows:, item:)",
    "posters": "a wall of pictures with titles (rows:, item:)",
    "builder": "free layout put together from blocks (blocks:, optional main:, rows:)",
}
BLOCKS = {
    "row": "blocks side by side (children, gap, align, wrap)",
    "column": "blocks one under the other (children, gap)",
    "divider": "a thin line",
    "text": "a text, fixed (text) or from the answer (value)",
    "value": "a value like in a value card (label, unit, format, rules)",
    "badge": "a small coloured label (text or value, color)",
    "symbol": "a Lucide icon (icon, color, size)",
    "image": "a picture (src, height)",
    "progress": "a bar (value, max, color)",
    "sparkline": "the course of a number (value, id is required)",
    "list": "the same blocks for every row of rows: (item)",
    "button": "a button of the card's buttons: (button: id)",
}

EXAMPLE = """\
nexdeck-card: 1
slug: download-queue
name: {en: Download queue, de: Warteschlange}
version: 1.0.0
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: list
rows: {select: records, sort: {field: size, desc: true}, limit: 8}
empty: {en: Nothing waiting, de: Nichts wartet}
item:
  title: title
  subtitle: {template: "{series.title} S{seasonNumber}"}
  value: {path: size, format: bytes}
  status: [{op: ">", than: 5000000000, then: warn}]
rules:
  - {value: totalRecords, op: ">=", than: 20, then: warn}
"""

SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_card",
    "description": "Hand in the finished card. yaml is the whole card as YAML text, nothing else.",
    "input_schema": {"type": "object", "properties": {"yaml": {"type": "string", "description": "The whole card."}}, "required": ["yaml"], "additionalProperties": False},
}


class AiError(Exception):
    """The provider could not be used: ``ai_unreachable``, ``ai_limit``, ``ai_failed``, ``assistant_off`` or ``bad_request``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Busy(Exception):
    """This administrator has a request running already."""


@dataclass
class Ask:
    mode: str
    description: str = ""
    #: The text of the card, for ``change`` and ``translate``.
    yaml: str = ""
    #: The kind of the connection (``sonarr``); asked of the connection itself when there is one.
    connection_kind: str = ""
    path: str = ""
    #: What the service answered at ``path``; ``MISSING`` when nothing was asked.
    answer: Any = MISSING
    include_values: bool = False


@dataclass
class Outbound:
    """Everything that goes to the provider for one request."""

    system: str
    message: str
    tools: list[dict[str, Any]] = field(default_factory=lambda: [SUBMIT_TOOL])

    def everything(self) -> str:
        return "\n".join((self.system, self.message, json.dumps(self.tools)))


@dataclass
class Outcome:
    ok: bool
    yaml: str
    text: str
    problems: list[dict[str, Any]]
    summary: dict[str, Any]
    sent: dict[str, Any]
    definition: Any = None

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "yaml": self.yaml, "summary": self.summary, "sent": self.sent}
        if not self.ok:
            out["problems"] = self.problems
            out["text"] = self.text
        return out


# -- what goes out -------------------------------------------------------------------------------


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _is_a_name(key: str) -> bool:
    """A field name that reads as one; a hash, a host name, a token or a person as a key is data and stays out."""
    return bool(_NAME.match(key)) and demo.data_kind(key) is None and next(credentials.find(key), None) is None


def _credential_field(key: str) -> bool:
    return credential_names.is_credential_name(key) or credentials.bad_name(key)


def sendable(value: Any, *, secret: bool = False) -> Any:
    """A value as it may go with the tick: a credential, an address of the network or a host name never goes as it is.

    ``secret`` is set for the value of a field that is named like a credential (``apiKey``, ``password``).
    """
    if value is None or isinstance(value, bool):
        return value
    if secret:
        return MASK
    if not isinstance(value, str):
        return value
    if next(credentials.find(value), None) is not None:
        return MASK
    kind = demo.data_kind(value)
    if kind in ("ipv4", "ipv6"):
        return "192.0.2.1"
    if kind == "host":
        return "example.com"
    if kind == "mail":
        return "user@example.com"
    text = _ADDRESS.sub(lambda found: f"{found.group(1).lower()}://example.com{found.group(2)}", value)
    return _IPV4.sub("192.0.2.1", _MAIL.sub("user@example.com", text))


def _stand_ins(node: dict[Any, Any]) -> dict[Any, bool]:
    """Which keys of an object are data (a hash, a name with spaces, a key): they go as ``<key1>``, ``<key2>``."""
    return {key: not _is_a_name(str(key)) for key in node}


def shape(answer: Any, *, values: bool = False) -> str:
    """The answer of a service as lines ``path: type``, a list with its length, no values unless ``values``.

    Paths are JMESPath from the root (``@``). A list shows its first entry, which has the fields of all the others;
    with ``values``, ten entries and the values themselves (through :func:`sendable`). A key that is data
    is ``<key1>``: the first one stands for all of them, with ``values`` ten of them show.
    """
    lines: list[str] = []

    def walk(path: str, node: Any, depth: int, secret: bool) -> None:
        if len(lines) >= MAX_SHAPE_LINES:
            return
        kind = _type(node)
        line = f"{path or '@'}: {kind}"
        if isinstance(node, list):
            line += f" ({len(node)} entries)"
        elif isinstance(node, dict):
            line += f" ({len(node)} fields)"
        elif values and kind != "null":
            shown = sendable(node, secret=secret)
            line += " = " + json.dumps(shown[:VALUE_CHARS] if isinstance(shown, str) else shown, ensure_ascii=False)
        lines.append(line)
        if depth >= MAX_SHAPE_DEPTH:
            return
        if isinstance(node, list):
            for index, one in enumerate(node[: VALUE_ENTRIES if values else 1]):
                walk(f"{path}[{index}]", one, depth + 1, secret)
        elif isinstance(node, dict):
            stand_ins = 0
            for key, one in list(node.items())[:MAX_SHAPE_FIELDS]:
                name = str(key)
                if _is_a_name(name):
                    walk(f"{path}.{name}" if path else name, one, depth + 1, secret or _credential_field(name))
                else:
                    stand_ins += 1
                    if stand_ins <= (VALUE_ENTRIES if values else 1):  # the first of them shows what the others are
                        walk(f"{path}.<key{stand_ins}>" if path else f"<key{stand_ins}>", one, depth + 1, secret)
            if len(node) > MAX_SHAPE_FIELDS:
                lines.append(f"{path or '@'}: {len(node) - MAX_SHAPE_FIELDS} more fields not shown")

    walk("", answer, 0, False)
    if len(lines) >= MAX_SHAPE_LINES:
        lines.append("(more not shown)")
    return "\n".join(lines)


def clean(node: Any, *, secret: bool = False) -> Any:
    """A tree of values (the ``demo`` of a card) the way the tick sends it: :func:`sendable` for every value, keys that are data as ``<keyN>``."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        stand_ins = 0
        for key, one in node.items():
            name = str(key)
            if _is_a_name(name):
                out[name] = clean(one, secret=secret or _credential_field(name))
            else:
                stand_ins += 1
                out[f"<key{stand_ins}>"] = clean(one, secret=secret)
        return out
    if isinstance(node, list):
        return [clean(one, secret=secret) for one in node[:VALUE_ENTRIES]]
    shown = sendable(node, secret=secret)
    return shown[:VALUE_CHARS] if isinstance(shown, str) else shown


def _without(value: Any) -> Any:
    """The JSON schema without the words around it: what the provider needs to write a valid card."""
    if isinstance(value, dict):
        return {key: _without(one) for key, one in value.items() if key not in ("title", "description", "examples", "default")}
    if isinstance(value, list):
        return [_without(one) for one in value]
    return value


def _system() -> str:
    forms = "\n".join(f"- {name}: {what}" for name, what in FORMS.items())
    blocks = "\n".join(f"- {name}: {what}" for name, what in BLOCKS.items())
    return f"""You write cards for nexdeck, a self-hosted dashboard for a homelab. A card is one YAML document that says what to read from a service and how to show it.

Hand in the card with the tool submit_card (field yaml: the whole card), or answer with the card alone in a yaml code block. Nothing else counts.

Rules:
- Follow the schema below exactly; a field it does not list is an error. nexdeck checks every card and sends back what is wrong.
- A card only reads: requests are GET paths that start with a single / and are underneath the address of the connection. Never a host, an address or a port.
- A card holds no secrets: no key, password, token or login, not even as an example. The connection adds its own credentials.
- Paths into an answer are JMESPath (records[0].title, items[?active].name). Use only fields that the shape of the answer shows; never invent one.
- A request path must exist at the service that requires names: the path given below, or one of the paths listed for its kind. Never take a path from another service, not even one with a similar API. nexdeck asks the service, and a path it does not answer is sent back.
- Never guess a name only the administrator knows (a status page, a board, an entity id). If their words do not give it, write it as {{name}} in the path (/api/status-page/heartbeat/{{status_page}}); nexdeck then tells them to fill it in.
- A formula (formula:) is numbers, + - * /, brackets, comparisons and round(x, n), abs(x), min(a, b), max(a, b). Every value from the answer stands in braces as a JMESPath: "{{disk.used}} / {{disk.total}} * 100". A word without braces is an error.
- requires names the kind of the connection. slug is lower case letters, digits and hyphens. Start with nexdeck-card: 1 and version 1.0.0.
- Write texts in English unless the description asks for another language. Keep names and labels short.
- Leave out demo; nexdeck makes the examples itself.

Forms (form:):
{forms}

Blocks (type:, for form: builder):
{blocks}

An example of a valid card:
```yaml
{EXAMPLE}```

The schema of a card as JSON:
{json.dumps(_without(schema.json_schema()), separators=(",", ":"))}"""


def known_paths(kind: str) -> list[str]:
    """What nexdeck's own cards read from a kind: the real API of the service, from nexdeck's code, not from this installation."""
    return [read["path"] for read in card_reads.reads_of(kind)][:MAX_KNOWN_PATHS]


def _known(kind: str, paths: list[str]) -> str:
    lines = "\n".join(f"- {path}" for path in paths)
    return f"Paths nexdeck's own cards read from {kind} (its real API; read one of these unless the administrator names another):\n{lines}"


def _quoted(text: str) -> str:
    return f"```yaml\n{text.rstrip()}\n```"


def outbound(ask: Ask) -> Outbound:
    """The whole request to the provider; the one place that decides what leaves."""
    parts: list[str] = []
    if ask.mode == "new":
        parts.append("Write a new card as described.")
    elif ask.mode == "change":
        parts.append("Change the card below as described. Hand in the whole new card and keep its slug.")
    else:
        parts.append(
            "Translate the card below. Every text of it (name, description, label, unit, empty, text) becomes a mapping with all of "
            f"{', '.join(LANGUAGES)}. A text that is plain, without languages, is English: keep it as en. Keep the languages that are there "
            "word for word and change nothing else: not one other field, not a button, not a body, not an example."
        )
    if ask.description.strip():
        parts.append(f"The administrator says:\n{ask.description.strip()}")
    if ask.connection_kind:
        parts.append(f"Kind of the connection: {ask.connection_kind}")
        if ask.mode != "translate" and (known := known_paths(ask.connection_kind)):
            parts.append(_known(ask.connection_kind, known))
    if ask.path:
        parts.append(f"Path to read: {ask.path}")
    if ask.yaml.strip():
        parts.append(f"The card now:\n{_quoted(for_the_wire(ask.yaml, include_values=ask.include_values))}")
    if ask.answer is not MISSING and ask.mode != "translate":
        if ask.include_values:
            parts.append(f"The answer of the service at that path, with its values, as paths, types and values:\n{shape(ask.answer, values=True)}")
        else:
            parts.append(f"The shape of the answer of the service at that path, as paths and types (no values):\n{shape(ask.answer)}")
    return Outbound(_system(), "\n\n".join(parts))


# -- the demo block --------------------------------------------------------------------------------


def _dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False, width=10_000)


def _parsed(text: str) -> dict[str, Any]:
    try:
        return load.parse(text)[0]
    except load.CardInvalid:
        raise AiError("bad_request", "The card cannot be sent while its text cannot be read as YAML.") from None


def for_the_wire(text: str, *, include_values: bool) -> str:
    """The text of a card as it goes out: read as YAML, the top-level ``demo`` (the examples are values) taken away, the rest written again.

    ⚠️ Not a search for lines: a card may spell ``demo`` quoted, in a flow, on one line as JSON or with comments in the block.
    With the tick the examples go through the filter of :func:`clean` and stay.
    """
    data = _parsed(text)
    examples = data.pop("demo", None)
    if include_values and examples:
        data["demo"] = clean(examples)
    return _dump(data)


def with_demo(text: str, answers: dict[str, Any]) -> str:
    """The card with example answers (``request id -> answer``) under ``demo``."""
    return f"{text.rstrip()}\n{_dump({'demo': answers})}"


def restore_demo(ask: Ask, text: str) -> str:
    """The examples of the card come back as they were: they are the author's, not the provider's.

    A change keeps what the provider hands in only when it wrote examples of its own; those it was shown (the filtered ones of
    the tick) are the old ones again. A translation never takes examples from the answer.
    """
    try:
        old = load.parse(ask.yaml)[0]
        new = load.parse(text)[0]
    except load.CardInvalid:
        return text
    kept = old.get("demo")
    wrote = "demo" in new
    if wrote:
        if ask.mode == "change" and not (ask.include_values and kept and new["demo"] == clean(kept)):
            return text
        if ask.mode == "translate" and new["demo"] == kept:
            return text
        new.pop("demo")
    elif not kept:
        return text
    if not kept:
        return _dump(new)
    block = _dump({"demo": kept})
    for combined in ([] if wrote else [f"{text.rstrip()}\n{block}"]) + [f"{_dump(new)}{block}"]:
        try:
            load.load_definition(combined)
        except load.CardInvalid:
            continue
        return combined
    return text


# -- checking what comes back -----------------------------------------------------------------------


def _lang_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(isinstance(key, str) and _LANG.match(key) and isinstance(one, str) for key, one in value.items())


def _text_grew(old: Any, new: Any) -> bool:
    """A text may gain languages: a plain text stays as the English one, the languages that are there stay word for word."""
    if isinstance(old, str):
        return new == old if isinstance(new, str) else _lang_dict(new) and new.get("en") == old
    return isinstance(old, dict) and _lang_dict(new) and all(new.get(language) == text for language, text in old.items())


def _is_text(annotation: Any) -> bool:
    """Whether a field of the schema is a text of the author, one text or one per language (``str | dict[lang, str]``)."""
    origin = typing.get_origin(annotation)
    if origin is dict:
        return typing.get_args(annotation)[-1:] == (str,)
    if origin in (typing.Union, types.UnionType, typing.Annotated):
        return any(_is_text(one) for one in typing.get_args(annotation))
    return False


def _frame(node: Any, texts: list[Any], *, top: bool = False) -> Any:
    """A checked card without its texts (a mark in their place, the texts collected in order) and without the examples."""
    if isinstance(node, BaseModel):
        out: dict[str, Any] = {"@": type(node).__name__}
        for name, info in type(node).model_fields.items():
            if top and name == "demo":
                continue
            value = getattr(node, name)
            if _is_text(info.annotation) and isinstance(value, str | dict):
                texts.append(value)
                out[name] = "@text"
            else:
                out[name] = _frame(value, texts)
        return out
    if isinstance(node, list):
        return [_frame(one, texts) for one in node]
    if isinstance(node, dict):
        return {key: _frame(one, texts) for key, one in node.items()}
    return node


def same_but_texts(old: Any, new: Any) -> bool:
    """Whether the checked card ``new`` is ``old`` with more languages in the fields that are texts and nothing else different.

    ⚠️ The fields are those the schema types as a text, not every key that is called ``text`` or ``name``: the body of a button
    is what is sent to the service, and it is not translated.
    """
    before: list[Any] = []
    after: list[Any] = []
    return bool(_frame(old, before, top=True) == _frame(new, after, top=True)) and len(before) == len(after) and all(_text_grew(one, other) for one, other in zip(before, after, strict=True))


def _data(text: str) -> dict[str, Any]:
    data, _lines = load.parse(text)
    data.pop("demo", None)
    return data


def _problem(code: str, message: str, path: str = "") -> Problem:
    return Problem(code, message, path)


def _extra_problems(ask: Ask, text: str, loaded: Any) -> list[Problem]:
    found: list[Problem] = []
    definition = loaded.definition
    if ask.mode == "new" and ask.connection_kind and not any(kind == ask.connection_kind or kind.startswith("custom:") for kind in definition.requires):
        found.append(_problem("ai_wrong_kind", f"requires must name the kind of the connection, {ask.connection_kind}.", "requires"))
    if ask.mode in ("change", "translate"):
        try:
            old = _data(ask.yaml)
        except load.CardInvalid:
            return found
        if old.get("slug") != definition.slug:
            found.append(_problem("ai_slug_changed", f"The slug stays {old.get('slug')}.", "slug"))
        if ask.mode == "translate":
            try:
                before = load.load_definition(ask.yaml).definition
            except load.CardInvalid:
                return found
            if not same_but_texts(before, definition):
                found.append(_problem("ai_translate_changed", "Only languages may be added to the texts: a plain text stays as en, the languages that are there stay word for word, nothing else changes, no button, no body.", ""))
    return found


def check(ask: Ask, text: str) -> tuple[Any, list[Problem]]:
    """``(loaded, [])`` for a card that stands, ``(None, problems)`` for one that does not."""
    try:
        loaded = load.load_definition(text)
    except load.CardInvalid as failure:
        return None, list(failure.problems)
    problems = _extra_problems(ask, text, loaded)
    return (None, problems) if problems else (loaded, [])


def _feedback(problems: list[Problem], loaded: Any = None) -> str:
    lines = [f"- {problem.message}" + (f" (line {problem.line})" if problem.line else f" ({problem.path})" if problem.path else "") for problem in problems[:20]]
    text = "nexdeck did not accept this card. What is wrong:\n" + "\n".join(lines)
    # A path the service did not answer: the paths it does answer go along, for the kinds the card names.
    if loaded is not None and any(problem.code == PATH_FAILED for problem in problems):
        for kind in loaded.definition.requires:
            if known := known_paths(kind):
                text += "\n\n" + _known(kind, known)
    return text + "\nHand in the whole corrected card."


def candidate(turn: providers.Turn) -> str:
    """The card in an answer: the tool call, else a yaml block, else the whole text."""
    for call in turn.calls:
        if call.get("name") == "submit_card" and isinstance(call.get("input", {}).get("yaml"), str):
            return call["input"]["yaml"]
    found = _FENCE.search(turn.text)
    return found.group(1) if found else turn.text.strip()


# -- the provider ------------------------------------------------------------------------------------


def _failure(failure: providers.AssistantError) -> AiError:
    """A limit or an empty account keeps the provider's own words (KARTEN-17 EC-4)."""
    if failure.code == "off":
        return AiError("assistant_off", "The assistant is switched off.")
    if failure.code == "rate_limited" or (failure.detail and _LIMIT_WORDS.search(failure.detail)):
        return AiError("ai_limit", failure.detail or failure.message)
    if failure.code == "unreachable":
        return AiError("ai_unreachable", failure.message)
    return AiError("ai_failed", failure.detail and f"{failure.message} {failure.detail}" or failure.message)


async def _turn(config: dict[str, Any], key: str, system: str, transcript: list[dict[str, Any]], tools: list[dict[str, Any]]) -> providers.Turn:
    try:
        turn = await asyncio.wait_for(providers.turn(config, key, system, transcript, tools), TIMEOUT_SECONDS)
    except TimeoutError:
        raise AiError("ai_unreachable", "The provider did not answer in time.") from None
    except providers.AssistantError as failure:
        raise _failure(failure) from None
    if turn.stop == "refusal":
        raise AiError("ai_failed", "The provider declined to answer.")
    return turn


def summarize(loaded: Any) -> dict[str, Any]:
    """What the card that came back uses, for the editor to show beside the preview (KARTEN-17 AC-10).

    ⚠️ From the card, not from the request: the provider may have changed the connection, the paths or the buttons.
    ``connection_kind`` and ``path`` name all of them, one after the other.
    """
    definition = loaded.definition if loaded is not None else None
    if definition is None:
        return {"connection_kind": None, "path": None, "form": None, "buttons": False, "requires": [], "paths": [], "methods": []}
    requires = list(definition.requires)
    paths = [request.path for request in definition.requests]
    methods = sorted({button.method for button in definition.buttons})
    return {
        "connection_kind": ", ".join(requires) or None, "path": ", ".join(paths) or None, "form": definition.form, "buttons": bool(definition.buttons),
        "requires": requires, "paths": paths, "methods": methods,
    }


#: The problem of a request the service did not answer; ``params``: ``path`` and ``failure``, the code of the card's own error.
PATH_FAILED = "card_path_failed"


@dataclass
class Checked:
    """What the service said to the requests of a card: the problems of those it did not answer, the answers of the others by request id."""

    problems: list[Problem]
    answers: dict[str, Any] = field(default_factory=dict)


#: Asks the service every request of a card that passed the check.
Verify = Callable[[Any], Awaitable[Checked]]
#: Answers of the provider at most: the card, a second try with the problems, one with the shapes it had not seen.
TURNS = 3


def _shapes(ask: Ask, unseen: dict[str, Any]) -> str:
    """The shapes of answers the provider has not seen, the way :func:`outbound` sends a shape (values only with the tick)."""
    parts = [f"At {path} the service answered, as paths and types{' and values' if ask.include_values else ' (no values)'}:\n{shape(answer, values=ask.include_values)}"
             for path, answer in unseen.items()]
    return ("nexdeck asked the service. " + "\n\n".join(parts) + "\n\nEvery path into an answer (select, value, title, total, …) must exist in these "
            "shapes; fix the ones that do not. Hand in the whole card, unchanged if it is right.")


async def generate(ask: Ask, config: dict[str, Any], key: str, verify: Verify | None = None) -> Outcome:
    """Ask the provider for a card, check it, ask once more with the problems, and say how it went.

    With ``verify`` a card that passed the check is asked of the service too (not a translation, which keeps every path):
    a path the service does not answer is a problem like the others and goes back once, with the paths of its kind. A path
    whose answer the provider never saw (it chose the path itself) goes back once with the shape of that answer, so that
    the fields the card reads are the service's and not guessed (both found in a real run on 1.0.0).
    """
    if ask.mode not in MODES:
        raise AiError("bad_request", "Say whether to write a new card, change one or translate one.")
    if ask.mode == "translate":
        try:
            load.load_definition(ask.yaml)
        except load.CardInvalid:
            raise AiError("bad_request", "The card cannot be translated while its text has problems.") from None
    sent = {"values": ask.include_values}
    out = outbound(ask)
    transcript: list[dict[str, Any]] = [{"role": "user", "text": out.message}]
    text, last_text, problems = "", "", []
    # The paths whose answer the provider has seen; the problems go back once, the shapes once.
    seen = {ask.path} if ask.answer is not MISSING and ask.path else set()
    told, shown = False, False
    for _turn_number in range(TURNS):
        turn = await _turn(config, key, out.system, transcript, out.tools)
        text, last_text = candidate(turn), turn.text
        loaded, problems = check(ask, text)
        unseen: dict[str, Any] = {}
        if loaded is not None and verify is not None and ask.mode != "translate":
            checked = await verify(loaded.definition)
            problems = checked.problems
            unseen = {request.path: checked.answers[request.id] for request in loaded.definition.requests
                      if request.id in checked.answers and request.path not in seen}
        if loaded is not None and not problems and (shown or not unseen):
            card = text
            if ask.mode != "new":
                card = restore_demo(ask, text)
            return Outcome(True, card, last_text, [], summarize(loaded), sent, loaded.definition)
        if problems and told:
            break
        if problems:
            feedback, told = _feedback(problems, loaded), True
        else:
            feedback, shown = _shapes(ask, unseen), True
            seen |= set(unseen)
        transcript.append({"role": "assistant", "text": turn.text, "calls": turn.calls, "provider": config["provider"], "raw": turn.raw})
        if turn.calls:
            transcript.append({"role": "tool", "results": [{"id": call["id"], "content": feedback, "is_error": bool(problems)} for call in turn.calls]})
        else:
            transcript.append({"role": "user", "text": feedback})
    return Outcome(False, text, last_text, [problem.as_dict() for problem in problems], summarize(None), sent)


# -- one request at a time per administrator -----------------------------------------------------------

RUNNING: dict[int, asyncio.Task[Any]] = {}


async def supervised(user_id: int, work: Coroutine[Any, Any, Any]) -> tuple[bool, Any]:
    """Run ``work`` as the one request of this administrator: ``(finished, result)``, ``(False, None)`` when it was cancelled.

    Raises :class:`Busy` when one is running already. What the work raises comes out unchanged.
    """
    if user_id in RUNNING:
        work.close()
        raise Busy
    task = asyncio.ensure_future(work)
    RUNNING[user_id] = task
    try:
        await asyncio.wait({task})
    finally:
        if RUNNING.get(user_id) is task:
            del RUNNING[user_id]
        if not task.done():
            task.cancel()  # the caller went away
    if task.cancelled():
        return False, None
    return True, task.result()


def cancel(user_id: int) -> bool:
    """End the request of this administrator. The routes call it from a worker thread, the task lives on the loop: ask the loop to do it."""
    task = RUNNING.get(user_id)
    if task is None or task.done():
        return False
    try:
        task.get_loop().call_soon_threadsafe(task.cancel)
    except RuntimeError:  # the loop is closed, nothing is waiting any more
        return False
    return True


def cancel_all() -> int:
    """The provider was taken away: every request that waits for it ends (KARTEN-17 EC-6)."""
    return sum(cancel(user) for user in list(RUNNING))
