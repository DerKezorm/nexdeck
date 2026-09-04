"""Test fixtures: a fresh data directory and application per test."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

CSRF = {"X-Nexdeck-Request": "1"}
ADMIN = {"username": "admin", "password": "correct-horse-battery"}


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "data"
    directory.mkdir()
    monkeypatch.setenv("NEXDECK_DATA_DIR", str(directory))
    monkeypatch.setenv("NEXDECK_SECRET_KEY", "test-secret-key-not-for-production")
    monkeypatch.setenv("NEXDECK_DEMO", "0")
    monkeypatch.setenv("NEXDECK_HEALTH_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("NEXDECK_LOG_LEVEL", "WARNING")
    from app import config, crypto, db
    from app.services import collector as collector_module
    from app.services import login_guard

    config.reset_settings_cache()
    db.reset_engine()
    crypto.forget_key()
    collector_module.set_demo_flag(False)
    login_guard.reset()
    return directory


@pytest.fixture
def client(data_dir: Path) -> Iterator[TestClient]:
    from app.main import app
    from app.services.state import live

    live.clear()
    with TestClient(app) as test_client:
        yield test_client
    from app import db

    db.reset_engine()


def setup_admin(client: TestClient, demo: bool = False) -> dict:
    response = client.post("/api/v1/setup", json={**ADMIN, "demo": demo})
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def create_user(client: TestClient, username: str, role: str = "user", password: str = "another-long-password") -> dict:
    response = client.post("/api/v1/users", json={"username": username, "password": password, "role": role}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def env_flag(name: str) -> bool:
    return os.environ.get(name, "") not in ("", "0", "false")
