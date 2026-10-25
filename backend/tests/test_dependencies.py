"""What runs on what (roadmap M5, 25.10.2026): found from addresses, proposed from names, and one message when a host goes down."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import WidgetData
from app.adapters.docker import container_thing
from app.db import db_session
from app.models import HealthCheck, Notice, Relation, Thing
from app.services import dependencies, impact, notify
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin


def _connection(client: TestClient, kind: str, name: str, address: str) -> int:
    from app.adapters import get_adapter

    field = "host" if kind == "docker" else "url"
    # Made-up values for whatever else the connection asks for; nothing here talks to it.
    config = {one.name: "x" for one in get_adapter(kind).fields if one.required}
    config[field] = address
    made = client.post("/api/v1/integrations", json={"kind": kind, "name": name, "config": config}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


def _things(integration_id: int, *found: dict) -> None:
    with db_session() as db:
        dependencies.keep(db, integration_id, list(found))


def _match(hosts: dict[int, list[str]]) -> None:
    with db_session() as db:
        dependencies.match(db, hosts)


def _relations() -> set[tuple[str, str, str, str]]:
    with db_session() as db:
        return {(row.child, row.parent, row.origin, row.state) for row in db.scalars(select(Relation))}


def _container(name: str, *ports: int, state: str = "running", image: str = "") -> dict:
    return {"kind": "container", "key": name, "name": name, "image": image or f"example/{name}:latest", "state": state, "addresses": [], "ports": list(ports)}


# -- reading addresses and what engines say -----------------------------------------------------


def test_an_address_names_its_host_and_its_port() -> None:
    assert dependencies.address_of("http://Plex.lan:32400/web") == ("plex.lan", 32400)
    assert dependencies.address_of("https://nas.example.com") == ("nas.example.com", 443)
    assert dependencies.address_of("tcp://10.0.0.5:2375") == ("10.0.0.5", 2375)
    assert dependencies.address_of("10.0.0.7:8080") == ("10.0.0.7", 8080)
    assert dependencies.address_of("") == ("", None)


def test_a_docker_container_brings_the_ports_it_publishes() -> None:
    row = {"Names": ["/plex"], "Image": "plexinc/pms-docker", "State": "running",
           "Ports": [{"IP": "0.0.0.0", "PrivatePort": 32400, "PublicPort": 32400, "Type": "tcp"}, {"PrivatePort": 1900, "Type": "udp"}],
           "HostConfig": {"NetworkMode": "bridge"}}
    assert container_thing(row) == {"kind": "container", "key": "plex", "name": "plex", "image": "plexinc/pms-docker", "state": "running",
                                    "addresses": [], "ports": [32400], "host_network": False}


async def test_a_synology_reads_only_the_ports_from_a_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.synology import SynologyAdapter

    asked: list[tuple[str, dict]] = []

    async def api(_self: object, _config: dict, _ctx: object, api: str, method: str, version: str = "1", extra: dict | None = None, **_: object) -> dict:
        asked.append((method, extra or {}))
        if method == "list":
            return {"containers": [{"name": "nexbeat", "image": "ghcr.io/derkezorm/nexbeat", "status": "running"}]}
        return {"profile": {"port_bindings": [{"container_port": 8000, "host_port": 8030, "type": "tcp"}], "use_host_network": False,
                            "env_variables": [{"key": "SECRET", "value": "hunter2"}]}}

    monkeypatch.setattr(SynologyAdapter, "_api", api)
    found = await SynologyAdapter().things({"url": "https://nas.example.com:5001"}, None)  # type: ignore[arg-type]
    assert found == {"host": ["nas.example.com"], "things": [{"kind": "container", "key": "nexbeat", "name": "nexbeat", "image": "ghcr.io/derkezorm/nexbeat",
                                                             "state": "running", "addresses": [], "ports": [8030], "host_network": False}]}
    assert "hunter2" not in json.dumps(found)
    assert asked[1] == ("get", {"name": '"nexbeat"'}), "the name goes in as a JSON string, as measured"


async def test_proxmox_names_container_addresses_and_stops_asking_a_refused_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.base import AdapterError
    from app.adapters.proxmox import ProxmoxAdapter

    asked: list[str] = []

    async def get(_self: object, _config: dict, _ctx: object, path: str, cache: float = 5) -> object:
        asked.append(path)
        if path.startswith("/cluster/resources"):
            return [{"vmid": 201, "name": "docker-live", "type": "lxc", "node": "pve", "status": "running"},
                    {"vmid": 100, "name": "windows", "type": "qemu", "node": "pve", "status": "running"},
                    {"vmid": 101, "name": "media", "type": "qemu", "node": "pve", "status": "running"},
                    {"vmid": 900, "name": "tpl", "type": "qemu", "node": "pve", "status": "stopped", "template": 1}]
        if path.endswith("/interfaces"):
            return [{"name": "lo", "inet": "127.0.0.1/8"}, {"name": "eth0", "inet": "10.0.0.65/24"}]
        raise AdapterError("The service rejected the credentials.", code="auth_failed")

    monkeypatch.setattr(ProxmoxAdapter, "_get", get)
    found = await ProxmoxAdapter().things({"url": "https://pve.example.com:8006"}, None)  # type: ignore[arg-type]
    assert [(one["key"], one["addresses"]) for one in found["things"]] == [("201", ["10.0.0.65"]), ("100", []), ("101", [])]
    assert sum(1 for path in asked if "/agent/" in path) == 1, "after the first refusal no other VM is asked"


# -- matching ---------------------------------------------------------------------------------------------


def test_the_same_address_and_port_is_certain_and_a_proxy_port_or_a_name_is_only_proposed(client: TestClient) -> None:
    setup_admin(client)
    engine = _connection(client, "docker", "docker-live", "tcp://10.0.0.65:2375")
    plex = _connection(client, "plex", "Plex", "http://10.0.0.65:32400")
    behind = _connection(client, "sonarr", "Sonarr", "https://10.0.0.65")
    named = _connection(client, "radarr", "Radarr", "http://radarr.example.invalid:7878")
    beside = _connection(client, "uptimekuma", "Kuma", "http://10.0.0.65:3001")
    _things(engine, _container("plex", 32400), _container("caddy", 443), _container("radarr"))
    _match({engine: ["10.0.0.65"]})
    found = _relations()
    beside_on = {parent for child, parent, _origin, _state in found if child == f"integration:{beside}"}
    assert beside_on == {f"integration:{engine}"}, "a port no container publishes is the host's, not some container's"
    assert (f"integration:{plex}", f"container:{engine}:plex", "auto", "on") in found
    assert (f"integration:{behind}", f"container:{engine}:caddy", "suggested", "suggested") in found
    assert (f"integration:{named}", f"container:{engine}:radarr", "suggested", "suggested") in found
    assert not any(child == f"integration:{engine}" for child, *_ in found), "an engine does not run on its own containers"


def test_a_service_on_a_hosts_address_without_a_container_runs_on_the_host(client: TestClient) -> None:
    setup_admin(client)
    nas = _connection(client, "synology", "NAS", "https://10.0.0.9:5001")
    photos = _connection(client, "immich", "Immich", "http://10.0.0.9:2283")
    _match({})
    assert (f"integration:{photos}", f"integration:{nas}", "auto", "on") in _relations()


def test_a_guest_with_the_address_is_certain_and_a_no_is_never_asked_again(client: TestClient) -> None:
    setup_admin(client)
    pve = _connection(client, "proxmox", "PVE", "https://10.0.0.2:8006")
    engine = _connection(client, "docker", "docker-live", "tcp://10.0.0.65:2375")
    _things(pve, {"kind": "guest", "key": "201", "name": "docker-live", "image": "LXC 201", "state": "running", "addresses": ["10.0.0.65"], "ports": []})
    _things(engine, _container("grafana", image="grafana/grafana"))
    named = _connection(client, "grafana", "Grafana", "http://grafana.example.invalid:3000")
    _match({pve: ["10.0.0.2"], engine: ["10.0.0.65"]})
    assert (f"integration:{engine}", f"guest:{pve}:201", "auto", "on") in _relations()
    with db_session() as db:
        proposal = db.scalar(select(Relation).where(Relation.child == f"integration:{named}"))
        proposal.state = "rejected"
    _match({pve: ["10.0.0.2"], engine: ["10.0.0.65"]})
    assert (f"integration:{named}", f"container:{engine}:grafana", "suggested", "rejected") in _relations()


def test_behind_a_reverse_proxy_an_address_names_no_host(client: TestClient) -> None:
    """⚠️ Measured on 25.10.2026: everything behind one proxy was put on Portainer and Proxmox at once, and those two on each other."""
    setup_admin(client)
    pve = _connection(client, "proxmox", "Proxmox VE", "https://10.0.0.159")
    portainer = _connection(client, "portainer", "Portainer", "https://10.0.0.159")
    wiki = _connection(client, "nexlore", "nexlore", "https://10.0.0.159")
    proxy = _connection(client, "npm", "Nginx Proxy Manager", "http://10.0.0.159:81")
    _things(pve, {"kind": "guest", "key": "100", "name": "docker-dev", "image": "VM 100 · proxmox", "state": "running", "addresses": ["10.0.0.159"], "ports": []})
    _match({pve: ["10.0.0.159"], portainer: ["10.0.0.159"]})
    certain = {(child, parent) for child, parent, origin, _state in _relations() if origin == "auto"}
    assert certain == {(f"integration:{proxy}", f"guest:{pve}:100")}, "only the proxy itself, on its own port, runs where the address points"
    assert not any(child == f"integration:{wiki}" for child, *_ in _relations())


def test_a_host_reached_through_a_proxy_carries_nothing_by_that_address(client: TestClient) -> None:
    setup_admin(client)
    portainer = _connection(client, "portainer", "Portainer", "https://10.0.0.159")
    proxy = _connection(client, "npm", "Nginx Proxy Manager", "http://10.0.0.159:81")
    _match({portainer: ["10.0.0.159"]})
    assert not any(child == f"integration:{proxy}" for child, *_ in _relations()), "the proxy does not run on Portainer"


def test_what_was_found_or_proposed_before_goes_when_it_no_longer_fits(client: TestClient) -> None:
    """The first matcher on 25.10.2026 wrote wrong relations into docker-live; the next round must take them away."""
    setup_admin(client)
    portainer = _connection(client, "portainer", "Portainer", "https://10.0.0.159")
    wiki = _connection(client, "nexlore", "nexlore", "https://10.0.0.159")
    _things(portainer, _container("nexlore-old", image="example/other"))
    with db_session() as db:
        db.add(Relation(child=f"integration:{wiki}", parent=f"integration:{portainer}", origin="auto", state="on"))
        db.add(Relation(child=f"integration:{wiki}", parent=f"container:{portainer}:nexlore-old", origin="suggested", state="suggested"))
        db.add(Relation(child=f"integration:{portainer}", parent=f"container:{portainer}:nexlore-old", origin="suggested", state="rejected"))
    _things(portainer, _container("nexlore-old", image="example/other"))
    with db_session() as db:
        db.get(Thing, db.scalar(select(Thing.id).where(Thing.name == "nexlore-old"))).name = "something-else"
    _match({portainer: ["10.0.0.159"]})
    assert _relations() == {(f"integration:{portainer}", f"container:{portainer}:nexlore-old", "suggested", "rejected")}


def test_a_service_is_proposed_on_its_main_container_never_on_a_helper(client: TestClient) -> None:
    """⚠️ Seen on 25.10.2026: Immich "probably runs on" immich_postgres, immich_redis and immich_machine_learning."""
    setup_admin(client)
    engine = _connection(client, "docker", "docker-dev", "tcp://10.0.0.66:2375")
    _things(engine, _container("immich_server"), _container("immich_postgres"), _container("immich_redis"), _container("immich_machine_learning"),
            _container("authentik-server-1"), _container("authentik-worker-1"), _container("authentik-postgresql-1"),
            _container("paperless_ngx"), _container("paperless_redis"), _container("seerr-web"), _container("seerr-cli"))
    photos = _connection(client, "immich", "Immich", "http://photos.example.invalid:2283")
    login_service = _connection(client, "authentik", "authentik", "https://auth.example.invalid:9443")
    papers = _connection(client, "paperless", "Paperless", "http://papers.example.invalid:8000")
    requests = _connection(client, "seerr", "Seerr", "http://requests.example.invalid:5055")
    _match({engine: ["10.0.0.66"]})
    proposed = {(child, parent) for child, parent, origin, _state in _relations() if origin == "suggested"}
    assert {parent for child, parent in proposed if child == f"integration:{papers}"} == {f"container:{engine}:paperless_ngx"}, "no main one, still no helper"
    assert {parent for child, parent in proposed if child == f"integration:{requests}"} == {f"container:{engine}:seerr-web"}, "no helper, the main one"
    assert {parent for child, parent in proposed if child == f"integration:{photos}"} == {f"container:{engine}:immich_server"}
    assert {parent for child, parent in proposed if child == f"integration:{login_service}"} == {f"container:{engine}:authentik-server-1"}


def test_an_app_tile_of_a_connected_service_hangs_on_the_connection(client: TestClient) -> None:
    """⚠️ Seen on 25.10.2026: "Jellyfin probably runs on jellyfin" twice, once for the connection and once for its tile."""
    setup_admin(client)
    engine = _connection(client, "docker", "docker-dev", "tcp://10.0.0.66:2375")
    _things(engine, _container("jellyfin"))
    media = _connection(client, "jellyfin", "Jellyfin", "https://jellyfin.example.invalid")
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    same_address = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.app", "title": "Movies", "link": "https://jellyfin.example.invalid"}, headers=CSRF).json()["widget"]
    same_name = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.app", "title": "jellyfin", "link": "https://tv.example.invalid"}, headers=CSRF).json()["widget"]
    _match({engine: ["10.0.0.66"]})
    found = _relations()
    for tile in (same_address, same_name):
        assert {(parent, origin) for child, parent, origin, _state in found if child == f"tile:{tile['id']}"} == {(f"integration:{media}", "auto")}
    assert (f"integration:{media}", f"container:{engine}:jellyfin", "suggested", "suggested") in found


@pytest.fixture
def proxied(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, int | None]]:
    """What a reverse proxy said it forwards, and a network that names 10.0.0.65 docker-live; no resolver is asked."""
    forwards: dict[str, tuple[str, int | None]] = {}
    monkeypatch.setattr(dependencies, "_forwards", forwards)
    monkeypatch.setattr(dependencies, "_named", {})
    monkeypatch.setattr(dependencies.socket, "gethostbyaddr", lambda address: ("docker-live.lan", [], [address]) if address == "10.0.0.65" else (_ for _ in ()).throw(OSError()))
    return forwards


def test_what_the_proxy_forwards_places_a_service_behind_it_in_its_container(client: TestClient, proxied: dict) -> None:
    """⚠️ Measured 25.10.2026: behind Nginx Proxy Manager every service answered on the proxy's address; the proxy knew the real one."""
    setup_admin(client)
    portainer = _connection(client, "portainer", "Portainer", "https://portainer.example.invalid")
    wiki = _connection(client, "nexlore", "nexlore", "https://wiki.example.invalid")
    _things(portainer, _container("nexlore", 8470), _container("nexlore-test", 8471))
    proxied.update({"portainer.example.invalid": ("10.0.0.65", 9443), "wiki.example.invalid": ("10.0.0.65", 8470)})
    _match({portainer: ["portainer.example.invalid"]})
    assert (f"integration:{wiki}", f"container:{portainer}:nexlore", "auto", "on") in _relations()
    proxied.clear()
    _match({portainer: ["portainer.example.invalid"]})
    assert not any(child == f"integration:{wiki}" and origin == "auto" for child, _parent, origin, _state in _relations()), "without the proxy's word it is a guess again"


