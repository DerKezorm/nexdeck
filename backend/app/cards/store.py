"""Saving, finding and removing custom cards.

The text of a card goes into the table word for word with the checked
definition beside it. Reading a card by its short name goes through a cache
in memory that every save and every delete empties, so a card that was
just changed is never shown as it was.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import CardRecord, utcnow
from . import load

#: How many cards of its own an installation keeps (KARTEN-11 AC-8).
MAX_CARDS = 200
#: Short names the address ``/api/v1/cards/<name>`` has for other things. A card called so could not be opened.
RESERVED_SLUGS = frozenset({"library", "sources", "schema", "preview-image"})


class TooManyCards(Exception):
    """The installation keeps ``MAX_CARDS`` cards already."""


@dataclass(frozen=True)
class Entry:
    """A saved card, as the rest of nexdeck reads it."""

    id: int
    slug: str
    kind: str
    definition: Any
    text: str
    origin: str
    users_may_place: bool
    updated_at: datetime


#: Held while a save compares what the editor read with what is stored and writes: two administrators saving at once
#: cannot both pass the comparison (KARTEN-9 EC-3).
saving = threading.Lock()

#: One dictionary per database, so a test (or a restored backup) that opens another one starts empty.
_cache: WeakKeyDictionary[Engine, dict[str, Entry]] = WeakKeyDictionary()
_lock = threading.Lock()


def invalidate() -> None:
    with _lock:
        _cache.clear()


def _entry(row: CardRecord) -> Entry | None:
    try:
        definition = load.definition_from_data(row.definition)
    except ValueError:
        # Written by a newer nexdeck and not readable by this one: it stays in the table and out of the way.
        return None
    return Entry(row.id, row.slug, row.kind, definition, row.yaml_source, row.origin, row.users_may_place, row.updated_at)


def get(db: Session, slug: str) -> Entry | None:
    """A card by its short name, from memory when it is there."""
    key = db.get_bind().engine
    with _lock:
        cached = _cache.get(key, {}).get(slug)
    if cached is not None:
        return cached
    row = db.scalar(select(CardRecord).where(CardRecord.slug == slug))
    entry = _entry(row) if row else None
    if entry is not None:
        with _lock:
            _cache.setdefault(key, {})[slug] = entry
    return entry


def listing(db: Session) -> list[CardRecord]:
    return list(db.scalars(select(CardRecord).where(CardRecord.kind == "card").order_by(CardRecord.slug)))


def count(db: Session) -> int:
    return int(db.scalar(select(func.count(CardRecord.id)).where(CardRecord.kind == "card")) or 0)


def _slug_taken(loaded: load.Loaded) -> load.CardInvalid:
    slug = loaded.definition.slug
    return load.CardInvalid(
        [
            load.Problem(
                "card_slug_taken",
                f"A card with the short name {slug} exists already.",
                "slug",
                loaded.lines.get(("slug",)),
                {"slug": slug},
            )
        ]
    )


def create(
    db: Session,
    text: str,
    *,
    user_id: int | None = None,
    origin: str = "local",
    shop_ref: str = "",
    shop_version: str = "",
    commit: bool = True,
) -> CardRecord:
    """Check the text and keep it. Raises ``load.CardInvalid`` (or ``TooManyCards``); nothing is written then.

    Without ``commit`` the row is only flushed: an import of several documents commits them together, or none, and
    empties the cache itself afterwards.
    """
    loaded = load.load_definition(text)
    if loaded.definition.slug in RESERVED_SLUGS:
        raise load.CardInvalid(
            [
                load.Problem(
                    "card_slug_reserved",
                    f"The short name {loaded.definition.slug} is kept for nexdeck itself.",
                    "slug",
                    loaded.lines.get(("slug",)),
                    {"slug": loaded.definition.slug},
                )
            ]
        )
    if count(db) >= MAX_CARDS:
        raise TooManyCards
    if db.scalar(select(CardRecord.id).where(CardRecord.slug == loaded.definition.slug)) is not None:
        raise _slug_taken(loaded)
    row = CardRecord(
        slug=loaded.definition.slug,
        kind="card",
        yaml_source=text,
        definition=loaded.data,
        origin=origin,
        shop_ref=shop_ref,
        shop_version=shop_version,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(row)
    try:
        db.commit() if commit else db.flush()
    except IntegrityError as failure:
        db.rollback()
        raise _slug_taken(loaded) from failure
    if commit:
        invalidate()
    return row


def update(db: Session, row: CardRecord, text: str, *, user_id: int | None = None, commit: bool = True) -> CardRecord:
    """Replace the text of a saved card. The short name stays: boards refer to the card by it.

    ⚠️ ``updated_at`` is what the editor compares to see that somebody saved meanwhile, so it differs after every save,
    even when two of them fall into the same tick of the clock.
    """
    loaded = load.load_definition(text)
    if loaded.definition.slug != row.slug:
        raise load.CardInvalid(
            [
                load.Problem(
                    "card_slug_changed",
                    f"The short name of a saved card cannot change (it is {row.slug}).",
                    "slug",
                    loaded.lines.get(("slug",)),
                    {"slug": row.slug},
                )
            ]
        )
    row.yaml_source = text
    row.definition = loaded.data
    now = utcnow()
    row.updated_at = max(now, row.updated_at + timedelta(microseconds=1)) if row.updated_at else now
    row.updated_by = user_id
    if commit:
        db.commit()
        invalidate()
    else:
        db.flush()
    return row


def delete(db: Session, row: CardRecord) -> None:
    db.delete(row)
    db.commit()
    invalidate()


def set_users_may_place(db: Session, row: CardRecord, allowed: bool) -> None:
    row.users_may_place = allowed
    db.commit()
    invalidate()
