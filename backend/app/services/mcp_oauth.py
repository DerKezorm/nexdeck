"""Connectors: AI programs that sign in with OAuth instead of being handed a key.

A program finds its way from the 401 of ``POST /api/mcp``: the header names
the protected resource metadata (RFC 9728), that names nexdeck as its own
authorization server (RFC 8414), the program registers itself (RFC 7591) and
sends its person to the consent page ``/connect`` with PKCE (S256, nothing
else). The account signs in as always, picks the level and the boards, and
the program trades the code it is handed for tokens, once.

What comes out is an MCP key of the kind ``oauth`` (``McpKey``), in the same
list as the keys made by hand, with the same walls: it acts as its account,
never above the administrator's ceiling, with rights per tool. Its access
token (``ndo_``) runs out after ``ACCESS_HOURS``; the refresh token (``ndr_``)
is good for ``REFRESH_DAYS`` and is used up by every refresh, which leaves
the next one in the same chain. A used one brought again means two hold a
copy: the whole chain ends, key included.

Only SHA-256 of codes and tokens is stored. Programs are public clients:
there is no secret a program could keep from its user. Return addresses only
over HTTPS, or plain HTTP to ``localhost``/``127.0.0.1``. Nothing here works
unless MCP is on and connectors are allowed; switching either off ends every
connector at once (``end_all``).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models import McpKey, McpOAuthClient, McpOAuthCode, McpOAuthRefresh, Role, User, utcnow
from ..security import hash_token, new_opaque_token
from . import mcp
from .mcp import McpError

logger = logging.getLogger("nexdeck.mcp")

ACCESS_PREFIX = "ndo"
REFRESH_PREFIX = "ndr"
CODE_PREFIX = "ndc"
CODE_MINUTES = 10
ACCESS_HOURS = 1
REFRESH_DAYS = 30
#: Registered programs kept at most; the ones used longest ago make room.
MAX_CLIENTS = 500
#: Registrations per minute for the whole server: registering needs no account.
REGISTER_PER_MINUTE = 30
#: Registrations one sender may make in an hour, so one sender cannot use up the server's minute again and again.
REGISTER_PER_SENDER = 10
#: Plain HTTP is allowed to these hosts only: the program runs on the person's own machine.
LOOPBACK = ("localhost", "127.0.0.1")
#: The only scope there is; a key's reach is its level and its boards, chosen on the consent page.
SCOPE = "mcp"


class OAuthError(Exception):
    """An answer in OAuth's own shape (``error``, ``error_description``), for the program, not for a person."""

    def __init__(self, code: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.code = code
        self.description = description
        self.status = status


def is_open(db: Session) -> bool:
    value = mcp.stored(db)
    return value["allowed"] and value["oauth_allowed"]


def resource_of(base: str) -> str:
    """The protected resource: the MCP endpoint itself."""
    return f"{base}/api/mcp"


def _normal(uri: str) -> tuple[str, str, str] | None:
    try:
        parts = urlsplit(uri.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment or parts.username:
        return None
    if port is None or (parts.scheme, port) in (("http", 80), ("https", 443)):
        host = parts.hostname
    else:
        host = f"{parts.hostname}:{port}"
    return parts.scheme, host, parts.path.rstrip("/")


def same_resource(given: str, expected: str) -> bool:
    """RFC 8707: the program names what it wants a token for, and it has to be this endpoint.

    Scheme and host in any case, a default port written or not, a slash at the
    end or not: all the same address. Anything else is somebody else's resource.
    """
    mine = _normal(expected)
    return mine is not None and _normal(given) == mine


def valid_redirect(uri: Any) -> bool:
    """HTTPS anywhere, or plain HTTP to the own machine on any port; never a fragment, never a user in the address."""
    if not isinstance(uri, str) or not uri or len(uri) > 2048 or any(ord(char) < 33 or ord(char) == 127 for char in uri):
        return False
    try:
        # urlsplit throws on a broken bracket, .port on a port that is not a number.
        parts = urlsplit(uri)
        hostname, _port = parts.hostname, parts.port
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not hostname:
        return False
    # A plain name or address: no "*.example.com", no brackets, nothing a later reader takes differently.
    if not re.fullmatch(r"[a-z0-9.-]+", hostname):
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and hostname in LOOPBACK


def verifier_fits(verifier: str, challenge: str) -> bool:
    """PKCE S256: the program that brings the code is the one that asked for it."""
    if not 43 <= len(verifier) <= 128 or not re.fullmatch(r"[A-Za-z0-9._~-]+", verifier):
        return False
    made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return secrets.compare_digest(made, challenge)


def _check_challenge(challenge: str, method: str) -> None:
    if method != "S256" or not 43 <= len(challenge) <= 128 or not re.fullmatch(r"[A-Za-z0-9._~-]+", challenge):
        raise McpError("oauth_pkce", "The program must use PKCE with S256.", 400)


# -- registering ------------------------------------------------------------------------------

_brake_lock = threading.Lock()
_registered: deque[float] = deque()
_by_sender: dict[str, deque[float]] = defaultdict(deque)


def may_register(sender: str, now: float | None = None) -> bool:
    """True while the sender stays under its hour and the server under its minute; counts this one."""
    now = time.monotonic() if now is None else now
    with _brake_lock:
        while _registered and now - _registered[0] >= 60:
            _registered.popleft()
        mine = _by_sender[sender]
        while mine and now - mine[0] >= 3600:
            mine.popleft()
        for other in [name for name, seen in _by_sender.items() if not seen and name != sender]:
            # No entry left behind for every address that ever registered.
            del _by_sender[other]
        if len(mine) >= REGISTER_PER_SENDER or len(_registered) >= REGISTER_PER_MINUTE:
            return False
        mine.append(now)
        _registered.append(now)
        return True


def forget_registrations() -> None:
    with _brake_lock:
        _registered.clear()
        _by_sender.clear()


def register(db: Session, body: Any, sender: str) -> McpOAuthClient:
    if not isinstance(body, dict):
        raise OAuthError("invalid_client_metadata", "The body must be a JSON object.")
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= 10 or not all(valid_redirect(uri) for uri in uris):
        raise OAuthError("invalid_redirect_uri", "Give 1 to 10 redirect addresses: https, or http to localhost or 127.0.0.1.")
    if body.get("token_endpoint_auth_method", "none") != "none":
        raise OAuthError("invalid_client_metadata", "Only public clients with PKCE sign in here (token_endpoint_auth_method none).")
    grants = body.get("grant_types", ["authorization_code"])
    if not isinstance(grants, list) or "authorization_code" not in grants:
        raise OAuthError("invalid_client_metadata", "The program must use the grant type authorization_code.")
    if not may_register(sender):
        raise OAuthError("temporarily_unavailable", "Too many registrations. Try again later.", 429)
    name = body.get("client_name") if isinstance(body.get("client_name"), str) else ""
    name = " ".join(name.split())[:100] or "MCP client"
    client = McpOAuthClient(id=secrets.token_urlsafe(24), name=name, redirect_uris=list(uris), created_at=utcnow(),
                            sender=sender[:64])
    db.add(client)
    db.commit()
    count = db.scalar(select(func.count()).select_from(McpOAuthClient)) or 0
    if count > MAX_CLIENTS:
        # The ones used longest ago (never used first) make room. Not one made in the last hour: its person may be on
        # the consent page right now. Their keys stay until they run out or are withdrawn.
        oldest = db.scalars(select(McpOAuthClient.id).where(McpOAuthClient.created_at < utcnow() - timedelta(hours=1))
                            .order_by(McpOAuthClient.last_used_at.is_not(None), McpOAuthClient.last_used_at,
                                      McpOAuthClient.created_at)
                            .limit(count - MAX_CLIENTS)).all()
        db.execute(delete(McpOAuthClient).where(McpOAuthClient.id.in_(oldest)))
        db.commit()
    logger.info("MCP connector %r registered from %s with %d return address(es).", name, sender, len(uris))
    return client


# -- the consent page -----------------------------------------------------------------------------


def client_for(db: Session, client_id: str, redirect_uri: str) -> McpOAuthClient:
    client = db.get(McpOAuthClient, client_id) if client_id else None
    if client is None:
        raise McpError("oauth_client", "This program is not registered here. Let it connect again.", 400)
    if redirect_uri not in (client.redirect_uris or []):
        # Never send anybody to an address the program did not register: that is how codes are stolen.
        raise McpError("oauth_redirect", "This return address is not registered for the program.", 400)
    return client


def check_request(db: Session, base: str, *, client_id: str, redirect_uri: str, code_challenge: str,
                  code_challenge_method: str, resource: str) -> McpOAuthClient:
    """Everything a sign-in request must hold before an account is asked; checked again when it answers."""
    client = client_for(db, client_id, redirect_uri)
    _check_challenge(code_challenge, code_challenge_method)
    if resource and not same_resource(resource, resource_of(base)):
        raise McpError("oauth_resource", "The program asks for access to something other than this nexdeck.", 400)
    return client


def check_request_shape(code_challenge: str, code_challenge_method: str, resource: str, base: str) -> None:
    """The mistakes of a sign-in request that go back to the program, in OAuth's words."""
    try:
        _check_challenge(code_challenge, code_challenge_method)
    except McpError:
        raise OAuthError("invalid_request", "PKCE with S256 is required.") from None
    if resource and not same_resource(resource, resource_of(base)):
        raise OAuthError("invalid_target", "The resource is not this nexdeck's MCP endpoint.")


def back_to(redirect_uri: str, values: dict[str, str]) -> str:
    joiner = "&" if "?" in redirect_uri else "?"
    return redirect_uri + joiner + urlencode({key: value for key, value in values.items() if value})


def connector_end(db: Session, key: McpKey) -> Any:
    """When a connector runs out unless it refreshes: its live refresh token's end, else its access token's."""
    latest = db.scalar(select(func.max(McpOAuthRefresh.expires_at))
                       .where(McpOAuthRefresh.key_id == key.id, McpOAuthRefresh.used_at.is_(None)))
    ends = [moment for moment in (mcp._aware(latest), mcp._aware(key.expires_at)) if moment is not None]
    return max(ends) if ends else None


def connector_alive(db: Session, key: McpKey) -> bool:
    if key.revoked:
        return False
    end = connector_end(db, key)
    return end is None or end > utcnow()


def holds(db: Session, user_id: int) -> int:
    """The keys an account holds against the twenty: hand-made ones that count, and connectors that can still refresh."""
    rows = db.scalars(select(McpKey).where(McpKey.user_id == user_id))
    return sum(1 for row in rows if (connector_alive(db, row) if row.kind == "oauth" else mcp.counts(row)))


def grant(db: Session, user: User, client: McpOAuthClient, *, redirect_uri: str, code_challenge: str, resource: str,
          level: str, boards: list[int] | None) -> str:
    """The account agrees: a code for the program, good once and for ``CODE_MINUTES``."""
    if level not in mcp.LEVELS:
        raise McpError("bad_level", "The level is read or act.", 422)
    if not mcp.at_least(mcp.stored(db)["max_level"], level):
        raise McpError("level_not_allowed", "The administrator does not allow keys of this level.", 403)
    if boards is not None:
        if not boards or not set(boards) <= mcp.visible_boards(db, user):
            raise McpError("unknown_board", "There is no such board.", 422)
        boards = sorted(set(boards))
    if holds(db, user.id) >= mcp.MAX_KEYS and not _previous(db, user.id, client.id):
        raise McpError("too_many_keys", f"An account holds at most {mcp.MAX_KEYS} keys. Withdraw one first.", 409)
    now = utcnow()
    db.execute(delete(McpOAuthCode).where(McpOAuthCode.expires_at <= now))
    code = f"{CODE_PREFIX}_{secrets.token_urlsafe(32)}"
    db.add(McpOAuthCode(code_hash=hash_token(code), client_id=client.id, user_id=user.id, challenge=code_challenge,
                        resource=resource or None, redirect_uri=redirect_uri, level=level, boards=boards, created_at=now,
                        expires_at=now + timedelta(minutes=CODE_MINUTES)))
    db.commit()
    logger.info("MCP connector %r allowed by %s, level %s, %s.", client.name, user.username, level,
                "every board" if boards is None else f"{len(boards)} board(s)")
    return code


# -- tokens ----------------------------------------------------------------------------------------


def _account_may(db: Session, user_id: int, since: Any) -> tuple[bool, bool]:
    """Whether the account may hold a connector now, and, when not, whether that is for good.

    For good: gone, disabled, a guest, or its password changed since ``since``.
    For now: it owes the installation a second factor.
    """
    from . import two_factor

    user = db.get(User, user_id)
    if user is None or user.disabled or user.role == Role.guest.value:
        return False, True
    if int(mcp._aware(since).timestamp() * 1000) < user.password_changed_ms:
        return False, True
    if two_factor.must_set_up(db, user, None):
        return False, False
    return True, False


def _previous(db: Session, user_id: int, client_id: str) -> list[McpKey]:
    """The account's connectors of this program that still stand."""
    ids = select(McpOAuthRefresh.key_id).where(McpOAuthRefresh.client_id == client_id)
    return list(db.scalars(select(McpKey).where(McpKey.user_id == user_id, McpKey.kind == "oauth", McpKey.revoked.is_(False),
                                                McpKey.id.in_(ids)).order_by(McpKey.id)))


def end_chain(db: Session, key_id: int, why: str) -> None:
    """The key and every refresh token of its chain, ended together."""
    now = utcnow()
    db.execute(update(McpOAuthRefresh).where(McpOAuthRefresh.key_id == key_id, McpOAuthRefresh.used_at.is_(None))
               .values(used_at=now))
    key = db.get(McpKey, key_id)
    if key is not None and not key.revoked:
        key.revoked = True
        key.revoked_at = now
    db.commit()
    logger.info("MCP connector key %s ended: %s.", key_id, why)


def end_all(db: Session, why: str) -> int:
    ids = list(db.scalars(select(McpKey.id).where(McpKey.kind == "oauth", McpKey.revoked.is_(False))))
    for key_id in ids:
        end_chain(db, key_id, why)
    return len(ids)


def _issue(db: Session, key: McpKey, client: McpOAuthClient) -> dict[str, Any]:
    now = utcnow()
    access, access_hash, prefix = new_opaque_token(ACCESS_PREFIX)
    refresh, refresh_hash, _ = new_opaque_token(REFRESH_PREFIX)
    key.token_hash = access_hash
    # The first access token names the key in the list; it stays the same name through every refresh.
    key.prefix = key.prefix or prefix
    key.expires_at = now + timedelta(hours=ACCESS_HOURS)
    db.add(McpOAuthRefresh(token_hash=refresh_hash, key_id=key.id, client_id=client.id, created_at=now,
                           expires_at=now + timedelta(days=REFRESH_DAYS)))
    client.last_used_at = now
    db.commit()
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_HOURS * 3600,
            "refresh_token": refresh, "scope": SCOPE}


def _tidy(db: Session) -> None:
    now = utcnow()
    db.execute(delete(McpOAuthCode).where(McpOAuthCode.expires_at <= now - timedelta(minutes=CODE_MINUTES)))
    db.execute(delete(McpOAuthRefresh).where(McpOAuthRefresh.expires_at <= now))
    db.commit()


def _invalid(text: str) -> OAuthError:
    return OAuthError("invalid_grant", text)


def trade_code(db: Session, client: McpOAuthClient, form: dict[str, str], base: str) -> dict[str, Any]:
    code_hash = hash_token(form.get("code", ""))
    row = db.get(McpOAuthCode, code_hash)
    if row is None or row.client_id != client.id:
        raise _invalid("The code is not valid.")
    now = utcnow()
    # Taken first, in one step: a code is traded once, even when two requests bring it at the same moment.
    taken = db.execute(update(McpOAuthCode).where(McpOAuthCode.code_hash == code_hash, McpOAuthCode.used_at.is_(None))
                       .values(used_at=now)).rowcount
    db.commit()
    if taken != 1:
        db.expire_all()
        first = db.get(McpOAuthCode, code_hash)
        if first is not None and first.key_id is not None:
            # Brought a second time: somebody else holds it too. What the first trade made ends (RFC 6749, 4.1.2).
            end_chain(db, first.key_id, "its code was brought a second time")
        raise _invalid("The code was used already.")
    if mcp._aware(row.expires_at) <= now:
        raise _invalid("The code ran out.")
    if form.get("redirect_uri", "") != row.redirect_uri:
        raise _invalid("The return address differs from the one the code was given for.")
    if not verifier_fits(form.get("code_verifier", ""), row.challenge):
        raise _invalid("The code verifier does not fit the challenge.")
    resource = form.get("resource", "")
    if resource and not (same_resource(resource, resource_of(base)) and (row.resource is None or same_resource(resource, row.resource))):
        raise OAuthError("invalid_target", "The token can only be for this nexdeck's MCP endpoint.")
    may, _for_good = _account_may(db, row.user_id, row.created_at)
    if not may:
        raise _invalid("The account may not sign in a program now.")
    # Signing the same program in again replaces its connector, keeping the rights per tool set for it.
    previous = _previous(db, row.user_id, client.id)
    if holds(db, row.user_id) - len(previous) >= mcp.MAX_KEYS:
        raise _invalid(f"The account holds {mcp.MAX_KEYS} keys already. Withdraw one first.")
    rights = dict(previous[-1].tool_rights or {}) if previous else {}
    for old in previous:
        end_chain(db, old.id, "its program signed in again")
    # A hash nobody holds until ``_issue`` writes the real one: the column takes no empty value twice.
    key = McpKey(user_id=row.user_id, name=client.name[:80], kind="oauth", level=row.level,
                 token_hash=hash_token(secrets.token_urlsafe(32)), prefix="", boards=row.boards, tool_rights=rights,
                 client=client.name[:200], created_at=now)
    db.add(key)
    db.flush()
    row.key_id = key.id
    answer = _issue(db, key, client)
    _tidy(db)
    logger.info("MCP connector %r signed in as key %s.", client.name, key.id)
    return answer


def refresh(db: Session, client: McpOAuthClient, form: dict[str, str], base: str) -> dict[str, Any]:
    brought = hash_token(form.get("refresh_token", ""))
    row = db.get(McpOAuthRefresh, brought)
    if row is None or row.client_id != client.id:
        raise _invalid("The refresh token is not valid.")
    if row.used_at is not None:
        # Used up already: whoever brings it holds a copy. The whole chain ends, for the thief and the program alike;
        # the account signs the program in again (OAuth 2.1, 4.3.1).
        logger.warning("MCP connector key %s: a used refresh token came back, the chain ends.", row.key_id)
        end_chain(db, row.key_id, "a used refresh token came back")
        raise _invalid("The refresh token was used already.")
    now = utcnow()
    if mcp._aware(row.expires_at) <= now:
        raise _invalid("The refresh token ran out.")
    resource = form.get("resource", "")
    if resource and not same_resource(resource, resource_of(base)):
        raise OAuthError("invalid_target", "The token can only be for this nexdeck's MCP endpoint.")
    key = db.get(McpKey, row.key_id)
    if key is None or key.revoked:
        raise _invalid("The connector was withdrawn.")
    may, for_good = _account_may(db, key.user_id, key.created_at)
    if not may:
        if for_good:
            end_chain(db, key.id, "its account may no longer hold it")
        raise _invalid("The account may not sign in a program now.")
    taken = db.execute(update(McpOAuthRefresh).where(McpOAuthRefresh.token_hash == brought, McpOAuthRefresh.used_at.is_(None))
                       .values(used_at=now)).rowcount
    db.commit()
    if taken != 1:
        # Another request used it in the same moment: the same as bringing it twice.
        end_chain(db, key.id, "a refresh token was used twice at once")
        raise _invalid("The refresh token was used already.")
    answer = _issue(db, key, client)
    _tidy(db)
    logger.info("MCP connector key %s refreshed.", key.id)
    return answer


def revoke(db: Session, token: str, client_id: str) -> None:
    """RFC 7009: a refresh or an access token ends its whole connector. Unknown tokens are no error."""
    if not token:
        return
    hashed = hash_token(token)
    row = db.get(McpOAuthRefresh, hashed)
    if row is not None:
        if not client_id or row.client_id == client_id:
            end_chain(db, row.key_id, "its program revoked it")
        return
    key = db.scalar(select(McpKey).where(McpKey.token_hash == hashed, McpKey.kind == "oauth"))
    if key is None:
        return
    owners = set(db.scalars(select(McpOAuthRefresh.client_id).where(McpOAuthRefresh.key_id == key.id)))
    if not client_id or client_id in owners:
        end_chain(db, key.id, "its program revoked it")
