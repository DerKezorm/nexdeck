"""OpenID Connect: discovery, the authorisation URL, the code exchange.

Authorisation code flow with PKCE. The state, nonce and verifier travel in
a short-lived signed cookie. The server keeps one thing between the two legs:
a hash of every state already used, so a callback cannot be played back.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from ..adapters.base import outbound_client
from ..config import get_settings
from ..security import ALGORITHM

COOKIE_NAME = "nexdeck_oidc"
ATTEMPT_MINUTES = 10
_discovery: dict[str, tuple[float, dict[str, Any]]] = {}
#: One key client per address, kept for the life of the process.
_jwks_clients: dict[str, jwt.PyJWKClient] = {}

#: One HTTP client for all three legs, kept for the life of the process.
#:
#: ⚠️ A fresh :class:`httpx.AsyncClient` builds a TLS context and loads the CA
#: bundle, and it does that on the event loop: measured on Windows on
#: 09.09.2026, 1.0 s for one and 11.35 s for eleven in a row. A sign-in walks
#: discovery, the code exchange and userinfo, so it built three, and the
#: server stood still for all three of them while somebody was waiting on a
#: redirect. The three legs differ in timeout and headers, and httpx takes
#: both per request, so nothing about them is lost by sharing the client.
#: Same shape as ``health.http_client`` and ``icons.http_client``.
_client: httpx.AsyncClient | None = None


def http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = outbound_client(timeout=10)
    return _client


async def close_client() -> None:
    """Shutdown: let go of the connections the provider legs hold open."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class OidcError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def forget_discovery(issuer_url: str) -> None:
    """Drop the kept document, so the next sign-in reads the provider afresh."""
    _discovery.pop(issuer_url.rstrip("/"), None)


async def discovery(issuer_url: str) -> dict[str, Any]:
    issuer = issuer_url.rstrip("/")
    hit = _discovery.get(issuer)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        response = await http_client().get(f"{issuer}/.well-known/openid-configuration", timeout=10)
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


#: What an attempt cookie says it is. Checked on the way back in.
ATTEMPT_TYPE = "oidc"


def _attempt_key() -> bytes:
    """A key of its own for the attempt cookie, derived from the secret like the session key.

    ⚠️ Until 0.36.0 the attempt was signed with the session key. Not open then:
    a session needs ``sub`` and ``sid``, which an attempt lacks, and a session
    token has no ``state``. But one change on either side would have made the
    one usable as the other. Two keys, and a ``type`` on top.
    """
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexdeck-oidc-attempt:" + secret).digest()


def pack_state(slug: str, attempt: dict[str, str], purpose: str = "login", user_id: int | None = None) -> str:
    payload = {
        "type": ATTEMPT_TYPE, "slug": slug, "state": attempt["state"], "nonce": attempt["nonce"], "verifier": attempt["verifier"],
        "purpose": purpose, "user_id": user_id, "exp": int(time.time()) + ATTEMPT_MINUTES * 60,
    }
    return jwt.encode(payload, _attempt_key(), algorithm=ALGORITHM)


