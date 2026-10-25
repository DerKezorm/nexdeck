"""Custom cards: list them, keep them, copy them, delete them, say who may place them (KARTEN-11).

Everything here is for administrators, except the library list, which tells every member what he may put on a board.
A card is kept as the text its author wrote (``cards/store.py``); this router only decides who may touch it and writes
it down in the log.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import get_adapter
from ..cards import load, schema, source, store
from ..deps import AdminUser, DbSession, MemberUser, error
from ..models import Board, CardRecord, Integration, Page, Role, Widget
from ..services.collector import collector
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])
logger = logging.getLogger("nexdeck.cards")


class CardText(BaseModel):
    """The text of a card, word for word as it is edited."""

    yaml: str = Field(max_length=schema.MAX_DEFINITION * 2)


class SharingBody(BaseModel):
    allowed: bool


def _invalid(failure: load.CardInvalid) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "card_invalid", "message": str(failure), **failure.detail()})


def _too_many() -> HTTPException:
    return error("too_many_cards", f"There are {store.MAX_CARDS} custom cards already, which is the most nexdeck keeps. Delete one first.", status.HTTP_409_CONFLICT)


def _row(db: Session, slug: str) -> CardRecord:
    row = db.scalar(select(CardRecord).where(CardRecord.slug == slug, CardRecord.kind == "card"))
    if row is None:
        raise error("not_found", "There is no such card.", status.HTTP_404_NOT_FOUND)
    return row


def _requirement(kind: str) -> dict[str, str]:
    """A kind of connection as people read it: its name and its logo."""
    if kind.startswith("custom:"):
        return {"kind": kind, "label": kind.partition(":")[2], "icon": ""}
    try:
        adapter = get_adapter(kind)
    except KeyError:
        return {"kind": kind, "label": kind, "icon": ""}
    return {"kind": kind, "label": adapter.label, "icon": adapter.icon}


def _placed(db: Session) -> dict[str, dict[int, tuple[str, str]]]:
    """Where each card stands: the boards that hold a widget of it, by the short name in the widget's options."""
    found: dict[str, dict[int, tuple[str, str]]] = {}
    query = (
        select(Widget.options, Board.id, Board.name, Board.slug)
        .join(Page, Page.id == Widget.page_id)
        .join(Board, Board.id == Page.board_id)
        .where(Widget.kind.like("custom.%"))
    )
    for options, board_id, board_name, board_slug in db.execute(query):
        slug = str((options or {}).get("card") or "")
        if slug:
            found.setdefault(slug, {})[board_id] = (board_slug, board_name)
    return found


def _view(row: CardRecord, placed: dict[str, dict[int, tuple[str, str]]]) -> dict[str, Any]:
    data = row.definition or {}
    boards = placed.get(row.slug, {})
    requires = [str(kind) for kind in data.get("requires", [])]
    return {
        "slug": row.slug,
        "name": data.get("name", row.slug),
        "description": data.get("description"),
        "form": data.get("form", ""),
        "version": data.get("version", ""),
        "author": data.get("author"),
        "requires": [_requirement(kind) for kind in requires],
        "origin": row.origin,
        "shop_version": row.shop_version,
        "boards": [{"id": number, "slug": at, "name": name} for number, (at, name) in sorted(boards.items(), key=lambda one: one[1][1].lower())],
        "users_may_place": row.users_may_place,
        "updated_at": row.updated_at,
    }


def _tell(db: Session, slug: str) -> None:
    """Every card of this definition fetches itself again and every open board hears it: a change shows at once (KARTEN-11)."""
    widgets = [w for w in db.scalars(select(Widget).where(Widget.kind.like("custom.%"))) if str((w.options or {}).get("card") or "") == slug]
    boards: set[int] = set()
    for widget in widgets:
        page = db.get(Page, widget.page_id)
        if page is not None:
            boards.add(page.board_id)
        collector.schedule(widget.id)
    for board_id in boards:
        hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})


# -- what the editor and the shop read -----------------------------------------------------


@router.get("/sources", summary="The kinds of connection a custom card can read through")
def sources(user: AdminUser) -> list[dict[str, Any]]:
    return source.sources()


@router.get("/schema", summary="The JSON schema of a custom card")
def json_schema(user: AdminUser) -> dict[str, Any]:
    return schema.json_schema()


# -- the library -----------------------------------------------------------------------


