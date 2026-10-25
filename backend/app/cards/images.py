"""Where the pictures of a custom card come from, and how the browser is allowed to ask for them.

A picture named by the answers of a service is one of three things: a path on the connection the card reads through,
an address on some other host, or something that is no picture address at all. The first goes through the image route
of the widget with the credentials of the connection, as every picture of a built-in card does (KARTEN-6 T3). The
second goes through the same route without any credentials and with the network rule for addresses a member typed
(KARTEN-6 EC-3). The third becomes a placeholder (EC-7).
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import parse_qs, quote, urlsplit

from ..config import get_settings
from .schema import stays_underneath

#: The path the image route reads as "somewhere else", with the address and its signature in the query.
EXTERNAL = "/_external"
#: The path the image route reads as "a path on the connection", signed the same way: only a path the server itself
#: read out of an answer of the card can be fetched with the credentials of the connection.
CONNECTION = "/_connection"


def _key() -> bytes:
    return hashlib.sha256(b"nexdeck-card-picture:" + get_settings().resolved_secret_key().encode("utf-8")).digest()


def _signature(url: str, scope: str = "") -> str:
    return hmac.new(_key(), f"{scope}|{url}".encode(), hashlib.sha256).hexdigest()[:32]


def reference(link: str | None, base: str = "") -> str:
    """The ``art`` of a row for a picture address the answers named; empty where there is no picture to show.

    ``base`` is the address of the connection: a picture that lives underneath it keeps the connection's credentials.
    """
    if not link:
        return ""
    text = link.strip()
    if base and text.startswith(base.rstrip("/") + "/"):
        text = text[len(base.rstrip("/")):]
    if text.startswith("/") and not text.startswith("//"):
        # ⚠️ Signed with the address of the connection: the route fetches this path with the connection's key, and a
        # viewer must not be able to ask for any path of the service (found in the review of KARTEN-2, 25.10.2026).
        if not stays_underneath(text):
            return ""
        return f"proxy:{CONNECTION}?u={quote(text, safe='')}&s={_signature(text, 'connection:' + base.rstrip('/'))}"
    split = urlsplit(text)
    if split.scheme.lower() not in ("http", "https") or not split.hostname or split.username or split.password:
        return ""
    # ⚠️ Signed: the route fetches this address for whoever asks, so it fetches only addresses this server itself
    # read out of the answers of a card. A person cannot make it fetch a different one.
    return f"proxy:{EXTERNAL}?u={quote(text, safe='')}&s={_signature(text)}"


def external_address(path: str) -> str | None:
    """The address behind an ``EXTERNAL`` path, or ``None`` when it is not one or the signature does not fit."""
    if not path.startswith(EXTERNAL + "?"):
        return None
    query = parse_qs(path[len(EXTERNAL) + 1:])
    address, signature = (query.get("u") or [""])[0], (query.get("s") or [""])[0]
    if not address or not hmac.compare_digest(signature, _signature(address)):
        return None
    return address


def connection_path(path: str, base: str) -> str | None:
    """The path behind a ``CONNECTION`` path of the connection at ``base``, or ``None`` when it is not one or the signature does not fit."""
    if not path.startswith(CONNECTION + "?"):
        return None
    query = parse_qs(path[len(CONNECTION) + 1:])
    found, signature = (query.get("u") or [""])[0], (query.get("s") or [""])[0]
    if not found or not stays_underneath(found) or not hmac.compare_digest(signature, _signature(found, "connection:" + base.rstrip("/"))):
        return None
    return found
