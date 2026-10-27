"""Widgets: create, change, refresh, act, reachability checks and history."""

from __future__ import annotations

import copy
import logging
import re
import time
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..adapters import split_widget_kind
from ..adapters.base import AdapterError, Context, outbound_client
from ..db import db_session
from ..deps import (
    AdminUser,
    CurrentUser,
    DbSession,
    NotReadOnly,
    OptionalUser,
    board_for_viewer_id,
    error,
    kiosk_from_request,
    optional_user,
    require_board_id,
)
from ..models import HealthCheck, Integration, Page, Role, User, Widget
from ..schemas import (
    ActionBody,
    HealthBody,
    NoteBody,
    WidgetCopy,
    WidgetCreate,
    WidgetMove,
    WidgetPatch,
    WidgetPreview,
)
from ..services import app_keys, chronicle, favicons, grid, history, holders, impact
from ..services import health as health_service
from ..services.boards import (
    GROUP_KINDS,
    _validate_options,
    card_sizes,
    clean_cards,
    place_widget,
    remove_from_layouts,
    widget_view,
)
from ..services.collector import collector
from ..services.hass_ws import hass_listener
from ..services.notify import emit
from ..services.sse import Recheck, board_topic, hub
from ..services.state import live
from .assets import unsafe_svg

router = APIRouter(prefix="/api/v1", tags=["widgets"])

logger = logging.getLogger("nexdeck.widgets")


def _widget(db: DbSession, widget_id: int) -> tuple[Widget, Page]:
    widget = db.get(Widget, widget_id)
    if widget is None:
        raise error("not_found", "There is no such widget.", status.HTTP_404_NOT_FOUND)
    page = db.get(Page, widget.page_id)
    if page is None:
        # ⚠️ Not an ``assert``: under ``python -O`` that is not there, and
        # without it a card deleted a moment ago ended in a 500.
        raise error("not_found", "There is no such widget.", status.HTTP_404_NOT_FOUND)
    return widget, page


def _validate_kind(db: DbSession, kind: str, integration_id: int | None, user: User | None = None) -> None:
    try:
        adapter, _ = split_widget_kind(kind)
    except KeyError as failure:
        raise error("unknown_kind", f"There is no widget kind {kind!r}.") from failure
    if integration_id is not None:
        integration = db.get(Integration, integration_id)
        if integration is None:
            raise error("not_found", "There is no such integration.", status.HTTP_404_NOT_FOUND)
        # A locked connection is the administrator's alone to build on. What he
        # has already built keeps running for everyone he shared it with.
        if integration.admin_only and user is not None and user.role != Role.admin.value:
            raise error("integration_locked", "This connection is reserved for administrators.", status.HTTP_403_FORBIDDEN)
        # An app tile may follow any service; every other widget needs its own kind.
        if integration.kind != adapter.kind and kind != "core.app":
            raise error("kind_mismatch", f"A {kind} widget needs a {adapter.label} integration, not {integration.kind}.")


def _refuse_unless_cards(page: Page) -> None:
    """Cards stand on card pages only: a network plan or a home page has no grid to hold them.

    ⚠️ Checked wherever a card arrives, not only where one is made: moving a
    card onto a network plan used to work and left it on a page that never
    shows it.
    """
    if page.kind == "topology":
        raise error("topology_page", "A topology page holds a network plan, not cards. Add the card to another page.")
    if page.kind == "home":
        raise error("home_page", "A home page holds controls, not cards. Add the card to another page.")


def _refuse_a_taken_alias(db: DbSession, board_id: int, widget_id: int | None, kind: str, options: dict | None) -> None:
    from ..services import aliases

    try:
        aliases.refuse_taken(db, board_id, widget_id, kind, options)
    except aliases.AliasRefused as refused:
        raise error(refused.code, str(refused), status.HTTP_409_CONFLICT if refused.code == "alias_taken" else 400) from None


@router.post("/pages/{page_id}/widgets", status_code=status.HTTP_201_CREATED, summary="Add a widget to a page")
def create_widget(page_id: int, body: WidgetCreate, user: CurrentUser, db: DbSession) -> dict:
    page = db.get(Page, page_id)
    if page is None:
        raise error("not_found", "There is no such page.", status.HTTP_404_NOT_FOUND)
    board, _ = require_board_id(db, page.board_id, user, "edit")
    _refuse_unless_cards(page)
    _validate_kind(db, body.kind, body.integration_id, user)
    _validate_options(db, body.kind, body.options, user)
    app_keys.refuse_twice(db, board.id, None, body.kind, body.options)
    _refuse_a_taken_alias(db, board.id, None, body.kind, body.options)
    adapter, widget_kind = split_widget_kind(body.kind)
    widget_type = adapter.widget(widget_kind)
    # A tile that follows an app shows the app's name until it is given one of its own.
    follows_app = body.kind == "core.app" and bool((body.options or {}).get("app_id"))
    widget = Widget(page_id=page.id, kind=body.kind, title=body.title.strip() or ("" if follows_app else widget_type.label), icon=body.icon or (adapter.icon if adapter.kind != "core" else ""),
                    link=body.link.strip(), integration_id=body.integration_id, options=body.options, refresh_seconds=body.refresh_seconds)
    db.add(widget)
    db.flush()
    widget.options = clean_cards(db, page.id, widget.id, body.kind, body.options)
    size = (body.w or widget_type.default_size[0], body.h or widget_type.default_size[1])
    place_widget(page, widget.id, size, widget_type.min_size, grid.columns(board.settings))
    health_service.ensure_check_for_widget(db, widget)
    chronicle.record("card_added", widget_id=widget.id, integration_id=widget.integration_id, board_id=board.id,
                     user_id=user.id, name=widget.title or body.kind, after=board.name, db=db)
    db.commit()
    db.refresh(widget)
    collector.schedule(widget.id)
    # The Home Assistant listener keeps a map of entity to widget so a state
    # change costs no query; it has to hear that the map changed.
    hass_listener.forget_widgets(body.integration_id)
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    return {"widget": widget_view(db, widget, columns=grid.columns(board.settings)), "layouts": page.layouts}