def test_a_forward_to_port_80_or_443_is_as_good_as_any_other(client: TestClient, proxied: dict) -> None:
    """Once the proxy says where it goes, port 80 on the real machine is that machine's, not a proxy's."""
    setup_admin(client)
    portainer = _connection(client, "portainer", "Portainer", "https://portainer.example.invalid")
    scanner = _connection(client, "uptimekuma", "Scanner", "https://scan.example.invalid")
    _things(portainer, _container("nexscan", 80))
    proxied.update({"portainer.example.invalid": ("10.0.0.65", 443), "scan.example.invalid": ("10.0.0.65", 80)})
    _match({})
    assert (f"integration:{scanner}", f"container:{portainer}:nexscan", "auto", "on") in _relations()


def test_a_guest_without_an_address_is_known_by_its_name_on_the_network(client: TestClient, proxied: dict) -> None:
    """Proxmox gives no address for a VM whose guest agent it may not ask; the network still calls 10.0.0.65 docker-live."""
    setup_admin(client)
    pve = _connection(client, "proxmox", "Proxmox VE", "https://pve.example.invalid")
    portainer = _connection(client, "portainer", "Portainer", "https://portainer.example.invalid")
    _things(pve, {"kind": "guest", "key": "100", "name": "docker-live", "image": "VM 100 · proxmox", "state": "running", "addresses": [], "ports": []},
            {"kind": "guest", "key": "200", "name": "docker-dev", "image": "VM 200 · proxmox", "state": "running", "addresses": [], "ports": []})
    proxied.update({"portainer.example.invalid": ("10.0.0.65", 9443)})
    _match({pve: ["pve.example.invalid"], portainer: ["portainer.example.invalid"]})
    assert {(child, parent) for child, parent, origin, _state in _relations() if origin == "auto"} == {(f"integration:{portainer}", f"guest:{pve}:100")}
    machine = next(node for node in client.get("/api/v1/inventory").json()["nodes"] if node["ref"] == f"integration:{portainer}")["machine"]
    assert machine == "docker-live", "the column is called after the machine, not the connection"


