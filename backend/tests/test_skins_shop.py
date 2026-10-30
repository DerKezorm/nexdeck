"""Skins in the Card shop (skins, phase D): read from the catalog, installed, updated, recalled and shared.

The Workshop is the pretend GitHub of the shop's tests; nothing reaches the network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import Notice, Skin
from app.skins import store as skin_store
from app.workshop import catalog, kinds, submit

from .cards_sample import VALUE_CARD
from .conftest import CSRF
from .karten14_sample import AUTHOR, GitHub, entry
from .karten16_sample import Hub

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]

KEY = "pixel-desk"
ENTRY = f"/api/v1/workshop/entries/{AUTHOR}/{KEY}"
UPDATES = "/api/v1/workshop/updates"
CONSOLE = json.loads(skin_store.EXAMPLES_DIR.joinpath("console.json").read_text(encoding="utf-8"))


def skin_text(version: str = "1.0.0", key: str = KEY, **more: Any) -> str:
    # Laid out unlike nexdeck lays out a file: a skin whose name is free is kept as it came, not written anew.
    return json.dumps({**CONSOLE, "key": key, "name": "Pixel desk", "version": version, **more}, indent=4)


def row(key: str = KEY) -> Skin | None:
    with db_session() as db:
        found = db.scalar(select(Skin).where(Skin.key == key))
        db.expunge_all()
        return found


def install(client: TestClient) -> dict[str, Any]:
    made = client.post(f"{ENTRY}/install", json={"accept_risk": True}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()  # type: ignore[no-any-return]


def look(client: TestClient, clock: list[float]) -> dict[str, Any]:
    clock[0] += 700
    assert client.get("/api/v1/workshop/catalog").status_code == 200
    return client.get(UPDATES).json()  # type: ignore[no-any-return]


# -- the kinds ---------------------------------------------------------------------------------------------------------


def test_the_form_names_each_kind_by_its_word_and_nothing_else() -> None:
    assert [kinds.from_form(word) for word in ("Card", "connection", " Skin ", "Connective", "Skins", "")] == ["card", "integration", "skin", None, None, None]


def test_the_catalog_has_skins_and_a_skin_without_a_version_is_left_out(shop: TestClient, github: GitHub) -> None:
    github.publish(skin_text())
    github.entries.append({**entry(skin_text(key="no-version")), "version": ""})
    found = shop.get("/api/v1/workshop/catalog").json()
    listed = {one["slug"]: one for one in found["entries"]}
    assert listed[KEY]["type"] == "skin" and listed[KEY]["fits"] is True and "no-version" not in listed


# -- installing --------------------------------------------------------------------------------------------------------


def test_a_skin_is_installed_under_its_own_name_then_the_next_free_one_and_marked_as_from_the_shop(shop: TestClient, github: GitHub) -> None:
    github.publish(skin_text())
    seen = shop.post(f"{ENTRY}/install/check", headers=CSRF).json()
    assert seen["ok"] is True and seen["skin_key"] == KEY and seen["documents"] == [] and seen["entry"]["verified"] is True
    made = install(shop)
    assert made["skin"] == KEY and made["place_url"] == "/system/skins"
    stored = row()
    assert stored is not None and stored.origin == "shop" and stored.shop_ref == f"{AUTHOR}/{KEY}" and stored.shop_version == "1.0.0"
    assert stored.text == skin_text(), "a skin whose name is free is kept exactly as it came"
    assert stored.compiled["css"], "the style sheet is made here, from the file"
    assert shop.post(f"{ENTRY}/install/check", headers=CSRF).json()["skin_key"] == f"{KEY}-2"
    assert install(shop)["skin"] == f"{KEY}-2"
    again = row(f"{KEY}-2")
    assert again is not None and json.loads(again.text)["key"] == f"{KEY}-2"
    assert shop.get("/api/v1/workshop/catalog").json()["entries"][0]["installed"]["slug"] == KEY


def test_a_skin_that_this_nexdeck_cannot_wear_is_not_installed(shop: TestClient, github: GitHub) -> None:
    github.publish(skin_text(css="[data-part=chip] { color: red !important }"))
    seen = shop.post(f"{ENTRY}/install/check", headers=CSRF).json()
    assert seen["ok"] is False and any("!important" in problem["message"] for problem in seen["problems"])
    refused = shop.post(f"{ENTRY}/install", json={"accept_risk": True}, headers=CSRF)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "entry_invalid"
    assert row() is None


def test_a_card_the_catalog_calls_a_skin_is_refused(shop: TestClient, github: GitHub) -> None:
    github.publish(VALUE_CARD)
    github.entries[-1] = {**github.entries[-1], "type": "skin"}
    refused = shop.post(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/install", json={"accept_risk": True}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "type_mismatch"
    assert "a skin" in refused.json()["detail"]["message"]


def test_a_skin_from_the_shop_needs_the_word_about_the_risk_too(shop: TestClient, github: GitHub) -> None:
    github.publish(skin_text())
    refused = shop.post(f"{ENTRY}/install", json={"accept_risk": False}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "risk_not_acknowledged" and row() is None


# -- updates and recalls -----------------------------------------------------------------------------------------------


def test_a_newer_version_is_offered_and_taken_with_the_name_kept(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(skin_text())
    install(shop)
    github.publish(skin_text("1.1.0", name="Pixel desk, brighter"))
    told = look(shop, clock)
    assert [(one["type"], one["slug"], one["new_version"]) for one in told["updates"]] == [("skin", KEY, "1.1.0")]
    shown = shop.get(f"{UPDATES}/skins/{KEY}").json()
    assert shown["installed_version"] == "1.0.0" and shown["new_version"] == "1.1.0" and shown["locally_changed"] is False
    assert shown["changelog"] == "Changes of 1.1.0."
    taken = shop.post(f"{UPDATES}/skins/{KEY}/accept", json={"expected_version": "1.1.0"}, headers=CSRF).json()
    assert taken == {"status": "updated", "key": KEY, "version": "1.1.0", "copy_key": None}
    stored = row()
    assert stored is not None and stored.shop_version == "1.1.0" and json.loads(stored.text)["name"] == "Pixel desk, brighter"
    assert look(shop, clock)["updates"] == []
    assert shop.post(f"{UPDATES}/skins/{KEY}/accept", json={}, headers=CSRF).json()["status"] == "already_up_to_date"


def test_what_was_changed_here_is_kept_as_a_copy_when_wanted(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(skin_text())
    install(shop)
    mine = skin_text(description="My own colours.")
    assert shop.put(f"/api/v1/skins/{KEY}", json={"text": mine}, headers=CSRF).status_code == 200
    github.publish(skin_text("1.1.0"))
    look(shop, clock)
    assert shop.get(f"{UPDATES}/skins/{KEY}").json()["locally_changed"] is True
    taken = shop.post(f"{UPDATES}/skins/{KEY}/accept", json={"keep_mine": True}, headers=CSRF).json()
    assert taken["copy_key"] == f"{KEY}-mine"
    copy = row(f"{KEY}-mine")
    assert copy is not None and copy.origin == "own" and json.loads(copy.text)["description"] == "My own colours."
    assert json.loads(copy.text)["name"] == "Pixel desk (mine)"
    stored = row()
    assert stored is not None and json.loads(stored.text)["description"] == CONSOLE["description"] and stored.shop_version == "1.1.0"


def test_an_update_that_was_overtaken_or_cannot_be_worn_changes_nothing(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(skin_text())
    install(shop)
    github.publish(skin_text("1.2.0"))
    look(shop, clock)
    overtaken = shop.post(f"{UPDATES}/skins/{KEY}/accept", json={"expected_version": "1.1.0"}, headers=CSRF)
    assert overtaken.status_code == 409 and overtaken.json()["detail"]["code"] == "update_changed"
    github.publish(skin_text("1.3.0", native="retro"))
    look(shop, clock)
    broken = shop.post(f"{UPDATES}/skins/{KEY}/accept", json={}, headers=CSRF)
    assert broken.status_code == 400 and broken.json()["detail"]["code"] == "update_invalid"
    stored = row()
    assert stored is not None and stored.shop_version == "1.0.0" and stored.text == skin_text()


def test_a_skin_made_here_has_no_update_to_take(shop: TestClient, github: GitHub) -> None:
    assert shop.post("/api/v1/skins", json={"text": skin_text()}, headers=CSRF).status_code == 201
    missing = shop.get(f"{UPDATES}/skins/{KEY}")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "not_installed_from_shop"


def test_a_harmful_skin_rings_the_bell_with_the_way_to_the_skins(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(skin_text())
    install(shop)
    github.publish(skin_text(), removed={"level": "harmful", "reason": "It hides the buttons.", "at": "2026-10-30T10:00:00Z"})
    told = look(shop, clock)
    assert [(one["type"], one["slug"]) for one in told["removed"]] == [("skin", KEY)]
    with db_session() as db:
        notice = db.scalar(select(Notice).where(Notice.event == "card_recalled"))
        assert notice is not None and notice.link == "/system/skins"


# -- sharing -----------------------------------------------------------------------------------------------------------


def test_the_issue_of_a_skin_says_skin_and_holds_the_file_as_json() -> None:
    made = submit.build_body(type="skin", category="other", definition=skin_text(), description="A desk of bricks for the board.")
    fields = submit.parse_body(made)
    assert fields["type"] == "Skin" and json.loads(fields["definition"]) == json.loads(skin_text())
    assert "```json\n" in made


@pytest.fixture
def github(hub: Hub) -> Hub:
    """The pretend repository that speaks the rest of GitHub as well: issues, sign-in, comments."""
    return hub


@pytest.fixture
def me(shop: TestClient, hub: Hub, moment: list[float]) -> TestClient:
    from .test_karten16_submit import ME, sign_in

    sign_in(shop, hub, moment, hub.person("someone", ME))
    return shop


def test_a_skin_of_this_installation_is_checked_and_shared(me: TestClient, hub: Hub) -> None:
    assert me.post("/api/v1/skins", json={"text": skin_text()}, headers=CSRF).status_code == 201
    found = me.post("/api/v1/workshop/submit/check", json={"type": "skin", "slug": KEY}, headers=CSRF).json()
    assert found["problems"] == [] and found["type"] == "skin" and found["name"] == "Pixel desk" and found["version"] == "1.0.0"
    sent = me.post(
        "/api/v1/workshop/submit",
        json={"type": "skin", "slug": KEY, "category": "other", "description": "A desk of bricks behind the cards.", "license": True},
        headers=CSRF,
    )
    assert sent.status_code == 200, sent.text
    fields = submit.parse_body(hub.issues[0]["body"])
    assert fields["type"] == "Skin" and fields["definition"].rstrip("\n") == skin_text()
    listed = me.get("/api/v1/workshop/submissions").json()["items"]
    assert [(one["type"], one["slug"], one["local"]) for one in listed] == [("skin", KEY, True)]


def test_a_skin_that_is_not_there_or_not_worn_is_not_shared(me: TestClient) -> None:
    missing = me.post("/api/v1/workshop/submit/check", json={"type": "skin", "slug": "nothing-here"}, headers=CSRF)
    assert missing.status_code == 404
    with db_session() as db:
        db.add(Skin(key=KEY, name="Broken", text=skin_text(css="[data-part=chip] { color: red !important }"), compiled={}))
        db.commit()
    found = me.post("/api/v1/workshop/submit/check", json={"type": "skin", "slug": KEY}, headers=CSRF).json()
    assert found["problems"] and found["problems"][0]["path"] == "css"


def test_a_shared_skin_in_the_shop_needs_a_higher_version_for_an_update(me: TestClient, hub: Hub, clock: list[float]) -> None:
    from .test_karten16_submit import accepted

    assert me.post("/api/v1/skins", json={"text": skin_text()}, headers=CSRF).status_code == 201
    sent = me.post("/api/v1/workshop/submit", json={"type": "skin", "slug": KEY, "category": "other", "description": "A desk of bricks behind the cards.", "license": True}, headers=CSRF)
    assert sent.status_code == 200, sent.text
    accepted(hub, clock, 1, skin_text())
    found = me.post("/api/v1/workshop/submit/check", json={"type": "skin", "slug": KEY}, headers=CSRF).json()
    assert "version_not_higher" in [one["code"] for one in found["problems"]]
    assert catalog.Entry.model_validate(entry(skin_text())).type == "skin"
