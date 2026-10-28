"""Short names for app tiles: ``/go/<name>`` opens the tile from the address bar.

A tile answers to a short name of lower-case letters, digits and hyphens. It
is taken from the tile's name until somebody gives it one of its own, which is
kept in ``options["alias"]``; a taken name follows a renamed tile, a given one
stays.

⚠️ Only tiles the person may see. The name is looked up among the boards the
person may open, a wall display only on its own board, so ``/go/<name>`` never
says whether a tile of that name exists on a board somebody else keeps for
himself. For the same reason a name is unique per board only: two boards may
each have their "plex". When the tiles a person may see answer one name with
two different addresses, nexdeck does not guess: it opens its search bar with
the name in it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import App, Board, KioskToken, Page, Role, User, Widget

#: Lower-case letters, digits and hyphens, no hyphen at either end, forty at most.
ALIAS = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
MOST = 40
#: How the four letters a German name is full of are written out instead of
#: losing their dots: a fridge called "K-u-umlaut-hlschrank" becomes
#: "kuehlschrank", not "kuhlschrank". By code point, so the source stays English.
_SPELLED = {chr(0xE4): "ae", chr(0xF6): "oe", chr(0xFC): "ue", chr(0xDF): "ss"}


class AliasRefused(ValueError):
    """A short name that cannot be stored as it was sent; the message says why."""

    def __init__(self, message: str, code: str = "bad_alias") -> None:
        super().__init__(message)
        self.code = code


def derive(name: str) -> str:
    """The short name a tile takes from its name, or ``""`` when nothing usable is left."""
    text = "".join(_SPELLED.get(letter, letter) for letter in str(name or "").lower())
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:MOST].rstrip("-")


def check(raw: Any) -> str:
    """A short name as it was given: empty, or one that keeps to the rule."""
    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str) or not ALIAS.match(raw):
        raise AliasRefused("A short name has lower-case letters, digits and hyphens only, "
                           f"no hyphen at either end, and {MOST} characters at most.")
    return raw


def given(widget: Widget) -> str:
    """The short name somebody gave the tile, if it keeps to the rule (a board file may say anything)."""
    raw = (widget.options or {}).get("alias")
    return raw if isinstance(raw, str) and ALIAS.match(raw) else ""


def alias_of(widget: Widget, app: App | None = None) -> str:
    """The short name the tile answers to."""
    return given(widget) or derive(widget.title or (app.name if app is not None else ""))


def refuse_taken(db: Session, board_id: int, widget_id: int | None, kind: str, options: dict | None) -> None:
    """Two tiles on one board may not answer the same name, when one of them was given it on purpose.

    Two that only took the same name from the same title are left alone: the
    look-up then sees two addresses or one, and acts on that.
    """
    if kind != "core.app":
        return
    wanted = check((options or {}).get("alias"))
    if not wanted:
        return
    for other in db.scalars(
        select(Widget).join(Page, Page.id == Widget.page_id).where(Page.board_id == board_id, Widget.kind == "core.app")
    ):
        if other.id == widget_id:
            continue
        if alias_of(other, _app(db, other)) == wanted:
            raise AliasRefused(f"Another tile on this board already answers to {wanted!r}.", "alias_taken")


def _app(db: Session, widget: Widget) -> App | None:
    from . import apps

    return apps.followed(db, widget)


# ---------------------------------------------------------------------------
# Looking a name up
# ---------------------------------------------------------------------------


def board_ids(db: Session, user: User | None, kiosk: KioskToken | None) -> list[int]:
    """The boards whose tiles a request may look through: the person's, and a display's own one."""
    from ..deps import board_permission

    found: set[int] = set()
    if user is not None:
        if user.role == Role.admin.value:
            found |= set(db.scalars(select(Board.id)))
        else:
            found |= {board.id for board in db.scalars(select(Board)) if board_permission(db, board, user) is not None}
    if kiosk is not None:
        found.add(int(kiosk.board_id))
    return sorted(found)


@dataclass
class Seen:
    """A card a request may see, with where it stands."""

    widget: Widget
    page: Page
    board: Board


def seen_cards(db: Session, user: User | None, kiosk: KioskToken | None) -> list[Seen]:
    """Every card on the boards of ``board_ids``, the person's start board first."""
    numbers = board_ids(db, user, kiosk)
    if not numbers:
        return []
    rows = db.execute(
        select(Widget, Page, Board).join(Page, Page.id == Widget.page_id).join(Board, Board.id == Page.board_id)
        .where(Board.id.in_(numbers)).order_by(Board.position, Board.id, Page.position, Page.id, Widget.id)
    ).all()
    start = user.start_board_id if user is not None else None
    cards = [Seen(widget, page, board) for widget, page, board in rows]
    return sorted(cards, key=lambda one: one.board.id != start)


