"""Long history and forecasts (roadmap M4, 25.10.2026).

Hours for 90 days and days for two years, folded once each from the finer
rows; a long chart that reads them with the part not folded yet; and the
forecasts: when a volume is full, when a number reaches its red, whether a
backup gets slower, told once under 14 days.
"""

from __future__ import annotations

import math
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.backrest import BackrestAdapter
from app.adapters.base import WidgetData
from app.adapters.duplicati import _span
from app.adapters.kopia import KopiaAdapter
from app.db import db_session
from app.models import Event, HistoryDay, HistoryHour, HistoryMinute, Notice, Setting
from app.services import forecast, history
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, create_user, login, setup_admin

DAY = 86400


def _minutes(widget_id: int, metric: str, start: int, values: list[float], count: int = 2) -> None:
    with db_session() as db:
        for index, value in enumerate(values):
            db.add(HistoryMinute(key=history.key_for(widget_id, metric), ts=start + index * 60, avg=value, min=value - 1, max=value + 1, count=count))


def _hours(widget_id: int, metric: str, values: list[tuple[int, float]]) -> None:
    with db_session() as db:
        for ts, value in values:
            db.add(HistoryHour(key=history.key_for(widget_id, metric), ts=ts - ts % 3600, avg=value, min=value, max=value, count=60))


def _rows(table: type) -> list:
    with db_session() as db:
        return list(db.scalars(select(table).order_by(table.ts)))


# -- folding ----------------------------------------------------------------------------


def test_an_hour_is_folded_once_from_its_minutes_weighted_by_their_count(client: TestClient) -> None:
    now = int(time.time())
    hour = now - now % 3600 - 3 * 3600
    _minutes(1, "cpu", hour, [10.0] * 30 + [40.0] * 30)
    with db_session() as db:
        history.condense(db, now=now)
    folded = [row for row in _rows(HistoryHour) if row.ts == hour]
    assert len(folded) == 1
    assert (folded[0].avg, folded[0].min, folded[0].max, folded[0].count) == (25.0, 9.0, 41.0, 120)
    with db_session() as db:
        history.condense(db, now=now + 60)
        assert db.get(Setting, history.FOLDED).value["hour"] == now - 3600 - (now - 3600) % 3600
    assert [row.count for row in _rows(HistoryHour) if row.ts == hour] == [120], "folded again, it would count twice"


def test_an_hour_waits_until_its_raw_samples_are_minutes(client: TestClient) -> None:
    now = int(time.time())
    current = now - now % 3600
    _minutes(1, "cpu", current, [5.0] * 3)
    with db_session() as db:
        history.condense(db, now=now)
    assert all(row.ts < current for row in _rows(HistoryHour))


def test_a_day_is_folded_at_the_houses_midnight_once_its_hours_are_there(client: TestClient) -> None:
    now = int(time.time())
    midnight = history.local_midnight(now)
    yesterday = history.local_midnight(midnight - 3600)
    _hours(2, "used", [(yesterday + hour * 3600, 50.0 + hour) for hour in range(24)])
    _hours(2, "used", [(midnight + 3600, 99.0)])
    with db_session() as db:
        history.condense(db, now=now)
    days = [row for row in _rows(HistoryDay) if row.key == "2:used"]
    assert [(row.ts, row.min, row.max) for row in days] == [(yesterday, 50.0, 73.0)], "today is not over yet"
    assert datetime.fromtimestamp(days[0].ts).astimezone().hour == 0


def test_old_hours_and_days_go(client: TestClient) -> None:
    now = int(time.time())
    _hours(3, "x", [(now - 91 * DAY, 1.0), (now - 89 * DAY, 2.0)])
    with db_session() as db:
        db.add(HistoryDay(key="3:x", ts=now - 731 * DAY, avg=1, min=1, max=1, count=1))
        db.add(HistoryDay(key="3:x", ts=now - 729 * DAY, avg=1, min=1, max=1, count=1))
    with db_session() as db:
        history.condense(db, now=now)
    assert [row.avg for row in _rows(HistoryHour) if row.key == "3:x"] == [2.0]
    days = [row.ts for row in _rows(HistoryDay) if row.key == "3:x"]
    assert min(days) > now - 730 * DAY and now - 729 * DAY in days, "the day of two years ago went, the younger stayed"


