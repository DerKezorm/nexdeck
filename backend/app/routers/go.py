"""From the address bar: ``/go/<short name>`` and ``/go?q=...``.

⚠️ These are addresses a browser opens, not calls the app makes, so each
answers with a redirect or a document and never with an error the person
would have to read as JSON. Signed out, ``/go`` goes to the sign-in and comes
back; the address it comes back to is built here and is always nexdeck's own
path. A wall display looks only on its own board.
"""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse, Response

from ..deps import DbSession, kiosk_from_request, optional_user
from ..models import KioskToken, User
from ..services import aliases

router = APIRouter(tags=["go"])

logger = logging.getLogger("nexdeck.go")

#: Longer than any short name and any sensible search.
MOST_WORDS = 200


def _to(location: str) -> RedirectResponse:
    # Never kept: where a name leads depends on who asks and from which network.
    return RedirectResponse(location, status_code=302, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def viewer(request: Request, db: DbSession) -> tuple[User | None, KioskToken | None, bool]:
    """Who asks: an account, a wall display, or both. The third value: an account held at the door.

    ⚠️ Asked by hand rather than as a dependency. An account that owes the
    installation a second factor is refused with a JSON error by
    ``optional_user``, which a browser opening an address would show as text.
    """
    try:
        user = optional_user(request, db)
    except HTTPException:
        return None, None, True
    return user, kiosk_from_request(request, db), False


def _sign_in_first(back: str) -> RedirectResponse:
    return _to("/login?" + urlencode({"next": back}))


def _search_bar(words: str) -> str:
    return "/?" + urlencode({"find": words}) if words else "/"


def _go(request: Request, db: DbSession, words: str, back: str) -> RedirectResponse:
    user, kiosk, held = viewer(request, db)
    if held:
        # The app says what is owed, and offers to set it up.
        return _to("/")
    if user is None and kiosk is None:
        return _sign_in_first(back)
    cards = aliases.seen_cards(db, user, kiosk)
    address = aliases.find(db, cards, words)
    if address:
        return _to(address)
    if user is None:
        # A wall display has no search bar to open.
        return _to("/k")
    card = aliases.card_named(cards, words)
    if card is not None:
        return _to(f"/b/{quote(card.board.slug, safe='')}/{quote(card.page.slug, safe='')}?" + urlencode({"find": words}))
    return _to(_search_bar(words))


@router.get("/go", include_in_schema=False)
def go_search(request: Request, db: DbSession, q: Annotated[str, Query(max_length=MOST_WORDS)] = "") -> Response:
    """What a browser opens for a search with nexdeck: a short name goes to its tile, anything else to the search bar."""
    words = q.strip()
    return _go(request, db, words, "/go?" + urlencode({"q": words}) if words else "/go")


@router.get("/go/{name}", include_in_schema=False)
def go_name(name: Annotated[str, Path(max_length=MOST_WORDS)], request: Request, db: DbSession) -> Response:
    """A tile by its short name."""
    words = name.strip()
    return _go(request, db, words, "/go/" + quote(words, safe=""))