async def test_the_proxy_manager_says_where_each_address_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.npm import NpmAdapter

    async def get(_self: object, _config: dict, _ctx: object, path: str, cache: float = 60, retry: bool = True) -> list:
        assert path == "/nginx/proxy-hosts"
        return [{"domain_names": ["Wiki.example.invalid", "notes.example.invalid"], "forward_host": "10.0.0.65", "forward_port": 8470, "enabled": 1},
                {"domain_names": ["old.example.invalid"], "forward_host": "10.0.0.9", "forward_port": 80, "enabled": 0},
                {"domain_names": ["nas.example.invalid"], "forward_host": "10.0.0.109", "forward_port": "5011", "enabled": True}]

    monkeypatch.setattr(NpmAdapter, "_get", get)
    found = await NpmAdapter().forwards({"url": "http://npm.example.invalid:81"}, None)  # type: ignore[arg-type]
    assert found == {"wiki.example.invalid": ("10.0.0.65", 8470), "notes.example.invalid": ("10.0.0.65", 8470), "nas.example.invalid": ("10.0.0.109", 5011)}


async def test_a_round_asks_the_proxy_and_keeps_its_word_when_it_does_not_answer(client: TestClient, monkeypatch: pytest.MonkeyPatch, proxied: dict) -> None:
    from app.adapters.base import AdapterError
    from app.adapters.npm import NpmAdapter

    setup_admin(client)
    _connection(client, "npm", "Nginx Proxy Manager", "http://10.0.0.159:81")
    answers: list[object] = [{"wiki.example.invalid": ("10.0.0.65", 8470)}, AdapterError("down", code="unreachable")]

    async def forwards(_self: object, _config: dict, _ctx: object) -> dict:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(NpmAdapter, "forwards", forwards)
    await dependencies.discover()
    assert dependencies._forwards == {"wiki.example.invalid": ("10.0.0.65", 8470)}
    await dependencies.discover()
    assert dependencies._forwards == {"wiki.example.invalid": ("10.0.0.65", 8470)}, "a proxy that does not answer keeps what it said last"


