"""What runs on what (roadmap M5): the inventory, the relations, and what follows when something goes down.

Three kinds of things take part, each named by a reference:

* ``integration:<id>``: a connection, which is a service (Plex), a host
  (a Synology, a Proxmox, a Docker engine) or both;
* ``tile:<widget id>``: an app tile with an address;
* ``container:<integration>:<name>`` and ``guest:<integration>:<vmid>``:
  what an engine or a hypervisor runs, found about once an hour
  (``discover``) and kept, so it is known while its host is down.

A container belongs to its engine and a guest to its hypervisor without
saying. The rest is in ``Relation``: found from the address (``auto``),
proposed from the name (``suggested``) or set by hand (``manual``).

⚠️ "Found from the address" means the same IP and the same port, and is
then certain. Ports 80 and 443 are the exception: behind them sits a
reverse proxy more often than the service, so a match there is only
proposed.

When something goes down, what hangs on it goes quiet (``hold``): one
message names the thing and how many are affected, and the cards of the
others say "because of …" (``cause``).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from collections import deque
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import db_session
from ..models import HealthCheck, Integration, Relation, Thing, Widget, utcnow
from .state import live

logger = logging.getLogger("nexdeck.dependencies")

#: Connections that run things (``Adapter.things``).
ENGINES = ("docker", "portainer", "synology", "proxmox")
#: Connections that are hosts in their own right: a service on their address hangs on them.
HOSTS = ("synology", "proxmox", "unraid", "truenas", "openmediavault", "docker", "portainer")
#: Where a match is a guess: a reverse proxy listens here more often than the service.
PROXY_PORTS = (80, 443)
#: How long an outage waits for its cause before it is told.
HOLD_SECONDS = 90
#: Events that are bundled under their cause.
BUNDLED = ("outage", "widget_broken")
DEPTH = 6
DEFAULT_PORTS = {"http": 80, "https": 443, "tcp": None}

#: Outages told under a cause, so their recovery is not told either.
_quiet: set[str] = set()


# -- addresses ----------------------------------------------------------------------------


def address_of(url: str) -> tuple[str, int | None]:
    """``(host, port)`` of an address as a connection or a tile has it."""
    raw = str(url or "").strip()
    if not raw:
        return "", None
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw.replace("tcp://", "http://", 1))
    try:
        port = parts.port
    except ValueError:
        port = None
    return (parts.hostname or "").lower(), port or DEFAULT_PORTS.get(parts.scheme)


_resolved: dict[str, tuple[float, set[str]]] = {}


def resolve(host: str) -> set[str]:
    """The addresses a name stands for, remembered for an hour; an address stands for itself."""
    if not host:
        return set()
    try:
        return {str(ipaddress.ip_address(host))}
    except ValueError:
        pass
    known = _resolved.get(host)
    if known and time.monotonic() - known[0] < 3600:
        return known[1]
    try:
        found = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        found = set()
    _resolved[host] = (time.monotonic(), found)
    return found


def _service_address(integration: Integration | None = None, tile: Widget | None = None) -> str:
    if integration is not None:
        from .integrations import resolve_config

        try:
            config = resolve_config(integration)
        except Exception:  # noqa: BLE001 - a secret that cannot be read leaves no address
            return ""
        return str(config.get("url") or config.get("host") or "")
    if tile is not None:
        check = tile.health_check
        return str((check.target if check is not None and check.target else "") or tile.link or (tile.options or {}).get("url") or "")
    return ""


# -- finding what runs where ----------------------------------------------------------------


async def discover() -> int:
    """Ask every engine and hypervisor what it runs, then match services to it. Returns how many things are known."""
    from .collector import collector

    with db_session() as db:
        engines = [(row.id, row.kind) for row in db.scalars(select(Integration).where(
            Integration.kind.in_(ENGINES), Integration.enabled.is_(True), Integration.demo.is_(False)))]
    hosts: dict[int, list[str]] = {}
    for integration_id, kind in engines:
        try:
            adapter, config, ctx = await collector.resolve_integration(integration_id)
            found = await adapter.things(config, ctx)
        except Exception as error:  # noqa: BLE001 - an engine that does not answer keeps what was known of it
            logger.info("Could not ask %s %s what it runs: %s", kind, integration_id, getattr(error, "message", error))
            continue
        if found is None:
            continue
        hosts[integration_id] = list(found.get("host") or [])
        with db_session() as db:
            keep(db, integration_id, found.get("things") or [])
    # ⚠️ In a thread: matching resolves names, and a resolver that hangs must not hold up the board.
    return await asyncio.to_thread(_match_now, hosts)


def _match_now(hosts: dict[int, list[str]]) -> int:
    with db_session() as db:
        match(db, hosts)
        return len(list(db.scalars(select(Thing.id))))


def keep(db: Session, integration_id: int, found: list[dict[str, Any]]) -> None:
    """What an engine runs now replaces what it ran before."""
    rows = {row.ref: row for row in db.scalars(select(Thing).where(Thing.integration_id == integration_id))}
    seen = set()
    for one in found:
        ref = f"{one.get('kind')}:{integration_id}:{one.get('key')}"[:200]
        seen.add(ref)
        row = rows.get(ref) or Thing(ref=ref, kind=str(one.get("kind")), integration_id=integration_id)
        row.name = str(one.get("name") or "")[:200]
        row.image = str(one.get("image") or "")[:300]
        row.state = str(one.get("state") or "")[:20]
        row.addresses = [str(address) for address in one.get("addresses") or []][:20]
        row.ports = [int(port) for port in one.get("ports") or []][:50]
        row.host_network = bool(one.get("host_network"))
        row.seen_at = utcnow()
        db.add(row)
    gone = [ref for ref in rows if ref not in seen]
    if gone:
        db.execute(delete(Thing).where(Thing.ref.in_(gone)))
        db.execute(delete(Relation).where(Relation.parent.in_(gone)))


def _words(text: str) -> set[str]:
    out, word = set(), ""
    for char in text.lower():
        if char.isalnum():
            word += char
        else:
            if len(word) >= 4:
                out.add(word)
            word = ""
    if len(word) >= 4:
        out.add(word)
    return out


def match(db: Session, hosts: dict[int, list[str]] | None = None) -> None:
    """Relations from addresses and names. Ones found from the address are rebuilt each time; a no is never asked again."""
    hosts = hosts or {}
    integrations = list(db.scalars(select(Integration).where(Integration.enabled.is_(True))))
    tiles = [row for row in db.scalars(select(Widget).where(Widget.kind == "core.app"))]
    things = list(db.scalars(select(Thing)))
    host_addresses = {integration_id: set().union(*(resolve(one) for one in names)) if names else set()
                      for integration_id, names in hosts.items()}
    # A host whose things were not asked this round keeps its address from its own setting.
    for integration in integrations:
        if integration.kind in HOSTS and integration.id not in host_addresses:
            host_addresses[integration.id] = resolve(address_of(_service_address(integration))[0])

    services: list[tuple[str, str, str, int | None, set[str]]] = []
    for integration in integrations:
        host, port = address_of(_service_address(integration))
        services.append((f"integration:{integration.id}", f"{integration.kind} {integration.name}", host, port, resolve(host)))
    for tile in tiles:
        host, port = address_of(_service_address(tile=tile))
        services.append((f"tile:{tile.id}", tile.title or "", host, port, resolve(host)))

    existing = {(row.child, row.parent): row for row in db.scalars(select(Relation))}
    auto: set[tuple[str, str]] = set()
    proposed: set[tuple[str, str]] = set()
    for ref, words, _host, port, addresses in services:
        own = ref.split(":", 1)[1] if ref.startswith("integration:") else None
        # The most exact wins: a container that publishes the port, else a guest
        # with the address, else a host with the address. A service in a
        # container on a VM hangs on the container; the VM follows through the engine.
        containers: list[str] = []
        guests: list[str] = []
        guessed: list[str] = []
        for thing in things if addresses else []:
            if str(thing.integration_id) == own:
                continue
            if thing.kind == "guest" and addresses & set(thing.addresses):
                guests.append(thing.ref)
            elif thing.kind == "container" and addresses & host_addresses.get(thing.integration_id, set()) and port and port in (thing.ports or []):
                (guessed if port in PROXY_PORTS else containers).append(thing.ref)
        certain = containers or guests or [f"integration:{integration_id}" for integration_id, known in host_addresses.items()
                                           if addresses and str(integration_id) != own and addresses & known]
        for parent in certain:
            auto.add((ref, parent))
        if not certain:
            mine = _words(words)
            for thing in things:
                if str(thing.integration_id) != own and mine & (_words(thing.name) | _words(thing.image.split("/")[-1].split(":")[0])):
                    guessed.append(thing.ref)
        for parent in guessed:
            proposed.add((ref, parent))

    for key, row in existing.items():
        if row.origin == "auto" and row.state == "on" and key not in auto:
            db.delete(row)
    for child, parent in auto:
        row = existing.get((child, parent))
        if row is None:
            db.add(Relation(child=child, parent=parent, origin="auto", state="on"))
        elif row.state == "suggested":
            row.origin, row.state = "auto", "on"
    for child, parent in proposed - auto:
        if (child, parent) not in existing:
            db.add(Relation(child=child, parent=parent, origin="suggested", state="suggested"))
    db.flush()


# -- reading the relations ------------------------------------------------------------------


def parents(db: Session, ref: str) -> list[str]:
    """What ``ref`` runs on or needs, directly."""
    found = [row.parent for row in db.scalars(select(Relation).where(Relation.child == ref, Relation.state == "on"))]
    if ref.startswith(("container:", "guest:")):
        found.append(f"integration:{ref.split(':')[1]}")
    return found


def ancestors(db: Session, ref: str) -> list[str]:
    """Everything ``ref`` hangs on, nearest first; never itself, never twice."""
    seen: list[str] = []
    queue = deque((one, 1) for one in parents(db, ref))
    while queue:
        one, depth = queue.popleft()
        if one == ref or one in seen or depth > DEPTH:
            continue
        seen.append(one)
        queue.extend((up, depth + 1) for up in parents(db, one))
    return seen


def descendants(db: Session, ref: str) -> list[str]:
    """Everything that hangs on ``ref``: services, tiles and, for an engine, its things."""
    children: dict[str, list[str]] = {}
    for row in db.scalars(select(Relation).where(Relation.state == "on")):
        children.setdefault(row.parent, []).append(row.child)
    for thing in db.scalars(select(Thing)):
        children.setdefault(f"integration:{thing.integration_id}", []).append(thing.ref)
    seen: list[str] = []
    queue = deque((one, 1) for one in children.get(ref, []))
    while queue:
        one, depth = queue.popleft()
        if one == ref or one in seen or depth > DEPTH:
            continue
        seen.append(one)
        queue.extend((down, depth + 1) for down in children.get(one, []))
    return seen


def name_of(db: Session, ref: str) -> str:
    kind, _, rest = ref.partition(":")
    if kind == "integration":
        row = db.get(Integration, int(rest)) if rest.isdigit() else None
        return row.name if row else ref
    if kind == "tile":
        row = db.get(Widget, int(rest)) if rest.isdigit() else None
        return (row.title or "") if row else ref
    thing = db.scalar(select(Thing).where(Thing.ref == ref))
    return thing.name if thing else rest.split(":")[-1]


def is_down(db: Session, ref: str) -> bool:
    """Down right now: a failing check, every card of a connection failing, a thing that stopped or whose host is down."""
    kind, _, rest = ref.partition(":")
    if kind == "tile" and rest.isdigit():
        check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == int(rest)))
        return bool(check is not None and check.enabled and check.last_ok is False)
    if kind == "integration" and rest.isdigit():
        widgets = list(db.scalars(select(Widget.id).where(Widget.integration_id == int(rest))))
        if any(check.last_ok is False for check in db.scalars(select(HealthCheck).where(HealthCheck.widget_id.in_(widgets or [-1]), HealthCheck.enabled.is_(True)))):
            return True
        read = [live.get(one) for one in widgets]
        read = [data for data in read if data is not None]
        return bool(read) and all(data.error for data in read)
    if kind in ("container", "guest"):
        thing = db.scalar(select(Thing).where(Thing.ref == ref))
        if thing is not None and thing.state and thing.state not in ("running", "online"):
            return True
        return is_down(db, f"integration:{rest.split(':')[0]}")
    return False


def cause(db: Session, ref: str) -> str:
    """The name of the furthest thing ``ref`` hangs on that is down, or ""."""
    down = [one for one in ancestors(db, ref) if is_down(db, one)]
    return name_of(db, down[-1]) if down else ""


def subject_of(widget: Widget | None) -> str | None:
    """Whom an outage of this card is about: its connection, or the tile itself."""
    if widget is None:
        return None
    if widget.integration_id:
        return f"integration:{widget.integration_id}"
    return f"tile:{widget.id}"


def related(db: Session, ref: str) -> bool:
    return bool(parents(db, ref)) or db.scalar(select(Relation.id).where(Relation.parent == ref, Relation.state == "on")) is not None \
        or (ref.startswith("integration:") and db.scalar(select(Thing.id).where(Thing.integration_id == int(ref.split(":")[1]))) is not None)


# -- telling it once --------------------------------------------------------------------------


def hold(event: str, subject: str | None, title: str, body: str, *, level: str, link: str, user_ids: list[int] | None,
         integration_id: int | None) -> bool:
    """Take an outage over when it has relations: wait for its cause, then tell it once. True when taken over."""
    if subject is None:
        return False
    if event == "recovery" and subject in _quiet:
        _quiet.discard(subject)
        logger.info("%s is back; it was not told as down, so its return is not told either.", subject)
        return True
    if event not in BUNDLED:
        return False
    with db_session() as db:
        if not related(db, subject):
            return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    loop.call_later(HOLD_SECONDS, _release, event, subject, title, body, level, link, user_ids, integration_id)
    return True


def _release(event: str, subject: str, title: str, body: str, level: str, link: str, user_ids: list[int] | None, integration_id: int | None) -> None:
    from . import notify

    with db_session() as db:
        above = [one for one in ancestors(db, subject) if is_down(db, one)]
        if above:
            _quiet.add(subject)
            logger.info("%s is quiet: it hangs on %s, which is down.", subject, name_of(db, above[-1]))
            return
        below = [one for one in descendants(db, subject) if is_down(db, one) and not one.startswith(("container:", "guest:"))]
        names = sorted({name_of(db, one) for one in below} - {""})
        own = name_of(db, subject)
    if names:
        title = f"{own} is down, {len(names)} {'service' if len(names) == 1 else 'services'} affected"
        body = f"{body}\nAffected: {', '.join(names[:20])}".strip()
        level = "error"
    notify.emit(event, title, body, level=level, link=link, user_ids=user_ids, integration_id=integration_id, held=True)


def view(db: Session) -> dict[str, Any]:
    """The inventory as the page draws it: every node with its state, and every relation."""
    nodes: list[dict[str, Any]] = []
    for integration in db.scalars(select(Integration).order_by(Integration.name)):
        host, port = address_of(_service_address(integration))
        ref = f"integration:{integration.id}"
        nodes.append({"ref": ref, "kind": "integration", "service": integration.kind, "name": integration.name,
                      "detail": f"{host}:{port}" if host and port else host, "host": integration.kind in HOSTS,
                      "down": is_down(db, ref), "demo": integration.demo})
    for tile in db.scalars(select(Widget).where(Widget.kind == "core.app")):
        ref = f"tile:{tile.id}"
        host, port = address_of(_service_address(tile=tile))
        nodes.append({"ref": ref, "kind": "tile", "service": "", "name": tile.title or "", "detail": f"{host}:{port}" if host and port else host,
                      "host": False, "down": is_down(db, ref), "demo": False})
    for thing in db.scalars(select(Thing).order_by(Thing.name)):
        detail = ", ".join(thing.addresses[:2]) or (", ".join(str(one) for one in thing.ports[:4]) and f"ports {', '.join(str(one) for one in thing.ports[:4])}")
        nodes.append({"ref": thing.ref, "kind": thing.kind, "service": "", "name": thing.name, "detail": detail or "", "image": thing.image,
                      "state": thing.state, "host": False, "down": is_down(db, thing.ref), "parent": f"integration:{thing.integration_id}", "demo": False})
    relations = [{"id": row.id, "child": row.child, "parent": row.parent, "origin": row.origin, "state": row.state}
                 for row in db.scalars(select(Relation).where(Relation.state != "rejected"))]
    return {"nodes": nodes, "relations": relations}
