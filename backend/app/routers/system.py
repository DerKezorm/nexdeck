"""Health, about, settings and the what's-new marker."""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select

from .. import __version__
from ..config import get_settings
from ..deps import AdminUser, CurrentUser, DbSession
from ..models import Board, Integration, Setting, User, Widget
from ..schemas import SettingsBody
from ..services import collector as collector_module
from ..services.collector import collector, demo_flag, set_demo_flag
from ..services.sse import hub

router = APIRouter(tags=["system"])
logger = logging.getLogger("nexdeck.system")

RELEASES_URL = "https://api.github.com/repos/nexapps/nexdeck/releases/latest"
_update_cache: dict[str, object] = {}


@router.get("/api/health", summary="Is the server alive")
def health() -> dict:
    """Public. Used by the container healthcheck."""
    return {"status": "ok", "version": __version__}


def get_setting(db: DbSession, key: str, default: dict | None = None) -> dict:
    row = db.get(Setting, key)
    return dict(row.value) if row is not None else (default or {})


def put_setting(db: DbSession, key: str, value: dict) -> None:
    db.merge(Setting(key=key, value=value))


@router.get("/api/v1/about", summary="Version, counts and settings overview")
async def about(user: CurrentUser, db: DbSession) -> dict:
    settings = get_settings()
    general = get_setting(db, "general")
    payload = {
        "version": __version__,
        "demo": settings.demo or demo_flag(),
        "public_url": general.get("public_url") or settings.public_url,
        "update_check": bool(general.get("update_check", settings.update_check)),
        "default_locale": general.get("default_locale", "en"),
        "counts": {
            "boards": int(db.scalar(select(func.count(Board.id))) or 0),
            "widgets": int(db.scalar(select(func.count(Widget.id))) or 0),
            "integrations": int(db.scalar(select(func.count(Integration.id))) or 0),
            "users": int(db.scalar(select(func.count(User.id))) or 0),
        },
        "connections": hub.connections,
        "latest_version": None,
    }
    if payload["update_check"] and user.role == "admin":
        payload["latest_version"] = await latest_version()
    return payload


async def latest_version() -> str | None:
    now = time.monotonic()
    if _update_cache.get("until", 0) > now:
        return _update_cache.get("version")  # type: ignore[return-value]
    version: str | None = None
    try:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "nexdeck"}) as client:
            response = await client.get(RELEASES_URL)
        if response.status_code == 200:
            version = str(response.json().get("tag_name", "")).lstrip("v") or None
    except httpx.HTTPError:
        version = None
    _update_cache.update({"until": now + 6 * 3600, "version": version})
    return version


@router.patch("/api/v1/settings", summary="Change installation settings")
def patch_settings(body: SettingsBody, user: AdminUser, db: DbSession) -> dict:
    general = get_setting(db, "general")
    if body.public_url is not None:
        general["public_url"] = body.public_url.strip().rstrip("/")
    if body.update_check is not None:
        general["update_check"] = body.update_check
    if body.default_locale is not None:
        general["default_locale"] = body.default_locale
    if body.demo is not None:
        general["demo"] = body.demo
        set_demo_flag(body.demo)
    put_setting(db, "general", general)
    db.commit()
    if body.demo is not None:
        for widget_id in list(db.scalars(select(Widget.id))):
            collector.schedule(widget_id)
    return general


def load_demo_flag(db: DbSession) -> None:
    general = get_setting(db, "general")
    set_demo_flag(bool(general.get("demo", False)))


def module_reference() -> object:
    return collector_module
