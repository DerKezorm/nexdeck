"""A session nexdeck opens at a service is a session it closes.

A Reolink hub lets only a handful of accounts in at once and keeps a token
for an hour. On 11.09.2026 the hub turned nexdeck away with "too many users
are signed in" after an afternoon of restarts, and the code had four ways of
taking a seat without ever giving it back: cards logging in side by side, the
Test button, a saved connection and a deleted one. The first lives in the
adapter tests; the other three are here, through the addresses a person uses.
"""

from __future__ import annotations

import time

import respx
from fastapi.testclient import TestClient

from app.services.collector import collector

from .conftest import CSRF, setup_admin
from .test_adapters import CONFIG, REO, _Reolink


def _connection(client: TestClient) -> int:
    made = client.post("/api/v1/integrations", json={"kind": "reolink", "name": "Hub", "config": CONFIG}, headers=CSRF)
    assert made.status_code == 201, made.text
    return int(made.json()["id"])


def _until(check, seconds: float = 5.0) -> bool:  # noqa: ANN001
    """Wait for the effect, not for the clock: the logout runs on the app's own loop."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


def test_testing_a_connection_logs_out_again(client: TestClient) -> None:
    setup_admin(client)
    device = _Reolink()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{REO}/api.cgi").mock(side_effect=device)
        answer = client.post("/api/v1/integrations/test", json={"kind": "reolink", "config": CONFIG}, headers=CSRF)
        assert answer.json()["ok"] is True, answer.text
        assert device.logins == 1
        assert device.logouts == [("cam", "T1")], "the Test button took a seat and must give it back"


def test_testing_a_saved_connection_logs_out_again(client: TestClient) -> None:
    setup_admin(client)
    integration_id = _connection(client)
    device = _Reolink()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{REO}/api.cgi").mock(side_effect=device)
        answer = client.post(f"/api/v1/integrations/{integration_id}/test", headers=CSRF)
        assert answer.json()["ok"] is True, answer.text
        assert device.logouts == [("cam", "T1")]


def test_a_dropdown_asked_of_the_service_logs_out_again(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    """No Reolink field asks the device for its choices yet; the first one to do so must not cost a seat."""
    from app.adapters.reolink import ReolinkAdapter

    async def channels(self, field, config, ctx):  # noqa: ANN001, ANN202
        await self._token(config, ctx)
        return [("0", "Front door")]

    monkeypatch.setattr(ReolinkAdapter, "choices", channels)
    setup_admin(client)
    integration_id = _connection(client)
    device = _Reolink()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{REO}/api.cgi").mock(side_effect=device)
        offered = client.get(f"/api/v1/integrations/{integration_id}/choices/channel")
        assert offered.status_code == 200, offered.text
        assert device.logins == 1 and device.logouts == [("cam", "T1")]


def test_saving_or_deleting_a_connection_hands_back_the_session_its_cards_held(client: TestClient) -> None:
    """The cards' token sat in the connection's cache, and the cache was thrown away on every save."""
    setup_admin(client)
    integration_id = _connection(client)
    device = _Reolink()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{REO}/api.cgi").mock(side_effect=device)
        collector._caches[integration_id] = {"reolink_token": ("T7", time.monotonic() + 3000, REO, True)}
        saved = client.patch(f"/api/v1/integrations/{integration_id}", json={"name": "Hub downstairs"}, headers=CSRF)
        assert saved.status_code == 200, saved.text
        assert _until(lambda: ("cam", "T7") in device.logouts), f"saving must log the old session out, saw {device.logouts}"

        collector._caches[integration_id] = {"reolink_token": ("T8", time.monotonic() + 3000, REO, True)}
        gone = client.delete(f"/api/v1/integrations/{integration_id}", headers=CSRF)
        assert gone.status_code == 204, gone.text
        assert _until(lambda: ("cam", "T8") in device.logouts), f"deleting must log the session out, saw {device.logouts}"
