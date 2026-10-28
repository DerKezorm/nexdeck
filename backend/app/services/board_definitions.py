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

from ..cards import exchange, load, store
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


# -- reading them from a board file ---------------------------------------------------------------


def _document(text: str) -> dict[str, Any]:
    """The board file as a mapping, with the objections ``import_board`` makes first, in the same words."""
    from .boards import ImportError_

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ImportError_(f"The file is not valid YAML: {error}") from error
    if not isinstance(document, dict) or "board" not in document:
        raise ImportError_("The file has no 'board' section.")
    return document


def parts_of(document: dict[str, Any]) -> list[tuple[int, str]]:
    """The texts of the definitions a board file carries, cards first; each text is its own file (lines count from its first)."""
    from .boards import ImportError_

    texts: list[str] = []
    for key in ("custom_cards", "own_integrations"):
        listed = document.get(key)
        if listed is None:
            continue
        if not isinstance(listed, list) or not all(isinstance(one, str) for one in listed):
            raise ImportError_(f"'{key}' has to be a list of texts, one for each definition.")
        texts += [one if one.endswith("\n") else one + "\n" for one in listed if one.strip()]
    if len(texts) > store.MAX_CARDS + integrations.MAX_INTEGRATIONS:
        raise ImportError_(f"This file carries {len(texts)} definitions, more than an installation keeps.")
    return [(0, text) for text in texts]


def _status(item: exchange.Item, admin: bool) -> str:
    if item.problems:
        return "invalid"
    if not admin:
        return "unknown"  # what exists here is not for somebody who cannot manage it
    return "same" if item.same else ("different" if item.exists else "missing")


def check(db: Session, text: str, *, admin: bool) -> dict[str, Any]:
    """What the definitions of a board file are here: missing, the same, or different (a different one is kept as it is)."""
    parts = parts_of(_document(text))
    seen = exchange.inspect_parts(db, parts) if parts else exchange.Inspection([], [])
    return {
        "can_create": admin,
        "definitions": [
            {k: v for k, v in item.view().items() if k in ("type", "id", "slug", "short", "name", "requires", "problems")} | {"status": _status(item, admin)}
            for item in seen.items
        ],
        "missing_integrations": seen.missing if admin else [],
    }


def apply(db: Session, text: str, *, user_id: int | None, replace_different: bool = False, source: str = "") -> tuple[exchange.Outcome, dict[str, list[str]]]:
    """Make the definitions of a board file that are not here yet, in the session and without committing.

    A definition here with the same short name and another text stays as it is (``kept``), unless ``replace_different``:
    a file the operator put on the server wins (``replaced``). Anything wrong in any definition refuses the whole file.
    """
    from .boards import ImportError_

    parts = parts_of(_document(text))
    report: dict[str, list[str]] = {"created": [], "replaced": [], "same": [], "kept": []}
    if not parts:
        return exchange.Outcome(), report
    seen = exchange.inspect_parts(db, parts)
    if not seen.ok:
        item = next(one for one in seen.items if one.problems)
        problem = item.problems[0]
        label = f"{item.type} {item.key}" if item.key else f"{item.type} document"
        raise ImportError_(f"The {label} in this file cannot be made: {problem.message}")
    actions: dict[str, str] = {}
    for item in seen.items:
        if not item.exists:
            actions[item.id] = "create"
            report["created"].append(item.id)
        elif item.same:
            actions[item.id] = "skip"
            report["same"].append(item.id)
        elif replace_different:
            actions[item.id] = "replace"
            report["replaced"].append(item.id)
        else:
            actions[item.id] = "skip"
            report["kept"].append(item.id)
    try:
        outcome = exchange.make(db, seen.items, actions, user_id=user_id, source=source)
    except exchange.Refused as refused:
        raise ImportError_(refused.message) from refused
    # ⚠️ The board that is imported next, in this same transaction, names connections of these kinds, and the import
    # looks them up in the registry. Whoever calls this puts the registry back from the table when the transaction fails.
    for short in [*outcome.integrations_added, *outcome.integrations_replaced]:
        row = integrations.get(db, short)
        if row is not None:
            integrations.register(row)
    return outcome, report


def skipped(text: str) -> list[str]:
    """The definitions a file carries, by ``card:<slug>`` and ``integration:<short>``, for an import that makes none."""
    try:
        parts = parts_of(_document(text))
    except Exception:  # noqa: BLE001 - the import itself says what is wrong with the file
        return []
    found: list[str] = []
    for _offset, part in parts:
        try:
            data, _lines = load.parse(part, 200_000)
        except load.CardInvalid:
            continue
        key = data.get("slug") if "nexdeck-card" in data else data.get("short")
        if key:
            found.append(f"{'card' if 'nexdeck-card' in data else 'integration'}:{key}")
    return found
