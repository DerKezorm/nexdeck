"""Signed in on the home network without a password, and nowhere else.

The address is the connection's own; a forwarding header counts only from a
proxy named in NEXDECK_TRUSTED_PROXIES. The session counts only at home, and
it cannot make itself a way in from elsewhere.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import home_network
from app.services.home_network import Refused, check_networks

from .conftest import CSRF, create_user, setup_admin

HOME = "192.168.1.0/24"
TABLET = ("192.168.1.20", 50000)
OUTSIDE = ("203.0.113.9", 50000)


def _browser(client: TestClient, where: tuple[str, int], headers: dict[str, str] | None = None) -> TestClient:
    return TestClient(client.app, client=where, headers=headers)


def _kitchen(client: TestClient) -> int:
    setup_admin(client)
    kitchen = create_user(client, "kitchen")
    answer = client.put("/api/v1/settings/home-network", json={"enabled": True, "networks": [HOME], "user_id": kitchen["id"]}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    return kitchen["id"]


def _sign_in(browser: TestClient, **body: object) -> object:
    return browser.post("/api/v1/auth/home", json=body, headers=CSRF)


# -- which networks ------------------------------------------------------------


def test_only_home_networks_are_taken() -> None:
    assert check_networks(["192.168.1.0/24", " 10.0.0.0/8 ", "fd00::/8", "100.64.0.0/10", "192.168.1.7", ""]) == [
        "192.168.1.0/24", "10.0.0.0/8", "fd00::/8", "100.64.0.0/10", "192.168.1.7/32"]
    for wide in ("0.0.0.0/0", "8.8.8.0/24", "192.0.0.0/2", "172.0.0.0/8", "::/0", "2001:db8::/32"):
        with pytest.raises(Refused, match="beyond a home network"):
            check_networks([wide])
    with pytest.raises(Refused, match="this machine itself"):
        check_networks(["127.0.0.0/8"])
    with pytest.raises(Refused, match="not a network"):
        check_networks(["kitchen"])


def test_an_administrator_is_never_the_home_account_and_a_required_factor_rules_it_out(client: TestClient) -> None:
    setup_admin(client)
    admin_id = client.get("/api/v1/auth/me").json()["id"]
    refused = client.put("/api/v1/settings/home-network", json={"enabled": True, "networks": [HOME], "user_id": admin_id}, headers=CSRF)
    assert refused.status_code == 400 and "administrator" in refused.json()["detail"]["message"]
    kitchen = create_user(client, "kitchen")
    assert client.put("/api/v1/settings/home-network", json={"enabled": True, "networks": [], "user_id": kitchen["id"]}, headers=CSRF).status_code == 400
    # Straight in the database: through the settings the administrator, who
    # has no factor either, would be kept at the door first and never get here.
    from app.db import db_session
    from app.services import two_factor

    with db_session() as db:
        two_factor.set_required(db, True)
        with pytest.raises(Refused, match="second factor"):
            home_network.store(db, home_network.Settings(True, (HOME,), kitchen["id"]))


# -- which address ---------------------------------------------------------------


def test_the_address_is_the_connections_own_and_a_stranger_cannot_forward_it(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _kitchen(client)
    assert _browser(client, TABLET).get("/api/v1/auth/home").json()["available"] is True
    assert _browser(client, OUTSIDE).get("/api/v1/auth/home").json() == {"available": False}
    # From outside, claiming to be the tablet: the header is somebody else's word.
    spoofed = _browser(client, OUTSIDE, {"X-Forwarded-For": "192.168.1.20"})
    assert _sign_in(spoofed).status_code == 401
    # A proxy at home that nobody named would bring the whole Internet in.
    proxied = _browser(client, ("192.168.1.2", 50000), {"X-Forwarded-For": "203.0.113.9"})
    assert _sign_in(proxied).status_code == 401

    monkeypatch.setenv("NEXDECK_TRUSTED_PROXIES", "192.168.1.2")
    assert _sign_in(_browser(client, ("192.168.1.2", 50000), {"X-Forwarded-For": "203.0.113.9"})).status_code == 401
    # Read from the right: what a stranger wrote on the left does not count.
    forged = _browser(client, ("192.168.1.2", 50000), {"X-Forwarded-For": "192.168.1.20, 203.0.113.9"})
    assert _sign_in(forged).status_code == 401
    assert _sign_in(_browser(client, ("192.168.1.2", 50000), {"X-Forwarded-For": "192.168.1.20"})).status_code == 200
    assert _sign_in(_browser(client, ("192.168.1.2", 50000), {"X-Real-IP": "192.168.1.21"})).status_code == 200
    # The proxy's own requests, without saying for whom: unknown.
    assert _sign_in(_browser(client, ("192.168.1.2", 50000))).status_code == 401


def test_the_administrator_sees_what_nexdeck_makes_of_the_address(client: TestClient) -> None:
    _kitchen(client)
    admin = _browser(client, ("192.168.1.2", 50000), {"X-Forwarded-For": "203.0.113.9"})
    admin.cookies = client.cookies
    seen = admin.get("/api/v1/settings/home-network").json()["seen"]
    assert seen["address"] is None and seen["how"] == "forwarded_by_unknown"


# -- the session -------------------------------------------------------------------


def test_the_tablet_is_signed_in_and_the_session_stays_at_home(client: TestClient) -> None:
    kitchen_id = _kitchen(client)
    tablet = _browser(client, TABLET)
    assert tablet.post("/api/v1/auth/home", json={}).status_code == 403, "not without the app's header"
    signed = _sign_in(tablet)
    assert signed.status_code == 200 and signed.json()["id"] == kitchen_id and signed.json()["auth_kind"] == "home"
    assert tablet.get("/api/v1/auth/me").status_code == 200

    carried = _browser(client, OUTSIDE)
    carried.cookies = tablet.cookies
    assert carried.get("/api/v1/auth/me").status_code == 401, "the cookie opens nothing outside"

    recent = client.get("/api/v1/settings/home-network").json()["recent"]
    assert recent[0]["username"] == "kitchen" and recent[0]["address"] == "192.168.1.20"

    # A change of the setting ends every session opened under the old one.
    client.put("/api/v1/settings/home-network", json={"enabled": True, "networks": ["10.0.0.0/8", HOME], "user_id": kitchen_id}, headers=CSRF)
    assert tablet.get("/api/v1/auth/me").status_code == 401


def test_a_session_at_home_makes_no_way_in_from_elsewhere(client: TestClient) -> None:
    _kitchen(client)
    board = client.post("/api/v1/boards", json={"name": "Kitchen"}, headers=CSRF).json()
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "edit"}]}, headers=CSRF)
    tablet = _browser(client, TABLET)
    _sign_in(tablet)
    for method, path, body in (
        ("post", "/api/v1/auth/password", {"current_password": "", "new_password": "a-new-long-password"}),
        ("patch", "/api/v1/auth/me", {"email": "kitchen@example.com"}),
        ("post", "/api/v1/tokens", {"name": "script"}),
        ("post", "/api/v1/auth/two-factor/start", {}),
        ("post", f"/api/v1/boards/{board['slug']}/kiosk-tokens", {"name": "wall"}),
    ):
        answer = getattr(tablet, method)(path, json=body, headers=CSRF)
        assert answer.status_code == 403 and answer.json()["detail"]["code"] == "home_session", (path, answer.text)
    # What stays on the tablet may still change.
    assert tablet.patch("/api/v1/auth/me", json={"theme": "dark"}, headers=CSRF).status_code == 200


def test_signing_out_holds_the_automatic_sign_in_off_until_asked_again(client: TestClient) -> None:
    _kitchen(client)
    tablet = _browser(client, TABLET)
    _sign_in(tablet)
    assert tablet.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
    assert tablet.cookies.get(home_network.OFF_COOKIE)
    assert tablet.get("/api/v1/auth/home").json()["held_off"] is True
    held = _sign_in(tablet)
    assert held.status_code == 401 and held.json()["detail"]["code"] == "held_off"
    assert _sign_in(tablet, again=True).status_code == 200
    assert not tablet.cookies.get(home_network.OFF_COOKIE)


def test_switched_off_nobody_is_signed_in_at_home(client: TestClient) -> None:
    kitchen_id = _kitchen(client)
    tablet = _browser(client, TABLET)
    _sign_in(tablet)
    client.put("/api/v1/settings/home-network", json={"enabled": False, "networks": [HOME], "user_id": kitchen_id}, headers=CSRF)
    assert tablet.get("/api/v1/auth/me").status_code == 401
    assert _sign_in(tablet).status_code == 401
    assert tablet.get("/api/v1/auth/home").json() == {"available": False}


def test_a_factor_required_later_ends_the_sign_in_at_home(client: TestClient) -> None:
    _kitchen(client)
    tablet = _browser(client, TABLET)
    _sign_in(tablet)
    from app.db import db_session
    from app.services import two_factor

    with db_session() as db:
        two_factor.set_required(db, True)
    assert tablet.get("/api/v1/auth/home").json() == {"available": False}
    assert tablet.get("/api/v1/boards").status_code == 401


def test_the_log_still_names_the_forwarded_address(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    """Keeping the connection's own address changed nothing for the log and the
    sign-in brake: they read the forwarded one, as under uvicorn's old flag."""
    setup_admin(client)
    proxied = _browser(client, ("192.168.1.2", 50000), {"X-Forwarded-For": "198.51.100.7"})
    with caplog.at_level("INFO", logger="nexdeck.auth"):
        proxied.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert "from 198.51.100.7" in caplog.text
