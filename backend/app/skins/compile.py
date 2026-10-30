"""A skin file turned into what a browser is handed: one style sheet and a few lists.

The second layer is written here as CSS of the third layer's kind and goes
through the same checker as a skin's own sheet (``css.compile_css`` with
``trusted`` only for ``position: relative`` under a decoration), so a sprite,
a frame or a motion can never do more than a hand-written rule could. Only the
sprites themselves and the switches are written directly; both are nexdeck's
own text, the sprites as ``data:`` addresses it drew.

``ENGINE`` counts the versions of this file: a stored skin compiled by an
older one is compiled again at start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..services import themes
from . import css, sprites
from .schema import SkinFile

ENGINE = 1

#: nexdeck's own keyframes for the motions a part can be given.
MOTIONS: dict[str, str] = {
    "hop": "0%, 100% { transform: translateY(0) } 40% { transform: translateY(-5px) }",
    "wiggle": "0%, 100% { transform: rotate(0deg) } 25% { transform: rotate(-3deg) } 75% { transform: rotate(3deg) }",
    "spin": "from { transform: rotate(0deg) } to { transform: rotate(360deg) }",
    "pulse": "0%, 100% { transform: scale(1) } 50% { transform: scale(1.06) }",
    "sink": "0%, 100% { transform: translateY(0) } 50% { transform: translateY(2px) }",
    "fade": "0%, 100% { opacity: 1 } 50% { opacity: 0.6 }",
}
TRIGGERS = {"hover": ":hover", "press": ":active", "always": ""}
CORNERS = {"top-left": ("top", "left"), "top-right": ("top", "right"), "bottom-left": ("bottom", "left"), "bottom-right": ("bottom", "right")}
FONT_CALL = re.compile(r"font\(\s*([a-z]+)\s*\)")


@dataclass
class Compiled:
    key: str
    css: str = ""
    native: str | None = None
    options: list[dict[str, Any]] = field(default_factory=list)
    tokens: dict[str, Any] = field(default_factory=dict)
    fonts: list[str] = field(default_factory=list)
    sounds: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Which parts play which sound when pressed: the part's selectors, so the page needs no registry of its own.
    presses: list[dict[str, Any]] = field(default_factory=list)
    #: Not a reason to refuse, but to show: colours below 4.5:1, as for any theme.
    weak: list[dict[str, Any]] = field(default_factory=list)
    engine: int = ENGINE

    def as_json(self) -> dict[str, Any]:
        return {
            "key": self.key, "css": self.css, "native": self.native, "options": self.options, "tokens": self.tokens,
            "fonts": self.fonts, "sounds": self.sounds, "presses": self.presses, "weak": self.weak, "engine": self.engine,
        }


def _second_layer(skin: SkinFile) -> str:
    rules: list[str] = []
    for name in sorted({look.motion.name for look in skin.parts.values() if look.motion}):
        rules.append(f"@keyframes {name} {{ {MOTIONS[name]} }}")
    for part, look in skin.parts.items():
        if look.frame:
            frame = skin.frames[look.frame]
            rules.append(
                f"[data-part={part}] {{ border-style: solid; border-width: {frame.width}px; "
                f"border-image: sprite({frame.sprite}) {frame.slice} fill / {frame.width}px {frame.repeat} }}"
            )
        if look.motion:
            motion = look.motion
            infinite = " infinite" if motion.on == "always" else ""
            rules.append(f"[data-part={part}]{TRIGGERS[motion.on]} {{ animation: {motion.name} {motion.ms}ms ease-in-out{infinite} }}")
    if skin.desk:
        tile = skin.sprites[skin.desk.tile]
        width, height = len(tile.rows[0]) * skin.desk.scale, len(tile.rows) * skin.desk.scale
        # On a layer of its own above nexdeck's light, which the desk carries inline and nothing may reach.
        rules.append(f"[data-part=desk-tile] {{ background-image: sprite({skin.desk.tile}); background-size: {width}px {height}px; background-repeat: repeat }}")
    used: dict[str, list[str]] = {}
    for decoration in skin.decorations:
        free = [slot for slot in css.registry()["parts"][decoration.part]["pseudo"] if slot not in used.get(decoration.part, [])]
        if not free:
            raise css.SkinCssError([css.Problem(f"{decoration.part} has room for {len(used[decoration.part])} decorations, not more.")])
        slot = free[0]
        used.setdefault(decoration.part, []).append(slot)
        vertical, horizontal = CORNERS[decoration.anchor]
        offset = -decoration.size // 2 + decoration.offset
        rules.append(f"[data-part={decoration.part}] {{ position: relative }}")
        rules.append(
            f"[data-part={decoration.part}]{slot} {{ content: ''; position: absolute; {vertical}: {offset}px; {horizontal}: {offset}px; "
            f"width: {decoration.size}px; height: {decoration.size}px; z-index: 2; "
            f"background: sprite({decoration.sprite}) center / contain no-repeat }}"
        )
    if skin.status:
        for state, name in skin.status.model_dump().items():
            if not name:
                continue
            for part in ("status-dot", "card-status"):
                rules.append(
                    f"[data-part={part}]:state({state}) {{ background: sprite({name}) center / contain no-repeat; "
                    "border-radius: 0; box-shadow: none }"
                )
    return "\n".join(rules)


def _switches(skin: SkinFile) -> str:
    """The rules a skin cannot write and may switch on: nexdeck's own text, fenced like every rule."""
    root = f":root[data-skin='{skin.key}']:not([data-skin-guard])"
    fence = ":where(:not([data-skin-guard], [data-skin-guard] *))"
    out = []
    if skin.switches.blur == "off":
        out.append(f"{root} :where(.glass, .glass-strong){fence} {{ backdrop-filter: none; -webkit-backdrop-filter: none }}")
    if skin.switches.shadows == "none":
        out.append(f"{root} :where(.card, .glass, .glass-strong, .btn){fence} {{ box-shadow: none }}")
    if skin.switches.corners == "square":
        out.append(f"{root} :where(.card, .glass, .glass-strong, .btn, .input, .chip){fence} {{ border-radius: 0 }}")
    return "\n".join(out)


