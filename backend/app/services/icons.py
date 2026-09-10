"""Service logos from dashboard-icons and selfh.st, fetched and cached by the server.

The browser never talks to a CDN. Icons are cached on disk for weeks; the
name indexes for the search are cached for a day.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from ..adapters.base import outbound_client
from ..config import get_settings

logger = logging.getLogger("nexdeck.icons")

SOURCES = (
    ("dashboard-icons", "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/{ext}/{name}.{ext}", "https://api.github.com/repos/homarr-labs/dashboard-icons/git/trees/main?recursive=1"),
    ("selfhst", "https://cdn.jsdelivr.net/gh/selfhst/icons/{ext}/{name}.{ext}", "https://api.github.com/repos/selfhst/icons/git/trees/main?recursive=1"),
)
#: Logos that ship with nexdeck: the nexapps family, which no collection carries.
BUNDLED = Path(__file__).resolve().parent.parent / "bundled_icons"
SAFE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
NEGATIVE_SECONDS = 3600
INDEX_SECONDS = 86400

_negative: dict[str, float] = {}
_index: dict[str, tuple[float, list[str]]] = {}


#: One client for the whole process.
#:
#: ⚠️ A fresh :class:`httpx.AsyncClient` builds a TLS context and loads the
#: CA bundle, and it does that on the event loop. Measured on Windows on
#: 09.09.2026: 1.0 s for one, 11.35 s for eleven in a row. This proxy built
#: one per icon, and on the first load of a fresh installation nothing is
#: cached and the demo board asks for eleven logos at once, so the server had
#: no turn for anything else for about eleven seconds. What waited behind it
#: was everything: the live stream took 5.4 s to open, and the board answer
#: that carries the cards' first data came back after 14.3 s, against an
#: end to end test that waits 15 s for a card to fill in. The reachability
#: checks learned this first, in ``health.http_client``; this was the last
#: place still paying it.
_client: httpx.AsyncClient | None = None


def http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = outbound_client(timeout=10, follow_redirects=True, headers={"User-Agent": "nexdeck"})
    return _client


async def close_client() -> None:
    """Shutdown: let go of the connections the proxy holds open."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _cache_dir() -> Path:
    directory = get_settings().cache_dir / "icons"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def valid_name(name: str) -> bool:
    return bool(SAFE.match(name))


async def fetch_icon(name: str, ext: str) -> tuple[bytes, str] | None:
    """Return ``(bytes, content_type)`` or None when no source has the icon."""
    if not valid_name(name) or ext not in ("svg", "png", "webp"):
        return None
    shipped = BUNDLED / f"{name}.svg"
    if ext == "svg" and shipped.is_file():
        return shipped.read_bytes(), _content_type("svg")
    key = f"{name}.{ext}"
    cached = _cache_dir() / key
    max_age = get_settings().icon_cache_days * 86400
    if cached.exists() and time.time() - cached.stat().st_mtime < max_age:
        return cached.read_bytes(), _content_type(ext)
    if _negative.get(key, 0) > time.monotonic():
        return None
    client = http_client()
    for _source, pattern, _tree in SOURCES:
        url = pattern.format(ext=ext, name=name)
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            continue
        if response.status_code == 200 and response.content:
            cached.write_bytes(response.content)
            return response.content, _content_type(ext)
    _remember_miss(key)
    return None


#: How many names the "we looked and there is none" list may hold.
#:
#: ⚠️ It had no ceiling and no sweep, and it can be filled without signing in:
#: the icon proxy answers before any session is required. Every made-up name
#: left an entry behind for an hour, and nothing ever walked the list.
NEGATIVE_LIMIT = 2000


def _remember_miss(key: str) -> None:
    now = time.monotonic()
    _negative[key] = now + NEGATIVE_SECONDS
    if len(_negative) <= NEGATIVE_LIMIT:
        return
    for name in [name for name, until in _negative.items() if until <= now]:
        _negative.pop(name, None)
    # Still too many: drop the ones that expire first, so what stays is what
    # was asked for most recently.
    while len(_negative) > NEGATIVE_LIMIT:
        _negative.pop(min(_negative, key=lambda name: _negative[name]), None)


def _content_type(ext: str) -> str:
    return {"svg": "image/svg+xml", "png": "image/png", "webp": "image/webp"}[ext]


async def _names(source: str, tree_url: str) -> list[str]:
    hit = _index.get(source)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    file = _cache_dir() / f"index-{source}.json"
    if file.exists() and time.time() - file.stat().st_mtime < INDEX_SECONDS:
        names = json.loads(file.read_text(encoding="utf-8"))
        _index[source] = (time.monotonic() + INDEX_SECONDS, names)
        return names
    names: list[str] = []
    try:
        response = await http_client().get(tree_url, timeout=20, headers={"Accept": "application/vnd.github+json"})
        if response.status_code == 200:
            for entry in response.json().get("tree", []):
                path = entry.get("path", "")
                if path.startswith("svg/") and path.endswith(".svg"):
                    names.append(path[4:-4])
    except (httpx.HTTPError, ValueError) as error:
        logger.info("Icon index %s unavailable: %s", source, error.__class__.__name__)
    if names:
        file.write_text(json.dumps(names), encoding="utf-8")
    _index[source] = (time.monotonic() + (INDEX_SECONDS if names else 300), names)
    return names


async def all_names() -> list[dict[str, str]]:
    """Every logo name of both collections, sorted, each once: the picker browses this."""
    results: list[dict[str, str]] = [{"name": name, "source": "bundled"} for name in bundled_names()]
    seen: set[str] = {entry["name"] for entry in results}
    for source, _pattern, tree_url in SOURCES:
        for name in await _names(source, tree_url):
            if name not in seen:
                seen.add(name)
                results.append({"name": name, "source": source})
    results.sort(key=lambda entry: entry["name"])
    return results


def bundled_names() -> list[str]:
    return sorted(path.stem for path in BUNDLED.glob("*.svg")) if BUNDLED.is_dir() else []


async def search(query: str, limit: int = 30) -> list[dict[str, str]]:
    query = query.lower().strip()
    if not query:
        return []
    results: list[dict[str, str]] = [{"name": name, "source": "bundled"} for name in bundled_names() if query in name]
    seen: set[str] = {entry["name"] for entry in results}
    for source, _pattern, tree_url in SOURCES:
        for name in await _names(source, tree_url):
            if query in name and name not in seen:
                seen.add(name)
                results.append({"name": name, "source": source})
    results.sort(key=lambda r: (not r["name"].startswith(query), len(r["name"])))
    return results[:limit]


def guess_from_image(image: str) -> str:
    """``lscr.io/linuxserver/radarr:latest`` -> ``radarr``."""
    name = image.split("@")[0].split(":")[0].rsplit("/", 1)[-1].lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    return name.strip("-")
