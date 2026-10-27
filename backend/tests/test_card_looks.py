"""How a card looks: a colour of its own, a board's own card style, logos per ground and per container."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import icons

from .conftest import CSRF, setup_admin


def _board_and_page(client: TestClient) -> tuple[dict, int]:
    board = client.post("/api/v1/boards", json={"name": "Looks"}, headers=CSRF).json()
    return board, board["pages"][0]["id"]


@pytest.mark.parametrize("colour", ["", "accent", "violet", "icon", "#3b82f6", "#E57000"])
def test_a_card_takes_a_colour_from_the_list_or_of_its_own(client: TestClient, colour: str) -> None:
    setup_admin(client)
    _board, page = _board_and_page(client)
    made = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.clock", "options": {"card_colour": colour, "card_effect": "tint"}}, headers=CSRF)
    assert made.status_code == 201, made.text


@pytest.mark.parametrize(("options", "code"), [
    ({"card_colour": "red; background: url(https://example.com/x)"}, "bad_card_colour"),
    ({"card_colour": "#12345"}, "bad_card_colour"),
    ({"card_colour": "tomato"}, "bad_card_colour"),
    ({"card_colour": 3}, "bad_card_colour"),
    ({"card_effect": "glow"}, "bad_card_effect"),
    ({"hide_head": "yes"}, "bad_hide_head"),
    ({"frameless": 1}, "bad_frameless"),
])
def test_anything_else_never_reaches_a_style(client: TestClient, options: dict, code: str) -> None:
    """⚠️ The colour goes into the card's style; only a name from the list or #rrggbb gets there."""
    setup_admin(client)
    _board, page = _board_and_page(client)
    made = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.clock", "options": options}, headers=CSRF)
    assert made.status_code == 400, made.text
    assert made.json()["detail"]["code"] == code
    made = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.clock"}, headers=CSRF).json()
    widget_id = made.get("id") or made["widget"]["id"]
    changed = client.patch(f"/api/v1/widgets/{widget_id}", json={"options": options}, headers=CSRF)
    assert changed.status_code == 400 and changed.json()["detail"]["code"] == code


def test_a_card_may_go_without_its_head_and_its_frame(client: TestClient) -> None:
    setup_admin(client)
    board, page = _board_and_page(client)
    made = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.search", "options": {"hide_head": True, "frameless": True}}, headers=CSRF)
    assert made.status_code == 201, made.text
    shown = client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["widgets"][0]["options"]
    assert (shown["hide_head"], shown["frameless"]) == (True, True)
    exported = client.get(f"/api/v1/boards/{board['slug']}/export").text
    assert "hide_head: true" in exported and "frameless: true" in exported, "and it travels with the board"


def test_a_board_draws_its_cards_in_a_style_of_its_own_or_follows(client: TestClient) -> None:
    setup_admin(client)
    board, _page = _board_and_page(client)
    own = client.patch(f"/api/v1/boards/{board['slug']}", json={"settings": {"card_style": "liquid"}}, headers=CSRF)
    assert own.status_code == 200, own.text
    assert own.json()["settings"]["card_style"] == "liquid"
    unknown = client.patch(f"/api/v1/boards/{board['slug']}", json={"settings": {"card_style": "wood"}}, headers=CSRF)
    assert "card_style" not in unknown.json()["settings"], "an unknown style follows the installation"


def test_each_account_decides_whether_cards_tip(client: TestClient) -> None:
    setup_admin(client)
    assert client.get("/api/v1/auth/me").json()["tilt"] is True, "on unless switched off"
    changed = client.patch("/api/v1/auth/me", json={"tilt": False}, headers=CSRF)
    assert changed.status_code == 200 and changed.json()["tilt"] is False
    assert client.get("/api/v1/auth/me").json()["tilt"] is False