def test_two_hosts_on_one_address_are_not_put_on_each_other(client: TestClient) -> None:
    setup_admin(client)
    pve = _connection(client, "proxmox", "PVE", "https://10.0.0.5:8006")
    portainer = _connection(client, "portainer", "Portainer", "http://10.0.0.5:9000")
    _match({})
    assert not any(child in (f"integration:{pve}", f"integration:{portainer}") for child, *_ in _relations())


def test_a_found_relation_that_would_make_a_circle_is_left_out(client: TestClient) -> None:
    setup_admin(client)
    nas = _connection(client, "synology", "NAS", "https://10.0.0.9:5001")
    photos = _connection(client, "immich", "Immich", "http://10.0.0.9:2283")
    with db_session() as db:
        db.add(Relation(child=f"integration:{nas}", parent=f"integration:{photos}", origin="manual", state="on"))
    _match({})
    assert (f"integration:{photos}", f"integration:{nas}", "auto", "on") not in _relations()


def test_a_name_proposes_the_exact_container_and_not_what_it_is_built_on(client: TestClient) -> None:
    setup_admin(client)
    pve = _connection(client, "proxmox", "PVE", "https://10.0.0.2:8006")
    engine = _connection(client, "docker", "docker-dev", "tcp://10.0.0.66:2375")
    _things(engine, _container("sabnzbd", image="linuxserver/sabnzbd"), _container("ndl-sabnzbd", image="linuxserver/sabnzbd"),
            _container("skp-durchreicher", image="nginx:alpine"))
    _things(pve, {"kind": "guest", "key": "101", "name": "media", "image": "VM 101 · proxmox", "state": "running", "addresses": [], "ports": []})
    sab = _connection(client, "sabnzbd", "SABnzbd", "http://sab.example.invalid:8080")
    proxy = _connection(client, "npm", "Nginx Proxy Manager", "http://npm.example.invalid:81")
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    tile = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.app", "title": "Proxmox"}, headers=CSRF).json()["widget"]
    _match({engine: ["10.0.0.66"]})
    proposed = {(child, parent) for child, parent, origin, _state in _relations() if origin == "suggested"}
    assert {parent for child, parent in proposed if child == f"integration:{sab}"} == {f"container:{engine}:sabnzbd"}
    assert not any(child == f"integration:{proxy}" for child, _parent in proposed), "nginx is what the container is built on"
    assert not any(child == f"tile:{tile['id']}" for child, _parent in proposed), "a guest's node is not its software"


