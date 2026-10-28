"""The Card shop: turning it on, the catalog, installing from it, updates and recalls (KARTEN-14, KARTEN-15).

Everything here is for administrators. The shop is off until one turns it on, and while it is off nothing here asks
GitHub (KARTEN-14 AC-2, EC-5). The address-by-address contract is ``API.md`` of the shop work.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from .. import __version__
from ..cards import exchange, store
from ..cards import integration_store as integrations
from ..deps import AdminUser, DbSession, error
from ..workshop import catalog, files, install, state, views

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])
logger = logging.getLogger("nexdeck.workshop")


class SettingsBody(BaseModel):
    enabled: bool | None = None
    repo: str | None = None


def _shop_off() -> Any:
    return error("shop_off", "The Card shop is off. Turn it on to load the catalog from GitHub.", 409)


def require_on(db: DbSession) -> str:
    """The repository to ask, or the refusal of a shop that is off."""
    if not state.enabled(db):
        raise _shop_off()
    return state.repo(db)


def _state(db: DbSession, user_id: int) -> dict[str, Any]:
    repo = state.repo(db)
    kept = catalog.known(repo) if state.enabled(db) else None
    return {
        "enabled": state.enabled(db),
        "repo": repo,
        "token_set": bool(state.token()),
        "risk_acknowledged": state.risk_acknowledged(db, user_id),
        "nexdeck_version": __version__,
        "catalog": None if kept is None else {
            "fetched_at": _iso(kept.fetched_at), "generated_at": kept.generated_at, "count": len(kept.entries),
        },
    }


def _iso(seconds: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")


@router.get("/state", summary="Whether the Card shop is on, where its catalog is, and whether a key is set")
def read_state(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Asks nobody: this is what the shop shows while it is still off."""
    return _state(db, user.id)


