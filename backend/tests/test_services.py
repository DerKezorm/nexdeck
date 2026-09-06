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
    # ⚠️ No "email": it is offered only once a mail server is set up, because
    # it has nothing of its own to configure and would otherwise save happily
    # and fail at the first outage. tests/test_email_channel.py covers it.
    assert {k["kind"] for k in kinds} >= {"telegram", "webpush", "ntfy", "gotify", "discord", "slack", "apprise"}
    assert "email" not in {k["kind"] for k in kinds}
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


def test_icon_names_and_search_merge_both_collections(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The picker browses every name once; the search ranks prefix matches first. No network here."""
    import time

    from app.services import icons

    far = time.monotonic() + 3600
    monkeypatch.setattr(icons, "_index", {"dashboard-icons": (far, ["sonarr", "radarr", "radarr-4k"]), "selfhst": (far, ["plex", "sonarr"])})
    setup_admin(client)
    names = [entry for entry in client.get("/api/v1/icons/names").json() if entry["source"] != "bundled"]
    assert [entry["name"] for entry in names] == ["plex", "radarr", "radarr-4k", "sonarr"]
    assert names[0]["source"] == "selfhst" and names[3]["source"] == "dashboard-icons"
    hits = client.get("/api/v1/icons/search?q=rad").json()
    assert [entry["name"] for entry in hits] == ["radarr", "radarr-4k"]
    assert client.get("/api/v1/icons/search?q=nothing-here").json() == []


def test_bundled_logos_are_served_and_listed_without_network(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The nexapps logos ship with nexdeck: no collection carries them, and no request leaves the house."""
    import time

    from app.services import icons

    far = time.monotonic() + 3600
    monkeypatch.setattr(icons, "_index", {"dashboard-icons": (far, ["radarr"]), "selfhst": (far, [])})
    setup_admin(client)
    logo = client.get("/api/v1/icons/nexview.svg")
    assert logo.status_code == 200 and logo.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in logo.content and b"<!--" not in logo.content
    names = client.get("/api/v1/icons/names").json()
    assert {"name": "nexview", "source": "bundled"} in names
    assert [entry["name"] for entry in client.get("/api/v1/icons/search?q=nex").json()] == ["nexdeck", "nexmail", "nexview"]


async def test_ping_without_subprocess_support_is_a_readable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows with the selector loop cannot spawn ping; the tile says so instead of the log filling up."""
    import asyncio

    from app.services import health

    async def no_processes(*_args, **_kwargs):
        raise NotImplementedError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_processes)
    ok, latency, detail = await health.check_ping("example.com", 2)
    assert ok is False and latency == 0
    assert "HTTP or TCP" in detail


async def test_one_broken_check_does_not_stop_the_others(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import select

    from app.db import db_session
    from app.models import HealthCheck
    from app.services import health

    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    page_id = board["pages"][0]["id"]
    for target in ("http://one.example.com", "http://two.example.com"):
        widget = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.app", "link": target}, headers=CSRF).json()["widget"]
        client.put(f"/api/v1/widgets/{widget['id']}/health", json={"kind": "http", "target": target}, headers=CSRF)

    async def flaky(check: HealthCheck) -> tuple[bool, int, str]:
        if "one" in check.target:
            raise RuntimeError("boom")
        return True, 12, "HTTP 200"

    monkeypatch.setattr(health, "run_check", flaky)
    await health.health.run_due(force=True)
    with db_session() as db:
        rows = {check.target: (check.last_ok, check.last_error) for check in db.scalars(select(HealthCheck))}
    assert rows["http://one.example.com"] == (False, "Check failed: RuntimeError")
    assert rows["http://two.example.com"] == (True, "")


def test_health_event_carries_fresh_uptime_bars(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every check result pushes the tile's bars, so they move without a page reload."""
    from app.services import health

    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(health.hub, "publish", lambda topic, event, payload: published.append((event, payload)))
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    widget = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.app", "link": "http://svc.example.com"}, headers=CSRF).json()["widget"]
    check = client.put(f"/api/v1/widgets/{widget['id']}/health", json={"kind": "http", "target": "http://svc.example.com"}, headers=CSRF).json()
    health.health._record(check["id"], True, 12, "HTTP 200")
    health.health._record(check["id"], False, 0, "ConnectError")
    events = [payload for event, payload in published if event == "health"]
    assert len(events) == 2
    bars = events[-1]["bars"]
    assert isinstance(bars, list) and len(bars) == 48
    assert bars[-1] == 0.5, "the current slice averages one success and one failure"
    assert all(bar is None for bar in bars[:-1])


def test_http_checks_share_one_client_per_tls_mode() -> None:
    """Building a TLS context per check cost a second on Windows and showed up as latency."""
    from app.services import health

    assert health.http_client(False) is health.http_client(False)
    assert health.http_client(True) is health.http_client(True)
    assert health.http_client(False) is not health.http_client(True)


def test_uptime_bars_windows_and_live_row(client: TestClient) -> None:
    """The same three checks, seen through every window an app tile offers."""
    import time

    from app.db import db_session
    from app.services import health, history

    setup_admin(client)
    now = int(time.time())
    with db_session() as db:
        for offset, value in ((30, 1.0), (20, 0.0), (10, 1.0)):
            history.record(db, 4242, {"up": value}, ts=now - offset)
        db.commit()
        live = health.uptime_bars(db, 4242, "live")
        hour = health.uptime_bars(db, 4242, "1h")
        day = health.uptime_bars(db, 4242, "24h")
        six = health.uptime_bars(db, 4242, "6h")
        empty = health.uptime_bars(db, 4243, "live")
    assert len(live) == 48 and live[-3:] == [1.0, 0.0, 1.0] and live[:-3] == [None] * 45
    assert len(hour) == 60 and hour[-1] == 0.67 and hour[-2] is None
    assert len(day) == 48 and day[-1] == 0.67
    assert len(six) == 48 and six[-1] == 0.67
    assert empty == [None] * 48
    assert health.bars_window({"bars": "live"}) == "live"
    assert health.bars_window({"bars": "nonsense"}) == "24h" and health.bars_window(None) == "24h"


def test_a_check_without_target_takes_the_shape_the_probe_needs() -> None:
    from types import SimpleNamespace

    from app.services.health import service_target

    widget = SimpleNamespace(integration=SimpleNamespace(kind="sonarr", config={"url": "https://sonarr.example.com/", "api_key": "k"}))
    assert service_target("http", widget) == "https://sonarr.example.com"
    assert service_target("tcp", widget) == "sonarr.example.com:443", "tcp wants host:port; https means 443 unless the address says otherwise"
    assert service_target("ping", widget) == "sonarr.example.com"
    widget.integration.config = {"url": "http://10.0.0.5:8989", "api_key": "k"}
    assert service_target("tcp", widget) == "10.0.0.5:8989"
    assert service_target("http", SimpleNamespace(integration=None)) == "" and service_target("http", None) == ""


async def test_a_check_without_target_probes_the_integration_address_of_the_moment(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import health

    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    integration = client.post("/api/v1/integrations", json={"kind": "sonarr", "name": "Sonarr", "config": {"url": "http://sonarr:8989", "api_key": "k"}}, headers=CSRF).json()
    tile = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.app", "integration_id": integration["id"]}, headers=CSRF).json()["widget"]
    client.put(f"/api/v1/widgets/{tile['id']}/health", json={"kind": "tcp", "target": ""}, headers=CSRF)
    probed: list[str] = []

    async def capture(check: HealthCheck) -> tuple[bool, int, str]:
        probed.append(check.target)
        return True, 3, "open"

    monkeypatch.setattr(health, "run_check", capture)
    await health.health.run_due(force=True)
    client.patch(f"/api/v1/integrations/{integration['id']}", json={"config": {"url": "https://10.0.0.5", "api_key": "k"}}, headers=CSRF)
    await health.health.run_due(force=True)
    assert probed == ["sonarr:8989", "10.0.0.5:443"], "the probe reads the integration's address every time, shaped as host:port for tcp"


async def test_the_collector_says_goodbye_to_its_sessions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A server that stops without logging out leaves a session behind at every restart; Reolink counts them."""
    from app.adapters import get_adapter
    from app.services.collector import collector

    setup_admin(client)
    integration = client.post("/api/v1/integrations", json={"kind": "reolink", "name": "Cams", "config": {"url": "http://cam", "username": "nexdeck", "password": "pw"}}, headers=CSRF).json()
    collector._caches[integration["id"]] = {"reolink_token": ("T1", 9e12)}
    goodbyes: list[tuple[int | None, object]] = []

    async def remember(self: object, config: dict, ctx: object) -> None:
        goodbyes.append((getattr(ctx, "integration_id", None), getattr(ctx, "cache", {}).get("reolink_token")))

    monkeypatch.setattr(type(get_adapter("reolink")), "close", remember)
    await collector.stop()
    assert goodbyes == [(integration["id"], ("T1", 9e12))]