@router.patch("/widgets/{widget_id}", summary="Change a widget's settings")
def patch_widget(widget_id: int, body: WidgetPatch, user: CurrentUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    board, _ = require_board_id(db, page.board_id, user, "edit")
    if body.integration_id is not None or body.clear_integration:
        _validate_kind(db, widget.kind, None if body.clear_integration else body.integration_id, user)
        widget.integration_id = None if body.clear_integration else body.integration_id
    if body.title is not None:
        widget.title = body.title.strip()
    if body.icon is not None:
        widget.icon = body.icon
    if body.link is not None:
        widget.link = body.link.strip()
    if body.options is not None:
        _validate_options(db, widget.kind, body.options, user)
        app_keys.refuse_twice(db, board.id, widget.id, widget.kind, body.options)
        _refuse_a_taken_alias(db, board.id, widget.id, widget.kind, body.options)
        widget.options = clean_cards(db, page.id, widget.id, widget.kind, body.options)
    if body.clear_refresh:
        widget.refresh_seconds = None
    elif body.refresh_seconds is not None:
        widget.refresh_seconds = body.refresh_seconds
    if body.page_id is not None and body.page_id != page.id:
        target = db.get(Page, body.page_id)
        if target is None or target.board_id != board.id:
            raise error("bad_page", "Widgets move between pages of the same board only.")
        _refuse_unless_cards(target)
        remove_from_layouts(page, widget.id)
        # Out of a group or the side bar of the page it leaves: there it would be drawn nowhere.
        holders.take_out(page, widget.id)
        widget.page_id = target.id
        adapter, kind = split_widget_kind(widget.kind)
        place_widget(target, widget.id, adapter.widget(kind).default_size, adapter.widget(kind).min_size, grid.columns(board.settings))
    health_service.ensure_check_for_widget(db, widget)
    db.commit()
    db.refresh(widget)
    collector.schedule(widget.id)
    hass_listener.forget_widgets(widget.integration_id)
    if widget.health_check is not None:
        health_service.health.reset(widget.health_check.id)
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    return widget_view(db, widget, columns=grid.columns(board.settings))


@router.put("/widgets/{widget_id}/note", summary="Write a note card's text, straight from the card")
def put_note(widget_id: int, body: NoteBody, user: CurrentUser, db: DbSession) -> dict:
    """The text of a Notes card, typed into the card itself.

    Its own address rather than a change of the card's settings, for two
    reasons. It touches the text and nothing else, so a save from the card
    cannot wind back an option somebody changed in the settings meanwhile.
    And it is refused when the stored text is no longer the one the typing
    started from: two tablets on the same list would otherwise take turns
    wiping out each other's lines, silently. The refusal carries the stored
    text, so the card can offer both.
    """
    widget, page = _widget(db, widget_id)
    board, _ = require_board_id(db, page.board_id, user, "edit")
    if widget.kind != "core.markdown":
        raise error("not_a_note", "Only a Notes card is written from the card.")
    options = dict(widget.options or {})
    # A new card holds no text of its own yet and shows the field's default;
    # that is what its first save starts from.
    adapter, kind = split_widget_kind(widget.kind)
    default = next((field.default for field in adapter.widget(kind).options if field.name == "content"), "")
    stored = str(options["content"]) if "content" in options else str(default or "")
    if stored != body.based_on and stored != body.content:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "note_changed", "message": "The note was changed elsewhere while you were typing.", "current": stored,
        })
    if stored != body.content:
        options["content"] = body.content
        widget.options = options
        db.commit()
        collector.schedule(widget.id)
        hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    return {"content": body.content}


@router.delete("/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a widget")
def delete_widget(widget_id: int, user: CurrentUser, db: DbSession) -> None:
    widget, page = _widget(db, widget_id)
    board, _ = require_board_id(db, page.board_id, user, "edit")
    integration_id = widget.integration_id
    remove_from_layouts(page, widget.id)
    # ⚠️ Out of its group and the side bar as well: SQLite hands the number of
    # the last card out again, and the next new card turned up inside them.
    holders.take_out(page, widget.id)
    history.forget_widget(db, widget.id)
    chronicle.record("card_removed", widget_id=widget.id, integration_id=integration_id, board_id=board.id,
                     user_id=user.id, name=widget.title or widget.kind, after=board.name, db=db)
    db.delete(widget)
    db.commit()
    collector.unschedule(widget_id)
    hass_listener.forget_widgets(integration_id)
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})


def _spot_in(widget: Widget, page: Page, from_columns: int, to_columns: int, as_id: int | None = None) -> dict:
    """Where a card stands on its page, in the columns of the board it goes to, under ``as_id`` if it arrives as another card."""
    spot = next((dict(item) for item in (page.layouts or {}).get("lg", []) if item.get("i") == str(widget.id)), None)
    if spot is None:
        default = card_sizes(widget, from_columns)[0]
        spot = {"x": 0, "y": 0, "w": default[0], "h": default[1]}
    name = str(as_id if as_id is not None else widget.id)
    floor = card_sizes(widget, to_columns)[1][0]
    [spot] = grid.rescale([{"i": name, **{key: spot[key] for key in ("x", "y", "w", "h")}}], from_columns, to_columns, {name: floor})
    return spot


