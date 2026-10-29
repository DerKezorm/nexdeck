"""How the installation looks: a colour theme, the accent colour, the cards and a style sheet of its own.

nexdeck ships one look in two brightnesses. That is enough for most, and not
enough for the people who put a dashboard on a wall and want it to match the
room. Two knobs are all it takes: the colour everything highlights with, and a
style sheet the operator writes.

⚠️ The style sheet is written by an administrator and shown to everybody, so
it is checked before it is stored. CSS cannot run code in any browser this
decade, but it can fetch: ``@import`` pulls a file from wherever it points,
which on a self-hosted dashboard is a leak, not a feature. That, and anything
that would close the tag early, is refused.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session as DbSessionType

from ..models import Setting
from . import css_scan, themes

KEY = "appearance"
#: Long enough for a real style sheet, short enough not to be a payload.
MAX_CSS = 20_000
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
#: What must not be in a style sheet that everyone is shown.
FORBIDDEN = (
    (re.compile(r"</\s*style", re.I), "It must not close the style tag."),
    (re.compile(r"@import", re.I), "@import fetches a file from somewhere else; put the style sheet in here instead."),
    # ⚠️ The same door, one line further down. @import was barred and url()
    # was not, and url() fetches just as well: a background image on a foreign
    # address tells that address the IP and the user agent of everyone who
    # opens a board. data: stays allowed, it fetches nothing.
    (re.compile(r"url\s*\(\s*(?!['\"]?data:)", re.I), "url() fetches from somewhere else; only data: is allowed here."),
    (re.compile(r"javascript\s*:", re.I), "javascript: does not belong in a style sheet."),
    (re.compile(r"expression\s*\(", re.I), "expression() does not belong in a style sheet."),
    (re.compile(r"<\s*script", re.I), "A script does not belong in a style sheet."),
)

#: The ready-made colours. The first one is what nexdeck has always looked like.
PRESETS: dict[str, str] = {
    "cyan": "#22d3ee",
    "violet": "#a78bfa",
    "emerald": "#34d399",
    "amber": "#fbbf24",
    "rose": "#fb7185",
    "sky": "#38bdf8",
    "slate": "#94a3b8",
}
#: How a card is drawn. Glass is what nexdeck has always been: see-through over
#: the background. Flat is solid, outline is a frame on nothing, neon a frame
#: that glows in the accent, liquid a thick glass with a lit rim whose edge
#: bends what lies behind it, calm a quiet sheet with small titles and soft
#: small print that does not move, window a card as a window of an early
#: desktop (the look called 1984, which redraws the whole interface, not only
#: the cards). A new style is a name here and its rules in the style sheet
#: (``:root[data-cards='…']``); nothing else needs to know it.
CARD_STYLES: tuple[str, ...] = ("glass", "liquid", "flat", "outline", "neon", "calm", "window")
#: Window is the installation's or nothing: it redraws every page, so one board
#: in it among boards of glass would be half of it.
BOARD_STYLES: tuple[str, ...] = tuple(style for style in CARD_STYLES if style != "window")
#: The type of the interface. Inter is what nexdeck has always been set in, the
#: system's own costs no download, the rest ship with nexdeck under the SIL Open
#: Font License and are fetched from nexdeck itself, only by a browser that
#: shows them. As with the styles, a new one is a name here and an entry in
#: the browser's list (``lib/fonts.ts``).
FONTS: tuple[str, ...] = ("inter", "system", "plex", "atkinson", "geist", "mono", "pixel")
#: What the window style can be told, each with its choices, the first the
#: default: how a yellow or red card says so (a coloured symbol and a shape, a
#: touch of colour on the shape as well, or the shape alone without any
#: colour), whether logos keep their colours, the ground of the desk, and
#: whether the pixel type sets the titles only or everything.
RETRO: dict[str, tuple[str, ...]] = {
    "status": ("symbol", "tint", "pattern"),
    "icons": ("colour", "mono"),
    "desk": ("dither", "weave", "grey"),
    "type": ("titles", "all"),
}
#: Corners and gaps in pixels, with the bounds a board still reads well in.
RADIUS = (0, 28, 16)
GAP = (4, 28, 12)
DEFAULTS: dict[str, Any] = {"preset": "cyan", "accent": "", "css": "", "theme": None, "card_style": "glass", "radius": RADIUS[2], "gap": GAP[2], "refraction": True,
                           "font": FONTS[0], "retro": {}}


class AppearanceError(Exception):
    def __init__(self, message: str, code: str = "bad_appearance") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def stored(db: DbSessionType) -> dict[str, Any]:
    row = db.get(Setting, KEY)
    value = {**DEFAULTS, **(dict(row.value) if row is not None else {})}
    return {
        "preset": str(value.get("preset") or "cyan"),
        "accent": str(value.get("accent") or ""),
        "css": str(value.get("css") or ""),
        "theme": value.get("theme"),
        "card_style": value["card_style"] if value.get("card_style") in CARD_STYLES else "glass",
        "radius": _within(value.get("radius"), RADIUS),
        "gap": _within(value.get("gap"), GAP),
        # Liquid glass only: whether the rim bends the background. A browser
        # that cannot (Safari, Firefox) draws the glass without it either way.
        "refraction": value.get("refraction") is not False,
        "font": value["font"] if value.get("font") in FONTS else FONTS[0],
        "retro": _retro(value.get("retro")),
        "card_styles": list(CARD_STYLES),
        "fonts": list(FONTS),
        "presets": PRESETS,
        "themes": themes.THEMES,
        # What in the chosen theme is hard to read, so the page can say so.
        "weak": themes.weak_spots(value["theme"]) if value.get("theme") else [],
    }


def _retro(value: Any) -> dict[str, str]:
    """The window style's choices as stored, each known one or its default."""
    given = value if isinstance(value, dict) else {}
    return {key: given[key] if given.get(key) in choices else choices[0] for key, choices in RETRO.items()}


