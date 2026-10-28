"""KARTEN-12: a board file that carries custom cards and own connections is read in: only an administrator makes them, and only when he agrees (AC-6, AC-7, EC-5)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import forget_all_custom, get_adapter
from app.cards import store
from app.db import db_session
from app.models import Board, CardRecord, OwnIntegration
from app.services.collector import collector
from app.services.state import live

from .cards_sample import changed
from .conftest import CSRF, login, setup_admin
from .karten12_sample import CARD, INTEGRATION, PLAIN, SHORT

API = "/api/v1/boards"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    yield client
    # An own kind made by a test stays in the registry of the process: the tests that count the kinds would see it.
    forget_all_custom()


def member_of(admin: TestClient, name: str = "kim") -> TestClient:
    made = admin.post("/api/v1/users", json={"username": name, "password": "another-long-password", "role": "user"}, headers=CSRF)
    assert made.status_code in (201, 409), made.text  # 409: the same member again
    member = TestClient(admin.app)
    login(member, name, "another-long-password")
    return member


def shows_card(admin: TestClient) -> str:
    """A board with the plain sample card on a connection a member may use; returns the board file as an administrator exports it."""
    assert admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF).status_code == 201
    made = admin.post("/api/v1/integrations", json={"kind": "sonarr", "name": "Shows", "config": {"url": "http://sonarr.example.com:8989", "api_key": "key-1"}}, headers=CSRF)
    assert made.status_code == 201, made.text
    board = admin.post(API, json={"name": "Shows"}, headers=CSRF).json()
    body = {"kind": "custom.value", "integration_id": made.json()["id"], "options": {"card": "queue-size"}}
    assert admin.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json=body, headers=CSRF).status_code == 201
    text = admin.get(f"{API}/{board['slug']}/export").text
    assert yaml.safe_load(text)["custom_cards"] == [PLAIN]
    return text


def other_instance(admin: TestClient, slug: str = "shows") -> None:
    """What the board file finds elsewhere: no board, no definitions (the connections stay, as they do when a definition is deleted)."""
    assert admin.delete(f"{API}/{slug}", headers=CSRF).status_code in (200, 204)
    admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    admin.delete(f"/api/v1/own-integrations/{SHORT}", headers=CSRF)


def import_file(client: TestClient, text: str, **more: Any):  # noqa: ANN202
    return client.post(f"{API}/import", json={"yaml_text": text, **more}, headers=CSRF)


def check(client: TestClient, text: str):  # noqa: ANN202
    return client.post(f"{API}/import/check", json={"yaml_text": text}, headers=CSRF)


def slugs() -> list[str]:
    with db_session() as db:
        return sorted(db.scalars(select(CardRecord.slug)))


def shorts() -> list[str]:
    with db_session() as db:
        return sorted(db.scalars(select(OwnIntegration.short)))


def boards() -> list[str]:
    with db_session() as db:
        return sorted(db.scalars(select(Board.slug)))


def test_karten12_ac6_the_check_says_which_definitions_are_missing_the_same_or_different(admin: TestClient) -> None:
    text = shows_card(admin)
    same = check(admin, text).json()
    assert same["can_create"] is True and [(one["id"], one["status"]) for one in same["definitions"]] == [("card:queue-size", "same")]
    assert same["definitions"][0]["slug"] == "queue-size" and same["definitions"][0]["requires"] == ["sonarr", "radarr"]
    admin.put("/api/v1/cards/queue-size", json={"yaml": changed('version: "1.0.0"', 'version: "1.1.0"')}, headers=CSRF)
    assert check(admin, text).json()["definitions"][0]["status"] == "different"
    admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    assert check(admin, text).json()["definitions"][0]["status"] == "missing"


def test_karten12_ac6_the_check_names_a_definition_that_is_wrong(admin: TestClient) -> None:
    document = yaml.safe_load(shows_card(admin))
    document["custom_cards"] = [changed("form: value", "form: nonsense")]
    wrong = check(admin, yaml.safe_dump(document)).json()["definitions"][0]
    assert wrong["status"] == "invalid" and wrong["problems"][0]["line"] is not None
    assert check(admin, "a: [unclosed").status_code == 400
    assert check(admin, "name: nothing\n").status_code == 400


def test_karten12_ac6_a_file_without_definitions_has_none_to_ask_about(admin: TestClient) -> None:
    admin.post(API, json={"name": "Plain"}, headers=CSRF)
    assert check(admin, admin.get(f"{API}/plain/export").text).json() == {"can_create": True, "definitions": [], "missing_integrations": []}


def test_karten12_ac6_nothing_is_made_until_the_administrator_agrees(admin: TestClient) -> None:
    text = shows_card(admin)
    other_instance(admin)
    asked = import_file(admin, text)
    assert asked.status_code == 201, asked.text
    assert slugs() == [] and asked.json()["definitions"]["created"] == []
    assert asked.json()["definitions"]["skipped"] == ["card:queue-size"], "the answer names what was not made"
    assert import_file(admin, text, definitions="skip", slug="shows-3").status_code == 201 and slugs() == []


def test_karten12_ac6_with_his_agreement_the_missing_definitions_are_made_with_the_board(admin: TestClient) -> None:
    text = shows_card(admin)
    other_instance(admin)
    made = import_file(admin, text, definitions="create")
    assert made.status_code == 201, made.text
    assert made.json()["definitions"] == {"created": ["card:queue-size"], "replaced": [], "same": [], "kept": [], "skipped": []}
    assert slugs() == ["queue-size"]
    with db_session() as db:
        row = db.scalar(select(CardRecord))
        assert row is not None and row.yaml_source == PLAIN and (row.origin, row.shop_ref) == ("local", "")
    assert made.json()["pages"][0]["widgets"][0]["options"] == {"card": "queue-size"}


def test_karten12_ac6_an_own_connection_of_the_file_works_for_the_board_that_names_it(admin: TestClient) -> None:
    assert admin.post("/api/v1/own-integrations", json={"yaml": INTEGRATION}, headers=CSRF).status_code == 201
    assert admin.post("/api/v1/cards", json={"yaml": CARD}, headers=CSRF).status_code == 201
    connection = admin.post(
        "/api/v1/integrations",
        json={"kind": f"custom:{SHORT}", "name": "Wiki", "config": {"url": "http://wiki.example.com", "token_id": "ID-1", "token_secret": "SECRET-1"}}, headers=CSRF,
    )
    board = admin.post(API, json={"name": "Wiki"}, headers=CSRF).json()
    admin.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "custom.value", "integration_id": connection.json()["id"], "options": {"card": "queue-size"}}, headers=CSRF)
    text = admin.get(f"{API}/wiki/export").text
    other_instance(admin, "wiki")
    refused = import_file(admin, text)
    assert refused.status_code == 400 and "own_integrations" in refused.json()["detail"]["message"], "without his agreement the kind is unknown"
    made = import_file(admin, text, definitions="create")
    assert made.status_code == 201, made.text
    assert sorted(made.json()["definitions"]["created"]) == sorted(["card:queue-size", f"integration:{SHORT}"])
    assert slugs() == ["queue-size"] and shorts() == [SHORT]
    assert get_adapter(f"custom:{SHORT}") is not None


def test_karten12_ac6_a_definition_here_with_another_text_stays_as_it_is(admin: TestClient) -> None:
    text = shows_card(admin)
    mine = changed('version: "1.0.0"', 'version: "7.0.0"')
    admin.put("/api/v1/cards/queue-size", json={"yaml": mine}, headers=CSRF)
    made = import_file(admin, text, definitions="create", slug="shows-2")
    assert made.status_code == 201, made.text
    assert made.json()["definitions"]["kept"] == ["card:queue-size"] and made.json()["definitions"]["created"] == []
    with db_session() as db:
        assert db.scalar(select(CardRecord.yaml_source)) == mine


def test_karten12_ac6_the_same_definition_is_left_alone(admin: TestClient) -> None:
    text = shows_card(admin)
    made = import_file(admin, text, definitions="create", slug="shows-2")
    assert made.json()["definitions"]["same"] == ["card:queue-size"] and slugs() == ["queue-size"]


def test_karten12_ec5_a_board_that_fails_leaves_the_definitions_it_would_have_made_unmade(admin: TestClient) -> None:
    assert admin.post("/api/v1/own-integrations", json={"yaml": INTEGRATION}, headers=CSRF).status_code == 201
    assert admin.post("/api/v1/cards", json={"yaml": CARD}, headers=CSRF).status_code == 201
    board = admin.post(API, json={"name": "Wiki"}, headers=CSRF).json()
    document = yaml.safe_load(admin.get(f"{API}/{board['slug']}/export").text)
    document = {**document, "custom_cards": [CARD], "own_integrations": [INTEGRATION]}
    document["pages"][0]["widgets"] = [{"kind": "core.clock", "title": "ok"}, {"kind": "nope.nothing", "title": "bad"}]
    text = yaml.safe_dump(document)
    other_instance(admin, board["slug"])
    before = boards()
    refused = import_file(admin, text, definitions="create")
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_import"
    assert slugs() == [] and shorts() == [] and boards() == before
    with pytest.raises(KeyError):
        get_adapter(f"custom:{SHORT}")


def test_karten12_ec5_a_definition_that_does_not_fit_stops_the_board(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    text = shows_card(admin)
    other_instance(admin)
    before = boards()
    monkeypatch.setattr(store, "MAX_CARDS", 0)
    refused = import_file(admin, text, definitions="create")
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_import" and boards() == before
    monkeypatch.setattr(store, "MAX_CARDS", 200)
    assert import_file(admin, text, definitions="create").status_code == 201


def test_karten12_ec5_a_definition_that_is_wrong_stops_the_board(admin: TestClient) -> None:
    document = yaml.safe_load(shows_card(admin))
    other_instance(admin)
    before = boards()
    document["custom_cards"] = [changed("form: value", "form: nonsense")]
    refused = import_file(admin, yaml.safe_dump(document), definitions="create")
    assert refused.status_code == 400 and "queue-size" in refused.json()["detail"]["message"]
    assert slugs() == [] and boards() == before


async def test_karten12_ac7_somebody_who_is_not_an_administrator_makes_no_definition_and_the_card_says_it_is_missing(admin: TestClient) -> None:
    text = shows_card(admin)
    other_instance(admin)
    member = member_of(admin)
    made = import_file(member, text)
    assert made.status_code == 201, made.text
    assert slugs() == [] and made.json()["definitions"]["created"] == [] and made.json()["definitions"]["skipped"] == ["card:queue-size"]
    widget = made.json()["pages"][0]["widgets"][0]["id"]
    await collector.refresh(widget)
    assert live.get(widget).meta["code"] == "definition_missing"


def test_karten12_ac7_asking_for_the_definitions_is_refused_and_nothing_is_made_not_even_the_board(admin: TestClient) -> None:
    text = shows_card(admin)
    other_instance(admin)
    member = member_of(admin)
    before = boards()
    refused = import_file(member, text, definitions="create")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "definitions_admin_only"
    assert slugs() == [] and boards() == before


def test_karten12_ac7_the_check_tells_a_member_nothing_about_what_is_here_and_offers_no_creating(admin: TestClient) -> None:
    text = shows_card(admin)
    member = member_of(admin)
    answered = check(member, text).json()
    assert answered["can_create"] is False and answered["missing_integrations"] == []
    assert [(one["id"], one["status"]) for one in answered["definitions"]] == [("card:queue-size", "unknown")]


def test_karten12_ac7_a_card_that_is_saved_and_not_released_is_still_refused_to_a_member(admin: TestClient) -> None:
    text = shows_card(admin)
    other_instance(admin)
    admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF)
    refused = import_file(member_of(admin), text)
    assert refused.status_code == 400 and "no card with that short name" in refused.json()["detail"]["message"]
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    assert import_file(member_of(admin, "kim"), text).status_code == 201


def test_karten12_a_board_file_that_is_wrong_about_its_definitions_is_refused_with_a_reason(admin: TestClient) -> None:
    document = yaml.safe_load(shows_card(admin))
    before = boards()
    for broken in ("text", [1, 2], {"a": 1}):
        refused = import_file(admin, yaml.safe_dump({**document, "custom_cards": broken}), definitions="create")
        assert refused.status_code == 400 and "custom_cards" in refused.json()["detail"]["message"]
    assert import_file(admin, yaml.safe_dump(document), definitions="maybe").status_code == 422
    assert boards() == before
