"""From YAML text to a checked card definition.

The text is read, checked against ``schema`` and then against what a schema
cannot say (the version of nexdeck, the kinds of connection that exist, whether
every path can be read). Whoever saves a card gets every problem at once, each
with the place in the text (the line, and the field) and the reason.

The text itself is what gets stored, comment for comment (KARTEN-1 AC-9); this
module only reads it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from .. import __version__
from . import blocks, buttons, credentials, schema

Path = tuple[str | int, ...]


@dataclass(frozen=True)
class Problem:
    """One thing wrong. ``message`` is English; the interface translates ``code`` and fills in ``params``."""

    code: str
    message: str
    path: str = ""
    line: int | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "path": self.path, "line": self.line, "params": self.params}


class CardInvalid(ValueError):
    """A definition that is not saved, with everything that is wrong with it."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        first = problems[0]
        where = f" (line {first.line})" if first.line else (f" ({first.path})" if first.path else "")
        super().__init__(f"{first.message}{where}")

    def detail(self) -> dict[str, Any]:
        """The body of an error answer: the first problem as the headline, all of them as a list."""
        first = self.problems[0]
        return {"code": "card_invalid", "message": str(self), "problems": [problem.as_dict() for problem in self.problems], "first": first.code}


@dataclass(frozen=True)
class Loaded:
    definition: Any
    #: The definition as plain JSON, in the format of this nexdeck (what the table keeps beside the text).
    data: dict[str, Any]
    #: The format the text was written in; lower than ``schema.FORMAT_VERSION`` when it was carried over.
    source_format: int
    text: str
    #: The line of every place in the text, for messages about the saved card that come later (a name already taken).
    lines: dict[Path, int] = field(default_factory=dict, repr=False)


#: One step each: the definition in format ``n`` becomes the one in format ``n + 1``. Nothing to carry over yet.
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


# -- reading YAML --------------------------------------------------------------


class _Loader(yaml.SafeLoader):
    """A YAML reader for cards.

    ⚠️ Three things differ from ``yaml.safe_load``, each of them because a card is written by hand and shared.
    No anchors and no aliases: they let a short text expand into a huge one, and nobody needs them for a card.
    ``no``, ``on`` and ``off`` are text, not booleans, or the language ``no`` (Norwegian) would be the key ``False``.
    And a date is text: a version or a name that looks like one must come out as typed.
    """

    def compose_node(self, parent: Node | None, index: Any) -> Node | None:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(None, None, "anchors and aliases are not allowed in a card", event.start_mark)
        event = self.peek_event()
        if getattr(event, "anchor", None) is not None:
            raise yaml.constructor.ConstructorError(None, None, "anchors and aliases are not allowed in a card", event.start_mark)
        return super().compose_node(parent, index)  # type: ignore[no-any-return]


def _resolvers() -> dict[str, list[tuple[str, re.Pattern[str]]]]:
    dropped = {"tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:merge", "tag:yaml.org,2002:value", "tag:yaml.org,2002:bool"}
    table = {
        first: [(tag, pattern) for tag, pattern in entries if tag not in dropped]
        for first, entries in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    plain_bool = re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$")
    for first in "tTfF":
        table.setdefault(first, []).append(("tag:yaml.org,2002:bool", plain_bool))
    return table


_Loader.yaml_implicit_resolvers = _resolvers()


def _key_name(path: Path) -> str:
    """``requests[0].path``: how a place in the definition is written."""
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


@dataclass
class _Walk:
    lines: dict[Path, int] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)