def public(db: DbSessionType) -> dict[str, Any]:
    """The part of the look a page needs before anybody signs in.

    The sign-in page and the first start are drawn in the installation's look
    as well, which for 1984 is the whole point. Without the operator's style
    sheet: that one is code, written for those who sign in.
    """
    config = stored(db)
    return {
        "theme": config["theme"], "card_style": config["card_style"], "font": config["font"],
        "retro": config["retro"], "radius": config["radius"], "gap": config["gap"],
        "colour": colour_of(config), "accent": config["accent"], "preset": config["preset"],
    }


def _within(value: Any, bounds: tuple[int, int, int]) -> int:
    """A stored number inside its bounds, or the default for anything else."""
    low, high, default = bounds
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else default


def colour_of(config: dict[str, Any]) -> str:
    """The accent that wins: a colour of one's own, else the chosen preset."""
    own = str(config.get("accent") or "").strip()
    if COLOUR.match(own):
        return own.lower()
    return PRESETS.get(str(config.get("preset") or "cyan"), PRESETS["cyan"])


def check_css(css: str) -> str:
    text = str(css or "")
    if len(text) > MAX_CSS:
        raise AppearanceError(f"The style sheet is longer than {MAX_CSS} characters.", "css_too_long")
    for pattern, why in FORBIDDEN:
        if pattern.search(text):
            raise AppearanceError(why, "css_refused")
    # The patterns read text; a browser reads tokens, with escapes decoded (css_scan).
    if why := css_scan.what_fetches(text):
        raise AppearanceError(why, "css_refused")
    return text


def save(db: DbSessionType, incoming: dict[str, Any]) -> dict[str, Any]:
    preset = str(incoming.get("preset") or "cyan")
    if preset not in PRESETS:
        raise AppearanceError("There is no such colour.", "no_such_preset")
    accent = str(incoming.get("accent") or "").strip()
    if accent and not COLOUR.match(accent):
        raise AppearanceError("A colour of your own has to read like #22d3ee.", "bad_colour")
    try:
        theme = themes.check(incoming.get("theme"))
    except themes.ThemeError as failure:
        raise AppearanceError(str(failure), "bad_theme") from failure
    card_style = str(incoming.get("card_style") or "glass")
    if card_style not in CARD_STYLES:
        raise AppearanceError(f"A card is drawn as {', '.join(CARD_STYLES)}.", "no_such_card_style")
    sizes: dict[str, int] = {}
    for name, (low, high, default) in (("radius", RADIUS), ("gap", GAP)):
        number = incoming.get(name)
        if number is None:
            number = default
        if not isinstance(number, int) or isinstance(number, bool) or not low <= number <= high:
            raise AppearanceError(f"The {'corners' if name == 'radius' else 'gap'} go from {low} to {high} pixels.", f"bad_{name}")
        sizes[name] = number
    font = str(incoming.get("font") or FONTS[0])
    if font not in FONTS:
        raise AppearanceError(f"The interface is set in one of {', '.join(FONTS)}.", "no_such_font")
    refraction = incoming.get("refraction", True)
    if not isinstance(refraction, bool):
        raise AppearanceError("Whether the glass bends the light is yes or no.", "bad_refraction")
    retro = incoming.get("retro") or {}
    if not isinstance(retro, dict):
        raise AppearanceError("The choices of the window style are a mapping.", "bad_retro")
    for key, choice in retro.items():
        if key not in RETRO or choice not in RETRO[key]:
            known = "; ".join(f"{name} is {' or '.join(options)}" for name, options in RETRO.items())
            raise AppearanceError(f"The window style knows these choices: {known}.", "bad_retro")
    value = {
        "preset": preset, "accent": accent.lower(), "css": check_css(incoming.get("css") or ""), "theme": theme,
        "card_style": card_style, **sizes, "refraction": refraction, "font": font, "retro": _retro(retro),
    }
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()
    return stored(db)
