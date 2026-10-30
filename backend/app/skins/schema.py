"""A skin as a file: ``{"nexdeck_skin": 1, …}``.

Three layers, each optional. The first is tokens: colours for dark and light,
the accent, the font, corners, gaps and the card style, checked for contrast
like any theme. The second is building blocks that are only data: sprites
drawn as rows of characters, frames cut from them, a desk tile, decorations,
status symbols, motions from nexdeck's list and synth sounds. The third is a
style sheet of its own, which ``css.py`` checks and rewrites. A skin carries
no code and nothing that fetches; ``native`` (a style sheet of nexdeck's own,
1984) is for the skins nexdeck ships and refused anywhere else.

Editor state (locks, undo) is not part of the file.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ..services import appearance, themes
from . import css as sheet

Key = Annotated[str, StringConstraints(pattern=sheet.KEY.pattern)]
Hex = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Label = Annotated[str, StringConstraints(min_length=1, max_length=60)]
SpriteName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,23}$")]

FORMAT = 1
MAX_SPRITES = 64
MAX_SIDE = 32
MAX_COLOURS = 16
#: Motions nexdeck draws; the keyframes are its own (``compile.MOTIONS``).
MOTIONS = ("hop", "wiggle", "spin", "pulse", "sink", "fade")
WAVES = ("square", "triangle", "sine", "sawtooth")
ANCHORS = ("top-left", "top-right", "bottom-left", "bottom-right")
CARD_STYLES = tuple(style for style in appearance.CARD_STYLES if style != "window")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tokens(_Strict):
    """The first layer: what a theme and the look's settings set, all optional."""

    dark: dict[str, Hex] | None = None
    light: dict[str, Hex] | None = None
    accent: Hex | None = None
    font: Literal[appearance.FONTS] | None = None  # type: ignore[valid-type]
    radius: Annotated[int, Field(ge=appearance.RADIUS[0], le=appearance.RADIUS[1])] | None = None
    gap: Annotated[int, Field(ge=appearance.GAP[0], le=appearance.GAP[1])] | None = None
    card_style: Literal[CARD_STYLES] | None = None  # type: ignore[valid-type]

    @field_validator("dark", "light")
    @classmethod
    def _known(cls, palette: dict[str, str] | None) -> dict[str, str] | None:
        if palette is None:
            return None
        unknown = sorted(set(palette) - set(themes.TOKENS))
        if unknown:
            raise ValueError(f"no such colour {', '.join(unknown)}; a palette knows {', '.join(themes.TOKENS)}")
        # Whole, so its contrast can be checked here and not only against whatever theme it lands on.
        missing = [name for name in themes.TOKENS if name not in palette]
        if missing:
            raise ValueError(f"a palette sets every colour; {', '.join(missing)} missing")
        return {name: value.lower() for name, value in palette.items()}


class Choice(_Strict):
    key: Key
    label: Label


class Option(_Strict):
    key: Key
    label: Label
    choices: Annotated[list[Choice], Field(min_length=2, max_length=6)]
    default: Key

    @model_validator(mode="after")
    def _default_is_a_choice(self) -> Option:
        if self.default not in {choice.key for choice in self.choices}:
            raise ValueError(f"the default {self.default!r} is not one of the choices")
        return self


class Sprite(_Strict):
    """Rows of characters, each a colour of the palette; ``.`` is see-through. ``tint`` uses the shape only."""

    palette: dict[Annotated[str, StringConstraints(min_length=1, max_length=1)], Hex]
    rows: Annotated[list[str], Field(min_length=1, max_length=MAX_SIDE)]
    tint: bool = False

    @model_validator(mode="after")
    def _drawn(self) -> Sprite:
        if len(self.palette) > MAX_COLOURS:
            raise ValueError(f"a sprite has at most {MAX_COLOURS} colours")
        if "." in self.palette:
            raise ValueError("'.' is see-through and needs no colour")
        width = len(self.rows[0])
        if not 1 <= width <= MAX_SIDE or any(len(row) != width for row in self.rows):
            raise ValueError(f"every row of a sprite is equally long, at most {MAX_SIDE}")
        stray = sorted({char for row in self.rows for char in row} - set(self.palette) - {"."})
        if stray:
            raise ValueError(f"no colour for {''.join(stray)!r} in the palette")
        return self