def _walk(node: Node, path: Path, found: _Walk) -> None:
    found.lines.setdefault(path, node.start_mark.line + 1)
    if isinstance(node, MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            line = key_node.start_mark.line + 1
            if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                found.problems.append(Problem("card_key_not_text", "A field name must be text.", _key_name(path), line))
                continue
            key = key_node.value
            if key in seen:
                found.problems.append(Problem("card_duplicate_key", f"The field {key} stands twice.", _key_name((*path, key)), line, {"field": key}))
            seen.add(key)
            found.lines[(*path, key)] = line
            _walk(value_node, (*path, key), found)
    elif isinstance(node, SequenceNode):
        for index, child in enumerate(node.value):
            _walk(child, (*path, index), found)


def parse(text: str, limit: int = schema.MAX_DEFINITION) -> tuple[dict[str, Any], dict[Path, int]]:
    """The data of a text and the line of every place in it. Raises ``CardInvalid``."""
    if len(text) > limit:
        raise CardInvalid(
            [
                Problem(
                    "card_definition_too_long",
                    f"The definition is {len(text)} characters long, the limit is {limit}.",
                    params={"length": len(text), "limit": limit},
                )
            ]
        )
    loader = _Loader(text)
    try:
        try:
            node = loader.get_single_node()
            if node is None:
                raise CardInvalid([Problem("card_empty", "The definition is empty.")])
            found = _Walk()
            _walk(node, (), found)
            if found.problems:
                raise CardInvalid(found.problems)
            data = loader.construct_document(node)
        finally:
            loader.dispose()
    except yaml.MarkedYAMLError as failure:
        mark = failure.problem_mark or failure.context_mark
        reason = (failure.problem or failure.context or "the text is not valid YAML").strip()
        line = mark.line + 1 if mark else None
        raise CardInvalid([Problem("card_yaml", f"The YAML cannot be read: {reason}.", "", line, {"reason": reason})]) from failure
    except RecursionError as failure:
        raise CardInvalid([Problem("card_too_deep", "The definition is nested too deeply.")]) from failure
    except CardInvalid:
        raise
    except ValueError as failure:
        # ⚠️ A whole number of more than 4300 digits is refused by Python itself with a ValueError, which was a 500.
        reason = "a number in the definition has too many digits"
        raise CardInvalid([Problem("card_yaml", f"The YAML cannot be read: {reason}.", params={"reason": reason})]) from failure
    except yaml.YAMLError as failure:
        raise CardInvalid([Problem("card_yaml", "The YAML cannot be read.", params={"reason": str(failure)})]) from failure
    if not isinstance(data, dict):
        raise CardInvalid([Problem("card_not_a_mapping", "A card is a list of fields, each written name: value.", line=1)])
    return data, found.lines


def _line(lines: dict[Path, int], path: Path) -> int | None:
    """The line of the place, or of the nearest place above it that the text has."""
    for cut in range(len(path), -1, -1):
        if path[:cut] in lines:
            return lines[path[:cut]]
    return None


# -- the format ---------------------------------------------------------------


def _format_of(data: dict[str, Any], lines: dict[Path, int]) -> int:
    value = data.get("nexdeck-card")
    if value is None:
        raise CardInvalid([Problem("card_missing_field", "This field is required.", "nexdeck-card", 1, {"field": "nexdeck-card"})])
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CardInvalid(
            [Problem("card_wrong_type", "nexdeck-card must be a whole number such as 1.", "nexdeck-card", _line(lines, ("nexdeck-card",)), {"expected": "whole_number"})]
        )
    if value > schema.FORMAT_VERSION:
        raise CardInvalid(
            [
                Problem(
                    "card_needs_newer_format",
                    f"This card is written in format {value} and needs a newer nexdeck; this one reads up to format {schema.FORMAT_VERSION}.",
                    "nexdeck-card",
                    _line(lines, ("nexdeck-card",)),
                    {"format": value, "known": schema.FORMAT_VERSION},
                )
            ]
        )
    return value


def _carry_over(data: dict[str, Any], version: int) -> dict[str, Any]:
    while version < schema.FORMAT_VERSION:
        data = UPGRADES[version](data)
        version += 1
    return data


# -- what the schema says ---------------------------------------------------------


#: What a place wants, by code; the interface translates the code.
EXPECTED = {
    "text": "text",
    "whole_number": "a whole number",
    "boolean": "true or false",
    "mapping": "a mapping",
    "list": "a list",
    "other": "another kind of value",
}
_KINDS = frozenset({"str", "int", "float", "bool", "dict", "list", "none", "constrained-str"})


def _without_block_tags(path: Path) -> Path:
    """``blocks[0].row.children[1]`` is ``blocks[0].children[1]``: the name of the kind of a block is no field of the text."""
    kept: list[str | int] = []
    for index, part in enumerate(path):
        if isinstance(part, str) and part in blocks.KINDS and index >= 2 and isinstance(path[index - 1], int) and path[index - 2] in ("blocks", "children", "item"):
            continue
        kept.append(part)
    return tuple(kept)


def _from_pydantic(error: Any, lines: dict[Path, int]) -> Problem:
    kind: str = error["type"]
    loc = tuple(error["loc"])
    # The first place names the form that was chosen (value, stats, list, posters, builder), which is not a field.
    # A block that is none of the twelve is a fault of that block, not of the form.
    a_block = kind == "union_tag_invalid" and len(loc) > 1 and loc[0] == "builder"
    path: Path = loc[1:] if loc and loc[0] in ("value", "stats", "list", "posters", "builder") and (kind != "union_tag_invalid" or a_block) else loc
    path = _without_block_tags(path)
    # A value that may be one of several kinds names the kind it failed as (``name.str``); that is not a place either.
    path = tuple(part for part in path if not (isinstance(part, str) and (part in _KINDS or "[" in part or "(" in part)))
    if kind == "union_tag_invalid" and not a_block:
        path = ("form",)
    context = error.get("ctx") or {}
    name = str(path[-1]) if path else ""
    line = _line(lines, path)
    where = _key_name(path)
    if kind.startswith("card_"):
        return Problem(kind, error["msg"], where, line, {k: v for k, v in context.items() if isinstance(v, str | int | float | bool)})
    if kind == "missing":
        return Problem("card_missing_field", f"The field {name} is required.", where, line, {"field": name})
    if kind == "extra_forbidden":
        return Problem("card_unknown_field", f"{name} is not a field of a card here.", where, line, {"field": name})
    if kind == "string_too_long":
        length, limit = len(str(error.get("input", ""))), context.get("max_length")
        return Problem("card_too_long", f"This is {length} characters long, the limit is {limit}.", where, line, {"length": length, "limit": limit})
    if kind in ("string_too_short", "too_short"):
        minimum = context.get("min_length", context.get("field_type"))
        return Problem("card_too_few", f"This needs at least {minimum} item(s) or characters.", where, line, {"minimum": minimum})
    if kind == "too_long":
        limit = context.get("max_length")
        return Problem("card_too_many", f"There can be at most {limit} here.", where, line, {"limit": limit})
    if kind == "string_pattern_mismatch":
        if path == ("slug",):
            return Problem(
                "card_bad_slug",
                "The short name may only have lower case letters, digits and hyphens, and starts with a letter or digit.",
                where,
                line,
            )
        return Problem("card_bad_form", f"This is not written the way it must be: {context.get('pattern')}.", where, line, {"pattern": str(context.get("pattern"))})
    if kind == "literal_error":
        expected = str(context.get("expected", ""))
        return Problem("card_not_allowed", f"This must be one of {expected}.", where, line, {"expected": expected})
    if kind == "union_tag_invalid":
        if a_block:
            expected = ", ".join(blocks.KINDS)
            return Problem("card_bad_block", f"type must be one of {expected}.", where, line, {"expected": expected})
        expected = "value, stats, list, posters, builder"
        return Problem("card_bad_form", f"form must be one of {expected}.", where, line, {"expected": expected})
    if kind in ("greater_than_equal", "less_than_equal", "greater_than", "less_than"):
        bound = next(iter(context.values()), "")
        return Problem("card_out_of_range", f"This is outside what is allowed ({bound}).", where, line, {"bound": bound})
    if kind.endswith("_type") or kind in ("model_type", "dict_type", "list_type"):
        expected = {"str": "text", "int": "whole_number", "bool": "boolean", "model": "mapping", "dict": "mapping", "list": "list"}.get(kind.split("_")[0], "other")
        return Problem("card_wrong_type", f"Expected {EXPECTED[expected]} here.", where, line, {"expected": expected})
    return Problem("card_invalid_value", error["msg"], where, line, {"reason": error["msg"]})


# -- what a schema cannot say -----------------------------------------------------


def version_tuple(text: str) -> tuple[int, int, int]:
    parts = [int(part) for part in text.split(".")][:3]
    return (*parts, *([0] * (3 - len(parts))))  # type: ignore[return-value]


def needs_newer(minimum: str | None, running: str = __version__) -> bool:
    return minimum is not None and version_tuple(minimum) > version_tuple(running)


def _semantic(definition: Any, lines: dict[Path, int], running: str) -> list[Problem]:
    from ..adapters import get_adapter
    from . import pipeline

    problems: list[Problem] = []

    def add(code: str, message: str, path: Path, **params: Any) -> None:
        problems.append(Problem(code, message, _key_name(path), _line(lines, path), params))

    if needs_newer(definition.min_nexdeck, running):
        add(
            "card_needs_newer",
            f"This card needs nexdeck {definition.min_nexdeck} or newer; this is {running}.",
            ("min_nexdeck",),
            need=definition.min_nexdeck,
            have=running,
        )
    for index, kind in enumerate(definition.requires):
        if kind.startswith("custom:"):
            continue
        try:
            get_adapter(kind)
        except KeyError:
            add("card_unknown_kind", f"nexdeck has no connection of the kind {kind}.", ("requires", index), kind=kind)
    ids = {request.id for request in definition.requests}
    for key in definition.demo:
        if key not in ids:
            add("card_demo_unknown_request", f"The demo answer {key} belongs to no request.", ("demo", key), id=key)
    for index, rule in enumerate(definition.rules):
        if rule.value is None and rule.formula is None:
            add("card_rule_subject", "A rule on the card has to say what it looks at: a value or a formula.", ("rules", index))
    for path, shown in _pictures(definition):
        if shown.formula is not None or (shown.template is not None and not (shown.template.startswith("/") and not shown.template.startswith("//"))):
            add(
                "card_picture_address",
                "A picture is a value of the answer, or a path on the connection that starts with a single /.",
                (*path, "formula" if shown.formula is not None else "template"),
            )
    for path, code, message, params in buttons.problems(definition):
        add(code, message, path, **params)
    for path, code, message, params in blocks.problems(definition):
        add(code, message, path, **params)
    for path, what, failure in pipeline.expression_problems(definition):
        where = f" (character {failure.position + 1})" if failure.position is not None else ""
        problems.append(
            Problem(
                "card_expression_at" if failure.position is not None else "card_expression",
                f"{failure.message}{where}",
                _key_name(path),
                _line(lines, path),
                {"reason": failure.message, "position": (failure.position + 1) if failure.position is not None else 0, "what": what},
            )
        )
    return problems


def _pictures(definition: Any) -> list[tuple[Path, Any]]:
    """The picture value of the rows of a card, with its place."""
    item = getattr(definition, "item", None)
    image = getattr(item, "image", None)
    return [(("item", "image"), image)] if image is not None else []


def check_for_submission(definition: Any) -> list[Problem]:
    """What a card needs to be handed in to the shop and not just kept here: English texts and demo answers.

    Saving locally asks for neither (KARTEN-1 EC-6, AC-11).
    """
    problems: list[Problem] = []
    if not definition.demo:
        problems.append(Problem("card_needs_demo", "A card for the shop needs demo data.", "demo"))
    for path, text in all_texts(definition):
        if isinstance(text, dict) and "en" not in text:
            problems.append(Problem("card_needs_english", "A text in several languages needs the English one.", _key_name(path)))
    return problems


def all_texts(definition: Any) -> list[tuple[Path, str | dict[str, str]]]:
    """Every text of the author (name, description, labels, units) with its place."""
    found: list[tuple[Path, str | dict[str, str]]] = []

    def visit(model: Any, path: Path) -> None:
        if isinstance(model, list):
            for index, child in enumerate(model):
                visit(child, (*path, index))
            return
        if not isinstance(model, BaseModel):
            return
        for name in type(model).model_fields:
            value = getattr(model, name)
            if name in ("name", "description", "label", "unit") and isinstance(value, str | dict):
                found.append(((*path, name), value))
            elif name == "demo":
                continue
            else:
                visit(value, (*path, name))

    visit(definition, ())
    return found


def load_definition(text: str, *, running_version: str = __version__) -> Loaded:
    """Read, check and return a definition, or raise ``CardInvalid`` with everything that is wrong."""
    data, lines = parse(text)
    source_format = _format_of(data, lines)
    data = _carry_over(data, source_format)

    findings = [
        Problem(
            found.code,
            f"This looks like {credentials.PHRASES[found.what]}. A card holds no secrets: the connection keeps them and adds them to the request."
            if found.code == "card_secret_value"
            else f"A card cannot have {credentials.PHRASES[found.what]}. The connection sends its own credentials and headers.",
            _key_name(found.path),
            _line(lines, found.path),
            {"what": found.what},
        )
        for found in credentials.find(data)
    ]
    if findings:
        raise CardInvalid(findings)

    try:
        definition = schema.ADAPTER.validate_python(data)
    except ValidationError as failure:
        found = {(problem.path, problem.code): problem for problem in (_from_pydantic(error, lines) for error in reversed(failure.errors()))}
        raise CardInvalid(list(reversed(found.values()))) from failure

    problems = _semantic(definition, lines, running_version)
    if problems:
        raise CardInvalid(problems)
    dumped = schema.ADAPTER.dump_python(definition, mode="json", by_alias=True, exclude_none=True)
    return Loaded(definition, dumped, source_format, text, lines)


def definition_from_data(data: dict[str, Any]) -> Any:
    """A definition from the JSON the table keeps, without the text and without the check against this nexdeck's version."""
    return schema.ADAPTER.validate_python(data)
