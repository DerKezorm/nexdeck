"""A card written, changed or translated by the provider of "Ask nexdeck" (KARTEN-17, KARTEN-18).

⚠️ Everything that leaves for the provider is built in **one** place, :func:`outbound`, so a test can read it whole:
the schema of a card (shortened), the forms and blocks, the administrator's own words, the kind of connection and the
chosen path, and the **shape** of the service's answer: for every node its path, its type and, for a list, its length.
No values. A key that is data itself (a hash, a host name, a number) becomes ``<key>``. Values of the answer go only
with the administrator's tick for this one request, cut like the examples of a card (10 entries, 200 characters).
Never: the address or the name of the connection, a credential, a host name or an address of the network.

The provider is the one of the assistant (``providers.turn``); a card has none of its own. Its answer is checked like a
saved card (``load.load_definition``: schema, secrets, paths, limits). A card that fails is sent back once with its
problems; one that fails again is shown with them and nothing is taken over.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

import yaml

from ..services.assistant import providers
from . import demo, load, schema
from .load import Problem

MODES = ("new", "change", "translate")
#: Seconds the provider has for one answer; a test sets it short.
TIMEOUT_SECONDS = 150.0
#: The languages a translation fills in.
LANGUAGES = ("en", "de", "es", "fr", "it")
#: The fields that hold a text of the author, which may be one text or one per language.
TEXT_KEYS = frozenset({"name", "description", "label", "unit", "empty", "text"})
#: Lines of the shape of an answer; the rest is counted.
MAX_SHAPE_LINES = 400
#: Fields of one object that are named; the rest is counted.
MAX_SHAPE_FIELDS = 40
MAX_SHAPE_DEPTH = 8
#: With the tick: entries of a list and characters of a text that go along.
VALUE_ENTRIES = 10
VALUE_CHARS = 200

MISSING: Any = object()

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
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
    """A field name that reads as one; a hash, a number, a host name or a token as a key is data and stays out."""
    return bool(_NAME.match(key)) and demo.data_kind(key) is None


def shape(answer: Any, *, values: bool = False) -> str:
    """The answer of a service as lines ``path: type``, a list with its length, no values unless ``values``.

    Paths are JMESPath from the root (``@``). A list shows its first entry, which has the fields of all the others;
    with ``values``, ten entries and the values themselves.
    """
    lines: list[str] = []

    def walk(path: str, node: Any, depth: int) -> None:
        if len(lines) >= MAX_SHAPE_LINES:
            return
        kind = _type(node)
        line = f"{path or '@'}: {kind}"
        if isinstance(node, list):
            line += f" ({len(node)} entries)"
        elif isinstance(node, dict):
            line += f" ({len(node)} fields)"
        elif values and kind != "null":
            line += " = " + json.dumps(node[:VALUE_CHARS] if isinstance(node, str) else node, ensure_ascii=False)
        lines.append(line)
        if depth >= MAX_SHAPE_DEPTH:
            return
        if isinstance(node, list):
            for index, one in enumerate(node[: VALUE_ENTRIES if values else 1]):
                walk(f"{path}[{index}]", one, depth + 1)
        elif isinstance(node, dict):
            stand_in = False
            for key, one in list(node.items())[:MAX_SHAPE_FIELDS]:
                name = str(key)
                if _is_a_name(name):
                    walk(f"{path}.{name}" if path else name, one, depth + 1)
                elif not stand_in:
                    stand_in = True  # the first of them shows what the others are
                    walk(f"{path}.<key>" if path else "<key>", one, depth + 1)
            if len(node) > MAX_SHAPE_FIELDS:
                lines.append(f"{path or '@'}: {len(node) - MAX_SHAPE_FIELDS} more fields not shown")

    walk("", answer, 0)
    if len(lines) >= MAX_SHAPE_LINES:
        lines.append("(more not shown)")
    return "\n".join(lines)


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
            f"{', '.join(LANGUAGES)}. Keep the languages that are there word for word and change nothing else: not one other field."
        )
    if ask.description.strip():
        parts.append(f"The administrator says:\n{ask.description.strip()}")
    if ask.connection_kind:
        parts.append(f"Kind of the connection: {ask.connection_kind}")
    if ask.path:
        parts.append(f"Path to read: {ask.path}")
    if ask.yaml.strip():
        text, _removed = without_demo(ask.yaml) if not ask.include_values else (ask.yaml, "")
        parts.append(f"The card now:\n{_quoted(text)}")
    if ask.answer is not MISSING and ask.mode != "translate":
        if ask.include_values:
            parts.append(f"The answer of the service at that path, with its values, as paths, types and values:\n{shape(ask.answer, values=True)}")
        else:
            parts.append(f"The shape of the answer of the service at that path, as paths and types (no values):\n{shape(ask.answer)}")
    return Outbound(_system(), "\n\n".join(parts))


# -- the demo block --------------------------------------------------------------------------------


def without_demo(text: str) -> tuple[str, str]:
    """The text of a card without its top-level ``demo`` block, and that block: the examples are values."""
    kept: list[str] = []
    removed: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        if re.match(r"^demo\s*:", line):
            inside = True
        elif inside and line.strip() and line[0] not in " \t-":
            inside = False
        (removed if inside else kept).append(line)
    return "".join(kept), "".join(removed)


def with_demo(text: str, answers: dict[str, Any]) -> str:
    """The card with example answers (``request id -> answer``) under ``demo``."""
    block = yaml.safe_dump({"demo": answers}, allow_unicode=True, default_flow_style=False, sort_keys=False, width=10_000)
    return f"{text.rstrip()}\n{block}"


# -- checking what comes back -----------------------------------------------------------------------


def _lang_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(isinstance(key, str) and _LANG.match(key) and isinstance(one, str) for key, one in value.items())


def _text_grew(old: Any, new: Any) -> bool:
    if isinstance(new, str):
        return old == new
    if isinstance(old, str):
        return old in new.values()
    return all(new.get(key) == one for key, one in old.items())


def same_but_texts(old: Any, new: Any, key: str = "") -> bool:
    """Whether ``new`` is ``old`` with more languages in its texts and nothing else different."""
    if key in TEXT_KEYS and (isinstance(old, str) or _lang_dict(old)) and (isinstance(new, str) or _lang_dict(new)):
        return _text_grew(old, new)
    if isinstance(old, dict):
        return isinstance(new, dict) and old.keys() == new.keys() and all(same_but_texts(one, new[name], str(name)) for name, one in old.items())
    if isinstance(old, list):
        return isinstance(new, list) and len(old) == len(new) and all(same_but_texts(one, other) for one, other in zip(old, new, strict=True))
    return bool(old == new) and type(old) is type(new)


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
        if ask.mode == "translate" and not same_but_texts(old, _data(text)):
            found.append(_problem("ai_translate_changed", "Only the languages of the texts may be added; something else was changed.", ""))
    return found


def check(ask: Ask, text: str) -> tuple[Any, list[Problem]]:
    """``(loaded, [])`` for a card that stands, ``(None, problems)`` for one that does not."""
    try:
        loaded = load.load_definition(text)
    except load.CardInvalid as failure:
        return None, list(failure.problems)
    problems = _extra_problems(ask, text, loaded)
    return (None, problems) if problems else (loaded, [])


def _feedback(problems: list[Problem]) -> str:
    lines = [f"- {problem.message}" + (f" (line {problem.line})" if problem.line else f" ({problem.path})" if problem.path else "") for problem in problems[:20]]
    return "nexdeck did not accept this card. What is wrong:\n" + "\n".join(lines) + "\nHand in the whole corrected card."


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


def summarize(ask: Ask, loaded: Any, text: str = "") -> dict[str, Any]:
    """What the card uses, for the editor to show beside the preview (KARTEN-17 AC-10)."""
    definition = loaded.definition if loaded is not None else None
    kind = ask.connection_kind or (definition.requires[0] if definition is not None else "")
    path = ask.path or (definition.requests[0].path if definition is not None else "")
    return {"connection_kind": kind, "path": path, "form": definition.form if definition is not None else None, "buttons": bool(definition.buttons) if definition is not None else False}


async def generate(ask: Ask, config: dict[str, Any], key: str) -> Outcome:
    """Ask the provider for a card, check it, ask once more with the problems, and say how it went."""
    if ask.mode not in MODES:
        raise AiError("bad_request", "Say whether to write a new card, change one or translate one.")
    if ask.mode == "translate":
        try:
            _data(ask.yaml)
        except load.CardInvalid:
            raise AiError("bad_request", "The card cannot be translated while its text has problems.") from None
    sent = {"values": ask.include_values}
    out = outbound(ask)
    transcript: list[dict[str, Any]] = [{"role": "user", "text": out.message}]
    text, last_text, problems = "", "", []
    for attempt in range(2):
        turn = await _turn(config, key, out.system, transcript, out.tools)
        text, last_text = candidate(turn), turn.text
        loaded, problems = check(ask, text)
        if loaded is not None:
            card = text
            if ask.mode != "new" and not ask.include_values:
                card = _restore_demo(ask, text)
            return Outcome(True, card, last_text, [], summarize(ask, loaded), sent, loaded.definition)
        if attempt == 0:
            transcript.append({"role": "assistant", "text": turn.text, "calls": turn.calls, "provider": config["provider"], "raw": turn.raw})
            feedback = _feedback(problems)
            if turn.calls:
                transcript.append({"role": "tool", "results": [{"id": call["id"], "content": feedback, "is_error": True} for call in turn.calls]})
            else:
                transcript.append({"role": "user", "text": feedback})
    return Outcome(False, text, last_text, [problem.as_dict() for problem in problems], summarize(ask, None), sent)


def _restore_demo(ask: Ask, text: str) -> str:
    """The examples that were not sent come back as they were, when they still fit the new card."""
    _kept, removed = without_demo(ask.yaml)
    if not removed.strip() or re.search(r"(?m)^demo\s*:", text):
        return text
    both = f"{text.rstrip()}\n{removed}"
    try:
        load.load_definition(both)
    except load.CardInvalid:
        return text
    return both


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
    task = RUNNING.get(user_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def cancel_all() -> int:
    """The provider was taken away: every request that waits for it ends (KARTEN-17 EC-6)."""
    ended = [user for user in RUNNING if cancel(user)]
    return len(ended)