def test_a_found_relation_goes_when_the_address_changes(client: TestClient) -> None:
    setup_admin(client)
    engine = _connection(client, "docker", "docker-live", "tcp://10.0.0.65:2375")
    plex = _connection(client, "plex", "Plex", "http://10.0.0.65:32400")
    _things(engine, _container("plex", 32400))
    _match({engine: ["10.0.0.65"]})
    client.patch(f"/api/v1/integrations/{plex}", json={"config": {"url": "http://10.0.0.77:32400"}}, headers=CSRF)
    _match({engine: ["10.0.0.65"]})
    assert not any(child == f"integration:{plex}" and origin == "auto" for child, _parent, origin, _state in _relations())


def test_what_an_engine_no_longer_runs_goes_with_its_relations(client: TestClient) -> None:
    setup_admin(client)
    engine = _connection(client, "docker", "docker-live", "tcp://10.0.0.65:2375")
    _things(engine, _container("plex", 32400), _container("old"))
    with db_session() as db:
        db.add(Relation(child="tile:999", parent=f"container:{engine}:old", origin="manual", state="on"))
    _things(engine, _container("plex", 32400))
    with db_session() as db:
        assert [row.name for row in db.scalars(select(Thing))] == ["plex"]
        assert db.scalar(select(Relation).where(Relation.parent == f"container:{engine}:old")) is None


