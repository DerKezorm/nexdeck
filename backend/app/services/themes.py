"""Colour themes: the whole palette of the interface, for dark and for light.

A theme names the fifteen colours the interface is built from, once for the
dark look and once for the light one, as ``#rrggbb``. The browser derives the
see-through surfaces and the soft and glowing shades of the accent from them.
nexdeck ships seven of its own and six known ones from elsewhere (Catppuccin,
Nord, Dracula, Tokyo Night, Gruvbox, Rosé Pine); any other can be pasted in as
JSON and taken out again the same way.

The known ones follow their published palettes. Where a colour of the original
falls below 4.5:1 here, it is darkened or lightened in its own hue until it
clears the line, and no further: Catppuccin Latte's yellow, for one, is a text
colour nobody could read on its own page.

Every colour that is drawn as text is checked against the page, the raised
page and the card: below 4.5:1 it is hard to read for many and impossible
for some. The shipped themes clear that everywhere, a guard keeps it so, and
a pasted one is told which colours fall short, in both brightnesses, before
it is taken. It is taken anyway: the person pasting it decides.
"""

from __future__ import annotations

import re
from typing import Any

#: The colours a theme sets, without the ``--nd-`` prefix of the style sheet.
TOKENS: tuple[str, ...] = (
    "bg", "bg-elev", "surface", "surface-hover", "border", "border-strong",
    "text", "text-muted", "text-faint", "accent", "on-accent", "ok", "warn", "bad", "unknown",
)
#: What is read as text, and the grounds it is read on.
TEXT = ("text", "text-muted", "text-faint", "accent", "ok", "warn", "bad", "unknown")
GROUNDS = ("bg", "bg-elev", "surface")
LEAST = 4.5
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeError(ValueError):
    pass


