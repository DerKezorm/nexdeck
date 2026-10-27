"""Found in your network: services the inventory knows that have an adapter and no connection yet."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import db_session
from app.models import Relation
from app.services import dependencies, found

from .conftest import CSRF, create_user, login, setup_admin


def _connection(client: TestClient, kind: str, name: str, address: str, field: str = "") -> int:
    from app.adapters import get_adapter

    field = field or ("host" if kind == "docker" else "url")
    # Made-up values for whatever else the connection asks for; nothing here talks to it.
    config = {one.name: "x" for one in get_adapter(kind).fields if one.required}
    config[field] = address
    made = client.post("/api/v1/integrations", json={"kind": kind, "name": name, "config": config}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


def _things(integration_id: int, *things: dict) -> None:
    with db_session() as db:
        dependencies.keep(db, integration_id, list(things))


def _container(name: str, image: str, *ports: int, state: str = "running") -> dict:
    return {"kind": "container", "key": name, "name": name, "image": image, "state": state, "addresses": [], "ports": list(ports)}


def _guest(name: str, *addresses: str, state: str = "running") -> dict:
    return {"kind": "guest", "key": name, "name": name, "image": "LXC 101 · pve", "state": state, "addresses": list(addresses), "ports": []}


def _found(client: TestClient) -> dict:
    answer = client.get("/api/v1/integrations/found")
    assert answer.status_code == 200, answer.text
    return answer.json()


def _by_kind(client: TestClient) -> dict[str, str]:
    return {entry["kind"]: entry["address"] for entry in _found(client)["found"]}


def _docker(client: TestClient) -> int:
    setup_admin(client)
    return _connection(client, "docker", "Docker docker-live", "tcp://192.0.2.10:2375")


def test_a_container_is_known_by_its_image_and_answers_on_the_hosts_address_and_its_published_port(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker,
            _container("paperless", "ghcr.io/paperless-ngx/paperless-ngx:latest", 8000),
            _container("adguard", "adguard/adguardhome:latest", 3000, 53),
            _container("sonarr-4k", "lscr.io/linuxserver/sonarr:latest", 8990))
    entries = _found(client)["found"]
    assert {entry["kind"]: entry["address"] for entry in entries} == {
        "paperless": "http://192.0.2.10:8000",
        "adguard": "http://192.0.2.10:3000",
        # Published on another port than Sonarr's own: that port, the one that answers.
        "sonarr": "http://192.0.2.10:8990",
    }
    paperless = next(entry for entry in entries if entry["kind"] == "paperless")
    assert paperless | {"key": "", "icon": ""} == {"key": "", "kind": "paperless", "label": "Paperless-ngx", "icon": "", "beta": False,
                                                  "thing": "container", "name": "paperless", "engine": "Docker docker-live",
                                                  "address": "http://192.0.2.10:8000"}


def test_the_arr_services_have_their_own_ports_not_the_one_of_their_shared_form(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker, _container("prowlarr", "lscr.io/linuxserver/prowlarr", 9696), _container("lidarr", "lscr.io/linuxserver/lidarr", 8686, 9999))
    assert _by_kind(client) == {"prowlarr": "http://192.0.2.10:9696", "lidarr": "http://192.0.2.10:8686"}


def test_a_container_on_the_host_network_takes_the_services_own_port(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker, _container("homeassistant", "ghcr.io/home-assistant/home-assistant:stable"))
    assert _by_kind(client) == {"homeassistant": "http://192.0.2.10:8123"}


def test_a_name_that_only_fits_when_cut_needs_the_services_own_port(client: TestClient) -> None:
    docker = _docker(client)
    # grafana-agent is named after what it serves and is not Grafana; immich-server is Immich, on Immich's port.
    _things(docker, _container("agent", "grafana/grafana-agent:latest", 12345), _container("immich_server", "ghcr.io/immich-app/immich-server:release", 2283))
    assert _by_kind(client) == {"immich": "http://192.0.2.10:2283"}


def test_helpers_and_stopped_containers_are_not_offered(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker,
            _container("immich_machine_learning", "ghcr.io/immich-app/immich-machine-learning:release", 3003),
            _container("immich_postgres", "ghcr.io/immich-app/postgres:14", 5432),
            # Publishes nothing, so no port tells it apart: only its name says it helps Immich.
            _container("immich_redis", "docker.io/valkey/valkey:8"),
            _container("jellyfin", "jellyfin/jellyfin", 8096, state="exited"),
            _container("whoami", "traefik/whoami", 8081))
    assert _found(client)["found"] == []


def test_a_guest_is_known_by_its_name_and_answers_on_its_own_address(client: TestClient) -> None:
    setup_admin(client)
    proxmox = _connection(client, "proxmox", "pve", "https://192.0.2.2:8006")
    _things(proxmox, _guest("pihole", "fe80::1", "192.0.2.53"), _guest("nextcloud"))
    entries = _found(client)["found"]
    # A guest without an address cannot say where it answers, and is still worth a word.
    assert {entry["kind"]: entry["address"] for entry in entries} == {"pihole": "http://192.0.2.53", "nextcloud": ""}
    assert {entry["thing"] for entry in entries} == {"guest"}


def test_what_is_connected_already_is_not_offered(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker,
            _container("sonarr", "lscr.io/linuxserver/sonarr", 8989),
            _container("radarr", "lscr.io/linuxserver/radarr", 7878),
            _container("plex", "plexinc/pms-docker", 32400),
            _container("pihole-2", "pihole/pihole", 8053))
    _connection(client, "sonarr", "Sonarr", "http://192.0.2.10:8989")  # by its address
    _connection(client, "radarr", "Radarr", "http://radarr:7878")  # by its name on a shared Docker network
    _connection(client, "pihole", "Pi-hole one", "http://192.0.2.10:8080")  # the same host, another port: another Pi-hole
    # Through a proxy on another address: only the relation of the inventory says it is this one.
    plex = _connection(client, "plex", "Plex", "https://192.0.2.99", field="url")
    with db_session() as db:
        db.add(Relation(child=f"integration:{plex}", parent=f"container:{docker}:plex", origin="manual", state="on"))
    assert _by_kind(client) == {"pihole": "http://192.0.2.10:8053"}


def test_a_connection_in_the_demo_connects_nothing(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker, _container("mealie", "ghcr.io/mealie-recipes/mealie", 9925))
    made = client.post("/api/v1/integrations", json={"kind": "mealie", "name": "Mealie (demo)", "config": {"url": "http://mealie:9925"}, "demo": True}, headers=CSRF)
    assert made.status_code == 201, made.text
    assert _by_kind(client) == {"mealie": "http://192.0.2.10:9925"}


def test_a_connection_by_a_name_nobody_looked_up_counts_as_this_one(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker, _container("mealie", "ghcr.io/mealie-recipes/mealie", 9925))
    dependencies._resolved.pop("food.example.com", None)
    _connection(client, "mealie", "Mealie", "https://food.example.com")
    # Nothing is asked of the network; in doubt it is taken as connected, better quiet than a second Mealie.
    assert _by_kind(client) == {}


def test_ignoring_is_kept_and_showing_again_brings_everything_back(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker, _container("mealie", "ghcr.io/mealie-recipes/mealie", 9925), _container("paperless", "paperless-ngx/paperless-ngx", 8000))
    key = next(entry["key"] for entry in _found(client)["found"] if entry["kind"] == "mealie")
    assert client.post("/api/v1/integrations/found/ignore", json={"key": key}, headers=CSRF).status_code == 204
    after = _found(client)
    assert [entry["kind"] for entry in after["found"]] == ["paperless"] and after["ignored"] == 1
    # Kept across what the inventory finds next.
    _things(docker, _container("mealie", "ghcr.io/mealie-recipes/mealie", 9925), _container("paperless", "paperless-ngx/paperless-ngx", 8000))
    assert [entry["kind"] for entry in _found(client)["found"]] == ["paperless"]
    assert client.delete("/api/v1/integrations/found/ignore", headers=CSRF).status_code == 204
    assert sorted(entry["kind"] for entry in _found(client)["found"]) == ["mealie", "paperless"]


def test_without_an_inventory_nothing_is_found_and_nothing_is_asked(client: TestClient) -> None:
    setup_admin(client)
    assert _found(client) == {"found": [], "ignored": 0, "looked_at": None}


def test_only_administrators_see_what_was_found(client: TestClient) -> None:
    docker = _docker(client)
    _things(docker, _container("mealie", "ghcr.io/mealie-recipes/mealie", 9925))
    create_user(client, "sam")
    login(client, "sam", "another-long-password")
    assert client.get("/api/v1/integrations/found").status_code == 403
    assert client.post("/api/v1/integrations/found/ignore", json={"key": "mealie@x"}, headers=CSRF).status_code == 403


def test_a_docker_engine_on_its_socket_takes_the_address_the_browser_reached(client: TestClient) -> None:
    setup_admin(client)
    docker = _connection(client, "docker", "Docker here", "unix:///var/run/docker.sock")
    _things(docker, _container("mealie", "ghcr.io/mealie-recipes/mealie", 9925))
    with db_session() as db:
        assert [entry["address"] for entry in found.found(db, "192.0.2.10")["found"]] == ["http://192.0.2.10:9925"]
        assert [entry["address"] for entry in found.found(db, "")["found"]] == [""]
    # A name or the machine itself is not an address to give: the test client is "testserver".
    assert [entry["address"] for entry in _found(client)["found"]] == [""]


def test_every_adapter_with_a_web_address_is_known_with_a_port() -> None:
    names = found.known()
    assert names["sonarr"].port == 8989 and names["plex"].port == 32400
    assert names["adguardhome"].kind == "adguard" and names["nginxproxymanager"].kind == "npm"
    assert names["truenas"].scheme == "https" and names["truenas"].port == 443
    # A Docker engine is reached at a socket, a mail server by IMAP: neither is offered from a container.
    assert all(entry.kind not in ("docker", "imap") for entry in names.values())
