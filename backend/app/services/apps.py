"""Apps set up once and placed as tiles on any board (issue #37).

An app holds a name, an icon, a line of description and every address it is
reached by, each with a label. A tile follows an app through
``options["app_id"]`` and picks one of its addresses through
``options["address"]``: a label, or ``"auto"`` for the one meant for the
network the browser is in.

⚠️ The address is worked out for each request, not stored on the tile. Who
is at home is a question about the browser, and two browsers looking at the
same board at the same moment may be in two places.
"""

from __future__ import annotations

import ipaddress
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import App, Widget

#: The automatic choice: the home address in the home networks, the other one elsewhere.
AUTO = "auto"
#: More addresses than this is a list of services, not one app reached several ways.
MOST_ADDRESSES = 8

#: The request being answered, so a card can ask where its browser is without
#: every route handing the request down (``RememberRequest`` sets it).
current_request: ContextVar[Request | None] = ContextVar("nexdeck_request", default=None)


class RememberRequest:
    """Keep the request being answered where a card can ask it where its browser is.

    Pure ASGI, inside ``RecordPeer``, so the peer it recorded is there. The
    request is built from the scope, and its ``state`` is the scope's, so the
    answer of ``at_home`` is kept for the rest of the request.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = current_request.set(Request(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            current_request.reset(token)


class AppRefused(ValueError):
    """An app that cannot be stored as it was sent; the message says why."""


def clean_addresses(raw: Any) -> list[dict[str, str]]:
    """The addresses as they are stored: a label and an http(s) URL each, labels unique."""
    if not isinstance(raw, list):
        raise AppRefused("The addresses have to be a list.")
    if not raw:
        raise AppRefused("An app needs at least one address.")
    if len(raw) > MOST_ADDRESSES:
        raise AppRefused(f"At most {MOST_ADDRESSES} addresses per app.")
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise AppRefused("Every address needs a label and a URL.")
        label = str(entry.get("label") or "").strip()[:40]
        url = str(entry.get("url") or "").strip()
        if not label:
            raise AppRefused("Every address needs a label.")
        if label.casefold() == AUTO:
            raise AppRefused("“auto” is the automatic choice and cannot be the label of an address.")
        if label.casefold() in seen:
            raise AppRefused(f"The label {label!r} is used twice.")
        seen.add(label.casefold())
        # ⚠️ Only http and https. The tile is a link that opens in the browser,
        # and javascript: or data: in it would run on nexdeck's page.
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or len(url) > 600:
            raise AppRefused(f"The address of {label!r} has to start with http:// or https://.")
        cleaned.append({"label": label, "url": url})
    return cleaned


def clean_choice(addresses: list[dict[str, str]], label: str) -> str:
    """A label for home or away that names one of the addresses, or nothing."""
    label = str(label or "").strip()
    if not label:
        return ""
    for entry in addresses:
        if entry["label"].casefold() == label.casefold():
            return entry["label"]
    raise AppRefused(f"There is no address called {label!r}.")


def _address(app: App, label: str) -> str:
    for entry in app.addresses or []:
        if entry.get("label") == label:
            return str(entry.get("url") or "")
    return ""


def _first(app: App) -> str:
    entries = app.addresses or []
    return str(entries[0].get("url") or "") if entries else ""


def automatic(app: App) -> bool:
    """Whether the app says which address is for home and which for the road."""
    return bool(app.home or app.away)


def resolve(app: App, choice: str, at_home: bool | None) -> str:
    """The address a tile opens.

    A label opens that address. ``auto`` opens the home address in the home
    networks and the other one everywhere else. Where nexdeck cannot tell, the
    one for the road: an outside address usually works from inside as well,
    an inside one never works from outside.
    """
    choice = str(choice or "")
    if choice and choice != AUTO:
        return _address(app, choice) or _first(app)
    if choice == AUTO or (not choice and automatic(app)):
        if at_home and app.home:
            return _address(app, app.home) or _first(app)
        if app.away:
            return _address(app, app.away) or _first(app)
        if app.home:
            return _address(app, app.home) or _first(app)
    return _first(app)


def check_address(app: App, choice: str) -> str:
    """The address nexdeck checks for reachability.

    nexdeck itself runs at home, so an automatic tile is checked on its home
    address; a tile that opens one address is checked on that one.
    """
    choice = str(choice or "")
    if choice and choice != AUTO:
        return _address(app, choice) or _first(app)
    return (_address(app, app.home) if app.home else "") or _first(app)


def followed(db: Session, widget: Widget) -> App | None:
    """The app a tile follows, if it follows one that still exists."""
    if widget.kind != "core.app":
        return None
    raw = (widget.options or {}).get("app_id")
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        return None
    try:
        number = int(raw)
    except ValueError:
        return None
    return db.get(App, number)


def at_home(db: Session) -> bool | None:
    """Whether the browser of the request being answered is in a home network.

    ``None`` when nexdeck cannot tell: no request (a background job), no home
    networks named, or an address only an untrusted proxy vouches for. The
    answer is kept on the request, so a board of forty tiles asks once.
    """
    request = current_request.get()
    if request is None:
        return None
    cached = getattr(request.state, "nexdeck_at_home", "unset")
    if cached != "unset":
        return cached
    from . import home_network

    answer: bool | None = None
    networks = [ipaddress.ip_network(n, strict=False) for n in home_network.load(db).networks]
    if networks:
        address, _how = home_network.seen_address(request)
        ip = home_network._ip(address) if address else None
        answer = None if ip is None else home_network._inside(ip, networks)
    request.state.nexdeck_at_home = answer
    return answer


def app_view(app: App) -> dict[str, Any]:
    return {
        "id": app.id,
        "name": app.name,
        "icon": app.icon,
        "description": app.description,
        "addresses": list(app.addresses or []),
        "home": app.home,
        "away": app.away,
    }


def tile_view(db: Session, widget: Widget) -> tuple[dict[str, Any] | None, str]:
    """What a tile following an app shows of it, and the address it opens right now."""
    app = followed(db, widget)
    if app is None:
        return None, ""
    choice = str((widget.options or {}).get("address") or "")
    view = {
        "id": app.id,
        "name": app.name,
        "icon": app.icon,
        "description": app.description,
        "address": choice or (AUTO if automatic(app) else ""),
        "addresses": [entry["label"] for entry in app.addresses or []],
        "automatic": automatic(app),
    }
    return view, resolve(app, choice, at_home(db))


def let_go(db: Session, app: App) -> int:
    """Turn every tile that follows ``app`` into a tile of its own, before the app goes.

    ⚠️ A deleted app must not leave empty tiles behind on boards its admin
    never looks at. Each keeps the name, icon and address it showed, as a
    plain tile, and its check keeps running on that address.
    """
    from . import health as health_service

    count = 0
    for widget in db.scalars(select(Widget).where(Widget.kind == "core.app")):
        if followed(db, widget) is not app:
            continue
        options = dict(widget.options or {})
        choice = str(options.pop("address", "") or "")
        options.pop("app_id", None)
        widget.title = widget.title or app.name
        widget.icon = widget.icon or app.icon
        if not widget.link:
            # An automatic tile keeps the address for the road: it works from
            # anywhere, which the one for home does not.
            widget.link = resolve(app, choice, None)
        widget.options = options
        health_service.ensure_check_for_widget(db, widget)
        count += 1
    return count


def by_name(db: Session, name: str) -> App | None:
    return db.scalar(select(App).where(App.name == name))
