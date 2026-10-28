"""Updates and recalls of what was installed from the shop (KARTEN-15).

An update is never taken by itself: it waits until an administrator has seen what changes, the new or changed buttons
one by one (AC-2, AC-3), and accepts it. A card that was taken out of the shop runs on; the shop only says so, and rings
the bell of every administrator when the reason is ``harmful`` (AC-6, AC-7).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import yaml
from sqlalchemy.orm import Session

from ..cards import load, store
from ..models import CardRecord
from ..services import chronicle
from ..services.notify import emit
from . import catalog, installed, state
from .installed import Installed

logger = logging.getLogger("nexdeck.workshop")

#: The part of a button that decides what it does at the service and how it asks first; a change in one of these needs a new
#: confirmation. The questions before it runs (``confirm``, ``danger``, ``asks``) and what it shows afterwards (``answer``)
#: count too: a button that no longer asks "Really?" acts differently for the person who presses it, which is stricter than KARTEN-15 AC-3.
BUTTON_ACTS = ("method", "path", "send", "body", "where", "confirm", "danger", "asks", "answer")
BUTTON_SHOWN = ("id", "label", *BUTTON_ACTS)
SUFFIX = " (mine)"
NAME_MAX = 60


def plain(text: Any) -> str:
    """A name or a reason as one line of text: the English wording of a text in several languages."""
    if isinstance(text, dict):
        text = text.get("en") or next(iter(text.values()), "")
    return str(text or "")


# -- what is to be told ----------------------------------------------------------------------------


def updates_and_recalls(db: Session, found: catalog.Catalog | None) -> dict[str, list[dict[str, Any]]]:
    """The updates that are waiting and the entries taken out of the shop, for what this installation has from it."""
    updates: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    if found is None:
        return {"updates": updates, "removed": removed}
    for ref, haves in installed.listing(db).items():
        entry = found.by_id.get(ref)
        if entry is None:
            continue
        for one in haves:
            if entry.removed is not None:
                removed.append({"slug": one.slug, "type": one.type, "ref": ref, "name": entry.name, **entry.removed.model_dump()})
            elif installed.update_available(entry, one):
                updates.append({
                    "slug": one.slug, "type": one.type, "ref": ref, "name": entry.name, "installed_version": one.version, "new_version": entry.version,
                    "needs_newer": load.needs_newer(entry.min_nexdeck), "min_nexdeck": entry.min_nexdeck, "locally_changed": one.locally_changed,
                })
    return {"updates": updates, "removed": removed}


def card_hints(db: Session, found: catalog.Catalog | None) -> dict[str, dict[str, Any]]:
    """What ``GET /cards`` adds to each card that came from the shop."""
    told = updates_and_recalls(db, found)
    out: dict[str, dict[str, Any]] = {}
    for row in db.query(CardRecord.slug, CardRecord.shop_ref).filter(CardRecord.kind == "card", CardRecord.origin == "shop", CardRecord.shop_ref != ""):
        out[row.slug] = {"ref": row.shop_ref, "update": False, "removed": None}
    for one in told["updates"]:
        if one["slug"] in out:
            out[one["slug"]]["update"] = True
    for one in told["removed"]:
        if one["slug"] in out:
            out[one["slug"]]["removed"] = {"level": one["level"], "reason": one["reason"], "at": one["at"]}
    return out


def look(found: catalog.Catalog) -> None:
    """A catalog that was just fetched is looked at for recalls, once."""
    if not found.announced:
        found.announced = True
        announce(found)


def announce(found: catalog.Catalog) -> None:
    """Ring the bell of every administrator once for each installed entry that was taken out as ``harmful`` (AC-7)."""
    from ..db import db_session

    with db_session() as db:
        if not state.enabled(db):
            return
        already = set(state.told(db))
        fresh: list[tuple[str, str, str]] = []
        for one in updates_and_recalls(db, found)["removed"]:
            key = f"{one['ref']}@{one['at']}"
            # A card installed twice (a copy) is one entry: the bell rings once for it.
            if one["level"] == "harmful" and key not in already and all(key != other[0] for other in fresh):
                fresh.append((key, plain(one["name"]) or one["slug"], one["reason"]))
        if fresh:
            state.mark_told(db, [key for key, _name, _reason in fresh])
            db.commit()
    for _key, name, reason in fresh:
        logger.warning("%s was removed from the Card shop as harmful.", name)
        emit("card_recalled", f"{name[:80]} was removed from the Card shop as harmful", reason, level="error", link="/system/custom-cards")


# -- what an update changes --------------------------------------------------------------------------


def _button(one: dict[str, Any]) -> dict[str, Any]:
    return {name: one.get(name) for name in BUTTON_SHOWN}


def _act(one: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(json.dumps(one.get(name), sort_keys=True) for name in BUTTON_ACTS)


def permissions(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """The difference in what a card may ask and press: the kinds it reads through, its requests (their paths) and its buttons."""
    before_kinds, after_kinds = [str(k) for k in old.get("requires", [])], [str(k) for k in new.get("requires", [])]
    before = {str(one["id"]): one for one in old.get("requests", [])}
    after = {str(one["id"]): one for one in new.get("requests", [])}
    old_buttons = {str(one["id"]): _button(one) for one in old.get("buttons", [])}
    new_buttons = {str(one["id"]): _button(one) for one in new.get("buttons", [])}
    changed = [{"before": old_buttons[key], "after": new_buttons[key]} for key in new_buttons if key in old_buttons and _act(old_buttons[key]) != _act(new_buttons[key])]
    return {
        "requires": {"added": [k for k in after_kinds if k not in before_kinds], "removed": [k for k in before_kinds if k not in after_kinds]},
        "requests": {
            "added": [{"id": key, "path": after[key]["path"]} for key in after if key not in before],
            "changed": [{"id": key, "before": before[key]["path"], "after": after[key]["path"]} for key in after if key in before and before[key]["path"] != after[key]["path"]],
            "removed": [{"id": key, "path": before[key]["path"]} for key in before if key not in after],
        },
        "buttons": {
            "added": [new_buttons[key] for key in new_buttons if key not in old_buttons],
            "changed": changed,
            "removed": [old_buttons[key] for key in old_buttons if key not in new_buttons],
        },
    }


def to_confirm(change: dict[str, Any]) -> list[str]:
    """The buttons the administrator has to confirm one by one: those that are new and those that act differently (AC-3)."""
    return [one["id"] for one in change["buttons"]["added"]] + [one["after"]["id"] for one in change["buttons"]["changed"]]


def connection_changed(change: dict[str, Any]) -> bool:
    """The update changes which kinds of connection the card reads through (EC-6)."""
    return bool(change["requires"]["added"] or change["requires"]["removed"])


# -- text surgery ------------------------------------------------------------------------------------


def _scalar_edits(node: Any, make: Any) -> list[tuple[int, int, str]]:
    edits: list[tuple[int, int, str]] = []
    if isinstance(node, yaml.ScalarNode):
        # A block scalar ends with its line break, which the replacement has to keep.
        tail = "\n" if node.style in ("|", ">") else ""
        edits.append((node.start_mark.index, node.end_mark.index, make(node.value) + tail))
    elif isinstance(node, yaml.MappingNode):
        for _key, value in node.value:
            edits += _scalar_edits(value, make)
    return edits


def _edited(text: str, places: dict[str, Any]) -> str:
    """The text with the value of the top-level keys changed in place, nothing else touched (comments, order, quotes)."""
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if not isinstance(root, yaml.MappingNode):
        raise ValueError("not a mapping")
    edits: list[tuple[int, int, str]] = []
    for key, value in root.value:
        if isinstance(key, yaml.ScalarNode) and key.value in places:
            edits += _scalar_edits(value, places[key.value])
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def with_slug(text: str, slug: str) -> str:
    """The text with another short name."""
    return _edited(text, {"slug": lambda _old: slug})


def _mine(old: str) -> str:
    old = old.strip()
    return json.dumps(f"{old[: NAME_MAX - len(SUFFIX)]}{SUFFIX}" if len(old) + len(SUFFIX) > NAME_MAX else f"{old}{SUFFIX}", ensure_ascii=False)


def copy_text(text: str, slug: str) -> str:
    """The text of a card for "Keep mine as a copy": another short name, and its name (every language) followed by (mine) (EC-7)."""
    return _edited(text, {"slug": lambda _old: slug, "name": _mine})


def free_slug(db: Session, slug: str) -> str:
    taken = {one.slug for one in store.listing(db)} | set(store.RESERVED_SLUGS)
    for number in range(1, 1000):
        suffix = "-mine" if number == 1 else f"-mine-{number}"
        candidate = f"{slug[: 60 - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
    raise catalog.CatalogError("no_free_name", "No free short name for a copy.", 409)


# -- taking an update -----------------------------------------------------------------------------------


def row_of(db: Session, slug: str) -> CardRecord | None:
    return db.query(CardRecord).filter(CardRecord.slug == slug, CardRecord.kind == "card", CardRecord.origin == "shop", CardRecord.shop_ref != "").first()


def apply(db: Session, row: CardRecord, entry: catalog.Entry, text: str, confirmed: list[str], keep_mine: bool, expected: str | None, *, user_id: int) -> dict[str, Any]:
    """Make the card the new version, without committing; the caller holds ``store.saving`` and commits.

    Everything is looked at again here, in the lock: two administrators who accept the same update at nearly the same
    moment both get here, and the second finds the card up to date already (EC-5).
    """
    db.refresh(row)
    if not installed.newer(entry.version, row.shop_version):
        return {"status": "already_up_to_date", "slug": row.slug, "version": row.shop_version, "copy_slug": None}
    if expected is not None and expected != entry.version:
        raise catalog.CatalogError("update_changed", f"A newer version ({entry.version}) came while you looked. Look at what it changes first.", 409, version=entry.version)
    try:
        loaded = load.load_definition(text)
    except load.CardInvalid as failure:
        raise catalog.CatalogError("update_invalid", f"The new version cannot be read: {failure}", 400) from failure
    change = permissions(row.definition or {}, loaded.data)
    missing = [one for one in to_confirm(change) if one not in confirmed]
    if missing:
        raise catalog.CatalogError("buttons_not_confirmed", "Every new or changed button has to be confirmed.", 409, missing=missing)
    one = Installed("card", row.slug, row.shop_ref, row.shop_version, row.yaml_source, row.shop_hash)
    copy_slug: str | None = None
    if one.locally_changed and keep_mine:
        copy_slug = free_slug(db, row.slug)
        try:
            store.create(db, copy_text(row.yaml_source, copy_slug), user_id=user_id, commit=False)
        except store.TooManyCards:
            raise catalog.CatalogError("too_many_cards", f"There are {store.MAX_CARDS} custom cards already, which is the most nexdeck keeps. Delete one first.", 409) from None
        except (load.CardInvalid, ValueError) as failure:
            raise catalog.CatalogError("copy_failed", f"The copy of your changes could not be made: {failure}", 400) from failure
        chronicle.record("card_definition_added", user_id=user_id, name=copy_slug, detail=f"copy of {row.slug} made before the update from the Card shop", db=db)
    try:
        store.update(db, row, with_slug(text, row.slug) if loaded.definition.slug != row.slug else text, user_id=user_id, commit=False)
    except load.CardInvalid as failure:
        raise catalog.CatalogError("update_invalid", f"The new version cannot be read: {failure}", 400) from failure
    row.shop_version, row.shop_hash = entry.version, installed.normalised_hash(row.yaml_source)
    chronicle.record("card_definition_changed", user_id=user_id, name=row.slug, detail=f"updated from the Card shop to {entry.version}", db=db)
    return {"status": "updated", "slug": row.slug, "version": entry.version, "copy_slug": copy_slug}
