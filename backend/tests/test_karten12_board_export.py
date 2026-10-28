"""KARTEN-12: a board file that carries its custom cards and own connections (AC-5, EC-4)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.adapters import forget_all_custom
from app.services.collector import collector

from .cards_sample import changed
from .conftest import CSRF, create_user, login, setup_admin
from .karten12_sample import CARD, INTEGRATION, PLAIN, SHORT

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "karten12_board_export_before.yaml"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    yield client
    # An own kind made by a test stays in the registry of the process: the tests that count the kinds would see it.
    forget_all_custom()


def plain_board(client: TestClient) -> str:
    """The board the fixture was exported from, made through the interface."""
    board = client.post("/api/v1/boards", json={"name": "Media"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    radarr = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr.example.com:7878", "api_key": "secret-key"}}, headers=CSRF).json()
    for body in (
        {"kind": "radarr.queue", "integration_id": radarr["id"], "title": "Queue"},
        {"kind": "core.markdown", "title": "Notes", "options": {"content": "hello\nworld"}},
        {"kind": "core.clock", "title": "Time"},
    ):
        assert client.post(f"/api/v1/pages/{page}/widgets", json=body, headers=CSRF).status_code == 201
    return str(board["slug"])


def test_karten12_ec4_a_board_without_custom_cards_is_exported_byte_for_byte_as_before(admin: TestClient) -> None:
    slug = plain_board(admin)
    text = admin.get(f"/api/v1/boards/{slug}/export").text
    if not FIXTURE.exists():
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    assert text == FIXTURE.read_text(encoding="utf-8")


def own_board(client: TestClient, card: str = CARD, with_connection: bool = True) -> str:
    """A board with a custom card that reads through an own connection which has a secret."""
    assert client.post("/api/v1/own-integrations", json={"yaml": INTEGRATION}, headers=CSRF).status_code == 201
    assert client.post("/api/v1/cards", json={"yaml": card}, headers=CSRF).status_code == 201
    board = client.post("/api/v1/boards", json={"name": "Wiki"}, headers=CSRF).json()
    body: dict = {"kind": "custom.value", "options": {"card": "queue-size"}}
    if with_connection:
        made = client.post(
            "/api/v1/integrations",
            json={"kind": f"custom:{SHORT}", "name": "Wiki", "config": {"url": "http://wiki.example.com", "token_id": "ID-1234", "token_secret": "SECRET-5678"}},
            headers=CSRF,
        )
        assert made.status_code == 201, made.text
        body["integration_id"] = made.json()["id"]
    assert client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json=body, headers=CSRF).status_code == 201
    return str(board["slug"])


def test_karten12_ac5_a_board_with_a_custom_card_carries_the_card_and_its_own_connection(admin: TestClient) -> None:
    slug = own_board(admin)
    text = admin.get(f"/api/v1/boards/{slug}/export").text
    document = yaml.safe_load(text)
    assert document["custom_cards"] == [CARD] and document["own_integrations"] == [INTEGRATION]
    assert "custom_cards:\n- |" in text, "the definitions stand as blocks of text, comments readable"
    assert "# A comment on top stays where it is." in text


def test_karten12_ac5_secrets_of_the_connections_stay_environment_references(admin: TestClient) -> None:
    text = admin.get(f"/api/v1/boards/{own_board(admin)}/export").text
    assert "SECRET-5678" not in text
    assert "${NEXDECK_CUSTOM_BOOKSTACK_OWN_1_TOKEN_SECRET}" in text
    assert [one["kind"] for one in yaml.safe_load(text)["integrations"]] == [f"custom:{SHORT}"]


def test_karten12_ac5_a_card_is_listed_once_however_often_the_board_shows_it(admin: TestClient) -> None:
    slug = own_board(admin, with_connection=False)
    page = admin.get(f"/api/v1/boards/{slug}").json()["pages"][0]["id"]
    admin.post(f"/api/v1/pages/{page}/widgets", json={"kind": "custom.value", "options": {"card": "queue-size"}}, headers=CSRF)
    document = yaml.safe_load(admin.get(f"/api/v1/boards/{slug}/export").text)
    assert document["custom_cards"] == [CARD] and document["own_integrations"] == [INTEGRATION]


def test_karten12_ac5_a_card_that_needs_no_own_connection_brings_no_list_of_them(admin: TestClient) -> None:
    admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF)
    board = admin.post("/api/v1/boards", json={"name": "Plain"}, headers=CSRF).json()
    admin.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "custom.value", "options": {"card": "queue-size"}}, headers=CSRF)
    document = yaml.safe_load(admin.get(f"/api/v1/boards/{board['slug']}/export").text)
    assert document["custom_cards"] == [PLAIN] and "own_integrations" not in document


def test_karten12_ac5_a_definition_with_a_line_that_ends_in_blanks_comes_back_the_same(admin: TestClient) -> None:
    card = changed("author: Example Author", "author: Example Author   ", PLAIN)
    admin.post("/api/v1/cards", json={"yaml": card}, headers=CSRF)
    board = admin.post("/api/v1/boards", json={"name": "Plain"}, headers=CSRF).json()
    admin.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "custom.value", "options": {"card": "queue-size"}}, headers=CSRF)
    assert yaml.safe_load(admin.get(f"/api/v1/boards/{board['slug']}/export").text)["custom_cards"] == [card]


def test_karten12_ac5_a_card_that_was_deleted_is_left_out_and_the_board_goes_on_as_before(admin: TestClient) -> None:
    slug = own_board(admin)
    admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    document = yaml.safe_load(admin.get(f"/api/v1/boards/{slug}/export").text)
    assert "custom_cards" not in document and "own_integrations" not in document


def test_karten12_ac5_only_an_administrator_gets_the_definitions_and_a_board_edited_as_text_never(admin: TestClient) -> None:
    slug = own_board(admin)
    assert "custom_cards" not in yaml.safe_load(admin.get(f"/api/v1/boards/{slug}/export?ids=true").text)
    create_user(admin, "kim")
    admin.put(f"/api/v1/boards/{slug}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "view"}]}, headers=CSRF)
    member = TestClient(admin.app)
    login(member, "kim", "another-long-password")
    shown = member.get(f"/api/v1/boards/{slug}/export")
    assert shown.status_code == 200 and "custom_cards" not in shown.text and "own_integrations" not in shown.text


def test_karten12_ac5_a_new_nexdeck_file_still_imports_where_the_definitions_are_not_asked_for(admin: TestClient) -> None:
    slug = own_board(admin)
    text = admin.get(f"/api/v1/boards/{slug}/export").text
    made = admin.post("/api/v1/boards/import", json={"yaml_text": text, "slug": "wiki-copy"}, headers=CSRF)
    assert made.status_code == 201, made.text
