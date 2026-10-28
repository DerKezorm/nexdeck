"""Sharing a card or an own connection in the Card shop, and what became of it (KARTEN-16).

The way in is the one the Workshop has for everybody: an issue made with its form (``.github/ISSUE_TEMPLATE/submit.yml``).
nexdeck writes the body of that issue the way the form does (:func:`build_body`), so the action of the Workshop reads a
submission from nexdeck and one from the form with the same code, and the issue stands under the GitHub name of the
administrator, made with his own sign-in (``github_login``). The Workshop decides; nexdeck only hands in and reads back.

⚠️ Nothing is kept here. "My submissions" is read from the issues and the comments of the action each time, so a
submission shows up when GitHub has confirmed it and not before (EC-6), and the same submission sent twice is one issue:
before an issue is made, the open ones of this account are searched for the same short name (EC-6, EC-7).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..adapters.base import AdapterError
from ..adapters.rawread import refuse_a_command
from ..cards import credentials, load, schema
from ..cards import integration as integration_loader
from ..cards import integration_store as integrations
from ..models import CardRecord, User
from . import catalog, github_login, installed, real_values, state
from .github_login import GithubError, login_needed

logger = logging.getLogger("nexdeck.workshop")

#: The feature list of the form and of the catalog (KARTEN-13 AC-12).
CATEGORIES = {
    "media": "Media",
    "downloads": "Downloads",
    "network": "Network",
    "server": "Server",
    "smart_home": "Smart home",
    "other": "Other",
}
TYPES = {"card": "Card", "integration": "Connection"}
LABELS = {
    "type": "Type",
    "category": "Category",
    "definition": "Definition",
    "description": "Description",
    "changes": "Changes",
    "based_on": "Based on",
    "update_of": "Update of",
    "license": "License",
}
VERSION_LABEL = "nexdeck version"
LICENSE_SENTENCE = "I submit this under the MIT License and I have the right to do so."
NO_RESPONSE = "_No response_"
#: More new entries than this from one account on one day wait for the next day (KARTEN-13 EC-3).
MAX_NEW_PER_DAY = 10
#: GitHub keeps an issue to 65536 characters.
MAX_BODY = 65_000
MAX_TEXT = 4000
NEW_TITLE = "Submit: "
UPDATE_TITLE = "Submit update: "
BOT = "github-actions[bot]"
MARKER = re.compile(r"<!-- workshop:(accepted|rejected|deferred):([0-9a-f]{64}) -->")
_HEADING = re.compile(r"^### (.+?)[ \t]*$")
_OPEN = re.compile(r"^(`{3,}|~{3,})(.*)$")
_EDGE = ("#", "`", "~")
_SLUG = re.compile(r"^(?:Submit update: |Submit: )([a-z0-9][a-z0-9_-]{0,59})$")


class SubmitError(Exception):
    """Something an administrator is told in a sentence. ``status`` is the HTTP status it becomes."""

    def __init__(self, code: str, message: str, status: int = 400, **more: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.more = code, message, status, more


# -- the body of the issue -------------------------------------------------------------------------


def mask(text: str) -> str:
    """A text of the author for one field of the issue: no line of it can be read as a heading or as the edge of a code block.

    ⚠️ The Workshop reads the issue by its ``### heading`` lines and its code fences, and the author writes free text. A line
    that starts with ``#``, a backtick or a tilde gets a backslash in front (so does a line that starts with a backslash and
    one of those, which keeps :func:`unmask` exact). Markdown shows the sign itself, the reader of the Workshop takes the
    backslash away again, and nothing can end a field early, open a code block, or write a field of its own.
    """
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        bare = line.lstrip()
        if bare[:1] in _EDGE or (bare[:1] == "\\" and bare[1:2] in (*_EDGE, "\\")):
            line = line[: len(line) - len(bare)] + "\\" + bare
        out.append(line)
    return "\n".join(out)


def unmask(text: str) -> str:
    """What :func:`mask` made of a text, as the author wrote it."""
    out = []
    for line in text.split("\n"):
        bare = line.lstrip()
        if bare[:1] == "\\" and bare[1:2] in (*_EDGE, "\\"):
            line = line[: len(line) - len(bare)] + bare[1:]
        out.append(line)
    return "\n".join(out)


def fence_of(text: str) -> str:
    """A code fence longer than any run of backticks in the text, so that nothing inside it can close it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def build_body(
    *,
    type: str,
    category: str,
    definition: str,
    description: str,
    changes: str = "",
    based_on: str = "",
    update_of: str = "",
    licensed: bool = True,
    version: str = __version__,
) -> str:
    """The body of the issue the way the form of the Workshop writes it, and the version of this nexdeck at the end."""
    fence = fence_of(definition)
    fenced = f"{fence}yaml\n" + definition.rstrip("\n") + f"\n{fence}"
    box = f"- [{'x' if licensed else ' '}] {LICENSE_SENTENCE}"
    parts = [
        (LABELS["type"], TYPES[type]),
        (LABELS["category"], CATEGORIES[category]),
        (LABELS["definition"], fenced),
        (LABELS["description"], mask(description) if description.strip() else NO_RESPONSE),
        (LABELS["changes"], mask(changes) if changes.strip() else NO_RESPONSE),
        (LABELS["based_on"], mask(based_on) if based_on.strip() else NO_RESPONSE),
        (LABELS["update_of"], mask(update_of) if update_of.strip() else NO_RESPONSE),
        (LABELS["license"], box),
        (VERSION_LABEL, version),
    ]
    return "\n\n".join(f"### {label}\n\n{value}" for label, value in parts) + "\n"


