"""Integrations: secrets stay encrypted and never come back out."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import Integration

from .conftest import CSRF, setup_admin


def test_secret_is_encrypted_in_the_database_and_masked_in_the_api(client: TestClient) -> None:
    setup_admin(client)
    created = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "very-secret"}}, headers=CSRF)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["config"]["api_key"] == "********"
    assert body["config"]["url"] == "http://radarr:7878"
    with db_session() as db:
        row = db.scalar(select(Integration))
        assert row is not None
        assert row.config["api_key"].startswith("enc:")
        assert "very-secret" not in row.config["api_key"]
    listed = client.get("/api/v1/integrations").json()
    assert "very-secret" not in str(listed)


def test_patch_without_secret_keeps_the_stored_one(client: TestClient) -> None:
    setup_admin(client)
    created = client.post("/api/v1/integrations", json={"kind": "sonarr", "name": "Series", "config": {"url": "http://sonarr:8989", "api_key": "first"}}, headers=CSRF).json()
    with db_session() as db:
        before = db.get(Integration, created["id"]).config["api_key"]
    client.patch(f"/api/v1/integrations/{created['id']}", json={"config": {"url": "http://sonarr:8990", "api_key": "********"}}, headers=CSRF)
    with db_session() as db:
        after = db.get(Integration, created["id"])
        assert after.config["api_key"] == before, "the placeholder must not overwrite the stored secret"
        assert after.config["url"] == "http://sonarr:8990"


def test_required_fields_and_unknown_kinds(client: TestClient) -> None:
    setup_admin(client)
    missing = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "R", "config": {"url": "http://r"}}, headers=CSRF)
    assert missing.status_code == 400
    assert "api_key" in missing.json()["detail"]["message"]
    assert client.post("/api/v1/integrations", json={"kind": "does-not-exist", "name": "X", "config": {}}, headers=CSRF).status_code == 400
    # Demo integrations need no credentials.
    assert client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Demo", "config": {}, "demo": True}, headers=CSRF).status_code == 201


def test_only_admins_manage_integrations(client: TestClient) -> None:
    from .conftest import create_user, login

    setup_admin(client)
    create_user(client, "sam")
    sam = TestClient(client.app)
    login(sam, "sam", "another-long-password")
    assert sam.get("/api/v1/integrations").status_code == 200
    assert sam.post("/api/v1/integrations", json={"kind": "radarr", "name": "R", "config": {"url": "http://r", "api_key": "k"}}, headers=CSRF).status_code == 403


def test_catalogue_lists_every_adapter_with_widgets(client: TestClient) -> None:
    setup_admin(client)
    adapters = client.get("/api/v1/adapters").json()
    assert len(adapters) >= 30
    for adapter in adapters:
        assert adapter["label"] and adapter["widgets"], adapter["kind"]
        for widget in adapter["widgets"]:
            assert widget["kind"].startswith(adapter["kind"] + "."), widget
            assert widget["renderer"]
