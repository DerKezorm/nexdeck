"""Installing an entry of the shop (KARTEN-14 AC-7, AC-8, AC-9, EC-1 to EC-4).

Installing is a checked import (KARTEN-12): the definition is fetched, its checksum compared with the catalog, and the
text goes through the same reading and the same choice for a name that is taken as a file a person imports. What is made is
marked with where it came from, so that the shop can offer updates (KARTEN-15). Every document or none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cards import exchange, load
from ..cards import integration_store as integrations
from ..models import CardRecord
from . import catalog, files, state
from .installed import normalised_hash

SOURCE = "the Card shop"


def gate(entry: catalog.Entry) -> None:
    """An entry that was taken out of the shop or needs a newer nexdeck is not installed (EC-2)."""
    if entry.removed is not None:
        raise catalog.CatalogError("entry_removed", "This entry was removed from the Card shop.", 409)
    if load.needs_newer(entry.min_nexdeck):
        raise catalog.CatalogError("needs_newer_nexdeck", f"This needs nexdeck {entry.min_nexdeck} or newer.", 409, min_nexdeck=entry.min_nexdeck)


def offers(db: Session, found: catalog.Catalog, entry: catalog.Entry) -> tuple[list[catalog.Entry], list[str]]:
    """The own connections a card needs that are not here: those the catalog has to offer, and those it has not (AC-8).

    Several kinds in ``requires`` mean any one of them, so a card that can read through a kind that is here misses nothing.
    """
    if entry.type != "card" or any(not kind.startswith("custom:") for kind in entry.requires):
        return [], []
    here = set(integrations.shorts(db))
    wanted = [kind.partition(":")[2] for kind in entry.requires]
    unmet = [short for short in wanted if short not in here]
    if len(unmet) < len(wanted):
        return [], []
    offered: list[catalog.Entry] = []
    missing: list[str] = []
    for short in dict.fromkeys(unmet):
        candidates = [
            one for one in found.entries
            if one.type == "integration" and one.slug == short and one.removed is None and not load.needs_newer(one.min_nexdeck)
        ]
        # The author of the card first, then the one with the most thumbs.
        candidates.sort(key=lambda one: (one.author_id != entry.author_id, -one.thumbs))
        if candidates:
            offered.append(candidates[0])
        else:
            missing.append(f"custom:{short}")
    return offered, missing


@dataclass
class Plan:
    """What an installation would make: the entry, the texts (the card first), and the own connections on offer."""

    entry: catalog.Entry
    text: str
    offered: list[catalog.Entry]
    missing: list[str]
    #: The definition of each offered connection, by entry id.
    offered_texts: dict[str, str] = field(default_factory=dict)


async def prepare(db: Session, repo: str, found: catalog.Catalog, entry: catalog.Entry) -> Plan:
    gate(entry)
    text = await files.definition(repo, entry)
    offered, missing = offers(db, found, entry)
    texts = {one.id: await files.definition(repo, one) for one in offered}
    return Plan(entry, text, offered, missing, texts)


def documents(plan: Plan, with_integrations: list[str]) -> list[tuple[int, str]]:
    """The card, then the own connections the person accepted, as the documents of a file."""
    return [(0, plan.text), *((0, plan.offered_texts[one.id]) for one in plan.offered if one.id in with_integrations)]


def inspect(db: Session, plan: Plan, with_integrations: list[str]) -> exchange.Inspection:
    return exchange.inspect_parts(db, documents(plan, with_integrations))


def install(db: Session, plan: Plan, choices: dict[str, str], with_integrations: list[str], *, user_id: int) -> dict[str, Any]:
    """Make what the plan says, without committing. Raises ``exchange.Refused`` or ``catalog.CatalogError``."""
    offered_ids = {one.id for one in plan.offered}
    unknown = [one for one in with_integrations if one not in offered_ids]
    if unknown:
        raise exchange.Refused("bad_integration_choice", f"{unknown[0]} is not offered with this entry.", 400, key=unknown[0])
    outcome, items = exchange.run_parts(db, documents(plan, with_integrations), choices, user_id=user_id, source=SOURCE)
    made: dict[str, str] = {}
    entries = [plan.entry, *(one for one in plan.offered if one.id in with_integrations)]
    for item, entry in zip(items, entries, strict=True):
        if item.id in outcome.skipped:
            continue
        key = outcome.copies.get(item.id) or item.key or ""
        made[entry.id] = key
        if item.type == "card":
            row = db.scalar(select(CardRecord).where(CardRecord.slug == key, CardRecord.kind == "card"))
            assert row is not None
            row.origin, row.shop_ref, row.shop_version, row.shop_hash = "shop", entry.id, entry.version, normalised_hash(row.yaml_source)
        else:
            piece = integrations.get(db, key)
            assert piece is not None
            piece.shop_ref, piece.shop_version, piece.shop_hash = entry.id, entry.version, normalised_hash(piece.yaml_source)
    return {"outcome": outcome, "made": made}


def acknowledge(db: Session, user_id: int, accepted: bool) -> None:
    """The first installation of an administrator needs his word that cards from the shop come from strangers (AC-9)."""
    if state.risk_acknowledged(db, user_id):
        return
    if not accepted:
        raise catalog.CatalogError(
            "risk_not_acknowledged",
            "Cards from the Card shop are written by strangers and run at your own risk. Confirm that you have read this to install one.",
            409,
        )
    state.acknowledge_risk(db, user_id)