def opens(db: Session, widget: Widget) -> str:
    """The address a tile opens for this request, as the board would show it; ``""`` if it opens nothing.

    The board's order: the tile's own link, then the address of the app it
    follows for the network of the request (``apps.tile_view``), then the
    address of its connection. ⚠️ The last one is what a tile bound to a
    connection and given no link of its own opens; leaving it out sent such
    a name to the search bar. Only http and https: whatever else stands in a
    link is not something to send a browser to.
    """
    from . import apps
    from .boards import service_link

    _view, app_address = apps.tile_view(db, widget)
    address = widget.link or app_address or service_link(widget)
    parts = urlsplit(address)
    return address if parts.scheme in ("http", "https") and parts.netloc else ""


def find(db: Session, cards: list[Seen], name: str) -> str:
    """Where a short name leads, or ``""`` when it leads nowhere or to two places."""
    name = str(name or "").strip().lower()
    if not ALIAS.match(name):
        return ""
    addresses = {opens(db, one.widget) for one in cards
                 if one.widget.kind == "core.app" and alias_of(one.widget, _app(db, one.widget)) == name}
    addresses.discard("")
    return addresses.pop() if len(addresses) == 1 else ""


def card_named(cards: list[Seen], words: str) -> Seen | None:
    """The first card whose name is exactly these words, ignoring case.

    Not an app tile: a tile is found by its short name, and one that was not
    (two of one name, or a link nexdeck will not open) must not lead to the
    board of whichever came first.
    """
    wanted = str(words or "").strip().casefold()
    if not wanted:
        return None
    return next((one for one in cards
                 if one.widget.kind != "core.app" and (one.widget.title or "").strip().casefold() == wanted), None)


def suggestions(db: Session, cards: list[Seen], words: str, most: int = 8) -> list[tuple[str, str]]:
    """What the address bar offers while somebody types: ``(completion, description)``.

    Tiles by their short name first (a pick opens the tile), then cards by
    their name (a pick opens their board with the search bar). A name counts
    when the words begin it or one of its words.
    """
    wanted = str(words or "").strip().casefold()
    if not wanted:
        return []

    def named(text: str) -> bool:
        # The start of the name or of one of its words: "k" offers "Kitchen clock", not "Docker".
        return f" {wanted}" in f" {text.casefold()}"

    first: list[tuple[str, str]] = []
    then: list[tuple[str, str]] = []
    seen: set[str] = set()
    for one in cards:
        title = (one.widget.title or "").strip()
        if one.widget.kind == "core.app":
            app = _app(db, one.widget)
            alias = alias_of(one.widget, app)
            shown = title or (app.name if app is not None else "")
            if alias and alias not in seen and (alias.startswith(wanted) or named(shown)):
                seen.add(alias)
                first.append((alias, shown))
            continue
        if title and title.casefold() not in seen and named(title):
            seen.add(title.casefold())
            then.append((title, f"{one.board.name} › {one.page.name}"))
    return (first + then)[:most]