def _below(target: Page, spots: list[dict]) -> dict[str, dict]:
    """Cards arriving together, as they stood, below the last row of the page they land on."""
    # Cards from different pages may now claim the same cells.
    block = grid.settle(spots)
    top = min(spot["y"] for spot in block)
    bottom = max((item["y"] + item["h"] for item in (target.layouts or {}).get("lg", [])), default=0)
    return {spot["i"]: {**spot, "y": spot["y"] - top + bottom} for spot in block}


@router.post("/widgets/move", summary="Put cards on another page, of this board or another")
def move_widgets(body: WidgetMove, user: CurrentUser, db: DbSession) -> dict:
    """The cards go together and arrive as they stood: side by side stays
    side by side, below the last row of the page they land on. They keep
    their settings, their checks and their history.

    Edit is needed on the board a card leaves and on the one it lands on,
    and neither may come from a file on the server.

    ⚠️ A card built on a connection reserved for administrators stays on
    the boards the administrator put it on. Carried to a member's own board
    it would be shown to everyone that board is shared with, which is the
    decision the reservation keeps for administrators. The options are checked for the
    same reason: a calendar card names its sources there.
    """
    target = db.get(Page, body.page_id)
    if target is None:
        raise error("not_found", "There is no such page.", status.HTTP_404_NOT_FOUND)
    to_board, _ = require_board_id(db, target.board_id, user, "edit")
    _refuse_unless_cards(target)
    if to_board.provisioned:
        raise error("provisioned", "That board comes from a file on the server; change the file instead.", status.HTTP_409_CONFLICT)
    moving: list[tuple[Widget, Page]] = []
    boards = {to_board.id: to_board}
    for widget_id in dict.fromkeys(body.ids):
        widget, page = _widget(db, widget_id)
        if page.id == target.id:
            continue
        if page.board_id not in boards:
            from_board, _ = require_board_id(db, page.board_id, user, "edit")
            if from_board.provisioned:
                raise error("provisioned", "This board comes from a file on the server; change the file instead.", status.HTTP_409_CONFLICT)
            boards[from_board.id] = from_board
        if page.board_id != to_board.id and user.role != Role.admin.value:
            if widget.integration is not None and widget.integration.admin_only:
                raise error("integration_locked", f"{widget.title or widget.kind} reads a connection reserved for administrators and stays on its board.", status.HTTP_403_FORBIDDEN)
            _validate_options(db, widget.kind, widget.options, user)
        moving.append((widget, page))
    if not moving:
        return {"moved": 0, "page_id": target.id}
    # ⚠️ A key means one tile per board. A tile that brings its key to a board
    # where another tile has it is refused, with the name of that tile, as in
    # the settings; nothing is moved.
    arriving = {widget.id for widget, page in moving if page.board_id != to_board.id}
    keys = app_keys.taken(db, to_board.id, leaving=arriving)
    for widget, _page in moving:
        key = app_keys.key_of(widget.options) if widget.kind == app_keys.KIND and widget.id in arriving else ""
        if key and key in keys:
            raise app_keys.refused(db, key, keys[key])
        if key:
            keys[key] = widget

    to_columns = grid.columns(to_board.settings)
    placed = _below(target, [_spot_in(widget, page, grid.columns(boards[page.board_id].settings), to_columns) for widget, page in moving])

    for widget, page in moving:
        remove_from_layouts(page, widget.id)
        holders.take_out(page, widget.id)
        widget.page_id = target.id
        adapter, widget_kind = split_widget_kind(widget.kind)
        widget_type = adapter.widget(widget_kind)
        # The screens nobody reads get a place the usual way; the wide one gets the block's.
        place_widget(target, widget.id, widget_type.default_size, widget_type.min_size, to_columns)
        layouts = dict(target.layouts)
        layouts["lg"] = [placed[item["i"]] if item["i"] == str(widget.id) else item for item in layouts["lg"]]
        target.layouts = layouts
    for page in {page.id: page for _moved, page in moving}.values():
        page.layout_version = (page.layout_version or 0) + 1
    target.layout_version = (target.layout_version or 0) + 1
    db.commit()
    for board_id in boards:
        hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})
    logger.info("%d card(s) moved to page %r of board %r by %s.", len(moving), target.name, to_board.slug, user.username)
    return {"moved": len(moving), "page_id": target.id}


#: Options that belong to the reachability check, which a copy does not take along:
#: it gets the check a new card gets.
CHECK_OPTIONS = frozenset({"check_target"})


def _twin(db: DbSession, widget: Widget, page_id: int) -> Widget:
    """A new card made like ``widget``: the same connection, title, icon, link and options, nothing else.

    ⚠️ Not the history, not the chronicle, not the check. The copy is usually
    changed right after, and one history under two cards would mix two series
    of numbers; its check is the one a new card gets.
    """
    options = {key: copy.deepcopy(value) for key, value in (widget.options or {}).items() if key not in CHECK_OPTIONS}
    twin = Widget(page_id=page_id, kind=widget.kind, title=widget.title, icon=widget.icon, link=widget.link,
                  integration_id=widget.integration_id, options=options, refresh_seconds=widget.refresh_seconds)
    db.add(twin)
    return twin


