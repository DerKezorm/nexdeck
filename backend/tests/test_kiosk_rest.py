"""A wall display can rest on a large clock after a while without a touch."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import migrations

from .conftest import CSRF, setup_admin


def test_a_display_learns_when_to_rest(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Hall"}, headers=CSRF).json()
    made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall display", "rest_minutes": 10}, headers=CSRF)
    assert made.status_code == 201, made.text
    assert made.json()["rest_minutes"] == 10
    assert client.get(f"/api/v1/boards/{board['slug']}/kiosk-tokens").json()[0]["rest_minutes"] == 10

    display = TestClient(client.app)
    display.post("/api/v1/kiosk/session", json={"token": made.json()["token"]}, headers=CSRF)
    assert display.get("/api/v1/kiosk").json()["kiosk"]["rest_minutes"] == 10


def test_a_display_made_before_rests_never(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Hall"}, headers=CSRF).json()
    made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall display"}, headers=CSRF).json()
    assert made["rest_minutes"] == 0
    refused = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall", "rest_minutes": 999}, headers=CSRF)
    assert refused.status_code == 422


def test_the_column_comes_to_an_old_database(tmp_path) -> None:  # noqa: ANN001
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE kiosk_tokens (id INTEGER PRIMARY KEY, name VARCHAR(80))"))
        connection.execute(text("INSERT INTO kiosk_tokens (id, name) VALUES (1, 'Hall')"))
        migrations._rest_column(connection)
        migrations._rest_column(connection)  # a second run changes nothing
        assert connection.execute(text("SELECT rest_minutes FROM kiosk_tokens")).scalar() == 0
