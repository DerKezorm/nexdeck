"""Ready-made boards to start from.

A template lives in ``app/templates/`` as YAML: a name, a description and the
connections it wants as **slots**, then pages of cards. A slot names the
kinds that can fill it, "Jellyfin, Plex or Emby", because those adapters give
their cards the same names; a card in a slot says which of those cards it is
(``widget: nowplaying``), not whose. Installing a template maps each slot to
one of this installation's connections, or to none, and hands the result to
the ordinary import with the rights of whoever asked.

A slot left empty takes its cards with it, and only the holes they leave
close: the rest of the page stays as the template laid it out.

Card titles, page names and the template's own texts are English here; the
browser sends the words in its own language along when it installs, the same
way a card from the library gets its title.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import get_adapter, split_widget_kind
from ..models import Board, Integration, Role, User
from . import grid
from .boards import ImportError_, import_board

DIRECTORY = Path(__file__).resolve().parent.parent / "templates"


class TemplateError(ValueError):
    pass


@lru_cache(maxsize=1)
def _all() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(DIRECTORY.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        found[str(document["template"]["id"])] = document
    return dict(sorted(found.items(), key=lambda item: item[1]["template"].get("order", 99)))


def get(template_id: str) -> dict[str, Any]:
    try:
        return _all()[template_id]
    except KeyError as missing:
        raise TemplateError("There is no such template.") from missing


def _cards(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [card for page in document.get("pages") or [] for card in page.get("cards") or []]


def words(document: dict[str, Any]) -> list[str]:
    """Every English text of a template that the browser translates."""
    meta = document["template"]
    found = [meta["name"], meta.get("description", "")]
    found += [slot["name"] for slot in meta.get("slots") or []]
    for page in document.get("pages") or []:
        found.append(page["name"])
        found += [card["title"] for card in page.get("cards") or []]
    return list(dict.fromkeys(text for text in found if text))


def summary(document: dict[str, Any]) -> dict[str, Any]:
    """What a tile shows: the texts, the slots with their kinds, and a
    sketch of the first page to draw the thumbnail from."""
    meta = document["template"]
    first = (document.get("pages") or [{}])[0]
    return {
        "id": meta["id"],
        "name": meta["name"],
        "description": meta.get("description", ""),
        "icon": meta.get("icon", "layout-dashboard"),
        "columns": grid.columns(meta.get("settings")),
        "pages": len(document.get("pages") or []),
        "cards": len(_cards(document)),
        "slots": [
            {
                "name": slot["name"],
                "kinds": [{"kind": kind, "label": get_adapter(kind).label, "icon": get_adapter(kind).icon} for kind in slot["kinds"]],
                "cards": sum(1 for card in _cards(document) if card.get("slot") == slot["name"]),
            }
            for slot in meta.get("slots") or []
        ],
        "sketch": [{"slot": card.get("slot"), "at": card["at"]} for card in first.get("cards") or []],
        "words": words(document),
    }


def choices(db: Session, document: dict[str, Any], user: User) -> dict[str, list[dict[str, Any]]]:
    """The connections each slot may be filled with, for this person.

    A connection reserved for administrators is offered to administrators
    only, the same rule as everywhere a card is built.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for slot in document["template"].get("slots") or []:
        rows = db.scalars(select(Integration).where(Integration.kind.in_(slot["kinds"])).order_by(Integration.name))
        result[slot["name"]] = [
            {"id": row.id, "name": row.name, "kind": row.kind, "demo": row.demo}
            for row in rows if not row.admin_only or user.role == Role.admin.value
        ]
    return result


def install(db: Session, template_id: str, *, user: User, name: str | None, slots: dict[str, int | None], texts: dict[str, str]) -> Board:
    """A board made from a template, its slots filled with real connections."""
    document = copy.deepcopy(get(template_id))
    meta = document["template"]
    known = {slot["name"]: slot for slot in meta.get("slots") or []}
    stray = set(slots) - set(known)
    if stray:
        raise TemplateError(f"The template has no slot called {sorted(stray)[0]!r}.")
    filled: dict[str, Integration] = {}
    for slot_name, integration_id in slots.items():
        if integration_id is None:
            continue
        integration = db.get(Integration, int(integration_id))
        if integration is None or integration.kind not in known[slot_name]["kinds"]:
            labels = ", ".join(get_adapter(kind).label for kind in known[slot_name]["kinds"])
            raise TemplateError(f"{slot_name} takes a connection of {labels}.")
        # A connection reserved for administrators is refused by the import
        # below, with the same words as everywhere else.
        filled[slot_name] = integration
    # ⚠️ The import finds a card's connection by its name. Two connections of
    # one name in two slots would put every card on whichever came last.
    names = [integration.name for integration in {i.id: i for i in filled.values()}.values()]
    if len(names) != len(set(names)):
        raise TemplateError("Two of the chosen connections have the same name. Rename one first.")

    say = lambda text: str(texts.get(text) or text)[:120]  # noqa: E731
    pages = []
    for page in document.get("pages") or []:
        kept: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for number, card in enumerate(page.get("cards") or []):
            slot = card.get("slot")
            if slot and slot not in filled:
                continue
            kind = f"{filled[slot].kind}.{card['widget']}" if slot else card["kind"]
            x, y, w, h = card["at"]
            entry = {
                "kind": kind,
                "title": say(card["title"]),
                "integration": filled[slot].name if slot else None,
                "options": dict(card.get("options") or {}),
            }
            kept.append((entry, {"i": str(number), "x": x, "y": y, "w": w, "h": h}))
        # Only the holes of the cards left out close; the rest stands as laid out.
        spots = {spot["i"]: spot for spot in grid.close_gaps([spot for _entry, spot in kept])}
        widgets = []
        for entry, spot in kept:
            placed = spots[spot["i"]]
            widgets.append({**entry, "layout": {"lg": {key: placed[key] for key in ("x", "y", "w", "h")}}})
        pages.append({"name": say(page["name"]), "widgets": widgets})

    board_doc = {
        "nexdeck": 1,
        "board": {"name": (name or "").strip() or say(meta["name"]), "icon": meta.get("icon", "layout-dashboard"), "settings": dict(meta.get("settings") or {})},
        "integrations": [{"name": integration.name, "kind": integration.kind} for integration in filled.values()],
        "pages": pages,
    }
    text = yaml.safe_dump(board_doc, sort_keys=False, allow_unicode=True)
    try:
        return import_board(db, text, owner_id=user.id, trusted=False, allow_locked=user.role == Role.admin.value)
    except ImportError_ as failure:
        raise TemplateError(str(failure)) from failure


def kinds_used(document: dict[str, Any]) -> list[str]:
    """Every widget kind a template can end up with, for the guards."""
    meta = document["template"]
    slots = {slot["name"]: slot["kinds"] for slot in meta.get("slots") or []}
    result = []
    for card in _cards(document):
        if card.get("slot"):
            result += [f"{kind}.{card['widget']}" for kind in slots[card["slot"]]]
        else:
            result.append(card["kind"])
    return result


def check(kind: str) -> None:
    """Raises KeyError for a widget kind that does not exist."""
    adapter, widget_kind = split_widget_kind(kind)
    adapter.widget(widget_kind)
