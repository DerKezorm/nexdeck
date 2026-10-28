"""KARTEN-12: a card or an own connection as a file (AC-1, AC-4 as far as the file goes, EC-6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.cards import store
from app.db import db_session
from app.services.collector import collector

from .conftest import CSRF, create_user, login, setup_admin
from .karten12_sample import CARD, INTEGRATION, PLAIN, SHORT


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    return client


def keep(client: TestClient, card: str | None = CARD, integration: str | None = INTEGRATION) -> None:
    if integration is not None:
        assert client.post("/api/v1/own-integrations", json={"yaml": integration}, headers=CSRF).status_code == 201
    if card is not None:
        assert client.post("/api/v1/cards", json={"yaml": card}, headers=CSRF).status_code == 201


def documents(text: str) -> list[str]:
    return [part for part in text.split("---\n") if part.strip()]


def test_karten12_ac1_a_card_comes_as_a_file_word_for_word_with_comments_and_demo(admin: TestClient) -> None:
    keep(admin, PLAIN, None)
    answer = admin.get("/api/v1/cards/queue-size/export")
    assert answer.status_code == 200
    assert answer.headers["content-disposition"] == 'attachment; filename="queue-size.nexdeck.yaml"'
    assert answer.headers["content-type"].startswith("text/yaml")
    assert answer.text == PLAIN
    assert "# A comment on top stays where it is." in answer.text and "# either one" in answer.text
    assert "demo:" in answer.text


def test_karten12_ac1_an_own_connection_comes_as_a_file_alone(admin: TestClient) -> None:
    keep(admin)
    answer = admin.get(f"/api/v1/own-integrations/{SHORT}/export")
    assert answer.status_code == 200
    assert answer.headers["content-disposition"] == f'attachment; filename="{SHORT}.nexdeck.yaml"'
    assert answer.text == INTEGRATION
    assert "nexdeck-card" not in answer.text


def test_karten12_ac1_nothing_secret_goes_out_with_a_file(admin: TestClient) -> None:
    keep(admin)
    made = admin.post(
        "/api/v1/integrations",
        json={"kind": f"custom:{SHORT}", "name": "Mine", "config": {"url": "http://wiki.example.com", "token_id": "ID-1234", "token_secret": "SECRET-5678"}},
        headers=CSRF,
    )
    assert made.status_code == 201, made.text
    for path in ("/api/v1/cards/queue-size/export", f"/api/v1/own-integrations/{SHORT}/export"):
        body = admin.get(path).text
        assert "SECRET-5678" not in body and "ID-1234" not in body and "wiki.example.com" not in body


def test_karten12_ac4_a_card_brings_the_own_connection_it_names(admin: TestClient) -> None:
    keep(admin)
    parts = documents(admin.get("/api/v1/cards/queue-size/export").text)
    assert len(parts) == 2
    assert parts[0] == CARD and parts[1].startswith("nexdeck: integration") and parts[1].rstrip("\n") == INTEGRATION.rstrip("\n")


def test_karten12_ac4_a_card_whose_connection_is_not_here_comes_alone(admin: TestClient) -> None:
    keep(admin, CARD, None)
    assert documents(admin.get("/api/v1/cards/queue-size/export").text) == [CARD]


def test_karten12_ec6_a_card_from_the_shop_is_a_plain_file_without_the_shop(admin: TestClient) -> None:
    with db_session() as db:
        store.create(db, PLAIN, origin="shop", shop_ref="author/queue-size", shop_version="1.2.0")
    body = admin.get("/api/v1/cards/queue-size/export").text
    assert body == PLAIN
    assert "shop" not in body.lower() and "author/queue-size" not in body and "1.2.0" not in body


def test_karten12_only_administrators_export(admin: TestClient) -> None:
    keep(admin)
    create_user(admin, "kim")
    member = TestClient(admin.app)
    login(member, "kim", "another-long-password")
    assert member.get("/api/v1/cards/queue-size/export").status_code == 403
    assert member.get(f"/api/v1/own-integrations/{SHORT}/export").status_code == 403
    assert TestClient(admin.app).get("/api/v1/cards/queue-size/export").status_code == 401


def test_karten12_a_card_or_connection_that_is_not_there_is_a_404(admin: TestClient) -> None:
    assert admin.get("/api/v1/cards/nothing/export").status_code == 404
    assert admin.get("/api/v1/own-integrations/nothing/export").status_code == 404
