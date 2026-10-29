"""KARTEN-19 AC-4, EC-1 (server): the entries the Workshop holds up as examples, and their checked text for a new draft."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import db_session
from app.models import CardRecord, Event, OwnIntegration
from app.workshop import catalog

from .conftest import CSRF, create_user, login
from .karten12_sample import INTEGRATION, SHORT
from .karten14_sample import AUTHOR, GitHub, card_text

BASE = "/api/v1/workshop"
SLUG = "queue-size"
pytest_plugins = ["tests.karten14_sample"]


def example(client: TestClient, slug: str = SLUG, author: str = AUTHOR):  # noqa: ANN202
    return client.get(f"{BASE}/examples/{author}/{slug}")


def counts() -> tuple[int, int, int]:
    with db_session() as db:
        return (
            int(db.scalar(select(func.count(CardRecord.id))) or 0),
            int(db.scalar(select(func.count(OwnIntegration.id))) or 0),
            int(db.scalar(select(func.count(Event.id))) or 0),
        )


def test_karten19_ac4_the_catalog_says_which_entries_are_examples(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), starter=True)
    github.publish(card_text("other-card"))
    github.publish(INTEGRATION, starter="yes")
    found = {one["slug"]: one["starter"] for one in shop.get(f"{BASE}/catalog").json()["entries"]}
    assert found == {SLUG: True, "other-card": False, SHORT: False}, "only the word true makes an example; a catalog without the field has none"


def test_karten19_ac4_an_example_comes_as_its_checked_text_and_makes_nothing(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), starter=True)
    before = counts()
    found = example(shop)
    assert found.status_code == 200, found.text
    assert found.json() == {"id": f"{AUTHOR}/{SLUG}", "type": "card", "slug": SLUG, "text": card_text()}
    assert counts() == before, "nothing is installed and nothing is saved before the administrator saves"
    assert github.count("definition.yaml") == 1


def test_karten19_ac4_an_entry_that_is_no_example_is_not_handed_out(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    refused = example(shop)
    assert refused.status_code == 404 and refused.json()["detail"]["code"] == "no_such_example"
    assert github.count("definition.yaml") == 0, "the definition of such an entry is not even fetched"
    assert example(shop, "nothing-here").status_code == 404


def test_karten19_ac4_the_text_must_match_the_checksum_of_the_catalog(shop: TestClient, github: GitHub) -> None:
    found = github.publish(card_text(), starter=True)
    github.files[found["files"]["definition"]] = card_text(version="9.9.9").encode()
    refused = example(shop)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "checksum_mismatch"


def test_karten19_ac4_a_removed_example_or_one_for_a_newer_nexdeck_is_not_handed_out(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), starter=True, removed={"level": "harmful", "reason": "No.", "at": "2026-10-28T00:00:00Z"})
    assert example(shop).json()["detail"]["code"] == "entry_removed"
    github.publish(card_text(), starter=True, min_nexdeck="99.0.0")
    catalog.forget()
    assert example(shop).json()["detail"]["code"] == "needs_newer_nexdeck"


def test_karten19_ac4_the_draft_gets_a_short_name_nobody_has_yet(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), starter=True)
    assert shop.post(f"{BASE}/entries/{AUTHOR}/{SLUG}/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    assert example(shop).json()["slug"] == f"{SLUG}-2"
    assert shop.post("/api/v1/cards", json={"yaml": card_text(f"{SLUG}-2")}, headers=CSRF).status_code == 201
    assert example(shop).json()["slug"] == f"{SLUG}-3"


def test_karten19_ac4_an_example_connection_gets_a_free_short_name_as_well(shop: TestClient, github: GitHub) -> None:
    github.publish(INTEGRATION, starter=True)
    assert example(shop, SHORT).json() == {"id": f"{AUTHOR}/{SHORT}", "type": "integration", "slug": SHORT, "text": INTEGRATION}
    assert shop.post("/api/v1/own-integrations", json={"yaml": INTEGRATION}, headers=CSRF).status_code == 201
    assert example(shop, SHORT).json()["slug"] == f"{SHORT}-2"


def test_karten19_ec1_a_shop_that_is_off_answers_without_asking_github(client: TestClient, github: GitHub) -> None:
    from .conftest import setup_admin

    setup_admin(client)
    refused = example(client)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "shop_off"
    assert github.requests == []


def test_karten19_ac4_only_administrators(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), starter=True)
    create_user(shop, "member")
    login(shop, "member", "another-long-password")
    assert example(shop).status_code == 403
    shop.post("/api/v1/auth/logout", headers=CSRF)
    assert example(shop).status_code in (401, 403)


def test_karten19_ac4_the_list_in_the_catalog_is_plain_json(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), starter=True)
    github.catalog_override = json.dumps({"format": 1, "generated_at": "", "entries": [{**github.entries[0], "starter": [1]}]}).encode()
    catalog.forget()
    assert shop.get(f"{BASE}/catalog").json()["entries"][0]["starter"] is False
