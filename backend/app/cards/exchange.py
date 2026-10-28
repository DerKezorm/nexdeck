"""Giving cards and own connections to somebody else as a file, and taking such a file in (KARTEN-12).

A file is YAML with one or several documents, split by a line holding only ``---``. Each document is a card or an own
connection, **as it was saved**, comments and demo data included. Nothing else goes in: no connection, no secret (a
definition holds none) and nothing about the shop the card may have come from, so a card that comes in from a file is a
card of this installation.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import CardRecord
from . import integration_store as integrations

#: The ending of the file name of an export.
SUFFIX = ".nexdeck.yaml"
MEDIA_TYPE = "text/yaml; charset=utf-8"


def join(texts: list[str]) -> str:
    """The documents one after the other, each word for word, split by ``---``."""
    return "---\n".join(text if text.endswith("\n") else text + "\n" for text in texts)


def wanted_integrations(requires: list[str]) -> list[str]:
    """The short names of the own connections a list of kinds names, in order, each once."""
    found: list[str] = []
    for kind in requires:
        short = kind.partition(":")[2] if kind.startswith("custom:") else ""
        if short and short not in found:
            found.append(short)
    return found


def card_documents(db: Session, row: CardRecord) -> list[str]:
    """The card, and behind it every own connection it names that this installation has."""
    texts = [row.yaml_source]
    for short in wanted_integrations([str(kind) for kind in (row.definition or {}).get("requires", [])]):
        found = integrations.get(db, short)
        if found is not None:
            texts.append(found.yaml_source)
    return texts


def file_name(key: str) -> str:
    return f"{key}{SUFFIX}"

