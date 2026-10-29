"""Nachlauf of the first real run: what the server tells and refuses after the Card shop was used (W3, N2, N3, N5, N6, N7)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.cards import demo
from app.db import db_session
from app.models import Widget
from app.services.collector import collector

from .cards_sample import VALUE_CARD, changed
from .conftest import CSRF, setup_admin
from .karten3_sample import MEMOS
from .karten14_sample import card_text
from .karten16_sample import Hub
from .test_cards_placing import connection, page_of, place
from .test_karten16_submit import (
    BASE,
    ME,
    SLUG,
    accepted,
    add_card,
    check,
    codes,
    install_from_another,
    share,
    sign_in,
)

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]


@pytest.fixture
def github(hub: Hub) -> Hub:
    return hub


@pytest.fixture
def me(shop: TestClient, hub: Hub, moment: list[float]) -> TestClient:
    """An administrator with the shop on, signed in to GitHub as 'someone' (4242), and a card of his own."""
    sign_in(shop, hub, moment, hub.person("someone", ME))
    add_card(shop)
    return shop


def shop_view(client: TestClient, slug: str) -> dict[str, Any]:
    return next(one for one in client.get("/api/v1/cards").json()["cards"] if one["slug"] == slug)["shop"]


# -- W3: nothing to share while it is as it came from the shop ------------------------------------------------------


def test_karten8n_w3_a_card_as_it_came_from_the_shop_says_so_and_is_not_shared(me: TestClient, hub: Hub, clock: list[float]) -> None:
    slug = install_from_another(me, hub, clock)
    assert shop_view(me, slug)["locally_changed"] is False
    assert "unchanged_from_shop" in codes(check(me, slug=slug))
    refused = share(me, slug=slug)
    assert refused.status_code == 400 and hub.issues == []
    assert "unchanged_from_shop" in [one["code"] for one in refused.json()["detail"]["problems"]]


def test_karten8n_w3_a_card_changed_after_it_came_is_shared_as_based_on_the_other(me: TestClient, hub: Hub, clock: list[float]) -> None:
    slug = install_from_another(me, hub, clock)
    me.put(f"/api/v1/cards/{slug}", json={"yaml": card_text(slug=slug) + "# mine\n", "overwrite": True}, headers=CSRF)
    assert shop_view(me, slug)["locally_changed"] is True
    found = check(me, slug=slug)
    assert "unchanged_from_shop" not in codes(found)
    assert found["based_on"] == "777/their-card" and found["mode"] == "new"


def test_karten8n_w3_an_own_entry_as_it_came_back_is_not_shared_but_changed_it_is_an_update(me: TestClient, hub: Hub, clock: list[float]) -> None:
    me.delete(f"/api/v1/cards/{SLUG}", headers=CSRF)
    hub.publish(card_text(), author=str(ME))
    clock[0] += 700
    assert me.post(f"{BASE}/entries/{ME}/{SLUG}/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    assert shop_view(me, SLUG)["locally_changed"] is False
    assert "unchanged_from_shop" in codes(check(me))
    newer = card_text(version="1.1.0") + "# next\n"
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": newer, "overwrite": True}, headers=CSRF)
    assert shop_view(me, SLUG)["locally_changed"] is True
    found = check(me)
    assert "unchanged_from_shop" not in codes(found) and found["mode"] == "update" and found["based_on"] is None


def test_karten8n_w3_a_card_of_your_own_has_no_shop_part(me: TestClient) -> None:
    mine = next(one for one in me.get("/api/v1/cards").json()["cards"] if one["slug"] == SLUG)
    assert mine["shop"] is None
    assert "unchanged_from_shop" not in codes(check(me))


def test_karten8n_w3_a_connection_from_the_shop_is_told_in_the_list_and_not_shared_until_changed(me: TestClient, hub: Hub) -> None:
    hub.publish(MEMOS, author="777")
    short = hub.entries[-1]["slug"]
    found = me.post(f"{BASE}/entries/777/{short}/install", json={"accept_risk": True}, headers=CSRF)
    assert found.status_code == 201, found.text
    row = next(one for one in me.get("/api/v1/own-integrations").json() if one["short"] == short)
    assert row["shop_ref"] == f"777/{short}" and row["locally_changed"] is False
    assert "unchanged_from_shop" in codes(check(me, type="integration", slug=short))
    assert share(me, type="integration", slug=short, category="other").status_code == 400
    me.put(f"/api/v1/own-integrations/{short}", json={"yaml": MEMOS + "# mine\n"}, headers=CSRF)
    row = next(one for one in me.get("/api/v1/own-integrations").json() if one["short"] == short)
    assert row["locally_changed"] is True
    again = check(me, type="integration", slug=short)
    assert "unchanged_from_shop" not in codes(again) and again["based_on"] == f"777/{short}"


def test_karten8n_w3_a_connection_of_your_own_is_not_called_changed(me: TestClient) -> None:
    made = me.post("/api/v1/own-integrations", json={"yaml": MEMOS}, headers=CSRF)
    row = next(one for one in me.get("/api/v1/own-integrations").json() if one["short"] == made.json()["short"])
    assert row["shop_ref"] == "" and row["locally_changed"] is False


# -- N5: an update starts from the words of the entry it updates ----------------------------------------------------


def test_karten8n_n5_an_update_starts_from_the_description_and_category_of_the_shop_entry(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    hub.accept(1, VALUE_CARD, description="Counts the items of the queue for the living room.", category="downloads")
    clock[0] += 700
    found = check(me)
    assert found["mode"] == "update"
    assert found["suggested"] == {"description": "Counts the items of the queue for the living room.", "category": "downloads"}


def test_karten8n_n5_without_the_entry_in_the_catalog_the_accepted_issue_tells_the_words(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me, category="smart_home", description="The words that went into the issue, a few of them.")
    accepted(hub, clock, 1)
    me.put(f"{BASE}/settings", json={"enabled": False}, headers=CSRF)
    found = check(me)
    assert found["mode"] == "update" and found["previous_version"] is None
    assert found["suggested"] == {"description": "The words that went into the issue, a few of them.", "category": "smart_home"}


def test_karten8n_n5_a_new_submission_starts_from_the_card(me: TestClient) -> None:
    found = check(me)
    assert found["mode"] == "new"
    assert found["suggested"] == {"description": "How many items wait in the queue.", "category": "media"}


# -- N6: a description is a few words of English --------------------------------------------------------------------


@pytest.mark.parametrize(
    "words",
    ["Testkarte", "Eine Karte fuer das Wohnzimmer hier", "Shows the queue", "Queue sizes displayed here now", "x" * 30, "  \n "],
)
def test_karten8n_n6_a_description_that_is_not_a_few_words_of_english_is_refused(me: TestClient, hub: Hub, words: str) -> None:
    refused = share(me, description=words)
    assert refused.status_code == 400 and hub.issues == []
    problems = refused.json()["detail"]["problems"]
    assert [one["message"] for one in problems if one["code"] == "description"] == ["Add a description of a few sentences, in English."]


@pytest.mark.parametrize("words", ["Shows how many items wait", "How many items are waiting in the download queue?", "A tile for the queue of your server"])
def test_karten8n_n6_a_description_of_a_few_english_words_is_taken(me: TestClient, hub: Hub, words: str) -> None:
    assert share(me, description=words).status_code == 200


def test_karten8n_n6_the_list_of_changes_of_an_update_needs_three_characters(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1)
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": changed('version: "1.0.0"', 'version: "1.1.0"'), "overwrite": True}, headers=CSRF)
    short = share(me, changes=" a ")
    assert short.status_code == 400 and "changes" in [one["code"] for one in short.json()["detail"]["problems"]]
    assert share(me, changes="Fix").status_code == 200


# -- N2: a new version of an entry shows its new pictures -----------------------------------------------------------

IMAGE = f"{BASE}/entries/{ME}/{SLUG}/image"


def test_karten8n_n2_the_entry_tells_the_version_of_its_pictures(me: TestClient, hub: Hub) -> None:
    hub.publish(card_text(version="1.2.0"), author=str(ME))
    hub.publish(MEMOS, author="777", version="", updated_at="2026-10-21T10:00:00Z")
    short = hub.entries[-1]["slug"]
    listed = {one["slug"]: one for one in me.get(f"{BASE}/catalog").json()["entries"]}
    assert listed[SLUG]["picture_version"] == "1.2.0"
    assert listed[short]["picture_version"] == "2026-10-21T10:00:00Z", "an entry without a version goes by the time it was updated"
    assert me.get(f"{BASE}/entries/{ME}/{SLUG}").json()["picture_version"] == "1.2.0"


def test_karten8n_n2_an_entry_with_neither_version_nor_time_goes_by_its_checksum(me: TestClient, hub: Hub) -> None:
    found = hub.publish(MEMOS, author="777", version="", updated_at="")
    listed = next(one for one in me.get(f"{BASE}/catalog").json()["entries"] if one["slug"] == found["slug"])
    assert listed["picture_version"] == found["sha256"]


def test_karten8n_n2_a_picture_is_kept_by_its_version_and_a_new_version_is_fetched(me: TestClient, hub: Hub, clock: list[float]) -> None:
    hub.publish(card_text(version="1.0.0"), author=str(ME))
    hub.files[f"entries/{ME}/{SLUG}/preview-light.png"] = b"\x89PNG\r\n\x1a\nold"
    assert me.get(f"{IMAGE}/light?v=1.0.0").content.endswith(b"old")
    assert me.get(f"{IMAGE}/light?v=1.0.0").content.endswith(b"old")
    assert hub.count("preview-light.png") == 1
    hub.publish(card_text(version="1.1.0"), author=str(ME))
    hub.files[f"entries/{ME}/{SLUG}/preview-light.png"] = b"\x89PNG\r\n\x1a\nnew"
    clock[0] += 700
    assert me.get(f"{IMAGE}/light?v=1.1.0").content.endswith(b"new"), "the same minute, the same server, a new address"
    assert hub.count("preview-light.png") == 2
    # The server keeps the picture of the version the catalog names (security review of stage 8, hint b): an old address gets the picture
    # there is now, and asks GitHub nothing.
    assert me.get(f"{IMAGE}/light?v=1.0.0").content.endswith(b"new"), "the server keeps what the catalog names, whatever v says"
    assert hub.count("preview-light.png") == 2


def test_karten8n_n2_the_version_of_a_picture_has_at_most_64_characters(me: TestClient, hub: Hub) -> None:
    hub.publish(card_text(), author=str(ME))
    assert me.get(f"{IMAGE}/light?v={'a' * 64}").status_code == 200
    refused = me.get(f"{IMAGE}/light?v={'a' * 65}")
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_picture_version"
    assert me.get(f"{IMAGE}/light").status_code == 200, "without a version it works as before"


# -- N3: the tiles follow the name of the card ----------------------------------------------------------------------

NAME = "name: {en: Queue, de: Warteschlange}"


@pytest.fixture
def tiles(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The sample card on a board in four tiles: called what the card is (English and German) and one named by somebody."""
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    client.post("/api/v1/cards", json={"yaml": VALUE_CARD}, headers=CSRF)
    page = page_of(client)
    ids = {}
    for key, title in (("english", "Queue"), ("german", "Warteschlange"), ("own", "My queue"), ("empty", "")):
        made = place(client, page, connection(client, "sonarr"), title=title)
        assert made.status_code == 201, made.text
        ids[key] = made.json()["widget"]["id"]
        client.patch(f"/api/v1/widgets/{ids[key]}", json={"title": title}, headers=CSRF)
    return {"client": client, "ids": ids}


