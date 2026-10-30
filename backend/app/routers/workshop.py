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
from ..cards import exchange, load, store
from ..cards import integration_store as integrations
from ..deps import AdminUser, DbSession, error
from ..models import CardRecord
from ..workshop import (
    catalog,
    derived,
    files,
    github_login,
    install,
    installed,
    state,
    thumbs,
    updates,
    views,
)
from ..workshop import skins as shop_skins

router = APIRouter(prefix="/api/v1/workshop", tags=["workshop"])
logger = logging.getLogger("nexdeck.workshop")
MAX_PICTURE_VERSION = 64


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
    if body.repo is not None and not state.REPO.fullmatch(body.repo):
        raise error("bad_repo", "The repository is written owner/name, for example DerKezorm/nexdeck-workshop.")
    before = (state.enabled(db), state.repo(db))
    state.configure(db, enabled=body.enabled, repo=body.repo)
    db.commit()
    after = (state.enabled(db), state.repo(db))
    if after != before:
        logger.info("%s changed the Card shop: %s, %s.", user.username, "on" if after[0] else "off", after[1])
    if not after[0] or after[1] != before[1]:
        catalog.forget()
        files.forget()
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
    updates.look(found)
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
    ctx = views.context(db)
    warning: catalog.CatalogError | None = None
    facts: derived.Facts | None = None
    try:
        facts = derived.of_text(await files.definition(repo, entry))
        if facts is None:
            warning = catalog.CatalogError("definition_unreadable", "The definition of this entry cannot be read, so what it reads and presses is not shown.", 400)
    except catalog.CatalogError as failure:
        warning = failure
    view = views.entry_view(entry, ctx, facts, unreadable=facts is None)
    view["readme"] = view["changelog"] = None
    try:
        view["readme"] = await files.text(repo, entry.files.readme)
        view["changelog"] = await files.text(repo, entry.files.changelog)
    except catalog.CatalogError as failure:
        warning = warning or failure
    view["files_warning"] = warning.view() if warning else None
    offered: list[dict[str, Any]] = []
    for one in install.offers(db, found, entry, facts.requires if facts else [])[0]:
        try:
            offered.append(views.entry_view(one, ctx, derived.of_text(await files.definition(repo, one)), unreadable=True))
        except catalog.CatalogError:
            offered.append(views.entry_view(one, ctx, unreadable=True))
    view["offered_integrations"] = offered
    return view