@pytest.fixture
def known(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    names = {"immich", "immich-light", "qbittorrent", "beszel", "postgres", "github", "github-light", "plex-dark", "plex"}
    monkeypatch.setattr(icons, "_known_now", lambda: names)
    return names


@pytest.mark.parametrize(("image", "name", "expected"), [
    ("lscr.io/linuxserver/qbittorrent:latest", "qbittorrent", "qbittorrent"),
    ("ghcr.io/immich-app/immich-server:release", "immich_server", "immich"),
    ("ghcr.io/immich-app/immich-machine-learning:release", "immich_machine_learning", "immich"),
    ("henrygd/beszel-agent:latest", "beszel-agent", "beszel"),
    ("ghcr.io/immich-app/postgres:14", "immich_postgres", "postgres"),
    ("example/backup-runner:2.1", "nightly-backup", ""),
])
def test_a_container_wears_the_logo_its_image_is_known_as(known: set[str], image: str, name: str, expected: str) -> None:
    assert icons.container_icon(image, name) == expected


def test_a_label_names_the_logo_of_a_container(known: set[str]) -> None:
    assert icons.container_icon("example/x:1", "x", {"nexdeck.icon": "Jellyfin"}) == "jellyfin"
    assert icons.container_icon("example/x:1", "x", {"nexdeck.icon": "lucide:box"}) == "lucide:box"
    assert icons.container_icon("lscr.io/linuxserver/qbittorrent", "q", {"nexdeck.icon": "../etc"}) == "qbittorrent", "a name that is no name is passed over"


def test_without_the_index_only_a_label_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """No request from the adapter: until the names are known, a row keeps its dot."""
    monkeypatch.setattr(icons, "_known_now", lambda: None)
    assert icons.container_icon("lscr.io/linuxserver/qbittorrent", "qbittorrent") == ""
    assert icons.container_icon("x", "x", {"nexdeck.icon": "plex"}) == "plex"


def test_a_logo_comes_in_the_variant_for_its_ground(known: set[str]) -> None:
    assert icons.variant("github", "dark") == "github-light"
    assert icons.variant("plex", "light") == "plex-dark"
    assert icons.variant("qbittorrent", "dark") == "qbittorrent", "without a variant it stays itself"
    assert icons.variant("github-light", "light") == "github-light", "a name that says which stays"
    assert icons.variant("github", "") == "github"
    assert icons.variant("nexdeck", "dark") == "nexdeck", "the logos that ship come as they are"


def test_the_proxy_serves_the_variant_and_falls_back(client: TestClient, known: set[str], monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    async def fake(name: str, ext: str) -> tuple[bytes, str] | None:
        asked.append(name)
        return None if name == "immich-light" else (name.encode(), "image/svg+xml")

    monkeypatch.setattr(icons, "fetch_icon", fake)
    assert client.get("/api/v1/icons/github.svg?on=dark").content == b"github-light"
    assert client.get("/api/v1/icons/github.svg?on=light").content == b"github"
    assert client.get("/api/v1/icons/github.svg").content == b"github"
    # The index says there is one and the collections have none: the plain logo, not a 404.
    assert client.get("/api/v1/icons/immich.svg?on=dark").content == b"immich"
    assert asked[-2:] == ["immich-light", "immich"]


def test_every_container_list_takes_the_same_logo(known: set[str]) -> None:
    """Docker, Synology, Portainer, Komodo, Dockhand, Arcane, What's up Docker: one rule for all."""
    assert icons.logo_fields("lscr.io/linuxserver/qbittorrent", "qbittorrent") == {"icon": "qbittorrent", "icon_dot": True}
    assert icons.logo_fields("example/backup:1", "nightly-backup") == {}, "a container nobody knows keeps its dot"


def test_the_synology_demo_shows_logos_in_its_container_list() -> None:
    from app.adapters.synology import SynologyAdapter

    rows = SynologyAdapter().demo("containers", {}, 0).items
    assert [row.get("icon") for row in rows] == ["nexview", "gotify", "paperless-ngx", None]
    assert all(row.get("icon_dot") for row in rows if row.get("icon"))


@pytest.mark.parametrize("index", [None, {"postgres"}])
def test_the_family_wears_the_logos_nexdeck_ships(monkeypatch: pytest.MonkeyPatch, index: set[str] | None) -> None:
    """⚠️ nexview, nexcrate and nexbeat are in no collection, and stood without a logo, index or not."""
    monkeypatch.setattr(icons, "_known_now", lambda: index)
    assert icons.container_icon("ghcr.io/derkezorm/nexcrate:latest", "nexcrate") == "nexcrate"
    assert icons.container_icon("ghcr.io/derkezorm/nexview:latest", "nexview") == "nexview"
    assert icons.container_icon("ghcr.io/derkezorm/nexbeat:latest", "nexbeat") == "nexbeat"