THEMES: dict[str, dict[str, Any]] = {
    "deepsea": {
        "name": "Deep sea",
        "dark": {
            "bg": "#07141c", "bg-elev": "#0b1d28", "surface": "#0f2633", "surface-hover": "#153242",
            "border": "#17374a", "border-strong": "#22506a", "text": "#e3f1f6", "text-muted": "#a7c3cf",
            "text-faint": "#86a6b4", "accent": "#2dd4bf", "on-accent": "#04201c", "ok": "#4ade80",
            "warn": "#facc15", "bad": "#f87171", "unknown": "#7b95a2",
        },
        "light": {
            "bg": "#eef6f8", "bg-elev": "#ffffff", "surface": "#ffffff", "surface-hover": "#e3eff3",
            "border": "#cfe1e8", "border-strong": "#b3ccd6", "text": "#0b2430", "text-muted": "#345563",
            "text-faint": "#4b6a78", "accent": "#0f766e", "on-accent": "#ffffff", "ok": "#147c3b",
            "warn": "#9c5f07", "bad": "#b91c1c", "unknown": "#556b76",
        },
    },
    "forest": {
        "name": "Forest floor",
        "dark": {
            "bg": "#10150f", "bg-elev": "#161d14", "surface": "#1c2519", "surface-hover": "#243020",
            "border": "#2a3825", "border-strong": "#3c4f35", "text": "#e8eddf", "text-muted": "#b7c2a8",
            "text-faint": "#9aa78a", "accent": "#a3c96b", "on-accent": "#15200b", "ok": "#86d17a",
            "warn": "#e0b84f", "bad": "#e88a6a", "unknown": "#8e9a80",
        },
        "light": {
            "bg": "#f3f5ee", "bg-elev": "#ffffff", "surface": "#fbfcf8", "surface-hover": "#e9eee0",
            "border": "#d8e0cb", "border-strong": "#c2cdb0", "text": "#1c2617", "text-muted": "#435238",
            "text-faint": "#566548", "accent": "#4d7a1f", "on-accent": "#ffffff", "ok": "#2f7d32",
            "warn": "#8a6212", "bad": "#b4432a", "unknown": "#5f6b55",
        },
    },
    "ember": {
        "name": "Ember",
        "dark": {
            "bg": "#141110", "bg-elev": "#1b1715", "surface": "#221d1a", "surface-hover": "#2c2521",
            "border": "#342b26", "border-strong": "#4a3d35", "text": "#f3ebe5", "text-muted": "#c9b8ab",
            "text-faint": "#ab998c", "accent": "#fb923c", "on-accent": "#231105", "ok": "#84cc16",
            "warn": "#fbbf24", "bad": "#f44462", "unknown": "#9b8c81",
        },
        "light": {
            "bg": "#faf5f1", "bg-elev": "#ffffff", "surface": "#ffffff", "surface-hover": "#f3eae3",
            "border": "#eadbd0", "border-strong": "#dbc6b6", "text": "#2a1d15", "text-muted": "#5c4638",
            "text-faint": "#6e5748", "accent": "#c2410c", "on-accent": "#ffffff", "ok": "#4d7c0f",
            "warn": "#9c5f07", "bad": "#be123c", "unknown": "#6f6056",
        },
    },
    "mist": {
        "name": "Morning mist",
        "dark": {
            "bg": "#15181d", "bg-elev": "#1b1f26", "surface": "#21262e", "surface-hover": "#2a303a",
            "border": "#2f3641", "border-strong": "#434c5a", "text": "#edf0f4", "text-muted": "#bcc3cf",
            "text-faint": "#a0a8b6", "accent": "#a5b4fc", "on-accent": "#141733", "ok": "#6ee7b7",
            "warn": "#fcd34d", "bad": "#fda4af", "unknown": "#98a0ad",
        },
        "light": {
            "bg": "#f4f5f8", "bg-elev": "#ffffff", "surface": "#ffffff", "surface-hover": "#eceef3",
            "border": "#dde1e8", "border-strong": "#c9ced8", "text": "#1d2230", "text-muted": "#475067",
            "text-faint": "#596178", "accent": "#4f46e5", "on-accent": "#ffffff", "ok": "#047857",
            "warn": "#92400e", "bad": "#be123c", "unknown": "#5b6275",
        },
    },
    "sandstone": {
        "name": "Sandstone",
        "dark": {
            "bg": "#1a1612", "bg-elev": "#211c17", "surface": "#29221c", "surface-hover": "#332b23",
            "border": "#3a3128", "border-strong": "#524538", "text": "#f2e9dc", "text-muted": "#cdbda6",
            "text-faint": "#b09f88", "accent": "#e4b363", "on-accent": "#231806", "ok": "#9ccc65",
            "warn": "#f0c052", "bad": "#ef8a73", "unknown": "#a39684",
        },
        "light": {
            "bg": "#f7f1e6", "bg-elev": "#fffdf8", "surface": "#fffdf8", "surface-hover": "#efe6d6",
            "border": "#e4d8c3", "border-strong": "#d3c3a7", "text": "#2e2418", "text-muted": "#5c4c38",
            "text-faint": "#6d5c47", "accent": "#9a5b13", "on-accent": "#ffffff", "ok": "#3f7a22",
            "warn": "#8f5e0a", "bad": "#b3402a", "unknown": "#6e6252",
        },
    },
    "graphite": {
        "name": "Graphite",
        "dark": {
            "bg": "#0c0c0d", "bg-elev": "#131314", "surface": "#1a1a1c", "surface-hover": "#232326",
            "border": "#2a2a2e", "border-strong": "#3d3d42", "text": "#f4f4f5", "text-muted": "#b8b8bf",
            "text-faint": "#9d9da6", "accent": "#d9f99d", "on-accent": "#141a05", "ok": "#86efac",
            "warn": "#fde047", "bad": "#fca5a5", "unknown": "#909098",
        },
        "light": {
            "bg": "#f4f4f5", "bg-elev": "#ffffff", "surface": "#ffffff", "surface-hover": "#ececee",
            "border": "#dcdce0", "border-strong": "#c6c6cc", "text": "#141416", "text-muted": "#45454d",
            "text-faint": "#57575f", "accent": "#3f6212", "on-accent": "#ffffff", "ok": "#166534",
            "warn": "#854d0e", "bad": "#b91c1c", "unknown": "#5c5c64",
        },
    },
    "plum": {
        "name": "Plum",
        "dark": {
            "bg": "#16101b", "bg-elev": "#1d1524", "surface": "#241a2d", "surface-hover": "#2e2239",
            "border": "#352841", "border-strong": "#4c3a5c", "text": "#f1e9f6", "text-muted": "#c7b5d3",
            "text-faint": "#aa97b8", "accent": "#e879f9", "on-accent": "#2a0a31", "ok": "#86efac",
            "warn": "#fcd34d", "bad": "#fb7185", "unknown": "#9d8ea9",
        },
        "light": {
            "bg": "#f8f3fa", "bg-elev": "#ffffff", "surface": "#ffffff", "surface-hover": "#f0e6f4",
            "border": "#e4d6ea", "border-strong": "#d1bddb", "text": "#261a2e", "text-muted": "#54405f",
            "text-faint": "#665271", "accent": "#a21caf", "on-accent": "#ffffff", "ok": "#147c3b",
            "warn": "#92400e", "bad": "#be123c", "unknown": "#6b5c73",
        },
    },
    "catppuccin": {
        "name": "Catppuccin",
        "dark": {
            "bg": "#181825", "bg-elev": "#1e1e2e", "surface": "#26263a", "surface-hover": "#313244",
            "border": "#313244", "border-strong": "#45475a", "text": "#cdd6f4", "text-muted": "#bac2de",
            "text-faint": "#a6adc8", "accent": "#cba6f7", "on-accent": "#11111b", "ok": "#a6e3a1",
            "warn": "#f9e2af", "bad": "#f38ba8", "unknown": "#9399b2",
        },
        "light": {
            "bg": "#e6e9ef", "bg-elev": "#eff1f5", "surface": "#f6f7fa", "surface-hover": "#dce0e8",
            "border": "#ccd0da", "border-strong": "#bcc0cc", "text": "#4c4f69", "text-muted": "#5c5f77",
            "text-faint": "#626576", "accent": "#8534ef", "on-accent": "#ffffff", "ok": "#2c7420",
            "warn": "#8a5b0f", "bad": "#cd0f38", "unknown": "#636675",
        },
    },
    "nord": {
        "name": "Nord",
        "dark": {
            "bg": "#242933", "bg-elev": "#2e3440", "surface": "#343b49", "surface-hover": "#3b4252",
            "border": "#3b4252", "border-strong": "#4c566a", "text": "#eceff4", "text-muted": "#d8dee9",
            "text-faint": "#b4bccb", "accent": "#88c0d0", "on-accent": "#2e3440", "ok": "#a3be8c",
            "warn": "#ebcb8b", "bad": "#d4999b", "unknown": "#a0a9b9",
        },
        "light": {
            "bg": "#e5e9f0", "bg-elev": "#eceff4", "surface": "#f4f6f9", "surface-hover": "#d8dee9",
            "border": "#d8dee9", "border-strong": "#c2cad8", "text": "#2e3440", "text-muted": "#3b4252",
            "text-faint": "#4c566a", "accent": "#486a90", "on-accent": "#ffffff", "ok": "#536d3d",
            "warn": "#9f4e33", "bad": "#ab434f", "unknown": "#4c566a",
        },
    },
    "dracula": {
        "name": "Dracula",
        "dark": {
            "bg": "#21222c", "bg-elev": "#282a36", "surface": "#2f3140", "surface-hover": "#3a3c4e",
            "border": "#3a3c4e", "border-strong": "#6272a4", "text": "#f8f8f2", "text-muted": "#d6d8e8",
            "text-faint": "#a9aed0", "accent": "#bd93f9", "on-accent": "#21222c", "ok": "#50fa7b",
            "warn": "#f1fa8c", "bad": "#ff6e6e", "unknown": "#9aa0c0",
        },
        "light": {
            "bg": "#f3eedb", "bg-elev": "#fffbeb", "surface": "#fffdf5", "surface-hover": "#ece6cf",
            "border": "#e3dcc2", "border-strong": "#cfc6a6", "text": "#1f1f1f", "text-muted": "#4a4636",
            "text-faint": "#6c664b", "accent": "#644ac9", "on-accent": "#ffffff", "ok": "#14710a",
            "warn": "#7c6613", "bad": "#c33828", "unknown": "#6c664b",
        },
    },
    "tokyonight": {
        "name": "Tokyo Night",
        "dark": {
            "bg": "#16161e", "bg-elev": "#1a1b26", "surface": "#1f2335", "surface-hover": "#292e42",
            "border": "#292e42", "border-strong": "#3b4261", "text": "#c0caf5", "text-muted": "#a9b1d6",
            "text-faint": "#8f98c2", "accent": "#7aa2f7", "on-accent": "#16161e", "ok": "#9ece6a",
            "warn": "#e0af68", "bad": "#f7768e", "unknown": "#838cb5",
        },
        "light": {
            "bg": "#d5d6db", "bg-elev": "#e1e2e7", "surface": "#e9e9ed", "surface-hover": "#c4c8da",
            "border": "#c4c8da", "border-strong": "#a8aecb", "text": "#343b58", "text-muted": "#3256ab",
            "text-faint": "#545a74", "accent": "#1358b1", "on-accent": "#ffffff", "ok": "#47632d",
            "warn": "#705730", "bad": "#b60a38", "unknown": "#51597a",
        },
    },
    "gruvbox": {
        "name": "Gruvbox",
        "dark": {
            "bg": "#1d2021", "bg-elev": "#282828", "surface": "#32302f", "surface-hover": "#3c3836",
            "border": "#3c3836", "border-strong": "#504945", "text": "#ebdbb2", "text-muted": "#d5c4a1",
            "text-faint": "#bdae93", "accent": "#fe8019", "on-accent": "#1d2021", "ok": "#b8bb26",
            "warn": "#fabd2f", "bad": "#fb6c5c", "unknown": "#a89984",
        },
        "light": {
            "bg": "#f2e5bc", "bg-elev": "#fbf1c7", "surface": "#fdf6d9", "surface-hover": "#ebdbb2",
            "border": "#ebdbb2", "border-strong": "#d5c4a1", "text": "#3c3836", "text-muted": "#504945",
            "text-faint": "#665c54", "accent": "#af3a03", "on-accent": "#ffffff", "ok": "#6a680c",
            "warn": "#885b0f", "bad": "#9d0006", "unknown": "#6d625a",
        },
    },
    "rosepine": {
        "name": "Rosé Pine",
        "dark": {
            "bg": "#191724", "bg-elev": "#1f1d2e", "surface": "#26233a", "surface-hover": "#2f2c45",
            "border": "#2a273f", "border-strong": "#403d52", "text": "#e0def4", "text-muted": "#c4c0dd",
            "text-faint": "#a8a4c2", "accent": "#ebbcba", "on-accent": "#191724", "ok": "#9ccfd8",
            "warn": "#f6c177", "bad": "#eb6f92", "unknown": "#908caa",
        },
        "light": {
            "bg": "#f2e9e1", "bg-elev": "#faf4ed", "surface": "#fffaf3", "surface-hover": "#f4ede8",
            "border": "#dfdad9", "border-strong": "#cecacd", "text": "#575279", "text-muted": "#5f5a82",
            "text-faint": "#686485", "accent": "#735d8f", "on-accent": "#ffffff", "ok": "#286983",
            "warn": "#915b10", "bad": "#a14e65", "unknown": "#696580",
        },
    },
}


