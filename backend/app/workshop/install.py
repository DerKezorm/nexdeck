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
from . import catalog, derived, files, state
from .installed import normalised_hash

SOURCE = "the Card shop"


def gate(entry: catalog.Entry) -> None:
    """An entry that was taken out of the shop or needs a newer nexdeck is not installed (EC-2)."""
    if entry.removed is not None:
        raise catalog.CatalogError("entry_removed", "This entry was removed from the Card shop.", 409)
    if load.needs_newer(entry.min_nexdeck):
        raise catalog.CatalogError("needs_newer_nexdeck", f"This needs nexdeck {entry.min_nexdeck} or newer.", 409, min_nexdeck=entry.min_nexdeck)


def offers(db: Session, found: catalog.Catalog, entry: catalog.Entry, requires: list[str]) -> tuple[list[catalog.Entry], list[str]]:
    """The own connections a card needs (``requires`` of its checked definition) that are not here: those the catalog has to offer, and those it has not (AC-8).

    Several kinds in ``requires`` mean any one of them, so a card that can read through a kind that is here misses nothing.
    """
    if entry.type != "card" or any(not kind.startswith("custom:") for kind in requires):
        return [], []
    here = set(integrations.shorts(db))
    wanted = [kind.partition(":")[2] for kind in requires]
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


def free_short(db: Session, entry: catalog.Entry) -> str:
    """A short name for a draft that starts from an example: the entry's own when it is free, else with -2, -3, … (KARTEN-19 AC-4).

    Free means no card, board or own connection here has it and, for a connection, no built-in kind is called so.
    """
    from ..adapters import get_adapter

    def taken(short: str) -> bool:
        if entry.type == "card":
            return db.scalar(select(CardRecord.id).where(CardRecord.slug == short)) is not None
        if short in integrations.shorts(db):
            return True
        try:
            get_adapter(short)
        except KeyError:
            return False
        return True

    for number in range(1, 1000):
        suffix = "" if number == 1 else f"-{number}"
        short = entry.slug[: 60 - len(suffix)] + suffix
        if not taken(short):
            return short
    return entry.slug


@dataclass
class Plan:
    """What an installation would make: the entry, the texts (the card first), and the own connections on offer."""

    entry: catalog.Entry
    text: str
    #: What the definition of the entry says it is, or ``None`` when it cannot be read.
    facts: derived.Facts | None
    offered: list[catalog.Entry]
    missing: list[str]
    #: The definition of each offered connection, by entry id.
    offered_texts: dict[str, str] = field(default_factory=dict)
    #: The same for each offered connection.
    offered_facts: dict[str, derived.Facts | None] = field(default_factory=dict)


async def prepare(db: Session, repo: str, found: catalog.Catalog, entry: catalog.Entry) -> Plan:
    gate(entry)
    text = await files.definition(repo, entry)
    facts = derived.of_text(text)
    offered, missing = offers(db, found, entry, facts.requires if facts else [])
    texts = {one.id: await files.definition(repo, one) for one in offered}
    return Plan(entry, text, facts, offered, missing, texts, {one.id: derived.of_text(texts[one.id]) for one in offered})


def documents(plan: Plan, with_integrations: list[str]) -> list[tuple[int, str]]:
    """The card, then the own connections the person accepted, as the documents of a file."""
    return [(0, plan.text), *((0, plan.offered_texts[one.id]) for one in plan.offered if one.id in with_integrations)]


def inspect(db: Session, plan: Plan, with_integrations: list[str]) -> exchange.Inspection:
    return exchange.inspect_parts(db, documents(plan, with_integrations))


def drops(db: Session, plan: Plan, choices: dict[str, str], with_integrations: list[str]) -> list[dict[str, Any]]:
    """The own connections that replacing would change so that stored values are thrown away, with the fields (EC-10 of KARTEN-12)."""
    seen = inspect(db, plan, with_integrations)
    return [
        {"id": item.id, "fields": item.dropped}
        for item in seen.items if item.type == "integration" and item.dropped and item.exists and choices.get(item.id) == "replace"
    ]


def confirm_drops(db: Session, plan: Plan, choices: dict[str, str], with_integrations: list[str], confirmed: bool) -> None:
    """Replacing an own connection that loses fields needs a word of the administrator: the values go, secrets too."""
    found = drops(db, plan, choices, with_integrations)
    if found and not confirmed:
        raise catalog.CatalogError(
            "dropped_not_confirmed",
            "Replacing this connection throws away what is stored in its fields, secrets included. Confirm that to go on.", 409, documents=found,
        )


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
