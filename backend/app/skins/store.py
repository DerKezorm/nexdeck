"""The skins of an installation: the ones nexdeck ships and the ones saved here.

Shipped skins are files in ``builtin/``, read once; saved ones are rows of
``skins``. Both are handed out the same way, compiled. A saved skin is
compiled when it is saved and again at start whenever the compiler changed
(``compile.ENGINE``); one that no longer compiles is kept, switched off, and
said so in the log, so an update never turns a board into an error page.
"""

from __future__ import annotations

import json
import logging
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSessionType

from ..models import Skin, utcnow
from . import compile as skin_compile
from .css import SkinCssError
from .schema import SkinFile

logger = logging.getLogger("nexdeck.skins")

BUILTIN_DIR = Path(__file__).with_name("builtin")
#: The skin that draws with nexdeck's own style sheet (``styles/retro.css``) and the card style it stood for.
NATIVE_1984 = "1984"


class SkinError(Exception):
    def __init__(self, message: str, code: str = "bad_skin", problems: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.problems = problems or []


@cache
def builtin() -> dict[str, tuple[SkinFile, dict[str, Any]]]:
    found = {}
    for path in sorted(BUILTIN_DIR.glob("*.json")):
        skin = SkinFile.model_validate_json(path.read_text(encoding="utf-8"))
        found[skin.key] = (skin, skin_compile.compile_skin(skin, builtin=True).as_json())
    return found


EXAMPLES_DIR = Path(__file__).with_name("examples")


@cache
def starters() -> list[dict[str, Any]]:
    """What a new skin can start from besides a copy of an installed one: nothing, a look nexdeck ships, an example.

    Each is a whole skin file as text, checked here once, so the editor never opens one that does not compile.
    """
    from ..services import themes

    found: list[dict[str, Any]] = [{"key": "empty", "kind": "empty", "name": "My skin", "text": json.dumps({"nexdeck_skin": 1, "key": "my-skin", "name": "My skin"}, indent=2)}]
    looks = json.loads((EXAMPLES_DIR / "looks.json").read_text(encoding="utf-8"))["looks"]
    for look in looks:
        theme = themes.THEMES.get(look["theme"]) if look["theme"] else None
        tokens: dict[str, Any] = {name: look[name] for name in ("card_style", "radius", "gap", "font") if name in look}
        if theme:
            tokens.update({mode: theme[mode] for mode in ("dark", "light") if theme.get(mode)})
        text = json.dumps({"nexdeck_skin": 1, "key": look["key"], "name": look["name"], "tokens": tokens}, indent=2)
        found.append({"key": look["key"], "kind": "look", "name": look["name"], "text": text})
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        if path.name == "looks.json":
            continue
        text = path.read_text(encoding="utf-8")
        found.append({"key": path.stem, "kind": "example", "name": json.loads(text)["name"], "text": text})
    for starter in found:
        skin_compile.compile_skin(read(starter["text"]))
    return found


def read(text: str) -> SkinFile:
    """The file checked, or SkinError with every problem a person can act on."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as failure:
        raise SkinError(f"The file is not JSON: {failure.msg} on line {failure.lineno}.", "not_json") from failure
    if not isinstance(data, dict) or data.get("nexdeck_skin") != 1:
        raise SkinError('A skin file starts with "nexdeck_skin": 1.', "not_a_skin")
    try:
        return SkinFile.model_validate(data)
    except ValidationError as failure:
        problems = [{"path": ".".join(str(step) for step in error["loc"]), "message": error["msg"]} for error in failure.errors()]
        raise SkinError("The file is not a skin nexdeck can wear.", "bad_skin", problems) from failure


def check(text: str) -> tuple[SkinFile, dict[str, Any]]:
    """Read and compile without storing: what the editor asks while somebody types."""
    skin = read(text)
    if skin.key in builtin():
        raise SkinError(f"{skin.key!r} is the name of a skin nexdeck ships; give yours another.", "taken")
    try:
        return skin, skin_compile.compile_skin(skin).as_json()
    except SkinCssError as failure:
        problems = [{"path": "css", "message": problem.message, "line": problem.line, "column": problem.column} for problem in failure.problems]
        raise SkinError("The skin cannot be worn as it is.", "bad_skin", problems) from failure


def listing(db: DbSessionType) -> list[dict[str, Any]]:
    rows = db.scalars(select(Skin).order_by(Skin.name)).all()
    shipped = [_entry(skin, compiled, "builtin") for skin, compiled in builtin().values()]
    return shipped + [_entry(SkinFile.model_validate_json(row.text), row.compiled, row.origin, row) for row in rows]


def _entry(skin: SkinFile, compiled: dict[str, Any], origin: str, row: Skin | None = None) -> dict[str, Any]:
    tokens = skin.tokens
    return {
        "key": skin.key, "name": skin.name, "description": skin.description, "author": skin.author,
        "version": skin.version, "origin": origin, "options": compiled.get("options", []),
        "native": skin.native, "wearable": bool(compiled),
        "swatches": [(tokens.dark or tokens.light or {}).get(name) for name in ("bg", "surface", "accent", "text")],
        "updated_at": row.updated_at.isoformat() if row is not None else None,
    }


def compiled(db: DbSessionType, key: str) -> dict[str, Any] | None:
    if key in builtin():
        return builtin()[key][1]
    row = db.scalar(select(Skin).where(Skin.key == key))
    return row.compiled or None if row is not None else None


def exists(db: DbSessionType, key: str) -> bool:
    return key in builtin() or db.scalar(select(Skin.id).where(Skin.key == key)) is not None


def choices(db: DbSessionType, key: str) -> dict[str, list[str]]:
    """The options a skin has and the values each takes."""
    found = compiled(db, key) or {}
    return {option["key"]: [choice["key"] for choice in option["choices"]] for option in found.get("options", [])}


def check_choice(db: DbSessionType, value: Any) -> dict[str, Any]:
    """``{"key", "options"}`` as somebody chose it, checked against the skins there are; ``{}`` is none."""
    if not value:
        return {}
    if not isinstance(value, dict) or not isinstance(value.get("key"), str):
        raise SkinError("A skin is chosen as {key, options}.", "bad_skin_choice")
    key = value["key"]
    if not exists(db, key):
        raise SkinError(f"There is no skin {key!r} here.", "no_such_skin")
    known = choices(db, key)
    options = value.get("options") or {}
    if not isinstance(options, dict) or any(known.get(name) is None or chosen not in known[name] for name, chosen in options.items()):
        named = "; ".join(f"{name} is {' or '.join(values)}" for name, values in known.items()) or "none"
        raise SkinError(f"The options of {key!r}: {named}.", "bad_skin_choice")
    return {"key": key, "options": {name: options.get(name, values[0]) for name, values in known.items()}}


def save(db: DbSessionType, text: str, user_id: int | None, *, replacing: str | None = None, origin: str = "own") -> dict[str, Any]:
    skin, result = check(text)
    row = db.scalar(select(Skin).where(Skin.key == (replacing or skin.key)))
    if replacing is None and row is not None:
        raise SkinError(f"There is a skin {skin.key!r} already.", "taken")
    if replacing is not None and row is None:
        raise SkinError(f"There is no skin {replacing!r} here.", "no_such_skin")
    if replacing is not None and skin.key != replacing and exists(db, skin.key):
        raise SkinError(f"There is a skin {skin.key!r} already.", "taken")
    if row is None:
        row = Skin(key=skin.key, name=skin.name, origin=origin, text=text, compiled=result, engine=skin_compile.ENGINE, created_by=user_id, updated_by=user_id)
        db.add(row)
    else:
        row.key, row.name, row.text, row.compiled, row.engine = skin.key, skin.name, text, result, skin_compile.ENGINE
        row.updated_by, row.updated_at = user_id, utcnow()
    db.commit()
    return _entry(skin, result, row.origin, row)


def delete(db: DbSessionType, key: str) -> None:
    row = db.scalar(select(Skin).where(Skin.key == key))
    if row is None:
        raise SkinError(f"There is no skin {key!r} here." if key not in builtin() else "A skin nexdeck ships stays.", "no_such_skin")
    db.delete(row)
    db.commit()


def file_text(db: DbSessionType, key: str) -> str:
    if key in builtin():
        return builtin()[key][0].model_dump_json(indent=2, exclude_defaults=True, by_alias=True)
    row = db.scalar(select(Skin).where(Skin.key == key))
    if row is None:
        raise SkinError(f"There is no skin {key!r} here.", "no_such_skin")
    return row.text


def recompile_stale(db: DbSessionType) -> int:
    """At start: compile again what an older compiler made. A skin that fails is switched off, not lost."""
    done = 0
    for row in db.scalars(select(Skin).where(Skin.engine != skin_compile.ENGINE)).all():
        try:
            row.compiled = skin_compile.compile_skin(SkinFile.model_validate_json(row.text)).as_json()
        except (ValidationError, SkinCssError) as failure:
            row.compiled = {}
            logger.warning("The skin %r no longer compiles and is switched off until it is saved again: %s", row.key, failure)
        row.engine = skin_compile.ENGINE
        done += 1
    db.commit()
    return done
