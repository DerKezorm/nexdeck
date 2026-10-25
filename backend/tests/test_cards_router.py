"""Managing and placing custom cards (KARTEN-11), and the two small addresses next to it (KARTEN-1 T1, KARTEN-2 AC-12)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
import respx
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cards import store
from app.db import db_session
from app.models import CardRecord
from app.services.collector import collector
from app.services.state import live

from .cards_sample import VALUE_CARD, changed
from .conftest import ADMIN, CSRF, create_user, login, setup_admin

BASE = "http://svc.example.com:8080"


def text_of(slug: str) -> str:
    return changed("slug: queue-size", f"slug: {slug}")


def connection(client: TestClient, kind: str = "sonarr", **more: Any) -> int:
    body = {"kind": kind, "name": f"My {kind}", "config": {"url": BASE, "api_key": "key-1"}, **more}
    made = client.post("/api/v1/integrations", json=body, headers=CSRF)
    assert made.status_code == 201, made.text
    return int(made.json()["id"])


def page_of(client: TestClient, name: str = "Wall") -> int:
    board = client.post("/api/v1/boards", json={"name": name}, headers=CSRF).json()
    return int(board["pages"][0]["id"])


def place(client: TestClient, page: int, integration: int | None, card: str = "queue-size", **more: Any):  # noqa: ANN202
    body = {"kind": "custom.value", "integration_id": integration, "options": {"card": card}, **more}
    return client.post(f"/api/v1/pages/{page}/widgets", json=body, headers=CSRF)


def add(client: TestClient, text: str = VALUE_CARD):  # noqa: ANN202
    return client.post("/api/v1/cards", json={"yaml": text}, headers=CSRF)


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    return client


def as_user(client: TestClient, name: str = "ann") -> None:
    """Signed in as an ordinary member; made on the first call, the same one afterwards."""
    if client.post("/api/v1/auth/login", json={"username": name, "password": "another-long-password"}).status_code != 200:
        create_user(client, name)
        login(client, name, "another-long-password")


def as_admin(client: TestClient) -> None:
    login(client, ADMIN["username"], ADMIN["password"])


# -- AC-1, AC-10: the list ------------------------------------------------------------


def test_karten11_ac1_the_list_says_name_form_source_origin_boards_and_release(admin: TestClient) -> None:
    assert add(admin).status_code == 201
    page = page_of(admin)
    assert place(admin, page, connection(admin)).status_code == 201
    listed = admin.get("/api/v1/cards").json()
    assert listed["limit"] == 200
    [card] = listed["cards"]
    assert card["slug"] == "queue-size" and card["name"] == {"en": "Queue", "de": "Warteschlange"} and card["form"] == "value"
    assert [one["kind"] for one in card["requires"]] == ["sonarr", "radarr"] and card["requires"][0]["label"] == "Sonarr"
    assert card["origin"] == "local" and card["version"] == "1.0.0" and card["users_may_place"] is False
    assert [one["name"] for one in card["boards"]] == ["Wall"], "where it stands: the boards, by name"


def test_karten11_ac1_a_card_is_read_with_its_text_and_replaced_by_a_new_one(admin: TestClient) -> None:
    add(admin)
    assert admin.get("/api/v1/cards/queue-size").json()["yaml"] == VALUE_CARD
    newer = changed("version: \"1.0.0\"", "version: \"1.1.0\"")
    answer = admin.put("/api/v1/cards/queue-size", json={"yaml": newer}, headers=CSRF)
    assert answer.status_code == 200 and answer.json()["version"] == "1.1.0"
    wrong = admin.put("/api/v1/cards/queue-size", json={"yaml": changed("form: value", "form: dial")}, headers=CSRF)
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "card_invalid" and wrong.json()["detail"]["problems"][0]["line"]
    assert admin.get("/api/v1/cards/queue-size").json()["version"] == "1.1.0", "a text with problems changes nothing"


def test_karten11_ac1_a_text_with_problems_is_refused_with_all_of_them(admin: TestClient) -> None:
    answer = add(admin, changed("form: value", "form: dial"))
    assert answer.status_code == 400 and answer.json()["detail"]["problems"]
    assert admin.get("/api/v1/cards").json()["cards"] == []


def test_karten11_ac1_a_short_name_the_addresses_use_is_not_a_card(admin: TestClient) -> None:
    answer = add(admin, text_of("library"))
    assert answer.status_code == 400 and answer.json()["detail"]["first"] == "card_slug_reserved"


def test_karten11_ac1_a_short_name_taken_is_refused(admin: TestClient) -> None:
    add(admin)
    answer = add(admin)
    assert answer.status_code == 400 and answer.json()["detail"]["first"] == "card_slug_taken"


# -- the two small addresses ------------------------------------------------------------


def test_karten2_ac12_the_kinds_a_card_can_read_through_are_listed_for_administrators(admin: TestClient) -> None:
    kinds = admin.get("/api/v1/cards/sources").json()
    by_kind = {one["kind"]: one for one in kinds}
    assert "sonarr" in by_kind and by_kind["sonarr"]["label"] == "Sonarr" and by_kind["sonarr"]["icon"]
    assert "qbittorrent" not in by_kind, "only kinds a card may read through"
    as_user(admin)
    assert admin.get("/api/v1/cards/sources").status_code == 403


def test_karten1_t1_the_schema_is_served_to_administrators(admin: TestClient) -> None:
    schema = admin.get("/api/v1/cards/schema").json()
    assert schema["title"] == "nexdeck card" and ("oneOf" in schema or "anyOf" in schema)
    as_user(admin)
    assert admin.get("/api/v1/cards/schema").status_code == 403


# -- AC-2, AC-3, AC-4, AC-12, EC-1: the library and who may place ----------------------------------


def test_karten11_ac3_users_never_see_a_card_that_is_not_released_and_cannot_place_it(admin: TestClient) -> None:
    add(admin)
    sonarr = connection(admin)
    as_user(admin)
    assert admin.get("/api/v1/cards/library").json() == {"cards": []}
    answer = place(admin, page_of(admin, "Mine"), sonarr)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "unknown_card"
    assert admin.get("/api/v1/cards").status_code == 403, "the management list stays with administrators"


def test_karten11_ac4_a_released_card_is_placed_by_anyone_who_may_edit_the_board(admin: TestClient) -> None:
    add(admin)
    sonarr = connection(admin)
    assert admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF).json()["users_may_place"] is True
    as_user(admin)
    [card] = admin.get("/api/v1/cards/library").json()["cards"]
    assert card["slug"] == "queue-size" and [one["id"] for one in card["fits"]] == [sonarr]
    assert place(admin, page_of(admin, "Mine"), sonarr).status_code == 201


def test_karten11_ac4_users_never_place_on_admin_only(admin: TestClient) -> None:
    add(admin)
    locked = connection(admin, admin_only=True)
    open_ = connection(admin, "radarr")
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    assert {one["id"] for one in admin.get("/api/v1/cards/library").json()["cards"][0]["fits"]} == {locked, open_}, "administrators see both"
    as_user(admin)
    assert [one["id"] for one in admin.get("/api/v1/cards/library").json()["cards"][0]["fits"]] == [open_]
    answer = place(admin, page_of(admin, "Mine"), locked)
    assert answer.status_code == 403 and answer.json()["detail"]["code"] == "integration_locked"


def test_karten11_ac2_the_library_offers_the_cards_with_the_connections_that_fit(admin: TestClient) -> None:
    add(admin)
    add(admin, changed("slug: queue-size", "slug: speed").replace("requires: [sonarr, radarr]", "requires: [prowlarr]"))
    sonarr = connection(admin)
    connection(admin, "lidarr")
    cards = {one["slug"]: one for one in admin.get("/api/v1/cards/library").json()["cards"]}
    assert [one["id"] for one in cards["queue-size"]["fits"]] == [sonarr]
    assert cards["queue-size"]["form"] == "value" and cards["queue-size"]["requires"][0]["label"] == "Sonarr"


def test_karten11_ac12_a_card_with_no_fitting_connection_is_listed_without_one(admin: TestClient) -> None:
    add(admin)
    connection(admin, "lidarr")
    [card] = admin.get("/api/v1/cards/library").json()["cards"]
    assert card["fits"] == [] and [one["kind"] for one in card["requires"]] == ["sonarr", "radarr"]


def test_karten11_ec1_taking_the_release_back_keeps_the_placed_cards_and_closes_new_ones(admin: TestClient) -> None:
    add(admin)
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    sonarr = connection(admin)
    as_user(admin)
    page = page_of(admin, "Mine")
    widget = place(admin, page, sonarr).json()["widget"]["id"]
    as_admin(admin)
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": False}, headers=CSRF)
    as_user(admin)
    assert admin.get("/api/v1/cards/library").json() == {"cards": []}
    assert place(admin, page, sonarr).status_code == 400, "a new one cannot be placed"
    changed_ = admin.patch(f"/api/v1/widgets/{widget}", json={"title": "Mine", "options": {"card": "queue-size", "card_colour": "blue"}}, headers=CSRF)
    assert changed_.status_code == 200, "the one that stands is still the user's to change"
    assert admin.get(f"/api/v1/widgets/{widget}/data").status_code == 200


def test_karten11_ec1_a_user_cannot_point_a_placed_card_at_a_card_not_released(admin: TestClient) -> None:
    add(admin)
    add(admin, text_of("other"))
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    sonarr = connection(admin)
    as_user(admin)
    widget = place(admin, page_of(admin, "Mine"), sonarr).json()["widget"]["id"]
    answer = admin.patch(f"/api/v1/widgets/{widget}", json={"options": {"card": "other"}}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "unknown_card"


# -- AC-5: copy ---------------------------------------------------------------------------


def test_karten11_ac5_a_copy_has_a_new_short_name_and_is_local_and_not_released(admin: TestClient) -> None:
    add(admin)
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    with db_session() as db:
        row = db.scalar(select(CardRecord))
        row.origin, row.shop_ref, row.shop_version = "shop", "queue-size", "2.0.0"
        db.commit()
    store.invalidate()
    first = admin.post("/api/v1/cards/queue-size/copy", headers=CSRF)
    assert first.status_code == 201 and first.json()["slug"] == "queue-size-copy"
    assert (first.json()["origin"], first.json()["shop_version"], first.json()["users_may_place"]) == ("local", "", False)
    assert admin.post("/api/v1/cards/queue-size/copy", headers=CSRF).json()["slug"] == "queue-size-copy-2"
    copy = admin.get("/api/v1/cards/queue-size-copy").json()
    assert copy["yaml"] == VALUE_CARD.replace("slug: queue-size", "slug: queue-size-copy"), "the text is the same, comments included"
    assert admin.get("/api/v1/cards/queue-size").json()["origin"] == "shop"


# -- AC-6: delete ----------------------------------------------------------------------------


@respx.mock
async def test_karten11_ac6_a_deleted_card_is_gone_at_once_and_comes_back_with_the_same_short_name(admin: TestClient) -> None:
    add(admin)
    page = page_of(admin)
    widget = place(admin, page, connection(admin)).json()["widget"]["id"]
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 4}))
    await collector.refresh(widget)
    assert live.get(widget).primary["value"] == 4
    answer = admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    assert answer.status_code == 200 and answer.json() == {"boards": 1}
    assert admin.get("/api/v1/cards/queue-size").status_code == 404 and admin.get("/api/v1/cards").json()["cards"] == []
    await collector.refresh(widget)
    assert live.get(widget).meta["code"] == "definition_missing"
    add(admin)
    await collector.refresh(widget)
    assert live.get(widget).primary["value"] == 4


# -- AC-7: the log -----------------------------------------------------------------------------


def test_karten11_ac7_creating_changing_releasing_copying_and_deleting_are_written_down(admin: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="nexdeck.cards"):
        add(admin)
        admin.put("/api/v1/cards/queue-size", json={"yaml": changed('version: "1.0.0"', 'version: "1.0.1"')}, headers=CSRF)
        admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
        admin.post("/api/v1/cards/queue-size/copy", headers=CSRF)
        admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    lines = [record.getMessage() for record in caplog.records if record.name == "nexdeck.cards"]
    assert len(lines) == 5 and all("admin" in line for line in lines)
    assert "created" in lines[0] and "changed" in lines[1] and "released" in lines[2] and "copied" in lines[3] and "deleted" in lines[4]


# -- AC-8: the limit ------------------------------------------------------------------------------


def fill(count: int) -> None:
    with db_session() as db:
        for number in range(count):
            db.add(CardRecord(slug=f"filler-{number}", kind="card", yaml_source="", definition={}))
        db.commit()


def test_karten11_ac8_the_two_hundred_and_first_card_is_refused_with_a_clear_message(admin: TestClient) -> None:
    fill(199)
    assert add(admin).status_code == 201
    answer = add(admin, text_of("one-too-many"))
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "too_many_cards" and "200" in answer.json()["detail"]["message"]
    assert admin.post("/api/v1/cards/queue-size/copy", headers=CSRF).status_code == 409, "a copy is a card as well"
    assert len(admin.get("/api/v1/cards").json()["cards"]) == 200


# -- AC-9: guests and strangers ---------------------------------------------------------------------


def test_karten11_ac9_a_guest_and_a_stranger_reach_none_of_it(admin: TestClient) -> None:
    add(admin)
    create_user(admin, "visitor", role="guest")
    calls = [
        ("get", "/api/v1/cards", None), ("post", "/api/v1/cards", {"yaml": VALUE_CARD}), ("get", "/api/v1/cards/queue-size", None),
        ("put", "/api/v1/cards/queue-size", {"yaml": VALUE_CARD}), ("delete", "/api/v1/cards/queue-size", None),
        ("post", "/api/v1/cards/queue-size/copy", None), ("put", "/api/v1/cards/queue-size/users", {"allowed": True}),
        ("get", "/api/v1/cards/sources", None), ("get", "/api/v1/cards/schema", None), ("get", "/api/v1/cards/library", None),
    ]
    admin.post("/api/v1/auth/logout", headers=CSRF)
    for method, path, body in calls:
        assert getattr(admin, method)(path, headers=CSRF, **({"json": body} if body is not None else {})).status_code == 401, (method, path)
    login(admin, "visitor", "another-long-password")
    for method, path, body in calls:
        assert getattr(admin, method)(path, headers=CSRF, **({"json": body} if body is not None else {})).status_code == 403, (method, path)
    as_admin(admin)
    assert len(admin.get("/api/v1/cards").json()["cards"]) == 1, "none of it changed anything"


def test_karten11_ac9_a_member_who_is_no_administrator_changes_nothing(admin: TestClient) -> None:
    add(admin)
    as_user(admin)
    for method, path, body in (
        ("post", "/api/v1/cards", {"yaml": text_of("mine")}), ("put", "/api/v1/cards/queue-size", {"yaml": VALUE_CARD}),
        ("delete", "/api/v1/cards/queue-size", None), ("post", "/api/v1/cards/queue-size/copy", None),
        ("put", "/api/v1/cards/queue-size/users", {"allowed": True}),
    ):
        assert getattr(admin, method)(path, headers=CSRF, **({"json": body} if body is not None else {})).status_code == 403, (method, path)


# -- EC-4, EC-6 -------------------------------------------------------------------------------------


@respx.mock
async def test_karten11_ec4_the_card_stays_and_runs_when_the_account_that_built_it_is_deleted(admin: TestClient) -> None:
    second = create_user(admin, "bob", role="admin")
    login(admin, "bob", "another-long-password")
    add(admin)
    page = page_of(admin)
    widget = place(admin, page, connection(admin)).json()["widget"]["id"]
    as_admin(admin)
    assert admin.delete(f"/api/v1/users/{second['id']}?boards=hand_over", headers=CSRF).status_code == 204
    with db_session() as db:
        assert db.scalar(select(CardRecord.created_by).where(CardRecord.slug == "queue-size")) is None
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 7}))
    await collector.refresh(widget)
    assert live.get(widget).primary["value"] == 7
    assert admin.get("/api/v1/cards").json()["cards"][0]["slug"] == "queue-size"


def test_karten11_ec6_saving_a_card_deleted_meanwhile_says_so_and_saving_as_new_works(admin: TestClient) -> None:
    add(admin)
    admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    answer = admin.put("/api/v1/cards/queue-size", json={"yaml": VALUE_CARD}, headers=CSRF)
    assert answer.status_code == 404 and answer.json()["detail"]["code"] == "card_deleted"
    assert add(admin).status_code == 201, "Save as new is the ordinary way to make a card"


# -- EC-1, AC-3 through a board's text ----------------------------------------------------------------


def board_text(client: TestClient, slug: str) -> dict:
    return yaml.safe_load(client.get(f"/api/v1/boards/{slug}/export?ids=true").text)


def test_karten11_ac3_a_card_that_is_not_released_does_not_come_in_through_a_board_file(admin: TestClient) -> None:
    add(admin)
    page = page_of(admin)
    place(admin, page, connection(admin))
    text = admin.get("/api/v1/boards/wall/export").text
    as_user(admin)
    answer = admin.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF)
    assert answer.status_code == 400 and "no card with that short name" in answer.json()["detail"]["message"]
    as_admin(admin)
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    as_user(admin)
    # The file names a connection that a user may not create: the card is not what stops it, so look at the reason.
    assert "no card with that short name" not in admin.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF).text


def test_karten11_ec1_a_board_edited_as_text_keeps_the_card_that_stands_and_takes_no_new_unreleased_one(admin: TestClient) -> None:
    add(admin)
    add(admin, text_of("other"))
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    sonarr = connection(admin)
    as_user(admin)
    board = admin.post("/api/v1/boards", json={"name": "Mine"}, headers=CSRF).json()
    place(admin, board["pages"][0]["id"], sonarr)
    as_admin(admin)
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": False}, headers=CSRF)
    as_user(admin)
    document = board_text(admin, board["slug"])
    card = document["pages"][0]["widgets"][0]
    card["title"] = "Renamed"
    saved = admin.put(f"/api/v1/boards/{board['slug']}/yaml", json={"yaml_text": yaml.safe_dump(document, sort_keys=False)}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    document["pages"][0]["widgets"].append({**card, "id": None, "options": {"card": "other"}})
    del document["pages"][0]["widgets"][-1]["id"]
    refused = admin.put(f"/api/v1/boards/{board['slug']}/yaml", json={"yaml_text": yaml.safe_dump(document, sort_keys=False)}, headers=CSRF)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_import"