def unpack_state(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, _attempt_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("type") == ATTEMPT_TYPE else None


#: Hashes of the states already used, each kept until its attempt would have run out anyway.
_used_states: dict[str, float] = {}
_used_lock = threading.Lock()


def consume_state(state: str) -> bool:
    """Mark the state as used. False if it was used before.

    ⚠️ Without this a callback could be repeated with the same cookie and the
    same state as long as the provider still took the code.
    """
    now = time.monotonic()
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    with _used_lock:
        for key in [key for key, until in _used_states.items() if until <= now]:
            del _used_states[key]
        if digest in _used_states:
            return False
        _used_states[digest] = now + ATTEMPT_MINUTES * 60
        return True


def forget_used_states() -> None:
    """For the tests."""
    with _used_lock:
        _used_states.clear()


def normal_issuer(issuer_url: str) -> str:
    """An issuer as it is stored: no spaces around it, no slash at the end."""
    return issuer_url.strip().rstrip("/")


def same_issuer(a: str, b: str) -> bool:
    """Two ways of writing one issuer: authentik hands it out with a slash at the end, the form stores it without.

    A subject means something only at the issuer that handed it out, so a
    provider pointed at another issuer loses its links. A space or a slash is
    not another issuer, and must not cost anybody their link.
    """
    return normal_issuer(a) == normal_issuer(b)


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
        response = await http_client().post(document["token_endpoint"], data=data, auth=auth, headers={"Accept": "application/json"}, timeout=15)
    except httpx.HTTPError as error:
        raise OidcError("oidc_unreachable", "The identity provider could not be reached for the token.") from error
    if response.status_code != 200:
        raise OidcError("oidc_token_refused", f"The identity provider refused the code (HTTP {response.status_code}).")
    return response.json()


def _jwks_client(uri: str) -> jwt.PyJWKClient:
    """The key client for one provider, built once and kept."""
    client = _jwks_clients.get(uri)
    if client is None:
        client = jwt.PyJWKClient(uri, cache_keys=True)
        _jwks_clients[uri] = client
    return client


#: What an ID token may be signed with. **No HS256**: a token signed with the
#: client secret would be checked with the client secret, and a forged ``alg``
#: header is the best known trick against JWT. Nexview refuses it for the
#: same reason.
ALGORITHMS = ["RS256", "ES256", "RS384", "RS512", "ES384", "ES512", "PS256"]

#: Said at the sign-in page and in the log when a provider signs with its
#: client secret or publishes no keys. authentik does both at once when no
#: signing key is chosen for the provider, and before this the only words
#: were "PyJWKSetError" (issue #11).
NO_SIGNING_KEY = (
    "The identity provider signs with its client secret or publishes no signing key. "
    "Choose a signing key for the provider; in authentik that is Signing Key on the provider."
)


async def claims(document: dict[str, Any], client_id: str, id_token: str, nonce: str, issuer_url: str) -> dict[str, Any]:
    try:
        algorithm = str(jwt.get_unverified_header(id_token).get("alg") or "")
    except jwt.PyJWTError as error:
        raise OidcError("oidc_bad_token", f"The ID token could not be read: {error.__class__.__name__}.") from error
    if algorithm.upper().startswith("HS"):
        raise OidcError("oidc_no_signing_key", f"{NO_SIGNING_KEY} The ID token came signed with {algorithm}.")
    try:
        # ⚠️ Two things here, and both were wrong. PyJWKClient fetches with
        # urllib, which blocks: in an async function that holds the whole
        # server for as long as the provider needs, and an unreachable
        # provider holds it for the socket timeout. And the client was built
        # fresh on every sign-in, so ``cache_keys=True`` cached into an object
        # that was thrown away immediately; the key set was fetched every
        # single time.
        key = await asyncio.to_thread(_jwks_client(document["jwks_uri"]).get_signing_key_from_jwt, id_token)
        payload = jwt.decode(id_token, key.key, algorithms=ALGORITHMS, audience=client_id, options={"verify_iss": False})
    except jwt.PyJWKSetError as error:
        # ``{"keys": []}``, or no key pyjwt can use. Not PyJWKClientError: that
        # is also what a key set says when it simply has no key with the
        # token's ``kid``, and that is an ordinary bad token.
        raise OidcError("oidc_no_signing_key", f"{NO_SIGNING_KEY} The key set said: {error}") from error
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
        response = await http_client().get(endpoint, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        return response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}


def redirect_uri(public_url: str, slug: str) -> str:
    """``public_url`` as ``services.public_url`` reads it: the setting, else the environment."""
    base = public_url.rstrip("/")
    if not base:
        raise OidcError("oidc_no_public_url", "The public URL is not set. Set it under Settings first.")
    return f"{base}/api/v1/auth/oidc/{slug}/callback"
