"""KARTEN-12: boards from files in data/boards/ bring their custom cards and own connections with them (AC-8, EC-3)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import forget_all_custom, get_adapter
from app.db import db_session
from app.models import Board, CardRecord, Event, OwnIntegration
from app.services import provisioning
from app.services.collector import collector

from .cards_sample import changed
from .conftest import CSRF, setup_admin
from .karten12_sample import CARD, INTEGRATION, PLAIN, SHORT

LOGGER = "nexdeck.provisioning"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    yield client
    # An own kind made by a test stays in the registry of the process: the tests that count the kinds would see it.
    forget_all_custom()


def wiki_file(admin: TestClient) -> str:
    """The board file of a board that shows a card of its own on a connection of an own kind, as an administrator exports it; nothing of it is left here."""
    assert admin.post("/api/v1/own-integrations", json={"yaml": INTEGRATION}, headers=CSRF).status_code == 201
    assert admin.post("/api/v1/cards", json={"yaml": CARD}, headers=CSRF).status_code == 201
    made = admin.post(
        "/api/v1/integrations",
        json={"kind": f"custom:{SHORT}", "name": "Wiki", "config": {"url": "http://wiki.example.com", "token_id": "ID-1", "token_secret": "SECRET-1"}}, headers=CSRF,
    )
    board = admin.post("/api/v1/boards", json={"name": "Wiki"}, headers=CSRF).json()
    body = {"kind": "custom.value", "integration_id": made.json()["id"], "options": {"card": "queue-size"}}
    admin.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json=body, headers=CSRF)
    text = admin.get(f"/api/v1/boards/{board['slug']}/export").text
    assert admin.delete(f"/api/v1/boards/{board['slug']}", headers=CSRF).status_code in (200, 204)
    admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    admin.delete(f"/api/v1/own-integrations/{SHORT}", headers=CSRF)
    return text


def put(data_dir: Path, text: str, name: str = "wiki.yaml") -> Path:
    directory = data_dir / "boards"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def card_text() -> str | None:
    with db_session() as db:
        return db.scalar(select(CardRecord.yaml_source).where(CardRecord.slug == "queue-size"))


def shorts() -> list[str]:
    with db_session() as db:
        return sorted(db.scalars(select(OwnIntegration.short)))


def loaded() -> bool:
    with db_session() as db:
        return db.scalar(select(Board.id).where(Board.slug == "wiki")) is not None


def test_karten12_ac8_a_board_file_makes_the_definitions_it_carries_without_asking(admin: TestClient, data_dir: Path) -> None:
    text = wiki_file(admin)
    assert card_text() is None and shorts() == []
    put(data_dir, text)
    provisioning.load_all()
    assert loaded() and card_text() == CARD and shorts() == [SHORT]
    assert get_adapter(f"custom:{SHORT}") is not None, "the connection of the file names the kind, so it is known"
    with db_session() as db:
        row = db.scalar(select(CardRecord))
        assert row is not None and (row.origin, row.users_may_place, row.created_by) == ("local", False, None)


def test_karten12_ac8_a_file_that_comes_again_with_the_same_definitions_changes_nothing(admin: TestClient, data_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    put(data_dir, wiki_file(admin))
    provisioning.load_all()
    with db_session() as db:
        stamp = db.scalar(select(CardRecord.updated_at))
    caplog.set_level(logging.INFO, logger=LOGGER)
    provisioning.load_all()
    with db_session() as db:
        assert db.scalar(select(CardRecord.updated_at)) == stamp
    assert "replaced" not in caplog.text and "made from" not in caplog.text


def test_karten12_ec3_the_file_wins_over_a_definition_here_and_the_journal_says_what_it_replaced(admin: TestClient, data_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = wiki_file(admin)
    mine = changed('version: "1.0.0"', 'version: "7.0.0"', CARD)
    assert admin.post("/api/v1/cards", json={"yaml": mine}, headers=CSRF).status_code == 201
    assert admin.post("/api/v1/own-integrations", json={"yaml": INTEGRATION.replace("name: BookStack", "name: Mine", 1)}, headers=CSRF).status_code == 201
    caplog.set_level(logging.INFO, logger=LOGGER)
    put(data_dir, text)
    provisioning.load_all()
    assert card_text() == CARD, "the file wins"
    assert admin.get(f"/api/v1/own-integrations/{SHORT}").json()["name"] == "BookStack"
    assert "custom card queue-size replaced from boards/wiki.yaml" in caplog.text
    assert f"own connection {SHORT} replaced from boards/wiki.yaml" in caplog.text
    with db_session() as db:
        lines = [(one.kind, one.name, one.detail) for one in db.scalars(select(Event).where(Event.kind == "card_definition_changed").order_by(Event.id))]
    assert ("card_definition_changed", "queue-size", "replaced from boards/wiki.yaml") in lines


def test_karten12_ec3_a_changed_file_replaces_again_on_the_next_read(admin: TestClient, data_dir: Path) -> None:
    text = wiki_file(admin)
    path = put(data_dir, text)
    provisioning.load_all()
    document = yaml.safe_load(text)
    newer = changed('version: "1.0.0"', 'version: "2.0.0"', CARD)
    document["custom_cards"] = [newer]
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    provisioning._load(path)  # noqa: SLF001 - what the watch does when the modification time changes
    assert card_text() == newer


def test_karten12_ec3_a_file_that_is_wrong_about_a_definition_is_given_up_on_and_leaves_nothing_behind(admin: TestClient, data_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    document = yaml.safe_load(wiki_file(admin))
    document["custom_cards"] = [PLAIN, changed("form: value", "form: nonsense", changed("slug: queue-size", "slug: second", CARD))]
    caplog.set_level(logging.WARNING, logger=LOGGER)
    put(data_dir, yaml.safe_dump(document))
    provisioning.load_all()
    assert not loaded() and card_text() is None and shorts() == []
    with pytest.raises(KeyError):
        get_adapter(f"custom:{SHORT}")
    assert "Board file wiki.yaml was not loaded" in caplog.text and "second" in caplog.text


def test_karten12_ec3_a_board_that_fails_after_its_definitions_leaves_them_unmade(admin: TestClient, data_dir: Path) -> None:
    document = yaml.safe_load(wiki_file(admin))
    document["pages"][0]["widgets"].append({"kind": "nope.nothing", "title": "bad"})
    put(data_dir, yaml.safe_dump(document))
    provisioning.load_all()
    assert not loaded() and card_text() is None and shorts() == []
    with pytest.raises(KeyError):
        get_adapter(f"custom:{SHORT}")
