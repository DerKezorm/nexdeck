"""Pairing a nexcrate connection: nexdeck asks for a key, the owner confirms the code in nexcrate.

The same way nexbeat does it. ``POST /api/v1/pairing`` at nexcrate answers
with a code to show, an id and a secret; the secret stays on this server,
and the browser asks here every few seconds until nexcrate hands the key
over, exactly once. Nothing is stored until the connection is saved: the
key goes into the form, like a key typed in by hand.

⚠️ Administrators only, as creating a connection is. And the address is
checked like any outbound address before anything is sent to it.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

import httpx
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..adapters.base import AdapterError, guard_outbound, outbound_client
from ..deps import AdminUser, error

router = APIRouter(prefix="/api/v1/nexcrate", tags=["integrations"])
logger = logging.getLogger("nexdeck.nexcrate")

#: What nexdeck asks for: reading for every card, operating for the buttons on a stuck download.
SCOPES = ["read", "operate"]
#: Pairings waiting for the owner, by nexdeck's own id. Ten minutes at nexcrate, and gone with a restart.
_waiting: dict[str, dict[str, Any]] = {}
MOST_WAITING = 20


class PairingStart(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    insecure: bool = False


def _forget_old() -> None:
    now = time.time()
    for key in [key for key, entry in _waiting.items() if entry["until"] < now]:
        _waiting.pop(key, None)


def _refused(answer: httpx.Response) -> Any:
    try:
        body = answer.json()
    except ValueError:
        body = {}
    message = body.get("message") if isinstance(body, dict) else None
    return error("nexcrate_refused", str(message or f"nexcrate answered with HTTP {answer.status_code}."), status.HTTP_502_BAD_GATEWAY)


@router.post("/pairing", summary="Ask nexcrate for a key; the owner confirms the code there")
async def start(body: PairingStart, user: AdminUser) -> dict:
    url = body.url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise error("bad_url", "The address starts with http:// or https://.")
    try:
        guard_outbound(url)
    except AdapterError as failure:
        raise error(failure.code, failure.message) from failure
    _forget_old()
    if len(_waiting) >= MOST_WAITING:
        raise error("busy", "Too many pairings are waiting. Wait a few minutes.", status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        async with outbound_client(verify=not body.insecure, timeout=15.0) as client:
            answer = await client.post(f"{url}/api/v1/pairing", json={"app": "nexdeck", "scopes": SCOPES})
    except httpx.HTTPError as failure:
        raise error("unreachable", f"nexcrate could not be reached: {failure.__class__.__name__}.", status.HTTP_502_BAD_GATEWAY) from failure
    if answer.status_code >= 400:
        raise _refused(answer)
    asked = answer.json()
    ours = secrets.token_urlsafe(16)
    _waiting[ours] = {
        "url": url, "insecure": body.insecure, "id": str(asked.get("pairing_id")), "secret": str(asked.get("secret")),
        "until": time.time() + 600,
    }
    logger.info("Pairing with nexcrate at %s started by %s.", url, user.username)
    return {"id": ours, "code": asked.get("code"), "expires_at": asked.get("expires_at"), "poll_seconds": asked.get("poll_seconds") or 2}


@router.post("/pairing/{pairing}", summary="Whether the owner confirmed; the key comes once")
async def poll(pairing: str, user: AdminUser) -> dict:
    """POST, so the answer that carries the key is never kept by a cache on the way."""
    _forget_old()
    entry = _waiting.get(pairing)
    if entry is None:
        return {"state": "expired"}
    try:
        async with outbound_client(verify=not entry["insecure"], timeout=15.0) as client:
            answer = await client.get(f"{entry['url']}/api/v1/pairing/{entry['id']}", headers={"X-Pairing-Secret": entry["secret"]})
    except httpx.HTTPError:
        # A moment without an answer is no reason to give up; the browser asks again.
        return {"state": "pending"}
    if answer.status_code == 404:
        _waiting.pop(pairing, None)
        return {"state": "expired"}
    if answer.status_code >= 400:
        raise _refused(answer)
    body = answer.json()
    state = str(body.get("state") or "pending")
    if state == "confirmed" and body.get("key"):
        _waiting.pop(pairing, None)
        logger.info("nexcrate at %s handed over a key to %s.", entry["url"], user.username)
        return {"state": "confirmed", "key": body["key"], "scopes": body.get("scopes") or []}
    if state in ("denied", "expired", "delivered"):
        _waiting.pop(pairing, None)
        # "delivered" without the key in hand: the answer that carried it was lost. Pair again.
        return {"state": "denied" if state == "denied" else "expired"}
    return {"state": "pending"}
