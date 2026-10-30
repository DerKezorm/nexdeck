"""An entry of the catalog as the shop shows it: the entry itself and what this installation adds to it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import get_adapter
from ..cards import load
from ..models import Integration
from . import catalog, derived, installed

BASE = "/api/v1/workshop"


@dataclass
class Context:
    """What the views of one request share: the connections of this installation, by kind."""

    connections: dict[str, list[dict[str, Any]]]
    #: What this installation has from the shop, by entry.
    from_shop: dict[str, list[installed.Installed]]


def context(db: Session) -> Context:
    found: dict[str, list[dict[str, Any]]] = {}
    for one in db.scalars(select(Integration).order_by(Integration.name)):
        try:
            if not get_adapter(one.kind).raw_access:
                continue
        except KeyError:
            continue
        found.setdefault(one.kind, []).append({"id": one.id, "name": one.name, "kind": one.kind})
    return Context(found, installed.listing(db))


def requirement(kind: str) -> dict[str, str]:
    from ..routers.cards import _requirement

    return _requirement(kind)


def picture_version(entry: catalog.Entry) -> str:
    """Changes when the pictures of the entry can: its version, else the time it was updated, else its checksum. The address of a picture carries it."""
    return (entry.version or entry.updated_at or entry.sha256)[:64]


def entry_view(entry: catalog.Entry, ctx: Context, facts: derived.Facts | None = None, *, unreadable: bool = False) -> dict[str, Any]:
    """The entry with its pictures, what it needs, the connections that fit and whether this nexdeck can run it.

    With the ``facts`` of its checked definition the class, the requests, the buttons and the kinds it needs are those of
    the definition, and ``claims_differ`` names what the catalog said otherwise. Without them (the list, which does not
    fetch every file) they are the catalog's words and ``verified`` is false; a definition that could not be read
    (``unreadable``) shows no class, no requests and no buttons.
    """
    requires = facts.requires if facts is not None else entry.requires
    connections = [one for kind in requires for one in ctx.connections.get(kind, [])]
    base = f"{BASE}/entries/{entry.id}/image"
    have = ctx.from_shop.get(entry.id, [])
    if facts is not None:
        shown: dict[str, Any] = {"class": facts.class_, "reads": facts.reads, "buttons": facts.buttons, "pictures": facts.pictures}
    elif unreadable:
        shown = {"class": "unknown", "reads": [], "buttons": [], "pictures": []}
    else:
        # The catalog names no pictures: the list shows none, the detail and the check before installing read them from the file.
        shown = {"class": entry.class_, "reads": [one.model_dump() for one in entry.reads], "buttons": [one.model_dump() for one in entry.buttons], "pictures": []}
    return {
        "id": entry.id,
        "author_id": entry.author_id,
        "slug": entry.slug,
        "type": entry.type,
        "name": entry.name,
        "description": entry.description,
        "author": entry.author.model_dump(),
        "version": entry.version,
        "min_nexdeck": entry.min_nexdeck,
        "category": entry.category,
        "requires": [requirement(kind) for kind in requires],
        **shown,
        "verified": facts is not None,
        "claims_differ": derived.differing(entry, facts) if facts is not None else [],
        "thumbs": entry.thumbs,
        "discussion": entry.discussion,
        "based_on": entry.based_on,
        "updated_at": entry.updated_at,
        "license": entry.license or "MIT",
        "removed": entry.removed.model_dump() if entry.removed else None,
        "starter": entry.starter,
        "needs_newer": load.needs_newer(entry.min_nexdeck),
        # An own connection and a skin have nothing to read through, so they are always something to install.
        "fits": entry.type in ("integration", "skin") or bool(connections),
        "connections": connections,
        "installed": None if not have else {
            "slug": have[0].slug, "version": have[0].version, "update": installed.update_available(entry, have[0]),
            "locally_changed": have[0].locally_changed,
        },
        "images": {"light": f"{base}/light", "dark": f"{base}/dark"},
        "picture_version": picture_version(entry),
    }
