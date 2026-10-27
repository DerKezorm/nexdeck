"""Services that run in the homelab, have an adapter, and are not connected yet: "Found in your network".

Read from the inventory alone (roadmap M5, ``services/dependencies.py``):
the containers Docker, Portainer and Synology run, and the guests of
Proxmox, with the ports they publish and the addresses they have. Nothing
is asked of the network here; a homelab without an inventory finds nothing.

A thing is a service when its image or its name is what an adapter is
called (its kind, its logo, its label), the same names the logos of the
container lists are found by (``icons.name_candidates``). The address is
the host the engine runs on with the port the container publishes, or the
guest's own address, with the port the service answers on out of the box.

⚠️ A match that only holds after cutting the name (``grafana-agent`` is
``grafana``) counts only where the container publishes the service's own
port: an agent, an exporter or a sidecar is named after what it serves and
is not it.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters import all_adapters
from ..models import Integration, Relation, Setting, Thing
from . import dependencies
from .icons import guess_from_image, name_candidates

#: Where the ignored ones are kept, by key: ``{"ignored": [...]}``.
SETTING = "found"
#: More is not kept: a list nobody reads again.
IGNORED_LIMIT = 500
RUNNING = frozenset({"running", "online", "up"})
#: The port an adapter's own example address does not say. ⚠️ The arr adapters
#: share one form, and its example is Radarr's ``http://radarr:7878``.
PORTS = {"sonarr": 8989, "lidarr": 8686, "prowlarr": 9696, "readarr": 8787}
#: Images named after something else than the service.
ALIASES = {"pmsdocker": "plex"}
SCHEME_PORTS = {"http": 80, "https": 443}


def squash(text: str) -> str:
    """``AdGuard Home``, ``adguard-home`` and ``adguardhome`` are one name."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class Known:
    """An adapter as the inventory can recognise it."""

    kind: str
    label: str
    icon: str
    beta: bool
    scheme: str
    port: int


def known() -> dict[str, Known]:
    """Every adapter that is reached at a web address, by each name it is known by."""
    found: dict[str, Known] = {}
    for adapter in all_adapters():
        field = next((one for one in adapter.fields if one.name == "url" and one.type == "url"), None)
        if not adapter.needs_integration or field is None or not field.placeholder.startswith(("http://", "https://")):
            continue
        example = urlsplit(field.placeholder)
        try:
            port = example.port
        except ValueError:
            port = None
        entry = Known(adapter.kind, adapter.label, adapter.icon, adapter.beta, example.scheme,
                      PORTS.get(adapter.kind) or port or SCHEME_PORTS[example.scheme])
        names = {adapter.kind, adapter.label}
        if not adapter.icon.startswith("lucide:"):
            names.add(adapter.icon)
        for name in names:
            found.setdefault(squash(name), entry)
    return found


def recognise(thing: Thing, names: dict[str, Known]) -> Known | None:
    """The service this container or guest is, or None."""
    image = thing.image if thing.kind == "container" else ""
    # A helper is named after the service it helps: immich_postgres, immich_machine_learning.
    if dependencies._tokens(f"{thing.name} {guess_from_image(image)}") & dependencies.HELPERS:
        return None
    exact = {squash(guess_from_image(image)), squash(thing.name)} - {""}
    for candidate in name_candidates(image, thing.name):
        key = ALIASES.get(squash(candidate), squash(candidate))
        service = names.get(key)
        if service is None:
            continue
        if squash(candidate) in exact or not thing.ports or service.port in thing.ports:
            return service
    return None


def _host_of(engine: Integration, fallback: str) -> str:
    host = dependencies.real_address(dependencies._service_address(engine))[0]
    # A Docker engine on its socket runs where nexdeck runs; its address is not in its setting.
    if not host and engine.kind == "docker":
        return fallback
    return host


def _first_address(addresses: list[str]) -> str:
    """A guest's IPv4 address before its IPv6 one: the one people type."""
    for one in addresses:
        try:
            if ipaddress.ip_address(one).version == 4:
                return one
        except ValueError:
            continue
    return addresses[0] if addresses else ""


