"""OpenID Connect: discovery, the authorisation URL, the code exchange.

Authorisation code flow with PKCE. The state, nonce and verifier travel in
a short-lived signed cookie, so nothing is kept on the server between the
two legs.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from ..adapters.base import outbound_client
from ..config import get_settings
from ..security import ALGORITHM, _signing_key

COOKIE_NAME = "nexdeck_oidc"
ATTEMPT_MINUTES = 10
_discovery: dict[str, tuple[float, dict[str, Any]]] = {}
#: One key client per address, kept for the life of the process.
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


class OidcError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def discovery(issuer_url: str) -> dict[str, Any]:
    issuer = issuer_url.rstrip("/")
    hit = _discovery.get(issuer)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        async with outbound_client(timeout=10) as client:
            response = await client.get(f"{issuer}/.well-known/openid-configuration")
    except httpx.HTTPError as error:
        raise OidcError("oidc_unreachable", "The identity provider could not be reached.") from error
    if response.status_code != 200:
        raise OidcError("oidc_unreachable", f"The identity provider answered with HTTP {response.status_code}.")
    document = response.json()
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if key not in document:
            raise OidcError("oidc_bad_discovery", f"The discovery document lacks {key}.")
    _discovery[issuer] = (time.monotonic() + 3600, document)
    return document


def new_attempt() -> dict[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return {"state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24), "verifier": verifier, "challenge": challenge}


def pack_state(slug: str, attempt: dict[str, str], purpose: str = "login", user_id: int | None = None) -> str:
    payload = {"slug": slug, "state": attempt["state"], "nonce": attempt["nonce"], "verifier": attempt["verifier"], "purpose": purpose, "user_id": user_id, "exp": int(time.time()) + ATTEMPT_MINUTES * 60}
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def unpack_state(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return jwt.decode(raw, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def authorization_url(document: dict[str, Any], client_id: str, redirect_uri: str, scopes: str, attempt: dict[str, str]) -> str:
    params = {
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": scopes or "openid profile email",
        "state": attempt["state"], "nonce": attempt["nonce"], "code_challenge": attempt["challenge"], "code_challenge_method": "S256",
    }
    return f"{document['authorization_endpoint']}?{urlencode(params)}"


async def exchange(document: dict[str, Any], client_id: str, client_secret: str, redirect_uri: str, code: str, verifier: str) -> dict[str, Any]:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id, "code_verifier": verifier}
    auth = (client_id, client_secret) if client_secret else None
    if not client_secret:
        data["client_id"] = client_id
    try:
        async with outbound_client(timeout=15) as client:
            response = await client.post(document["token_endpoint"], data=data, auth=auth, headers={"Accept": "application/json"})
    except httpx.HTTPError as error:
        raise OidcError("oidc_unreachable", "The identity provider could not be reached for the token.") from error
    if response.status_code != 200:
        raise OidcError("oidc_token_refused", f"The identity provider refused the code (HTTP {response.status_code}).")
    return response.json()


async def claims(document: dict[str, Any], client_id: str, id_token: str, nonce: str, issuer_url: str) -> dict[str, Any]:
    try:
        jwks = jwt.PyJWKClient(document["jwks_uri"], cache_keys=True)
        key = jwks.get_signing_key_from_jwt(id_token)
        payload = jwt.decode(id_token, key.key, algorithms=["RS256", "ES256", "RS384", "RS512", "ES384", "ES512", "PS256"], audience=client_id, options={"verify_iss": False})
    except jwt.PyJWTError as error:
        raise OidcError("oidc_bad_token", f"The ID token could not be verified: {error.__class__.__name__}.") from error
    issued_by = str(payload.get("iss", "")).rstrip("/")
    expected = issuer_url.rstrip("/")
    if issued_by != expected and issued_by != str(document.get("issuer", "")).rstrip("/"):
        raise OidcError("oidc_bad_token", "The ID token was issued by someone else.")
    if payload.get("nonce") != nonce:
        raise OidcError("oidc_bad_token", "The ID token does not belong to this attempt.")
    return payload


async def userinfo(document: dict[str, Any], access_token: str) -> dict[str, Any]:
    endpoint = document.get("userinfo_endpoint")
    if not endpoint or not access_token:
        return {}
    try:
        async with outbound_client(timeout=10) as client:
            response = await client.get(endpoint, headers={"Authorization": f"Bearer {access_token}"})
        return response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}


def redirect_uri(public_url: str, slug: str) -> str:
    settings = get_settings()
    base = (public_url or settings.public_url).rstrip("/")
    if not base:
        raise OidcError("oidc_no_public_url", "The public URL is not set. Set it under Settings first.")
    return f"{base}{settings.url_base}/api/v1/auth/oidc/{slug}/callback"
