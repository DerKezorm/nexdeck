"""Boards, pages, layouts, shares, export, import and kiosk tokens."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..deps import (
    KIOSK_COOKIE,
    CurrentUser,
    DbSession,
    MemberUser,
    OptionalUser,
    board_for_viewer,
    board_is_shared_with,
    board_permission,
    error,
    kiosk_from_request,
    require_board,
    require_board_id,
    usable_token,
)
from ..models import Board, BoardShare, KioskToken, Page, Widget, utcnow
from ..schemas import (
    BoardCreate,
    BoardPatch,
    ImportBody,
    KioskCreate,
    KioskSession,
    LayoutsBody,
    PageCreate,
    PagePatch,
    SharesBody,
)
from ..security import create_kiosk_cookie, hash_token, new_opaque_token
from ..services import boards as board_service
from ..services.boards import COLUMNS, ImportError_, board_summary, board_view, slugify, unique_slug
from ..services.collector import collector
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1", tags=["boards"])


def _announce(board_id: int) -> None:
    hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})


@router.get("/boards", summary="List boards I may open")
def list_boards(user: CurrentUser, db: DbSession, all_boards: bool = False) -> list[dict]:
    """My own boards and the ones shared with me.

    ⚠️ **An administrator is not shown everything by default.** He may open
    every board, so the plain list handed him ten colleagues' boards along with
    his own, in his menu and in his settings. ``all_boards=true`` asks for the
    full list on purpose; the settings page has a switch for it.
    """
    result = []
    for board in db.scalars(select(Board).order_by(Board.position, Board.id)):
        permission = board_permission(db, board, user)
        if permission is None:
            continue
        mine = board.owner_id == user.id
        shared = board_is_shared_with(db, board, user)
        if not (all_boards or mine or shared or board.provisioned):
            continue
        result.append(board_summary(db, board, permission))
    return result


@router.post("/boards", status_code=status.HTTP_201_CREATED, summary="Create a board")
def create_board(body: BoardCreate, user: MemberUser, db: DbSession) -> dict:
    board = Board(slug=unique_slug(db, body.slug or body.name), name=body.name.strip(), icon=body.icon, owner_id=user.id,
                  background={"kind": "bundled", "value": "aurora"}, position=(db.scalar(select(Board.position).order_by(Board.position.desc())) or 0) + 1)
    db.add(board)
    db.flush()
    db.add(Page(board_id=board.id, name="Overview", slug="overview", position=0, layouts={key: [] for key in COLUMNS}))
    db.commit()
    return board_view(db, board, "owner")


@router.get("/boards/{slug}", summary="Open a board with its pages, widgets and live data")
def get_board(slug: str, request: Request, user: OptionalUser, db: DbSession) -> dict:
    """Works for signed-in users and for kiosk displays with a token."""
    kiosk = kiosk_from_request(request, db)
    board, permission = board_for_viewer(db, slug, user, kiosk)
    view = board_view(db, board, permission)
    if kiosk is not None:
        view["kiosk"] = {"cycle_seconds": kiosk.cycle_seconds, "dim_from": kiosk.dim_from, "dim_to": kiosk.dim_to, "allow_actions": kiosk.allow_actions, "name": kiosk.name}
    return view


@router.post("/kiosk/session", summary="Exchange a kiosk token for a session cookie")
def kiosk_session(body: KioskSession, response: Response, db: DbSession) -> dict:
    """The door of a wall display: the token goes in here and nowhere else.

    ⚠️ It used to be appended to every image, video and event address, because
    none of those can carry a header. A display makes a few thousand such
    requests a day and every one of them wrote the token into the reverse
    proxy log. The cookie is signed, short-lived and renewed on the next load.
    """
    token = body.token.strip()
    row = db.scalar(select(KioskToken).where(KioskToken.token_hash == hash_token(token))) if token.startswith("nk_") else None
    if row is None or not usable_token(row):
        raise error("unauthenticated", "This kiosk link is not valid.", status.HTTP_401_UNAUTHORIZED)
    cookie, seconds = create_kiosk_cookie(row.id, row.expires_at)
    response.set_cookie(KIOSK_COOKIE, cookie, max_age=seconds, httponly=True, samesite="lax",
                        secure=get_settings().public_url.startswith("https://"), path="/")
    return {"board_id": row.board_id, "expires_in": seconds}


@router.get("/kiosk", summary="Open the board that belongs to a kiosk token")
def kiosk_board(request: Request, db: DbSession) -> dict:
    """The wall display knows only its token; this resolves the board."""
    kiosk = kiosk_from_request(request, db)
    if kiosk is None:
        raise error("unauthenticated", "A kiosk token is required.", status.HTTP_401_UNAUTHORIZED)
    board = db.get(Board, kiosk.board_id)
    if board is None:
        raise error("not_found", "The board of this kiosk token is gone.", status.HTTP_404_NOT_FOUND)
    view = board_view(db, board, "act" if kiosk.allow_actions else "view")
    view["kiosk"] = {"cycle_seconds": kiosk.cycle_seconds, "dim_from": kiosk.dim_from, "dim_to": kiosk.dim_to, "allow_actions": kiosk.allow_actions, "name": kiosk.name}
    return view


@router.get("/boards/{slug}/history", summary="Read the metric history of every widget on a board")
def board_history(slug: str, request: Request, user: OptionalUser, db: DbSession, hours: float = 24) -> dict:
    """One call for all sparklines: ``{widget id: {metric: [[ts, value], ...]}}``."""
    from ..services import history
    from ..services.state import live

    board, _ = board_for_viewer(db, slug, user, kiosk_from_request(request, db))
    hours = max(0.1, min(24.0, hours))
    result: dict[str, dict[str, list[tuple[int, float]]]] = {}
    # ⚠️ health_check is a lazy relationship: without this, a board with
    # thirty cards fires thirty extra queries just to ask whether each
    # one has a check.
    widgets = db.scalars(
        select(Widget).join(Page).where(Page.board_id == board.id).options(selectinload(Widget.health_check))
    ).all()
    for widget in widgets:
        data = live.get(widget.id)
        names = list(data.metrics.keys()) if data and data.metrics else []
        if widget.health_check is not None:
            names.extend(["latency", "up"])
        if names:
            result[str(widget.id)] = {name: history.series(db, widget.id, name, hours=hours) for name in names}
    return result


@router.patch("/boards/{slug}", summary="Change a board's name, look or settings")
def patch_board(slug: str, body: BoardPatch, user: CurrentUser, db: DbSession) -> dict:
    board, permission = require_board(db, slug, user, "edit")
    if body.name is not None:
        board.name = body.name.strip()
    if body.icon is not None:
        board.icon = body.icon
    if body.background is not None:
        board.background = body.background
    if body.settings is not None:
        board.settings = body.settings
    if body.position is not None:
        board.position = body.position
    if body.in_menu is not None:
        board.in_menu = body.in_menu
    if body.owner_id is not None and permission == "owner":
        board.owner_id = body.owner_id
    db.commit()
    _announce(board.id)
    return board_view(db, board, permission)


@router.delete("/boards/{slug}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a board")
def delete_board(slug: str, user: CurrentUser, db: DbSession) -> None:
    board, permission = require_board(db, slug, user, "edit")
    if permission != "owner":
        raise error("forbidden", "Only the owner or an administrator may delete a board.", status.HTTP_403_FORBIDDEN)
    widget_ids = list(db.scalars(select(Widget.id).join(Page).where(Page.board_id == board.id)))
    db.delete(board)
    db.commit()
    for widget_id in widget_ids:
        collector.unschedule(widget_id)


# -- pages -------------------------------------------------------------------


@router.post("/boards/{slug}/pages", status_code=status.HTTP_201_CREATED, summary="Add a page to a board")
def create_page(slug: str, body: PageCreate, user: CurrentUser, db: DbSession) -> dict:
    board, permission = require_board(db, slug, user, "edit")
    position = (db.scalar(select(Page.position).where(Page.board_id == board.id).order_by(Page.position.desc())) or 0) + 1
    page = Page(board_id=board.id, name=body.name.strip(), slug=slugify(body.name), icon=body.icon, position=position, layouts={key: [] for key in COLUMNS})
    db.add(page)
    db.commit()
    _announce(board.id)
    return board_view(db, board, permission)


def _page_for_edit(db: DbSession, page_id: int, user: CurrentUser) -> tuple[Page, Board, str]:
    page = db.get(Page, page_id)
    if page is None:
        raise error("not_found", "There is no such page.", status.HTTP_404_NOT_FOUND)
    board, permission = require_board_id(db, page.board_id, user, "edit")
    return page, board, permission


@router.patch("/pages/{page_id}", summary="Rename or reorder a page")
def patch_page(page_id: int, body: PagePatch, user: CurrentUser, db: DbSession) -> dict:
    page, board, permission = _page_for_edit(db, page_id, user)
    if body.name is not None:
        page.name = body.name.strip()
        page.slug = slugify(body.name)
    if body.icon is not None:
        page.icon = body.icon
    if body.position is not None:
        page.position = body.position
    if body.sections is not None:
        page.sections = body.sections
    db.commit()
    _announce(board.id)
    return board_view(db, board, permission)


@router.delete("/pages/{page_id}", summary="Delete a page and its widgets")
def delete_page(page_id: int, user: CurrentUser, db: DbSession) -> dict:
    page, board, permission = _page_for_edit(db, page_id, user)
    if len(board.pages) <= 1:
        raise error("last_page", "A board keeps at least one page.", status.HTTP_409_CONFLICT)
    widget_ids = [w.id for w in page.widgets]
    db.delete(page)
    db.commit()
    for widget_id in widget_ids:
        collector.unschedule(widget_id)
    _announce(board.id)
    return board_view(db, board, permission)


@router.put("/pages/{page_id}/layouts", summary="Save the widget positions of a page")
def put_layouts(page_id: int, body: LayoutsBody, user: CurrentUser, db: DbSession) -> dict:
    """One layout per screen size; sizes the page does not send stay as they are."""
    page, board, _ = _page_for_edit(db, page_id, user)
    known = {str(w.id) for w in page.widgets}
    layouts = dict(page.layouts or {})
    for key in COLUMNS:
        items = getattr(body, key)
        if items is None:
            continue
        layouts[key] = [item.model_dump() for item in items if item.i in known]
    page.layouts = layouts
    db.commit()
    hub.publish(board_topic(board.id), "layout", {"page_id": page.id, "layouts": layouts})
    return {"layouts": layouts}


# -- shares ------------------------------------------------------------------


@router.get("/boards/{slug}/shares", summary="Who may see a board")
def get_shares(slug: str, user: CurrentUser, db: DbSession) -> list[dict]:
    board, _ = require_board(db, slug, user, "edit")
    return [{"id": s.id, "user_id": s.user_id, "role": s.role, "level": s.level} for s in board.shares]


@router.put("/boards/{slug}/shares", summary="Set who may see, edit or act on a board")
def put_shares(slug: str, body: SharesBody, user: CurrentUser, db: DbSession) -> list[dict]:
    board, permission = require_board(db, slug, user, "edit")
    if permission != "owner":
        raise error("forbidden", "Only the owner or an administrator may share a board.", status.HTTP_403_FORBIDDEN)
    for share in list(board.shares):
        db.delete(share)
    for entry in body.shares:
        if entry.user_id is None and entry.role is None:
            continue
        db.add(BoardShare(board_id=board.id, user_id=entry.user_id, role=entry.role, level=entry.level))
    db.commit()
    db.refresh(board)
    return [{"id": s.id, "user_id": s.user_id, "role": s.role, "level": s.level} for s in board.shares]


# -- export and import -------------------------------------------------------


@router.get("/boards/{slug}/export", summary="Export a board as YAML")
def export_board(slug: str, user: CurrentUser, db: DbSession) -> Response:
    """Secrets are replaced by environment references, never written out."""
    board, _ = require_board(db, slug, user, "view")
    text = board_service.export_board(db, board)
    return Response(content=text, media_type="application/yaml", headers={"Content-Disposition": f'attachment; filename="{board.slug}.yaml"'})


@router.post("/boards/import", status_code=status.HTTP_201_CREATED, summary="Import a board from YAML")
async def import_board(body: ImportBody, user: MemberUser, db: DbSession) -> dict:
    try:
        board = board_service.import_board(
            db, body.yaml_text, owner_id=user.id, slug=body.slug,
            # Anybody may call this, so it reads no environment and makes
            # no connections; a locked one is only allowed to an administrator.
            trusted=False, allow_locked=user.role == "admin",
        )
    except ImportError_ as failure:
        raise error("bad_import", str(failure)) from failure
    db.commit()
    for widget_id in db.scalars(select(Widget.id).join(Page).where(Page.board_id == board.id)):
        collector.schedule(widget_id)
    return board_view(db, board, "owner")


# -- kiosk tokens ------------------------------------------------------------


@router.get("/boards/{slug}/kiosk-tokens", summary="List kiosk links of a board")
def list_kiosk_tokens(slug: str, user: CurrentUser, db: DbSession) -> list[dict]:
    board, _ = require_board(db, slug, user, "edit")
    return [_kiosk_public(t) for t in board.kiosk_tokens if not t.revoked]


@router.post("/boards/{slug}/kiosk-tokens", status_code=status.HTTP_201_CREATED, summary="Create a kiosk link for a wall display")
def create_kiosk_token(slug: str, body: KioskCreate, user: CurrentUser, db: DbSession) -> dict:
    """The full token is shown once, right here."""
    board, permission = require_board(db, slug, user, "edit")
    # ⚠️ Creating a link needs "edit" and the body carried "allow_actions", so
    # a share that was deliberately not allowed to press buttons could mint a
    # display that could. Nobody hands out more than they hold.
    if body.allow_actions and permission not in ("act", "owner"):
        raise error("forbidden", "You may not give a display the right to act on this board.", status.HTTP_403_FORBIDDEN)
    token, token_hash, prefix = new_opaque_token("nk")
    ends = utcnow() + timedelta(days=body.expires_days) if body.expires_days else None
    row = KioskToken(board_id=board.id, name=body.name, token_hash=token_hash, prefix=prefix, allow_actions=body.allow_actions,
                     cycle_seconds=body.cycle_seconds, dim_from=body.dim_from, dim_to=body.dim_to, expires_at=ends)
    db.add(row)
    db.commit()
    return {**_kiosk_public(row), "token": token, "url": f"/k/{token}"}


@router.delete("/kiosk-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a kiosk link")
def delete_kiosk_token(token_id: int, user: CurrentUser, db: DbSession) -> None:
    row = db.get(KioskToken, token_id)
    if row is None or row.revoked:
        raise error("not_found", "There is no such kiosk link.", status.HTTP_404_NOT_FOUND)
    # ⚠️ Never route a number through the slug lookup: a board may be called
    # after a number, and then the wrong board decides.
    require_board_id(db, row.board_id, user, "edit")
    # The row stays. A withdrawn link must never be handed out again under the
    # same hash, and the cookie it gave out stops at the next request.
    row.revoked = True
    row.revoked_at = utcnow()
    db.commit()


def _kiosk_public(token: KioskToken) -> dict:
    return {"id": token.id, "name": token.name, "prefix": token.prefix, "allow_actions": token.allow_actions, "cycle_seconds": token.cycle_seconds,
            "dim_from": token.dim_from, "dim_to": token.dim_to, "created_at": token.created_at, "last_used_at": token.last_used_at,
            "expires_at": token.expires_at}
