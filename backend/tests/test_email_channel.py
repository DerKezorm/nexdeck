"""The e-mail channel uses the installation's own mail server.

It used to ask every person for a host, a port, a user name, a password, a
sender and a recipient: the same mail account typed out again per channel,
password included, in a place where nobody would think to update it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.channels import KINDS, kinds_payload

from .conftest import CSRF, setup_admin

SMTP = {
    "host": "smtp.example.com", "port": 587, "security": "starttls",
    "username": "deck", "password": "a-long-enough-password", "from_address": "deck@example.com",
}


def test_the_channel_asks_for_one_thing(client: TestClient) -> None:
    fields = {field.name for field in KINDS["email"].fields}
    assert fields == {"to_address"}
    assert "host" not in fields, "the server belongs to the installation, not to a channel"
    assert "password" not in fields, "and its password certainly does"


def test_it_is_not_offered_while_no_mail_server_is_set_up(client: TestClient) -> None:
    """⚠️ It has nothing of its own to configure. Offering it without a server
    would mean a channel that looks finished, saves, and then fails silently
    at the first outage, which is the worst moment to find out."""
    setup_admin(client)
    kinds = [row["kind"] for row in client.get("/api/v1/channel-kinds").json()]
    assert "email" not in kinds
    assert "ntfy" in kinds, "the others are still there"

    assert client.put("/api/v1/settings/mail", json=SMTP, headers=CSRF).status_code == 200
    kinds = [row["kind"] for row in client.get("/api/v1/channel-kinds").json()]
    assert "email" in kinds


def test_adding_one_without_a_mail_server_is_refused(client: TestClient) -> None:
    """The list is a courtesy; this is the rule."""
    setup_admin(client)
    refused = client.post("/api/v1/channels", json={
        "kind": "email", "name": "Mail", "config": {"to_address": "me@example.com"}, "events": ["outage"],
    }, headers=CSRF)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"]["code"] == "no_mail_server"


def test_it_can_be_added_once_a_server_is_there(client: TestClient) -> None:
    setup_admin(client)
    client.put("/api/v1/settings/mail", json=SMTP, headers=CSRF)
    made = client.post("/api/v1/channels", json={
        "kind": "email", "name": "Mail", "config": {"to_address": "me@example.com"}, "events": ["outage"],
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    assert made.json()["config"]["to_address"] == "me@example.com"


def test_the_list_can_be_asked_for_either_shape() -> None:
    """The service answers the question; the router asks it."""
    assert any(k["kind"] == "email" for k in kinds_payload(mail_ready=True))
    assert not any(k["kind"] == "email" for k in kinds_payload(mail_ready=False))


def test_sending_without_a_server_says_so_rather_than_failing_quietly(client: TestClient) -> None:
    """A channel from before this change still carries a host in its settings.
    Those are ignored now, and if there is no server the message says which
    one is missing."""
    import asyncio

    from app.services.channels import _email
    from app.services.notify import Message

    setup_admin(client)
    message = Message(event="test", title="x", body="y")
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        pass
    try:
        _email({"to_address": "me@example.com", "host": "old.example.com"}, message)
    except RuntimeError as failure:
        assert "mail server" in str(failure).lower()
    else:  # pragma: no cover - only reached if a server was configured
        raise AssertionError("it should have refused: no mail server is set up")
