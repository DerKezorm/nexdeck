"""Signed in at home without a password: a wall tablet on the home network.

An administrator names the home networks and one account. A browser whose
address is inside those networks gets a session as that account on the sign-in
page, without typing anything. Everywhere else the sign-in page stays.

What keeps this from being a door left open:

- **The address is the connection's own.** The image used to start uvicorn with
  ``--forwarded-allow-ips "*"``, which makes the client address whatever
  ``X-Forwarded-For`` says, from anybody. That was fine for a log line and a
  sign-in brake that counts the account as well; it is no ground for letting
  somebody in. So the socket's own peer is recorded before anything rewrites
  it (``RecordPeer``), and a forwarding header is believed only from a proxy
  named in ``NEXDECK_TRUSTED_PROXIES``, read from the right, where the nearest
  proxy wrote it. A forwarding header from anybody else means the real address
  is unknown, and an unknown address is not at home.
- **Only home networks.** A network with any address the Internet routes is
  refused, and so is loopback: a reverse proxy on the same machine talks from
  there, and it would bring everybody.
- **Not an administrator.** The account a whole room shares may use the
  boards; it may not change who else can.
- **The session stays at home.** A session opened this way is checked on every
  request: from anywhere outside the networks it is not signed in. A cookie
  copied off the tablet, or the tablet taken along, opens nothing.
- **Not while every account owes a second factor**: that setting says nobody
  gets in on a password alone, so certainly not on no password.
- **Signing out holds it off** for twelve hours in that browser, or the page
  would sign straight back in. The sign-in page offers the way back.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..models import Role, Session, Setting, User

SETTING = "home_network"
#: The kind a session opened this way carries.
KIND = "home"
#: The cookie that holds the automatic sign-in off after signing out on purpose.
OFF_COOKIE = "nexdeck_home_off"
OFF_SECONDS = 12 * 3600
#: Headers by which something in front says who it forwards for.
FORWARDING = ("x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip", "true-client-ip", "x-client-ip")

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
#: What a home network may lie in: the private ranges, the shared range that
#: Tailscale and carrier NAT use, and IPv6's unique local and link-local ones.
HOME_RANGES = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7", "fe80::/10",
))
LOOPBACK = {4: ipaddress.ip_network("127.0.0.0/8"), 6: ipaddress.ip_network("::1/128")}


class Refused(ValueError):
    """A setting that cannot be stored, with the reason in words."""


# -- the address --------------------------------------------------------------


class RecordPeer:
    """Keep the socket's own peer before any forwarding header rewrites the client.

    Pure ASGI and outermost. Behind it the client address is rewritten from
    the forwarding headers exactly as uvicorn's ``--forwarded-allow-ips "*"``
    did, so every log line and the sign-in brake see what they always saw;
    the image now starts uvicorn with ``--no-proxy-headers`` so that the peer
    recorded here is the real one.
    """

    def __init__(self, app: Any) -> None:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        self.inner = ProxyHeadersMiddleware(app, trusted_hosts="*")

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket") and "nexdeck.peer" not in scope:
            client = scope.get("client")
            scope["nexdeck.peer"] = client[0] if client else ""
        await self.inner(scope, receive, send)


def trusted_proxies() -> list[Network]:
    raw = os.environ.get("NEXDECK_TRUSTED_PROXIES", "")
    found: list[Network] = []
    for part in raw.replace(";", ",").split(","):
        if part.strip():
            try:
                found.append(ipaddress.ip_network(part.strip(), strict=False))
            except ValueError:
                continue
    return found


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    text = text.strip().strip('"')
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    elif text.count(":") == 1:
        text = text.split(":")[0]
    try:
        found = ipaddress.ip_address(text)
    except ValueError:
        return None
    # An IPv4 address as the IPv6 stack writes it is still that IPv4 address.
    if isinstance(found, ipaddress.IPv6Address) and found.ipv4_mapped:
        return found.ipv4_mapped
    return found


def _inside(address: ipaddress.IPv4Address | ipaddress.IPv6Address, networks: list[Network]) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def seen_address(request: Request) -> tuple[str | None, str]:
    """The address this request really comes from, or None and why not."""
    peer = _ip(str(request.scope.get("nexdeck.peer") or (request.client.host if request.client else "")))
    if peer is None:
        return None, "no_peer"
    headers = {name: request.headers.get(name) for name in FORWARDING if request.headers.get(name)}
    proxies = trusted_proxies()
    if not _inside(peer, proxies):
        # Something in front forwards for somebody else, and nobody said it
        # may: whoever that is, it is not known.
        return (None, "forwarded_by_unknown") if headers else (str(peer), "direct")
    chain = [part for part in (headers.get("x-forwarded-for") or "").split(",") if part.strip()]
    if not chain and headers.get("x-real-ip"):
        # nginx's usual line when it sets no X-Forwarded-For.
        chain = [str(headers["x-real-ip"])]
    for entry in reversed(chain):
        address = _ip(entry)
        if address is None:
            return None, "unreadable_forwarding"
        if not _inside(address, proxies):
            return str(address), "via_proxy"
    return None, "proxy_without_forwarding"


# -- the setting ----------------------------------------------------------------


@dataclass
class Settings:
    enabled: bool = False
    networks: tuple[str, ...] = ()
    user_id: int | None = None

    def view(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "networks": list(self.networks), "user_id": self.user_id}


def load(db: DbSession) -> Settings:
    row = db.get(Setting, SETTING)
    value = dict(row.value) if row is not None else {}
    user_id = value.get("user_id")
    return Settings(bool(value.get("enabled")), tuple(str(n) for n in value.get("networks") or ()), user_id if isinstance(user_id, int) else None)


def check_networks(lines: list[str]) -> list[str]:
    """Home networks only, written the way ``ipaddress`` reads them back."""
    kept: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as failure:
            raise Refused(f"{text} is not a network. Write it like 192.168.1.0/24.") from failure
        if network.subnet_of(LOOPBACK[network.version]):  # type: ignore[arg-type]
            raise Refused(f"{text} is this machine itself. A reverse proxy on the same machine talks from there, and it would bring everybody in.")
        # Inside a private range as a whole, not only at both ends: 192.0.0.0/2
        # starts and ends on addresses nobody routes and holds half the Internet.
        if not any(network.version == home.version and network.subnet_of(home) for home in HOME_RANGES):  # type: ignore[arg-type]
            raise Refused(f"{text} reaches beyond a home network. Only private ranges are allowed, like 192.168.0.0/16, 10.0.0.0/8 or fd00::/8.")
        if str(network) not in kept:
            kept.append(str(network))
    return kept


def check_account(db: DbSession, user_id: int | None) -> User:
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise Refused("Choose the account a browser at home is signed in as.")
    if user.role == Role.admin.value:
        raise Refused("An administrator's account is never signed in without a password. Choose an ordinary account.")
    if user.disabled:
        raise Refused("That account is disabled.")
    return user


def store(db: DbSession, wanted: Settings) -> Settings:
    """Check and keep. Every session opened at home under the old setting ends."""
    from . import two_factor

    networks = tuple(check_networks(list(wanted.networks)))
    if wanted.enabled:
        if not networks:
            raise Refused("Name at least one home network.")
        check_account(db, wanted.user_id)
        if two_factor.required(db):
            raise Refused("Every account owes a second factor on this installation, so nobody is signed in without a password.")
    elif wanted.user_id is not None:
        check_account(db, wanted.user_id)
    kept = Settings(wanted.enabled, networks, wanted.user_id)
    db.merge(Setting(key=SETTING, value=kept.view()))
    for session in db.scalars(select(Session).where(Session.kind == KIND, Session.revoked.is_(False))):
        session.revoked = True
    return kept


# -- the decision ----------------------------------------------------------------


def account_for(db: DbSession, request: Request) -> tuple[User | None, str]:
    """The account a browser here would be signed in as, or None and why not."""
    from . import two_factor

    settings = load(db)
    if not settings.enabled or not settings.networks:
        return None, "off"
    address, how = seen_address(request)
    if address is None:
        return None, how
    ip = _ip(address)
    networks = [ipaddress.ip_network(n, strict=False) for n in settings.networks]
    if ip is None or not _inside(ip, networks):
        return None, "outside"
    try:
        user = check_account(db, settings.user_id)
    except Refused:
        return None, "no_account"
    if two_factor.required(db):
        return None, "factor_required"
    return user, "home"


def still_home(db: DbSession, request: Request, session: Session) -> bool:
    """A session opened at home counts only at home, for the account still chosen."""
    if session.kind != KIND:
        return True
    user, _ = account_for(db, request)
    return user is not None and user.id == session.user_id
