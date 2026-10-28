"""Saving, finding and removing own connections (KARTEN-3).

The text goes into the table word for word with the checked definition beside it, like a card. Every save and every
delete also changes the registry the same moment, so the change holds for every connection of the kind at once (AC-11).
"""

from __future__ import annotations

import threading
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Integration, OwnIntegration, utcnow
from . import integration as loader
from . import integration_schema as sch
from . import load

#: How many own kinds an installation keeps (KARTEN-3 AC-12).
MAX_INTEGRATIONS = sch.MAX_INTEGRATIONS

#: Held while a save compares what the editor read with what is stored and writes.
saving = threading.Lock()


class TooManyIntegrations(Exception):
    """The installation keeps ``MAX_INTEGRATIONS`` own kinds already."""


def kind_of(short: str) -> str:
    return f"custom:{short}"


def listing(db: Session) -> list[OwnIntegration]:
    return list(db.scalars(select(OwnIntegration).order_by(OwnIntegration.short)))


def count(db: Session) -> int:
    return int(db.scalar(select(func.count(OwnIntegration.id))) or 0)


def get(db: Session, short: str) -> OwnIntegration | None:
    return db.scalar(select(OwnIntegration).where(OwnIntegration.short == short))


def connections(db: Session, short: str) -> int:
    return int(db.scalar(select(func.count(Integration.id)).where(Integration.kind == kind_of(short))) or 0)


def _taken(loaded: loader.LoadedIntegration) -> load.CardInvalid:
    short = loaded.definition.short
    return load.CardInvalid([load.Problem("card_integration_short_exists", f"An own connection called {short} exists already.", "short", loaded.lines.get(("short",)), {"short": short})])


def create(db: Session, text: str, *, user_id: int | None = None, commit: bool = True) -> OwnIntegration:
    """Check the text and keep it. Raises ``load.CardInvalid`` (or ``TooManyIntegrations``); nothing is written then.

    Without ``commit`` the row is only flushed and the registry stays as it is: an import of several documents commits
    them together, or none, and registers the kinds itself afterwards.
    """
    loaded = loader.load_integration(text)
    short = loaded.definition.short
    if get(db, short) is not None:
        raise _taken(loaded)
    if count(db) >= MAX_INTEGRATIONS:
        raise TooManyIntegrations
    row = OwnIntegration(short=short, yaml_source=text, definition=loaded.data, created_by=user_id, updated_by=user_id)
    db.add(row)
    try:
        db.commit() if commit else db.flush()
    except IntegrityError as failure:
        db.rollback()
        raise _taken(loaded) from failure
    if commit:
        _register(row)
    return row


def update(db: Session, row: OwnIntegration, text: str, *, user_id: int | None = None, commit: bool = True) -> OwnIntegration:
    """Replace the text. The short name stays: connections refer to the kind by it.

    A field the new text no longer has loses its value in every connection of the kind, secrets included (EC-10); so
    does a field that changed its type, because what was stored for the old type means nothing for the new one.
    """
    loaded = loader.load_integration(text)
    if loaded.definition.short != row.short:
        raise load.CardInvalid([load.Problem("card_integration_short_changed", f"The short name of a saved connection cannot change (it is {row.short}).", "short", loaded.lines.get(("short",)), {"short": row.short})])
    dropped = dropped_fields(row, loaded)
    row.yaml_source = text
    row.definition = loaded.data
    now = utcnow()
    row.updated_at = max(now, row.updated_at + timedelta(microseconds=1)) if row.updated_at else now
    row.updated_by = user_id
    if dropped:
        forget_values(db, row.short, dropped)
    if commit:
        db.commit()
        _register(row)
    else:
        db.flush()
    return row


def dropped_fields(row: OwnIntegration, loaded: loader.LoadedIntegration) -> list[str]:
    """The fields whose stored values a new text throws away: gone from it, or of another type now (EC-10)."""
    before = {one["name"]: one["type"] for one in (row.definition or {}).get("fields", [])}
    after = {one.name: one.type for one in loaded.definition.fields}
    return [name for name, kind in before.items() if after.get(name) != kind]


def forget_values(db: Session, short: str, names: list[str]) -> int:
    """Take the stored values of fields out of every connection of the kind; the caller commits."""
    touched = 0
    for one in db.scalars(select(Integration).where(Integration.kind == kind_of(short))):
        config = dict(one.config or {})
        left = {name: value for name, value in config.items() if name not in names}
        if len(left) != len(config):
            one.config = left
            touched += 1
    return touched


def delete(db: Session, row: OwnIntegration) -> None:
    """The kind is gone at once; its connections stay in the database and say that the kind is missing (EC-6)."""
    short = row.short
    db.delete(row)
    db.commit()
    from ..adapters import unregister_custom

    unregister_custom(kind_of(short))


def register(row: OwnIntegration) -> None:
    """The kind of a saved row into the registry (after the commit that saved it)."""
    _register(row)


def _register(row: OwnIntegration) -> None:
    from ..adapters import register_custom
    from ..adapters.defined import DefinedAdapter

    register_custom(DefinedAdapter(loader.definition_from_data(row.definition), row.yaml_source))


def load_all(db: Session) -> int:
    """Every saved kind into the registry; the start, a restored backup and a test call this."""
    from ..adapters import forget_all_custom

    forget_all_custom()
    loaded = 0
    for row in listing(db):
        try:
            _register(row)
            loaded += 1
        except ValueError:
            # Written by a newer nexdeck and not readable by this one: it stays in the table and out of the way.
            continue
    return loaded
