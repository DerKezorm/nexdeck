"""The app catalog: apps set up once and placed as tiles on any board (issue #37)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import AdminUser, DbSession, MemberUser, error
from ..models import App, Page, Widget
from ..schemas import AppCreate, AppPatch
from ..services import apps as apps_service
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1", tags=["apps"])
logger = logging.getLogger("nexdeck.apps")


def _tiles(db: Session, app: App) -> list[Widget]:
    return [widget for widget in db.scalars(select(Widget).where(Widget.kind == "core.app"))
            if apps_service.followed(db, widget) is app]


def _tell_boards(db: Session, widgets: list[Widget]) -> None:
    """Every open board with one of these tiles fetches itself again."""
    for board_id in {db.get(Page, widget.page_id).board_id for widget in widgets if db.get(Page, widget.page_id)}:
        hub.publish(board_topic(board_id), "board", {"id": board_id, "changed": True})


def _choice(addresses: list[dict[str, str]], kept: str, sent: str | None) -> str:
    """The label for home or away after a change.

    One that was sent has to name an address. One that was kept and whose
    address went away goes with it, rather than refusing a change that never
    mentioned it.
    """
    if sent is not None:
        return apps_service.clean_choice(addresses, sent)
    try:
        return apps_service.clean_choice(addresses, kept)
    except apps_service.AppRefused:
        return ""


def _refused(failure: apps_service.AppRefused) -> Exception:
    return error("app_refused", str(failure))


def _name_free(db: Session, name: str, own: App | None = None) -> None:
    existing = apps_service.by_name(db, name)
    if existing is not None and existing is not own:
        raise error("app_exists", f"There is an app called {name!r} already.", status.HTTP_409_CONFLICT)


@router.get("/apps", summary="List the apps of the catalog")
def list_apps(user: MemberUser, db: DbSession) -> list[dict]:
    """Open to every member: placing an app on one's own board needs the list. Changing it does not."""
    apps = db.scalars(select(App).order_by(App.name)).all()
    counts: dict[int, int] = {}
    for widget in db.scalars(select(Widget).where(Widget.kind == "core.app")):
        app = apps_service.followed(db, widget)
        if app is not None:
            counts[app.id] = counts.get(app.id, 0) + 1
    return [{**apps_service.app_view(app), "tiles": counts.get(app.id, 0)} for app in apps]


@router.post("/apps", status_code=status.HTTP_201_CREATED, summary="Add an app to the catalog")
def create_app(body: AppCreate, user: AdminUser, db: DbSession) -> dict:
    name = body.name.strip()
    _name_free(db, name)
    try:
        addresses = apps_service.clean_addresses([entry.model_dump() for entry in body.addresses])
        home = apps_service.clean_choice(addresses, body.home)
        away = apps_service.clean_choice(addresses, body.away)
    except apps_service.AppRefused as failure:
        raise _refused(failure) from failure
    app = App(name=name, icon=body.icon.strip(), description=body.description.strip(), addresses=addresses, home=home, away=away)
    db.add(app)
    db.commit()
    logger.info("App %r added to the catalog by %s, %d address(es).", app.name, user.username, len(addresses))
    return {**apps_service.app_view(app), "tiles": 0}


@router.patch("/apps/{app_id}", summary="Change an app; every tile that follows it changes with it")
def update_app(app_id: int, body: AppPatch, user: AdminUser, db: DbSession) -> dict:
    app = db.get(App, app_id)
    if app is None:
        raise error("not_found", "There is no such app.", status.HTTP_404_NOT_FOUND)
    if body.name is not None:
        _name_free(db, body.name.strip(), app)
        app.name = body.name.strip()
    if body.icon is not None:
        app.icon = body.icon.strip()
    if body.description is not None:
        app.description = body.description.strip()
    try:
        if body.addresses is not None:
            app.addresses = apps_service.clean_addresses([entry.model_dump() for entry in body.addresses])
        app.home = _choice(app.addresses, app.home, body.home)
        app.away = _choice(app.addresses, app.away, body.away)
    except apps_service.AppRefused as failure:
        db.rollback()
        raise _refused(failure) from failure
    tiles = _tiles(db, app)
    for widget in tiles:
        # A tile that opened an address which is gone opens the first one now;
        # saying so beats a tile that keeps a label nobody can pick any more.
        choice = str((widget.options or {}).get("address") or "")
        if choice and choice != apps_service.AUTO and choice not in {entry["label"] for entry in app.addresses}:
            widget.options = {**(widget.options or {}), "address": ""}
    db.commit()
    logger.info("App %r changed by %s; %d tile(s) follow it.", app.name, user.username, len(tiles))
    _tell_boards(db, tiles)
    return {**apps_service.app_view(app), "tiles": len(tiles)}


@router.delete("/apps/{app_id}", summary="Delete an app; its tiles stay, as tiles of their own")
def delete_app(app_id: int, user: AdminUser, db: DbSession) -> dict:
    app = db.get(App, app_id)
    if app is None:
        raise error("not_found", "There is no such app.", status.HTTP_404_NOT_FOUND)
    tiles = _tiles(db, app)
    kept = apps_service.let_go(db, app)
    name = app.name
    db.delete(app)
    db.commit()
    logger.info("App %r deleted by %s; %d tile(s) kept as tiles of their own.", name, user.username, kept)
    _tell_boards(db, tiles)
    return {"tiles_kept": kept}