def _opens(line: str) -> tuple[str, int] | None:
    """``(sign, length)`` when the line opens a code block."""
    found = _OPEN.match(line.lstrip())
    if found is None or (found.group(1)[0] == "`" and "`" in found.group(2)):
        return None
    return found.group(1)[0], len(found.group(1))


def _closes(line: str, fence: tuple[str, int]) -> bool:
    bare = line.strip()
    return len(bare) >= fence[1] and set(bare) == {fence[0]}


def sections_of(body: str) -> list[tuple[str, list[str]]]:
    """``(heading, lines)`` per ``### heading``; a heading inside a code block is part of the block (the rule of the Workshop)."""
    sections: list[tuple[str, list[str]]] = []
    fence: tuple[str, int] | None = None
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        heading = None
        if fence is None:
            fence = _opens(line)
            heading = None if fence else _HEADING.match(line)
        elif _closes(line, fence):
            fence = None
        if heading:
            sections.append((heading.group(1).strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def unfence(value: str) -> str:
    """The text inside a code block that fills a whole field; any other text as it is."""
    lines = value.split("\n")
    fence = _opens(lines[0]) if len(lines) >= 2 else None
    if fence and _closes(lines[-1], fence):
        return "\n".join(lines[1:-1])
    return value


def parse_body(body: str) -> dict[str, str]:
    """The fields of an issue body, as far as nexdeck needs them back (Fix and resend, "My submissions")."""
    labels = {label: key for key, label in {**LABELS, "version": VERSION_LABEL}.items()}
    found: dict[str, str] = {}
    for label, lines in sections_of(body):
        key = labels.get(label)
        if key is None or key in found:
            continue
        value = "\n".join(lines).strip()
        value = "" if value == NO_RESPONSE else value
        if key == "definition":
            value = unfence(value).strip("\n") + "\n"
        elif key in ("description", "changes", "based_on", "update_of"):
            value = unmask(value)
        found[key] = value
    return found


def plain(value: Any) -> str:
    """A text of the author as one string, English first."""
    if isinstance(value, dict):
        return str(value.get("en") or next(iter(value.values()), ""))
    return "" if value is None else str(value)


# -- what is being shared --------------------------------------------------------------------------


@dataclass
class Subject:
    """A card or an own connection of this installation, as it is saved."""

    type: str
    slug: str
    text: str
    origin: str
    shop_ref: str
    locally_changed: bool
    name: str = ""
    version: str = ""
    description: str = ""
    category: str = ""
    demo: Any = None
    reads: list[dict[str, str]] = field(default_factory=list)


def subject_of(db: Session, kind: str, slug: str) -> Subject:
    """The saved card or connection with this short name; ``no_such_card`` when there is none."""
    if kind == "card":
        row = db.scalar(select(CardRecord).where(CardRecord.slug == slug, CardRecord.kind == "card"))
        if row is None:
            raise SubmitError("no_such_card", "There is no such card.", 404)
        one = installed.Installed("card", row.slug, row.shop_ref, row.shop_version, row.yaml_source, row.shop_hash)
        return Subject("card", row.slug, row.yaml_source, row.origin, row.shop_ref, one.locally_changed)
    row2 = integrations.get(db, slug)
    if row2 is None:
        raise SubmitError("no_such_card", "There is no such connection.", 404)
    one = installed.Installed("integration", row2.short, row2.shop_ref, row2.shop_version, row2.yaml_source, row2.shop_hash)
    return Subject("integration", row2.short, row2.yaml_source, "shop" if row2.shop_ref else "local", row2.shop_ref, one.locally_changed)


def problem(code: str, message: str, path: str = "") -> dict[str, str]:
    return {"code": code, "message": message, "path": path}


def read_definition(one: Subject) -> list[dict[str, str]]:
    """What is wrong with the text for the Workshop (nothing, when the list is empty); fills in what the dialog shows."""
    problems: list[dict[str, str]] = []
    if len(one.text) > schema.MAX_DEFINITION:
        return [problem("too_long", f"The definition is {len(one.text)} characters long, the limit is {schema.MAX_DEFINITION}.")]
    try:
        if one.type == "card":
            loaded = load.load_definition(one.text)
            definition = loaded.definition
            problems += [problem(p.code, p.message, p.path) for p in load.check_for_submission(definition)]
            for index, request in enumerate(definition.requests):
                try:
                    refuse_a_command(SimpleNamespace(raw_read_commands=None), request.path)  # type: ignore[arg-type]
                except AdapterError as failure:
                    problems.append(problem("command_refused", failure.message, f"requests[{index}].path"))
            one.name, one.version = plain(definition.name), definition.version
            one.description = plain(definition.description)
            one.category = definition.category or ""
            one.demo = definition.demo
        else:
            made = integration_loader.load_integration(one.text, saved=[])
            definition = made.definition
            one.name, one.version = definition.name, ""
            one.description = definition.description
            one.category = definition.category
            one.reads = [{"label": read.label, "path": read.path} for read in definition.reads]
    except load.CardInvalid as failure:
        problems += [problem(p.code, p.message, p.path) for p in failure.problems]
    return problems


def category_guess(text: str) -> str:
    key = re.sub(r"[^a-z]+", "_", text.lower()).strip("_")
    return key if key in CATEGORIES else ""


# -- the form of the dialog ------------------------------------------------------------------------


@dataclass
class Form:
    """What the administrator wrote in the dialog."""

    category: str = ""
    description: str = ""
    changes: str = ""
    license: bool = False


def read_form(form: Form, *, update: bool) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    if form.category not in CATEGORIES:
        problems.append(problem("category", f"Pick a category: {', '.join(CATEGORIES.values())}.", "category"))
    if not form.description.strip():
        problems.append(problem("description", "Add a description of a few sentences, in English.", "description"))
    if len(form.description) > MAX_TEXT or len(form.changes) > MAX_TEXT:
        problems.append(problem("too_long", f"The description and the list of changes may have {MAX_TEXT} characters each.", "description"))
    for label, text in (("description", form.description), ("changes", form.changes)):
        found = credentials._value(text, structure=False)  # noqa: SLF001
        if found:
            problems.append(problem("secret_in_text", f"The {label} looks like it holds {credentials.PHRASES[found]}. Take it out.", label))
    if update and not form.changes.strip():
        problems.append(problem("changes", "An update needs a list of changes.", "changes"))
    if not form.license:
        problems.append(problem("license", "Tick the box that says you submit this under the MIT License.", "license"))
    return problems


# -- GitHub: the issues of the Workshop --------------------------------------------------------------


@dataclass
class Context:
    """Who shares, with which sign-in, into which repository."""

    db: Session
    user: User
    repo: str
    access: github_login.Access

    async def api(self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        """One request to the issues of the Workshop, with the token of the administrator."""
        response = await github_login.call(method, f"{github_login.API}/repos/{self.repo}/issues{path}", token=self.access.token, json=json, params=params)
        code = response.status_code
        if code == 401:
            github_login.drop(self.db, self.user.id)
            raise login_needed("revoked")
        if code == 429 or (code == 403 and _asks_to_wait(response)):
            raise GithubError("github_rate_limited", "GitHub asks you to wait a moment before the next request. Try again shortly.")
        if code in (403, 404, 410):
            # The repository is private and this account was not asked in (EC-3), or the issues are turned off.
            raise GithubError(
                "repo_no_access",
                "Your GitHub account cannot reach the Workshop repository. While it is private, only the accounts invited to it can share cards.",
                403,
            )
        if code >= 500:
            raise GithubError("github_unreachable", github_login.UNREACHABLE)
        if code not in (200, 201):
            logger.info("GitHub answered %s to %s %s.", code, method, path)
            raise GithubError("github_rejected", "GitHub did not take the request. Try again later.")
        try:
            return response.json()
        except ValueError:
            raise GithubError("github_rejected", "GitHub gave an answer nexdeck cannot read.") from None

    async def name(self) -> None:
        """The GitHub name of this account as it is now: it is stored when the administrator signs in, and a renamed account would find none of its issues."""
        response = await github_login.call("GET", f"{github_login.API}/user", token=self.access.token)
        if response.status_code == 401:
            github_login.drop(self.db, self.user.id)
            raise login_needed("revoked")
        try:
            who = response.json()
        except ValueError:
            who = None
        if response.status_code == 200 and isinstance(who, dict) and who.get("login"):
            github_login.rename(self.db, self.user.id, str(who["login"]))
            self.access = replace(self.access, login=str(who["login"])[:100])

    async def mine(self, state_name: str = "all") -> list[dict[str, Any]]:
        """The issues of this account in the Workshop, the newest first (a pull request is none)."""
        await self.name()
        found = await self.api("GET", "", params={"creator": self.access.login, "state": state_name, "per_page": 100, "sort": "created", "direction": "desc"})
        return [one for one in found if isinstance(one, dict) and "pull_request" not in one and (one.get("user") or {}).get("id") == _number(self.access.github_id)]

    async def comments(self, issue: dict[str, Any]) -> list[dict[str, Any]]:
        """The comments of an issue, the last page of them (the answer of the action is among the last)."""
        count = int(issue.get("comments") or 0)
        if count == 0:
            return []
        page = max(1, -(-count // 100))
        found = await self.api("GET", f"/{issue['number']}/comments", params={"per_page": 100, "page": page})
        return [one for one in found if isinstance(one, dict)]


def _asks_to_wait(response: Any) -> bool:
    """A 403 that is a limit and no refusal: the primary limit is used up, or the secondary one (``retry-after``, "rate limit" in the message) was hit."""
    if response.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in response.headers:
        return True
    try:
        message = str(response.json().get("message") or "")
    except (ValueError, AttributeError):
        return False
    return "rate limit" in message.lower()


def _number(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return -1


def slug_of(issue: dict[str, Any]) -> str | None:
    found = _SLUG.match(str(issue.get("title") or ""))
    return found.group(1) if found else None


def last_marker(comments: list[dict[str, Any]]) -> tuple[str, str, str] | None:
    """What the action said last: ``(status, digest of the wording it judged, the text of the comment)``."""
    for comment in reversed(comments):
        if (comment.get("user") or {}).get("login") != BOT:
            continue
        found = MARKER.search(comment.get("body") or "")
        if found:
            return found.group(1), found.group(2), str(comment.get("body") or "")
    return None


def reasons_of(text: str) -> list[str]:
    """The reasons the action gave: the bullets of its comment."""
    lines = [line[2:].strip() for line in text.split("\n") if line.startswith("- ")]
    return [line for line in lines if line][:30]


def today() -> str:
    return datetime.fromtimestamp(github_login.now(), UTC).strftime("%Y-%m-%d")


async def context(db: Session, user: User) -> Context:
    """The sign-in of this administrator and the repository he shares into; ``github_login_needed`` when he is not signed in."""
    access = await github_login.session(db, user.id)
    return Context(db, user, state.repo(db), access)


# -- looking at the history -------------------------------------------------------------------------


@dataclass
class History:
    """What this account has in the Workshop under one short name."""

    open: dict[str, Any] | None = None
    accepted: bool = False
    #: The newest closed issue that the action took in: what the author wrote then, when the catalog does not have the entry.
    accepted_issue: dict[str, Any] | None = None
    new_today: int = 0
    entry: catalog.Entry | None = None


async def history(ctx: Context, kind: str, slug: str) -> History:
    """The open issue under this name (the one a new try goes into), whether it was taken in before, how many new ones were made today."""
    issues = await ctx.mine("all")
    found = History()
    day = today()
    for one in issues:
        title = str(one.get("title") or "")
        if title.startswith(NEW_TITLE) and str(one.get("created_at") or "")[:10] == day:
            found.new_today += 1
    same = [one for one in issues if slug_of(one) == slug and parse_body(str(one.get("body") or "")).get("type", "").lower() == TYPES[kind].lower()]
    found.open = next((one for one in same if one.get("state") == "open"), None)
    for one in [one for one in same if one.get("state") == "closed"][:3]:
        marker = last_marker(await ctx.comments(one))
        if marker and marker[0] == "accepted":
            found.accepted = True
            found.accepted_issue = one
            break
    found.entry = await entry_of(ctx.db, f"{ctx.access.github_id}/{slug}")
    return found


async def entry_of(db: Session, entry_id: str) -> catalog.Entry | None:
    """The catalog entry, when the shop is on and the catalog can be had; the catalog is the shop's business, so its trouble is not ours."""
    if not state.enabled(db):
        return None
    try:
        found, _warning = await catalog.load(state.repo(db))
    except catalog.CatalogError:
        return None
    return found.by_id.get(entry_id)


def previous_words(past: History, one: Subject) -> dict[str, str]:
    """The description and category of the earlier entry of this name, for an update to start from (N5): the catalog, else the issue it came in with.

    What the earlier entry does not tell stays what the card says.
    """
    description, category = "", ""
    if past.entry is not None:
        description, category = plain(past.entry.description).strip(), past.entry.category
    elif past.accepted_issue is not None:
        fields = parse_body(str(past.accepted_issue.get("body") or ""))
        description, category = fields.get("description", "").strip(), category_guess(fields.get("category", ""))
    return {"description": description or one.description, "category": category or category_guess(one.category)}


def lineage(one: Subject, github_id: str | None) -> tuple[str | None, str | None, list[dict[str, str]]]:
    """``(based_on, own entry, problems)``: what came unchanged from the shop is not shared again; a changed card of somebody else is shared as a new card that is based on it (AC-8)."""
    if one.origin != "shop" or not one.shop_ref:
        return None, None, []
    if not one.locally_changed:
        return None, None, [problem("unchanged_from_shop", "This came unchanged from the Card shop. Change it to share your own version.")]
    author = one.shop_ref.partition("/")[0]
    if github_id and author == github_id:
        return None, one.shop_ref, []
    return one.shop_ref, None, []


# -- the check of the dialog ----------------------------------------------------------------------------


async def check(db: Session, user: User, kind: str, slug: str) -> dict[str, Any]:
    """Everything the dialog shows before anything is sent: what is wrong, what to be warned of, new or update, how many today.

    The words the administrator types are not judged here: the dialog asks for them while they are typed, sending judges them again.
    """
    one = subject_of(db, kind, slug)
    problems = read_definition(one)
    signed = github_login.status(db, user.id)
    out: dict[str, Any] = {
        "type": one.type,
        "slug": one.slug,
        "name": one.name,
        "version": one.version,
        "problems": problems,
        "warnings": {"real_values": real_values.places(user, one.demo) if one.type == "card" else []},
        "signed_in": signed["signed_in"],
        "login": signed["login"],
        "mode": "new",
        "previous_version": None,
        "based_on": None,
        "removed": None,
        "daily": None,
        "github": None,
        "suggested": {"description": one.description, "category": category_guess(one.category)},
        "reads": one.reads,
        "repo": state.repo(db),
    }
    github_id = signed["github_id"]
    based_on, own, lineage_problems = lineage(one, github_id)
    problems += lineage_problems
    out["based_on"] = based_on
    if not signed["signed_in"]:
        out["mode"] = "update" if own else "new"
        return out
    try:
        ctx = await context(db, user)
        past = await history(ctx, one.type, one.slug)
    except GithubError as failure:
        out["github"] = {"code": failure.code, "message": failure.message}
        out["signed_in"] = failure.code != "github_login_needed" and out["signed_in"]
        return out
    update = past.entry is not None or past.accepted or own is not None
    out["mode"] = "update" if update else "new"
    if update:
        out["suggested"] = previous_words(past, one)
    if past.entry is not None:
        out["previous_version"] = past.entry.version
        if past.entry.removed is not None and past.entry.removed.level != "withdrawn":
            out["removed"] = {"level": past.entry.removed.level, "reason": past.entry.removed.reason}
            problems.append(problem("entry_removed", "A maintainer took this entry out of the Card shop. Ask a maintainer to bring it back before sharing an update."))
        elif one.type == "card" and one.version and not installed.newer(one.version, past.entry.version):
            problems.append(problem("version_not_higher", f"The version must be higher than the {past.entry.version} that is in the Card shop. Raise it in the editor."))
    if not update:
        used = past.new_today if past.open is None else past.new_today - 1
        out["daily"] = {"used": max(0, used), "max": MAX_NEW_PER_DAY, "reached": used >= MAX_NEW_PER_DAY}
    return out


# -- sending ------------------------------------------------------------------------------------------

#: The submissions that are on their way: a second click on the same one is turned away, not sent again (EC-7).
_busy: set[tuple[int, str, str]] = set()


def forget() -> None:
    _busy.clear()


def _make_body(one: Subject, form: Form, *, based_on: str | None, update: bool) -> str:
    return build_body(
        type=one.type,
        category=form.category,
        definition=one.text,
        description=form.description.strip(),
        changes=form.changes.strip() if update else "",
        based_on=based_on or "",
    )


def view_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {"number": issue.get("number"), "url": issue.get("html_url"), "state": issue.get("state")}


async def submit(db: Session, user: User, kind: str, slug: str, form: Form) -> dict[str, Any]:
    """Hand the card in: an issue under the name of the administrator, or the one he has open already, brought up to date (EC-6, EC-7)."""
    key = (user.id, kind, slug)
    if key in _busy:
        raise SubmitError("already_sending", "This submission is on its way. Wait a moment.", 409)
    _busy.add(key)
    try:
        ctx = await context(db, user)
        one = subject_of(db, kind, slug)
        problems = read_definition(one)
        based_on, own, lineage_problems = lineage(one, ctx.access.github_id)
        problems += lineage_problems
        past = await history(ctx, kind, slug)
        update = past.entry is not None or past.accepted or own is not None
        if past.entry is not None:
            if past.entry.removed is not None and past.entry.removed.level != "withdrawn":
                problems.append(problem("entry_removed", "A maintainer took this entry out of the Card shop. Ask a maintainer to bring it back before sharing an update."))
            elif kind == "card" and one.version and not installed.newer(one.version, past.entry.version):
                problems.append(problem("version_not_higher", f"The version must be higher than the {past.entry.version} that is in the Card shop. Raise it in the editor."))
        problems += read_form(form, update=update)
        if not problems:
            problems += _length(one, form, based_on, update)
        if problems:
            raise SubmitError("submission_invalid", "The submission cannot be sent yet.", 400, problems=problems)
        body = _make_body(one, form, based_on=based_on, update=update)
        title = f"{UPDATE_TITLE if update else NEW_TITLE}{slug}"
        if past.open is not None:
            if past.open.get("body") == body and past.open.get("title") == title:
                return {"issue": view_issue(past.open), "created": False, "changed": False, "update": update}
            edited = await ctx.api("PATCH", f"/{past.open['number']}", json={"title": title, "body": body})
            logger.info("%s sent a new wording of %s %s to issue %s.", user.username, kind, slug, past.open["number"])
            return {"issue": view_issue(edited), "created": False, "changed": True, "update": update}
        if not update and past.new_today >= MAX_NEW_PER_DAY:
            raise SubmitError(
                "daily_limit",
                f"This GitHub account has made {MAX_NEW_PER_DAY} new submissions today, which is the most the Workshop takes in a day. Try again tomorrow.",
                409,
            )
        made = await ctx.api("POST", "", json={"title": title, "body": body})
        logger.info("%s shared %s %s in the Workshop as issue %s.", user.username, kind, slug, made.get("number"))
        return {"issue": view_issue(made), "created": True, "changed": True, "update": update}
    finally:
        _busy.discard(key)


def _length(one: Subject, form: Form, based_on: str | None, update: bool) -> list[dict[str, str]]:
    if len(_make_body(one, form, based_on=based_on, update=update)) > MAX_BODY:
        return [problem("too_long", f"The submission is longer than GitHub keeps in an issue ({MAX_BODY} characters). Shorten the definition or its demo data.")]
    return []


async def resend(db: Session, user: User, number: int) -> dict[str, Any]:
    """"Fix and resend": the card as it is now goes into the issue it was handed in with (AC-10)."""
    ctx = await context(db, user)
    issue = await ctx.api("GET", f"/{number}")
    slug = slug_of(issue)
    if issue.get("state") != "open" or slug is None or (issue.get("user") or {}).get("id") != _number(ctx.access.github_id):
        raise SubmitError("not_resendable", "This is not an open submission of yours.", 409)
    fields = parse_body(str(issue.get("body") or ""))
    kind = "integration" if fields.get("type", "").lower().startswith("conn") else "card"
    key = (user.id, kind, slug)
    if key in _busy:
        raise SubmitError("already_sending", "This submission is on its way. Wait a moment.", 409)
    _busy.add(key)
    try:
        one = subject_of(db, kind, slug)
        problems = read_definition(one)
        form = Form(
            category=next((key_ for key_, label in CATEGORIES.items() if label.lower() == fields.get("category", "").lower()), ""),
            description=fields.get("description", ""),
            changes=fields.get("changes", ""),
            license=True,
        )
        problems += read_form(form, update=str(issue.get("title") or "").startswith(UPDATE_TITLE))
        if problems:
            raise SubmitError("submission_invalid", "The submission cannot be sent yet.", 400, problems=problems)
        body = build_body(
            type=kind, category=form.category, definition=one.text, description=form.description, changes=form.changes,
            based_on=fields.get("based_on", ""), update_of=fields.get("update_of", ""),
        )
        if body == issue.get("body"):
            # Nothing changed, so the action would not judge it again by itself: ask it to look once more.
            await ctx.api("POST", f"/{number}/comments", json={"body": "/recheck"})
            how = "recheck"
        else:
            await ctx.api("PATCH", f"/{number}", json={"body": body})
            how = "edited"
        logger.info("%s sent %s %s again to issue %s (%s).", user.username, kind, slug, number, how)
        return {"issue": {"number": number, "url": issue.get("html_url"), "state": "open"}, "how": how}
    finally:
        _busy.discard(key)


# -- without signing in (AC-9) ----------------------------------------------------------------------------


def form_link(repo: str, one: Subject, form: Form, based_on: str | None) -> str:
    """The form of the Workshop on GitHub, as far as an address can fill it in: the definition is too long for that."""
    parts = {
        "template": "submit.yml",
        "title": f"{NEW_TITLE}{one.slug}",
        "type": TYPES[one.type],
        "category": CATEGORIES.get(form.category, ""),
        "description": mask(form.description.strip())[:1500],
        "based_on": based_on or "",
    }
    query = "&".join(f"{name}={quote(value, safe='')}" for name, value in parts.items() if value)
    return f"https://github.com/{repo}/issues/new?{query}"


async def offline(db: Session, user: User, kind: str, slug: str, form: Form) -> dict[str, Any]:
    """The submission as a file and a link to the form on GitHub, for an administrator who does not sign in (AC-9)."""
    one = subject_of(db, kind, slug)
    problems = read_definition(one)
    signed = github_login.status(db, user.id)
    based_on, _own, lineage_problems = lineage(one, signed["github_id"])
    problems += lineage_problems + read_form(form, update=bool(form.changes.strip()))
    if not problems:
        problems += _length(one, form, based_on, bool(form.changes.strip()))
    if problems:
        raise SubmitError("submission_invalid", "The submission cannot be written yet.", 400, problems=problems)
    repo = state.repo(db)
    text = _make_body(one, form, based_on=based_on, update=bool(form.changes.strip()))
    return {"filename": f"nexdeck-submission-{one.slug}.md", "text": text, "link": form_link(repo, one, form, based_on)}


# -- My submissions (AC-6) ----------------------------------------------------------------------------------


def _state_of(issue: dict[str, Any], marker: tuple[str, str, str] | None) -> tuple[str, list[str]]:
    digest = hashlib.sha256(str(issue.get("body") or "").encode("utf-8")).hexdigest()
    if marker is None or marker[1] != digest:
        return ("closed", []) if issue.get("state") == "closed" and marker is None else ("checking", [])
    if marker[0] == "rejected":
        return "failed", reasons_of(marker[2])
    if marker[0] == "deferred":
        return "waiting", []
    return "in_shop", []


async def submissions(db: Session, user: User) -> dict[str, Any]:
    """What became of each submission of this account: in review, failed with the reasons, in the shop, removed with the reason."""
    signed = github_login.status(db, user.id)
    if not signed["signed_in"]:
        return {"signed_in": False, "login": None, "items": [], "catalog_known": False}
    ctx = await context(db, user)
    issues = [one for one in await ctx.mine("all") if slug_of(one) is not None][:30]
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for one in issues:
        fields = parse_body(str(one.get("body") or ""))
        kind = "integration" if fields.get("type", "").lower().startswith("conn") else "card"
        latest.setdefault((kind, str(slug_of(one))), one)
    known = None
    if state.enabled(db):
        try:
            known, _warning = await catalog.load(state.repo(db))
        except catalog.CatalogError:
            known = None
    local_cards = set(db.scalars(select(CardRecord.slug).where(CardRecord.kind == "card")))
    local_connections = set(integrations.shorts(db))
    items = []
    for (kind, slug), one in latest.items():
        marker = last_marker(await ctx.comments(one))
        status, reasons = _state_of(one, marker)
        entry = known.by_id.get(f"{signed['github_id']}/{slug}") if known is not None and status == "in_shop" else None
        removed = None
        if entry is not None and entry.removed is not None:
            status = "removed"
            removed = {"level": entry.removed.level, "reason": entry.removed.reason, "at": entry.removed.at}
        items.append({
            "issue": one.get("number"),
            "url": one.get("html_url"),
            "slug": slug,
            "type": kind,
            "update": str(one.get("title") or "").startswith(UPDATE_TITLE),
            "created_at": one.get("created_at"),
            "state": status,
            "reasons": reasons,
            "removed": removed,
            "entry": {"id": entry.id, "version": entry.version, "thumbs": entry.thumbs, "discussion": entry.discussion} if entry is not None else None,
            "local": slug in (local_cards if kind == "card" else local_connections),
        })
    return {"signed_in": True, "login": signed["login"], "items": items, "catalog_known": known is not None}
