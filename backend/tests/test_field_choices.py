"""The dropdown that asks the service what to offer.

⚠️ It reaches a connection by a number that came out of a widget's settings,
which is the exact shape of the hole that let four other places read a locked
connection. It goes through the same guard.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin


def _unifi(client: TestClient, admin_only: bool = False) -> dict:
    made = client.post("/api/v1/integrations", json={
        "kind": "unifi", "name": "UniFi",
        "config": {"url": "https://unifi.example.com", "api_key": "a-key", "site": "default"},
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    row = made.json()
    if admin_only:
        client.patch(f"/api/v1/integrations/{row['id']}", json={"admin_only": True}, headers=CSRF)
    return row


def test_a_connection_that_does_not_exist_is_a_404(client: TestClient) -> None:
    setup_admin(client)
    assert client.get("/api/v1/integrations/9999/choices/device").status_code == 404


def test_a_field_nobody_offers_answers_with_an_empty_list(client: TestClient) -> None:
    setup_admin(client)
    row = _unifi(client)
    answer = client.get(f"/api/v1/integrations/{row['id']}/choices/colour")
    assert answer.status_code == 200
    assert answer.json() == []


def test_a_locked_connection_hands_out_nothing(client: TestClient) -> None:
    """⚠️ A connection reserved for administrators must not read out its
    device names to anybody who can guess a number."""
    setup_admin(client)
    row = _unifi(client, admin_only=True)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    refused = kim.get(f"/api/v1/integrations/{row['id']}/choices/device")
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "integration_locked"


def test_signing_in_is_required(client: TestClient) -> None:
    setup_admin(client)
    row = _unifi(client)
    stranger = TestClient(client.app)
    assert stranger.get(f"/api/v1/integrations/{row['id']}/choices/device").status_code == 401


def test_a_service_that_will_not_answer_does_not_take_the_sheet_down(client: TestClient) -> None:
    """The console is not there; the field says so and the rest of the
    settings stay usable."""
    setup_admin(client)
    row = _unifi(client)
    answer = client.get(f"/api/v1/integrations/{row['id']}/choices/device")
    assert answer.status_code in (400, 502), answer.text
    assert answer.json()["detail"]["code"]
