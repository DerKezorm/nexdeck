"""Skins: the list everyone wears from, what a browser is handed of one, and saving them (administrators)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from ..deps import AdminUser, DbSession, OptionalUser, error, kiosk_from_request
from ..services import appearance
from ..skins import compile as skin_compile
from ..skins import css, schema, store

router = APIRouter(prefix="/api/v1/skins", tags=["system"])

logger = logging.getLogger("nexdeck.skins")

#: A skin file with its sprites stays far below this; the cap is against a payload, not a look.
MAX_FILE = 200_000


class SkinText(BaseModel):
    text: str = Field(max_length=MAX_FILE)


def _signed_in(request: Request, user: Any, db: DbSession) -> None:
    if user is None and kiosk_from_request(request, db) is None:
        raise error("unauthenticated", "Sign in first.", status.HTTP_401_UNAUTHORIZED)


def _refused(failure: store.SkinError) -> Exception:
    exception = error(failure.code, failure.message)
    exception.detail["problems"] = failure.problems  # type: ignore[index]
    return exception


@router.get("", summary="List the skins of this installation")
def listing(request: Request, user: OptionalUser, db: DbSession) -> dict:
    _signed_in(request, user, db)
    return {"skins": store.listing(db), "default": appearance.stored(db)["skin"]}


@router.get("/schema", summary="What a skin may hold: parts, properties, functions, motions, limits")
def described(admin: AdminUser) -> dict:
    data = css.registry()
    return {
        "parts": data["parts"], "groups": data["groups"], "container_refused": data["container_refused"],
        "fonts": list(data["fonts"]), "functions": sorted(css.FUNCTIONS), "motions": list(schema.MOTIONS),
        "waves": list(schema.WAVES), "anchors": list(schema.ANCHORS), "card_styles": list(schema.CARD_STYLES),
        "limits": {
            "css": css.MAX_CSS, "sprites": schema.MAX_SPRITES, "side": schema.MAX_SIDE, "colours": schema.MAX_COLOURS,
            "animation_ms": list(css.ANIMATION_MS), "transition_ms": list(css.TRANSITION_MS), "content": css.CONTENT_CHARACTERS,
        },
        "engine": skin_compile.ENGINE,
    }


@router.get("/starters", summary="What a new skin can start from: nothing, a look nexdeck ships, an example")
def starting_points(admin: AdminUser) -> dict:
    return {"starters": store.starters()}


@router.post("/check", summary="Check and compile a skin without saving it")
def check(body: SkinText, admin: AdminUser) -> dict:
    """Asked while somebody edits: always 200, with what is wrong in ``problems``."""
    try:
        _skin, compiled = store.check(body.text)
    except store.SkinError as failure:
        return {"ok": False, "code": failure.code, "message": failure.message, "problems": failure.problems}
    return {"ok": True, "compiled": compiled, "problems": []}


@router.get("/{key}/compiled", summary="What a browser needs to wear a skin")
def compiled(key: str, request: Request, response: Response, user: OptionalUser, db: DbSession) -> Any:
    _signed_in(request, user, db)
    found = store.compiled(db, key)
    if found is None:
        raise error("no_such_skin", f"There is no skin {key!r} here, or it is switched off.", status.HTTP_404_NOT_FOUND)
    tag = '"' + hashlib.sha256(json.dumps(found, sort_keys=True).encode()).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": tag})
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = "private, no-cache"
    return found


@router.get("/{key}/file", summary="A skin as a file to share")
def file(key: str, admin: AdminUser, db: DbSession) -> Response:
    try:
        text = store.file_text(db, key)
    except store.SkinError as failure:
        raise error(failure.code, failure.message, status.HTTP_404_NOT_FOUND) from failure
    return Response(text, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{key}.nexdeck-skin.json"'})


@router.post("", summary="Save a new skin", status_code=status.HTTP_201_CREATED)
def create(body: SkinText, admin: AdminUser, db: DbSession) -> dict:
    try:
        saved = store.save(db, body.text, admin.id)
    except store.SkinError as failure:
        raise _refused(failure) from failure
    logger.info("The skin %r was saved by %s.", saved["key"], admin.username)
    return saved


@router.put("/{key}", summary="Change a skin")
def change(key: str, body: SkinText, admin: AdminUser, db: DbSession) -> dict:
    try:
        saved = store.save(db, body.text, admin.id, replacing=key)
    except store.SkinError as failure:
        raise _refused(failure) from failure
    logger.info("The skin %r was changed by %s.", saved["key"], admin.username)
    return saved


@router.delete("/{key}", summary="Delete a skin", status_code=status.HTTP_204_NO_CONTENT)
def remove(key: str, admin: AdminUser, db: DbSession) -> Response:
    if appearance.stored(db)["skin"].get("key") == key:
        raise error("skin_in_use", "Everybody wears this skin; choose another for the installation first.")
    try:
        store.delete(db, key)
    except store.SkinError as failure:
        raise error(failure.code, failure.message, status.HTTP_404_NOT_FOUND) from failure
    logger.info("The skin %r was deleted by %s.", key, admin.username)
    # Whoever wore it wears the installation's again; the account keeps no choice of a skin that is gone.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import", summary="Bring in a skin, a look or a theme as a skin", status_code=status.HTTP_201_CREATED)
def bring_in(body: SkinText, admin: AdminUser, db: DbSession) -> dict:
    try:
        text = _as_skin(body.text, db)
        saved = store.save(db, text, admin.id)
    except store.SkinError as failure:
        raise _refused(failure) from failure
    logger.info("The skin %r was imported by %s.", saved["key"], admin.username)
    return saved


def _as_skin(text: str, db: DbSession) -> str:
    """A look (``nexdeck_look``) or a theme (``nexdeck_theme``) is a skin of the first layer only."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as failure:
        raise store.SkinError(f"The file is not JSON: {failure.msg} on line {failure.lineno}.", "not_json") from failure
    if not isinstance(data, dict):
        raise store.SkinError("The file is not a skin, a look or a theme.", "not_a_skin")
    if data.get("nexdeck_skin") == 1:
        return text
    look = data if data.get("nexdeck_look") == 1 else {"theme": data} if data.get("nexdeck_theme") == 1 or "dark" in data or "light" in data else None
    if look is None:
        raise store.SkinError("The file is not a skin, a look or a theme.", "not_a_skin")
    if look.get("card_style") == "window":
        raise store.SkinError("This look is 1984, which is here already: choose the skin 1984.", "is_1984")
    theme = look.get("theme") if isinstance(look.get("theme"), dict) else {}
    name = str(theme.get("name") or "Imported look")[:60]
    tokens: dict[str, Any] = {key: theme[key] for key in ("dark", "light") if isinstance(theme.get(key), dict)}
    for key in ("accent", "font", "radius", "gap", "card_style"):
        if look.get(key) not in (None, ""):
            tokens[key] = look[key]
    return json.dumps({"nexdeck_skin": 1, "key": _free_key(name, db), "name": name, "tokens": tokens})


def _free_key(name: str, db: DbSession) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "look"
    if not base[0].isalnum():
        base = "look-" + base
    key, number = base, 2
    while store.exists(db, key):
        key, number = f"{base}-{number}", number + 1
    return key