def _luminance(colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(one: str, other: str) -> float:
    """The contrast ratio of two colours, from 1 to 21."""
    a, b = _luminance(one), _luminance(other)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def weak_spots(theme: dict[str, Any]) -> list[dict[str, Any]]:
    """Every colour of a theme that is read as text and falls below 4.5:1."""
    found = []
    for mode in ("dark", "light"):
        palette = theme.get(mode) or {}
        for token in TEXT:
            if token not in palette:
                continue
            worst = min((contrast(palette[token], palette[g]) for g in GROUNDS if g in palette), default=21.0)
            if worst < LEAST:
                found.append({"mode": mode, "token": token, "ratio": round(worst, 2)})
        if "accent" in palette and "on-accent" in palette and contrast(palette["accent"], palette["on-accent"]) < LEAST:
            found.append({"mode": mode, "token": "on-accent", "ratio": round(contrast(palette["accent"], palette["on-accent"]), 2)})
    return found


def check(incoming: Any) -> dict[str, Any] | None:
    """A theme as it may be stored, or None for nexdeck's own look.

    Refused in words: something that is not a theme, a colour that is not
    ``#rrggbb``, a name nobody set. A brightness left out keeps nexdeck's
    own colours there, and so does a colour left out.
    """
    if incoming is None or incoming == {}:
        return None
    if not isinstance(incoming, dict):
        raise ThemeError("A theme is a name and the colours for dark and for light.")
    name = str(incoming.get("name") or "").strip()[:40]
    if not name:
        raise ThemeError("A theme needs a name.")
    result: dict[str, Any] = {"name": name}
    for mode in ("dark", "light"):
        palette = incoming.get(mode)
        if palette is None:
            continue
        if not isinstance(palette, dict):
            raise ThemeError(f"The {mode} colours have to be a mapping of name to colour.")
        stray = sorted(set(palette) - set(TOKENS))
        if stray:
            raise ThemeError(f"{stray[0]!r} is not a colour a theme sets. These are: {', '.join(TOKENS)}.")
        for token, colour in palette.items():
            if not isinstance(colour, str) or not HEX.match(colour):
                raise ThemeError(f"{mode} {token} has to read like #1e293b, not {str(colour)[:20]!r}.")
        result[mode] = {token: palette[token].lower() for token in TOKENS if token in palette}
    if "dark" not in result and "light" not in result:
        raise ThemeError("A theme needs the colours for dark, for light, or both.")
    return result
