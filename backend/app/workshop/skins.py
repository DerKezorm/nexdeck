"""Skins from the shop: installed, told when a newer version is there, and updated (skins, phase D).

A skin from the shop is a skin like any other here: the file is read and compiled by this nexdeck, never the style sheet
somebody else made of it, so it reaches no page a skin may not reach and fetches nothing. It is marked with the entry it
came from, as a card is, so the shop can offer its updates. Its short name is the entry's own, or the next free one
with -2, -3, … when a skin here has it.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Skin
from ..skins import store as skin_store
from . import catalog, installed

#: The longest short name a skin has (``skins.css.KEY``).
KEY_MAX = 32
SUFFIX = " (mine)"


def check_text(text: str) -> catalog.CatalogError | None:
    """What is wrong with the file of a skin by the checks of this nexdeck; none when nothing is."""
    try:
        skin_store.check(text)
    except skin_store.SkinError as failure:
        return catalog.CatalogError("entry_invalid", "This entry does not pass the check of this nexdeck.", 422, problems=failure.problems or [{"path": "", "message": failure.message}])
    return None


def free_key(db: Session, key: str, suffix: str = "") -> str:
    """``key`` when no skin here has it (one nexdeck ships included), else the next of key-2, key-3, …"""
    for number in range(1, 1000):
        tail = f"{suffix}" if number == 1 else f"{suffix}-{number}"
        candidate = key[: KEY_MAX - len(tail)].rstrip("-") + tail
        if not skin_store.exists(db, candidate):
            return candidate
    raise catalog.CatalogError("no_free_name", "No free short name for this skin.", 409)


def _with(text: str, **fields: Any) -> str:
    """The file with other values at the top; the file as it came when nothing changes, so that its checksum stays."""
    data = json.loads(text)
    if all(data.get(name) == value for name, value in fields.items()):
        return text
    return json.dumps({**data, **fields}, ensure_ascii=False, indent=2)


def install(db: Session, entry: catalog.Entry, text: str, *, user_id: int) -> str:
    """Save the skin of an entry and mark where it came from; the short name it got here. Commits."""
    key = free_key(db, entry.slug)
    stored = _with(text, key=key)
    try:
        skin_store.save(db, stored, user_id, origin="shop", commit=False)
    except skin_store.SkinError as failure:
        db.rollback()
        raise catalog.CatalogError("entry_invalid", "This entry does not pass the check of this nexdeck.", 422, problems=failure.problems) from failure
    row = row_of(db, key)
    assert row is not None
    row.shop_ref, row.shop_version, row.shop_hash = entry.id, entry.version, installed.normalised_hash(stored)
    db.commit()
    return key


def row_of(db: Session, key: str) -> Skin | None:
    return db.scalar(select(Skin).where(Skin.key == key))


def from_shop(db: Session, key: str) -> Skin | None:
    row = row_of(db, key)
    return row if row is not None and row.origin == "shop" and row.shop_ref else None


def as_installed(row: Skin) -> installed.Installed:
    return installed.Installed("skin", row.key, row.shop_ref, row.shop_version, row.text, row.shop_hash)


def apply(db: Session, row: Skin, entry: catalog.Entry, text: str, keep_mine: bool, expected: str | None, *, user_id: int) -> dict[str, Any]:
    """Make the skin the new version and commit. What somebody changed here is kept as a copy when they want it.

    The skin keeps its short name here, so whoever wears it wears the new version at once.
    """
    db.refresh(row)
    if not installed.newer(entry.version, row.shop_version):
        return {"status": "already_up_to_date", "key": row.key, "version": row.shop_version, "copy_key": None}
    if expected is not None and expected != entry.version:
        raise catalog.CatalogError("update_changed", f"A newer version ({entry.version}) came while you looked. Look at it first.", 409, version=entry.version)
    copy_key: str | None = None
    try:
        if as_installed(row).locally_changed and keep_mine:
            copy_key = free_key(db, row.key, "-mine")
            mine = json.loads(row.text)
            skin_store.save(db, _with(row.text, key=copy_key, name=(str(mine.get("name") or row.key)[: 60 - len(SUFFIX)] + SUFFIX)), user_id, commit=False)
        stored = _with(text, key=row.key)
        skin_store.save(db, stored, user_id, replacing=row.key, commit=False)
    except skin_store.SkinError as failure:
        db.rollback()
        raise catalog.CatalogError("update_invalid", f"The new version cannot be worn here: {failure.message}", 400, problems=failure.problems) from failure
    row.shop_version, row.shop_hash = entry.version, installed.normalised_hash(stored)
    db.commit()
    return {"status": "updated", "key": row.key, "version": entry.version, "copy_key": copy_key}
