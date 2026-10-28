"""Giving cards and own connections to somebody else as a file, and taking such a file in (KARTEN-12).

A file is YAML with one or several documents, split by a line holding only ``---``. Each document is a card or an own
connection, **as it was saved**, comments and demo data included. Nothing else goes in: no connection, no secret (a
definition holds none) and nothing about the shop the card may have come from, so a card that comes in from a file is a
card of this installation.

Taking a file in is two steps that read the file the same way: :func:`inspect` says what is in it and what is wrong with
it (the problems with their line in the **file**), :func:`run` makes it, every document or none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CardRecord
from ..services import chronicle
from . import integration as integration_loader
from . import integration_store as integrations
from . import load, store

#: The ending of the file name of an export.
SUFFIX = ".nexdeck.yaml"
MEDIA_TYPE = "text/yaml; charset=utf-8"
#: What one import may be: the size of the file in bytes and the number of documents in it (EC-1).
MAX_BYTES = 512 * 1024
MAX_DOCUMENTS = 20

#: What a person may answer to a name that is taken already.
CHOICES = ("replace", "copy", "skip")


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


# -- reading a file ------------------------------------------------------------------------


class Refused(Exception):
    """The whole file is refused, with a reason a person can act on. ``status`` is the HTTP status it becomes."""

    def __init__(self, code: str, message: str, status: int = 400, **more: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.more = code, message, status, more


_SEPARATOR = re.compile(r"^---[ \t\r]*$")
_CARD = re.compile(r"^nexdeck-card[ \t]*:", re.MULTILINE)
_INTEGRATION = re.compile(r"^nexdeck[ \t]*:[ \t]*[\"']?integration[\"']?[ \t]*(#.*)?$", re.MULTILINE)
_SLUG_LINE = re.compile(r"^(\s*slug\s*:\s*)([\"']?)[^\s#\"']+\2")
_SHORT_LINE = re.compile(r"^(\s*short\s*:\s*)([\"']?)[^\s#\"']+\2")


def split(text: str) -> list[tuple[int, str]]:
    """The documents of a file with the number of lines in front of each (so line 1 of a document is line ``offset + 1``).

    Documents with nothing but blank lines and comments are dropped: a file that starts with ``---`` has an empty one.
    """
    size = len(text.encode("utf-8"))
    if size > MAX_BYTES:
        raise Refused("import_too_large", f"The file is larger than {MAX_BYTES // 1024} KB, which is the most an import takes.", size=size, limit=MAX_BYTES)
    found: list[tuple[int, str]] = []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    start = 0

    def close(end: int) -> None:
        chunk = lines[start:end]
        if any(line.strip() and not line.strip().startswith("#") for line in chunk):
            found.append((start, "".join(f"{line}\n" for line in chunk)))

    for index, line in enumerate(lines):
        if _SEPARATOR.match(line):
            close(index)
            start = index + 1
    close(len(lines))
    if len(found) > MAX_DOCUMENTS:
        raise Refused("import_too_many", f"The file has {len(found)} documents; an import takes at most {MAX_DOCUMENTS}.", count=len(found), limit=MAX_DOCUMENTS)
    if not found:
        raise Refused("import_empty", "The file has no card and no own connection in it.")
    return found


@dataclass
class Item:
    """One document of a file, read."""

    type: str  # card | integration | unknown
    text: str
    #: The line of the file the document begins at.
    line: int
    key: str | None = None
    name: Any = None
    requires: list[str] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)
    form: str = ""
    problems: list[load.Problem] = field(default_factory=list)
    loaded: Any = None
    exists: bool = False
    same: bool = False
    #: An own connection here with another text: the fields whose stored values replacing it throws away, secrets too.
    dropped: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        """What the choices name: ``card:<slug>`` or ``integration:<short>``."""
        return f"{self.type}:{self.key}"

    def view(self) -> dict[str, Any]:
        found = {
            "type": self.type, "id": self.id, "name": self.name, "requires": self.requires, "buttons": self.buttons, "form": self.form,
            "problems": [problem.as_dict() for problem in self.problems], "exists": self.exists, "same": self.same, "line": self.line,
        }
        found["slug" if self.type == "card" else "short"] = self.key
        if self.type == "integration":
            found["dropped_fields"] = self.dropped
        return found


@dataclass
class Inspection:
    items: list[Item]
    #: The own connections the cards need that are neither in the file nor here (``custom:<short>``).
    missing: list[str]

    @property
    def ok(self) -> bool:
        return all(not item.problems for item in self.items)

    def view(self) -> dict[str, Any]:
        return {"ok": self.ok, "documents": [item.view() for item in self.items], "missing_integrations": self.missing}


def _in_file(problem: load.Problem, offset: int) -> load.Problem:
    return replace(problem, line=problem.line + offset if problem.line is not None else None)


def _same(a: str, b: str) -> bool:
    return a.replace("\r\n", "\n").rstrip() == b.replace("\r\n", "\n").rstrip()


def _read(db: Session, offset: int, text: str) -> Item:
    item = Item("unknown", text, offset + 1)
    if _CARD.search(text):
        item.type = "card"
    elif _INTEGRATION.search(text):
        item.type = "integration"
    else:
        item.problems.append(load.Problem(
            "import_unknown_document", "This is neither a card (nexdeck-card: 1) nor an own connection (nexdeck: integration).", "", offset + 1,
        ))
        return item
    try:
        if item.type == "card":
            item.loaded = load.load_definition(text)
            definition = item.loaded.definition
            item.key, item.name, item.form = definition.slug, item.loaded.data.get("name"), definition.form
            item.requires = [str(kind) for kind in definition.requires]
            item.buttons = [{"label": one.get("label"), "method": one.get("method"), "path": one.get("path")} for one in item.loaded.data.get("buttons", [])]
            if item.key in store.RESERVED_SLUGS:
                raise load.CardInvalid([load.Problem(
                    "card_slug_reserved", f"The short name {item.key} is kept for nexdeck itself.", "slug", item.loaded.lines.get(("slug",)), {"slug": item.key},
                )])
            row: Any = db.scalar(select(CardRecord).where(CardRecord.slug == item.key, CardRecord.kind == "card"))
        else:
            item.loaded = integration_loader.load_integration(text, saved=integrations.shorts(db))
            item.key, item.name = item.loaded.definition.short, item.loaded.data.get("name")
            row = integrations.get(db, item.key)
    except load.CardInvalid as failure:
        item.problems = [_in_file(problem, offset) for problem in failure.problems]
        item.loaded = None
        try:
            # The short name, as far as the text says it, so a person sees which document it is.
            data, _ = load.parse(text, 200_000)
            item.key = str(data.get("slug" if item.type == "card" else "short") or "") or None
            item.name = data.get("name")
        except load.CardInvalid:
            pass
        return item
    item.exists = row is not None
    item.same = row is not None and _same(row.yaml_source, text)
    if item.type == "integration" and item.exists and not item.same:
        item.dropped = integrations.dropped_fields(row, item.loaded)
    return item


def inspect(db: Session, text: str) -> Inspection:
    """Every document read and checked, with what exists here already; nothing is written."""
    return inspect_parts(db, split(text))


def inspect_parts(db: Session, parts: list[tuple[int, str]]) -> Inspection:
    """The same for documents that are already apart, each with the number of lines in front of it."""
    items = [_read(db, offset, chunk) for offset, chunk in parts]
    seen: set[str] = set()
    for item in items:
        if item.key is None or item.problems:
            continue
        if item.id in seen:
            place = "slug" if item.type == "card" else "short"
            item.problems.append(_in_file(load.Problem("import_twice", f"The file has {item.key} twice.", place, item.loaded.lines.get((place,))), item.line - 1))
        seen.add(item.id)
    in_file = {item.key for item in items if item.type == "integration" and item.key and not item.problems}
    here = {row.short for row in integrations.listing(db)}
    missing: list[str] = []
    for item in items:
        if item.type != "card" or item.problems:
            continue
        # Several kinds mean any one of them: a card that can read through a built-in kind misses nothing.
        if any(not kind.startswith("custom:") for kind in item.requires):
            continue
        unmet = [kind for kind in item.requires if kind.partition(":")[2] not in in_file | here]
        if len(unmet) == len(item.requires):
            missing += [kind for kind in unmet if kind not in missing]
    return Inspection(items, missing)


# -- making what a file holds -----------------------------------------------------------------


@dataclass
class Outcome:
    """What an import did, by the short names as they are kept here."""

    cards_added: list[str] = field(default_factory=list)
    cards_replaced: list[str] = field(default_factory=list)
    integrations_added: list[str] = field(default_factory=list)
    integrations_replaced: list[str] = field(default_factory=list)
    #: ``card:<slug>`` and ``integration:<short>`` of the file to the short name a copy got.
    copies: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    #: Where the documents came from when it is not a person's file (``boards/<file>``); the chronicle says so.
    source: str = ""

    def view(self) -> dict[str, Any]:
        return {
            "cards_added": self.cards_added, "cards_replaced": self.cards_replaced, "integrations_added": self.integrations_added,
            "integrations_replaced": self.integrations_replaced, "copies": self.copies, "skipped": self.skipped,
        }


def _free(taken: set[str], key: str) -> str:
    for number in range(2, 1000):
        suffix = f"-{number}"
        candidate = f"{key[: 60 - len(suffix)]}{suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise Refused("no_free_name", f"No free short name for a copy of {key}.")


def _rewrite(item: Item, pattern: re.Pattern[str], new: str | None, renamed: dict[str, str]) -> str:
    """The text of a document with its short name and the own connections it names changed, nothing else touched."""
    lines = item.text.split("\n")
    where = item.loaded.lines
    if new is not None:
        number = where.get(("slug",) if item.type == "card" else ("short",))
        if number is None:
            raise Refused("import_invalid", f"The short name of {item.key} could not be found in its text.")
        lines[number - 1] = pattern.sub(lambda found: f"{found.group(1)}{new}", lines[number - 1], count=1)
    for index, kind in enumerate(item.requires):
        short = kind.partition(":")[2]
        number = where.get(("requires", index))
        if kind.startswith("custom:") and short in renamed and number is not None:
            lines[number - 1] = re.sub(rf"(?<![\w:.-])custom:{re.escape(short)}(?![\w-])", f"custom:{renamed[short]}", lines[number - 1])
    return "\n".join(lines)


def _said(outcome: Outcome, what: str) -> str:
    """The line of the chronicle: what was done, and where the document came from when it was not a person's file."""
    if outcome.source:
        return f"{what} from {outcome.source}"
    return f"{what} by an import" if what.endswith("replaced") else what


