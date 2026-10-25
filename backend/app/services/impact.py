"""What a button is about to hit, said before it is pressed (roadmap M3).

"Restart plex" ends three streams; "pause" holds five downloads; a scene
switches four lights. The card that offers the button rarely knows: the
streams stand on the media server's card, the container on Docker's. This
module puts the two together from what the cards already hold, so it asks
no service anything new, except Home Assistant for the entities a scene
switches (``Adapter.impact``).

Facts, not sentences: each is ``{"fact": ..., ...}`` and the browser words it
in the reader's language.

* ``up``: how long the container has been running, in Docker's own words.
* ``streams``: who is watching on a media server whose name the container or
  machine carries.
* ``downloads``: how many downloads are running in a download program the
  button holds, or whose name the container carries.
* ``devices`` and ``last_run``: from the adapter itself (Home Assistant).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from ..adapters import split_widget_kind
from ..db import db_session
from ..models import Integration, Widget
from .state import live

logger = logging.getLogger("nexdeck.impact")

MEDIA = ("plex", "jellyfin", "emby")
DOWNLOADS = ("qbittorrent", "sabnzbd", "transmission", "deluge", "nzbget", "rtorrent")
#: Buttons that stop or interrupt what runs inside; starting or scanning interrupts nothing.
INTERRUPTING = {"stop", "restart", "pause", "reboot", "shutdown", "kill"}


def _item_for(data: Any, params: dict[str, Any]) -> dict[str, Any] | None:
    """The row of the card a button sits on, found by the parameters it carries."""
    if data is None:
        return None
    wanted = {str(value) for value in params.values() if isinstance(value, (str, int))}
    for item in data.items:
        if not isinstance(item, dict):
            continue
        for entry in item.get("actions") or []:
            fixed = entry.get("params") if isinstance(entry, dict) else getattr(entry, "params", {})
            if fixed and dict(fixed) == dict(params):
                return item
        if wanted & {str(item.get("id") or ""), str(item.get("title") or "")}:
            return item
    return None


def _cards_of(kinds: tuple[str, ...]) -> list[tuple[int, str, str]]:
    """``(widget id, adapter kind, integration name)`` of every card on a connection of these kinds."""
    with db_session() as db:
        return [
            (widget_id, kind.split(".")[0], name or "")
            for widget_id, kind, name in db.execute(
                select(Widget.id, Widget.kind, Integration.name).outerjoin(Integration, Widget.integration_id == Integration.id)
            )
            if kind.split(".")[0] in kinds
        ]


def streams(named: str) -> dict[str, Any] | None:
    """Who is watching on the media server this name points at ("plex", "jellyfin-server")."""
    lower = named.lower()
    kinds = tuple(kind for kind in MEDIA if kind in lower)
    if not kinds:
        return None
    titles: list[str] = []
    for widget_id, _kind, _name in _cards_of(kinds):
        data = live.get(widget_id)
        if data is None or data.error:
            continue
        for item in data.items:
            if isinstance(item, dict) and item.get("progress") is not None and item.get("title"):
                # Who is watching comes first in the line under the title; the
                # room and the quality after it are too much for a warning.
                who = str(item.get("subtitle") or "").split(" · ")[0]
                titles.append(" · ".join(part for part in (str(item["title"]), who) if part))
    unique = list(dict.fromkeys(titles))
    return {"fact": "streams", "count": len(unique), "names": unique[:6]} if unique else None


def downloads(named: str = "", widget_id: int | None = None) -> dict[str, Any] | None:
    """Running downloads of the program this name points at, or of the card the button sits on."""
    sources: list[int] = []
    if widget_id is not None:
        sources.append(widget_id)
    lower = named.lower()
    kinds = tuple(kind for kind in DOWNLOADS if kind in lower)
    if kinds:
        sources.extend(number for number, _kind, _name in _cards_of(kinds))
    running = set()
    for number in sources:
        data = live.get(number)
        if data is None or data.error:
            continue
        for item in data.items:
            if isinstance(item, dict) and item.get("progress") is not None and item.get("status") == "ok":
                running.add(str(item.get("id") or item.get("title")))
    return {"fact": "downloads", "count": len(running)} if running else None


async def facts(widget_id: int, action_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything known about what this button hits. Empty when nothing is known."""
    with db_session() as db:
        widget = db.get(Widget, widget_id)
        if widget is None:
            return []
        kind = widget.kind
        integration_id = widget.integration_id
        # A connection in the demo points nowhere; its own preview would ask a service that is not there.
        from .collector import collector

        demo = collector._demo_active(widget.integration)
    adapter_kind = kind.split(".")[0]
    data = live.get(widget_id)
    item = _item_for(data, params)
    found: list[dict[str, Any] | None] = []
    interrupting = action_id in INTERRUPTING
    if adapter_kind in ("docker", "proxmox", "portainer", "dockhand", "komodo", "unraid") and item is not None and interrupting:
        name = str(item.get("title") or "")
        # Docker's own words ("Up 3 days"); Proxmox puts the guest's number there.
        if str(item.get("subtitle") or "").startswith("Up "):
            found.append({"fact": "up", "text": str(item["subtitle"])})
        found += [streams(name), downloads(named=name)]
    elif adapter_kind in DOWNLOADS and interrupting:
        found.append(downloads(widget_id=widget_id))
    try:
        adapter, widget_kind = split_widget_kind(kind)
        own: list[dict[str, Any]] = []
        if integration_id is not None and not demo:
            _adapter, config, ctx = await collector.resolve_integration(integration_id)
            own = await adapter.impact(widget_kind, action_id, params, config, ctx)
    except Exception:  # noqa: BLE001 - a preview that fails must not keep the button from working
        logger.exception("The impact of %s on widget %s could not be worked out.", action_id, widget_id)
        own = []
    return [fact for fact in [*found, *own] if fact]