@router.put("/settings", summary="Turn the Card shop on or off, or name another repository for its catalog")
def change_settings(body: SettingsBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Turning it on asks nothing yet; the first request comes with the first look at the catalog. Turning it off forgets the catalog (EC-5)."""
    if body.repo is not None and not state.REPO.match(body.repo):
        raise error("bad_repo", "The repository is written owner/name, for example DerKezorm/nexdeck-workshop.")
    before = (state.enabled(db), state.repo(db))
    state.configure(db, enabled=body.enabled, repo=body.repo)
    db.commit()
    after = (state.enabled(db), state.repo(db))
    if after != before:
        logger.info("%s changed the Card shop: %s, %s.", user.username, "on" if after[0] else "off", after[1])
    if not after[0] or after[1] != before[1]:
        catalog.forget()
    return _state(db, user.id)


# -- the catalog -------------------------------------------------------------------------------


def _failure(failure: catalog.CatalogError) -> HTTPException:
    return HTTPException(failure.status, {"code": failure.code, "message": failure.message, **failure.more})


async def _catalog(db: DbSession) -> tuple[str, catalog.Catalog, catalog.CatalogError | None]:
    """The repository, its catalog (fetched when it is older than ten minutes) and why an old one is shown, if it is."""
    repo = require_on(db)
    try:
        found, warning = await catalog.load(repo)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    return repo, found, warning


def _entry(found: catalog.Catalog, author: str, slug: str) -> catalog.Entry:
    entry = found.by_id.get(f"{author}/{slug}")
    if entry is None:
        raise error("no_such_entry", "The catalog has no such entry.", 404)
    return entry


@router.get("/catalog", summary="The entries of the Card shop, fetched from GitHub when the last look is older than ten minutes")
async def read_catalog(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Cards and own connections with what fits this installation. Search, filter and sorting are the interface's (KARTEN-14 AC-3, AC-4)."""
    _repo, found, warning = await _catalog(db)
    ctx = views.context(db)
    return {
        "fetched_at": _iso(found.fetched_at),
        "generated_at": found.generated_at,
        "entries": [views.entry_view(entry, ctx) for entry in found.entries],
        "warning": warning.view() if warning else None,
    }


@router.get("/entries/{author}/{slug}", summary="One entry of the Card shop with its description and list of changes")
async def read_entry(author: str, slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """A text that cannot be fetched is left out and said in ``files_warning``; the rest of the page still shows (AC-5)."""
    repo, found, _warning = await _catalog(db)
    entry = _entry(found, author, slug)
    view = views.entry_view(entry, views.context(db))
    view["readme"] = view["changelog"] = view["files_warning"] = None
    try:
        view["readme"] = await files.text(repo, entry.files.readme)
        view["changelog"] = await files.text(repo, entry.files.changelog)
    except catalog.CatalogError as failure:
        view["files_warning"] = failure.view()
    ctx = views.context(db)
    view["offered_integrations"] = [views.entry_view(one, ctx) for one in install.offers(db, found, entry)[0]]
    return view


@router.get("/entries/{author}/{slug}/image/{theme}", summary="A picture of an entry, fetched by the server and kept for an hour")
async def entry_image(author: str, slug: str, theme: str, user: AdminUser, db: DbSession) -> Response:
    """The browser asks this server and never GitHub, so opening the shop tells GitHub nothing about the visitor."""
    if theme not in ("light", "dark"):
        raise error("no_such_picture", "The theme is light or dark.", 404)
    repo, found, _warning = await _catalog(db)
    entry = _entry(found, author, slug)
    try:
        body = await files.image(repo, getattr(entry.files, theme))
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    if body is None:
        raise error("no_such_picture", "This entry has no such picture.", 404)
    return Response(content=body, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


class PreviewBody(BaseModel):
    integration_id: int


@router.post("/entries/{author}/{slug}/preview", summary="Show a card with the data of one of your connections, without installing it")
async def preview_entry(author: str, slug: str, body: PreviewBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """The preview of the card editor, on the definition of the catalog after its checksum was checked (KARTEN-14 AC-6)."""
    from . import cards as card_routes

    repo, found, _warning = await _catalog(db)
    entry = _entry(found, author, slug)
    if entry.type != "card":
        raise error("no_preview", "Only a card has a preview.")
    try:
        text = await files.definition(repo, entry)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    return await card_routes.preview(card_routes.PreviewBody(yaml=text, integration_id=body.integration_id), user)


# -- installing ----------------------------------------------------------------------------------


class InstallBody(BaseModel):
    """What to do with a name that is taken (``card:<slug>``, ``integration:<short>``), which offered own connections to take along, and the word about the risk."""

    choices: dict[str, str] = Field(default_factory=dict, max_length=exchange.MAX_DOCUMENTS)
    with_integrations: list[str] = Field(default_factory=list, max_length=10)
    accept_risk: bool = False


async def _prepared(db: DbSession, author: str, slug: str) -> tuple[catalog.Entry, install.Plan, views.Context]:
    repo, found, _warning = await _catalog(db)
    entry = _entry(found, author, slug)
    try:
        return entry, await install.prepare(db, repo, found, entry), views.context(db)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure


@router.post("/entries/{author}/{slug}/install/check", summary="Say what installing an entry of the Card shop would make, without making anything")
async def check_install(author: str, slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """The documents of the entry (and the own connections on offer) read the way an import reads a file: what exists here already needs a choice (KARTEN-14 AC-7, AC-8, EC-4)."""
    entry, plan, ctx = await _prepared(db, author, slug)
    seen = install.inspect(db, plan, [one.id for one in plan.offered])
    return {
        "entry": views.entry_view(entry, ctx),
        "ok": seen.ok,
        "documents": [one.view() for one in seen.items],
        "missing_integrations": seen.missing,
        "offered_integrations": [views.entry_view(one, ctx) for one in plan.offered],
        "risk_acknowledged": state.risk_acknowledged(db, user.id),
    }


@router.post("/entries/{author}/{slug}/install", status_code=status.HTTP_201_CREATED, summary="Install an entry of the Card shop, with the own connections it needs if you accept them")
async def install_entry(author: str, slug: str, body: InstallBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Every document or none. The first installation of an administrator needs his word that cards of the shop run at his own risk (AC-9)."""
    from . import cards as card_routes

    entry, plan, _ctx = await _prepared(db, author, slug)
    try:
        install.acknowledge(db, user.id, body.accept_risk)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    db.commit()
    with store.saving, integrations.saving:
        try:
            result = install.install(db, plan, body.choices, body.with_integrations, user_id=user.id)
            db.commit()
        except exchange.Refused as failure:
            db.rollback()
            raise card_routes._refused(failure) from failure  # noqa: SLF001
        except BaseException:
            db.rollback()
            raise
    exchange.finish(result["outcome"])
    made: dict[str, str] = result["made"]
    logger.info("%s installed %s %s from the Card shop.", user.username, entry.type, entry.id)
    return {
        "slug": made.get(entry.id) if entry.type == "card" else None,
        "integration": made.get(entry.id) if entry.type == "integration" else None,
        "integrations": [made[one.id] for one in plan.offered if one.id in made and entry.type == "card"],
        "outcome": result["outcome"].view(),
        "missing_integrations": [*plan.missing, *(f"custom:{one.slug}" for one in plan.offered if one.id not in body.with_integrations)],
        "place_url": "/system/custom-cards",
    }