def test_forgetting_a_card_takes_its_long_history_along(client: TestClient) -> None:
    _hours(4, "x", [(int(time.time()) - DAY, 1.0)])
    with db_session() as db:
        db.add(HistoryDay(key="4:x", ts=0, avg=1, min=1, max=1, count=1))
        history.forget_widget(db, 4)
    assert [row for row in _rows(HistoryHour) if row.key == "4:x"] == []
    assert [row for row in _rows(HistoryDay) if row.key == "4:x"] == []


# -- reading it back ----------------------------------------------------------------------


def test_a_long_series_reads_the_hours_and_the_part_not_folded_yet(client: TestClient) -> None:
    now = int(time.time())
    _hours(5, "x", [(now - 5 * 3600, 10.0), (now - 4 * 3600, 20.0)])
    last = now - now % 3600 - 3 * 3600
    _minutes(5, "x", last, [30.0, 34.0], count=1)
    found = history.series_long(db_session_get(), 5, "x", 7)
    assert [round(avg) for _ts, avg, _lo, _hi in found] == [10, 20, 32]
    assert found[-1][2:] == (29.0, 35.0)


def db_session_get():  # noqa: ANN201 - a session that stays open for one read
    from app.db import session_factory

    return session_factory()()


def test_a_year_reads_days_and_folds_the_rest_by_day(client: TestClient) -> None:
    now = int(time.time())
    midnight = history.local_midnight(now)
    with db_session() as db:
        db.add(HistoryDay(key="6:x", ts=history.local_midnight(midnight - 10 * DAY + 7200), avg=40, min=35, max=45, count=1440))
    _hours(6, "x", [(midnight + 3600, 50.0), (midnight + 7200, 60.0)])
    found = history.series_long(db_session_get(), 6, "x", 365)
    assert [(round(avg), low, high) for _ts, avg, low, high in found] == [(40, 35, 45), (55, 50.0, 60.0)]


def test_a_long_series_is_paired_down_keeping_the_extremes() -> None:
    rows = [(index, float(index), float(index) - 0.5, float(index) + 0.5) for index in range(900)]
    paired = history._paired(rows, 400)
    assert len(paired) <= 400
    assert paired[0][2] == -0.5 and paired[-1][3] == 899.5, "the lowest and the highest survive"


def test_the_long_history_route_keeps_to_who_may_see_the_board(client: TestClient) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    card = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.clock"}, headers=CSRF).json()["widget"]
    collector.unschedule(card["id"])
    _hours(card["id"], "used", [(int(time.time()) - 7200, 42.0)])
    answer = client.get(f"/api/v1/widgets/{card['id']}/history/long?days=30&metric=used")
    assert answer.status_code == 200 and answer.json()["used"][0][1] == 42.0
    create_user(client, "member")
    login(client, "member", "another-long-password")
    assert client.get(f"/api/v1/widgets/{card['id']}/history/long?days=30&metric=used").status_code in (403, 404)


# -- what a card's rows add -----------------------------------------------------------------


def test_the_rows_of_a_volume_card_and_of_a_backup_card_are_kept_and_others_are_not() -> None:
    volumes = WidgetData(items=[{"title": "Volume 1", "progress": 82.4}, {"title": "Volume 2", "progress": 40}])
    assert history.extras("synology.volumes", volumes) == {"fill:Volume 1": 82.4, "fill:Volume 2": 40.0}
    assert history.extras("radarr.queue", WidgetData(items=[{"title": "A film", "progress": 50}])) == {}
    plans = WidgetData(items=[{"title": "photos", "duration": 3480.0}, {"title": "never", "duration": 0}])
    assert history.extras("backrest.plans", plans) == {"duration:photos": 3480.0}
    assert history.extras("synology.volumes", WidgetData(error="down", items=volumes.items)) == {}


