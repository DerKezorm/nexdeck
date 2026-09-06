"""The search bar that leaves the house.

nexdeck's own bar finds boards, cards and settings. This is the other half:
a handful of targets a typed word can be handed to, on the web or to a service
that is already connected. Homarr, Glance and Dashy all do it, and it is the
one thing the bar was missing.

A target is a name and an address with ``{query}`` in it. The prefix is what
makes it quick: ``!y cats`` goes straight to YouTube. Everything is stored in
one setting, and every signed-in person may read it, because the bar needs it.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSessionType

from ..models import Integration, Setting

KEY = "search"
#: More than this and the bar stops being quick.
MAX_TARGETS = 20
QUERY = "{query}"
PREFIX = re.compile(r"^[a-z0-9]{1,6}$")

#: What a fresh installation searches with. The first one is the default.
DEFAULTS: list[dict[str, Any]] = [
    {"name": "DuckDuckGo", "url": "https://duckduckgo.com/?q={query}", "prefix": "d", "icon": "duckduckgo"},
    {"name": "Wikipedia", "url": "https://en.wikipedia.org/w/index.php?search={query}", "prefix": "w", "icon": "wikipedia"},
    {"name": "YouTube", "url": "https://www.youtube.com/results?search_query={query}", "prefix": "y", "icon": "youtube"},
    {"name": "GitHub", "url": "https://github.com/search?q={query}", "prefix": "gh", "icon": "github"},
]

#: How a connected service is searched. One entry per adapter that has a search
#: page worth opening; everything else is left alone on purpose.
FROM_INTEGRATIONS: dict[str, tuple[str, str]] = {
    "radarr": ("{url}/add/new?term={query}", "r"),
    "sonarr": ("{url}/add/new?term={query}", "s"),
    "lidarr": ("{url}/add/new?term={query}", "l"),
    "readarr": ("{url}/add/new?term={query}", "b"),
    "prowlarr": ("{url}/search?query={query}", "pr"),
    "seerr": ("{url}/search?query={query}", "q"),
    "overseerr": ("{url}/search?query={query}", "ov"),
    "jellyseerr": ("{url}/search?query={query}", "js"),
    "jellyfin": ("{url}/web/#/search.html?query={query}", "j"),
    "emby": ("{url}/web/index.html#!/search?query={query}", "em"),
    "plex": ("{url}/web/index.html#!/search?query={query}", "p"),
    "immich": ("{url}/search?q={query}", "im"),
    "paperless": ("{url}/documents?query={query}", "pa"),
    "komga": ("{url}/search?q={query}", "ko"),
    "kavita": ("{url}/search?query={query}", "ka"),
    "audiobookshelf": ("{url}/search/{query}", "ab"),
    "navidrome": ("{url}/app/#/search?q={query}", "nd"),
    "nextcloud": ("{url}/index.php/search/providers?term={query}", "nc"),
}


class SearchError(Exception):
    def __init__(self, message: str, code: str = "bad_search") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def stored(db: DbSessionType) -> dict[str, Any]:
    row = db.get(Setting, KEY)
    if row is None:
        return {"enabled": True, "targets": [dict(entry) for entry in DEFAULTS]}
    value = dict(row.value or {})
    return {
        "enabled": bool(value.get("enabled", True)),
        "targets": [dict(entry) for entry in value.get("targets") or []],
    }


def _clean(entry: dict[str, Any]) -> dict[str, Any]:
    name = str(entry.get("name") or "").strip()[:40]
    url = str(entry.get("url") or "").strip()
    prefix = str(entry.get("prefix") or "").strip().lower()[:6]
    if not name:
        raise SearchError("Every search target needs a name.", "missing_name")
    if not url.lower().startswith(("http://", "https://")):
        raise SearchError(f"The address of {name} has to start with http:// or https://.", "bad_url")
    if QUERY not in url:
        raise SearchError(f"The address of {name} has no {QUERY} in it.", "missing_query")
    if prefix and not PREFIX.match(prefix):
        raise SearchError(f"The shortcut of {name} may only be letters and digits.", "bad_prefix")
    return {"name": name, "url": url[:400], "prefix": prefix, "icon": str(entry.get("icon") or "").strip()[:80]}


def save(db: DbSessionType, incoming: dict[str, Any]) -> dict[str, Any]:
    targets = [_clean(entry) for entry in (incoming.get("targets") or [])[:MAX_TARGETS]]
    seen: set[str] = set()
    for target in targets:
        if target["prefix"] and target["prefix"] in seen:
            raise SearchError(f"The shortcut {target['prefix']} is used twice.", "duplicate_prefix")
        seen.add(target["prefix"])
    value = {"enabled": bool(incoming.get("enabled", True)), "targets": targets}
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()
    return stored(db)


def suggestions(db: DbSessionType) -> list[dict[str, Any]]:
    """Targets built out of the services that are already connected."""
    found: list[dict[str, Any]] = []
    taken: set[str] = set()
    rows = db.scalars(select(Integration).where(Integration.enabled.is_(True))).all()
    for integration in rows:
        recipe = FROM_INTEGRATIONS.get(integration.kind)
        if recipe is None or integration.demo:
            continue
        address = str((integration.config or {}).get("url") or "").strip().rstrip("/")
        if not address.lower().startswith(("http://", "https://")):
            continue
        template, prefix = recipe
        while prefix in taken:
            prefix += "x"
        taken.add(prefix)
        found.append({
            "name": integration.name,
            "url": template.replace("{url}", address),
            "prefix": prefix,
            "icon": integration.kind,
        })
    return found


def build(target: dict[str, Any], query: str) -> str:
    """The address to open, with the words put in safely."""
    return str(target.get("url") or "").replace(QUERY, quote(query.strip(), safe=""))
