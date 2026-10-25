"""The small calculation language of a custom card.

A formula is numbers, references to the answer in braces, ``+ - * /``,
brackets, comparisons and four functions: ``round(x, n)``, ``abs(x)``,
``min(a, b)`` and ``max(a, b)``. A reference is a JMESPath expression:
``{disk.used} / {disk.total} * 100``. Nothing else: no names, no loops, no
calls out, so there is nothing a formula could do beyond calculating.

⚠️ This is a parser of its own and never ``eval`` or ``ast``. The text comes
from whoever writes a card, and a card can come from the shop.

A value that is not there, or is not a number, makes the whole result
``None`` ("–" on the card), and so does dividing by zero (KARTEN-5 EC-1, EC-2).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import jmespath
import jmespath.exceptions
import jmespath.functions

MAX_FORMULA = 500
#: Brackets, calls and minus signs inside one another.
MAX_DEPTH = 32
#: Parts altogether, so the work for one formula has a ceiling too.
MAX_NODES = 200
MAX_REF = 200

FUNCTIONS = ("round", "abs", "min", "max")
_NUMBER_TEXT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_NUMBER_TOKEN = re.compile(r"\d+(\.\d+)?([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?")
_NAME = re.compile(r"[a-z]+")


class FormulaError(ValueError):
    """What is wrong and where: ``position`` counts characters from 0."""

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position


@dataclass(frozen=True)
class Ref:
    """A JMESPath expression that picks something out of the answer."""

    expression: str
    compiled: Any

    def search(self, data: Any) -> Any:
        """What the expression finds. A type that does not fit (the sum of texts) finds nothing, like a missing field."""
        try:
            return self.compiled.search(data)
        except jmespath.exceptions.JMESPathError:
            return None


_KNOWN_FUNCTIONS = frozenset(name[6:] for name in dir(jmespath.functions.Functions) if name.startswith("_func_"))


def _unknown_function(node: Any) -> str | None:
    """A name used as a function that JMESPath does not have; it would only fail later, when an answer arrives."""
    if isinstance(node, dict):
        if node.get("type") == "function_expression" and node.get("value") not in _KNOWN_FUNCTIONS:
            return str(node.get("value"))
        children = node.get("children", [])
        return next((found for child in children if (found := _unknown_function(child))), None)
    return None


def compile_ref(expression: str, offset: int = 0) -> Ref:
    text = expression.strip()
    if not text:
        raise FormulaError("A reference in braces is empty.", offset)
    if len(text) > MAX_REF:
        raise FormulaError(f"A reference is longer than {MAX_REF} characters.", offset)
    try:
        compiled = jmespath.compile(text)
        unknown = _unknown_function(compiled.parsed)
        if unknown:
            raise FormulaError(f"{unknown!r} is not a function JMESPath knows.", offset)
        return Ref(text, compiled)
    except jmespath.exceptions.ParseError as failure:
        where = offset + (failure.lex_position or 0)
        raise FormulaError(f"Cannot read the reference {text!r}: {failure.msg}.", where) from failure
    except jmespath.exceptions.JMESPathError as failure:
        raise FormulaError(f"Cannot read the reference {text!r}: {failure}.", offset) from failure


def compile_path(expression: str) -> Ref:
    """A path on its own (not inside braces); the same reader, the same errors."""
    return compile_ref(expression, 0)


def as_number(value: Any) -> float | None:
    """A number, or ``None``. A text counts when all of it is one, with a point (KARTEN-5 EC-3)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str) and _NUMBER_TEXT.match(value.strip()):
        number = float(value.strip())
        return number if math.isfinite(number) else None
    return None


def _scan_reference(text: str, start: int) -> int:
    """Index of the ``}`` that closes the ``{`` at ``start``; quotes and inner braces are skipped."""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char in "\"'`":
            index += 1
            while index < len(text) and text[index] != char:
                index += 2 if text[index] == "\\" else 1
            if index >= len(text):
                raise FormulaError("A quote in a reference is never closed.", start)
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise FormulaError("A reference is missing its closing brace.", start)


