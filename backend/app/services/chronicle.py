"""The chronicle: what changed, and when.

"The problem began at 14:32, and at 14:28 the container was updated" is the
question a dashboard gets asked when something breaks, and until now nothing
here could answer it: a card knew how it stood, not since when or what came
before. Every source of change writes one line here, at the moment it sees
the change, and never more than once for the same change:

* a card that turns yellow, red or green again (the collector);
* a service that stops answering and comes back (the checks), and maintenance;
* a service that runs another version, a container that restarted or was
  created anew (the version readings and the Docker cards);
* changes made in nexdeck: connections and cards added, changed, removed,
  and sign-ins.

⚠️ Writing a line must never break whatever wrote it. A full disk or a locked
database loses the line, not the fetch or the sign-in that caused it.

⚠️ Only a change is written, never a reading. A card that is yellow for a
week is one line, not twenty thousand.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..db import db_session
from ..models import Board, Event, Page, Role, Setting, User, Widget, utcnow

logger = logging.getLogger("nexdeck.chronicle")

#: Every kind of line, with what it means. The interface words each one itself.
KINDS: dict[str, str] = {
    "card": "A card turned yellow, red or green",
    "outage": "A service stopped answering",
    "recovery": "A service is back",
    "maintenance": "Maintenance began",
    "maintenance_end": "Maintenance was ended early",
    "forecast": "Something will be full or reach its red line within two weeks",
    "version": "A service runs another version",
    "container_restarted": "A container restarted",
    "container_recreated": "A container was created anew",
    "connection_added": "A connection was added",
    "connection_changed": "A connection was changed",
    "connection_removed": "A connection was removed",
    "card_definition_added": "A custom card was made or copied",
    "card_definition_changed": "A custom card was changed, released for users or reserved for administrators",
    "card_definition_removed": "A custom card was deleted",
    "card_added": "A card was added",
    "card_removed": "A card was removed",
    "signed_in": "Somebody signed in",
    "sign_in_refused": "A sign-in was refused",
}

#: The filters of the chronicle page and of the card.
GROUPS: dict[str, tuple[str, ...]] = {
    "cards": ("card", "outage", "recovery", "maintenance", "maintenance_end", "forecast"),
    "versions": ("version", "container_restarted", "container_recreated"),
    "nexdeck": ("connection_added", "connection_changed", "connection_removed",
               "card_definition_added", "card_definition_changed", "card_definition_removed", "card_added", "card_removed", "signed_in", "sign_in_refused"),
}

#: Lines only administrators see: they are about the installation, not about a board.
ADMIN_ONLY = frozenset({
    "connection_added", "connection_changed", "connection_removed",
    "card_definition_added", "card_definition_changed", "card_definition_removed", "signed_in", "sign_in_refused",
})


def _clip(text: Any, length: int) -> str:
    return " ".join(str(text or "").split())[:length]


def record(kind: str, *, level: str = "info", widget_id: int | None = None, integration_id: int | None = None,
           board_id: int | None = None, user_id: int | None = None, name: str = "", before: str = "", after: str = "",
           detail: str = "", at: datetime | None = None, db: Session | None = None) -> None:
    """Write one line. With ``db`` it goes into that session; otherwise into one of its own."""
    if kind not in KINDS:
        raise ValueError(f"Unknown chronicle kind {kind!r}.")
    row = Event(kind=kind, level=level, widget_id=widget_id, integration_id=integration_id, board_id=board_id,
                user_id=user_id, name=_clip(name, 200), before=_clip(before, 200), after=_clip(after, 200),
                detail=_clip(detail, 400), at=at or utcnow())
    try:
        if db is not None:
            if row.board_id is None and widget_id is not None:
                row.board_id = board_of(db, widget_id)
            db.add(row)
            return
        with db_session() as own:
            if row.board_id is None and widget_id is not None:
                row.board_id = board_of(own, widget_id)
            own.add(row)
    except Exception:  # noqa: BLE001 - see the module: the line is lost, not what caused it
        logger.exception("A line of the chronicle (%s, %r) could not be written.", kind, name)


def board_of(db: Session, widget_id: int) -> int | None:
    return db.scalar(select(Page.board_id).join(Widget, Widget.page_id == Page.id).where(Widget.id == widget_id))


# -- cards ------------------------------------------------------------------


def card_turned(widget_id: int, title: str, before: str, after: str, reason: str = "", integration_id: int | None = None) -> None:
    """A card went from one of green, yellow and red to another."""
    level = after if after in ("warn", "bad") else "ok"
    record("card", level=level, widget_id=widget_id, integration_id=integration_id, name=title,
           before=before, after=after, detail=reason)


def last_turned(widget_id: int, level: str) -> float | None:
    """When the card turned to ``level``, if its last line says so.

    After a restart the live state no longer knows since when a card is
    yellow; the chronicle still does, as long as the change happened while
    nexdeck was running.
    """
    with db_session() as db:
        row = db.scalar(select(Event).where(Event.kind == "card", Event.widget_id == widget_id)
                        .order_by(Event.at.desc(), Event.id.desc()).limit(1))
        if row is None or row.after != level:
            return None
        return row.at.timestamp()


# -- containers ---------------------------------------------------------------

_UNIT = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000, "year": 31536000}
_UP = re.compile(r"^Up\s+(?:(?P<about>About an?|An?)\s+(?P<one>second|minute|hour|day|week|month|year)|(?P<count>\d+)\s+(?P<unit>second|minute|hour|day|week|month|year)s?|(?P<less>Less than a second))", re.I)


def uptime(status: str) -> float | None:
    """Seconds a container has been up, from Docker's own words ("Up 3 days (healthy)").

    Docker rounds hard: "About an hour", "2 weeks". Good enough to tell a
    container that restarted from one that kept running, which is all it is
    used for.
    """
    match = _UP.match(str(status or "").strip())
    if not match:
        return None
    if match["less"]:
        return 0.0
    if match["one"]:
        return float(_UNIT[match["one"].lower()])
    return float(int(match["count"]) * _UNIT[match["unit"].lower()])


def containers_changed(before: Any, after: Any) -> list[tuple[str, str, str, str]]:
    """``(kind, name, before, after)`` for every container that restarted or was created anew.

    Matched by name. A new id under the same name was created anew (an image
    update does that); a running container whose time up went down restarted.
    Docker rounds its words but never down, so any less is a restart, even
    "2 minutes" to "About a minute". A card that could not be read compares
    nothing.
    """
    if before is None or getattr(before, "error", None) or getattr(after, "error", None):
        return []
    was = {str(row.get("title")): row for row in before.items or [] if row.get("title")}
    found: list[tuple[str, str, str, str]] = []
    for row in after.items or []:
        name = str(row.get("title") or "")
        old = was.get(name)
        if not name or old is None:
            continue
        if old.get("id") and row.get("id") and old.get("id") != row.get("id"):
            found.append(("container_recreated", name, str(old.get("image") or ""), str(row.get("image") or "")))
            continue
        if old.get("state") == "running" and row.get("state") == "running":
            then, now = uptime(str(old.get("subtitle") or "")), uptime(str(row.get("subtitle") or ""))
            if then is not None and now is not None and now < then:
                found.append(("container_restarted", name, str(old.get("subtitle") or ""), str(row.get("subtitle") or "")))
    return found


# -- versions -----------------------------------------------------------------

SEEN_KEY = "chronicle.versions"


def version_read(integration_id: int, name: str, running: str | None) -> None:
    """Remember the version a connection runs; a different one than last time is a line.

    The first reading of a connection is no change, it is where the
    remembering starts.
    """
    if not running:
        return
    try:
        with db_session() as db:
            setting = db.get(Setting, SEEN_KEY)
            seen: dict[str, str] = dict(setting.value or {}) if setting is not None else {}
            known = seen.get(str(integration_id))
            if known == running:
                return
            seen[str(integration_id)] = running
            # A new dict, not the old one changed: the JSON column notices only an assignment.
            if setting is None:
                db.add(Setting(key=SEEN_KEY, value=seen))
            else:
                setting.value = seen
            if known is not None:
                record("version", level="info", integration_id=integration_id, name=name, before=known, after=running, db=db)
    except Exception:  # noqa: BLE001 - a reading must not fail because it could not be remembered
        logger.exception("The version of connection %s could not be remembered.", integration_id)


# -- reading ------------------------------------------------------------------


def _open_boards(db: Session, user: User) -> set[int]:
    from ..deps import board_permission

    return {board.id for board in db.scalars(select(Board)) if board_permission(db, board, user) is not None}


def _owner_boards(db: Session, owner_id: int | None, board_id: int) -> set[int]:
    if owner_id is None:
        return {board_id}
    return set(db.scalars(select(Board.id).where(Board.owner_id == owner_id)))


def _within(boards: set[int], db: Session):  # noqa: ANN202 - an SQL condition
    """Lines about these boards: a card on one of them, or a connection one of their cards uses."""
    integrations = set(db.scalars(
        select(Widget.integration_id).join(Page, Widget.page_id == Page.id)
        .where(Page.board_id.in_(list(boards) or [-1]), Widget.integration_id.is_not(None))
    ))
    return or_(Event.board_id.in_(list(boards) or [-1]), Event.integration_id.in_(list(integrations) or [-1]))


def query(db: Session, *, user: User | None = None, boards: set[int] | None = None, kinds: tuple[str, ...] | None = None,
          since: datetime | None = None, words: str = "", before_id: int | None = None, limit: int = 100) -> list[Event]:
    """Lines, newest first. ``user`` filters by what that account may see; ``boards`` by boards."""
    statement = select(Event)
    if user is not None and user.role != Role.admin.value:
        statement = statement.where(Event.kind.not_in(list(ADMIN_ONLY)), _within(_open_boards(db, user), db))
    if boards is not None:
        statement = statement.where(_within(boards, db))
    if kinds:
        statement = statement.where(Event.kind.in_(list(kinds)))
    if since is not None:
        statement = statement.where(Event.at >= since)
    if words.strip():
        needle = f"%{words.strip().lower()}%"
        statement = statement.where(or_(Event.name.ilike(needle), Event.detail.ilike(needle),
                                        Event.before.ilike(needle), Event.after.ilike(needle)))
    if before_id is not None:
        # ⚠️ After the line in the order the page shows, by time and then by number.
        # By number alone a version read at noon about a change from last week
        # came out of order, and paging back skipped lines.
        anchor = db.get(Event, before_id)
        if anchor is not None:
            statement = statement.where(or_(Event.at < anchor.at, and_(Event.at == anchor.at, Event.id < anchor.id)))
    return list(db.scalars(statement.order_by(Event.at.desc(), Event.id.desc()).limit(max(1, min(500, limit)))))


def view(db: Session, rows: list[Event], user: User | None = None) -> list[dict[str, Any]]:
    """Lines as the browser gets them, with where a card line leads when it still can."""
    boards = {board.id: board for board in db.scalars(select(Board).where(Board.id.in_({row.board_id for row in rows if row.board_id} or {-1})))}
    places = {
        widget_id: (board_id, slug)
        for widget_id, board_id, slug in db.execute(
            select(Widget.id, Page.board_id, Page.slug).join(Page, Widget.page_id == Page.id)
            .where(Widget.id.in_({row.widget_id for row in rows if row.widget_id} or {-1}))
        )
    }
    names = {number: name for number, name in db.execute(select(User.id, User.username).where(User.id.in_({row.user_id for row in rows if row.user_id} or {-1})))}
    may_open = None if user is None or user.role == Role.admin.value else _open_boards(db, user)
    out = []
    for row in rows:
        board = boards.get(row.board_id) if row.board_id else None
        line: dict[str, Any] = {
            "id": row.id, "at": row.at.isoformat(), "when": row.at.timestamp(), "kind": row.kind, "level": row.level,
            "name": row.name, "before": row.before, "after": row.after, "detail": row.detail,
            "board": board.name if board is not None else "",
            "user": names.get(row.user_id, "") if row.user_id else "",
        }
        place = places.get(row.widget_id) if row.widget_id else None
        if place is not None and (may_open is None or place[0] in may_open):
            home = db.get(Board, place[0])
            if home is not None:
                line["target"] = {"board": home.slug, "page": place[1], "widget": row.widget_id}
        out.append(line)
    return out


def card_lines(db: Session, widget_id: int, *, kinds: tuple[str, ...], whole: bool, limit: int) -> list[dict[str, Any]]:
    """What the chronicle card shows: the boards of its owner, or only its own board."""
    me = db.get(Widget, widget_id)
    page = db.get(Page, me.page_id) if me is not None else None
    board = db.get(Board, page.board_id) if page is not None else None
    if board is None:
        return []
    boards = _owner_boards(db, board.owner_id, board.id) if whole else {board.id}
    owner = db.get(User, board.owner_id) if board.owner_id is not None else None
    # The card is read once for everybody who sees it, like the attention card:
    # it shows what the owner sees, and nothing only an administrator may.
    shown = tuple(kind for kind in kinds if kind not in ADMIN_ONLY or (owner is not None and owner.role == Role.admin.value))
    rows = query(db, boards=boards, kinds=shown, limit=limit)
    return view(db, rows)


def since_of(at: datetime | None) -> float | None:
    if at is None:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=UTC)).timestamp()
