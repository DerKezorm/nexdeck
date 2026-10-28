"""The custom cards and own connections that travel with a board file (KARTEN-12).

A board that shows custom cards is exported with two more lists, ``custom_cards`` and ``own_integrations``: the texts of
the definitions as they were saved, each as one block of text. A board without custom cards is exported as it always
was, byte for byte.
"""

from __future__ import annotations

from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cards import exchange
from ..cards import integration_store as integrations
from ..models import CardRecord, Widget


class _Block(str):
    """A definition, written into the file as a block of text so its lines and comments stay readable."""


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(_Block, lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:str", str(value), style="|"))


def dump(document: dict[str, Any]) -> str:
    return yaml.dump(document, Dumper=_Dumper, sort_keys=False, allow_unicode=True)


def cards_on(widgets: list[Widget]) -> list[str]:
    """The short names of the custom cards a list of cards shows, in order, each once."""
    found: list[str] = []
    for widget in widgets:
        slug = str((widget.options or {}).get("card") or "").strip() if widget.kind.startswith("custom.") else ""
        if slug and slug not in found:
            found.append(slug)
    return found


def attach(db: Session, document: dict[str, Any], slugs: list[str], connection_kinds: list[str]) -> bool:
    """Add the texts of the custom cards in ``slugs`` and the own connections they or the exported connections need.

    Returns whether anything was added. A card that is not here any more is left out: the board shows "definition
    missing" for it wherever it stands.
    """
    rows = {row.slug: row for row in db.scalars(select(CardRecord).where(CardRecord.slug.in_(slugs or [""]), CardRecord.kind == "card"))}
    cards = [rows[slug] for slug in slugs if slug in rows]
    if not cards:
        return False
    wanted = exchange.wanted_integrations([str(kind) for row in cards for kind in (row.definition or {}).get("requires", [])] + connection_kinds)
    kept = [row for row in (integrations.get(db, short) for short in wanted) if row is not None]
    document["custom_cards"] = [_Block(row.yaml_source) for row in cards]
    if kept:
        document["own_integrations"] = [_Block(row.yaml_source) for row in kept]
    return True
