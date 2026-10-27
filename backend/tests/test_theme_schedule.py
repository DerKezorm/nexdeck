"""Light and dark by the clock: for an account, and for a wall display."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import migrations

from .conftest import CSRF, create_user, login, setup_admin


def test_an_account_can_follow_the_clock(client: TestClient) -> None:
    setup_admin(client)
    me = client.get("/api/v1/auth/me").json()
    assert (me["light_from"], me["dark_from"]) == ("07:00", "20:00"), "a sensible day before anybody chose one"

    changed = client.patch("/api/v1/auth/me", json={"theme": "schedule", "light_from": "06:30", "dark_from": "21:15"}, headers=CSRF)
    assert changed.status_code == 200, changed.text
    assert (changed.json()["theme"], changed.json()["light_from"], changed.json()["dark_from"]) == ("schedule", "06:30", "21:15")
    again = client.get("/api/v1/auth/me").json()
    assert (again["theme"], again["light_from"], again["dark_from"]) == ("schedule", "06:30", "21:15")

    # Switching to dark keeps the times for the next time the clock decides.
    client.patch("/api/v1/auth/me", json={"theme": "dark"}, headers=CSRF)
    assert client.get("/api/v1/auth/me").json()["light_from"] == "06:30"


def test_an_account_refuses_times_that_are_no_times(client: TestClient) -> None:
    setup_admin(client)
    for wrong in ("24:00", "7:00", "07:60", "noon", "07:00:00"):
        answer = client.patch("/api/v1/auth/me", json={"theme": "schedule", "light_from": wrong}, headers=CSRF)
        assert answer.status_code == 422, wrong
    same = client.patch("/api/v1/auth/me", json={"light_from": "20:00"}, headers=CSRF)
    assert same.status_code == 400
    assert same.json()["detail"]["code"] == "same_times"
    assert client.get("/api/v1/auth/me").json()["light_from"] == "07:00", "nothing changed"
    assert client.patch("/api/v1/auth/me", json={"theme": "sometimes"}, headers=CSRF).status_code == 422


def test_a_display_is_dark_unless_told_otherwise(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Hall"}, headers=CSRF).json()
    made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall display"}, headers=CSRF).json()
    assert (made["theme"], made["light_from"], made["dark_from"]) == ("dark", "07:00", "20:00")

    display = TestClient(client.app)
    display.post("/api/v1/kiosk/session", json={"token": made["token"]}, headers=CSRF)
    assert display.get("/api/v1/kiosk").json()["kiosk"]["theme"] == "dark"


def test_a_display_goes_by_the_clock_and_can_be_changed_on_the_wall(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Hall"}, headers=CSRF).json()
    made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens",
                       json={"name": "Tablet", "theme": "schedule", "light_from": "06:00", "dark_from": "22:00"}, headers=CSRF)
    assert made.status_code == 201, made.text
    display = TestClient(client.app)
    display.post("/api/v1/kiosk/session", json={"token": made.json()["token"]}, headers=CSRF)
    shown = display.get("/api/v1/kiosk").json()["kiosk"]
    assert (shown["theme"], shown["light_from"], shown["dark_from"]) == ("schedule", "06:00", "22:00")
    shown = display.get(f"/api/v1/boards/{board['slug']}").json()["kiosk"]
    assert shown["theme"] == "schedule", "the board address tells the display the same"

    changed = client.patch(f"/api/v1/kiosk-tokens/{made.json()['id']}/look", json={"theme": "system"}, headers=CSRF)
    assert changed.status_code == 200, changed.text
    assert changed.json()["theme"] == "system"
    assert "token" not in changed.json(), "the token is shown once, when it is made"
    assert display.get("/api/v1/kiosk").json()["kiosk"]["theme"] == "system", "the same link, a new look"
    assert client.get(f"/api/v1/boards/{board['slug']}/kiosk-tokens").json()[0]["theme"] == "system"


def test_a_display_refuses_a_day_without_light(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Hall"}, headers=CSRF).json()
    same = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"theme": "schedule", "light_from": "08:00", "dark_from": "08:00"}, headers=CSRF)
    assert same.status_code == 422
    made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall"}, headers=CSRF).json()
    assert client.patch(f"/api/v1/kiosk-tokens/{made['id']}/look", json={"theme": "schedule", "light_from": "9:00"}, headers=CSRF).status_code == 422
    assert client.patch(f"/api/v1/kiosk-tokens/{made['id'] + 99}/look", json={"theme": "light"}, headers=CSRF).status_code == 404


def test_only_who_may_edit_the_board_changes_its_display(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Hall"}, headers=CSRF).json()
    made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall"}, headers=CSRF).json()
    create_user(client, "member")
    other = TestClient(client.app)
    login(other, "member", "another-long-password")
    refused = other.patch(f"/api/v1/kiosk-tokens/{made['id']}/look", json={"theme": "light"}, headers=CSRF)
    assert refused.status_code in (403, 404)
    assert client.get(f"/api/v1/boards/{board['slug']}/kiosk-tokens").json()[0]["theme"] == "dark"


def test_the_columns_come_to_an_old_database(tmp_path) -> None:  # noqa: ANN001
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, theme VARCHAR(8))"))
        connection.execute(text("CREATE TABLE kiosk_tokens (id INTEGER PRIMARY KEY, name VARCHAR(80))"))
        connection.execute(text("INSERT INTO users (id, theme) VALUES (1, 'light')"))
        connection.execute(text("INSERT INTO kiosk_tokens (id, name) VALUES (1, 'Hall')"))
        migrations._theme_schedule_columns(connection)
        migrations._theme_schedule_columns(connection)  # a second run changes nothing
        assert connection.execute(text("SELECT theme, light_from, dark_from FROM users")).one() == ("light", "07:00", "20:00")
        assert connection.execute(text("SELECT theme, light_from, dark_from FROM kiosk_tokens")).one() == ("dark", "07:00", "20:00")
