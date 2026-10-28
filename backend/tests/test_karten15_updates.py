"""KARTEN-15: updates and recalls of what was installed from the shop (AC-1 to AC-7, EC-1 to EC-7)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import CardRecord, Event, Notice, User
from app.services.collector import collector
from app.workshop import catalog, rounds, updates

from .conftest import CSRF, create_user, login
from .karten8_sample import DOWNLOADS, button, with_buttons
from .karten14_sample import AUTHOR, GitHub

SLUG = "downloads"
ENTRY = f"/api/v1/workshop/entries/{AUTHOR}/{SLUG}"
UPDATES = "/api/v1/workshop/updates"
REMOVED = {"level": "not_useful", "reason": "It shows nothing a card does not show better.", "at": "2026-10-21T10:00:00Z"}

#: The pretend GitHub, the clock of the shop and the signed-in administrator with the shop on.
pytest_plugins = ["tests.karten14_sample"]


def text(version: str = "1.0.0", *buttons: dict[str, Any], **more: Any) -> str:
    return with_buttons(*buttons, text=DOWNLOADS, version=version, **more)


def install(client: TestClient, github: GitHub, version: str = "1.0.0", *buttons: dict[str, Any]) -> None:
    github.publish(text(version, *buttons))
    made = client.post(f"{ENTRY}/install", json={"accept_risk": True}, headers=CSRF)
    assert made.status_code == 201, made.text


def publish(github: GitHub, clock: list[float], version: str, *buttons: dict[str, Any], **more: Any) -> None:
    """A new version in the repository, and the time to look at the catalog again."""
    github.publish(text(version, *buttons, **more.pop("data", {})), **more)
    clock[0] += 700


def look(client: TestClient) -> dict[str, Any]:
    """Open the shop (which fetches the catalog when it is old enough), then ask what is to be told."""
    assert client.get("/api/v1/workshop/catalog").status_code == 200
    return client.get(UPDATES).json()


def accept(client: TestClient, **body: Any):  # noqa: ANN202
    return client.post(f"/api/v1/workshop/updates/{SLUG}/accept", json=body, headers=CSRF)


def card() -> CardRecord:
    with db_session() as db:
        row = db.scalar(select(CardRecord).where(CardRecord.slug == SLUG))
        db.expunge_all()
        return row


def place(client: TestClient, kind: str = "jsonapi") -> int:
    made = client.post("/api/v1/integrations", json={"kind": kind, "name": "Torrents", "config": {"url": "http://svc.example.com:8080", "token": "t"}}, headers=CSRF)
    assert made.status_code == 201, made.text
    page = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()["pages"][0]["id"]
    widget = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "custom.list", "integration_id": made.json()["id"], "options": {"card": SLUG}}, headers=CSRF)
    assert widget.status_code in (200, 201), widget.text
    return int(widget.json()["widget"]["id"])


def test_karten15_ac1_a_newer_version_in_the_catalog_is_an_update_available(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    assert look(shop)["updates"] == []
    publish(github, clock, "1.1.0")
    told = look(shop)
    assert told["enabled"] is True and told["catalog_known"] is True
    assert told["updates"] == [{
        "slug": SLUG, "type": "card", "ref": f"{AUTHOR}/{SLUG}", "name": "Name of downloads", "installed_version": "1.0.0",
        "new_version": "1.1.0", "needs_newer": False, "min_nexdeck": None, "locally_changed": False,
    }]
    entry = shop.get("/api/v1/workshop/catalog").json()["entries"][0]
    assert entry["installed"] == {"slug": SLUG, "version": "1.0.0", "update": True, "locally_changed": False}
    listed = shop.get("/api/v1/cards").json()["cards"][0]
    assert listed["shop"] == {"ref": f"{AUTHOR}/{SLUG}", "update": True, "removed": None}


def test_karten15_ac1_the_hints_are_read_from_what_is_known_and_ask_nobody(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    look(shop)
    before = len(github.requests)
    for _ in range(3):
        assert len(shop.get(UPDATES).json()["updates"]) == 1
    shop.get("/api/v1/cards")
    assert len(github.requests) == before


def test_karten15_an_older_version_in_the_catalog_is_no_update(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github, "1.2.0")
    publish(github, clock, "1.1.0")
    assert look(shop)["updates"] == []


def test_karten15_ac2_the_update_shows_the_list_of_changes_and_what_the_card_may_do_now(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github, "1.0.0", button(id="pause", path="/api/pause"))
    publish(github, clock, "1.1.0", button(id="pause", path="/api/pause2"), button(id="wipe", path="/api/wipe"))
    look(shop)
    found = shop.get(f"/api/v1/workshop/updates/{SLUG}")
    assert found.status_code == 200, found.text
    body = found.json()
    assert (body["installed_version"], body["new_version"]) == ("1.0.0", "1.1.0")
    assert body["changelog"] == "Changes of 1.1.0."
    assert [one["id"] for one in body["permissions"]["buttons"]["added"]] == ["wipe"]
    assert [(one["before"]["path"], one["after"]["path"]) for one in body["permissions"]["buttons"]["changed"]] == [("/api/pause", "/api/pause2")]
    assert body["buttons_to_confirm"] == ["wipe", "pause"]
    assert body["permissions"]["requests"] == {"added": [], "changed": [], "removed": []}
    assert body["connection_changed"] is False
    assert body["locally_changed"] is False


def test_karten15_ac2_new_and_changed_requests_and_kinds_are_listed(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    changed = text("1.1.0", requires=["jsonapi", "sonarr"], requests=[{"id": "torrents", "path": "/api/v3/torrents"}, {"id": "more", "path": "/api/more"}])
    github.publish(changed)
    clock[0] += 700
    look(shop)
    permissions = shop.get(f"/api/v1/workshop/updates/{SLUG}").json()["permissions"]
    assert permissions["requires"] == {"added": ["sonarr"], "removed": []}
    assert permissions["requests"]["changed"] == [{"id": "torrents", "before": "/api/v2/torrents/info", "after": "/api/v3/torrents"}]
    assert permissions["requests"]["added"] == [{"id": "more", "path": "/api/more"}]


def test_karten15_ac3_new_or_changed_buttons_have_to_be_confirmed_one_by_one(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github, "1.0.0", button(id="pause", path="/api/pause"))
    publish(github, clock, "1.1.0", button(id="pause", path="/api/pause2"), button(id="wipe", path="/api/wipe"))
    look(shop)
    refused = accept(shop)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "buttons_not_confirmed"
    assert refused.json()["detail"]["missing"] == ["wipe", "pause"]
    half = accept(shop, confirmed_buttons=["wipe"])
    assert half.status_code == 409
    assert half.json()["detail"]["missing"] == ["pause"]
    assert card().shop_version == "1.0.0"
    assert accept(shop, confirmed_buttons=["wipe", "pause"]).status_code == 200
    assert card().shop_version == "1.1.0"


def test_karten15_ac3_a_button_whose_label_only_changed_needs_no_confirmation(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github, "1.0.0", button(id="pause", label="Pause"))
    publish(github, clock, "1.1.0", button(id="pause", label="Pause it"))
    look(shop)
    assert shop.get(f"/api/v1/workshop/updates/{SLUG}").json()["buttons_to_confirm"] == []
    assert accept(shop).status_code == 200


def test_karten15_ac4_accepting_changes_the_card_everywhere_at_once_and_writes_it_down(
    shop: TestClient, github: GitHub, clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    install(shop, github)
    widget = place(shop)
    scheduled: list[int] = []
    monkeypatch.setattr(collector, "schedule", lambda number, *a, **k: scheduled.append(number))
    publish(github, clock, "1.1.0")
    look(shop)
    done = accept(shop, expected_version="1.1.0")
    assert done.status_code == 200, done.text
    assert done.json() == {"status": "updated", "slug": SLUG, "version": "1.1.0", "copy_slug": None}
    row = card()
    assert row.shop_version == "1.1.0"
    assert 'version: 1.1.0' in row.yaml_source or "version: '1.1.0'" in row.yaml_source
    assert row.definition["version"] == "1.1.0"
    # The card on the board fetches again, and the update is no longer waiting.
    assert widget in scheduled
    assert shop.get(UPDATES).json()["updates"] == []
    # The card is the shop's again, not "changed here": the text it was installed with is the new one.
    assert shop.get("/api/v1/workshop/catalog").json()["entries"][0]["installed"]["locally_changed"] is False
    with db_session() as db:
        lines = [one.detail for one in db.scalars(select(Event)) if one.name == SLUG]
    assert "updated from the Card shop to 1.1.0" in lines


def test_karten15_ac5_later_leaves_the_hint_until_a_newer_version_comes(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    look(shop)
    # Looking at the update and closing the dialog changes nothing.
    shop.get(f"/api/v1/workshop/updates/{SLUG}")
    assert look(shop)["updates"][0]["new_version"] == "1.1.0"
    assert card().shop_version == "1.0.0"
    publish(github, clock, "1.2.0")
    assert look(shop)["updates"][0]["new_version"] == "1.2.0"


def test_karten15_ac5_a_version_that_was_replaced_meanwhile_has_to_be_looked_at_again(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    look(shop)
    publish(github, clock, "1.2.0")
    look(shop)
    refused = accept(shop, expected_version="1.1.0")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "update_changed"
    assert card().shop_version == "1.0.0"


def test_karten15_ec1_an_update_for_a_newer_nexdeck_cannot_be_accepted(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0", min_nexdeck="99.0.0")
    told = look(shop)["updates"][0]
    assert (told["needs_newer"], told["min_nexdeck"]) == (True, "99.0.0")
    refused = accept(shop)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "needs_newer_nexdeck"
    assert shop.get(f"/api/v1/workshop/updates/{SLUG}").json()["needs_newer"] is True
    assert card().shop_version == "1.0.0"


def test_karten15_the_new_file_has_to_match_the_checksum(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    github.files[f"entries/{AUTHOR}/{SLUG}/definition.yaml"] = text("1.1.0", button(id="evil", path="/api/evil")).encode()
    look(shop)
    refused = accept(shop)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "checksum_mismatch"
    assert shop.get(f"/api/v1/workshop/updates/{SLUG}").status_code == 409
    assert card().shop_version == "1.0.0"


def change_here(client: TestClient) -> None:
    current = client.get(f"/api/v1/cards/{SLUG}").json()
    mine = current["yaml"].replace("title: name", "title: hash")
    assert mine != current["yaml"]
    assert client.put(f"/api/v1/cards/{SLUG}", json={"yaml": mine}, headers=CSRF).status_code == 200


def test_karten15_ec2_a_card_changed_here_is_told_and_the_changes_are_kept_as_a_copy(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    widget = place(shop)
    change_here(shop)
    publish(github, clock, "1.1.0")
    told = look(shop)["updates"][0]
    assert told["locally_changed"] is True
    assert shop.get(f"/api/v1/workshop/updates/{SLUG}").json()["locally_changed"] is True
    done = accept(shop)
    assert done.status_code == 200, done.text
    assert done.json()["copy_slug"] == "downloads-mine"
    updated, copy = card(), None
    with db_session() as db:
        copy = db.scalar(select(CardRecord).where(CardRecord.slug == "downloads-mine"))
        db.expunge_all()
    assert "title: name" in updated.yaml_source
    assert updated.shop_version == "1.1.0"
    # EC-7: the copy is the changed card under another name, of this installation, and placed nowhere.
    assert copy is not None
    assert copy.definition["name"] == {"en": "Downloads (mine)", "de": "Downloads (mine)"}
    assert "title: hash" in copy.yaml_source
    assert (copy.origin, copy.shop_ref, copy.shop_version, copy.shop_hash) == ("local", "", "", "")
    boards = shop.get("/api/v1/cards").json()["cards"]
    assert {one["slug"]: [b["name"] for b in one["boards"]] for one in boards} == {SLUG: ["Wall"], "downloads-mine": []}
    assert widget  # the card on the board is the updated one


def test_karten15_ec7_the_copy_can_be_declined(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    change_here(shop)
    publish(github, clock, "1.1.0")
    look(shop)
    done = accept(shop, keep_mine=False)
    assert done.status_code == 200
    assert done.json()["copy_slug"] is None
    with db_session() as db:
        assert db.scalar(select(CardRecord).where(CardRecord.slug == "downloads-mine")) is None
    assert "title: name" in card().yaml_source


def test_karten15_ec7_a_card_that_was_not_changed_makes_no_copy(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    look(shop)
    assert accept(shop).json()["copy_slug"] is None


def test_karten15_ec7_a_text_with_a_name_in_one_language_gets_the_note_too(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    current = shop.get(f"/api/v1/cards/{SLUG}").json()["yaml"]
    changed = current.replace("name:\n  en: Downloads\n  de: Downloads\n", "name: Downloads   # my name\n").replace("title: name", "title: hash")
    assert "# my name" in changed
    assert shop.put(f"/api/v1/cards/{SLUG}", json={"yaml": changed}, headers=CSRF).status_code == 200
    publish(github, clock, "1.1.0")
    look(shop)
    assert accept(shop).json()["copy_slug"] == "downloads-mine"
    with db_session() as db:
        copy = db.scalar(select(CardRecord).where(CardRecord.slug == "downloads-mine"))
        assert copy.definition["name"] == "Downloads (mine)"
        assert "# my name" in copy.yaml_source


def test_karten15_ec5_a_second_administrator_finds_it_up_to_date_already(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    look(shop)
    create_user(shop, "second", role="admin")
    first = accept(shop, expected_version="1.1.0")
    login(shop, "second", "another-long-password")
    second = accept(shop, expected_version="1.1.0")
    assert (first.json()["status"], second.json()["status"]) == ("updated", "already_up_to_date")
    with db_session() as db:
        lines = [one.detail for one in db.scalars(select(Event)) if one.name == SLUG and "updated" in one.detail]
    assert lines == ["updated from the Card shop to 1.1.0"]


def test_karten15_ec5_the_card_is_looked_at_again_inside_the_lock(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    """Two administrators who both read the card as it was: the second finds it taken already, even though it came here after the check."""
    install(shop, github)
    github.publish(text("1.1.0"))
    found = catalog.Entry.model_validate(github.entries[0])
    with db_session() as first, db_session() as second:
        stale = updates.row_of(first, SLUG)
        late = updates.row_of(second, SLUG)
        assert stale.shop_version == late.shop_version == "1.0.0"
        done = updates.apply(second, late, found, text("1.1.0"), [], True, None, user_id=1)
        second.commit()
        again = updates.apply(first, stale, found, text("1.1.0"), [], True, None, user_id=1)
    assert (done["status"], again["status"]) == ("updated", "already_up_to_date")
    with db_session() as db:
        lines = [one.detail for one in db.scalars(select(Event)) if one.name == SLUG and "updated" in one.detail]
    assert lines == ["updated from the Card shop to 1.1.0"]


def test_karten15_ec6_an_update_that_changes_the_kind_of_connection_is_told_and_the_card_on_the_old_one_says_it_no_longer_fits(
    shop: TestClient, github: GitHub, clock: list[float]
) -> None:
    install(shop, github)
    widget = place(shop)
    publish(github, clock, "1.1.0", data={"requires": ["sonarr"]})
    look(shop)
    detail = shop.get(f"/api/v1/workshop/updates/{SLUG}").json()
    assert detail["connection_changed"] is True
    assert detail["permissions"]["requires"] == {"added": ["sonarr"], "removed": ["jsonapi"]}
    assert detail["placed_on"] == 1
    assert accept(shop).status_code == 200
    collector._caches.clear()
    shown = shop.post(f"/api/v1/widgets/{widget}/refresh", headers=CSRF)
    assert "kind_mismatch" in shown.text
    assert "no longer fits" in shown.text


def test_karten15_ac6_a_card_taken_out_of_the_shop_runs_on_and_says_why(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.0.0", removed=REMOVED)
    told = look(shop)
    assert told["updates"] == []
    assert told["removed"] == [{"slug": SLUG, "type": "card", "ref": f"{AUTHOR}/{SLUG}", "name": "Name of downloads", **REMOVED}]
    assert shop.get("/api/v1/cards").json()["cards"][0]["shop"]["removed"] == {"level": "not_useful", "reason": REMOVED["reason"], "at": REMOVED["at"]}
    assert card().shop_version == "1.0.0"
    assert shop.get("/api/v1/cards/downloads").status_code == 200
    # No bell for a reason that is not harmful.
    with db_session() as db:
        assert db.scalar(select(Notice).where(Notice.event == "card_recalled")) is None


def test_karten15_ac6_a_removed_entry_with_a_newer_version_is_no_update(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0", removed=REMOVED)
    told = look(shop)
    assert told["updates"] == [] and len(told["removed"]) == 1
    assert accept(shop).json()["detail"]["code"] == "entry_removed"


def test_karten15_ac7_harmful_rings_the_bell_of_every_administrator_once(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    create_user(shop, "second", role="admin")
    create_user(shop, "member", role="user")
    harmful = {"level": "harmful", "reason": "It sends your data to a stranger.", "at": "2026-10-22T10:00:00Z"}
    publish(github, clock, "1.0.0", removed=harmful)
    told = look(shop)
    assert told["removed"][0]["level"] == "harmful"
    look(shop)
    clock[0] += 700
    look(shop)
    with db_session() as db:
        notices = list(db.scalars(select(Notice).where(Notice.event == "card_recalled")))
        admins = set(db.scalars(select(User.id).where(User.role == "admin")))
    assert {one.user_id for one in notices} == admins and len(notices) == len(admins)
    assert {one.level for one in notices} == {"error"}
    assert "removed from the Card shop as harmful" in notices[0].title
    assert notices[0].body == harmful["reason"]
    assert notices[0].link == "/system/custom-cards"


def test_karten15_ac7_a_card_you_never_installed_rings_no_bell(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(text("1.0.0"), removed={"level": "harmful", "reason": "Bad.", "at": "2026-10-22T10:00:00Z"})
    look(shop)
    with db_session() as db:
        assert db.scalar(select(Notice).where(Notice.event == "card_recalled")) is None


def test_karten15_ec4_a_card_that_comes_back_loses_its_hint(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.0.0", removed=REMOVED)
    assert len(look(shop)["removed"]) == 1
    publish(github, clock, "1.0.0")
    assert look(shop)["removed"] == []
    assert shop.get("/api/v1/cards").json()["cards"][0]["shop"]["removed"] is None


def test_karten15_ec3_with_the_shop_off_there_are_no_hints_and_nobody_is_asked(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    look(shop)
    shop.put("/api/v1/workshop/settings", json={"enabled": False}, headers=CSRF)
    before = len(github.requests)
    assert shop.get(UPDATES).json() == {"enabled": False, "catalog_known": False, "updates": [], "removed": []}
    assert shop.get("/api/v1/cards").json()["cards"][0]["shop"] == {"ref": f"{AUTHOR}/{SLUG}", "update": False, "removed": None}
    assert shop.get(f"/api/v1/workshop/updates/{SLUG}").status_code == 409
    assert accept(shop).status_code == 409
    clock[0] += 3 * 24 * 3600
    import asyncio

    asyncio.run(rounds.once())
    assert len(github.requests) == before
    # The installed card runs on.
    assert shop.get("/api/v1/cards/downloads").status_code == 200


def test_karten14_ac12_once_a_day_the_collector_looks_at_the_catalog(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    import asyncio

    install(shop, github)
    harmful = {"level": "harmful", "reason": "Bad.", "at": "2026-10-22T10:00:00Z"}
    asyncio.run(rounds.once())
    first = github.count("catalog.json")
    asyncio.run(rounds.once())
    clock[0] += 3600
    asyncio.run(rounds.once())
    assert github.count("catalog.json") == first, "a catalog younger than a day is not fetched again"
    github.publish(text("1.0.0"), removed=harmful)
    clock[0] += 24 * 3600
    asyncio.run(rounds.once())
    assert github.count("catalog.json") == first + 1
    with db_session() as db:
        assert db.scalar(select(Notice).where(Notice.event == "card_recalled")) is not None
    assert shop.get(UPDATES).json()["removed"][0]["level"] == "harmful"


def test_karten15_a_card_that_did_not_come_from_the_shop_has_no_update(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(text("2.0.0"))
    shop.post("/api/v1/cards", json={"yaml": text("1.0.0")}, headers=CSRF)
    assert look(shop)["updates"] == []
    assert accept(shop).status_code == 404
    assert accept(shop).json()["detail"]["code"] == "not_installed_from_shop"


def test_karten15_a_user_cannot_look_at_or_take_an_update(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    install(shop, github)
    publish(github, clock, "1.1.0")
    look(shop)
    create_user(shop, "member")
    login(shop, "member", "another-long-password")
    assert shop.get(UPDATES).status_code == 403
    assert shop.get(f"/api/v1/workshop/updates/{SLUG}").status_code == 403
    assert accept(shop).status_code == 403
