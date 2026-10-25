"""Putting a custom card on a board, and what the collector does with it (KARTEN-2 AC-9, AC-10, AC-13, EC-2, EC-9; KARTEN-6 AC-10)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.cards import store
from app.db import db_session
from app.services import history
from app.services.collector import collector
from app.services.state import live

from .cards_sample import DEMO_LINE, VALUE_CARD, changed
from .conftest import CSRF, setup_admin

BASE = "http://svc.example.com:8080"


def save_card(text: str = VALUE_CARD) -> None:
    with db_session() as db:
        store.create(db, text)


def connection(client: TestClient, kind: str = "sonarr", **config: Any) -> int:
    body = {"kind": kind, "name": f"My {kind}", "config": {"url": BASE, "api_key": "key-1", **config}}
    made = client.post("/api/v1/integrations", json=body, headers=CSRF)
    assert made.status_code == 201, made.text
    return int(made.json()["id"])


def page_of(client: TestClient) -> int:
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    return int(board["pages"][0]["id"])


def place(client: TestClient, page: int, integration: int | None, kind: str = "custom.value", card: str | None = "queue-size", **more: Any):  # noqa: ANN202
    body: dict[str, Any] = {"kind": kind, "integration_id": integration, "options": {"card": card} if card else {}, **more}
    return client.post(f"/api/v1/pages/{page}/widgets", json=body, headers=CSRF)


@pytest.fixture
def stand(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, int]:
    """An administrator, a board page, the sample card saved. The collector's own loops stand still, as in the other race-free tests."""
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    save_card()
    return client, page_of(client)


