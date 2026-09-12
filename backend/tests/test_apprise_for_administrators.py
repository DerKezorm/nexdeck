"""Apprise channels are set up by administrators, and only theirs send.

⚠️ Apprise sends through its own HTTP library and follows redirects there, so
none of nexdeck's address checks reach its requests. A member could point a
channel at a server of their own that answers with a redirect to 127.0.0.1, and
read from the test result whether something listens beside nexdeck. Every other
kind goes through a client that checks each hop. Decided on 12.09.2026: Apprise
stays, for the people who may point the server anywhere already.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import NotificationChannel, User
from app.services import channels
from app.services.notify import Message

from .conftest import CSRF, create_user, login, setup_admin

APPRISE = {"kind": "apprise", "name": "Everything", "config": {"urls": "json://hooks.example.com/nexdeck"}, "events": []}
MESSAGE = Message(event="test", title="nexdeck test message", body="", level="info")


def _member(client: TestClient) -> TestClient:
    create_user(client, "kim")
    member = TestClient(client.app)
    login(member, "kim", "another-long-password")
    return member


def _id_of(username: str) -> int:
    with db_session() as db:
        user_id = db.scalar(select(User.id).where(User.username == username))
        assert user_id is not None
        return user_id


def test_a_member_is_not_offered_apprise_and_cannot_add_it(client: TestClient) -> None:
    setup_admin(client)
    member = _member(client)
    assert "apprise" not in {kind["kind"] for kind in member.get("/api/v1/channel-kinds").json()}
    refused = member.post("/api/v1/channels", json=APPRISE, headers=CSRF)
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "admin_only_channel"

    assert "apprise" in {kind["kind"] for kind in client.get("/api/v1/channel-kinds").json()}
    assert client.post("/api/v1/channels", json=APPRISE, headers=CSRF).status_code == 201


def test_an_apprise_channel_a_member_already_has_is_neither_changed_nor_sent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    member = _member(client)
    with db_session() as db:
        old = NotificationChannel(user_id=_id_of("kim"), kind="apprise", name="From before", config={"urls": "json://hooks.example.com/old"}, enabled=True)
        db.add(old)
        db.flush()
        channel_id = old.id

    import apprise

    notified: list[str] = []
    monkeypatch.setattr(apprise.Apprise, "notify", lambda self, **kwargs: notified.append(kwargs["title"]) or True)

    changed = member.patch(f"/api/v1/channels/{channel_id}", json={"config": {"urls": "json://127.0.0.1:8000/"}}, headers=CSRF)
    assert changed.status_code == 403, changed.text
    tested = member.post(f"/api/v1/channels/{channel_id}/test", headers=CSRF)
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is False
    assert "administrator" in tested.json()["message"]
    with pytest.raises(RuntimeError, match="administrator"):
        asyncio.run(channels.send("apprise", {"urls": "json://hooks.example.com/old"}, MESSAGE, user_id=_id_of("kim")))
    assert notified == []

    asyncio.run(channels.send("apprise", {"urls": "json://hooks.example.com/admin"}, MESSAGE, user_id=_id_of("admin")))
    assert notified == ["nexdeck test message"]