# -- down, and why ----------------------------------------------------------------------------------------


def _chain(client: TestClient) -> tuple[int, int, int]:
    setup_admin(client)
    pve = _connection(client, "proxmox", "PVE", "https://10.0.0.2:8006")
    engine = _connection(client, "docker", "docker-live", "tcp://10.0.0.65:2375")
    plex = _connection(client, "plex", "Plex", "http://10.0.0.65:32400")
    _things(pve, {"kind": "guest", "key": "201", "name": "docker-live", "image": "LXC 201", "state": "running", "addresses": ["10.0.0.65"], "ports": []})
    _things(engine, _container("plex", 32400))
    _match({pve: ["10.0.0.2"], engine: ["10.0.0.65"]})
    return pve, engine, plex


def test_the_chain_runs_from_the_service_to_the_hypervisor(client: TestClient) -> None:
    pve, engine, plex = _chain(client)
    with db_session() as db:
        assert dependencies.ancestors(db, f"integration:{plex}") == [f"container:{engine}:plex", f"integration:{engine}", f"guest:{pve}:201", f"integration:{pve}"]
        assert f"integration:{plex}" in dependencies.descendants(db, f"guest:{pve}:201")


def test_a_card_names_the_furthest_thing_that_is_down(client: TestClient) -> None:
    pve, engine, plex = _chain(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    card = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "docker.containers", "integration_id": engine}, headers=CSRF).json()["widget"]
    collector.unschedule(card["id"])
    with db_session() as db:
        assert dependencies.cause(db, f"integration:{plex}") == ""
    live.set(card["id"], WidgetData(status="unknown", error="Connection refused"))
    with db_session() as db:
        assert dependencies.is_down(db, f"container:{engine}:plex")
        assert dependencies.cause(db, f"integration:{plex}") == "docker-live"
        db.scalar(select(Thing).where(Thing.ref == f"guest:{pve}:201")).state = "stopped"
    with db_session() as db:
        assert dependencies.cause(db, f"integration:{plex}") == "docker-live", "the guest, named like the engine"
        assert dependencies.ancestors(db, f"integration:{plex}")[-2] == f"guest:{pve}:201"


