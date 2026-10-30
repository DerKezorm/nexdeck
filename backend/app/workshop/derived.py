"""What a definition of the shop is, read from its own text (KARTEN-14 AC-5, AC-7, KARTEN-15 AC-3).

The catalog says what an entry reads, presses and needs, but the catalog is only a list: the text that is installed is
the file with the checksum. Whatever the shop shows as the class of an entry, its buttons, its requests and the kinds of
connection it needs is read from that text, and when the catalog says something else the text wins and the difference
is told.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..cards import exchange, load
from ..cards import integration as integration_loader
from . import catalog

#: The parts of an entry the shop shows, which the catalog also claims.
CLAIMS = ("class", "reads", "buttons", "requires")


@dataclass(frozen=True)
class Facts:
    type: str  # card | integration
    requires: list[str]
    class_: str
    reads: list[dict[str, str]]
    buttons: list[dict[str, Any]] = field(default_factory=list)
    #: The picture paths the card's text makes (templates): fetched with the connection's credentials like a read.
    pictures: list[dict[str, str]] = field(default_factory=list)


def picture_paths(data: dict[str, Any]) -> list[str]:
    """The picture paths a card's text makes (``template`` of ``item.image`` and of picture blocks), in the order written.

    ⚠️ Such a path is fetched by GET with the connection's credentials for whoever looks at the board, so the shop shows
    it like a read before installing and an update that brings a new one is confirmed (B2 of a review of 1.0.2).
    """
    found: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for one in node:
                visit(one)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key == "demo":
                    continue
                if key in ("image", "src") and isinstance(value, dict) and isinstance(value.get("template"), str):
                    if value["template"] not in found:
                        found.append(value["template"])
                else:
                    visit(value)

    visit(data)
    return found


def kind_of(text: str) -> str | None:
    """Whether the text is a card or an own connection, by its first line that says so."""
    return exchange.kind_of(text)


def read(text: str) -> Facts:
    """The facts of a definition, or ``load.CardInvalid`` when it cannot be read. This nexdeck being too old is not a fault here."""
    found = kind_of(text)
    if found == "card":
        loaded = load.load_definition(text, running_version="9999.0.0")
        definition = loaded.definition
        kinds = [str(kind) for kind in definition.requires]
        return Facts(
            "card", kinds, "buttons" if definition.buttons else "read",
            [{"kind": kinds[0], "path": request.path} for request in definition.requests] if kinds else [],
            [{"label": one.get("label"), "method": one.get("method"), "path": one.get("path")} for one in loaded.data.get("buttons", [])],
            [{"kind": kinds[0], "path": path} for path in picture_paths(loaded.data)] if kinds else [],
        )
    if found == "integration":
        piece = integration_loader.load_integration(text, saved=[]).definition
        return Facts("integration", [], "login" if piece.auth.type == "session" else "read", [{"kind": f"custom:{piece.short}", "path": one.path} for one in piece.reads])
    raise load.CardInvalid([load.Problem("import_unknown_document", "This is neither a card (nexdeck-card: 1) nor an own connection (nexdeck: integration).", "", 1)])


def of_text(text: str) -> Facts | None:
    """The facts of a definition, or ``None`` when the text cannot be read (the check of an installation says why)."""
    try:
        return read(text)
    except load.CardInvalid:
        return None


def _claimed(entry: catalog.Entry) -> dict[str, Any]:
    return {
        "class": entry.class_,
        "reads": sorted((one.kind, one.path) for one in entry.reads),
        "buttons": sorted((one.method.upper(), one.path) for one in entry.buttons),
        "requires": sorted(entry.requires),
    }


def _real(facts: Facts) -> dict[str, Any]:
    return {
        "class": facts.class_,
        "reads": sorted((one["kind"], one["path"]) for one in facts.reads),
        "buttons": sorted((str(one["method"] or "").upper(), str(one["path"] or "")) for one in facts.buttons),
        "requires": sorted(facts.requires),
    }


def differing(entry: catalog.Entry, facts: Facts) -> list[str]:
    """The parts the catalog claims differently from the definition, by name (``class``, ``reads``, ``buttons``, ``requires``)."""
    claimed, real = _claimed(entry), _real(facts)
    return [name for name in CLAIMS if claimed[name] != real[name]]


def wrong_type(entry: catalog.Entry, text: str) -> catalog.CatalogError | None:
    """The refusal for a definition that is not what the entry says it is (a card for an own connection or the other way round)."""
    found = kind_of(text)
    if found == entry.type:
        return None
    names = {"card": "a card", "integration": "an own connection"}
    return catalog.CatalogError(
        "type_mismatch", f"The catalog calls this entry {names[entry.type]}, but its file is {names.get(found or '', 'neither a card nor an own connection')}. It was not used.", 409,
    )
