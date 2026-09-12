"""A browser's push subscription follows whoever signs in on it, and nobody who only knows its address.

⚠️ ``store_subscription`` took any endpoint and wrote the caller's account over
whoever had it. With keys of their own, somebody who learned the address of
another person's browser moved that person's notifications to an account they
cannot be decrypted for, and the owner simply stopped getting any. Found on
12.09.2026.

The same browser signing in as somebody else is ordinary, and it sends the same
keys, because the keys belong to the browser's subscription and not to the
account.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from .conftest import CSRF, create_user, login, setup_admin

ENDPOINT = "https://push.example.com/send/one-browser"


def _body(p256dh: str = "BBrowserPublicKey", auth: str = "browser-auth-secret") -> dict:
    return {"subscription": {"endpoint": ENDPOINT, "keys": {"p256dh": p256dh, "auth": auth}}}


def _owner() -> tuple[str, str]:
    from app.db import db_session
    from app.models import PushSubscription, User

    with db_session() as db:
        row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == ENDPOINT))
        assert row is not None
        user = db.get(User, row.user_id)
        assert user is not None
        return user.username, row.p256dh


def test_an_endpoint_is_not_taken_over_with_keys_of_somebody_else(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "neighbour")
    assert client.post("/api/v1/push/subscribe", json=_body(), headers=CSRF).status_code == 201
    login(client, "neighbour", "another-long-password")
    taken = client.post("/api/v1/push/subscribe", json=_body(p256dh="BSomebodyElse", auth="not-the-browser"), headers=CSRF)
    assert taken.status_code == 400, taken.text
    assert _owner() == ("admin", "BBrowserPublicKey")


def test_the_same_browser_signing_in_as_somebody_else_takes_its_subscription_along(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "neighbour")
    assert client.post("/api/v1/push/subscribe", json=_body(), headers=CSRF).status_code == 201
    login(client, "neighbour", "another-long-password")
    moved = client.post("/api/v1/push/subscribe", json=_body(), headers=CSRF)
    assert moved.status_code == 201, moved.text
    assert _owner() == ("neighbour", "BBrowserPublicKey")
