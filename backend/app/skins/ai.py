"""A skin made or changed by the provider of the assistant (skins, phase C).

The editor's tab "AI" sends what the administrator wrote, the skin as it is,
the sections they locked and, on a second round, what the stage looks like
in dark and in light mode: a picture of each where the provider can see one,
and what the stage found itself (text that cannot be read, parts that
vanished). Both modes, because a skin is worn in both: a first try that set
its cards dark in css read well on the dark stage and not at all on the light
one, and a look at one mode never told. Nothing else leaves: the
stage draws invented data, never the installation's.

What comes back is a skin file and nothing else. It is checked like any skin
(``schema.SkinFile`` and ``compile.compile_skin``); one that fails goes back
once with its problems, one that fails again is shown with them. Locked
sections are put back from the skin that was sent, whatever the provider did
with them, and the skin keeps its key.

The build guide (:func:`guide`) is written from ``parts.json`` and the schema,
so it can never name a part or a property nexdeck does not have; a test holds
it to that.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..cards import ai as card_ai
from ..services.assistant import providers
from . import compile as skin_compile
from . import css, schema

#: The top-level sections of a skin file a lock can hold.
SECTIONS = ("tokens", "options", "sprites", "frames", "desk", "decorations", "status", "parts", "sounds", "switches", "css")
#: A picture of the stage, base64: a JPEG of the stage at 1024 pixels is far below this.
MAX_IMAGE = 1_500_000
IMAGE_TYPES = ("image/jpeg", "image/png")
MODES = ("dark", "light")
MAX_AUDIT = 40

SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_skin",
    "description": "Hand in the finished skin: the whole skin file as a JSON object, and in one or two sentences what you made or changed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "skin": {"type": "object", "description": "The whole skin file, starting with nexdeck_skin: 1."},
            # Here and not as words beside the tool: Claude called the tool and said nothing, and the editor showed only that something changed.
            "summary": {"type": "string", "description": "One or two sentences in the language of the request: what you made or changed."},
        },
        "required": ["skin", "summary"],
        "additionalProperties": False,
    },
}

_FENCE = re.compile(r"```(?:json)?[ \t]*\r?\n(.*?)```", re.DOTALL)
EXAMPLE = (Path(__file__).with_name("examples") / "console.json").read_text(encoding="utf-8")


@dataclass
class Picture:
    """The stage in one mode, base64."""

    mode: str
    data: str
    media_type: str = "image/jpeg"


@dataclass
class Ask:
    prompt: str
    skin: dict[str, Any]
    locked: list[str] = field(default_factory=list)
    #: The second round: the stage as it looks now, to improve the skin once.
    review: bool = False
    pictures: list[Picture] = field(default_factory=list)
    audit: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    ok: bool
    skin: dict[str, Any]
    text: str
    problems: list[dict[str, Any]]
    #: What the provider counted over every round, for the log.
    tokens_in: int = 0
    tokens_out: int = 0

    def body(self) -> dict[str, Any]:
        return {"ok": self.ok, "skin": self.skin, "text": self.text, "problems": self.problems}


def guide() -> str:
    """What the provider is told a skin is: written from parts.json and the schema, never by hand."""
    data = css.registry()
    lines = [
        "You design skins for nexdeck, a dashboard for a homelab. A skin is a JSON file and nothing else: no code, nothing that is fetched.",
        "Hand in the whole skin with the tool submit_skin. Keep its key. Its summary says in one or two sentences, in the language of the request, what you made.",
        "A skin is worn in dark and in light mode. A colour set in css for one of them goes under :mode(dark) or :mode(light), with its partner for the other; "
        "the palettes dark and light do the rest.",
        "",
        "# The file",
        '{"nexdeck_skin": 1, "key": "…", "name": "…", "description": "…", "tokens": {…}, "options": […], "sprites": {…}, "frames": {…}, '
        '"desk": {…}, "decorations": […], "status": {…}, "parts": {…}, "sounds": {…}, "switches": {…}, "css": "…"}. Every section is optional.',
        "",
        "## tokens (colours, corners, type)",
        f"dark and light: each a palette that sets all of {', '.join(css_tokens())} as #rrggbb. Text colours must reach 4.5:1 against bg, bg-elev and surface.",
        f"accent: #rrggbb. font: one of {', '.join(data['fonts'])}. radius: 0 to 28. gap: 4 to 28. card_style: one of {', '.join(schema.CARD_STYLES)}.",
        "",
        "## sprites (little pixel pictures)",
        f"\"name\": {{\"palette\": {{\"K\": \"#1a1a1a\", …}}, \"rows\": [\"..KK..\", …], \"tint\": false}}. At most {schema.MAX_SIDE}x{schema.MAX_SIDE} pixels, "
        f"{schema.MAX_COLOURS} colours, {schema.MAX_SPRITES} sprites. Every row equally long; '.' is see-through. 8x8 to 16x16 reads best. "
        "tint: true keeps only the shape, coloured like the text.",
        "",
        "## frames, desk, decorations, status",
        'frames: {"name": {"sprite": "…", "slice": 2, "width": 4, "repeat": "round"}}: a border cut from a sprite, slice pixels from each side.',
        'desk: {"tile": "sprite", "scale": 1 to 8}: a tile repeated behind the cards.',
        f'decorations: [{{"part": "…", "anchor": one of {", ".join(schema.ANCHORS)}, "sprite": "…", "size": 8 to 32, "offset": -16 to 16}}], only on parts with a free place (below).',
        'status: {"ok": "sprite", "warn": "sprite", "bad": "sprite", "unknown": "sprite"}: the lights of a card. ok, warn and bad must differ in shape, not only in colour.',
        "",
        "## parts, sounds, switches, options",
        f'parts: {{"part": {{"frame": "…", "motion": {{"name": one of {", ".join(schema.MOTIONS)}, "on": "hover|press|always", '
        f'"ms": {css.ANIMATION_MS[0]} to {css.ANIMATION_MS[1]}}}, "sound": "…"}}}}.',
        f'sounds: {{"name": {{"wave": one of {", ".join(schema.WAVES)}, "from": 40 to 4000, "to": 40 to 4000, "ms": 20 to 600, "volume": 0.01 to 0.2}}}}.',
        'switches: {"corners": "square", "shadows": "none", "blur": "off"}, each optional.',
        'options: [{"key": "desk", "label": "Desk", "default": "bricks", "choices": [{"key": "bricks", "label": "Bricks"}, {"key": "plain", "label": "Plain"}]}]: choices for the wearer.',
        "",
        "## css (only what the rest cannot do)",
        "Selectors name parts as [data-part=name], never classes or elements, with :hover, :active, :focus-visible, :state(x), :option(key=value), "
        ":mode(dark|light), and ::before or ::after on the last part where it is free. Parts combine with a space or >.",
        f"Properties: {', '.join(sorted({p for group, members in data['groups'].items() if group != 'pseudo' for p in members}))}. "
        f"On ::before and ::after also {', '.join(data['groups']['pseudo'])} (position only absolute, z-index -1 to 10, content only sprite(name) or at most "
        f"{css.CONTENT_CHARACTERS} characters).",
        f"Functions: {', '.join(sorted(css.FUNCTIONS))}. sprite(name) puts in a sprite, font(key) a font, var() reads --nd-* colours and --sk-* of the skin.",
        f"Not on containers ({', '.join(name for name, part in data['parts'].items() if part.get('container'))}): {', '.join(data['container_refused'])}.",
        "Never: url(), !important, @import, @font-face, position other than absolute, a --nd-* of its own. @keyframes and @media (min-width, max-width, "
        "prefers-reduced-motion) are allowed; animations last 340 to 2000 ms.",
        "",
        "# The parts",
    ]
    for name, part in data["parts"].items():
        extra = []
        if part.get("states"):
            extra.append("states " + ", ".join(part["states"]))
        if part["pseudo"]:
            extra.append("free " + " ".join(part["pseudo"]))
        lines.append(f"- {name}: {part['label']}" + (f" ({'; '.join(extra)})" if extra else ""))
    lines += ["", "# An example", EXAMPLE.strip()]
    return "\n".join(lines)


def css_tokens() -> tuple[str, ...]:
    from ..services import themes

    return themes.TOKENS


def outbound(ask: Ask) -> tuple[str, list[dict[str, Any]]]:
    """The system and the first message: everything that leaves is built here."""
    locked = [section for section in ask.locked if section in SECTIONS]
    parts = [f"The request: {ask.prompt.strip() or '(none, improve the skin as it is)'}", "", "The skin as it is now:", json.dumps(ask.skin, ensure_ascii=False)]
    if locked:
        parts += ["", f"Locked, leave exactly as they are: {', '.join(locked)}."]
    pictures = [picture for picture in ask.pictures if picture.mode in MODES] if ask.review else []
    if ask.review:
        shown = " and ".join(f"{picture.mode} mode" for picture in pictures)
        parts += ["", "This is a second look at your skin as nexdeck draws it" + (f" (the pictures show the stage with invented data: {shown}, in this order)." if pictures else ".")]
        if ask.audit:
            parts += ["The stage found:", *(f"- {finding}" for finding in ask.audit[:MAX_AUDIT])]
        parts += ["Improve the skin once where it does not yet look like the request or reads badly in either mode, or hand it in unchanged."]
    message: dict[str, Any] = {"role": "user", "text": "\n".join(parts)}
    if pictures:
        message["images"] = [{"media_type": picture.media_type, "data": picture.data} for picture in pictures]
    return guide(), [message]


def candidate(turn: providers.Turn) -> Any:
    for call in turn.calls:
        if call.get("name") == "submit_skin" and isinstance(call.get("input", {}).get("skin"), dict):
            return call["input"]["skin"]
    found = _FENCE.search(turn.text)
    try:
        return json.loads(found.group(1) if found else turn.text)
    except (json.JSONDecodeError, TypeError):
        return None


def summary(turn: providers.Turn) -> str:
    """What the provider says it made: the summary it handed in with the skin, else its words beside it."""
    for call in turn.calls:
        said = call.get("input", {}).get("summary") if call.get("name") == "submit_skin" else None
        if isinstance(said, str) and said.strip():
            return said.strip()
    return turn.text.strip()


def kept(ask: Ask, proposed: Any) -> dict[str, Any] | None:
    """The proposal with what may not change put back: the key, the format and every locked section."""
    if not isinstance(proposed, dict):
        return None
    skin = dict(proposed)
    skin["nexdeck_skin"] = 1
    skin["key"] = ask.skin.get("key", skin.get("key"))
    for section in ask.locked:
        if section not in SECTIONS:
            continue
        if section in ask.skin:
            skin[section] = ask.skin[section]
        else:
            skin.pop(section, None)
    return skin


def problems_of(skin: dict[str, Any] | None) -> list[dict[str, Any]]:
    if skin is None:
        return [{"path": "", "message": "No skin came back: hand it in with submit_skin as a JSON object."}]
    try:
        skin_compile.compile_skin(schema.SkinFile.model_validate(skin))
    except ValidationError as failure:
        return [{"path": ".".join(str(step) for step in error["loc"]), "message": error["msg"]} for error in failure.errors()]
    except css.SkinCssError as failure:
        return [{"path": "css", "message": problem.message, "line": problem.line} for problem in failure.problems]
    return []


def _feedback(problems: list[dict[str, Any]]) -> str:
    lines = [f"- {problem['message']}" + (f" (line {problem['line']} of css)" if problem.get("line") else f" ({problem['path']})" if problem.get("path") else "") for problem in problems[:25]]
    return "nexdeck did not accept this skin. What is wrong:\n" + "\n".join(lines) + "\nHand in the whole corrected skin with submit_skin."


async def generate(ask: Ask, config: dict[str, Any], key: str) -> Outcome:
    system, transcript = outbound(ask)
    tools = [SUBMIT_TOOL]
    skin: dict[str, Any] | None = None
    problems: list[dict[str, Any]] = []
    text = ""
    counted = [0, 0]
    for _round in range(2):
        turn = await card_ai._turn(config, key, system, transcript, tools)
        counted = [counted[0] + turn.tokens_in, counted[1] + turn.tokens_out]
        text = summary(turn)
        skin = kept(ask, candidate(turn))
        problems = problems_of(skin)
        if not problems:
            return Outcome(True, skin or {}, text, [], *counted)
        feedback = _feedback(problems)
        transcript.append({"role": "assistant", "text": turn.text, "calls": turn.calls, "provider": config["provider"], "raw": turn.raw})
        if turn.calls:
            transcript.append({"role": "tool", "results": [{"id": call["id"], "content": feedback, "is_error": True} for call in turn.calls]})
        else:
            transcript.append({"role": "user", "text": feedback})
    return Outcome(False, skin or {}, text, problems, *counted)
