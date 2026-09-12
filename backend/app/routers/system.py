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
from ..deps import AdminUser, CurrentUser, DbSession
from ..models import Board, Integration, Setting, User, Widget
from ..schemas import SettingsBody
from ..services import collector as collector_module
from ..services import two_factor
from ..services.collector import collector, demo_flag, set_demo_flag
from ..services.notify import emit
from ..services.public_url import public_url
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

#: One client for the update check, kept for the life of the process.
#:
#: ⚠️ A fresh :class:`httpx.AsyncClient` builds a TLS context and loads the CA
#: bundle, and it does that on the event loop: measured on Windows on
#: 09.09.2026, 1.0 s for one and 11.35 s for eleven in a row. The answer is
#: cached for six hours, so this is the cheapest of the four places that paid
#: it, but it is also the one an administrator triggers by hand and then
#: watches: the second the button costs was a second of nothing else moving.
#: Same shape as ``health.http_client`` and ``icons.http_client``.
_client: httpx.AsyncClient | None = None


def http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = outbound_client(timeout=8, headers={"User-Agent": "nexdeck"})
    return _client


async def close_client() -> None:
    """Shutdown: let go of the connection the update check holds open."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


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
        "public_url": public_url(db),
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
    if user.role == "admin":
        # ⚠️ The switch decides whether nexdeck *asks*, not whether an answer
        # it already has may be shown. With the switch off this returned None
        # even right after somebody had pressed "check now", so the press
        # looked like it had failed. Nothing goes out on this path unless the
        # switch is on.
        payload["latest_version"] = await latest_version() if payload["update_check"] else _update_cache.get("version")
    return payload


async def latest_version(force: bool = False) -> str | None:
    now = time.monotonic()
    if not force and _update_cache.get("until", 0) > now:
        return _update_cache.get("version")  # type: ignore[return-value]
    version: str | None = None
    try:
        response = await http_client().get(RELEASES_URL, timeout=8)
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
    """The daily question, asked by hand.

    ⚠️ This used to be refused while the daily check was off, on the grounds
    that it is the one call nexdeck makes to the outside. That reasoning
    covers the *standing* call, which an operator has to agree to, and not
    this one: an administrator pressing a button is the consent. The effect
    was that the one person most likely to want to look now and then, the one
    who deliberately keeps a daily outbound call switched off, was the only
    one who could not.

    The switch still decides whether nexdeck asks by itself. Nothing goes out
    here unless somebody presses.
    """
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
