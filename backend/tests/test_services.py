"""History, health checks, notifications, the path language and the iCal parser."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.ical import occurrences, parse_ics
from app.adapters.uptimekuma import parse_metrics
from app.db import db_session
from app.models import HealthCheck, Notice, Outage, Widget
from app.services import health as health_service
from app.services import history, notify
from app.services.jsonpath import PathError, extract

from .conftest import CSRF, setup_admin

# -- history -----------------------------------------------------------------


def test_history_records_condenses_and_prunes(client: TestClient) -> None:
    setup_admin(client)
    now = int(time.time())
    with db_session() as db:
        for offset in range(0, 3 * 3600, 60):
            history.record(db, 1, {"cpu": float(offset % 100)}, ts=now - offset)
        assert history.sample_count(db) == 180
        history.condense(db, now=now)
        remaining_raw = history.sample_count(db)
        assert remaining_raw == 60, "one hour of raw samples stays"
        points = history.series(db, 1, "cpu", hours=24)
        assert len(points) > 60, "minute rows carry the older two hours"
        assert points == sorted(points, key=lambda p: p[0])
        history.condense(db, now=now + 30 * 3600)
        assert history.series(db, 1, "cpu", hours=24) == [], "everything older than a day is gone"


# -- health ------------------------------------------------------------------


@respx.mock
async def test_http_check_counts_401_as_reachable_and_5xx_as_down() -> None:
    respx.get("http://svc/login").mock(return_value=httpx.Response(401))
    respx.get("http://svc/broken").mock(return_value=httpx.Response(502))
    respx.get("http://svc/exact").mock(return_value=httpx.Response(204))
    ok, _, detail = await health_service.check_http("http://svc/login", 5, 0, False)
    assert ok and detail == "HTTP 401"
    ok, _, _ = await health_service.check_http("http://svc/broken", 5, 0, False)
    assert not ok
    ok, _, _ = await health_service.check_http("http://svc/exact", 5, 200, False)
    assert not ok, "an expected status is exact"


async def test_tcp_check_needs_host_and_port() -> None:
    ok, _, detail = await health_service.check_tcp("nonsense", 1)
    assert not ok and "host:port" in detail


def test_outage_is_announced_after_the_threshold(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "H"}, headers=CSRF).json()
    widget = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.app", "title": "Svc", "link": "http://svc.invalid", "options": {"check": True}}, headers=CSRF).json()["widget"]
    emitted: list[tuple[str, str]] = []
    monkeypatch.setattr(notify, "emit", lambda event, title, body="", **kw: emitted.append((event, title)))
    with db_session() as db:
        check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == widget["id"]))
        assert check is not None and check.target == "http://svc.invalid"
        check_id = check.id
    service = health_service.HealthService()
    service._record(check_id, ok=False, latency=10, detail="ConnectError")
    assert emitted == [], "a first failure is not yet an outage"
    with db_session() as db:
        check = db.get(HealthCheck, check_id)
        check.down_since = datetime.now(UTC) - timedelta(seconds=600)
    service._record(check_id, ok=False, latency=10, detail="ConnectError")
    assert emitted == [("outage", "Svc is down")]
    service._record(check_id, ok=False, latency=10, detail="ConnectError")
    assert len(emitted) == 1, "announced once"
    service._record(check_id, ok=True, latency=12, detail="HTTP 200")
    assert emitted[-1][0] == "recovery"
    with db_session() as db:
        outage = db.scalar(select(Outage))
        assert outage is not None and outage.ended_at is not None and outage.announced
        assert db.get(HealthCheck, check_id).down_since is None
        bars = health_service.uptime_bars(db, widget["id"])
        assert len(bars) == 48 and any(b is not None for b in bars)


def test_app_tile_without_link_has_no_check(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "H"}, headers=CSRF).json()
    widget = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.app", "title": "No link"}, headers=CSRF).json()["widget"]
    assert widget["health"] is None
    with db_session() as db:
        assert db.get(Widget, widget["id"]).health_check is None


# -- notify ------------------------------------------------------------------


def test_emit_creates_notices_for_admins_only(client: TestClient) -> None:
    from .conftest import create_user

    admin = setup_admin(client)
    create_user(client, "sam")
    notify.emit("outage", "X is down", "details", level="error")
    with db_session() as db:
        notices = list(db.scalars(select(Notice)))
        assert [n.user_id for n in notices] == [admin["id"]]
        assert notices[0].level == "error"
    listed = client.get("/api/v1/notices").json()
    assert listed[0]["title"] == "X is down" and listed[0]["read_at"] is None
    assert client.get("/api/v1/auth/unread").json()["unread"] == 1
    client.post("/api/v1/notices/read", json={"all": True}, headers=CSRF)
    assert client.get("/api/v1/auth/unread").json()["unread"] == 0


def test_channel_secrets_are_encrypted_and_test_message_formats(client: TestClient) -> None:
    from app.services.channels import plain_text, store_channel_config

    stored = store_channel_config("telegram", {"bot_token": "123:abc", "chat_id": "42"})
    assert stored["bot_token"].startswith("enc:") and stored["chat_id"] == "42"
    kept = store_channel_config("telegram", {"bot_token": "********", "chat_id": "43"}, stored)
    assert kept["bot_token"] == stored["bot_token"] and kept["chat_id"] == "43"
    text = plain_text(notify.Message(event="outage", title="Radarr is down", body="No answer for 3 minutes.", level="error", link="https://deck.example.com/b/home"))
    assert text.startswith("🔴 Radarr is down\n") and text.endswith("https://deck.example.com/b/home")


def test_channel_endpoints_round_trip(client: TestClient) -> None:
    setup_admin(client)
    kinds = client.get("/api/v1/channel-kinds").json()
    assert {k["kind"] for k in kinds} >= {"telegram", "email", "webpush", "ntfy", "gotify", "discord", "slack", "apprise"}
    created = client.post("/api/v1/channels", json={"kind": "ntfy", "name": "Phone", "config": {"url": "https://ntfy.sh", "topic": "deck", "token": "tk"}, "events": ["outage"]}, headers=CSRF)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["config"]["token"] == "********" and body["events"] == ["outage"]
    patched = client.patch(f"/api/v1/channels/{body['id']}", json={"events": ["outage", "recovery"]}, headers=CSRF).json()
    assert patched["events"] == ["outage", "recovery"]
    assert client.post("/api/v1/channels", json={"kind": "carrier-pigeon", "name": "x"}, headers=CSRF).status_code == 400


# -- json path ---------------------------------------------------------------


def test_json_path_language() -> None:
    data = {"data": {"items": [{"name": "a", "n": 1}, {"name": "b", "n": 2}], "temp": "21,5"}}
    assert extract(data, "data.items[0].name") == "a"
    assert extract(data, "data.items[*].n") == [1, 2]
    assert extract(data, "$.data.items[-1].name") == "b"
    assert extract(data, "") is data
    with pytest.raises(PathError):
        extract(data, "data.missing")
    with pytest.raises(PathError):
        extract(data, "data.items[9]")
    with pytest.raises(PathError):
        extract(data, "data.items[*].name.x")


# -- ical --------------------------------------------------------------------


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Dentist\\, again
DTSTART;VALUE=DATE:20260910
DTEND;VALUE=DATE:20260911
LOCATION:Main street 1
END:VEVENT
BEGIN:VEVENT
SUMMARY:Weekly|
 call
DTSTART:20260901T090000Z
RRULE:FREQ=WEEKLY;COUNT=4
END:VEVENT
BEGIN:VEVENT
SUMMARY:Birthday
DTSTART;VALUE=DATE:19900912
RRULE:FREQ=YEARLY
END:VEVENT
END:VCALENDAR
""".replace("|", " ")


def test_ics_parser_and_recurrence() -> None:
    events = parse_ics(ICS)
    assert [e["summary"] for e in events] == ["Dentist, again", "Weekly call", "Birthday"]
    assert events[0]["all_day"] is True and events[0]["location"] == "Main street 1"
    window = (date(2026, 9, 7), date(2026, 9, 21))
    assert occurrences(events[0], *window) == [date(2026, 9, 10)]
    assert occurrences(events[1], *window) == [date(2026, 9, 8), date(2026, 9, 15)]
    assert occurrences(events[2], *window) == [date(2026, 9, 12)], "a yearly rule from 1990 lands on this year's date"


# -- prometheus text ---------------------------------------------------------


def test_prometheus_text_parser_handles_labels_with_commas() -> None:
    rows = parse_metrics('monitor_status{monitor_name="A, B",monitor_type="http"} 1\n# comment\nbad line\n')
    assert rows == [("monitor_status", {"monitor_name": "A, B", "monitor_type": "http"}, 1.0)]