def _alike(skin: SkinFile) -> list[css.Problem]:
    if not skin.status:
        return []
    chosen = {state: name for state, name in skin.status.model_dump().items() if name}
    problems = []
    states = sorted(chosen)
    for index, first in enumerate(states):
        for second in states[index + 1:]:
            if sprites.too_alike(skin.sprites[chosen[first]], skin.sprites[chosen[second]]):
                problems.append(css.Problem(f"The symbols for {first} and {second} differ only in colour; give them different shapes."))
    return problems


def compile_skin(skin: SkinFile, *, builtin: bool = False) -> Compiled:
    """Everything a browser needs to wear the skin; raises css.SkinCssError with every problem found."""
    if skin.native and not builtin:
        raise css.SkinCssError([css.Problem("Only the skins nexdeck ships draw with a style sheet of nexdeck's own.")])
    compiled = Compiled(
        key=skin.key,
        native=skin.native,
        options=[option.model_dump() for option in skin.options],
        tokens=skin.tokens.model_dump(exclude_none=True),
        weak=themes.weak_spots({"dark": skin.tokens.dark or {}, "light": skin.tokens.light or {}}),
    )
    problems = _alike(skin)
    names = list(skin.sprites)
    choices = {option.key: [choice.key for choice in option.choices] for option in skin.options}
    sheets: list[str] = []
    if skin.sprites:
        variables = "; ".join(f'--sk-sprite-{name}: url("{sprites.address(sprite)}")' for name, sprite in skin.sprites.items())
        sheets.append(f":root[data-skin='{skin.key}'] {{ {variables} }}")
    for source, trusted in ((_second_layer(skin), True), (skin.css, False)):
        if not source.strip():
            continue
        try:
            sheets.append(css.compile_css(source, skin.key, sprites=names, options=choices, trusted=trusted))
        except css.SkinCssError as error:
            problems.extend(error.problems)
    if problems:
        raise css.SkinCssError(problems)
    switched = _switches(skin)
    if switched:
        sheets.insert(1 if skin.sprites else 0, switched)
    if sheets:
        # The order is fixed whichever sheet a browser meets first: 1984's own, then the skin's.
        compiled.css = "@layer retro, skin;\n@layer skin {\n" + "\n".join(sheets) + "\n}\n"
    fonts = {skin.tokens.font} if skin.tokens.font else set()
    fonts |= set(FONT_CALL.findall(skin.css))
    compiled.fonts = sorted(font for font in fonts if font)
    compiled.sounds = {name: sound.model_dump(by_alias=True) for name, sound in skin.sounds.items()}
    parts = css.registry()["parts"]
    compiled.presses = [{"part": part, "selectors": parts[part]["selectors"], "sound": look.sound} for part, look in skin.parts.items() if look.sound]
    return compiled
