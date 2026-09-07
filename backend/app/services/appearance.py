"""How the installation looks: the accent colour and a style sheet of its own.

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
DEFAULTS: dict[str, Any] = {"preset": "cyan", "accent": "", "css": ""}


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
        "presets": PRESETS,
    }


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
    return text


def save(db: DbSessionType, incoming: dict[str, Any]) -> dict[str, Any]:
    preset = str(incoming.get("preset") or "cyan")
    if preset not in PRESETS:
        raise AppearanceError("There is no such colour.", "no_such_preset")
    accent = str(incoming.get("accent") or "").strip()
    if accent and not COLOUR.match(accent):
        raise AppearanceError("A colour of your own has to read like #22d3ee.", "bad_colour")
    value = {"preset": preset, "accent": accent.lower(), "css": check_css(incoming.get("css") or "")}
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()
    return stored(db)