# -- templates ---------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    parts: tuple[str | Ref, ...]

    def refs(self) -> list[Ref]:
        return [part for part in self.parts if isinstance(part, Ref)]


def compile_template(text: str) -> Template:
    """``"S{seasonNumber}E{episodeNumber}"``; ``{{`` and ``}}`` write a brace."""
    if len(text) > MAX_FORMULA:
        raise FormulaError(f"A template is longer than {MAX_FORMULA} characters.", MAX_FORMULA)
    parts: list[str | Ref] = []
    literal: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if text.startswith("{{", index) or text.startswith("}}", index):
            literal.append(char)
            index += 2
        elif char == "{":
            end = _scan_reference(text, index)
            if literal:
                parts.append("".join(literal))
                literal = []
            parts.append(compile_ref(text[index + 1 : end], index + 1))
            index = end + 1
        elif char == "}":
            raise FormulaError("A closing brace has no opening one. Write }} for a brace.", index)
        else:
            literal.append(char)
            index += 1
    if literal:
        parts.append("".join(literal))
    if len(parts) > MAX_NODES:
        raise FormulaError(f"A template has more than {MAX_NODES} parts.", 0)
    return Template(tuple(parts))


def plain_text(value: Any) -> str | None:
    """A value as it stands in a sentence. A list or an object is not one."""
    if value is None or isinstance(value, list | dict):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return str(int(value)) if value == int(value) else format(value, ".10g")
    return str(value)


def render_template(template: Template, resolve: Callable[[Ref], Any]) -> str | None:
    """The text, or ``None`` when any value in it is missing (the card then says "–")."""
    out: list[str] = []
    for part in template.parts:
        if isinstance(part, str):
            out.append(part)
            continue
        text = plain_text(resolve(part))
        if text is None:
            return None
        out.append(text)
    return "".join(out)


# -- formulas ----------------------------------------------------------------

Node = tuple[Any, ...]


