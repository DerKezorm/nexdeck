"""Number keys for app tiles: on the board, 1 to 9 opens a tile as a click on it would.

A key belongs to one tile per board, wherever on the board it stands, so a
key always means the same thing whichever page is open. Two tiles with the
same key would make one of them unreachable without saying which, so the
second one is refused with the name of the first.

The key is an option of the tile (``options["key"]``) and travels with it
into a file and back. The browser does the opening (``lib/appKeys.ts``);
this only keeps the keys apart.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import error
from ..models import App, Page, Widget

#: The keys a tile can have. 0 is left out: on most keyboards it sits after 9, not before 1.
KEYS = tuple("123456789")
#: Only app tiles open something; every other card has nothing a key could do.
KIND = "core.app"


def key_of(options: dict[str, Any] | None) -> str:
    """The key of a tile, or an empty string when it has none."""
    value = str((options or {}).get("key") or "")
    return value if value in KEYS else ""


def check_value(kind: str, options: dict[str, Any] | None) -> None:
    """A key of an app tile is one digit from 1 to 9, or nothing. Other cards have no key to check."""
    raw = (options or {}).get("key")
    if kind != KIND or raw in (None, ""):
        return
    if str(raw) not in KEYS:
        raise error("bad_key", "A key is one digit from 1 to 9, or none.")


def name_of(db: Session, widget: Widget) -> str:
    """What the tile is called on the board: its own name, else the name of the app it follows."""
    if widget.title:
        return widget.title
    try:
        app = db.get(App, int((widget.options or {}).get("app_id") or 0))
    except (TypeError, ValueError):
        app = None
    return app.name if app is not None else "another tile"


def taken(db: Session, board_id: int, *, leaving: set[int] | frozenset[int] = frozenset()) -> dict[str, Widget]:
    """The keys given out on a board, and the tile each opens; ``leaving`` are tiles that do not count."""
    rows = db.scalars(select(Widget).join(Page, Page.id == Widget.page_id).where(Page.board_id == board_id, Widget.kind == KIND))
    return {key_of(row.options): row for row in rows if row.id not in leaving and key_of(row.options)}


def refused(db: Session, key: str, holder: Widget) -> HTTPException:
    """The refusal of a key that is taken, with the key and the tile that has it, so the sheet can say both."""
    name = name_of(db, holder)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail={
        "code": "key_taken",
        "message": f"Key {key} already opens {name} on this board. Each key opens one tile.",
        "key": key,
        "name": name,
    })


def refuse_twice(db: Session, board_id: int, own_id: int | None, kind: str, options: dict[str, Any] | None) -> None:
    """Refuse a key another tile of the board has already."""
    check_value(kind, options)
    key = key_of(options) if kind == KIND else ""
    if not key:
        return
    holder = taken(db, board_id, leaving={own_id} if own_id is not None else frozenset()).get(key)
    if holder is not None:
        raise refused(db, key, holder)


def twice_in_file(pages: list[Any]) -> str:
    """The first key a board file gives to two tiles, or an empty string; a file is one board."""
    seen: set[str] = set()
    for page in pages:
        for widget in (page.get("widgets") or []) if isinstance(page, dict) else []:
            if not isinstance(widget, dict) or widget.get("kind") != KIND or not isinstance(widget.get("options"), dict):
                continue
            key = key_of(widget["options"])
            if key in seen:
                return key
            if key:
                seen.add(key)
    return ""