@router.get("/library", summary="The custom cards this account may put on a board, with the connections that fit")
def library(user: MemberUser, db: DbSession) -> dict[str, Any]:
    """Administrators see every card; anybody else only the ones released for users, and never a connection reserved for administrators (KARTEN-11 AC-2 to AC-4).

    ⚠️ ``fits`` is what the card could be placed on right now. A card with no fitting connection is still listed, so the
    library can offer to add the integration (AC-12).
    """
    admin = user.role == Role.admin.value
    connections = [
        one for one in db.scalars(select(Integration).order_by(Integration.name)) if (admin or not one.admin_only)
    ]
    out: list[dict[str, Any]] = []
    for row in store.listing(db):
        if not (admin or row.users_may_place):
            continue
        view = _view(row, {})
        needed = {entry["kind"] for entry in view["requires"]}
        fits = []
        for one in connections:
            if one.kind not in needed:
                continue
            try:
                if not get_adapter(one.kind).raw_access:
                    continue
            except KeyError:
                continue
            fits.append({"id": one.id, "name": one.name, "kind": one.kind})
        out.append({k: view[k] for k in ("slug", "name", "description", "form", "requires", "version")} | {"fits": fits})
    return {"cards": out}


# -- the list --------------------------------------------------------------------------


@router.get("", summary="List the custom cards")
def list_cards(user: AdminUser, db: DbSession) -> dict[str, Any]:
    placed = _placed(db)
    rows = store.listing(db)
    return {"cards": [_view(row, placed) for row in rows], "limit": store.MAX_CARDS}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Save a new custom card from its text")
def create_card(body: CardText, user: AdminUser, db: DbSession) -> dict[str, Any]:
    try:
        row = store.create(db, body.yaml, user_id=user.id)
    except load.CardInvalid as failure:
        raise _invalid(failure) from failure
    except store.TooManyCards:
        raise _too_many() from None
    logger.info("Custom card %r created by %s.", row.slug, user.username)
    return _view(row, {})


@router.get("/{slug}", summary="Read a custom card with its text")
def read_card(slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    row = _row(db, slug)
    return {**_view(row, _placed(db)), "yaml": row.yaml_source}


@router.put("/{slug}", summary="Replace the text of a custom card; every board shows the change at once")
def replace_card(slug: str, body: CardText, user: AdminUser, db: DbSession) -> dict[str, Any]:
    row = db.scalar(select(CardRecord).where(CardRecord.slug == slug, CardRecord.kind == "card"))
    if row is None:
        # ⚠️ Somebody else deleted it while this one had it open (KARTEN-11 EC-6). The editor says so and offers "Save as new".
        raise error("card_deleted", "This card was deleted meanwhile.", status.HTTP_404_NOT_FOUND)
    try:
        store.update(db, row, body.yaml)
    except load.CardInvalid as failure:
        raise _invalid(failure) from failure
    logger.info("Custom card %r changed by %s.", slug, user.username)
    _tell(db, slug)
    return {**_view(row, _placed(db)), "yaml": row.yaml_source}


@router.delete("/{slug}", summary="Delete a custom card; the cards that show it say that the definition is missing")
def delete_card(slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    row = _row(db, slug)
    boards = len(_placed(db).get(slug, {}))
    store.delete(db, row)
    logger.info("Custom card %r deleted by %s; it stood on %d board(s).", slug, user.username, boards)
    _tell(db, slug)
    return {"boards": boards}


def _free_slug(db: Session, slug: str) -> str:
    taken = {one.slug for one in store.listing(db)} | set(store.RESERVED_SLUGS)
    for number in range(1, 1000):
        suffix = "-copy" if number == 1 else f"-copy-{number}"
        candidate = f"{slug[: 60 - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
    raise error("no_free_name", "No free short name for a copy.")


@router.post("/{slug}/copy", status_code=status.HTTP_201_CREATED, summary="Make a copy of a custom card under a new short name")
def copy_card(slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """The copy is a card of this installation (``local``), shared with nobody, whatever the original was (KARTEN-11 AC-5)."""
    row = _row(db, slug)
    new = _free_slug(db, slug)
    try:
        lines = load.load_definition(row.yaml_source).lines
        number = lines.get(("slug",))
        if number is None:
            raise error("card_unreadable", "The short name of this card could not be found in its text.")
        text = row.yaml_source.split("\n")
        text[number - 1] = re.sub(r"^(\s*slug\s*:\s*)([\"']?)[^\s#\"']+\2", lambda found: f"{found.group(1)}{new}", text[number - 1], count=1)
        copy = store.create(db, "\n".join(text), user_id=user.id)
    except load.CardInvalid as failure:
        raise _invalid(failure) from failure
    except store.TooManyCards:
        raise _too_many() from None
    logger.info("Custom card %r copied to %r by %s.", slug, copy.slug, user.username)
    return _view(copy, {})


@router.put("/{slug}/users", summary="Say whether users may place a custom card, or only administrators")
def share_card(slug: str, body: SharingBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Taking it back leaves the cards that stand on boards where they are; only placing a new one is closed (KARTEN-11 EC-1)."""
    row = _row(db, slug)
    store.set_users_may_place(db, row, body.allowed)
    logger.info("Custom card %r %s for users by %s.", slug, "released" if body.allowed else "reserved for administrators", user.username)
    return _view(row, _placed(db))