def _may_copy(db: DbSession, widget: Widget, user: User) -> bool:
    """Whether this person could make this card anew: its connection and its options, as for a new card."""
    try:
        _validate_kind(db, widget.kind, widget.integration_id, user)
        _validate_options(db, widget.kind, widget.options, user)
    except HTTPException:
        return False
    return True


@router.post("/widgets/copy", summary="Copy cards onto a page, the one they are on or one of another board")
def copy_widgets(body: WidgetCopy, user: CurrentUser, db: DbSession) -> dict:
    """The copies arrive together and as the cards stood, below the last row
    of the page, in the columns of its board. Edit is needed on both boards.

    Each card is checked as a new one would be: a member cannot copy a card
    on a connection reserved for administrators, not even beside the
    original, because he could not have made it.

    A card that holds others (a group, tabs, key figures) names them by
    number, and those numbers mean cards of its own page. Wherever it is
    copied, beside the original as well, it takes copies of its cards along,
    those this person could make; the rest stay behind and the answer says
    how many. ⚠️ Copies, never the same numbers: a card stands in one place
    only, so the copy would have taken the cards out of the original.
    """
    target = db.get(Page, body.page_id)
    if target is None:
        raise error("not_found", "There is no such page.", status.HTTP_404_NOT_FOUND)
    to_board, _ = require_board_id(db, target.board_id, user, "edit")
    _refuse_unless_cards(target)
    if to_board.provisioned:
        raise error("provisioned", "That board comes from a file on the server; change the file instead.", status.HTTP_409_CONFLICT)
    boards = {to_board.id: to_board}
    sources: list[tuple[Widget, Page]] = []
    for widget_id in dict.fromkeys(body.ids):
        widget, page = _widget(db, widget_id)
        if page.board_id not in boards:
            boards[page.board_id], _ = require_board_id(db, page.board_id, user, "edit")
        # Refused as a whole, with the reason: these are the cards that were asked for.
        _validate_kind(db, widget.kind, widget.integration_id, user)
        _validate_options(db, widget.kind, widget.options, user)
        sources.append((widget, page))

    to_columns = grid.columns(to_board.settings)
    notes: list[dict[str, Any]] = []
    # Read before the first copy is made: the copies carry the keys of their originals.
    keys = app_keys.taken(db, to_board.id)
    made: list[tuple[Widget, Widget, Page]] = []
    held: list[tuple[Widget, Widget, Page]] = []
    taken_along: dict[int, list[Widget]] = {}
    for widget, page in sources:
        twin = _twin(db, widget, target.id)
        made.append((twin, widget, page))
        cards = (widget.options or {}).get("cards")
        if widget.kind not in GROUP_KINDS or not isinstance(cards, list) or not cards:
            continue
        name = widget.title or widget.kind
        wanted = [number for number in cards if isinstance(number, int)]
        inside = {row.id: row for row in db.scalars(select(Widget).where(Widget.page_id == page.id, Widget.id.in_(wanted or [-1])))}
        taken: list[Widget] = []
        for number in wanted:
            card = inside.get(number)
            if card is None or card.kind in GROUP_KINDS or not _may_copy(db, card, user):
                continue
            copied = _twin(db, card, target.id)
            taken.append(copied)
            held.append((copied, card, page))
        taken_along[id(twin)] = taken
        if len(taken) < len(inside):
            notes.append({"code": "held_left", "name": name, "count": len(inside) - len(taken)})
    # A key opens one tile of a board. Beside its original, or where another
    # tile has it, the copy comes without it, and the answer says so.
    for twin, _source, _page in [*made, *held]:
        key = app_keys.key_of(twin.options) if twin.kind == app_keys.KIND else ""
        if key and key in keys:
            twin.options = {name: value for name, value in twin.options.items() if name != "key"}
            notes.append({"code": "key_dropped", "name": twin.title or app_keys.name_of(db, keys[key]), "key": key})
        elif key:
            keys[key] = twin
    db.flush()

    # The holders name their copied cards by the numbers those just got.
    for twin, _source, _page in made:
        if id(twin) in taken_along:
            twin.options = clean_cards(db, target.id, twin.id, twin.kind, {**twin.options, "cards": [card.id for card in taken_along[id(twin)]]})

    placed = _below(target, [_spot_in(widget, page, grid.columns(boards[page.board_id].settings), to_columns, twin.id)
                             for twin, widget, page in made])
    for twin, _source, _page in made:
        adapter, widget_kind = split_widget_kind(twin.kind)
        widget_type = adapter.widget(widget_kind)
        place_widget(target, twin.id, widget_type.default_size, widget_type.min_size, to_columns)
        layouts = dict(target.layouts)
        layouts["lg"] = [placed[item["i"]] if item["i"] == str(twin.id) else item for item in layouts["lg"]]
        target.layouts = layouts
    # A card inside a holder is drawn by it; its place on the grid only matters once it is taken out.
    for twin, _source, _page in held:
        adapter, widget_kind = split_widget_kind(twin.kind)
        place_widget(target, twin.id, adapter.widget(widget_kind).default_size, adapter.widget(widget_kind).min_size, to_columns)
    target.layout_version = (target.layout_version or 0) + 1

    for twin, source, page in [*made, *held]:
        health_service.ensure_check_for_widget(db, twin)
        chronicle.record("card_copied", widget_id=twin.id, integration_id=twin.integration_id, board_id=to_board.id,
                         user_id=user.id, name=twin.title or source.kind, before=f"{boards[page.board_id].name} › {page.name}",
                         after=to_board.name, db=db)
    db.commit()
    for twin, _source, _page in [*made, *held]:
        collector.schedule(twin.id)
    for integration_id in {twin.integration_id for twin, _source, _page in [*made, *held] if twin.integration_id}:
        hass_listener.forget_widgets(integration_id)
    hub.publish(board_topic(to_board.id), "board", {"id": to_board.id, "changed": True})
    logger.info("%d card(s) copied to page %r of board %r by %s.", len(made), target.name, to_board.slug, user.username)
    return {"copied": len(made), "page_id": target.id, "ids": [twin.id for twin, _source, _page in made], "notes": notes}