class Frame(_Strict):
    """A border cut from a sprite: ``slice`` pixels of it from each side, drawn ``width`` pixels wide."""

    sprite: SpriteName
    slice: Annotated[int, Field(ge=1, le=MAX_SIDE // 2)]
    width: Annotated[int, Field(ge=1, le=16)]
    repeat: Literal["stretch", "repeat", "round"] = "round"


class Desk(_Strict):
    tile: SpriteName
    scale: Annotated[int, Field(ge=1, le=8)] = 2


class Decoration(_Strict):
    part: str
    anchor: Literal[ANCHORS]  # type: ignore[valid-type]
    sprite: SpriteName
    size: Annotated[int, Field(ge=8, le=32)] = 16
    offset: Annotated[int, Field(ge=-16, le=16)] = 0


class Status(_Strict):
    ok: SpriteName
    warn: SpriteName
    bad: SpriteName
    unknown: SpriteName | None = None


class Motion(_Strict):
    name: Literal[MOTIONS]  # type: ignore[valid-type]
    on: Literal["hover", "press", "always"] = "hover"
    ms: Annotated[int, Field(ge=sheet.ANIMATION_MS[0], le=sheet.ANIMATION_MS[1])] = 400


class Sound(_Strict):
    wave: Literal[WAVES] = "square"  # type: ignore[valid-type]
    start: Annotated[int, Field(ge=40, le=4000, alias="from")] = 520
    to: Annotated[int, Field(ge=40, le=4000)] = 1040
    ms: Annotated[int, Field(ge=20, le=600)] = 120
    volume: Annotated[float, Field(ge=0.01, le=0.2)] = 0.06

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PartLook(_Strict):
    frame: SpriteName | None = None
    motion: Motion | None = None
    sound: SpriteName | None = None


class Switches(_Strict):
    """Things only nexdeck's own rules can do, offered as data."""

    corners: Literal["square"] | None = None
    shadows: Literal["none"] | None = None
    blur: Literal["off"] | None = None


class SkinFile(_Strict):
    nexdeck_skin: Literal[1]
    key: Key
    name: Label
    description: Annotated[str, StringConstraints(max_length=280)] = ""
    author: Annotated[str, StringConstraints(max_length=60)] = ""
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+(\.\d+)?$")] = "1.0"
    tokens: Tokens = Field(default_factory=Tokens)
    options: Annotated[list[Option], Field(max_length=6)] = Field(default_factory=list)
    sprites: dict[SpriteName, Sprite] = Field(default_factory=dict)
    frames: dict[SpriteName, Frame] = Field(default_factory=dict)
    desk: Desk | None = None
    decorations: Annotated[list[Decoration], Field(max_length=16)] = Field(default_factory=list)
    status: Status | None = None
    parts: dict[str, PartLook] = Field(default_factory=dict)
    sounds: dict[SpriteName, Sound] = Field(default_factory=dict)
    switches: Switches = Field(default_factory=Switches)
    css: Annotated[str, StringConstraints(max_length=sheet.MAX_CSS)] = ""
    native: Literal["retro"] | None = None

    @model_validator(mode="after")
    def _references(self) -> SkinFile:
        known_parts = sheet.registry()["parts"]
        if len(self.sprites) > MAX_SPRITES:
            raise ValueError(f"a skin has at most {MAX_SPRITES} sprites")
        if len({option.key for option in self.options}) != len(self.options):
            raise ValueError("two options have the same key")
        wanted = [frame.sprite for frame in self.frames.values()]
        wanted += [self.desk.tile] if self.desk else []
        wanted += [decoration.sprite for decoration in self.decorations]
        wanted += [name for name in (self.status.model_dump().values() if self.status else ()) if name]
        missing = sorted(set(wanted) - set(self.sprites))
        if missing:
            raise ValueError(f"no sprite {', '.join(missing)}")
        for part, look in self.parts.items():
            if part not in known_parts:
                raise ValueError(f"there is no part {part!r}")
            if look.frame and look.frame not in self.frames:
                raise ValueError(f"{part}: no frame {look.frame!r}")
            if look.sound and look.sound not in self.sounds:
                raise ValueError(f"{part}: no sound {look.sound!r}")
        for decoration in self.decorations:
            if decoration.part not in known_parts:
                raise ValueError(f"there is no part {decoration.part!r}")
            if not known_parts[decoration.part]["pseudo"]:
                raise ValueError(f"{decoration.part} leaves no place free for a decoration")
        return self


#: For a text that is not even JSON, or not a skin.
MARKER = re.compile(r'"nexdeck_skin"\s*:\s*1')
