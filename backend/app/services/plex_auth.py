"""Sign in with Plex: plex.tv hands out the token, nobody copies it from an XML page.

Plex separates two things: plex.tv answers "who are you" and "which servers
may you use"; the Plex Media Server at home answers "what is in the library".
The sign-in runs over a PIN: nexdeck asks plex.tv for one, the browser sends
the person to Plex, and nexdeck asks plex.tv until a token comes back. The
token then goes into the integration like a typed one, encrypted at rest.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlencode

import httpx

from ..adapters.base import outbound_client
from ..config import get_settings

BASE_URL = "https://plex.tv/api/v2"
AUTH_URL = "https://app.plex.tv/auth"
PRODUCT = "nexdeck"

_client: httpx.AsyncClient | None = None


class PlexTvError(Exception):
    """plex.tv did not play along; the message is meant for the operator."""

    def __init__(self, message: str, code: str = "plex_tv_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def client_identifier() -> str:
    """One stable identifier per installation: Plex lists the sign-in as this device."""
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexdeck-plex:" + secret).hexdigest()[:32]


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": PRODUCT,
        "X-Plex-Client-Identifier": client_identifier(),
        "X-Plex-Device": PRODUCT,
        "X-Plex-Platform": "Web",
    }
    if token:
        headers["X-Plex-Token"] = token
    return headers


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = outbound_client(timeout=15, follow_redirects=True)
    return _client


async def _request(method: str, path: str, *, token: str | None = None, params: dict[str, Any] | None = None) -> Any:
    try:
        response = await _http().request(method, f"{BASE_URL}{path}", headers=_headers(token), params=params)
    except httpx.TimeoutException as error:
        raise PlexTvError("plex.tv did not answer in time.") from error
    except httpx.HTTPError as error:
        raise PlexTvError("plex.tv could not be reached. Does the server have internet access?") from error
    if response.status_code in (401, 403):
        raise PlexTvError("Plex did not accept the sign-in.", code="plex_refused")
    if response.status_code >= 400:
        raise PlexTvError(f"plex.tv answered with HTTP {response.status_code}.")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as error:
        raise PlexTvError("plex.tv answered with something other than JSON.") from error


async def begin_login() -> dict[str, str]:
    """Ask for a PIN and build the address the browser opens."""
    data = await _request("POST", "/pins", params={"strong": "true"})
    pin_id = (data or {}).get("id")
    code = (data or {}).get("code")
    if not pin_id or not code:
        raise PlexTvError("Plex did not hand out a sign-in PIN.")
    query = urlencode({"clientID": client_identifier(), "code": code, "context[device][product]": PRODUCT})
    return {"id": str(pin_id), "code": str(code), "url": f"{AUTH_URL}#?{query}"}


async def poll_login(pin_id: str, code: str) -> str | None:
    """Has the person agreed at Plex yet? ``authToken`` stays null while the window is open."""
    data = await _request("GET", f"/pins/{pin_id}", params={"code": code})
    return (data or {}).get("authToken") or None


async def account_name(token: str) -> str:
    data = await _request("GET", "/user", token=token)
    return str((data or {}).get("username") or (data or {}).get("title") or "")


def _urls(connections: list[dict[str, Any]]) -> list[str]:
    """Every address of a server, local ones first: nexdeck usually sits in the same network."""
    local = [str(c["uri"]) for c in connections if c.get("local") and c.get("uri")]
    remote = [str(c["uri"]) for c in connections if not c.get("local") and c.get("uri")]
    return local + remote


async def servers(token: str) -> list[dict[str, Any]]:
    """The servers this account may use, the account's own first."""
    data = await _request("GET", "/resources", token=token, params={"includeHttps": "1"})
    found: list[dict[str, Any]] = []
    for entry in data or []:
        if "server" not in str(entry.get("provides") or ""):
            continue
        urls = _urls(entry.get("connections") or [])
        found.append({
            "name": str(entry.get("name") or "Plex").strip(),
            "owned": bool(entry.get("owned")),
            "machine_id": str(entry.get("clientIdentifier") or ""),
            "urls": urls,
            # A shared server needs its own access token; the owner's is the account token.
            "access_token": str(entry.get("accessToken") or "") or token,
        })
    found.sort(key=lambda s: (not s["owned"], s["name"].lower()))
    return found
