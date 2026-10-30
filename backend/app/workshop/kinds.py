"""The kinds of entry the shop knows, in one place: their names in the form of the Workshop and in its catalog.

⚠️ Read back from an issue by its word, never by how the word begins: ``startswith("conn")`` took everything else for
a card, and a skin came back from the Workshop as one.
"""

from __future__ import annotations

#: The kinds, by the word the catalog and nexdeck use, with the word the form of the Workshop shows.
TYPES = {"card": "Card", "integration": "Connection", "skin": "Skin"}


def from_form(word: str) -> str | None:
    """The kind an issue of the Workshop names in its field Type, or ``None`` for a word it does not know."""
    wanted = word.strip().lower()
    return next((kind for kind, label in TYPES.items() if label.lower() == wanted), None)
