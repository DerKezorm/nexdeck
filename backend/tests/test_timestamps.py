"""A moment in time survives the database and the wire.

SQLite has no type for one. The column said ``timezone=True`` and the value
came back naive, so the JSON carried no offset and the browser read it as
local time: the same notice showed one time live and another after a reload,
off by the zone.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import ApiToken, Integration, Notice, User

from .conftest import CSRF, setup_admin

#: ``…Z`` or ``…+02:00``: something that says which zone the moment is in.
OFFSET = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


def test_a_stored_moment_still_knows_its_zone(client: TestClient) -> None:
    """The round trip, at the layer where the marker used to be lost."""
    setup_admin(client)
    with db_session() as db:
        db.add(User(username="clock", display_name="clock", password_hash="x", role="user"))
    with db_session() as db:
        row = db.scalar(select(User).where(User.username == "clock"))
        assert row is not None
        assert row.created_at.tzinfo is not None, "the offset was dropped on the way out"
        # The comparison that used to raise TypeError.
        assert datetime.now(UTC) - row.created_at < timedelta(minutes=5)


def test_the_api_writes_an_offset_on_every_moment(client: TestClient) -> None:
    """Whatever the endpoint, a timestamp says which zone it is in.

    Without it the browser reads the text as local time, and every duration
    drawn from it is wrong by the zone.
    """
    setup_admin(client)
    client.post("/api/v1/tokens", json={"name": "script"}, headers=CSRF)
    client.post("/api/v1/integrations", json={"kind": "docker", "name": "Docker", "config": {}, "demo": True}, headers=CSRF)
    client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF)

    checked = 0
    for path in ("/api/v1/tokens", "/api/v1/integrations", "/api/v1/auth/sessions"):
        answer = client.get(path)
        assert answer.status_code == 200, f"{path}: {answer.text}"
        for field, value in _timestamps(answer.json()):
            checked += 1
            assert OFFSET.search(value), f"{path} → {field} = {value!r} has no zone"
    assert checked >= 4, "no timestamp was looked at; this test would pass on anything"


def test_a_notice_reads_the_same_before_and_after_a_reload(client: TestClient) -> None:
    """The one a person actually saw.

    Live over the event stream the browser was handed a real moment; on a
    reload it was handed text without a zone and read it as local time. The
    same notice then showed two different times.
    """
    setup_admin(client)
    with db_session() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        db.add(Notice(user_id=admin.id, event="widget_down", level="info", title="Something happened", body="", created_at=datetime.now(UTC)))

    answer = client.get("/api/v1/notices")
    assert answer.status_code == 200, answer.text
    rows = answer.json()
    rows = rows.get("notices", rows) if isinstance(rows, dict) else rows
    assert rows, "the notice should be listed"
    stamp = rows[0]["created_at"]
    assert OFFSET.search(stamp), f"a notice without a zone: {stamp!r}"
    assert abs((datetime.fromisoformat(stamp) - datetime.now(UTC)).total_seconds()) < 300


def test_a_moment_written_in_another_zone_is_stored_as_utc(client: TestClient) -> None:
    """Whatever goes in, UTC comes out; otherwise two rows cannot be compared."""
    setup_admin(client)
    berlin = datetime(2026, 9, 6, 12, 0, tzinfo=UTC).astimezone()
    with db_session() as db:
        db.add(Integration(kind="docker", name="Zoned", config={}, demo=True, created_at=berlin))
    with db_session() as db:
        row = db.scalar(select(Integration).where(Integration.name == "Zoned"))
        assert row is not None
        assert row.created_at.tzinfo is not None
        assert row.created_at == berlin, "the same moment, however it was written"


def test_an_expiry_can_be_compared_without_a_crash(client: TestClient) -> None:
    """The failure this started from: a naive value out of the database met
    ``datetime.now(UTC)`` and raised TypeError, which reads as a 500."""
    setup_admin(client)
    made = client.post("/api/v1/tokens", json={"name": "script", "expires_days": 1}, headers=CSRF)
    assert made.status_code == 201, made.text
    with db_session() as db:
        row = db.scalar(select(ApiToken))
        assert row is not None and row.expires_at is not None
        assert row.expires_at > datetime.now(UTC)


def _timestamps(payload: object, prefix: str = "") -> list[tuple[str, str]]:
    """Every field whose name ends in ``_at`` and whose value is text."""
    found: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.endswith("_at") and isinstance(value, str) and value:
                found.append((f"{prefix}{key}", value))
            else:
                found += _timestamps(value, f"{prefix}{key}.")
    elif isinstance(payload, list):
        for index, entry in enumerate(payload):
            found += _timestamps(entry, f"{prefix}[{index}].")
    return found


def test_the_endpoints_still_report_timestamps(client: TestClient) -> None:
    """A guard on the guard: if nothing carried a timestamp any more, the test
    above would pass by looking at nothing."""
    setup_admin(client)
    client.post("/api/v1/integrations", json={"kind": "docker", "name": "Docker", "config": {}, "demo": True}, headers=CSRF)
    client.post("/api/v1/tokens", json={"name": "script"}, headers=CSRF)
    assert _timestamps(client.get("/api/v1/integrations").json()), "integrations stopped reporting when they were made"
    assert _timestamps(client.get("/api/v1/tokens").json()), "tokens stopped reporting when they were made"
