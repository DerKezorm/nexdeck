"""What this installation has from the shop: the cards and own connections that carry a ``shop_ref``."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CardRecord, OwnIntegration
from . import catalog


def normalised_hash(text: str) -> str:
    """The checksum of a text with its line ends and its last blank lines left out: a file saved on Windows is the same file."""
    return hashlib.sha256(text.replace("\r\n", "\n").rstrip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Installed:
    """One card or own connection that came from an entry of the shop."""

    type: str  # card | integration
    slug: str  # the short name here
    ref: str  # the entry it came from
    version: str
    text: str
    hash: str

    @property
    def locally_changed(self) -> bool:
        """The stored text is not the text that was installed (KARTEN-15 EC-2). Unknown when nothing was written down."""
        return bool(self.hash) and normalised_hash(self.text) != self.hash


def listing(db: Session) -> dict[str, list[Installed]]:
    """By entry, in the order they were made (a copy of the same entry is a second one)."""
    found: dict[str, list[Installed]] = {}
    for row in db.scalars(select(CardRecord).where(CardRecord.kind == "card", CardRecord.origin == "shop", CardRecord.shop_ref != "").order_by(CardRecord.id)):
        found.setdefault(row.shop_ref, []).append(Installed("card", row.slug, row.shop_ref, row.shop_version, row.yaml_source, row.shop_hash))
    for piece in db.scalars(select(OwnIntegration).where(OwnIntegration.shop_ref != "").order_by(OwnIntegration.id)):
        found.setdefault(piece.shop_ref, []).append(Installed("integration", piece.short, piece.shop_ref, piece.shop_version, piece.yaml_source, piece.shop_hash))
    return found


def _numbers(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def newer(new: str, old: str) -> bool:
    """Whether a version is later than another, compared by their numbers with the shorter one padded with zeros."""
    a, b = _numbers(new), _numbers(old)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def update_available(entry: catalog.Entry, one: Installed) -> bool:
    """A newer version of a card is in the catalog and the entry is not taken out of the shop (KARTEN-15 AC-1)."""
    return one.type == "card" and entry.removed is None and newer(entry.version, one.version)
