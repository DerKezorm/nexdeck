"""The test button of a notification channel is not a way to send mail at will.

⚠️ Every member may add an e-mail channel with any address and press "Send a
test" as often as they like, and each press went out through the installation's
own mail server, on its good name with the mail provider. Members get nothing
else through their channels today, so the button was the whole lever. Found on
12.09.2026.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.routers import channels as channels_router

from .conftest import CSRF, setup_admin

#: Presses one account may make within the window.
LIMIT = 5


def _channel(client: TestClient, name: str) -> int:
    made = client.post("/api/v1/channels", json={
        "kind": "slack", "name": name, "config": {"webhook": "https://hooks.example.com/services/x"}, "events": [],
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    went_out: list[str] = []

    async def pretend(kind: str, config: dict, message: object, *, user_id: int | None = None) -> None:
        went_out.append(kind)

    monkeypatch.setattr(channels_router, "send", pretend)
    return went_out


def test_the_test_button_stops_after_a_few_presses_across_all_channels(client: TestClient, sent: list[str]) -> None:
    setup_admin(client)
    first, second = _channel(client, "One"), _channel(client, "Two")
    presses = [client.post(f"/api/v1/channels/{channel}/test", headers=CSRF) for channel in (first, second, first, second, first, second)]
    assert [press.status_code for press in presses] == [200] * LIMIT + [429]
    assert presses[-1].json()["detail"]["code"] == "too_many_tests"
    assert len(sent) == LIMIT


def test_the_button_works_again_after_the_window(client: TestClient, sent: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    channel = _channel(client, "One")
    now = [1000.0]
    monkeypatch.setattr(channels_router, "_now", lambda: now[0])
    for _ in range(LIMIT):
        assert client.post(f"/api/v1/channels/{channel}/test", headers=CSRF).status_code == 200
    assert client.post(f"/api/v1/channels/{channel}/test", headers=CSRF).status_code == 429
    now[0] += channels_router.TEST_WINDOW_SECONDS + 1
    assert client.post(f"/api/v1/channels/{channel}/test", headers=CSRF).status_code == 200