def address(service: Known, thing: Thing, engine: Integration, fallback: str) -> tuple[str, int, str]:
    """``(host, port, url)`` where the service answers; the url is empty when the host is not known."""
    if thing.kind == "guest":
        host, port = _first_address(list(thing.addresses or [])), service.port
    else:
        host = _host_of(engine, fallback)
        ports = sorted(thing.ports or [])
        port = service.port if not ports or service.port in ports else ports[0]
    scheme = service.scheme if port == service.port else ("https" if port in (443, 8443, 9443) else "http")
    if not host:
        return "", port, ""
    shown = f"[{host}]" if ":" in host else host
    tail = "" if SCHEME_PORTS.get(scheme) == port else f":{port}"
    return host, port, f"{scheme}://{shown}{tail}"


def _same_place(connection_host: str, connection_port: int | None, thing: Thing, names: set[str], host: str, port: int) -> bool:
    """Whether a connection already reaches this thing. In doubt, yes: better quiet than a second Sonarr."""
    if not connection_host:
        return False
    if connection_host in names:
        # The container's name on a shared Docker network: http://sonarr:8989.
        return True
    places = {host, *(thing.addresses or [])} - {""}
    try:
        ipaddress.ip_address(connection_host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        return connection_host in places and (connection_port is None or connection_port == port)
    # ⚠️ A name is not looked up here (nothing is asked of the network); only what is known already counts.
    known_as = dependencies._resolved.get(connection_host)
    if known_as is None:
        return True
    return bool(known_as[1] & places) and (connection_port is None or connection_port == port)


def ignored(db: Session) -> list[str]:
    row = db.get(Setting, SETTING)
    return [str(one) for one in (row.value or {}).get("ignored", [])] if row is not None else []


def ignore(db: Session, key: str) -> None:
    keys = [one for one in ignored(db) if one != key] + [key]
    db.merge(Setting(key=SETTING, value={"ignored": keys[-IGNORED_LIMIT:]}))


def show_again(db: Session) -> None:
    db.merge(Setting(key=SETTING, value={"ignored": []}))


def found(db: Session, fallback_host: str = "") -> dict[str, Any]:
    """What runs and could be connected: ``{"found": [...], "ignored": how many of them are hidden, "looked_at": when}``.

    ``fallback_host`` is where a Docker engine on its socket runs, as far as
    the request says (only an address, never a name).
    """
    names = known()
    connections = list(db.scalars(select(Integration)))
    engines = {row.id: row for row in connections if row.enabled}
    on = {(row.child, row.parent) for row in db.scalars(select(Relation).where(Relation.state == "on"))}
    skip = set(ignored(db))
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    hidden = 0
    for thing in db.scalars(select(Thing).order_by(Thing.name)):
        engine = engines.get(thing.integration_id)
        if engine is None or thing.state.lower() not in RUNNING:
            continue
        service = recognise(thing, names)
        if service is None:
            continue
        key = f"{service.kind}@{thing.ref}"
        host, port, url = address(service, thing, engine, fallback_host)
        same = {thing.name.lower(), *name_candidates(thing.image if thing.kind == "container" else "", thing.name)}
        taken = False
        for connection in connections:
            # A connection in the demo reaches nothing, whatever its address says.
            if connection.kind != service.kind or connection.demo:
                continue
            if (f"integration:{connection.id}", thing.ref) in on:
                taken = True
                break
            there, there_port = dependencies.address_of(dependencies._service_address(connection))
            if _same_place(there, there_port, thing, same, host, port):
                taken = True
                break
        if taken or (service.kind, url or key) in seen:
            continue
        seen.add((service.kind, url or key))
        if key in skip:
            hidden += 1
            continue
        entries.append({"key": key, "kind": service.kind, "label": service.label, "icon": service.icon, "beta": service.beta,
                        "thing": thing.kind, "name": thing.name, "engine": engine.name, "address": url})
    looked = db.scalar(select(func.max(Thing.seen_at)))
    # Counted among what is found now: an ignored container that is gone is no longer one to show again.
    return {"found": entries, "ignored": hidden, "looked_at": looked.isoformat() if looked else None}