def test_a_tile_whose_check_fails_is_down(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    tile = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.app", "title": "Wiki"}, headers=CSRF).json()["widget"]
    with db_session() as db:
        db.add(HealthCheck(widget_id=tile["id"], target="http://10.0.0.8", enabled=True, last_ok=False))
    with db_session() as db:
        assert dependencies.is_down(db, f"tile:{tile['id']}")


# -- one message ------------------------------------------------------------------------------------------


def _notices() -> list[str]:
    with db_session() as db:
        return [row.title for row in db.scalars(select(Notice).where(Notice.event.in_(("outage", "widget_broken", "recovery"))))]


async def test_a_host_going_down_is_one_message_and_what_hangs_on_it_stays_quiet(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pve, engine, plex = _chain(client)
    monkeypatch.setattr(dependencies, "HOLD_SECONDS", 0.01)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    engine_card = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "docker.containers", "integration_id": engine}, headers=CSRF).json()["widget"]
    plex_card = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "plex.nowplaying", "integration_id": plex}, headers=CSRF).json()["widget"]
    for card in (engine_card, plex_card):
        collector.unschedule(card["id"])
        live.set(card["id"], WidgetData(status="unknown", error="Connection refused"))
    notify.emit("widget_broken", "Plex stopped working", "refused", level="warn", integration_id=plex, subject=f"integration:{plex}")
    notify.emit("widget_broken", "docker-live stopped working", "refused", level="warn", integration_id=engine, subject=f"integration:{engine}")
    assert _notices() == [], "both wait for their cause"
    await asyncio.sleep(0.1)
    told = _notices()
    assert told == ["docker-live is down, 1 service affected"]
    with db_session() as db:
        assert "Affected: Plex" in db.scalar(select(Notice.body).where(Notice.title == told[0]))
    notify.emit("recovery", "Plex is back", "", integration_id=plex, subject=f"integration:{plex}")
    assert _notices() == told, "a return nobody was told the leaving of is not told either"


