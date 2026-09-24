"""A card whose adapter declares no metric keeps its big number all the same,
so the value card can draw a line under it like under any other."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.base import WidgetData
from app.services import history

from .conftest import CSRF, setup_admin


def test_the_declared_metrics_win_over_the_headline() -> None:
    data = WidgetData(primary={"label": "Load", "value": 3}, metrics={"load": 0.4})
    assert history.recorded(data) == {"load": 0.4}


def test_a_numeric_headline_is_kept_without_a_declared_metric() -> None:
    assert history.recorded(WidgetData(primary={"label": "Films", "value": 1284})) == {history.HEADLINE: 1284.0}


def test_nothing_is_kept_that_would_draw_nonsense() -> None:
    assert history.recorded(None) == {}
    assert history.recorded(WidgetData(primary={"label": "Version", "value": "1.2.3"})) == {}
    assert history.recorded(WidgetData(primary={"label": "Up", "value": True})) == {}, "a yes/no is no number"
    assert history.recorded(WidgetData(primary={"label": "Films", "value": 1284}, error="The service did not answer.")) == {}, (
        "a failed fetch would draw a dip")
    assert history.recorded(WidgetData()) == {}


def test_the_board_history_lists_the_headline_of_a_card_that_declares_nothing(client: TestClient) -> None:
    setup_admin(client)
    connection = client.post("/api/v1/integrations", json={"kind": "plex", "name": "Plex", "demo": True, "config": {"url": "http://plex.example.com"}}, headers=CSRF).json()
    board = client.post("/api/v1/boards", json={"name": "Media"}, headers=CSRF).json()
    card = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
                       json={"kind": "plex.library", "integration_id": connection["id"]}, headers=CSRF).json()["widget"]
    assert client.post(f"/api/v1/widgets/{card['id']}/refresh", headers=CSRF).status_code == 200

    lines = client.get(f"/api/v1/boards/{board['slug']}/history").json()
    points = lines[str(card["id"])][history.HEADLINE]
    # ⚠️ Not exactly one point: making the card schedules a collection of its
    # own, and when that one is done before the history is read, the refresh
    # above writes a second point with the same number. Seen once in a full
    # run on 24.09.2026, under the load of another test run on the machine.
    assert points, "the collector wrote the number down, and the board offers it"
    assert {value for _ts, value in points} == {points[0][1]} and points[0][1] > 0