def titles(world: dict[str, Any]) -> dict[str, str]:
    found = {}
    for key, number in world["ids"].items():
        with db_session() as db:
            found[key] = db.get(Widget, number).title
    return found


def test_karten8n_n3_before_anything_changes_the_tiles_carry_the_name_they_were_given(tiles: dict[str, Any]) -> None:
    assert titles(tiles) == {"english": "Queue", "german": "Warteschlange", "own": "My queue", "empty": ""}


def test_karten8n_n3_saving_in_the_editor_renames_the_tiles_that_carry_the_old_name_in_their_language(tiles: dict[str, Any]) -> None:
    client: TestClient = tiles["client"]
    newer = changed(NAME, "name: {en: Backlog, de: Rueckstau}")
    assert client.put("/api/v1/cards/queue-size", json={"yaml": newer, "overwrite": True}, headers=CSRF).status_code == 200
    assert titles(tiles) == {"english": "Backlog", "german": "Rueckstau", "own": "My queue", "empty": ""}


def test_karten8n_n3_a_language_the_new_name_lacks_takes_the_english_one(tiles: dict[str, Any]) -> None:
    client: TestClient = tiles["client"]
    client.put("/api/v1/cards/queue-size", json={"yaml": changed(NAME, "name: Backlog"), "overwrite": True}, headers=CSRF)
    assert titles(tiles) == {"english": "Backlog", "german": "Backlog", "own": "My queue", "empty": ""}