def _chosen(item: Item, choices: dict[str, str]) -> str:
    """What to do with a document: make it (``create``), or what the person chose for a name that is taken."""
    choice = choices.get(item.id)
    if choice is not None and choice not in CHOICES:
        raise Refused("import_choice_invalid", f"{choice!r} is not a choice for {item.id}. Choose replace, copy or skip.", key=item.id)
    if choice == "skip":
        return "skip"
    if not item.exists:
        return "create"
    if choice is None:
        raise Refused("import_choice_missing", f"{item.id} exists already. Choose replace, copy or skip.", key=item.id)
    return choice


def _refuse(problems: list[load.Problem], item: Item) -> Refused:
    return Refused("import_invalid", str(load.CardInvalid(problems)), problems=[problem.as_dict() for problem in problems], key=item.id)


def run(db: Session, text: str, choices: dict[str, str], *, user_id: int | None) -> Outcome:
    """Make what the file holds, in the session and without committing: the caller commits, or rolls back when this raises.

    ⚠️ Every document or none (EC-5): nothing here commits, and the registry of own connections and the cache of cards
    are left alone until :func:`finish` runs after the commit.
    """
    seen = inspect(db, text)
    if not seen.ok:
        first = next(item for item in seen.items if item.problems)
        raise Refused("import_invalid", str(load.CardInvalid(first.problems)), documents=[item.view() for item in seen.items])
    for key in choices:
        if not any(item.id == key for item in seen.items):
            raise Refused("import_choice_invalid", f"The file has no {key}.", key=key)
    return make(db, seen.items, {item.id: _chosen(item, choices) for item in seen.items}, user_id=user_id)


