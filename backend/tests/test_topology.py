"""Topology pages: a UniFi network as a plan, with the traffic on every link.

The console answers are shaped after one measured on 19.10.2026 (Network 9,
22 devices): ``stat/device`` with port counters and uplinks, ``stat/sta`` with
the switch port of every wired client. Names, addresses and numbers here are
made up.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services import topology
from app.services.topology import Meter, build

from .conftest import CSRF, create_user, login, setup_admin

GW, CORE, ATTIC, MESH, CAMERA, NAS = "aa:00:00:00:00:01", "aa:00:00:00:00:02", "aa:00:00:00:00:03", "aa:00:00:00:00:04", "bb:00:00:00:00:10", "bb:00:00:00:00:11"


def _port(idx: int, sent: float, received: float, *, rate_sent: float = 0.0, rate_received: float = 0.0, speed: int = 1000, name: str = "") -> dict:
    return {"port_idx": idx, "up": True, "speed": speed, "name": name or f"Port {idx}",
            "tx_bytes": sent, "rx_bytes": received, "tx_bytes-r": rate_sent, "rx_bytes-r": rate_received}


def _console(t: float, core_ports: list[dict], *, gateway_wan: tuple[float, float] = (5e9, 1e9), core_seen: float | None = None,
             mesh_online: bool = True, gw_rates: tuple[float, float] = (0.0, 0.0)) -> list[dict]:
    """Gateway, a core switch on its port 10, a switch on the core's port 12, and a mesh AP on the attic switch's AP."""
    return [
        {"mac": GW, "type": "udm", "name": "Gateway", "model": "UDMPROSE", "state": 1, "last_seen": t, "uptime": 3600,
         "port_table": [_port(10, 9e9, 2e9, speed=10000)],
         "uplink": {"type": "wire", "port_idx": 9, "speed": 1000, "rx_bytes": gateway_wan[0], "tx_bytes": gateway_wan[1],
                    "rx_bytes-r": gw_rates[0], "tx_bytes-r": gw_rates[1]}},
        {"mac": CORE, "type": "usw", "name": "Core", "model": "USPM48", "state": 1, "last_seen": core_seen if core_seen is not None else t,
         "port_table": core_ports, "uplink": {"type": "wire", "uplink_mac": GW, "uplink_remote_port": 10, "port_idx": 49, "rx_bytes": 0, "tx_bytes": 0}},
        {"mac": ATTIC, "type": "uap", "name": "Attic AP", "model": "U7LT", "state": 1, "last_seen": t, "num_sta": 7,
         "uplink": {"type": "wire", "uplink_mac": CORE, "uplink_remote_port": 12, "port_idx": 1}},
        {"mac": MESH, "type": "uap", "name": "Garden AP", "model": "UMSH", "state": 1 if mesh_online else 0, "last_seen": t if mesh_online else t - 7200,
         "uplink": {"type": "wireless", "uplink_mac": ATTIC, "rx_bytes": 3e6 + t * 1000, "tx_bytes": 1e6 + t * 100, "tx_rate": 433000, "rx_rate": 300000}},
    ]


STATIONS = [
    {"mac": CAMERA, "name": "Front door camera", "is_wired": True, "sw_mac": CORE, "sw_port": 20, "ip": "192.168.1.50"},
    {"mac": NAS, "hostname": "nas01", "is_wired": True, "sw_mac": CORE, "sw_port": 26, "ip": "192.168.1.10"},
    # ⚠️ What UniFi sometimes says about the device behind an uplink: a client
    # on the port that leads to the attic AP. It is not a client port.
    {"mac": "bb:00:00:00:00:12", "name": "ghost", "is_wired": True, "sw_mac": CORE, "sw_port": 12},
    {"mac": "cc:00:00:00:00:13", "name": "phone", "is_wired": False, "ap_mac": ATTIC},
]


def _link(data: dict, link_id: str) -> dict:
    return next(link for link in data["links"] + data["client_links"] if link["id"] == link_id)


def _core(sent12: float, received12: float, sent20: float = 0.0, received20: float = 0.0, **rates: float) -> list[dict]:
    return [_port(12, sent12, received12, **rates), _port(20, sent20, received20), _port(26, 0, 0, speed=10000)]


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


def test_a_link_carries_what_the_parent_port_counted_since_the_last_report() -> None:
    meter = Meter()
    build(_console(1000, _core(1_000_000, 500_000)), STATIONS, [], {}, meter, 1000)
    data = build(_console(1060, _core(1_000_000 + 60 * 125_000, 500_000 + 60 * 12_500)), STATIONS, [], {}, meter, 1060)
    attic = _link(data, f"link:{ATTIC}")
    # Sent by the core's port 12 is the way down to the AP: 125 kB/s is 1 Mbit/s.
    assert attic["down"] == pytest.approx(1e6) and attic["up"] == pytest.approx(1e5)
    assert attic["meter"] == CORE and attic["port_a"] == {"index": 12, "name": ""}


def test_a_report_whose_counters_stand_still_is_no_measurement() -> None:
    """Measured: a switch now and then reports every port unchanged, while the
    other end of the cable carries traffic. Taken at its word that is a minute
    of zero, and the next report would claim twice the real rate."""
    meter = Meter()
    build(_console(1000, _core(1_000_000, 500_000)), STATIONS, [], {}, meter, 1000)
    first = build(_console(1060, _core(1_000_000 + 60 * 125_000, 500_000)), STATIONS, [], {}, meter, 1060)
    standing = build(_console(1130, _core(1_000_000 + 60 * 125_000, 500_000)), STATIONS, [], {}, meter, 1130)
    assert _link(standing, f"link:{ATTIC}")["down"] == pytest.approx(1e6), "the frozen report keeps the last value"
    assert _link(standing, f"link:{ATTIC}")["at"] == 1060, "and its age keeps counting from the last real one"
    after = build(_console(1200, _core(1_000_000 + 200 * 125_000, 500_000)), STATIONS, [], {}, meter, 1200)
    # 140 seconds of bytes over the 140 seconds since the last real report: still 1 Mbit/s.
    assert _link(after, f"link:{ATTIC}")["down"] == pytest.approx(1e6)
    assert _link(first, f"link:{ATTIC}")["history"]["down"] == [pytest.approx(1e6)]
    assert len(_link(after, f"link:{ATTIC}")["history"]["down"]) == 2
    # The frozen report was still a report: the core reports every 60 to 70 seconds, not every 140.
    assert topology.every(meter, CORE) == 70


def test_the_same_report_twice_changes_nothing() -> None:
    meter = Meter()
    build(_console(1000, _core(1_000_000, 0)), STATIONS, [], {}, meter, 1000)
    build(_console(1060, _core(1_000_000 + 60 * 125_000, 0)), STATIONS, [], {}, meter, 1060)
    again = build(_console(1060, _core(1_000_000 + 60 * 125_000, 0)), STATIONS, [], {}, meter, 1065)
    assert _link(again, f"link:{ATTIC}")["down"] == pytest.approx(1e6)
    assert len(_link(again, f"link:{ATTIC}")["history"]["down"]) == 1


def test_a_device_without_counters_counts_one_report_once() -> None:
    """An access point on a cable has no counters of its own; only its last_seen tells a new report from an old one."""
    meter = Meter()
    ap = {"mac": ATTIC, "type": "uap", "last_seen": 1000, "uplink": {"type": "wire", "uplink_mac": CORE}}
    assert topology.observe(meter, ap) is True
    assert topology.observe(meter, dict(ap)) is False
    assert topology.observe(meter, {**ap, "last_seen": 1070}) is True
    assert topology.every(meter, ATTIC) == 70


def test_counters_that_start_again_after_a_restart_never_make_a_negative_rate() -> None:
    meter = Meter()
    build(_console(1000, _core(9e9, 9e9)), STATIONS, [], {}, meter, 1000)
    restarted = build(_console(1060, _core(1000, 1000, rate_sent=250.0, rate_received=0.0)), STATIONS, [], {}, meter, 1060)
    assert _link(restarted, f"link:{ATTIC}")["down"] == pytest.approx(2000), "UniFi's own rate stands in for one report"


def test_a_first_report_that_reads_zero_everywhere_is_unknown_not_zero() -> None:
    data = build(_console(1000, _core(1e6, 1e6)), STATIONS, [], {}, Meter(), 1000)
    assert _link(data, f"link:{ATTIC}")["down"] is None


def test_the_internet_line_and_a_mesh_link_count_what_arrives_as_the_way_down() -> None:
    meter = Meter()
    build(_console(1000, _core(1, 1), gateway_wan=(1e9, 1e8)), STATIONS, [], {}, meter, 1000)
    data = build(_console(1010, _core(2, 2), gateway_wan=(1e9 + 10 * 2_500_000, 1e8 + 10 * 250_000)), STATIONS, [], {}, meter, 1010)
    wan = _link(data, "link:internet")
    assert (wan["down"], wan["up"]) == (pytest.approx(20e6), pytest.approx(2e6))
    assert wan["a"] == "internet" and wan["meter"] == GW and wan["kind"] == "wan" and wan["speed"] == 1e9
    mesh = _link(data, f"link:{MESH}")
    assert mesh["kind"] == "wifi" and mesh["meter"] == MESH and mesh["a"] == ATTIC
    assert (mesh["down"], mesh["up"]) == (pytest.approx(8000), pytest.approx(800))
    assert mesh["speed"] == 433e6


# ---------------------------------------------------------------------------
# What stands on the plan
# ---------------------------------------------------------------------------


def test_devices_hang_on_their_uplink_and_say_how_they_stand() -> None:
    data = build(_console(1000, _core(1, 1), mesh_online=False), STATIONS, [{"subsystem": "wan", "isp_name": "Example Fibre", "status": "ok"}],
                 {CORE: "USW Pro Max 48"}, Meter(), 1000)
    nodes = {node["id"]: node for node in data["nodes"]}
    assert nodes["internet"]["model"] == "Example Fibre"
    assert nodes[CORE]["model"] == "USW Pro Max 48", "the Integration API's name wins over the code"
    assert nodes[GW]["model"] == "UDMPROSE"
    assert nodes[ATTIC]["wifi_clients"] == 7 and nodes[CORE]["wired_clients"] == 2
    assert nodes[MESH]["status"] == "offline" and nodes[MESH]["facts"]["last_seen_ago"] == 7200
    mesh = _link(data, f"link:{MESH}")
    assert mesh["state"] == "down" and mesh["down"] is None
    assert [link["b"] for link in data["links"]] == [GW, CORE, ATTIC, MESH]


def test_wired_clients_know_their_port_and_the_uplink_port_is_no_client() -> None:
    data = build(_console(1000, _core(1, 1)), STATIONS, [], {}, Meter(), 1000)
    clients = {client["id"]: client for client in data["clients"]}
    assert set(clients) == {CAMERA, NAS}
    assert clients[NAS]["name"] == "nas01" and clients[NAS]["kind"] == "nas" and clients[NAS]["port"] == {"index": 26, "name": ""}
    assert clients[CAMERA]["kind"] == "camera"
    assert _link(data, f"client:{NAS}")["speed"] == 10e9


def test_ages_are_worked_out_when_the_answer_leaves() -> None:
    data = build(_console(1000, _core(1, 1)), STATIONS, [], {}, Meter(), 1000)
    aged = topology.with_ages(data, 1042)
    assert _link(aged, f"link:{ATTIC}")["age"] == 42 and "at" not in _link(aged, f"link:{ATTIC}")


def test_what_a_browser_stores_is_bounded_and_kept_to_its_shape() -> None:
    layout = topology.clean_layout({
        "placed": ["a", "a", 7, "x" * 65, "b"], "hidden": "nope",
        "positions": {"a": [1, 2], "b": [float("nan"), 1], "c": [1e9, 0], "d": ["1", "2"], "e": [1, 2, 3]},
        "start": "everything",
    }, 3)
    assert layout["placed"] == ["a", "b"] and layout["hidden"] == []
    assert layout["positions"] == {"a": [1.0, 2.0], "d": [1.0, 2.0]}
    assert layout["start"] == "all" and layout["integration_id"] == 3


def test_the_demo_console_goes_through_the_same_path() -> None:
    meter = Meter()
    devices, stations, health, models = topology.demo_console(10_000)
    build(devices, stations, health, models, meter, 10_000)
    devices, stations, health, models = topology.demo_console(10_200)
    data = build(devices, stations, health, models, meter, 10_200)
    assert len(data["nodes"]) == 8 and len(data["clients"]) == 9
    wan = _link(data, "link:internet")
    assert wan["down"] and 80e6 < wan["down"] < 240e6
    assert _link(data, f"link:{topology._mac('07')}")["state"] == "down"


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def _board(client: TestClient) -> dict:
    response = client.post("/api/v1/boards", json={"name": "Home"}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _unifi(client: TestClient, name: str = "UniFi", **extra: object) -> dict:
    response = client.post("/api/v1/integrations", json={"kind": "unifi", "name": name, "config": {"url": "https://unifi.example.com", "api_key": "a-key"}, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _topology_page(client: TestClient, board: dict, integration_id: int | None, **extra: object) -> dict:
    return client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Network", "kind": "topology", "integration_id": integration_id, **extra}, headers=CSRF)


def test_a_topology_page_needs_a_unifi_connection_this_person_may_use(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    assert _topology_page(client, board, None).json()["detail"]["code"] == "integration_required"
    radarr = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF).json()
    assert _topology_page(client, board, radarr["id"]).json()["detail"]["code"] == "kind_mismatch"
    locked = _unifi(client, "Locked", admin_only=True)
    create_user(client, "kim")
    login(client, "kim", "another-long-password")
    own = _board(client)
    refused = _topology_page(client, own, locked["id"])
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "integration_locked"


def test_a_new_page_shows_every_network_device_and_cards_stay_off_it(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    unifi = _unifi(client, demo=True)
    made = _topology_page(client, board, unifi["id"])
    assert made.status_code == 201, made.text
    page = next(p for p in made.json()["pages"] if p["kind"] == "topology")
    assert page["topology"] == {"integration_id": unifi["id"]}
    answer = client.get(f"/api/v1/pages/{page['id']}/topology").json()
    assert answer["problem"] is None
    assert set(answer["layout"]["placed"]) == {node["id"] for node in answer["data"]["nodes"]}
    assert answer["layout"]["seeded"] is True
    assert all("age" in link for link in answer["data"]["links"])
    card = client.post(f"/api/v1/pages/{page['id']}/widgets", json={"kind": "core.clock"}, headers=CSRF)
    assert card.status_code == 400 and card.json()["detail"]["code"] == "topology_page"


def test_an_empty_start_puts_only_the_gateway_on_the_plan(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page = next(p for p in _topology_page(client, board, _unifi(client, demo=True)["id"], start="empty").json()["pages"] if p["kind"] == "topology")
    placed = client.get(f"/api/v1/pages/{page['id']}/topology").json()["layout"]["placed"]
    assert placed == ["internet", topology._mac("01")]


def test_an_arrangement_is_saved_refused_when_stale_and_only_by_editors(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page = next(p for p in _topology_page(client, board, _unifi(client, demo=True)["id"]).json()["pages"] if p["kind"] == "topology")
    url = f"/api/v1/pages/{page['id']}/topology"
    version = client.get(url).json()["version"]
    saved = client.put(url, json={"placed": ["internet"], "positions": {"internet": [10, 20]}, "clients": [NAS], "version": version}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert saved.json()["layout"]["positions"] == {"internet": [10.0, 20.0]} and saved.json()["layout"]["clients"] == [NAS]
    assert client.put(url, json={"placed": [], "version": version}, headers=CSRF).status_code == 409
    again = client.get(url).json()
    assert again["layout"]["placed"] == ["internet"], "a saved arrangement is not seeded over"
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"role": "user", "level": "view"}]}, headers=CSRF)
    create_user(client, "viewer")
    login(client, "viewer", "another-long-password")
    assert client.get(url).status_code == 200
    assert client.put(url, json={"placed": []}, headers=CSRF).status_code == 403


def test_a_page_whose_connection_went_says_so(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    unifi = _unifi(client, demo=True)
    page = next(p for p in _topology_page(client, board, unifi["id"]).json()["pages"] if p["kind"] == "topology")
    assert client.delete(f"/api/v1/integrations/{unifi['id']}", headers=CSRF).status_code in (200, 204)
    answer = client.get(f"/api/v1/pages/{page['id']}/topology").json()
    assert answer["data"] is None and answer["problem"]["code"] == "no_integration"


@respx.mock
def test_a_console_that_refuses_the_key_is_an_answer_not_an_error(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page = next(p for p in _topology_page(client, board, _unifi(client)["id"]).json()["pages"] if p["kind"] == "topology")
    respx.get("https://unifi.example.com/proxy/network/api/s/default/stat/device").mock(return_value=httpx.Response(401))
    answer = client.get(f"/api/v1/pages/{page['id']}/topology")
    assert answer.status_code == 200
    assert answer.json()["problem"]["code"] == "auth_failed" and answer.json()["layout"]["seeded"] is False


def test_export_and_import_keep_the_plan_and_its_connection_by_name(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    unifi = _unifi(client, demo=True)
    page = next(p for p in _topology_page(client, board, unifi["id"]).json()["pages"] if p["kind"] == "topology")
    client.put(f"/api/v1/pages/{page['id']}/topology", json={"placed": ["internet"], "positions": {"internet": [5, 6]}}, headers=CSRF)
    text = client.get(f"/api/v1/boards/{board['slug']}/export").text
    assert "kind: topology" in text and "a-key" not in text
    copy = client.post("/api/v1/boards/import", json={"yaml_text": text, "slug": "home-copy"}, headers=CSRF)
    assert copy.status_code == 201, copy.text
    plan = next(p for p in copy.json()["pages"] if p["kind"] == "topology")
    assert plan["topology"] == {"integration_id": unifi["id"]}
    assert client.get(f"/api/v1/pages/{plan['id']}/topology").json()["layout"]["positions"] == {"internet": [5.0, 6.0]}


def test_two_pages_of_one_name_get_two_addresses(client: TestClient) -> None:
    """A topology page is named "Network" for you; the demo board has a "Network" page of its own."""
    setup_admin(client)
    board = _board(client)
    first = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Network"}, headers=CSRF).json()
    second = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Network"}, headers=CSRF).json()
    slugs = [page["slug"] for page in second["pages"] if page["name"] == "Network"]
    assert slugs == ["network", "network-2"]
    own = next(page for page in first["pages"] if page["slug"] == "network")
    renamed = client.patch(f"/api/v1/pages/{own['id']}", json={"name": "Network"}, headers=CSRF).json()
    assert sorted(page["slug"] for page in renamed["pages"] if page["name"] == "Network") == ["network", "network-2"], "renaming to its own name keeps its address"
