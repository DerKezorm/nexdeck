"""Cards and own connections for the tests of KARTEN-12 (export and import)."""

from __future__ import annotations

from .cards_sample import VALUE_CARD, changed
from .karten3_sample import HEADER

#: The own connection of the sample card; its text is the shipped example, comments and all.
INTEGRATION = HEADER
SHORT = "bookstack-own"

#: A card that reads through that own connection.
CARD = changed("requires: [sonarr, radarr]   # either one", f"requires: [custom:{SHORT}]")
#: A card that needs no own connection.
PLAIN = VALUE_CARD


def card(slug: str, text: str = CARD) -> str:
    return changed("slug: queue-size", f"slug: {slug}", text)


def separated(*texts: str) -> str:
    """The documents of a file."""
    return "---\n".join(text if text.endswith("\n") else text + "\n" for text in texts)