def make(db: Session, items: list[Item], actions: dict[str, str], *, user_id: int | None, source: str = "") -> Outcome:
    """Do what ``actions`` say with each document (create, replace, copy, skip), connections first, without committing."""
    outcome = Outcome(source=source)
    taken_cards = {row.slug for row in store.listing(db)} | set(store.RESERVED_SLUGS) | {item.key for item in items if item.type == "card" and item.key}
    taken_shorts = {row.short for row in integrations.listing(db)} | {item.key for item in items if item.type == "integration" and item.key}
    # An own connection copied under a new short name: the cards of the file that read through it follow the copy.
    renamed = {item.key: _free(taken_shorts, item.key) for item in items if item.type == "integration" and item.key and actions[item.id] == "copy"}
    for item in items:
        if item.type == "integration":
            _make_integration(db, item, actions[item.id], renamed.get(item.key or ""), user_id, outcome)
    for item in items:
        if item.type == "card":
            new = _free(taken_cards, item.key) if actions[item.id] == "copy" and item.key else None
            _make_card(db, item, actions[item.id], new, renamed, user_id, outcome)
    return outcome


def _make_integration(db: Session, item: Item, action: str, new: str | None, user_id: int | None, outcome: Outcome) -> None:
    if action == "skip":
        outcome.skipped.append(item.id)
        return
    text = _rewrite(item, _SHORT_LINE, new, {}) if new is not None else item.text
    try:
        if action == "replace":
            row = integrations.get(db, item.key or "")
            assert row is not None
            integrations.update(db, row, text, user_id=user_id, commit=False)
            outcome.integrations_replaced.append(row.short)
            chronicle.definition_saved(db, added=False, user_id=user_id, name=integrations.kind_of(row.short), detail=_said(outcome, "own connection replaced"))
            return
        row = integrations.create(db, text, user_id=user_id, commit=False)
    except load.CardInvalid as failure:
        raise _refuse(failure.problems, item) from failure
    except integrations.TooManyIntegrations:
        raise Refused("integration_limit", f"There are {integrations.MAX_INTEGRATIONS} own connections already, which is the most nexdeck keeps. Delete one first.") from None
    if action == "copy":
        outcome.copies[item.id] = row.short
    outcome.integrations_added.append(row.short)
    chronicle.definition_saved(db, added=True, user_id=user_id, name=integrations.kind_of(row.short),
                     detail=f"own connection imported as a copy of {item.key}" if action == "copy" else _said(outcome, "own connection imported"))


