"""The mail server of the installation, e-mail addresses and passwords set by an administrator."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin

SMTP = {
    "host": "smtp.example.com",
    "port": 587,
    "security": "starttls",
    "username": "deck",
    "password": "letmein",
    "from_address": "deck@example.com",
    "from_name": "nexdeck",
}


def test_mail_settings_are_stored_and_the_password_stays_here(client: TestClient) -> None:
    setup_admin(client)
    assert client.get("/api/v1/settings/mail").json()["configured"] is False

    saved = client.put("/api/v1/settings/mail", json=SMTP, headers=CSRF)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["host"] == "smtp.example.com"
    assert body["configured"] is True
    assert body["password"] == "********", "the password must never travel back"

    # Reading again keeps the mask, and the stored secret is not the plain text.
    assert client.get("/api/v1/settings/mail").json()["password"] == "********"
    from app.crypto import decrypt
    from app.db import db_session
    from app.services import mail

    with db_session() as db:
        stored = mail.stored(db)
    assert stored["password"] != "letmein"
    assert decrypt(stored["password"]) == "letmein"


def test_the_mask_coming_back_keeps_the_stored_password(client: TestClient) -> None:
    setup_admin(client)
    client.put("/api/v1/settings/mail", json=SMTP, headers=CSRF)
    client.put("/api/v1/settings/mail", json={**SMTP, "password": "********", "port": 2525}, headers=CSRF)

    from app.crypto import decrypt
    from app.db import db_session
    from app.services import mail

    with db_session() as db:
        stored = mail.stored(db)
    assert stored["port"] == 2525
    assert decrypt(stored["password"]) == "letmein", "sending the mask back must not wipe the password"


def test_a_server_without_a_sender_is_refused(client: TestClient) -> None:
    setup_admin(client)
    refused = client.put("/api/v1/settings/mail", json={**SMTP, "from_address": ""}, headers=CSRF)
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "no_sender"
    crooked = client.put("/api/v1/settings/mail", json={**SMTP, "from_address": "not-an-address"}, headers=CSRF)
    assert crooked.json()["detail"]["code"] == "bad_address"


def test_only_administrators_touch_the_mail_server(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    assert other.get("/api/v1/settings/mail").status_code == 403
    assert other.put("/api/v1/settings/mail", json=SMTP, headers=CSRF).status_code == 403


def test_the_test_message_goes_through_the_stored_server(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    client.put("/api/v1/settings/mail", json=SMTP, headers=CSRF)
    client.patch("/api/v1/auth/me", json={"email": "boss@example.com"}, headers=CSRF)

    sent: list[tuple[dict[str, Any], str, str]] = []

    def fake_send(config: dict[str, Any], to_address: str, subject: str, body: str) -> None:
        sent.append((config, to_address, subject))

    from app.services import mail

    monkeypatch.setattr(mail, "send", fake_send)

    # Without an address of its own it goes to the administrator's.
    answer = client.post("/api/v1/settings/mail/test", json={"to_address": ""}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["to_address"] == "boss@example.com"
    assert sent[0][1] == "boss@example.com"
    assert sent[0][0]["host"] == "smtp.example.com"

    # A given address wins.
    client.post("/api/v1/settings/mail/test", json={"to_address": "other@example.com"}, headers=CSRF)
    assert sent[1][1] == "other@example.com"


def test_a_test_message_without_a_recipient_says_so(client: TestClient) -> None:
    setup_admin(client)
    client.put("/api/v1/settings/mail", json=SMTP, headers=CSRF)
    refused = client.post("/api/v1/settings/mail/test", json={"to_address": ""}, headers=CSRF)
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "no_recipient"


def test_sending_without_a_server_fails_readably() -> None:
    from app.services import mail

    with pytest.raises(mail.MailError) as caught:
        mail.send({**mail.DEFAULTS}, "you@example.com", "Subject", "Body")
    assert caught.value.code == "not_configured"


def test_an_account_keeps_its_own_address(client: TestClient) -> None:
    setup_admin(client)
    assert client.get("/api/v1/auth/me").json()["email"] == ""

    saved = client.patch("/api/v1/auth/me", json={"email": " Boss@Example.com "}, headers=CSRF)
    assert saved.status_code == 200
    assert saved.json()["email"] == "Boss@Example.com", "trimmed, but written as it was typed"

    crooked = client.patch("/api/v1/auth/me", json={"email": "boss(at)example.com"}, headers=CSRF)
    assert crooked.status_code == 400
    assert crooked.json()["detail"]["code"] == "bad_address"
    assert client.get("/api/v1/auth/me").json()["email"] == "Boss@Example.com", "a refused change keeps the old one"

    cleared = client.patch("/api/v1/auth/me", json={"email": ""}, headers=CSRF)
    assert cleared.json()["email"] == ""


def test_two_accounts_cannot_share_an_address(client: TestClient) -> None:
    """A password reset has to end at one account, so the address names one."""
    setup_admin(client)
    create_user(client, "kim")
    client.patch("/api/v1/auth/me", json={"email": "shared@example.com"}, headers=CSRF)

    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    refused = other.patch("/api/v1/auth/me", json={"email": "SHARED@example.com"}, headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "taken"

    # Keeping one's own address is not a collision with oneself.
    assert client.patch("/api/v1/auth/me", json={"email": "shared@example.com"}, headers=CSRF).status_code == 200


def test_an_administrator_sets_a_password_and_ends_the_sessions(client: TestClient) -> None:
    setup_admin(client)
    kim = create_user(client, "kim")
    other = TestClient(client.app)
    login(other, "kim", "another-long-password")
    assert other.get("/api/v1/auth/me").status_code == 200

    changed = client.patch(f"/api/v1/users/{kim['id']}", json={"password": "a-fresh-long-password"}, headers=CSRF)
    assert changed.status_code == 200
    assert other.get("/api/v1/auth/me").status_code == 401, "the old session must be gone"

    fresh = TestClient(client.app)
    assert fresh.post("/api/v1/auth/login", json={"username": "kim", "password": "another-long-password"}).status_code == 401
    login(fresh, "kim", "a-fresh-long-password")


def test_nobody_else_sets_a_password(client: TestClient) -> None:
    setup_admin(client)
    kim = create_user(client, "kim")
    create_user(client, "robin")
    other = TestClient(client.app)
    login(other, "robin", "another-long-password")
    assert other.patch(f"/api/v1/users/{kim['id']}", json={"password": "a-fresh-long-password"}, headers=CSRF).status_code == 403