async def test_something_on_its_own_is_told_at_once(client: TestClient) -> None:
    setup_admin(client)
    alone = _connection(client, "radarr", "Radarr", "http://10.9.9.9:7878")
    notify.emit("widget_broken", "Radarr stopped working", "refused", level="warn", integration_id=alone, subject=f"integration:{alone}")
    assert _notices() == ["Radarr stopped working"]


# -- what a button hits -------------------------------------------------------------------------------------


def test_a_guest_reboot_names_what_runs_in_it(client: TestClient) -> None:
    pve, _engine, _plex = _chain(client)
    fact = impact.hanging_on(f"guest:{pve}:201")
    assert fact == {"fact": "depends", "count": 2, "names": ["Plex", "docker-live"], "containers": 1}
    assert impact.hanging_on("guest:999:1") is None


# -- the inventory route -------------------------------------------------------------------------------------


def test_relations_by_hand_confirm_and_say_no(client: TestClient) -> None:
    pve, engine, plex = _chain(client)
    wiki = _connection(client, "radarr", "Radarr", "http://radarr.example.invalid")
    made = client.post("/api/v1/relations", json={"child": f"integration:{wiki}", "parent": f"guest:{pve}:201"}, headers=CSRF)
    assert made.status_code == 201 and made.json()["origin"] == "manual"
    circle = client.post("/api/v1/relations", json={"child": f"guest:{pve}:201", "parent": f"integration:{plex}"}, headers=CSRF)
    assert circle.status_code == 400 and circle.json()["detail"]["code"] == "circle"
    nowhere = client.post("/api/v1/relations", json={"child": f"integration:{wiki}", "parent": "guest:1:404"}, headers=CSRF)
    assert nowhere.status_code == 404
    found = next(one for one in client.get("/api/v1/inventory").json()["relations"] if one["origin"] == "auto" and one["child"] == f"integration:{plex}")
    assert client.delete(f"/api/v1/relations/{found['id']}", headers=CSRF).status_code == 204
    assert (f"integration:{plex}", f"container:{engine}:plex", "auto", "rejected") in _relations(), "kept as a no, so it is not found again"
    assert client.delete(f"/api/v1/relations/{made.json()['id']}", headers=CSRF).status_code == 204
    assert not any(child == f"integration:{wiki}" for child, *_ in _relations()), "one set by hand simply goes"


def test_the_inventory_lists_nodes_with_their_state(client: TestClient) -> None:
    pve, engine, _plex = _chain(client)
    view = client.get("/api/v1/inventory").json()
    kinds = {node["ref"]: node["kind"] for node in view["nodes"]}
    assert kinds[f"guest:{pve}:201"] == "guest" and kinds[f"container:{engine}:plex"] == "container"
    guest = next(node for node in view["nodes"] if node["ref"] == f"guest:{pve}:201")
    assert guest["detail"] == "10.0.0.65" and guest["parent"] == f"integration:{pve}"


def test_members_see_no_inventory(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "member")
    login(client, "member", "another-long-password")
    for method, path in (("get", "/api/v1/inventory"), ("post", "/api/v1/inventory/refresh"), ("post", "/api/v1/relations")):
        assert client.request(method.upper(), path, json={"child": "integration:1", "parent": "integration:2"}, headers=CSRF).status_code == 403, path