def test_the_backup_tools_say_how_long_the_last_good_run_took() -> None:
    recent = {"flowId": ["4", "1"], "timestampMs": ["1789164247490", "1789164243828"], "durationMs": ["1392000", "1411"],
              "status": ["STATUS_SUCCESS", "STATUS_SUCCESS"], "bytesAdded": ["0", "0"]}
    data = BackrestAdapter._plans([{"id": "photos", "recentBackups": recent}], {}, 10)
    assert data.items[0]["duration"] == 1392.0
    failed_first = {**recent, "status": ["STATUS_ERROR", "STATUS_SUCCESS"]}
    assert BackrestAdapter._plans([{"id": "p", "recentBackups": failed_first}], {}, 10).items[0]["duration"] == 1.411
    rows = KopiaAdapter._rows([{"source": {"host": "nas", "userName": "root", "path": "/photos"}, "status": "IDLE",
                                   "lastSnapshot": {"startTime": "2026-10-25T01:00:00.123456789Z", "endTime": "2026-10-25T01:58:00.123456789Z",
                                                    "stats": {"errorCount": 0}}}], [])
    assert round(rows[0]["row"]["duration"]) == 3480
    assert _span("00:58:00.1234567") == 3480 and _span("1.02:03:04") == 93784 and _span("nonsense") == 0


# -- forecasts ----------------------------------------------------------------------------------


def _rising(widget_id: int, metric: str, start: float, per_day: float, days: int = 20) -> None:
    now = int(time.time())
    _hours(widget_id, metric, [(now - hour * 3600, start + per_day * (days * 24 - hour) / 24) for hour in range(days * 24, 0, -1)])


def _card(client: TestClient, kind: str = "core.clock", **options: object) -> dict:
    """A card of any kind with the options written straight in: the forecasts read them, the card's form is not under test."""
    from app.models import Widget

    if client.get("/api/v1/auth/me").status_code != 200:
        setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": f"Lab {time.monotonic_ns()}"}, headers=CSRF).json()
    made = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.clock"}, headers=CSRF)
    assert made.status_code == 201, made.text
    card = made.json()["widget"]
    collector.unschedule(card["id"])
    with db_session() as db:
        widget = db.get(Widget, card["id"])
        widget.kind = kind
        widget.options = dict(options)
    return card


def _work_out(card_id: int, data: WidgetData) -> dict | None:
    from app.models import Widget

    live.set(card_id, data)
    with db_session() as db:
        return forecast.work_out(db, db.get(Widget, card_id), data)


def test_a_volume_filling_by_half_a_percent_a_day_is_full_in_about_twenty_days(client: TestClient) -> None:
    card = _card(client, "synology.volumes")
    _rising(card["id"], "fill:Volume 1", 80.0, 0.5)
    found = _work_out(card["id"], WidgetData(items=[{"title": "Volume 1", "progress": 90.0}]))
    assert found is not None and found["kind"] == "full" and found["row"] == "Volume 1"
    assert 19 <= found["days"] <= 21


def test_a_line_that_fits_badly_or_is_too_short_says_nothing(client: TestClient) -> None:
    card = _card(client, level_bad=90)
    now = int(time.time())
    # A slow rise in the mean under a day-and-night swing forty either way: the line would say 30 days, and it is a guess.
    _hours(card["id"], "headline", [(now - hour * 3600, 60.0 - hour / 24 + 40 * math.sin(hour / 24 * math.tau)) for hour in range(480, 0, -1)])
    assert _work_out(card["id"], WidgetData(primary={"label": "CPU", "value": 50.0})) is None, "noise is no trend"
    short = _card(client, level_bad=90)
    _rising(short["id"], "headline", 50.0, 5.0, days=2)
    assert _work_out(short["id"], WidgetData(primary={"label": "CPU", "value": 60.0})) is None, "two days are a guess"


def test_a_number_reaches_its_red_line_and_low_is_bad_counts_downward(client: TestClient) -> None:
    card = _card(client, level_warn=70, level_bad=90)
    _rising(card["id"], "headline", 60.0, 1.0)
    found = _work_out(card["id"], WidgetData(primary={"label": "CPU", "value": 80.0}))
    assert found is not None and found["kind"] == "level" and found["line"] == "bad" and 9 <= found["days"] <= 11
    free = _card(client, level_warn=20, level_bad=10)
    _rising(free["id"], "headline", 60.0, -2.0)
    down = _work_out(free["id"], WidgetData(primary={"label": "Free", "value": 20.0}))
    assert down is not None and 4 <= down["days"] <= 6, "a free share at 20, falling 2 a day towards red at 10"
    past = _card(client, level_bad=50)
    _rising(past["id"], "headline", 25.0, 1.0)
    assert _work_out(past["id"], WidgetData(primary={"label": "CPU", "value": 55.0})) is None, "red right now needs no forecast, whatever the hours said"


