"""The style sheet of a skin, checked and turned into what a browser is given.

A skin's own CSS (the third layer) is written by someone else, so it is not
passed through, not even after a check: it is taken apart into tokens with
tinycss2 and written anew from what was allowed. What is allowed is narrow on
purpose.

* **Selectors name parts, never classes.** ``[data-part=card]`` becomes the
  selectors of ``parts.json``; a part may carry a state (``:state(warn)``),
  ``:hover``, ``:active``, ``:focus-visible``, the skin's options
  (``:option(desk=weave)``) and the brightness (``:mode(dark)``), and a
  ``::before``/``::after`` only where nexdeck leaves that slot free.
* **Properties come from a list per part**, values from a list of token kinds
  and functions. Nothing fetches: there is no ``url()`` and no string except a
  short ``content``; pictures come from the skin's own sprites as
  ``sprite(name)``, fonts from nexdeck's as ``font(key)``.
* **Every rule is fenced.** It starts at ``:root[data-skin='<key>']`` and ends
  with ``:not([data-skin-guard], [data-skin-guard] *)``, so a page or a dialog
  that carries the guard (sign-in, keys, a confirmation) never sees it, and
  ``:where()`` gives every rule the same weight, so the later one wins.
* **Nothing covers what it should not.** No ``position`` but ``absolute`` on a
  pseudo element, which never takes a click; ``z-index`` from -1 to 10, under
  every overlay; no ``!important``; no ``--nd-*`` of its own, the colours come
  from the first layer, which is checked for contrast.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import tinycss2
from tinycss2 import ast

#: Long enough for a whole look, short enough not to be a payload.
MAX_CSS = 20_000
#: A skin's key, an option's name or value: it stands in a selector unquoted by anything but '…'.
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
#: The pseudo elements a skin may draw, where its part leaves them free.
PSEUDO_ELEMENTS = ("before", "after")
SIMPLE_STATES = ("hover", "active", "focus-visible")
#: Functions a value may hold. ``sprite`` and ``font`` are the skin's own and are rewritten.
FUNCTIONS = frozenset({
    "var", "calc", "min", "max", "clamp",
    "rgb", "rgba", "hsl", "hsla", "oklch", "oklab", "color-mix",
    "linear-gradient", "radial-gradient", "conic-gradient",
    "repeating-linear-gradient", "repeating-radial-gradient", "repeating-conic-gradient",
    "steps", "cubic-bezier",
    "translate", "translatex", "translatey", "rotate", "scale", "scalex", "scaley", "skew", "skewx", "skewy",
    "grayscale", "invert", "contrast", "brightness", "saturate", "sepia", "hue-rotate", "drop-shadow",
    "sprite", "font",
})
#: Where a sprite may be put: as a picture or as the shape of a mask.
SPRITE_PROPERTIES = frozenset({"background", "background-image", "mask", "mask-image", "border-image", "border-image-source", "content"})
#: What a keyframe may change: movement and colour, not the size or place of anything.
KEYFRAME_PROPERTIES = frozenset({"opacity", "transform", "translate", "rotate", "scale", "color", "background-color", "border-color", "box-shadow", "filter"})
DISPLAYS = frozenset({"block", "inline-block", "inline", "none", "flex", "grid"})
#: Animations: at most three flashes a second (WCAG 2.3.1), and nothing that keeps a page busy for long.
ANIMATION_MS = (340, 2000)
TRANSITION_MS = (0, 2000)
CONTENT_CHARACTERS = 8


@dataclass(frozen=True)
class Problem:
    message: str
    line: int = 0
    column: int = 0


class SkinCssError(Exception):
    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("; ".join(problem.message for problem in problems))
        self.problems = problems


@cache
def registry() -> dict[str, Any]:
    with (Path(__file__).with_name("parts.json")).open(encoding="utf-8") as file:
        data: dict[str, Any] = json.load(file)
    return data


def _allowed(part: str, pseudo: bool) -> frozenset[str]:
    data = registry()
    groups = data["groups"]
    names = {name for group, members in groups.items() if group != "pseudo" for name in members}
    if pseudo:
        names |= set(groups["pseudo"])
    elif data["parts"][part].get("container"):
        names -= set(data["container_refused"])
    return frozenset(names)


@dataclass
class _Compound:
    part: str
    state: str | None
    simple: list[str]
    pseudo: str | None


@dataclass
class _Selector:
    compounds: list[_Compound]
    combinators: list[str]
    options: list[tuple[str, str]]
    mode: str | None

    @property
    def last(self) -> _Compound:
        return self.compounds[-1]


class _Sheet:
    def __init__(self, key: str, sprites: Iterable[str], options: dict[str, Iterable[str]], trusted: bool = False) -> None:
        self.key = key
        #: The rules nexdeck writes itself from the second layer may anchor a decoration: position: relative.
        self.trusted = trusted
        self.sprites = frozenset(sprites)
        self.options = {name: frozenset(values) for name, values in options.items()}
        self.keyframes: dict[str, str] = {}
        self.problems: list[Problem] = []

    def refuse(self, node: ast.Node | None, message: str) -> None:
        self.problems.append(Problem(message, getattr(node, "source_line", 0), getattr(node, "source_column", 0)))

    # Selectors -------------------------------------------------------------------------------------------------

    def selectors(self, prelude: list[ast.Node]) -> list[_Selector] | None:
        groups: list[list[ast.Node]] = [[]]
        for node in prelude:
            if isinstance(node, ast.LiteralToken) and node.value == ",":
                groups.append([])
            else:
                groups[-1].append(node)
        parsed = [self.selector(group) for group in groups]
        return None if any(selector is None for selector in parsed) else [s for s in parsed if s is not None]

    def selector(self, nodes: list[ast.Node]) -> _Selector | None:
        tokens = list(nodes)
        while tokens and isinstance(tokens[0], ast.WhitespaceToken):
            tokens.pop(0)
        while tokens and isinstance(tokens[-1], ast.WhitespaceToken):
            tokens.pop()
        result = _Selector([], [], [], None)
        index = 0
        pending = ""
        while index < len(tokens):
            node = tokens[index]
            if isinstance(node, ast.WhitespaceToken):
                pending = pending or " "
                index += 1
                continue
            if isinstance(node, ast.LiteralToken) and node.value == ">":
                pending = ">"
                index += 1
                continue
            if not isinstance(node, ast.SquareBracketsBlock):
                self.refuse(node, "A selector names a part as [data-part=name], nothing else.")
                return None
            if result.compounds:
                if not pending:
                    self.refuse(node, "Two parts in a selector need a space or > between them.")
                    return None
                result.combinators.append(pending)
            elif pending == ">":
                self.refuse(node, "A selector cannot start with >.")
                return None
            pending = ""
            part = self.part_name(node)
            if part is None:
                return None
            compound = _Compound(part, None, [], None)
            index += 1
            while index < len(tokens) and isinstance(tokens[index], ast.LiteralToken) and tokens[index].value == ":":
                index = self.pseudo(tokens, index, compound, result)
                if index < 0:
                    return None
            result.compounds.append(compound)
        if not result.compounds:
            self.refuse(nodes[0] if nodes else None, "A rule needs a part to style.")
            return None
        if pending == ">":
            self.refuse(tokens[-1], "A selector cannot end with >.")
            return None
        if any(compound.pseudo for compound in result.compounds[:-1]):
            self.refuse(nodes[0], "::before and ::after go on the last part of a selector.")
            return None
        return result

    def part_name(self, block: ast.SquareBracketsBlock) -> str | None:
        inner = [node for node in block.content if not isinstance(node, ast.WhitespaceToken)]
        if (
            len(inner) == 3
            and isinstance(inner[0], ast.IdentToken)
            and inner[0].lower_value == "data-part"
            and isinstance(inner[1], ast.LiteralToken)
            and inner[1].value == "="
            and isinstance(inner[2], ast.IdentToken | ast.StringToken)
        ):
            name = inner[2].value
            if name in registry()["parts"]:
                return name
            self.refuse(block, f"There is no part {name!r}.")
            return None
        self.refuse(block, "A selector names a part as [data-part=name], nothing else.")
        return None

    def pseudo(self, tokens: list[ast.Node], index: int, compound: _Compound, selector: _Selector) -> int:
        """One ``:…`` or ``::…`` after a part; the index after it, or -1 when it was refused."""
        start = tokens[index]
        index += 1
        if index < len(tokens) and isinstance(tokens[index], ast.LiteralToken) and tokens[index].value == ":":
            index += 1
            name = tokens[index] if index < len(tokens) else None
            if not isinstance(name, ast.IdentToken) or name.lower_value not in PSEUDO_ELEMENTS:
                self.refuse(start, "The only pseudo elements are ::before and ::after.")
                return -1
            if f"::{name.lower_value}" not in registry()["parts"][compound.part]["pseudo"]:
                self.refuse(start, f"::{name.lower_value} of {compound.part} is nexdeck's own and not free for a skin.")
                return -1
            if compound.pseudo:
                self.refuse(start, "A part takes one pseudo element.")
                return -1
            compound.pseudo = name.lower_value
            return index + 1
        node = tokens[index] if index < len(tokens) else None
        if compound.pseudo:
            self.refuse(start, "Nothing may follow ::before or ::after.")
            return -1
        if isinstance(node, ast.IdentToken) and node.lower_value in SIMPLE_STATES:
            compound.simple.append(node.lower_value)
            return index + 1
        if isinstance(node, ast.FunctionBlock):
            values = [arg for arg in node.arguments if not isinstance(arg, ast.WhitespaceToken)]
            if node.lower_name == "state" and len(values) == 1 and isinstance(values[0], ast.IdentToken):
                state = values[0].lower_value
                if state not in registry()["parts"][compound.part].get("states", {}):
                    self.refuse(node, f"{compound.part} has no state {state!r}.")
                    return -1
                if compound.state:
                    self.refuse(node, "A part takes one :state().")
                    return -1
                compound.state = state
                return index + 1
            if node.lower_name == "mode" and len(values) == 1 and isinstance(values[0], ast.IdentToken) and values[0].lower_value in ("dark", "light"):
                selector.mode = values[0].lower_value
                return index + 1
            if (
                node.lower_name == "option"
                and len(values) == 3
                and isinstance(values[0], ast.IdentToken)
                and isinstance(values[1], ast.LiteralToken)
                and values[1].value == "="
                and isinstance(values[2], ast.IdentToken)
            ):
                option, value = values[0].value, values[2].value
                if value not in self.options.get(option, ()):
                    self.refuse(node, f"The skin has no option {option}={value}.")
                    return -1
                selector.options.append((option, value))
                return index + 1
        self.refuse(start, "After a part come only :hover, :active, :focus-visible, :state(), :option(), :mode() and ::before or ::after.")
        return -1

    def compiled_selector(self, selector: _Selector) -> str:
        root = f":root[data-skin='{self.key}']:not([data-skin-guard])"
        root += "".join(f"[data-skin-o-{option}='{value}']" for option, value in selector.options)
        if selector.mode == "light":
            root += "[data-theme='light']"
        elif selector.mode == "dark":
            root += ":not([data-theme='light'])"
        last = registry()["parts"][selector.last.part]
        if selector.last.pseudo and last.get("pseudo_unless"):
            root += f":not({last['pseudo_unless']})"
        parts = []
        for compound in selector.compounds:
            entry = registry()["parts"][compound.part]
            inner = entry["states"][compound.state] if compound.state else entry["selectors"]
            text = f":where({', '.join(inner)})"
            text += "".join(f":{state}" for state in compound.simple)
            text += ":where(:not([data-skin-guard], [data-skin-guard] *))"
            if compound.pseudo:
                text += f"::{compound.pseudo}"
            parts.append(text)
        out = root + " " + parts[0]
        for combinator, text in zip(selector.combinators, parts[1:], strict=True):
            out += (" > " if combinator == ">" else " ") + text
        return out

    # Values ----------------------------------------------------------------------------------------------------

    def value(self, prop: str, tokens: list[ast.Node], node: ast.Node, keyframe: bool = False) -> str | None:
        """The value written anew, or None when something in it was refused."""
        ok = True
        for token in _walk(tokens):
            if isinstance(token, ast.URLToken | ast.SquareBracketsBlock | ast.CurlyBracketsBlock | ast.AtKeywordToken):
                self.refuse(node, f"{prop}: holds something a skin may not use ({token.type}).")
                ok = False
            elif isinstance(token, ast.StringToken) and (prop != "content" or len(token.value) > CONTENT_CHARACTERS):
                self.refuse(node, f"{prop}: holds text; only content takes a text of at most {CONTENT_CHARACTERS} characters.")
                ok = False
            elif isinstance(token, ast.ParseError):
                self.refuse(node, f"{prop}: cannot be read ({token.message}).")
                ok = False
            elif isinstance(token, ast.FunctionBlock):
                ok = self.function(prop, token, node) and ok
        if not ok:
            return None
        return self.bounds(prop, tokens, node, keyframe)

    def function(self, prop: str, token: ast.FunctionBlock, node: ast.Node) -> bool:
        name = token.lower_name
        if name not in FUNCTIONS:
            self.refuse(node, f"{prop}: {name}() is not allowed in a skin.")
            return False
        args = [arg for arg in token.arguments if not isinstance(arg, ast.WhitespaceToken)]
        if name == "var":
            variable = args[0] if args else None
            if not isinstance(variable, ast.IdentToken) or not variable.value.startswith(("--nd-", "--sk-")):
                self.refuse(node, f"{prop}: var() reads only nexdeck's colours (--nd-…) and the skin's own (--sk-…).")
                return False
        if name == "sprite":
            if prop not in SPRITE_PROPERTIES:
                self.refuse(node, f"{prop}: a sprite goes into a background, a mask, a border image or content.")
                return False
            if len(args) != 1 or not isinstance(args[0], ast.IdentToken) or args[0].value not in self.sprites:
                self.refuse(node, f"{prop}: sprite() names one of the skin's sprites.")
                return False
        if name == "font" and (prop != "font-family" or len(args) != 1 or not isinstance(args[0], ast.IdentToken) or args[0].value not in registry()["fonts"]):
            self.refuse(node, f"{prop}: font() names one of nexdeck's fonts ({', '.join(registry()['fonts'])}), only in font-family.")
            return False
        return True

    def bounds(self, prop: str, tokens: list[ast.Node], node: ast.Node, keyframe: bool) -> str | None:
        plain = [token for token in tokens if not isinstance(token, ast.WhitespaceToken)]
        if prop == "font-family" and not (len(plain) == 1 and isinstance(plain[0], ast.FunctionBlock) and plain[0].lower_name == "font"):
            self.refuse(node, "font-family: is one font(), the fonts nexdeck ships.")
            return None
        if prop == "position" and self.trusted and len(plain) == 1 and isinstance(plain[0], ast.IdentToken) and plain[0].lower_value == "relative":
            return self.emit(tokens)
        if prop == "position" and not (len(plain) == 1 and isinstance(plain[0], ast.IdentToken) and plain[0].lower_value == "absolute"):
            self.refuse(node, "position: is absolute or nothing, only on ::before and ::after.")
            return None
        if prop == "display" and not (len(plain) == 1 and isinstance(plain[0], ast.IdentToken) and plain[0].lower_value in DISPLAYS):
            self.refuse(node, f"display: is one of {', '.join(sorted(DISPLAYS))}.")
            return None
        if prop == "z-index" and not (len(plain) == 1 and isinstance(plain[0], ast.NumberToken) and plain[0].is_integer and -1 <= plain[0].int_value <= 10):
            self.refuse(node, "z-index: is a whole number from -1 to 10, under every dialog.")
            return None
        if prop == "font-size" and not all(_size_ok(token) for token in plain):
            self.refuse(node, "font-size: stays between 9 and 72 pixels.")
            return None
        if prop in ("width", "height", "inset", "top", "right", "bottom", "left", "margin", "padding") and not all(_box_ok(token) for token in plain):
            self.refuse(node, f"{prop}: stays within 128 pixels or 100 %.")
            return None
        if prop.startswith(("animation", "transition")) and not self.durations(prop, plain, node):
            return None
        if prop == "opacity" and not all(not isinstance(token, ast.NumberToken | ast.PercentageToken) or _share(token) >= 0.3 for token in plain) and not keyframe:
            self.refuse(node, "opacity: stays at 0.3 or more, so nothing is hidden.")
            return None
        return self.emit(tokens)

    def durations(self, prop: str, plain: list[ast.Node], node: ast.Node) -> bool:
        low, high = ANIMATION_MS if prop.startswith("animation") else TRANSITION_MS
        for token in plain:
            if isinstance(token, ast.DimensionToken) and token.lower_unit in ("s", "ms"):
                ms = token.value * (1000 if token.lower_unit == "s" else 1)
                if prop in ("animation-delay", "transition-delay"):
                    continue
                if not low <= ms <= high:
                    self.refuse(node, f"{prop}: lasts from {low} to {high} ms.")
                    return False
            if prop in ("animation", "animation-name") and isinstance(token, ast.IdentToken) and token.lower_value not in ANIMATION_WORDS and token.value not in self.keyframes:
                self.refuse(node, f"{prop}: there are no @keyframes {token.value} in this skin.")
                return False
        return True

    def emit(self, tokens: list[ast.Node]) -> str:
        out = []
        for token in tokens:
            if isinstance(token, ast.FunctionBlock):
                if token.lower_name == "sprite":
                    out.append(f"var(--sk-sprite-{_args(token)[0].value})")
                elif token.lower_name == "font":
                    out.append(registry()["fonts"][_args(token)[0].value])
                else:
                    out.append(f"{token.name}({self.emit(token.arguments)})")
            elif isinstance(token, ast.ParenthesesBlock):
                out.append(f"({self.emit(token.content)})")
            elif isinstance(token, ast.IdentToken) and token.value in self.keyframes:
                out.append(self.keyframes[token.value])
            else:
                out.append(tinycss2.serialize([token]))
        return "".join(out).strip()

    # Rules -----------------------------------------------------------------------------------------------------

    def declarations(self, content: list[ast.Node], allowed: frozenset[str] | None, keyframe: bool = False) -> list[str]:
        out = []
        for item in tinycss2.parse_blocks_contents(content, skip_comments=True, skip_whitespace=True):
            if isinstance(item, ast.ParseError):
                self.refuse(item, f"Cannot read this declaration ({item.message}).")
                continue
            if not isinstance(item, ast.Declaration):
                self.refuse(item, "A rule holds declarations, no rules of its own.")
                continue
            name = item.lower_name
            if item.important:
                self.refuse(item, f"{name}: !important is not needed in a skin and not allowed.")
                continue
            if name.startswith("--"):
                if not name.startswith("--sk-") or name.startswith("--sk-sprite-"):
                    self.refuse(item, f"{name}: a skin keeps variables of its own as --sk-…; nexdeck's colours come from its tokens.")
                    continue
            elif keyframe and name not in KEYFRAME_PROPERTIES:
                self.refuse(item, f"{name}: a keyframe changes only {', '.join(sorted(KEYFRAME_PROPERTIES))}.")
                continue
            elif allowed is not None and name not in allowed:
                self.refuse(item, f"{name}: is not a property a skin may set here.")
                continue
            text = self.value(name, item.value, item, keyframe)
            if text is not None:
                out.append(f"{name}: {text}")
        return out

    def rule(self, rule: ast.QualifiedRule) -> str | None:
        selectors = self.selectors(rule.prelude)
        if not selectors:
            return None
        allowed: frozenset[str] | None = None
        for selector in selectors:
            own = _allowed(selector.last.part, bool(selector.last.pseudo)) | ({"position"} if self.trusted else set())
            allowed = own if allowed is None else allowed & own
        body = self.declarations(rule.content, allowed)
        if any(selector.last.pseudo for selector in selectors):
            body.append("pointer-events: none")
        if not body:
            return None
        return f"{', '.join(self.compiled_selector(selector) for selector in selectors)} {{ {'; '.join(body)} }}"

    def keyframe(self, rule: ast.AtRule) -> str | None:
        name = self.keyframe_name(rule)
        if name is None or rule.content is None:
            return None
        frames = []
        for frame in tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True):
            if not isinstance(frame, ast.QualifiedRule) or not all(
                isinstance(token, ast.PercentageToken | ast.WhitespaceToken) or (isinstance(token, ast.IdentToken) and token.lower_value in ("from", "to")) or (isinstance(token, ast.LiteralToken) and token.value == ",")
                for token in frame.prelude
            ):
                self.refuse(frame, "A keyframe starts with from, to or a percentage.")
                continue
            body = self.declarations(frame.content, None, keyframe=True)
            frames.append(f"{tinycss2.serialize(frame.prelude).strip()} {{ {'; '.join(body)} }}")
        return f"@keyframes {self.keyframes[name]} {{ {' '.join(frames)} }}"

    def keyframe_name(self, rule: ast.AtRule) -> str | None:
        plain = [token for token in rule.prelude if not isinstance(token, ast.WhitespaceToken)]
        if len(plain) != 1 or not isinstance(plain[0], ast.IdentToken):
            self.refuse(rule, "@keyframes takes one plain name.")
            return None
        return plain[0].value

    def media(self, rule: ast.AtRule) -> str | None:
        query = self.media_query(rule)
        if query is None or rule.content is None:
            return None
        inner = [text for item in tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True) if (text := self.item(item, nested=True))]
        return f"@media {query} {{ {' '.join(inner)} }}" if inner else None

    def media_query(self, rule: ast.AtRule) -> str | None:
        parts = []
        for token in rule.prelude:
            if isinstance(token, ast.WhitespaceToken):
                continue
            if isinstance(token, ast.IdentToken) and token.lower_value == "and":
                parts.append("and")
                continue
            feature = [t for t in token.content if not isinstance(t, ast.WhitespaceToken)] if isinstance(token, ast.ParenthesesBlock) else []
            if (
                len(feature) == 3
                and isinstance(feature[0], ast.IdentToken)
                and isinstance(feature[1], ast.LiteralToken)
                and feature[1].value == ":"
            ):
                name, value = feature[0].lower_value, feature[2]
                if name in ("min-width", "max-width") and isinstance(value, ast.DimensionToken) and value.lower_unit == "px":
                    parts.append(f"({name}: {value.serialize()})")
                    continue
                if name == "prefers-reduced-motion" and isinstance(value, ast.IdentToken) and value.lower_value in ("reduce", "no-preference"):
                    parts.append(f"({name}: {value.lower_value})")
                    continue
            self.refuse(rule, "@media asks only min-width, max-width (in px) and prefers-reduced-motion; the brightness is :mode().")
            return None
        if not parts or parts[0] == "and" or parts[-1] == "and":
            self.refuse(rule, "@media needs a question.")
            return None
        return " ".join(parts)

    def item(self, item: ast.Node, nested: bool = False) -> str | None:
        if isinstance(item, ast.QualifiedRule):
            return self.rule(item)
        if isinstance(item, ast.AtRule) and item.lower_at_keyword == "media" and not nested:
            return self.media(item)
        if isinstance(item, ast.AtRule) and item.lower_at_keyword == "keyframes" and not nested:
            return self.keyframe(item)
        if isinstance(item, ast.ParseError):
            self.refuse(item, f"Cannot read this part of the style sheet ({item.message}).")
            return None
        keyword = getattr(item, "lower_at_keyword", None)
        self.refuse(item, f"@{keyword} is not allowed in a skin." if keyword else "This is not allowed in a skin.")
        return None


ANIMATION_WORDS = frozenset({
    "none", "infinite", "normal", "reverse", "alternate", "alternate-reverse", "forwards", "backwards", "both",
    "running", "paused", "linear", "ease", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end",
    "all", "initial", "inherit", "unset",
})


def _walk(nodes: Iterable[ast.Node] | None) -> Iterator[ast.Node]:
    for node in nodes or ():
        yield node
        inner = getattr(node, "arguments", None) if isinstance(node, ast.FunctionBlock) else getattr(node, "content", None)
        if isinstance(inner, list):
            yield from _walk(inner)


def _args(function: ast.FunctionBlock) -> list[ast.Node]:
    return [arg for arg in function.arguments if not isinstance(arg, ast.WhitespaceToken)]


def _size_ok(token: ast.Node) -> bool:
    if isinstance(token, ast.DimensionToken):
        if token.lower_unit == "px":
            return 9 <= token.value <= 72
        if token.lower_unit in ("rem", "em"):
            return 0.5 <= token.value <= 4.5
        return False
    if isinstance(token, ast.PercentageToken):
        return 50 <= token.value <= 400
    return isinstance(token, ast.IdentToken | ast.FunctionBlock)


def _box_ok(token: ast.Node) -> bool:
    if isinstance(token, ast.DimensionToken):
        limit = {"px": 128, "rem": 8, "em": 8}.get(token.lower_unit)
        return limit is not None and -limit <= token.value <= limit
    if isinstance(token, ast.PercentageToken):
        return -100 <= token.value <= 100
    if isinstance(token, ast.NumberToken):
        return token.value == 0
    return isinstance(token, ast.IdentToken | ast.FunctionBlock | ast.LiteralToken)


def _share(token: ast.NumberToken | ast.PercentageToken) -> float:
    return float(token.value) / (100 if isinstance(token, ast.PercentageToken) else 1)


def compile_css(
    source: str, key: str, *, sprites: Iterable[str] = (), options: dict[str, Iterable[str]] | None = None, trusted: bool = False
) -> str:
    """The skin's style sheet as the browser gets it; raises SkinCssError with every problem found.

    ``trusted`` is for the rules ``compile.py`` writes from the second layer, never for a skin's own text.
    """
    if len(source) > MAX_CSS and not trusted:
        raise SkinCssError([Problem(f"The style sheet is longer than {MAX_CSS} characters.")])
    if not KEY.match(key):
        raise SkinCssError([Problem("A skin's key is lower case letters, digits and dashes.")])
    sheet = _Sheet(key, sprites, options or {}, trusted)
    items = tinycss2.parse_stylesheet(source, skip_comments=True, skip_whitespace=True)
    for item in items:
        # Named first, so an animation may use keyframes written further down; a bad name is told once, later.
        plain = [token for token in getattr(item, "prelude", None) or () if not isinstance(token, ast.WhitespaceToken)]
        if isinstance(item, ast.AtRule) and item.lower_at_keyword == "keyframes" and len(plain) == 1 and isinstance(plain[0], ast.IdentToken):
            sheet.keyframes[plain[0].value] = f"sk-{key}-{plain[0].value}"
    out = [text for item in items if (text := sheet.item(item))]
    if sheet.problems:
        raise SkinCssError(sheet.problems)
    return "\n".join(out)
