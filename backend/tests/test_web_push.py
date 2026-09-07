"""Web Push: the three addresses that had no test at all.

⚠️ Subscribing does more than it says: it also creates the account's
notification channel and three subscriptions on first use. That is a side
effect nobody was checking, on a path that was shipped and then broken for a
whole release (0.31.0 went out with Push dead, because the CSP blocked the
service worker and nothing measured it).

The secret half is the auth key of a browser's subscription, which is stored
encrypted. A test that only counted rows would not have noticed it being
written in the clear.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import NotificationChannel, PushSubscription, Subscription

from .conftest import CSRF, create_user, login, setup_admin

A_BROWSER = {
    "endpoint": "https://push.example.com/send/abc123",
    "keys": {"p256dh": "BPencodedpublickeythatisnotreal", "auth": "aGVsbG8td29ybGQ"},
}


def test_a_browser_that_subscribes_gets_a_channel_and_its_events(client: TestClient) -> None:
    setup_admin(client)
    answer = client.post("/api/v1/push/subscribe", json={"subscription": A_BROWSER}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    assert answer.json()["ok"] is True

    with db_session() as db:
        channel = db.scalar(select(NotificationChannel).where(NotificationChannel.kind == "webpush"))
        assert channel is not None, "subscribing did not make the channel it says it makes"
        assert channel.enabled
        events = sorted(db.scalars(select(Subscription.event).where(Subscription.channel_id == channel.id)))
        assert events == ["action_failed", "outage", "recovery"]


def test_subscribing_twice_does_not_make_a_second_channel(client: TestClient) -> None:
    setup_admin(client)
    first = client.post("/api/v1/push/subscribe", json={"subscription": A_BROWSER}, headers=CSRF)
    second = client.post("/api/v1/push/subscribe", json={
        "subscription": {**A_BROWSER, "endpoint": "https://push.example.com/send/def456"},
    }, headers=CSRF)
    assert first.json()["channel_id"] == second.json()["channel_id"]
    with db_session() as db:
        assert len(list(db.scalars(select(NotificationChannel).where(NotificationChannel.kind == "webpush")))) == 1
        assert len(list(db.scalars(select(PushSubscription)))) == 2, "the second browser was not remembered"


def test_the_key_of_a_browser_is_not_stored_in_the_clear(client: TestClient) -> None:
    """⚠️ The auth key lets anybody who has it send a notification to that
    browser. It goes in encrypted, like every other stored secret.
    """
    setup_admin(client)
    client.post("/api/v1/push/subscribe", json={"subscription": A_BROWSER}, headers=CSRF)
    with db_session() as db:
        row = db.scalar(select(PushSubscription))
        assert row is not None
        assert row.auth != A_BROWSER["keys"]["auth"], "the key is in the database as it arrived"
        assert row.auth.startswith("enc:")
        # The public half is not a secret and stays readable.
        assert row.p256dh == A_BROWSER["keys"]["p256dh"]


def test_an_incomplete_subscription_is_refused_in_words(client: TestClient) -> None:
    setup_admin(client)
    for missing in ({"endpoint": "", "keys": A_BROWSER["keys"]}, {"endpoint": A_BROWSER["endpoint"], "keys": {}}):
        refused = client.post("/api/v1/push/subscribe", json={"subscription": missing}, headers=CSRF)
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "bad_subscription"


def test_a_browser_can_be_taken_off_again(client: TestClient) -> None:
    setup_admin(client)
    client.post("/api/v1/push/subscribe", json={"subscription": A_BROWSER}, headers=CSRF)
    gone = client.request("DELETE", "/api/v1/push/subscribe", json={"endpoint": A_BROWSER["endpoint"]}, headers=CSRF)
    assert gone.status_code == 204, gone.text
    with db_session() as db:
        assert list(db.scalars(select(PushSubscription))) == []


def test_one_account_cannot_take_another_browser_off(client: TestClient) -> None:
    """⚠️ The endpoint is the only thing the caller sends, and it is guessable
    in the sense that it is not secret: it appears in the other account's own
    settings page. The account has to match.
    """
    setup_admin(client)
    client.post("/api/v1/push/subscribe", json={"subscription": A_BROWSER}, headers=CSRF)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    kim.request("DELETE", "/api/v1/push/subscribe", json={"endpoint": A_BROWSER["endpoint"]}, headers=CSRF)
    with db_session() as db:
        assert len(list(db.scalars(select(PushSubscription)))) == 1, "Kim took somebody else's browser off"


def test_the_public_key_needs_a_session(client: TestClient) -> None:
    setup_admin(client)
    stranger = TestClient(client.app)
    assert stranger.get("/api/v1/push/key").status_code == 401
    mine = client.get("/api/v1/push/key")
    assert mine.status_code == 200
    assert isinstance(mine.json()["key"], str)


# -- a way back in ------------------------------------------------------------


def test_a_locked_out_administrator_has_a_way_back(client: TestClient) -> None:
    """⚠️ The only way back used to be a mail, and without a mail server the
    sign-in page did not even offer the link. An installation whose last
    administrator lost their password was finished.
    """
    setup_admin(client)
    from app.services import password_reset

    link = password_reset.rescue_link("https://deck.example.com")
    assert link.startswith("https://deck.example.com/reset/nr_"), link

    token = link.rsplit("/", 1)[-1]
    looked = client.get(f"/api/v1/auth/reset/{token}")
    assert looked.status_code == 200, looked.text

    used = client.post("/api/v1/auth/reset", json={"token": token, "new_password": "a-brand-new-long-password"}, headers=CSRF)
    assert used.status_code in (200, 204), used.text

    # And it works exactly once.
    again = client.post("/api/v1/auth/reset", json={"token": token, "new_password": "another-long-password"}, headers=CSRF)
    assert again.status_code >= 400, "the rescue link was good for a second use"


def test_the_rescue_link_says_so_when_there_is_nobody_to_let_in(client: TestClient) -> None:
    import pytest

    from app.services import password_reset

    with pytest.raises(RuntimeError):
        password_reset.rescue_link("https://deck.example.com")