@router.post("/widgets/{widget_id}/preview", summary="Fetch a widget's data with draft settings, without saving")
async def preview_widget(widget_id: int, body: WidgetPreview, user: CurrentUser, db: DbSession) -> dict:
    """The settings sheet shows what a change would look like before it is saved."""
    widget, page = _widget(db, widget_id)
    require_board_id(db, page.board_id, user, "edit")
    if body.integration_id is not None:
        _validate_kind(db, widget.kind, body.integration_id, user)
    # A preview reaches the adapter with unsaved options, so it needs the
    # same check; otherwise the sheet is the way around it.
    _validate_options(db, widget.kind, body.options, user)
    if body.clear_integration:
        integration_id = None
    elif body.integration_id is not None:
        integration_id = body.integration_id
    else:
        integration_id = widget.integration_id
    data = await collector.preview(widget_id, body.options, integration_id)
    return data.model_dump()


@router.post("/widgets/{widget_id}/refresh", summary="Fetch a widget's data right now")
async def refresh_widget(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """⚠️ Above "view", because this reaches out to the foreign service.

    It used to take the same level as looking at the board, and the answer was
    thrown away: a guest, or anybody holding a view-only share, could ask the
    server to call Radarr as fast as it would answer. Found on 07.09.2026 by
    the guard that asks which right an address really wants.
    """
    widget, page = _widget(db, widget_id)
    _board, permission = board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    if permission not in ("edit", "act", "owner"):
        raise error("forbidden", "You may not refresh cards on this board.", status.HTTP_403_FORBIDDEN)
    data = await collector.refresh_now(widget_id)
    return data.model_dump() if data else {}


@router.get("/widgets/{widget_id}/data", summary="Read a widget's latest data")
def widget_data(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    data = live.get(widget_id)
    return data.model_dump() if data else {}


@router.post("/widgets/{widget_id}/actions/{action_id}/impact", summary="What a widget action would hit")
async def action_impact(widget_id: int, action_id: str, body: ActionBody, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """Streams that would end, downloads that would stop: shown before the press. Same right as pressing."""
    _widget_row, page = _widget(db, widget_id)
    _board, permission = board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    if permission not in ("act", "owner"):
        raise error("forbidden", "You may look at this board, but not act on it.", status.HTTP_403_FORBIDDEN)
    try:
        collector._refuse_unless_offered(widget_id, action_id, body.params)
    except AdapterError as failure:
        raise error(failure.code, failure.message) from failure
    db.rollback()
    return {"impact": await impact.facts(widget_id, action_id, body.params)}


@router.post("/widgets/{widget_id}/actions/{action_id}", summary="Run a widget action")
async def run_action(widget_id: int, action_id: str, body: ActionBody, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """Needs the act permission on the board, or a kiosk token that allows actions. Every call is logged."""
    widget, page = _widget(db, widget_id)
    kiosk = kiosk_from_request(request, db)
    board, permission = board_for_viewer_id(db, page.board_id, user, kiosk)
    if permission not in ("act", "owner"):
        raise error("forbidden", "You may look at this board, but not act on it.", status.HTTP_403_FORBIDDEN)
    actor = user.username if user else f"kiosk:{kiosk.name}" if kiosk else "?"
    if body.via == "assistant":
        actor = f"{actor} (via assistant)"
    try:
        message = await collector.run_action(widget_id, action_id, body.params, actor=actor, user_id=user.id if user else None)
    except AdapterError as failure:
        emit("action_failed", f"{action_id} on {widget.title} failed", failure.message, level="warn",
             user_ids=[user.id] if user else None, integration_id=widget.integration_id)
        logger.warning("Action %r on %r failed for %s: %s", action_id, widget.title, actor, failure.message)
        raise error(failure.code, failure.message) from failure
    # The one thing in here that reaches out and changes somebody else's
    # service. It goes in the action log as a row; it belongs in the text log
    # too, next to whatever happened around it.
    logger.info("Action %r ran on %r by %s: %s", action_id, widget.title, actor, message)
    # ⚠️ Was in the catalogue from the start and emitted from nowhere. Somebody
    # could subscribe to "an action succeeded" and never hear a thing.
    emit("action_done", f"{action_id} on {widget.title}", message,
         user_ids=[user.id] if user else None, integration_id=widget.integration_id)
    return {"ok": True, "message": message}


# -- images of a widget's service ----------------------------------------------

IMAGE_TTL = 3600
IMAGE_LIMIT = 300
IMAGE_MAX_BYTES = 5 * 1024 * 1024
#: The words of an SVG's title, with no "<" among them (see ``widget_image``).
TITLE_WORDS = re.compile(rb"<title>[^<]*</title>", re.I)
#: What the whole cache may weigh.
#:
#: ⚠️ It was bounded by the number of entries and nothing else, and one entry
#: may be five megabytes: three hundred posters is a gigabyte and a half held
#: in the process, on a machine that is often a Raspberry Pi. The count stays
#: as a second ceiling; whichever is reached first evicts.
IMAGE_MAX_TOTAL = 64 * 1024 * 1024
_images: dict[tuple[int, str], tuple[float, bytes, str]] = {}
_insecure_client: httpx.AsyncClient | None = None


def _cached_bytes() -> int:
    return sum(len(entry[1]) for entry in _images.values())


def _make_room() -> None:
    """Evict the entries that expire first until the cache fits again."""
    expired = [key for key, entry in _images.items() if entry[0] <= time.monotonic()]
    for key in expired:
        _images.pop(key, None)
    total = _cached_bytes()
    while _images and (len(_images) > IMAGE_LIMIT or total > IMAGE_MAX_TOTAL):
        oldest = min(_images, key=lambda key: _images[key][0])
        total -= len(_images[oldest][1])
        _images.pop(oldest, None)


def _image_client(insecure: bool) -> httpx.AsyncClient:
    global _insecure_client
    if not insecure:
        return collector.client
    if _insecure_client is None or _insecure_client.is_closed:
        _insecure_client = outbound_client(verify=False, follow_redirects=True, timeout=15.0, headers={"User-Agent": "nexdeck"})
    return _insecure_client


async def _service_of(widget: Widget) -> tuple[Any, dict[str, Any], Context]:
    """The adapter, configuration and shared context behind a widget's integration.

    The context is the collector's, so a session token the adapter already holds
    (Reolink, Synology) serves images and streams too instead of a fresh login.
    """
    if not widget.integration_id:
        raise error("not_found", "This widget has no service to fetch from.", status.HTTP_404_NOT_FOUND)
    try:
        return await collector.resolve_integration(widget.integration_id)
    except AdapterError as failure:
        raise error("not_found", str(failure), status.HTTP_404_NOT_FOUND) from failure


@router.get("/widgets/{widget_id}/favicon", summary="Serve the logo the service of a card names for itself")
async def widget_favicon(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> Response:
    """For a card whose logo no collection has: the service's own, from the address the card opens.

    Only for whoever may see the board, a wall display included, and only from
    the address stored on the card, its app or its connection: the request
    names no address, so it cannot point the server anywhere else.
    """
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    from ..services import apps as apps_service
    from ..services.boards import service_link

    _app, app_link = apps_service.tile_view(db, widget)
    address = widget.link or app_link or service_link(widget)
    found = await favicons.favicon(address) if address else None
    if found is None:
        raise error("not_found", "The service names no logo of its own.", status.HTTP_404_NOT_FOUND)
    content, content_type = found
    return Response(content=content, media_type=content_type, headers=_image_headers(content_type, "private, max-age=86400"))


@router.get("/widgets/{widget_id}/image", summary="Serve an image of a widget's service through the server")
async def widget_image(widget_id: int, path: str, request: Request, user: OptionalUser, db: DbSession,
                       _effect: NotReadOnly) -> Response:
    """Posters, thumbnails and snapshots come from the service with the server's credentials; the browser never sees a token.

    ``path`` is relative to the integration's address, so the server only ever
    fetches from the service the widget already talks to. The adapter may
    redirect a path (``/snap/0``) to the real request through ``image_source``.

    ⚠️ Not for a token that only reads. The path is the caller's, and a GET
    on a media server is not always a read: Plex marks a title as played on
    ``/:/scrobble`` and scans a library on ``.../refresh``, both asked with
    the server's credentials.
    """
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise error("bad_path", "An image path is relative to the service, starting with a slash.")
    hit = _images.get((widget_id, path))
    if hit and hit[0] > time.monotonic():
        return Response(content=hit[1], media_type=hit[2], headers=_image_headers(hit[2], "private, max-age=3600"))
    adapter, config, ctx = await _service_of(widget)
    try:
        source = await adapter.image_source(config, path, ctx)
    except AdapterError as failure:
        code = getattr(failure, "code", "") or "no_image"
        raise error(code, str(failure), status.HTTP_400_BAD_REQUEST if code == "bad_path" else status.HTTP_502_BAD_GATEWAY) from failure
    try:
        response = await _image_client(bool(config.get("insecure"))).get(source.url, headers=source.headers, params=source.params or None)
    except httpx.HTTPError as failure:
        raise error("unreachable", f"The service did not deliver the image: {failure.__class__.__name__}.", status.HTTP_502_BAD_GATEWAY) from failure
    content_type = response.headers.get("content-type", "") or source.media_type
    # ⚠️ "image/" is not enough. image/svg+xml passes that test and is not a
    # picture but a document that runs script, handed out from nexdeck's own
    # address. No service sends a poster as SVG. One that draws its pictures as
    # SVG says so through the adapter (``MediaSource.svg``); that answer is
    # then checked for script like an uploaded one, and served in a sandbox.
    if content_type.split(";")[0].strip().lower() == "image/svg+xml":
        if not source.svg:
            raise error("no_image", "The service answered with SVG, which is not served as an image.", status.HTTP_404_NOT_FOUND)
        # The words of a <title> are left out of the check: "JavaScript: Basics"
        # or "Online = yes" as the name of a board looked like an address or a
        # handler, and the picture was refused (found against nexcanvas on
        # 11.10.2026). Only a title without a single "<" in it: XML allows no
        # "<" in an attribute, so such a span cannot hide a tag or a handler.
        checked = TITLE_WORDS.sub(b"<title></title>", response.content)
        refused = unsafe_svg(checked) if response.status_code < 400 else "it is an error page"
        if refused:
            raise error("no_image", f"The service's SVG was refused: {refused}.", status.HTTP_404_NOT_FOUND)
    if response.status_code >= 400 or not content_type.startswith("image/") or len(response.content) > IMAGE_MAX_BYTES:
        raise error("no_image", "The service did not answer with an image.", status.HTTP_404_NOT_FOUND)
    if source.cache_seconds <= 0:
        return Response(content=response.content, media_type=content_type, headers=_image_headers(content_type, "no-store"))
    _images[(widget_id, path)] = (time.monotonic() + min(IMAGE_TTL, source.cache_seconds), response.content, content_type)
    _make_room()
    return Response(content=response.content, media_type=content_type, headers=_image_headers(content_type, "private, max-age=3600"))


def _image_headers(content_type: str, cache: str) -> dict[str, str]:
    """The headers of a served image; an SVG gets a sandbox of its own on top of the API's floor.

    ⚠️ Stated here and not left to the middleware that sets the same policy
    for everything under ``/api/``: this is the one route that hands out SVG
    of somebody else's making, and it should stay safe if that floor moves.
    """
    headers = {"Cache-Control": cache}
    if content_type.split(";")[0].strip().lower() == "image/svg+xml":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    return headers


# -- live video of a widget's service -------------------------------------------

#: How many live streams the server relays at once; every one is an open connection to a camera.
STREAM_LIMIT = 12
_streams_open = 0


@router.get("/widgets/{widget_id}/stream", summary="Relay a widget's live video through the server")
async def widget_stream(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> StreamingResponse:
    """Live video (HTTP-FLV from a camera or recorder) flows through the server with
    the service's credentials; the browser only ever talks to nexdeck and plays
    the bytes with Media Source Extensions, no transcoder anywhere."""
    global _streams_open
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    adapter, config, ctx = await _service_of(widget)
    try:
        source = await adapter.stream_source(config, dict(widget.options or {}), ctx)
    except AdapterError as failure:
        raise error(getattr(failure, "code", "") or "no_stream", str(failure), status.HTTP_404_NOT_FOUND) from failure
    if _streams_open >= STREAM_LIMIT:
        raise error("too_many_streams", f"The server relays at most {STREAM_LIMIT} live streams at once.", status.HTTP_503_SERVICE_UNAVAILABLE)
    # ⚠️ Take the slot here, before the first await, and give it back on every
    # way out. Between the check above and the counting there used to be a
    # network round trip to the camera, so a dozen browsers opening in the same
    # second all passed a limit of twelve and the server relayed every one.
    _streams_open += 1
    client = _image_client(bool(config.get("insecure")))
    upstream = client.build_request("GET", source.url, headers=source.headers, params=source.params or None, timeout=httpx.Timeout(15.0, read=60.0))
    try:
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError as failure:
        _streams_open -= 1
        raise error("unreachable", f"The service did not deliver the stream: {failure.__class__.__name__}.", status.HTTP_502_BAD_GATEWAY) from failure
    if response.status_code >= 400:
        _streams_open -= 1
        await response.aclose()
        raise error("no_stream", f"The service answered the stream request with HTTP {response.status_code}.", status.HTTP_502_BAD_GATEWAY)
    media_type = source.media_type or response.headers.get("content-type", "video/x-flv")

    board_id = page.board_id

    def _still_allowed() -> bool:
        # ⚠️ A camera keeps sending for as long as somebody watches, and a wall
        # display watches for weeks. The right to see the board used to be
        # looked at once, when the relay opened.
        try:
            with db_session() as db_again:
                board_for_viewer_id(db_again, board_id, optional_user(request, db_again), kiosk_from_request(request, db_again))
        except HTTPException:
            return False
        return True

    recheck = Recheck(_still_allowed, every=25)

    async def relay():
        # Every chunk goes out as it arrives. Collecting 64 kB first would hold
        # up to a second of a small stream back and the player would stutter.
        global _streams_open
        try:
            async for chunk in response.aiter_raw():
                if await recheck.denied():
                    break
                yield chunk
        finally:
            _streams_open -= 1
            await response.aclose()

    return StreamingResponse(relay(), media_type=media_type, headers={"Cache-Control": "no-store"})


# -- a file a row offers to save ---------------------------------------------


def _offered_file(widget_id: int, path: str) -> dict[str, Any] | None:
    """The file with this path among the rows the card last delivered.

    ⚠️ The same guard the actions have, for the same reason. Without it the
    address below reads "fetch any path from this widget's service with the
    server's credentials", and everybody who may look at the board may ask,
    kiosk displays included. With it, a card can only hand out what it put in
    front of somebody, and the name comes from there too rather than from the
    request, so nothing a caller writes reaches a response header.
    """
    data = live.get(widget_id)
    for item in getattr(data, "items", []) or []:
        entry = item.get("file") if isinstance(item, dict) else None
        if isinstance(entry, dict) and entry.get("path") == path:
            return entry
    return None


@router.get("/widgets/{widget_id}/file", summary="Save a file a widget's row offers, through the server")
async def widget_file(widget_id: int, path: str, request: Request, user: OptionalUser, db: DbSession) -> StreamingResponse:
    """The bytes flow through the server and arrive as a download, not as a page.

    Two things the browser cannot do by itself with a link to the service: it
    would have to reach the service, which on a homelab it usually cannot, and
    a video would play in a tab instead of being saved, because ``download`` on
    a link is ignored across origins.
    """
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    offered = _offered_file(widget_id, path)
    if offered is None:
        raise error("no_such_file", "This card is not offering that file.", status.HTTP_404_NOT_FOUND)
    adapter, config, ctx = await _service_of(widget)
    try:
        source = await adapter.file_source(config, path, ctx)
    except AdapterError as failure:
        raise error(getattr(failure, "code", "") or "no_such_file", str(failure), status.HTTP_404_NOT_FOUND) from failure

    client = _image_client(bool(config.get("insecure")))
    upstream = client.build_request(
        "GET", source.url, headers=source.headers, params=source.params or None,
        timeout=httpx.Timeout(15.0, read=120.0),
    )
    try:
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError as failure:
        raise error("unreachable", f"The service did not deliver the file: {failure.__class__.__name__}.",
                    status.HTTP_502_BAD_GATEWAY) from failure
    if response.status_code >= 400:
        await response.aclose()
        raise error("no_such_file", f"The service answered the file request with HTTP {response.status_code}.",
                    status.HTTP_502_BAD_GATEWAY)

    async def relay():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()

    name = str(offered.get("name") or "download")
    headers = {
        # ⚠️ Both spellings. The plain one is what old browsers read and it may
        # hold nothing but ASCII, so anything else is stripped rather than
        # written into a header; the starred one carries the real name.
        "Content-Disposition":
            f'attachment; filename="{quote(name, safe="")}"; filename*=UTF-8\'\'{quote(name, safe="")}',
        "Cache-Control": "no-store",
    }
    length = response.headers.get("content-length")
    if length:
        headers["Content-Length"] = length
    return StreamingResponse(
        relay(), media_type=response.headers.get("content-type") or "application/octet-stream", headers=headers,
    )


# -- reachability checks -----------------------------------------------------


@router.get("/widgets/{widget_id}/health", summary="Read a widget's reachability check")
def get_health(widget_id: int, request: Request, user: OptionalUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    if widget.health_check is None:
        return {}
    payload = health_service.check_payload(widget.health_check)
    payload["bars"] = health_service.uptime_bars(db, widget.id, health_service.bars_window(widget.options))
    return payload


@router.put("/widgets/{widget_id}/health", summary="Set a widget's reachability check")
def put_health(widget_id: int, body: HealthBody, user: CurrentUser, db: DbSession) -> dict:
    widget, page = _widget(db, widget_id)
    require_board_id(db, page.board_id, user, "edit")
    follows_app = widget.kind == "core.app" and bool((widget.options or {}).get("app_id"))
    if not body.target.strip() and widget.integration_id is None and not follows_app:
        raise error("target_missing", "A check needs a target, or the widget an integration or an app whose address it follows.")
    check = widget.health_check or HealthCheck(widget_id=widget.id, target=body.target)
    check.kind = body.kind
    # An empty target means: the address of the widget's integration, looked up at every check.
    check.target = body.target.strip()
    check.interval_seconds = body.interval_seconds
    check.timeout_seconds = body.timeout_seconds
    check.expect_status = body.expect_status
    check.insecure = body.insecure
    check.enabled = body.enabled
    db.add(check)
    db.commit()
    health_service.health.reset(check.id)
    return health_service.check_payload(check)


@router.delete("/widgets/{widget_id}/health", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a widget's reachability check")
def delete_health(widget_id: int, user: CurrentUser, db: DbSession) -> None:
    widget, page = _widget(db, widget_id)
    require_board_id(db, page.board_id, user, "edit")
    if widget.health_check is not None:
        db.delete(widget.health_check)
        db.commit()


# -- history -----------------------------------------------------------------


@router.get("/widgets/{widget_id}/history", summary="Read a widget's metric history")
def widget_history(widget_id: int, request: Request, user: OptionalUser, db: DbSession, metric: str = "", hours: float = 24) -> dict:
    """``metric`` empty returns every metric the widget has recorded."""
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    hours = max(0.1, min(24.0, hours))
    if metric:
        names = [metric]
    else:
        data = live.get(widget_id)
        names = list(data.metrics.keys()) if data and data.metrics else []
        if widget.health_check is not None:
            names.extend(["latency", "up"])
    return {name: history.series(db, widget_id, name, hours=hours) for name in names}


@router.get("/widgets/{widget_id}/history/long", summary="A widget's metric history over days, with the lowest and highest")
def widget_history_long(widget_id: int, request: Request, user: OptionalUser, db: DbSession, days: int = 30, metric: str = "") -> dict:
    """``{metric: [[ts, avg, min, max], ...]}``: hours up to 30 days, days up to two years (roadmap M4)."""
    widget, page = _widget(db, widget_id)
    board_for_viewer_id(db, page.board_id, user, kiosk_from_request(request, db))
    days = max(1, min(730, days))
    if metric:
        names = [metric]
    else:
        data = live.get(widget_id)
        names = list(history.recorded(data)) if data else []
    return {name: [list(point) for point in history.series_long(db, widget_id, name, days)] for name in names}


@router.post("/history/prune", summary="Condense the metric history now")
def prune_history(db: DbSession, user: AdminUser) -> dict:
    """⚠️ POST and administrators only, and both matter.

    This rewrites the whole history: it folds raw samples into minutes and
    drops what is past its retention. As a GET behind ``CurrentUser`` it was
    open to every account down to a guest, and a GET carries no
    ``X-Nexdeck-Request`` header, so the one thing that stops another site from
    making a browser call this did not apply to it either. Nothing calls it;
    it exists so an operator can run the housekeeping without waiting for the
    five minute tick.
    """
    history.condense(db)
    db.commit()
    return {"ok": True}


def _unused(select_=select) -> None:  # keeps the import for type checkers
    return None
