"""Health, about, settings and the what's-new marker."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select

from .. import __version__
from ..adapters.base import outbound_client
from ..config import get_settings
from ..deps import AdminUser, CurrentUser, DbSession, error
from ..models import Board, Integration, Setting, User, Widget
from ..schemas import SettingsBody
from ..services import collector as collector_module
from ..services import two_factor
from ..services.collector import collector, demo_flag, set_demo_flag
from ..services.notify import emit
from ..services.sse import hub

router = APIRouter(tags=["system"])
logger = logging.getLogger("nexdeck.system")

#: Where nexdeck lives. One place, so the About page and the update check can
#: never point at two different repositories.
REPO_URL = "https://github.com/DerKezorm/nexdeck"
WEBSITE_URL = "https://nexdeck.nexapps.dev"
LICENSE = "AGPL-3.0-or-later"
RELEASES_URL = "https://api.github.com/repos/DerKezorm/nexdeck/releases/latest"
#: The newest version already announced, so the timer does not repeat itself.
_told_about: str | None = None
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
        "require_two_factor": two_factor.required(db),
        "repo_url": REPO_URL,
        "release_url": f"{REPO_URL}/releases",
        "issues_url": f"{REPO_URL}/issues",
        "website_url": WEBSITE_URL,
        "license": LICENSE,
        "checked_at": _update_cache.get("at"),
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


async def latest_version(force: bool = False) -> str | None:
    now = time.monotonic()
    if not force and _update_cache.get("until", 0) > now:
        return _update_cache.get("version")  # type: ignore[return-value]
    version: str | None = None
    try:
        async with outbound_client(timeout=8, headers={"User-Agent": "nexdeck"}) as client:
            response = await client.get(RELEASES_URL)
        if response.status_code == 200:
            version = str(response.json().get("tag_name", "")).lstrip("v") or None
    except httpx.HTTPError:
        version = None
    _update_cache.update({"until": now + 6 * 3600, "version": version, "at": datetime.now(UTC).isoformat()})
    if version:
        _tell_about_update(version, __version__)
    return version


@router.post("/api/v1/about/check", summary="Ask GitHub for the newest version now")
async def check_now(admin: AdminUser, db: DbSession) -> dict:
    """The daily question, asked by hand. Off by default like the daily one:
    it is the one call nexdeck makes to the outside, and only an administrator
    who has switched it on gets it."""
    general = get_setting(db, "general")
    if not bool(general.get("update_check", get_settings().update_check)):
        raise error("update_check_off", "The update check is switched off.")
    await latest_version(force=True)
    return await about(admin, db)


def _tell_about_update(latest: str, current: str) -> None:
    """Say it once per version, not once per check.

    ⚠️ The check runs on a timer. Without the note of what was already said,
    every administrator would hear about the same release every few hours.
    """
    global _told_about
    if not latest or latest == current or latest == _told_about:
        return
    _told_about = latest
    logger.info("nexdeck %s is out; this installation runs %s.", latest, current)
    emit("update_available", f"nexdeck {latest} is out",
         f"This installation runs {current}.", link="https://github.com/DerKezorm/nexdeck/releases")


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
    if body.require_two_factor is not None:
        # Its own key, not "general": this is the one setting where reading a
        # stale copy would decide whether somebody gets in.
        two_factor.set_required(db, body.require_two_factor)
    put_setting(db, "general", general)
    db.commit()
    named = [name for name, value in (("public URL", body.public_url), ("update check", body.update_check),
                                      ("default language", body.default_locale), ("demo mode", body.demo),
                                      ("second factor for everybody", body.require_two_factor))
             if value is not None]
    if named:
        logger.info("Installation settings changed by %s: %s.", user.username, ", ".join(named))
    if body.demo is not None:
        for widget_id in list(db.scalars(select(Widget.id))):
            collector.schedule(widget_id)
    return {**general, "require_two_factor": two_factor.required(db)}


def load_demo_flag(db: DbSession) -> None:
    general = get_setting(db, "general")
    set_demo_flag(bool(general.get("demo", False)))


def module_reference() -> object:
    return collector_module
