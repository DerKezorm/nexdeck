"""KARTEN-14: the Card shop is off until an administrator turns it on, and only administrators reach it (AC-1, AC-2, AC-11, AC-13, EC-5)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import respx
from fastapi.testclient import TestClient

from app.services.collector import collector
from app.workshop import catalog

from .conftest import CSRF, create_user, login, setup_admin

ROUTES = [
    ("GET", "/api/v1/workshop/state"),
    ("PUT", "/api/v1/workshop/settings"),
]


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    catalog.forget()
    yield client
    catalog.forget()


def test_karten14_ac2_off_from_the_start_and_nothing_goes_to_github(admin: TestClient) -> None:
    """The installation never asks GitHub before the shop is turned on; every request that would leave fails the test."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as network:
        found = admin.get("/api/v1/workshop/state")
        assert found.status_code == 200, found.text
        body = found.json()
        assert body["enabled"] is False
        assert body["repo"] == "DerKezorm/nexdeck-workshop"
        assert body["catalog"] is None
        assert len(network.calls) == 0


def test_karten14_ac2_turning_it_on_asks_nothing_yet(admin: TestClient) -> None:
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as network:
        turned = admin.put("/api/v1/workshop/settings", json={"enabled": True}, headers=CSRF)
        assert turned.status_code == 200, turned.text
        assert turned.json()["enabled"] is True
        assert admin.get("/api/v1/workshop/state").json()["enabled"] is True
        assert len(network.calls) == 0


def test_karten14_ec5_turning_it_off_forgets_the_catalog(admin: TestClient) -> None:
    admin.put("/api/v1/workshop/settings", json={"enabled": True}, headers=CSRF)
    catalog._kept["DerKezorm/nexdeck-workshop"] = catalog._Kept(catalog.Catalog([], "", 1.0))  # noqa: SLF001
    assert admin.get("/api/v1/workshop/state").json()["catalog"] is not None
    admin.put("/api/v1/workshop/settings", json={"enabled": False}, headers=CSRF)
    state = admin.get("/api/v1/workshop/state").json()
    assert state["enabled"] is False
    assert state["catalog"] is None
    assert catalog.known("DerKezorm/nexdeck-workshop") is None


def test_karten14_the_repository_is_written_owner_slash_name(admin: TestClient) -> None:
    refused = admin.put("/api/v1/workshop/settings", json={"repo": "https://evil.example.com/x"}, headers=CSRF)
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "bad_repo"
    assert admin.put("/api/v1/workshop/settings", json={"repo": "someone/their-catalog"}, headers=CSRF).json()["repo"] == "someone/their-catalog"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_karten14_ac1_a_user_who_is_not_an_administrator_is_refused(admin: TestClient, method: str, path: str) -> None:
    create_user(admin, "member")
    login(admin, "member", "another-long-password")
    refused = admin.request(method, path, json={} if method == "PUT" else None, headers=CSRF)
    assert refused.status_code == 403, refused.text


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_karten14_ac1_nobody_signed_out_reaches_it(client: TestClient, method: str, path: str) -> None:
    refused = client.request(method, path, json={} if method == "PUT" else None, headers=CSRF)
    assert refused.status_code in (401, 403), refused.text


def test_karten14_ac11_the_key_is_told_as_set_and_never_shown(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert admin.get("/api/v1/workshop/state").json()["token_set"] is False
    monkeypatch.setenv("NEXDECK_WORKSHOP_TOKEN", "ghp_example-key-0123456789")
    found = admin.get("/api/v1/workshop/state")
    assert found.json()["token_set"] is True
    assert "ghp_example-key-0123456789" not in found.text