def test_karten8n_n3_a_card_saved_with_the_same_name_changes_no_tile(tiles: dict[str, Any]) -> None:
    client: TestClient = tiles["client"]
    client.put("/api/v1/cards/queue-size", json={"yaml": VALUE_CARD + "# note\n", "overwrite": True}, headers=CSRF)
    assert titles(tiles) == {"english": "Queue", "german": "Warteschlange", "own": "My queue", "empty": ""}


def test_karten8n_n3_an_import_that_replaces_the_card_renames_its_tiles_too(tiles: dict[str, Any]) -> None:
    client: TestClient = tiles["client"]
    newer = changed(NAME, "name: {en: Backlog, de: Rueckstau}", changed('version: "1.0.0"', 'version: "2.0.0"'))
    done = client.post("/api/v1/cards/import", json={"text": newer, "choices": {"card:queue-size": "replace"}}, headers=CSRF)
    assert done.status_code == 201, done.text
    assert titles(tiles) == {"english": "Backlog", "german": "Rueckstau", "own": "My queue", "empty": ""}


def test_karten8n_n3_an_update_from_the_shop_renames_the_tiles_too(shop: TestClient, hub: Hub, clock: list[float]) -> None:
    hub.publish(card_text(version="1.0.0"), author=str(ME))
    assert shop.post(f"{BASE}/entries/{ME}/{SLUG}/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    made = place(shop, page_of(shop), connection(shop, "sonarr"))
    assert made.status_code == 201, made.text
    number = made.json()["widget"]["id"]
    assert made.json()["widget"]["title"] == "Queue"
    hub.publish(changed(NAME, "name: {en: Backlog, de: Rueckstau}", card_text(version="1.1.0")), author=str(ME))
    clock[0] += 700
    assert shop.get(f"{BASE}/catalog").status_code == 200
    done = shop.post(f"{BASE}/updates/{SLUG}/accept", json={}, headers=CSRF)
    assert done.status_code == 200, done.text
    with db_session() as db:
        assert db.get(Widget, number).title == "Backlog"


# -- N7: the demo data move their dates ------------------------------------------------------------------------------

SHIFT = timedelta(days=100, minutes=15)


@pytest.mark.parametrize(
    ("moment", "moved"),
    [
        ("2026-10-01", "2026-06-23"),
        ("2026-10-01T12:30:00Z", "2026-06-23T12:15:00Z"),
        ("2026-10-01T12:30:00.250+02:00", "2026-06-23T12:15:00.250+02:00"),
        ("2026-10-01 00:10:05", "2026-06-22 23:55:05"),
        ("2026-10-01T12:30", "2026-06-23T12:15"),
        (" 2026-10-01 ", " 2026-06-23 "),
    ],
)
def test_karten8n_n7_a_date_or_time_stamp_moves_back_and_keeps_its_form(moment: str, moved: str) -> None:
    assert demo.disguise_text(moment, SHIFT) == moved


@pytest.mark.parametrize("text", ["12:30", "Mon, 02 Jan 2006 15:04:05 GMT", "2026-13-45", "2026-10-01T25:00:00Z", "0001-01-02", "on 2026-10-01 at noon"])
def test_karten8n_n7_what_is_no_iso_moment_is_not_moved_as_one(text: str) -> None:
    moved = demo.disguise_text(text, SHIFT)
    if text in ("12:30", "Mon, 02 Jan 2006 15:04:05 GMT", "2026-13-45", "2026-10-01T25:00:00Z", "0001-01-02"):
        assert moved == text
    else:
        assert moved != text and "2026-10-01" not in moved


def test_karten8n_n7_the_dates_of_the_demo_move_by_the_same_time_and_keep_their_order() -> None:
    answers = {"q": {"items": [{"createdAt": f"2026-10-0{n}T12:30:00Z", "day": f"2026-10-0{n}", "n": 7, "stamp": 1_761_998_400} for n in (1, 2, 3)]}}
    made, _cut = demo.disguise(answers, SHIFT)
    items = made["q"]["items"]
    assert [one["createdAt"] for one in items] == ["2026-06-23T12:15:00Z", "2026-06-24T12:15:00Z", "2026-06-25T12:15:00Z"]
    assert [one["day"] for one in items] == ["2026-06-23", "2026-06-24", "2026-06-25"]
    assert all(one["stamp"] == 1_761_998_400 for one in items), "a number of seconds stays as it is"


def test_karten8n_n7_each_demo_draws_a_shift_of_30_to_400_days() -> None:
    seen = set()
    for _ in range(40):
        made, _cut = demo.disguise({"q": {"day": "2026-10-01"}})
        days = (datetime(2026, 10, 1) - datetime.fromisoformat(made["q"]["day"])).days
        assert 30 <= days <= 400
        seen.add(days)
    assert len(seen) > 5, "drawn each time, not one fixed number"
    for _ in range(40):
        shift = demo.draw_shift()
        assert timedelta(days=30) <= shift <= timedelta(days=400, minutes=59)