def _make_card(db: Session, item: Item, action: str, new: str | None, renamed: dict[str, str], user_id: int | None, outcome: Outcome) -> None:
    if action == "skip":
        outcome.skipped.append(item.id)
        return
    text = _rewrite(item, _SLUG_LINE, new, renamed) if (new is not None or renamed) else item.text
    try:
        if action == "replace":
            row = db.scalar(select(CardRecord).where(CardRecord.slug == item.key, CardRecord.kind == "card"))
            assert row is not None
            store.update(db, row, text, user_id=user_id, commit=False)
            # A card that came from the shop is a card of this installation from now on (EC-6).
            row.origin, row.shop_ref, row.shop_version = "local", "", ""
            outcome.cards_replaced.append(row.slug)
            chronicle.definition_saved(db, added=False, user_id=user_id, name=row.slug, detail=_said(outcome, "replaced"))
            return
        row = store.create(db, text, user_id=user_id, commit=False)
    except load.CardInvalid as failure:
        raise _refuse(failure.problems, item) from failure
    except store.TooManyCards:
        raise Refused(
            "too_many_cards", f"There are {store.MAX_CARDS} custom cards already, which is the most nexdeck keeps. Delete one first.", 409,
        ) from None
    if new is not None and row.slug != new:
        raise Refused("import_invalid", f"The short name of the copy of {item.key} could not be changed.")
    if action == "copy":
        outcome.copies[item.id] = row.slug
    outcome.cards_added.append(row.slug)
    chronicle.definition_saved(db, added=True, user_id=user_id, name=row.slug,
                     detail=f"imported as a copy of {item.key}" if action == "copy" else _said(outcome, "imported"))


def finish(outcome: Outcome) -> None:
    """After the commit: the registry of own connections, the cache of cards, and every card that stands on a board fetches again."""
    from ..db import db_session
    from ..routers import cards as card_routes
    from ..routers import own_integrations as integration_routes

    store.invalidate()
    with db_session() as db:
        for short in [*outcome.integrations_added, *outcome.integrations_replaced]:
            row = integrations.get(db, short)
            if row is not None:
                integrations.register(row)
        for short in outcome.integrations_replaced:
            integration_routes._tell(db, short)  # noqa: SLF001
        for slug in outcome.cards_replaced:
            card_routes._tell(db, slug)  # noqa: SLF001