def test_karten2_ac10_a_card_goes_on_a_connection_of_a_kind_it_names(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    answer = place(client, page, connection(client, "sonarr"))
    assert answer.status_code == 201, answer.text
    assert answer.json()["widget"]["options"]["card"] == "queue-size"
    assert answer.json()["widget"]["title"] == "Queue", "a custom card is called what its author called it"
    assert place(client, page, connection(client, "radarr")).status_code == 201


def test_karten2_ac10_a_connection_of_another_kind_is_refused(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    answer = place(client, page, connection(client, "lidarr"))
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "kind_mismatch"


def test_karten2_ac10_a_kind_a_card_cannot_read_through_is_refused_whatever_the_card_names(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    with db_session() as db:
        store.create(db, changed("slug: queue-size", "slug: log-in").replace("requires: [sonarr, radarr]", "requires: [qbittorrent]"))
    answer = place(client, page, connection(client, "qbittorrent", username="u", password="p"), card="log-in")
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "no_raw_access"


def test_karten2_ac10_a_card_is_changed_onto_another_connection_under_the_same_rule(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    widget = place(client, page, connection(client, "sonarr")).json()["widget"]["id"]
    wrong = client.patch(f"/api/v1/widgets/{widget}", json={"integration_id": connection(client, "lidarr")}, headers=CSRF)
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "kind_mismatch"
    right = client.patch(f"/api/v1/widgets/{widget}", json={"integration_id": connection(client, "radarr")}, headers=CSRF)
    assert right.status_code == 200


def test_karten2_ac10_the_preview_of_the_settings_sheet_is_held_to_it_too(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    widget = place(client, page, connection(client, "sonarr")).json()["widget"]["id"]
    answer = client.post(f"/api/v1/widgets/{widget}/preview", json={"integration_id": connection(client, "lidarr"), "options": {"card": "queue-size"}}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "kind_mismatch"


def test_karten2_ac10_a_card_nobody_saved_and_a_card_of_another_form_are_refused(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    sonarr = connection(client, "sonarr")
    assert place(client, page, sonarr, card="nothing-here").json()["detail"]["code"] == "unknown_card"
    assert place(client, page, sonarr, card=None).json()["detail"]["code"] == "unknown_card"
    assert place(client, page, sonarr, kind="custom.list").json()["detail"]["code"] == "form_mismatch"


def test_karten2_ac9_a_custom_card_is_not_refreshed_more_often_than_every_ten_seconds(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    sonarr = connection(client, "sonarr")
    answer = place(client, page, sonarr, refresh_seconds=5)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "too_fast"
    assert place(client, page, sonarr, refresh_seconds=10).status_code == 201
    widget = place(client, page, sonarr).json()["widget"]["id"]
    assert client.patch(f"/api/v1/widgets/{widget}", json={"refresh_seconds": 9}, headers=CSRF).json()["detail"]["code"] == "too_fast"
    assert client.patch(f"/api/v1/widgets/{widget}", json={"refresh_seconds": 15}, headers=CSRF).status_code == 200


@respx.mock
async def test_karten2_ac9_a_stored_pace_below_ten_seconds_is_still_held_to_ten(stand: tuple[TestClient, int]) -> None:
    from app.models import Widget

    client, page = stand
    widget = place(client, page, connection(client, "sonarr")).json()["widget"]["id"]
    with db_session() as db:
        stored = db.get(Widget, widget)
        stored.refresh_seconds = 5
        db.commit()
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 4}))
    assert await collector.refresh(widget) == 10


def test_karten2_a_card_with_a_definition_that_moved_on_can_still_be_renamed(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    widget = place(client, page, connection(client, "sonarr")).json()["widget"]["id"]
    with db_session() as db:
        row = store.get(db, "queue-size")
        assert row is not None
        from app.models import CardRecord

        record = db.get(CardRecord, row.id)
        store.update(db, record, changed("requires: [sonarr, radarr]", "requires: [radarr]"))
    assert client.patch(f"/api/v1/widgets/{widget}", json={"title": "Queue"}, headers=CSRF).status_code == 200


def test_karten6_ac10_a_card_is_made_at_the_size_its_definition_names_and_never_below_the_floor(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    sized = changed("requires: [sonarr, radarr]", "requires: [sonarr]\nsize: {w: 4, h: 3}\nmin_size: {w: 3, h: 3}").replace("slug: queue-size", "slug: sized")
    with db_session() as db:
        store.create(db, sized)
        store.create(db, changed("slug: queue-size", "slug: tiny").replace("requires: [sonarr, radarr]", "requires: [sonarr]\nmin_size: {w: 1, h: 1}"))
    sonarr = connection(client, "sonarr")
    big = place(client, page, sonarr, card="sized").json()["widget"]
    assert (big["default_size"][1], big["min_size"][1]) == (3, 3)
    assert big["default_size"][0] > big["min_size"][0] >= 3
    # The definition asks for one cell; the form's floor (a number is at least 1 by 1) and nothing smaller is kept.
    small = place(client, page, sonarr, card="tiny").json()["widget"]
    assert small["min_size"][0] >= 1 and small["min_size"][1] >= 1


def test_karten6_ac10_a_definition_cannot_ask_for_less_than_the_floor_of_a_list(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    from app.adapters.base import RENDERER_MIN

    text = LIST_CARD.replace("size: {w: 1, h: 1}", "min_size: {w: 1, h: 1}")
    with db_session() as db:
        store.create(db, text)
    made = place(client, page, connection(client, "sonarr"), kind="custom.list", card="a-list").json()["widget"]
    assert tuple(made["min_size"][1:]) >= RENDERER_MIN["list"][1:]
    assert made["min_size"][1] >= RENDERER_MIN["list"][1]


LIST_CARD = """\
nexdeck-card: 1
slug: a-list
name: A list
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: list
rows:
  select: records
item:
  title: title
size: {w: 1, h: 1}
"""


# -- EC-2, AC-11, AC-13, EC-9: through the collector --------------------------------------


async def refreshed(client: TestClient, widget: int):  # noqa: ANN202
    await collector.refresh(widget)
    return live.get(widget)


@respx.mock
async def test_karten2_ec2_a_card_whose_connection_was_deleted_says_so(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    sonarr = connection(client, "sonarr")
    widget = place(client, page, sonarr).json()["widget"]["id"]
    assert client.delete(f"/api/v1/integrations/{sonarr}", headers=CSRF).status_code in (200, 204)
    data = await refreshed(client, widget)
    assert data is not None and data.meta["code"] == "no_integration" and data.error


@respx.mock
async def test_karten2_ac11_a_refused_key_turns_the_card_red_with_the_message_of_any_card(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    widget = place(client, page, connection(client, "sonarr")).json()["widget"]["id"]
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(401))
    data = await refreshed(client, widget)
    assert data is not None and data.meta["code"] == "auth_failed" and data.error and data.status == "unknown"


@respx.mock
async def test_karten2_ac11_a_card_keeps_its_last_numbers_when_the_service_stops_answering(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    widget = place(client, page, connection(client, "sonarr")).json()["widget"]["id"]
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 4}))
    assert (await refreshed(client, widget)).primary["value"] == 4
    respx.get(f"{BASE}/api/v3/queue").mock(side_effect=httpx.ConnectError("down"))
    collector._caches.clear()
    data = await refreshed(client, widget)
    assert data.error and data.meta["code"] == "unreachable" and data.primary["value"] == 4 and "stale_since" in data.meta


@respx.mock
async def test_karten2_ac13_in_demo_mode_the_card_shows_its_example_answers_and_asks_nothing(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    sonarr = connection(client, "sonarr")
    widget = place(client, page, sonarr).json()["widget"]["id"]
    route = respx.route().mock(return_value=httpx.Response(200, json={"totalRecords": 99}))
    from app.services.collector import set_demo_flag

    set_demo_flag(True)
    try:
        data = await refreshed(client, widget)
    finally:
        set_demo_flag(False)
    assert data is not None and data.primary["value"] == 4 and data.meta["custom"] is True
    assert not route.called


@respx.mock
async def test_karten1_ac11_a_card_without_example_answers_says_so_in_demo_mode(stand: tuple[TestClient, int]) -> None:
    client, page = stand
    with db_session() as db:
        store.create(db, changed(DEMO_LINE, "").replace("slug: queue-size", "slug: no-demo"))
    widget = place(client, page, connection(client, "sonarr"), card="no-demo").json()["widget"]["id"]
    from app.services.collector import set_demo_flag

    set_demo_flag(True)
    try:
        data = await refreshed(client, widget)
    finally:
        set_demo_flag(False)
    assert data is not None and data.meta["code"] == "no_demo_data" and "demo" in (data.error or "")


@respx.mock
async def test_karten2_ec9_after_a_restart_a_custom_card_is_where_a_built_in_card_is(stand: tuple[TestClient, int]) -> None:
    """Nothing is kept in memory across a restart for any card; what was recorded is still there, and the first fetch fills the card again."""
    client, page = stand
    widget = place(client, page, connection(client, "sonarr")).json()["widget"]["id"]
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 4}))
    await refreshed(client, widget)
    with db_session() as db:
        assert history.series(db, widget, "value", 3600)
    live.clear()
    assert live.get(widget) is None
    assert client.get("/api/v1/boards").status_code == 200
    collector._caches.clear()
    assert (await refreshed(client, widget)).primary["value"] == 4
