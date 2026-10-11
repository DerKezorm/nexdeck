"""The problems card says what is wrong on a card, and leads to it.

Issue #35: a row read "Jellyfin findings: 0 error finding(s), 1 warning(s)".
That there was a warning, not which one, and the row went nowhere. Now it
names the first red and yellow rows of the card, says how many more there
are, and carries the link the card itself would open.
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import Context, WidgetData
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, setup_admin


def _page(client: TestClient) -> int:
    response = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()["pages"][0]["id"]


def _widget(client: TestClient, page_id: int, kind: str = "core.clock", **extra: object) -> dict:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    widget = response.json()["widget"]
    # Off the collector, so nothing it fetches writes over the state set here.
    collector.unschedule(widget["id"])
    return widget


async def _rows(problems: dict) -> list[dict]:
    ctx = Context(httpx.AsyncClient(), widget_id=problems["id"], cache={})
    return (await get_adapter("core").fetch("problems", {}, {}, ctx)).items


async def test_a_row_names_the_first_red_and_yellow_findings_and_how_many_more(client: TestClient) -> None:
    setup_admin(client)
    page_id = _page(client)
    jellyfin = _widget(client, page_id, title="Jellyfin")
    problems = _widget(client, page_id, kind="core.problems", title="Problems")
    live.set(jellyfin["id"], WidgetData(status="bad", items=[
        {"title": "Jellyfin", "subtitle": "Update available", "status": "unknown"},
        {"title": "Jellyfin", "subtitle": "A restart is pending", "status": "warn"},
        {"title": "Sign-in", "subtitle": "6 failed sign-ins in 24 h", "status": "warn"},
        {"title": "Intro Skipper", "subtitle": "Plugin malfunctioned", "status": "bad"},
        {"title": "Activity log", "subtitle": "2 error(s) in 24 h", "status": "warn", "worded": True},
    ], meta={"status_reason": "1 error finding(s), 3 warning(s)"}))

    [row] = await _rows(problems)
    # Red first, then yellow in the card's own order; the grey row is no problem.
    assert row["findings"] == [
        {"title": "Intro Skipper", "subtitle": "Plugin malfunctioned", "worded": False},
        {"title": "Jellyfin", "subtitle": "A restart is pending", "worded": False},
    ]
    assert row["more"] == 2
    assert row["subtitle"] == "Intro Skipper: Plugin malfunctioned · Jellyfin: A restart is pending · +2 more"
    assert row["status"] == "bad"


async def test_no_more_when_everything_fits_and_the_reason_when_rows_say_nothing(client: TestClient) -> None:
    setup_admin(client)
    page_id = _page(client)
    one = _widget(client, page_id, title="Jellyfin")
    silent = _widget(client, page_id, title="UniFi Network")
    problems = _widget(client, page_id, kind="core.problems", title="Problems")
    live.set(one["id"], WidgetData(status="warn", items=[
        {"title": "Jellyfin", "subtitle": "A restart is pending", "status": "warn"},
    ], meta={"status_reason": "0 error finding(s), 1 warning(s)"}))
    # A card that says it only by its reason, with rows that carry no status.
    live.set(silent["id"], WidgetData(status="warn", items=[{"title": "Switch", "subtitle": "online"}],
                                      meta={"status_reason": "3 device(s) offline", "urgent": ["Gateway"]}))

    rows = {row["title"]: row for row in await _rows(problems)}
    assert rows["Jellyfin"]["subtitle"] == "Jellyfin: A restart is pending"
    assert rows["Jellyfin"]["more"] == 0
    assert rows["UniFi Network"]["subtitle"] == "3 device(s) offline · Gateway"
    assert "findings" not in rows["UniFi Network"]


async def test_a_row_leads_where_its_card_leads(client: TestClient) -> None:
    setup_admin(client)
    page_id = _page(client)
    integration = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "k"}}, headers=CSRF).json()
    own = _widget(client, page_id, kind="radarr.queue", integration_id=integration["id"], title="Own", link="http://own.example.com/")
    service = _widget(client, page_id, kind="radarr.queue", integration_id=integration["id"], title="Service")
    reported = _widget(client, page_id, kind="radarr.queue", integration_id=integration["id"], title="Reported")
    nowhere = _widget(client, page_id, title="Nowhere")
    problems = _widget(client, page_id, kind="core.problems", title="Problems")
    for widget in (own, service, nowhere):
        live.set(widget["id"], WidgetData(status="warn", meta={"status_reason": "Something"}))
    live.set(reported["id"], WidgetData(status="bad", error="The service could not be reached.", link="http://live.example.com/", meta={"code": "unreachable"}))

    rows = {row["title"]: row for row in await _rows(problems)}
    assert rows["Own"]["url"] == "http://own.example.com/"
    assert rows["Reported"]["url"] == "http://live.example.com/"
    assert rows["Service"]["url"] == "http://radarr:7878"
    assert "url" not in rows["Nowhere"]
