"""The problems card also names a tile whose reachability check fails.

⚠️ It read the live state of the cards, and an app tile draws itself in the
browser and has none. Its check failed, the tile went red, and the problems
card beside it said "Everything is fine". Found on 07.09.2026, still there on
12.09.2026.
"""

from __future__ import annotations

import asyncio
import time

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import get_adapter
from app.adapters.base import Context
from app.db import db_session
from app.models import HealthCheck
from app.services.collector import collector

from .conftest import CSRF, setup_admin


def _board(client: TestClient, name: str = "Lab") -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _widget(client: TestClient, page_id: int, kind: str, **extra: object) -> dict:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()["widget"]


def test_a_tile_whose_check_fails_is_a_problem(client: TestClient) -> None:
    setup_admin(client)
    page_id = _board(client)["pages"][0]["id"]
    # An address the check refuses at once, so it fails without waiting on a network.
    tile = _widget(client, page_id, "core.app", title="Router", link="http://127.0.0.1:9/", options={"check": True})
    problems = _widget(client, page_id, "core.problems", title="Problems")
    for widget in (tile, problems):
        collector.unschedule(widget["id"])

    deadline = time.monotonic() + 20
    while True:
        with db_session() as db:
            check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == tile["id"]))
            assert check is not None, "the tile got no check, so this proves nothing"
            if check.last_ok is False:
                reason = check.last_error
                break
        assert time.monotonic() < deadline, "the check never ran"
        time.sleep(0.2)

    ctx = Context(httpx.AsyncClient(), widget_id=problems["id"], cache={})
    data = asyncio.run(get_adapter("core").fetch("problems", {}, {}, ctx))
    assert [(item["title"], item["status"], item["subtitle"]) for item in data.items] == [("Router", "bad", reason)]
    assert data.status == "bad"
