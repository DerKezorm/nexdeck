"""``/go/<short name>``: an app tile from the address bar.

Each test is one way the short address could lead somewhere it should not: to
a tile on a board the person may not open, off nexdeck after the sign-in, to
the wrong address for the network, or over an address nexdeck already uses.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.services import aliases

from .conftest import CSRF, create_user, login, setup_admin
from .test_apps import HOME, OUTSIDE, PAPERLESS, TABLET, _app, _browser

ROOT = Path(__file__).resolve().parents[2]


def _board(client: TestClient, name: str) -> dict:
    answer = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _tile(client: TestClient, board: dict, title: str = "", link: str = "", **options: object):  # noqa: ANN202
    return client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
                       json={"kind": "core.app", "title": title, "link": link, "options": options}, headers=CSRF)


def _made(answer) -> dict:  # noqa: ANN001
    assert answer.status_code == 201, answer.text
    return answer.json()["widget"]


def _go(client: TestClient, address: str) -> str:
    answer = client.get(address, follow_redirects=False)
    assert answer.status_code == 302, answer.text
    assert answer.headers["cache-control"] == "no-store"
    return answer.headers["location"]


# -- the name ---------------------------------------------------------------------


@pytest.mark.parametrize(("name", "short"), [
    ("Plex", "plex"),
    ("Home Assistant", "home-assistant"),
    ("Kühlschrank & Gefrierfach", "kuehlschrank-gefrierfach"),
    ("Café ☕", "cafe"),
    ("  --Pi-hole--  ", "pi-hole"),
    ("★★", ""),
    ("x" * 60, "x" * 40),
])
def test_a_tile_takes_its_short_name_from_its_name(name: str, short: str) -> None:
    assert aliases.derive(name) == short
    assert short == "" or aliases.ALIAS.match(short)


def test_a_short_name_keeps_to_lower_case_letters_digits_and_hyphens(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Lab")
    for wrong in ("Plex", "plex!", "-plex", "plex-", "pl ex", "p" * 41, 7):
        refused = _tile(client, board, "Plex", "https://plex.example.com", alias=wrong)
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_alias", wrong
    assert _made(_tile(client, board, "Plex", "https://plex.example.com", alias="tv-2"))["options"]["alias"] == "tv-2"


def test_a_name_given_twice_on_one_board_is_refused_and_on_two_boards_is_not(client: TestClient) -> None:
    setup_admin(client)
    lab, wall = _board(client, "Lab"), _board(client, "Wall")
    _made(_tile(client, lab, "Plex", "https://plex.example.com"))
    taken = _tile(client, lab, "Jellyfin", "https://jellyfin.example.com", alias="plex")
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "alias_taken"
    _made(_tile(client, wall, "Jellyfin", "https://jellyfin.example.com", alias="plex"))
    # Changing a tile keeps its own name without counting itself as the other one.
    own = _made(_tile(client, lab, "Radarr", "https://radarr.example.com", alias="movies"))
    again = client.patch(f"/api/v1/widgets/{own['id']}", json={"options": {"alias": "movies", "check": False}}, headers=CSRF)
    assert again.status_code == 200, again.text
    clash = client.patch(f"/api/v1/widgets/{own['id']}", json={"options": {"alias": "plex"}}, headers=CSRF)
    assert clash.status_code == 409


# -- where it leads -----------------------------------------------------------------


def test_a_short_name_opens_its_tile_and_a_given_one_wins(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Lab")
    _made(_tile(client, board, "Plex", "https://plex.example.com"))
    _made(_tile(client, board, "Home Assistant", "https://ha.example.com", alias="ha"))
    assert _go(client, "/go/plex") == "https://plex.example.com"
    assert _go(client, "/go/PLEX") == "https://plex.example.com"
    assert _go(client, "/go/ha") == "https://ha.example.com"
    assert _go(client, "/go?q=ha") == "https://ha.example.com"
    assert urlsplit(_go(client, "/go/home-assistant")).path == "/", "a given name replaces the taken one"


def test_signed_out_it_goes_to_the_sign_in_and_comes_back_to_itself(client: TestClient) -> None:
    setup_admin(client)
    _made(_tile(client, _board(client, "Lab"), "Plex", "https://plex.example.com"))
    stranger = TestClient(client.app)
    for asked, back in (("/go/plex", "/go/plex"), ("/go?q=two words", "/go?q=two+words"),
                        ("/go/a%3Fb", "/go/a%3Fb")):
        location = _go(stranger, asked)
        parts = urlsplit(location)
        assert (parts.scheme, parts.netloc, parts.path) == ("", "", "/login"), location
        assert parse_qs(parts.query)["next"] == [back]
        assert parse_qs(parts.query)["next"][0].startswith("/") and not parse_qs(parts.query)["next"][0].startswith("//")


def test_a_tile_on_a_board_the_person_may_not_open_is_not_found(client: TestClient) -> None:
    setup_admin(client)
    secret = _board(client, "Private")
    _made(_tile(client, secret, "Vault", "https://vault.example.com"))
    shared = _board(client, "Shared")
    _made(_tile(client, shared, "Plex", "https://plex.example.com"))
    robin = create_user(client, "robin")
    client.put(f"/api/v1/boards/{shared['slug']}/shares", json={"shares": [{"user_id": robin["id"], "level": "view"}]}, headers=CSRF)
    member = TestClient(client.app)
    login(member, "robin", "another-long-password")
    assert _go(member, "/go/plex") == "https://plex.example.com"
    assert _go(member, "/go/vault") == "/?find=vault", "the same answer as a name nobody uses"
    assert _go(member, "/go/nothing") == "/?find=nothing"


def test_a_wall_display_looks_on_its_own_board_only(client: TestClient) -> None:
    setup_admin(client)
    wall, other = _board(client, "Wall"), _board(client, "Other")
    _made(_tile(client, wall, "Plex", "https://plex.example.com"))
    _made(_tile(client, other, "Vault", "https://vault.example.com"))
    made = client.post(f"/api/v1/boards/{wall['slug']}/kiosk-tokens", json={"name": "Hall"}, headers=CSRF).json()
    display = TestClient(client.app)
    assert display.post("/api/v1/kiosk/session", json={"token": made["token"]}, headers=CSRF).status_code == 200
    assert _go(display, "/go/plex") == "https://plex.example.com"
    assert _go(display, "/go/vault") == "/k"


def test_the_address_for_the_network_is_the_one_the_board_shows(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    board = _board(client, "Desk")
    _made(_tile(client, board, app_id=app["id"], address="auto"))
    client.put("/api/v1/settings/home-network", json={"enabled": False, "networks": [HOME], "user_id": None}, headers=CSRF)
    assert _go(_browser(client, TABLET), "/go/paperless") == "http://192.168.1.5:8000"
    assert _go(_browser(client, OUTSIDE), "/go/paperless") == "https://paperless.tailnet.example"
    assert PAPERLESS["name"] == "Paperless"


def test_one_name_with_two_addresses_opens_the_search_bar_instead_of_guessing(client: TestClient) -> None:
    setup_admin(client)
    lab, wall = _board(client, "Lab"), _board(client, "Wall")
    _made(_tile(client, lab, "Proxmox", "https://pve1.example.com"))
    _made(_tile(client, wall, "Proxmox", "https://pve2.example.com"))
    assert _go(client, "/go/proxmox") == "/?find=proxmox"
    _made(_tile(client, lab, "Plex", "https://plex.example.com"))
    _made(_tile(client, wall, "Plex", "https://plex.example.com"))
    assert _go(client, "/go/plex") == "https://plex.example.com", "the same address twice is one answer"


def _connection(client: TestClient, name: str, url: str) -> dict:
    answer = client.post("/api/v1/integrations", json={"kind": "plex", "name": name, "config": {"url": url, "token": "t"}}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _bound_tile(client: TestClient, board: dict, connection: dict, title: str, link: str = ""):  # noqa: ANN202
    return client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
                       json={"kind": "core.app", "title": title, "link": link, "integration_id": connection["id"]}, headers=CSRF)


def test_a_tile_without_a_link_opens_the_address_of_its_connection(client: TestClient) -> None:
    setup_admin(client)
    lab, wall = _board(client, "Lab"), _board(client, "Wall")
    plex = _connection(client, "Plex", "https://plex.example.com")
    _made(_bound_tile(client, lab, plex, "Plex"))
    assert _go(client, "/go/plex") == "https://plex.example.com"
    _made(_bound_tile(client, wall, plex, "Plex"))
    assert _go(client, "/go/plex") == "https://plex.example.com", "two tiles, one connection, one address"
    other = _connection(client, "Second", "https://plex2.example.com")
    _made(_bound_tile(client, wall, other, "Plex"))
    assert _go(client, "/go/plex") == "/?find=plex", "two connections are two addresses"


def test_a_link_of_its_own_wins_over_the_connection(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Lab")
    plex = _connection(client, "Plex", "https://plex.example.com")
    _made(_bound_tile(client, board, plex, "Plex", "https://mine.example.com"))
    assert _go(client, "/go/plex") == "https://mine.example.com"


def test_a_link_that_is_not_a_web_address_is_never_followed(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Lab")
    _made(_tile(client, board, "Odd", "javascript:alert(1)"))
    assert _go(client, "/go/odd") == "/?find=odd"


def test_words_open_the_search_bar_or_the_board_of_the_card_they_name(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Lab")
    client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.clock", "title": "Kitchen clock"}, headers=CSRF)
    location = _go(client, "/go?q=kitchen clock")
    parts = urlsplit(location)
    assert parts.path == f"/b/{board['slug']}/{board['pages'][0]['slug']}"
    assert parse_qs(parts.query)["find"] == ["kitchen clock"]
    assert _go(client, "/go?q=what is this") == "/?find=what+is+this"
    assert _go(client, "/go?q=") == "/"


def test_an_account_that_owes_a_second_factor_is_sent_to_the_app(client: TestClient) -> None:
    setup_admin(client)
    _made(_tile(client, _board(client, "Lab"), "Plex", "https://plex.example.com"))
    create_user(client, "kim")
    assert client.patch("/api/v1/settings", json={"require_two_factor": True}, headers=CSRF).status_code == 200
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    assert member.get("/api/v1/boards").status_code == 403, "the account is held at the door"
    assert _go(member, "/go/plex") == "/"


def test_a_token_that_only_reads_may_follow_a_name(client: TestClient) -> None:
    setup_admin(client)
    _made(_tile(client, _board(client, "Lab"), "Plex", "https://plex.example.com"))
    token = client.post("/api/v1/tokens", json={"name": "script"}, headers=CSRF).json()["token"]
    script = TestClient(client.app, headers={"Authorization": f"Bearer {token}"})
    assert _go(script, "/go/plex") == "https://plex.example.com"


# -- the address itself -------------------------------------------------------------


def test_go_hides_no_address_the_app_already_has() -> None:
    """``/go`` is matched before the single-page app, so it must not be a page of the app or a file of the build."""
    from app.main import app

    def in_order(routes: list) -> list[str]:  # noqa: ANN001
        found: list[str] = []
        for route in routes:
            inner = getattr(route, "original_router", None)
            found += in_order(inner.routes) if inner is not None else [getattr(route, "path", "")]
        return found

    paths = in_order(list(app.routes))
    assert paths.index("/go") < paths.index("/{path:path}") and paths.index("/go/{name}") < paths.index("/{path:path}")
    pages = re.findall(r'<Route\s+path="([^"]+)"', (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8"))
    assert len(pages) >= 10, "the routes of the app were not found"
    assert [page for page in pages if page == "/go" or page.startswith("/go/")] == []
    built = {entry.name for entry in (ROOT / "frontend" / "public").iterdir()}
    assert "go" not in built and "opensearch.xml" not in built


def test_go_takes_nothing_from_its_neighbours(client: TestClient) -> None:
    setup_admin(client)
    for path in ("/golf", "/gopher/x", "/b/go"):
        answer = client.get(path, follow_redirects=False)
        assert answer.status_code != 302, path
    assert client.get("/api/v1/go").status_code == 404
