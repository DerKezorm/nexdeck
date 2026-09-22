"""Boards from Homepage and Homarr.

The files under fixtures/imports are written the way the two projects'
documentation writes them, with example.com addresses and invented keys.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.services import dashboard_import

from .conftest import CSRF, create_user, login, setup_admin

FIXTURES = Path(__file__).parent / "fixtures" / "imports"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _homepage() -> dict:
    return {"services": _read("homepage-services.yaml"), "bookmarks": _read("homepage-bookmarks.yaml"), "widgets": _read("homepage-widgets.yaml")}


def _cards(plan: dict) -> dict[str, dict]:
    return {card["title"]: card for page in plan["pages"] for card in page["cards"]}


def _connections(plan: dict) -> dict[str, dict]:
    return {connection["name"]: connection for connection in plan["connections"]}


# -- reading the files ------------------------------------------------------------


def test_homepage_groups_become_pages_and_services_become_connections_and_cards() -> None:
    plan = dashboard_import.from_homepage(**_homepage())
    assert [page["name"] for page in plan["pages"]] == ["Overview", "Media", "Infrastructure"]
    cards, connections = _cards(plan), _connections(plan)
    assert cards["Sonarr"]["kind"] == "sonarr.status" and cards["Sonarr"]["link"] == "https://sonarr.example.com"
    assert connections["Sonarr"]["config"] == {"url": "http://sonarr:8989", "api_key": "sonarr-key-for-tests"}
    assert connections["Sonarr"]["missing"] == []
    assert cards["Jellyfin"]["kind"] == "jellyfin.library" and cards["Jellyfin"]["icon"] == "jellyfin"
    # Proxmox names the token and its secret username and password.
    assert connections["Proxmox"]["config"]["token_id"] == "api@pam!homepage"
    assert connections["Proxmox"]["config"]["token_secret"] == "proxmox-secret-for-tests"


def test_a_homepage_placeholder_is_missing_not_a_key() -> None:
    """Taken as it came, the key was the text {{HOMEPAGE_VAR_RADARR_KEY}}."""
    plan = dashboard_import.from_homepage(**_homepage())
    radarr = _connections(plan)["Radarr"]
    assert "api_key" not in radarr["config"]
    assert radarr["missing"] == ["api_key"]
    assert any("Radarr" in note and "placeholder" in note for note in plan["notes"])


def test_a_link_becomes_a_tile_and_an_unknown_widget_says_so() -> None:
    plan = dashboard_import.from_homepage(**_homepage())
    cards = _cards(plan)
    assert cards["Router"]["kind"] == "core.app"
    assert cards["Router"]["options"] == {"description": "The gateway", "check": True}
    assert cards["Router"]["icon"] == "lucide:link", "an mdi- icon is Homepage's own and means nothing here"
    assert cards["Something odd"]["kind"] == "core.app"
    assert any("moonraker" in note for note in plan["notes"])


def test_a_group_inside_a_group_joins_its_page_and_a_custom_api_keeps_its_field() -> None:
    plan = dashboard_import.from_homepage(**_homepage())
    infrastructure = next(page for page in plan["pages"] if page["name"] == "Infrastructure")
    assert [card["title"] for card in infrastructure["cards"]][-2:] == ["AdGuard", "Temperature"]
    temperature = _cards(plan)["Temperature"]
    assert temperature["kind"] == "jsonapi.value"
    assert temperature["options"] == {"value_path": "data.temperature", "label": "Server room", "unit": "°C"}


def test_homepages_info_widgets_and_bookmarks_come_along() -> None:
    plan = dashboard_import.from_homepage(**_homepage())
    overview = plan["pages"][0]
    kinds = [card["kind"] for card in overview["cards"]]
    assert kinds == ["core.search", "core.clock", "weather.current", "core.bookmarks", "core.bookmarks"]
    weather = overview["cards"][2]["options"]
    assert weather == {"latitude": 53.55, "longitude": 9.99, "place": "Hamburg"}
    developer = overview["cards"][3]["options"]["links"].splitlines()
    assert developer == ["Github | https://github.com/", "Docs | https://docs.example.com/"]
    # A javascript: address is no bookmark.
    assert "javascript" not in overview["cards"][4]["options"]["links"]
    assert any("resources" in note for note in plan["notes"])


def test_homarr_categories_become_pages_and_apps_come_with_their_keys() -> None:
    plan = dashboard_import.from_homarr(_read("homarr-config.json"))
    assert [page["name"] for page in plan["pages"]] == ["Media", "Network", "Overview"]
    cards, connections = _cards(plan), _connections(plan)
    assert connections["Sonarr"]["config"] == {"url": "http://sonarr:8989", "api_key": "sonarr-key-for-tests"}
    assert cards["Sonarr"]["link"] == "https://sonarr.example.com" and cards["Sonarr"]["icon"] == "sonarr"
    # A private value Homarr left out of the file is missing.
    assert connections["Pi-hole"]["missing"] == ["password"]
    assert cards["Pi-hole"]["icon"] == "pi-hole"
    assert cards["Wiki"]["kind"] == "core.app" and cards["Wiki"]["options"]["check"] is True
    assert cards["Notes"]["options"] == {"content": "# Hello"}
    assert any("torrents-status" in note for note in plan["notes"])


def test_what_is_not_the_right_file_is_said_in_words() -> None:
    for call in (lambda: dashboard_import.from_homarr("not json"), lambda: dashboard_import.from_homarr('{"apps": 1}'),
                 lambda: dashboard_import.from_homepage("- [unclosed"), lambda: dashboard_import.from_homepage("", "", "")):
        try:
            call()
        except dashboard_import.DashboardImportError as failure:
            assert str(failure)
        else:
            raise AssertionError("no error for a file that is not one")


def test_every_mapping_names_fields_the_adapters_have() -> None:
    """A renamed field in an adapter would quietly stop the import filling it."""
    for kind, fields in dashboard_import.PER_KIND.items():
        known = {field.name for field in get_adapter(kind).fields}
        assert set(fields) <= known, f"{kind}: {set(fields) - known}"
    for other, ours in dashboard_import.RENAMED.items():
        assert get_adapter(ours).needs_integration, other


# -- through the API ------------------------------------------------------------------


def _preview(client: TestClient, files: dict) -> dict:
    answer = client.post("/api/v1/imports/preview", json={"files": files}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_an_administrator_imports_and_the_connections_are_made(client: TestClient) -> None:
    setup_admin(client)
    plan = _preview(client, _homepage())
    # Radarr's key was a placeholder: filled in here, as the preview lets one.
    for connection in plan["connections"]:
        if connection["name"] == "Radarr":
            connection["config"]["api_key"] = "radarr-key-typed-in"
    made = client.post("/api/v1/imports/apply", json={"plan": plan, "name": "From Homepage"}, headers=CSRF)
    assert made.status_code == 201, made.text
    board = made.json()
    assert board["name"] == "From Homepage" and board["settings"] == {"columns": 24}
    assert [page["name"] for page in board["pages"]] == ["Overview", "Media", "Infrastructure"]
    integrations = {row["name"]: row for row in client.get("/api/v1/integrations").json()}
    assert {"Sonarr", "Radarr", "Jellyfin", "Overseerr", "Proxmox", "AdGuard", "Temperature"} <= set(integrations)
    # The key is kept and not handed out again.
    assert integrations["Radarr"]["config"].get("api_key") in ("", "********", None)
    media = board["pages"][1]
    assert {w["title"]: w["integration_name"] for w in media["widgets"]}["Radarr"] == "Radarr"


def test_the_same_address_is_the_same_service_and_is_not_made_twice(client: TestClient) -> None:
    setup_admin(client)
    existing = client.post("/api/v1/integrations", json={"kind": "sonarr", "name": "Sonarr at home", "config": {"url": "http://sonarr:8989/", "api_key": "k"}}, headers=CSRF).json()
    plan = _preview(client, {"services": _read("homepage-services.yaml")})
    sonarr = _connections(plan)["Sonarr"]
    assert sonarr["use"] == existing["id"]
    assert _connections(plan)["Radarr"]["use"] == "create"


def test_a_connection_still_missing_a_value_is_refused_until_filled_or_left_out(client: TestClient) -> None:
    setup_admin(client)
    plan = _preview(client, {"services": _read("homepage-services.yaml")})
    refused = client.post("/api/v1/imports/apply", json={"plan": plan, "name": "X"}, headers=CSRF)
    assert refused.status_code == 400 and "Radarr" in refused.json()["detail"]["message"]
    assert client.get("/api/v1/integrations").json() == [], "a refused import leaves no connections behind"
    for connection in plan["connections"]:
        if connection["name"] == "Radarr":
            connection["use"] = None
    made = client.post("/api/v1/imports/apply", json={"plan": plan, "name": "X"}, headers=CSRF)
    assert made.status_code == 201, made.text
    titles = [w["title"] for page in made.json()["pages"] for w in page["widgets"]]
    assert "Radarr" not in titles and "Sonarr" in titles


def test_cards_left_out_stay_out(client: TestClient) -> None:
    setup_admin(client)
    plan = _preview(client, {"services": _read("homepage-services.yaml")})
    for page in plan["pages"]:
        for card in page["cards"]:
            card["include"] = card["title"] in ("Router", "Sonarr")
    for connection in plan["connections"]:
        if connection["name"] == "Radarr":
            connection["use"] = None
    board = client.post("/api/v1/imports/apply", json={"plan": plan, "name": "Two"}, headers=CSRF).json()
    assert sorted(w["title"] for page in board["pages"] for w in page["widgets"]) == ["Router", "Sonarr"]


def test_a_member_uses_what_exists_and_creates_nothing(client: TestClient) -> None:
    setup_admin(client)
    sonarr = client.post("/api/v1/integrations", json={"kind": "sonarr", "name": "Sonarr", "config": {}, "demo": True}, headers=CSRF).json()
    client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Radarr 4K", "config": {}, "demo": True, "admin_only": True}, headers=CSRF)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    plan = _preview(kim, {"services": _read("homepage-services.yaml")})
    connections = _connections(plan)
    assert connections["Sonarr"]["use"] == sonarr["id"]
    assert connections["Radarr"]["use"] is None and connections["Radarr"]["existing"] == [], "a reserved connection is not offered"
    forced = [dict(c, use="create") if c["name"] == "Jellyfin" else c for c in plan["connections"]]
    refused = kim.post("/api/v1/imports/apply", json={"plan": {**plan, "connections": forced}, "name": "Kim"}, headers=CSRF)
    assert refused.status_code == 400 and "administrator" in refused.json()["detail"]["message"]
    made = kim.post("/api/v1/imports/apply", json={"plan": plan, "name": "Kim"}, headers=CSRF)
    assert made.status_code == 201, made.text
    assert len(client.get("/api/v1/integrations").json()) == 2


def test_a_plan_sent_back_changed_is_read_like_any_other_input(client: TestClient) -> None:
    setup_admin(client)
    plan = _preview(client, {"services": _read("homepage-services.yaml")})
    plan["connections"] = [dict(c, use=None) for c in plan["connections"]]
    plan["pages"][0]["cards"].append({"key": "x", "kind": "core.app", "title": "Evil", "link": "javascript:alert(1)", "options": {}, "include": True, "connection": None})
    board = client.post("/api/v1/imports/apply", json={"plan": plan, "name": "Checked"}, headers=CSRF).json()
    evil = next(w for page in board["pages"] for w in page["widgets"] if w["title"] == "Evil")
    assert evil["link"] == ""
    plan["pages"][0]["cards"].append({"key": "y", "kind": "nothing.here", "title": "Unknown", "include": True, "connection": None})
    assert client.post("/api/v1/imports/apply", json={"plan": plan, "name": "Unknown"}, headers=CSRF).status_code == 400


def test_a_guest_imports_nothing(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "visitor", role="guest")
    guest = TestClient(client.app)
    login(guest, "visitor", "another-long-password")
    assert guest.post("/api/v1/imports/preview", json={"files": {"services": "- A: []"}}, headers=CSRF).status_code == 403