@dataclass(frozen=True)
class Formula:
    tree: Node
    refs: tuple[Ref, ...]


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0
        self.refs: list[Ref] = []
        self.nodes = 0

    def fail(self, message: str, position: int | None = None) -> FormulaError:
        return FormulaError(message, self.index if position is None else position)

    def skip(self) -> None:
        while self.index < len(self.text) and self.text[self.index].isspace():
            self.index += 1

    def peek(self, *candidates: str) -> str | None:
        self.skip()
        for candidate in candidates:
            if self.text.startswith(candidate, self.index):
                return candidate
        return None

    def take(self, candidate: str) -> None:
        self.skip()
        if not self.text.startswith(candidate, self.index):
            raise self.fail(f"Expected {candidate!r}.")
        self.index += len(candidate)

    def count(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise self.fail(f"The formula has more than {MAX_NODES} parts.")

    def parse(self) -> Formula:
        tree = self.comparison(0)
        self.skip()
        if self.index < len(self.text):
            raise self.fail(f"Unexpected {self.text[self.index]!r}.")
        return Formula(tree, tuple(self.refs))

    def comparison(self, depth: int) -> Node:
        left = self.sum(depth)
        operator = self.peek("==", "!=", "<=", ">=", "<", ">")
        if operator is None:
            return left
        self.index += len(operator)
        self.count()
        return ("bin", operator, left, self.sum(depth))

    def sum(self, depth: int) -> Node:
        left = self.term(depth)
        while (operator := self.peek("+", "-")) is not None:
            self.index += 1
            self.count()
            left = ("bin", operator, left, self.term(depth))
        return left

    def term(self, depth: int) -> Node:
        left = self.unary(depth)
        while (operator := self.peek("*", "/")) is not None:
            self.index += 1
            self.count()
            left = ("bin", operator, left, self.unary(depth))
        return left

    def unary(self, depth: int) -> Node:
        if depth >= MAX_DEPTH:
            raise self.fail(f"Brackets and minus signs are nested deeper than {MAX_DEPTH}.")
        if self.peek("-") is not None:
            self.index += 1
            self.count()
            return ("neg", self.unary(depth + 1))
        return self.primary(depth)

    def primary(self, depth: int) -> Node:
        self.skip()
        if self.index >= len(self.text):
            raise self.fail("The formula ends where a value or a bracket was expected.")
        char = self.text[self.index]
        self.count()
        if char == "(":
            self.index += 1
            inner = self.comparison(depth + 1)
            self.take(")")
            return inner
        if char == "{":
            end = _scan_reference(self.text, self.index)
            ref = compile_ref(self.text[self.index + 1 : end], self.index + 1)
            self.index = end + 1
            self.refs.append(ref)
            return ("ref", ref)
        match = _NUMBER_TOKEN.match(self.text, self.index)
        if match:
            self.index = match.end()
            return ("num", float(match.group()))
        name = _NAME.match(self.text, self.index)
        if name and name.group() in FUNCTIONS:
            self.index = name.end()
            self.take("(")
            arguments = [self.comparison(depth + 1)]
            while self.peek(",") is not None:
                self.index += 1
                arguments.append(self.comparison(depth + 1))
            self.take(")")
            return self.check_call(name.group(), arguments, name.start())
        if name:
            raise self.fail(f"{name.group()!r} is not known here. The functions are {', '.join(FUNCTIONS)}.")
        raise self.fail(f"Unexpected {char!r}.")

    def check_call(self, name: str, arguments: list[Node], position: int) -> Node:
        low, high = {"round": (1, 2), "abs": (1, 1), "min": (2, 8), "max": (2, 8)}[name]
        if not low <= len(arguments) <= high:
            wanted = f"{low}" if low == high else f"{low} to {high}"
            raise self.fail(f"{name}() takes {wanted} value(s), not {len(arguments)}.", position)
        return ("call", name, tuple(arguments))


def compile_formula(text: str) -> Formula:
    if len(text) > MAX_FORMULA:
        raise FormulaError(f"A formula is longer than {MAX_FORMULA} characters.", MAX_FORMULA)
    if not text.strip():
        raise FormulaError("The formula is empty.", 0)
    return _Parser(text).parse()


def _round_half_up(value: float, digits: int) -> float:
    return float(Decimal(repr(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def _compare(operator: str, left: Any, right: Any) -> bool | None:
    one, two = as_number(left), as_number(right)
    if one is not None and two is not None:
        left, right = one, two
    elif operator not in ("==", "!="):
        return None
    elif isinstance(left, bool) or isinstance(right, bool) or left is None or right is None:
        return None
    return {
        "==": left == right,
        "!=": left != right,
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
    }[operator]


def _run(node: Node, resolve: Callable[[Ref], Any]) -> Any:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return resolve(node[1])
    if kind == "neg":
        value = as_number(_run(node[1], resolve))
        return None if value is None else -value
    if kind == "bin":
        operator = node[1]
        left, right = _run(node[2], resolve), _run(node[3], resolve)
        if operator in ("==", "!=", "<", "<=", ">", ">="):
            return _compare(operator, left, right)
        one, two = as_number(left), as_number(right)
        if one is None or two is None:
            return None
        if operator == "+":
            result = one + two
        elif operator == "-":
            result = one - two
        elif operator == "*":
            result = one * two
        else:
            if two == 0:
                return None
            result = one / two
        return result if math.isfinite(result) else None
    name, arguments = node[1], node[2]
    values = [as_number(_run(argument, resolve)) for argument in arguments]
    if any(value is None for value in values):
        return None
    if name == "abs":
        return abs(values[0])
    if name == "min":
        return min(values)
    if name == "max":
        return max(values)
    digits = 0
    if len(values) == 2:
        if values[1] != int(values[1]) or not 0 <= values[1] <= 10:
            return None
        digits = int(values[1])
    return _round_half_up(values[0], digits)


def evaluate(formula: Formula, resolve: Callable[[Ref], Any]) -> float | bool | None:
    """The result, or ``None`` when something it needs is missing or the division is by zero."""
    return _run(formula.tree, resolve)