@router.get("/examples/{author}/{slug}", summary="The checked definition of an example, to open in the editor as a new draft; nothing is installed or saved")
async def read_example(author: str, slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Only entries the Workshop holds up as examples (``starter``). The text is the one the catalog's checksum names, like an installation's (KARTEN-19 AC-4)."""
    repo, found, _warning = await _catalog(db)
    entry = _entry(found, author, slug)
    if not entry.starter:
        raise error("no_such_example", "This entry is not one of the examples.", 404)
    try:
        install.gate(entry)
        text = await files.definition(repo, entry)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    # ⚠️ Checked in full the moment it is fetched, the way an installation checks it, not only when the draft is saved.
    refused = install.check_text(entry, text)
    if refused is not None:
        raise _failure(refused)
    return {"id": entry.id, "type": entry.type, "slug": install.free_short(db, entry), "text": text}


@router.get("/entries/{author}/{slug}/image/{theme}", summary="A picture of an entry, fetched by the server and kept for an hour")
async def entry_image(author: str, slug: str, theme: str, user: AdminUser, db: DbSession, v: str = "") -> Response:
    """The browser asks this server and never GitHub, so opening the shop tells GitHub nothing about the visitor.

    ``v`` is the ``picture_version`` of the entry: the address changes with it, so the browser keeps the pictures of an
    older version apart from the new ones. ⚠️ This server keeps them by the ``picture_version`` of the catalog, not by
    ``v``: a ``v`` the catalog does not name would otherwise fetch the picture from GitHub again, with the key of the shop,
    as often as somebody changes it.
    """
    if theme not in ("light", "dark"):
        raise error("no_such_picture", "The theme is light or dark.", 404)
    if len(v) > MAX_PICTURE_VERSION:
        raise error("bad_picture_version", f"The version of the picture has at most {MAX_PICTURE_VERSION} characters.", 400)
    repo, found, _warning = await _catalog(db)
    entry = _entry(found, author, slug)
    try:
        body = await files.image(repo, getattr(entry.files, theme), views.picture_version(entry))
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    if body is None:
        raise error("no_such_picture", "This entry has no such picture.", 404)
    return Response(content=body, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


class ThumbBody(BaseModel):
    on: bool


def _github_failure(problem: github_login.GithubError) -> HTTPException:
    return HTTPException(problem.status, {"code": problem.code, "message": problem.message, **problem.more})


@router.get("/entries/{author}/{slug}/thumb", summary="Whether you are signed in to GitHub and have put your thumb on the discussion of an entry")
async def read_thumb(author: str, slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """For the page of one entry, never for the tiles. GitHub is asked only when you are signed in and the entry has a discussion; otherwise ``on`` is null."""
    repo, found, _warning = await _catalog(db)
    try:
        return await thumbs.read(db, user, _entry(found, author, slug), repo)
    except github_login.GithubError as problem:
        raise _github_failure(problem) from problem


@router.put("/entries/{author}/{slug}/thumb", summary="Put your thumb on the discussion of an entry, or take it away, in your GitHub name")
async def put_thumb(author: str, slug: str, body: ThumbBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """The discussion is the one the catalog names for the entry, never one from the request. Needs your own sign-in to GitHub."""
    repo, found, _warning = await _catalog(db)
    try:
        return await thumbs.put(db, user, _entry(found, author, slug), repo, body.on)
    except github_login.GithubError as problem:
        raise _github_failure(problem) from problem


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
        # A card that was taken out of the shop, or needs a newer nexdeck, does not read through anybody's connection either.
        install.gate(entry)
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
    #: The word that replacing an own connection may throw away stored values (``dropped_fields`` of the check).
    confirm_dropped: bool = False


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
    if entry.type == "skin":
        # A skin is one file that becomes one skin here, under its own short name or the next free one: nothing to choose.
        refusal = install.check_text(entry, plan.text)
        return {
            "entry": views.entry_view(entry, ctx, plan.facts, unreadable=plan.facts is None),
            "ok": refusal is None,
            "documents": [],
            "problems": refusal.more.get("problems", []) if refusal is not None else [],
            "skin_key": install.free_short(db, entry),
            "missing_integrations": [],
            "offered_integrations": [],
            "risk_acknowledged": state.risk_acknowledged(db, user.id),
        }
    seen = install.inspect(db, plan, [one.id for one in plan.offered])
    return {
        "entry": views.entry_view(entry, ctx, plan.facts, unreadable=plan.facts is None),
        "ok": seen.ok,
        "documents": [one.view() for one in seen.items],
        "missing_integrations": seen.missing,
        "offered_integrations": [views.entry_view(one, ctx, plan.offered_facts[one.id], unreadable=True) for one in plan.offered],
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
    if entry.type == "skin":
        try:
            key = shop_skins.install(db, entry, plan.text, user_id=user.id)
        except catalog.CatalogError as failure:
            raise _failure(failure) from failure
        logger.info("%s installed skin %s from the Card shop.", user.username, entry.id)
        return {"slug": None, "integration": None, "skin": key, "integrations": [], "outcome": None, "missing_integrations": [], "place_url": "/system/skins"}
    try:
        install.confirm_drops(db, plan, body.choices, body.with_integrations, body.confirm_dropped)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
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


# -- updates and recalls ---------------------------------------------------------------------------


@router.get("/updates", summary="Which installed cards have an update waiting and which were taken out of the Card shop")
def read_updates(user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Read from the catalog as it was last fetched; this asks nobody, and says nothing while the shop is off (KARTEN-15 AC-1, AC-6, EC-3)."""
    if not state.enabled(db):
        return {"enabled": False, "catalog_known": False, "updates": [], "removed": []}
    found = catalog.known(state.repo(db))
    return {"enabled": True, "catalog_known": found is not None, **updates.updates_and_recalls(db, found)}


class SkinAcceptBody(BaseModel):
    """Whether to keep what was changed here as a copy, and the version the administrator looked at."""

    keep_mine: bool = True
    expected_version: str | None = Field(default=None, max_length=20)


async def _installed_skin(db: DbSession, key: str) -> tuple[str, Any, catalog.Entry]:
    row = shop_skins.from_shop(db, key)
    if row is None:
        raise error("not_installed_from_shop", "This skin did not come from the Card shop.", 404)
    repo, found, _warning = await _catalog(db)
    entry = found.by_id.get(row.shop_ref)
    if entry is None:
        raise error("no_such_entry", "The catalog has no such entry any more.", 404)
    return repo, row, entry


@router.get("/updates/skins/{key}", summary="What the update of a skin from the Card shop is: its versions and its list of changes")
async def read_skin_update(key: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """A skin reads and presses nothing, so there is nothing to confirm; whoever wears it wears the new version at once."""
    repo, row, entry = await _installed_skin(db, key)
    try:
        if entry.removed is not None:
            raise catalog.CatalogError("entry_removed", "This entry was removed from the Card shop.", 409)
        if not installed.newer(entry.version, row.shop_version):
            raise catalog.CatalogError("no_update", "This skin is up to date.", 409)
        changelog = await files.text(repo, entry.files.changelog)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    return {
        "key": row.key, "name": entry.name, "ref": entry.id, "installed_version": row.shop_version, "new_version": entry.version,
        "needs_newer": load.needs_newer(entry.min_nexdeck), "min_nexdeck": entry.min_nexdeck, "changelog": changelog,
        "locally_changed": shop_skins.as_installed(row).locally_changed,
    }


@router.post("/updates/skins/{key}/accept", summary="Take the update of a skin from the Card shop: whoever wears it wears the new version at once")
async def accept_skin_update(key: str, body: SkinAcceptBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    repo, row, entry = await _installed_skin(db, key)
    try:
        install.gate(entry)
        text = await files.definition(repo, entry)
        result = shop_skins.apply(db, row, entry, text, body.keep_mine, body.expected_version, user_id=user.id)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    if result["status"] == "updated":
        logger.info("%s updated skin %s from the Card shop to %s.", user.username, key, entry.version)
    return result


async def _installed_entry(db: DbSession, slug: str) -> tuple[str, CardRecord, catalog.Entry]:
    repo, found, _warning = await _catalog(db)
    row = updates.row_of(db, slug)
    if row is None:
        raise error("not_installed_from_shop", "This card did not come from the Card shop.", 404)
    entry = found.by_id.get(row.shop_ref)
    if entry is None:
        raise error("no_such_entry", "The catalog has no such entry any more.", 404)
    return repo, row, entry


@router.get("/updates/{slug}", summary="What the update of an installed card changes: its list of changes, what it may ask and press now")
async def read_update(slug: str, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """The new file is fetched and checked against the catalog; nothing is changed (KARTEN-15 AC-2, AC-3, EC-1, EC-6)."""
    from . import cards as card_routes

    repo, row, entry = await _installed_entry(db, slug)
    try:
        if entry.removed is not None:
            raise catalog.CatalogError("entry_removed", "This entry was removed from the Card shop.", 409)
        if not installed.newer(entry.version, row.shop_version):
            raise catalog.CatalogError("no_update", "This card is up to date.", 409)
        text = await files.definition(repo, entry)
        changelog = await files.text(repo, entry.files.changelog)
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    try:
        # Read as if this nexdeck were new enough: a card that needs a newer one is shown, not refused (EC-1).
        change = updates.permissions(row.definition or {}, load.load_definition(text, running_version="9999.0.0").data)
    except load.CardInvalid as failure:
        raise error("update_invalid", f"The new version cannot be read: {failure}") from failure
    one = installed.Installed("card", row.slug, row.shop_ref, row.shop_version, row.yaml_source, row.shop_hash)
    return {
        "slug": row.slug,
        "name": entry.name,
        "ref": entry.id,
        "installed_version": row.shop_version,
        "new_version": entry.version,
        "needs_newer": load.needs_newer(entry.min_nexdeck),
        "min_nexdeck": entry.min_nexdeck,
        "changelog": changelog,
        "locally_changed": one.locally_changed,
        "permissions": change,
        "buttons_to_confirm": updates.to_confirm(change),
        "connection_changed": updates.connection_changed(change),
        "placed_on": len(card_routes._placed(db).get(row.slug, {})),  # noqa: SLF001
    }


class AcceptBody(BaseModel):
    """The buttons the administrator confirmed, whether to keep his own changes as a copy, and the version he looked at."""

    confirmed_buttons: list[str] = Field(default_factory=list, max_length=20)
    keep_mine: bool = True
    expected_version: str | None = Field(default=None, max_length=20)


@router.post("/updates/{slug}/accept", summary="Take the update of an installed card: every board that shows it follows at once")
async def accept_update(slug: str, body: AcceptBody, user: AdminUser, db: DbSession) -> dict[str, Any]:
    """Nothing is taken without an administrator: the server checks that every new or changed button was confirmed (KARTEN-15 AC-3, AC-4, EC-5)."""
    from . import cards as card_routes

    repo, row, entry = await _installed_entry(db, slug)
    if not installed.newer(entry.version, row.shop_version) and entry.removed is None:
        return {"status": "already_up_to_date", "slug": row.slug, "version": row.shop_version, "copy_slug": None}
    try:
        install.gate(entry)
        text = await files.definition(repo, entry)
        with store.saving:
            try:
                result = updates.apply(db, row, entry, text, body.confirmed_buttons, body.keep_mine, body.expected_version, user_id=user.id)
                db.commit()
            except BaseException:
                db.rollback()
                raise
    except catalog.CatalogError as failure:
        raise _failure(failure) from failure
    if result["status"] == "updated":
        store.invalidate()
        card_routes._tell(db, row.slug)  # noqa: SLF001
        logger.info("%s took the update of the card %s to %s.", user.username, row.slug, entry.version)
    return result
