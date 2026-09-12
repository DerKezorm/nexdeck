"""A backup leaves the short history out, as it always meant to.

⚠️ ``CACHE_TABLES`` named ``widget_history``, a table that does not exist. The
tables are ``history_samples`` and ``history_minutes``, a day of chart points at
most and the largest part of the database, so every backup carried all of it
while its profile said ``emptied: []`` and nobody noticed. Found on 07.09.2026,
still there on 12.09.2026.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.db import db_session
from app.models import HistoryMinute, HistorySample
from app.services import backup

from .conftest import setup_admin


def _count(path: str, table: str) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - a fixed name
    finally:
        connection.close()


def test_a_backup_holds_no_chart_points_and_says_so(client: TestClient) -> None:
    setup_admin(client)
    with db_session() as db:
        db.add(HistorySample(key="1:cpu", ts=1789200000, value=12.5))
        db.add(HistoryMinute(key="1:cpu", ts=1789200000, avg=12.5, min=10.0, max=15.0, count=4))

    snapshot = backup.create(note="for the test")

    assert _count(str(snapshot), "history_samples") == 0
    assert _count(str(snapshot), "history_minutes") == 0
    profile = backup.Profile.from_json(backup._profile_path(snapshot).read_text(encoding="utf-8"))
    assert sorted(profile.emptied) == ["history_minutes", "history_samples"]

    # The running installation keeps its charts.
    with db_session() as db:
        assert db.query(HistorySample).count() == 1
        assert db.query(HistoryMinute).count() == 1
