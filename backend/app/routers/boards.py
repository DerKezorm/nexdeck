"""Boards, pages, layouts, shares, export, import and kiosk tokens."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from ..deps import (
    CurrentUser,
    DbSession,
    MemberUser,
    OptionalUser,
    board_for_viewer,
    board_permission,
    error,
    kiosk_from_request,
    require_board,
)
from ..models import Board, BoardShare, KioskToken, Page, Widget
from ..schemas import (
    BoardCreate,
    BoardPatch,
    ImportBody,
    KioskCreate,
    LayoutsBody,
    PageCreate,
    PagePatch,
    SharesBody,
)
from ..security import new_opaque_token
from ..services import boards as board_service
from ..services.boards import COLUMNS, ImportError_, board_summary, board_view, slugify, unique_slug
from ..services.collector import collector
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1", tags=["boards"])


def _announce(board_id: int) -> None:
    hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})


@router.get("/boards", summary="List boards I may open")
def list_boards(user: CurrentUser, db: DbSession) -> list[dict]:
    result = []
    for board in db.scalars(select(Board).order_by(Board.position, Board.id)):
        permission = board_permission(db, board, user)
        if permission is not None:
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
    widgets = db.scalars(select(Widget).join(Page).where(Page.board_id == board.id)).all()
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
    board, permission = require_board(db, str(page.board_id), user, "edit")
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
        board = board_service.import_board(db, body.yaml_text, owner_id=user.id, slug=body.slug)
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
    return [_kiosk_public(t) for t in board.kiosk_tokens]


@router.post("/boards/{slug}/kiosk-tokens", status_code=status.HTTP_201_CREATED, summary="Create a kiosk link for a wall display")
def create_kiosk_token(slug: str, body: KioskCreate, user: CurrentUser, db: DbSession) -> dict:
    """The full token is shown once, right here."""
    board, _ = require_board(db, slug, user, "edit")
    token, token_hash, prefix = new_opaque_token("nk")
    row = KioskToken(board_id=board.id, name=body.name, token_hash=token_hash, prefix=prefix, allow_actions=body.allow_actions,
                     cycle_seconds=body.cycle_seconds, dim_from=body.dim_from, dim_to=body.dim_to)
    db.add(row)
    db.commit()
    return {**_kiosk_public(row), "token": token, "url": f"/k/{token}"}


@router.delete("/kiosk-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a kiosk link")
def delete_kiosk_token(token_id: int, user: CurrentUser, db: DbSession) -> None:
    row = db.get(KioskToken, token_id)
    if row is None:
        raise error("not_found", "There is no such kiosk link.", status.HTTP_404_NOT_FOUND)
    require_board(db, str(row.board_id), user, "edit")
    db.delete(row)
    db.commit()


def _kiosk_public(token: KioskToken) -> dict:
    return {"id": token.id, "name": token.name, "prefix": token.prefix, "allow_actions": token.allow_actions, "cycle_seconds": token.cycle_seconds,
            "dim_from": token.dim_from, "dim_to": token.dim_to, "created_at": token.created_at, "last_used_at": token.last_used_at}
