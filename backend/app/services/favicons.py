"""A card's logo from the service itself, when no collection has one.

An app tile or a card whose name no logo collection knows showed a grey box.
Most services carry their own logo: a ``<link rel="icon">`` or an Apple touch
icon in the head of their start page, or ``/favicon.ico``. The server reads it
from the address the card already opens and keeps it with the other logos.

⚠️ This fetches from an address somebody typed, from inside the house. So it
goes only through ``outbound_client`` with the member rule on every hop
(loopback and link-local barred, as for a notification channel), follows a
redirect only while it stays on the same host and port (``same_place``), and
never fetches a logo from any other host than the page's own, whatever the
page names. What comes back must be a picture of a known kind under a size
limit, read in pieces so a large answer is never held whole. An SVG is a
document that can run script: it is checked like an uploaded one and refused
if anything in it could, and served in a sandbox on top.
"""

from __future__ import annotations

import hashlib
import logging
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from ..adapters.base import AdapterError, guard_member_target, outbound_client, same_place
from ..config import get_settings
from . import icons

logger = logging.getLogger("nexdeck.favicons")

#: Enough for any head of a page; a start page larger than this is read only that far.
PAGE_LIMIT = 512 * 1024
#: A logo larger than this is not a logo.
ICON_LIMIT = 256 * 1024
#: Hops of a redirect, all on the same place.
HOPS = 4
#: The kinds of picture taken, by their first bytes. An SVG is checked apart.
MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
EXTENSIONS = {"image/png": "png", "image/x-icon": "ico", "image/gif": "gif", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg"}
TYPES = {ext: kind for kind, ext in EXTENSIONS.items()}

_client: httpx.AsyncClient | None = None


def http_client() -> httpx.AsyncClient:
    """One client for the process, without following redirects: those are followed here, hop by hop."""
    global _client
    if _client is None or _client.is_closed:
        _client = outbound_client(member=True, timeout=8, follow_redirects=False, headers={"User-Agent": "nexdeck"})
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def origin_of(address: str) -> str:
    """``scheme://host:port`` of an address, or an empty string for one nexdeck does not fetch from."""
    split = urlsplit(address.strip())
    if split.scheme not in ("http", "https") or not split.hostname:
        return ""
    port = f":{split.port}" if split.port else ""
    host = f"[{split.hostname}]" if ":" in split.hostname else split.hostname
    return f"{split.scheme}://{host.lower()}{port}"


class _Links(HTMLParser):
    """The icons a page names in its head, and nothing after the head."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[int, str]] = []
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.done:
            return
        if tag == "body":
            self.done = True
            return
        if tag != "link":
            return
        values = {name.lower(): (value or "") for name, value in attrs}
        rel = set(values.get("rel", "").lower().split())
        href = values.get("href", "").strip()
        # A mask icon is one colour on nothing, drawn to be tinted by Safari: not a logo.
        if not href or "mask-icon" in rel or not rel & {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}:
            return
        self.found.append((_rank(rel, values.get("sizes", ""), values.get("type", ""), href), href))

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.done = True


def _rank(rel: set[str], sizes: str, kind: str, href: str) -> int:
    """Higher first: a large picture reads best on a big tile and is shrunk cleanly for a small one."""
    if rel & {"apple-touch-icon", "apple-touch-icon-precomposed"}:
        return 1000
    if "svg" in kind.lower() or href.lower().split("?")[0].endswith(".svg"):
        return 900
    largest = 0
    for size in sizes.lower().split():
        width, _, _height = size.partition("x")
        if width.isdigit():
            largest = max(largest, int(width))
    return min(largest, 800) or 16


def candidates(page: str, base: str) -> list[str]:
    """Where the page says its logo is, best first, only on its own place, with ``/favicon.ico`` last."""
    parser = _Links()
    try:
        parser.feed(page)
    except Exception:  # noqa: BLE001 - a page that does not parse names no logo, it does not fail the card
        logger.debug("The start page of %s could not be read as HTML.", base)
    start = httpx.URL(base)
    seen: list[str] = []
    for _rank_value, href in sorted(parser.found, key=lambda one: -one[0]):
        url = urljoin(base + "/", href)
        try:
            target = httpx.URL(url)
        except httpx.InvalidURL:
            continue
        # ⚠️ Only this host: a page that names a logo elsewhere does not make nexdeck fetch from there.
        if target.scheme in ("http", "https") and same_place(start, target) and url not in seen:
            seen.append(url)
    fallback = urljoin(base + "/", "/favicon.ico")
    if fallback not in seen:
        seen.append(fallback)
    return seen


async def _get(url: str, limit: int, verify_place: str) -> tuple[bytes, str] | None:
    """The body of an address, following redirects only on the same place, read up to ``limit``."""
    start = httpx.URL(verify_place)
    current = url
    client = http_client()
    for _hop in range(HOPS):
        try:
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    following = urljoin(current, response.headers.get("location", ""))
                    if not following or not same_place(start, httpx.URL(following)):
                        return None
                    current = following
                    continue
                if response.status_code != 200:
                    return None
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > limit:
                    return None
                body = bytearray()
                async for piece in response.aiter_bytes():
                    body.extend(piece)
                    if len(body) > limit:
                        return None
                return bytes(body), response.headers.get("content-type", "").split(";")[0].strip().lower()
        except (httpx.HTTPError, AdapterError, ValueError):
            return None
    return None


def picture(data: bytes, declared: str) -> str:
    """The kind of picture these bytes are, or an empty string for anything that is not one nexdeck serves."""
    for magic, kind in MAGIC:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:1024].lstrip().lower()
    if declared == "image/svg+xml" or head.startswith((b"<svg", b"<?xml")):
        from ..routers.assets import unsafe_svg
        from ..routers.widgets import TITLE_WORDS

        # The words of a title are left out of the check, as for a service's pictures (``widget_image``).
        if b"<svg" in data[:4096].lower() and not unsafe_svg(TITLE_WORDS.sub(b"<title></title>", data)):
            return "image/svg+xml"
    return ""


def _cache_path(origin: str, ext: str) -> Path:
    directory = icons._cache_dir() / "sites"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{hashlib.sha256(origin.encode()).hexdigest()[:32]}.{ext}"


def _cached(origin: str) -> tuple[bytes, str] | None:
    max_age = get_settings().icon_cache_days * 86400
    for ext, kind in TYPES.items():
        path = _cache_path(origin, ext)
        if path.exists() and time.time() - path.stat().st_mtime < max_age:
            return path.read_bytes(), kind
    return None


async def favicon(address: str) -> tuple[bytes, str] | None:
    """The logo of the service at ``address``, from the cache or from the service; None when it has none."""
    origin = origin_of(address)
    if not origin:
        return None
    try:
        guard_member_target(origin)
    except AdapterError:
        return None
    hit = _cached(origin)
    if hit is not None:
        return hit
    key = f"site:{origin}"
    if icons._negative.get(key, 0) > time.monotonic():
        return None
    page = await _get(origin + "/", PAGE_LIMIT, origin)
    text = page[0].decode("utf-8", "replace") if page is not None and "html" in (page[1] or "text/html") else ""
    for url in candidates(text, origin):
        got = await _get(url, ICON_LIMIT, origin)
        if got is None:
            continue
        kind = picture(*got)
        if not kind:
            continue
        _cache_path(origin, EXTENSIONS[kind]).write_bytes(got[0])
        logger.info("Took the logo of %s from %s.", origin, urlsplit(url).path or "/")
        return got[0], kind
    icons._remember_miss(key)
    return None
