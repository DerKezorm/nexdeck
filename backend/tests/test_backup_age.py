"""A backup that is too old turns its card yellow (roadmap M2): Backrest, Kopia and Duplicati."""

from __future__ import annotations

import time

from app.adapters import backup_age
from app.adapters.backrest import BackrestAdapter
from app.adapters.base import WidgetData
from app.adapters.duplicati import DuplicatiAdapter
from app.adapters.kopia import KopiaAdapter

HOUR = 3600.0


def test_the_limit_belongs_to_the_connection_and_defaults_to_26_hours() -> None:
    assert backup_age.limit_of({}) == 26 * HOUR
    assert backup_age.limit_of({"stale_hours": 200}) == 200 * HOUR
    assert backup_age.limit_of({"stale_hours": 0}) == 0
    assert backup_age.limit_of({"stale_hours": "nonsense"}) == 26 * HOUR
    for adapter in (BackrestAdapter, KopiaAdapter, DuplicatiAdapter):
        assert backup_age.STALE_FIELD in adapter.fields


def test_too_old_is_older_than_the_limit_and_never_for_a_backup_that_never_ran() -> None:
    now = 1_000_000.0
    assert backup_age.too_old(now - 27 * HOUR, 26 * HOUR, now)
    assert not backup_age.too_old(now - 25 * HOUR, 26 * HOUR, now)
    assert not backup_age.too_old(None, 26 * HOUR, now)
    assert not backup_age.too_old(now - 999 * HOUR, 0, now), "0 switches it off"


def _rows(*goods: float) -> list[dict]:
    return [{"state": "ok", "good": good, "row": {"title": f"job {index}", "subtitle": "", "status": "ok"}} for index, good in enumerate(goods)]


def test_kopia_and_duplicati_turn_yellow_and_say_why() -> None:
    now = time.time()
    for adapter, listing in ((KopiaAdapter, KopiaAdapter._sources), (DuplicatiAdapter, DuplicatiAdapter._backups)):
        rows = backup_age.age(_rows(now - HOUR, now - 30 * HOUR), 26 * HOUR, now)
        assert [one["state"] for one in rows] == ["ok", "warn"]
        assert rows[1]["row"]["subtitle"] == "Too old" and rows[1]["row"]["stale"] is True
        assert listing(rows, {}).status == "warn", adapter.kind
        assert adapter._summary(rows).status == "warn", adapter.kind
        fresh = backup_age.age(_rows(now - HOUR), 26 * HOUR, now)
        assert listing(fresh, {}).status == "ok" and adapter._summary(fresh).status == "ok"


def _plan(identifier: str, hours_ago: float, now: float) -> dict:
    return {"id": identifier, "recentBackups": {"timestampMs": [str(int((now - hours_ago * HOUR) * 1000))], "status": ["STATUS_SUCCESS"]}}


def test_backrest_turns_an_old_plan_yellow_on_both_cards() -> None:
    now = time.time()
    plans = [_plan("documents", 2, now), _plan("photos", 40, now)]
    listed = BackrestAdapter._plans(plans, {}, 10, now=now, stale=26 * HOUR)
    rows = {row["title"]: row for row in listed.items}
    assert listed.status == "warn"
    assert rows["photos"]["status"] == "warn" and rows["photos"]["subtitle"] == "Too old" and rows["photos"].get("stale")
    assert rows["documents"]["status"] == "ok"
    summary = BackrestAdapter._summary(plans, now=now, stale=26 * HOUR)
    assert summary.status == "warn" and summary.primary["value"] == 1
    assert BackrestAdapter._plans(plans, {}, 10, now=now).status == "ok", "without a limit nothing is too old"


def test_a_backup_that_became_too_old_is_told_once_and_not_on_the_first_fetch() -> None:
    old = WidgetData(items=[{"title": "photos", "status": "ok"}])
    stale = WidgetData(items=[{"title": "photos", "status": "warn", "stale": True, "value": "30 h"}])
    [news] = backup_age.news(old, stale)
    assert news.event == "backup_stale" and news.key == "backup_stale:photos"
    assert backup_age.news(stale, stale) == [], "still too old is no news"
    assert backup_age.news(None, stale) == [], "not on the first fetch"
    assert backup_age.news(old, WidgetData(error="unreachable")) == []
    assert KopiaAdapter().detect("sources", old, stale, {}) and not KopiaAdapter().detect("summary", old, stale, {})