def test_half_a_year_away_is_not_shown(client: TestClient) -> None:
    card = _card(client, level_bad=1000)
    _rising(card["id"], "headline", 10.0, 0.1)
    assert _work_out(card["id"], WidgetData(primary={"label": "x", "value": 12.0})) is None


def test_a_backup_that_takes_two_minutes_longer_each_week_is_slower(client: TestClient) -> None:
    card = _card(client, "backrest.plans")
    now = int(time.time())
    with db_session() as db:
        for day in range(40):
            ts = history.local_midnight(now - (40 - day) * DAY)
            value = 2520 + day * 120 / 7
            db.add(HistoryDay(key=history.key_for(card["id"], "duration:photos"), ts=ts, avg=value, min=value, max=value, count=24))
    found = _work_out(card["id"], WidgetData(items=[{"title": "photos", "duration": 3480}]))
    assert found is not None and found["kind"] == "slower" and 110 <= found["per_week"] <= 130


def test_under_two_weeks_is_told_once_and_again_only_after_it_rose(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    card = _card(client, level_bad=90)
    _rising(card["id"], "headline", 60.0, 1.0)
    live.set(card["id"], WidgetData(primary={"label": "CPU", "value": 80.0}))
    forecast.forget()
    assert forecast.round_once() >= 1
    assert forecast.of(card["id"])["told"] is True
    forecast.round_once()
    with db_session() as db:
        notices = [row.title for row in db.scalars(select(Notice).where(Notice.event == "forecast"))]
        lines = list(db.scalars(select(Event).where(Event.kind == "forecast")))
    assert len(notices) == 1 and "reaches red in about" in notices[0]
    assert len(lines) == 1 and lines[0].before == "bad"

    # Slower now: more than three weeks away, the next fall under two weeks is told again.
    def ahead(days: float):  # noqa: ANN202 - stands in for work_out, for this card only
        return lambda db, widget, data: ({"kind": "level", "metric": "headline", "row": None, "line": "bad", "days": days,
                                          "at": 0, "limit": 90.0, "slope": 1.0, "now": 80.0} if widget.id == card["id"] else None)

    monkeypatch.setattr(forecast, "work_out", ahead(30.0))
    forecast.round_once()
    monkeypatch.setattr(forecast, "work_out", ahead(5.0))
    forecast.round_once()
    with db_session() as db:
        assert len(list(db.scalars(select(Notice).where(Notice.event == "forecast")))) == 2


def test_a_demo_card_shows_its_forecast_and_tells_nobody(client: TestClient) -> None:
    setup_admin(client)
    integration = client.post("/api/v1/integrations", json={"kind": "glances", "name": "Box", "config": {}, "demo": True}, headers=CSRF).json()
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    card = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
                       json={"kind": "glances.disks", "integration_id": integration["id"]}, headers=CSRF).json()["widget"]
    collector.unschedule(card["id"])
    _rising(card["id"], "fill:/", 70.0, 1.0)
    live.set(card["id"], WidgetData(items=[{"title": "/", "progress": 90.0}]))
    forecast.round_once()
    assert forecast.of(card["id"])["kind"] == "full"
    with db_session() as db:
        assert list(db.scalars(select(Notice).where(Notice.event == "forecast"))) == []


def test_the_big_number_is_found_among_the_metrics_when_the_card_does_not_name_it(client: TestClient) -> None:
    card = _card(client, level_bad=40)
    _rising(card["id"], "cpu", 10.0, 0.5)
    found = _work_out(card["id"], WidgetData(primary={"label": "CPU", "value": 20.0}, metrics={"cpu": 20.0, "memory": 35.0}))
    assert found is not None and found["metric"] == "cpu" and 38 <= found["days"] <= 42
    twice = _card(client, level_bad=40)
    _rising(twice["id"], "cpu", 10.0, 0.5)
    assert _work_out(twice["id"], WidgetData(primary={"label": "CPU", "value": 20.0}, metrics={"cpu": 20.0, "load": 20.0})) is None, "two with that value: no guess"
