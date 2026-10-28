"""KARTEN-14: installing from the shop (AC-1, AC-7, AC-8, AC-9, EC-1, EC-2, EC-3, EC-4)."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import CardRecord, Event, OwnIntegration, Setting

from .cards_sample import changed
from .conftest import CSRF, create_user, login
from .karten12_sample import CARD, INTEGRATION, SHORT
from .karten14_sample import AUTHOR, GitHub, card_text, clock, github, shop  # noqa: F401 - fixtures

SLUG = "queue-size"
BASE = f"/api/v1/workshop/entries/{AUTHOR}"


def check(client: TestClient, slug: str = SLUG):  # noqa: ANN202
    return client.post(f"{BASE}/{slug}/install/check", json={}, headers=CSRF)


def install(client: TestClient, slug: str = SLUG, **body):  # noqa: ANN202
    return client.post(f"{BASE}/{slug}/install", json={"accept_risk": True, **body}, headers=CSRF)


def cards() -> dict[str, CardRecord]:
    with db_session() as db:
        found = {row.slug: row for row in db.scalars(select(CardRecord).where(CardRecord.kind == "card"))}
        db.expunge_all()
        return found


def test_karten14_ac7_installing_makes_the_card_and_remembers_where_it_came_from(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(version="1.2.0"))
    found = install(shop)
    assert found.status_code == 201, found.text
    body = found.json()
    assert body["slug"] == SLUG
    assert body["outcome"]["cards_added"] == [SLUG]
    assert body["place_url"] == "/system/custom-cards"
    row = cards()[SLUG]
    assert (row.origin, row.shop_ref, row.shop_version) == ("shop", f"{AUTHOR}/{SLUG}", "1.2.0")
    # The text is the one of the catalog, word for word, and its checksum is kept to see a later change here.
    assert row.yaml_source == card_text(version="1.2.0")
    assert row.shop_hash == hashlib.sha256(card_text(version="1.2.0").rstrip().encode()).hexdigest()
    listed = shop.get("/api/v1/cards").json()["cards"][0]
    assert (listed["origin"], listed["shop_version"]) == ("shop", "1.2.0")
    with db_session() as db:
        lines = [one.detail for one in db.scalars(select(Event)) if one.name == SLUG]
    assert lines == ["imported from the Card shop"]


def test_karten14_ec3_an_installed_entry_says_so(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    assert shop.get("/api/v1/workshop/catalog").json()["entries"][0]["installed"] is None
    install(shop)
    assert shop.get("/api/v1/workshop/catalog").json()["entries"][0]["installed"] == {
        "slug": SLUG, "version": "1.0.0", "update": False, "locally_changed": False,
    }


def test_karten14_ac9_the_first_installation_needs_the_word_about_the_risk(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.publish(card_text("other-card"))
    assert shop.get("/api/v1/workshop/state").json()["risk_acknowledged"] is False
    assert check(shop).json()["risk_acknowledged"] is False
    refused = shop.post(f"{BASE}/{SLUG}/install", json={}, headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "risk_not_acknowledged"
    assert cards() == {}
    assert install(shop).status_code == 201
    assert shop.get("/api/v1/workshop/state").json()["risk_acknowledged"] is True
    # Said once: the next one does not ask again.
    assert shop.post(f"{BASE}/other-card/install", json={}, headers=CSRF).status_code == 201


def test_karten14_ac9_the_word_is_that_of_each_administrator(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    install(shop)
    create_user(shop, "second", role="admin")
    login(shop, "second", "another-long-password")
    assert shop.get("/api/v1/workshop/state").json()["risk_acknowledged"] is False
    refused = shop.post(f"{BASE}/{SLUG}/install", json={"choices": {f"card:{SLUG}": "copy"}}, headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "risk_not_acknowledged"


def test_karten14_ec1_a_file_that_does_not_match_the_checksum_is_not_installed(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.files[f"entries/{AUTHOR}/{SLUG}/definition.yaml"] = changed("Queue", "Changed", card_text()).encode()
    refused = install(shop)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "checksum_mismatch"
    assert "checksum" in refused.json()["detail"]["message"]
    assert cards() == {}


def test_karten14_ec2_a_card_for_a_newer_nexdeck_is_not_installed(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), min_nexdeck="99.0.0")
    refused = install(shop)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "needs_newer_nexdeck"
    assert cards() == {}


def test_karten14_an_entry_that_was_taken_out_is_not_installed(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), removed={"level": "not_useful", "reason": "Does nothing.", "at": "2026-10-21T10:00:00Z"})
    refused = install(shop)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "entry_removed"


def test_karten14_ec4_a_name_that_is_taken_needs_a_choice(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    assert shop.post("/api/v1/cards", json={"yaml": card_text(version="0.1.0")}, headers=CSRF).status_code == 201
    seen = check(shop).json()
    assert [(one["id"], one["exists"]) for one in seen["documents"]] == [(f"card:{SLUG}", True)]
    missing = install(shop)
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "import_choice_missing"
    assert cards()[SLUG].origin == "local"


def test_karten14_ec4_a_copy_is_a_card_of_the_shop_under_a_new_name(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    shop.post("/api/v1/cards", json={"yaml": card_text(version="0.1.0")}, headers=CSRF)
    found = install(shop, choices={f"card:{SLUG}": "copy"})
    assert found.status_code == 201, found.text
    assert found.json()["slug"] == f"{SLUG}-2"
    made = cards()
    assert (made[SLUG].origin, made[SLUG].shop_ref) == ("local", "")
    assert (made[f"{SLUG}-2"].origin, made[f"{SLUG}-2"].shop_ref) == ("shop", f"{AUTHOR}/{SLUG}")


def test_karten14_ec4_replacing_a_card_makes_it_one_of_the_shop(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    shop.post("/api/v1/cards", json={"yaml": card_text(version="0.1.0")}, headers=CSRF)
    found = install(shop, choices={f"card:{SLUG}": "replace"})
    assert found.status_code == 201, found.text
    row = cards()[SLUG]
    assert (row.origin, row.shop_ref, row.shop_version) == ("shop", f"{AUTHOR}/{SLUG}", "1.0.0")
    assert row.yaml_source == card_text()


def test_karten14_ec4_skipping_installs_nothing(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    shop.post("/api/v1/cards", json={"yaml": card_text(version="0.1.0")}, headers=CSRF)
    found = install(shop, choices={f"card:{SLUG}": "skip"})
    assert found.status_code == 201
    assert found.json()["slug"] is None
    assert cards()[SLUG].origin == "local"


def publish_pair(github: GitHub) -> None:
    github.publish(INTEGRATION)
    github.publish(CARD)


def test_karten14_ac8_a_card_that_needs_a_missing_own_connection_offers_it(shop: TestClient, github: GitHub) -> None:
    publish_pair(github)
    seen = check(shop, "queue-size").json()
    assert seen["ok"] is True
    assert [one["slug"] for one in seen["offered_integrations"]] == [SHORT]
    assert [one["id"] for one in seen["documents"]] == ["card:queue-size", f"integration:{SHORT}"]
    assert seen["missing_integrations"] == []
    assert shop.get(f"{BASE}/queue-size").json()["offered_integrations"][0]["slug"] == SHORT


def test_karten14_ac8_installing_takes_the_offered_connection_along(shop: TestClient, github: GitHub) -> None:
    publish_pair(github)
    found = install(shop, with_integrations=[f"{AUTHOR}/{SHORT}"])
    assert found.status_code == 201, found.text
    body = found.json()
    assert body["integrations"] == [SHORT]
    assert body["missing_integrations"] == []
    with db_session() as db:
        piece = db.scalar(select(OwnIntegration).where(OwnIntegration.short == SHORT))
        assert (piece.shop_ref, piece.shop_version) == (f"{AUTHOR}/{SHORT}", "1.0.0")
    assert cards()["queue-size"].origin == "shop"
    # The kind works at once.
    assert any(one["kind"] == f"custom:{SHORT}" for one in shop.get("/api/v1/cards/sources").json())


def test_karten14_ac8_the_offer_can_be_declined_and_the_card_says_what_is_missing(shop: TestClient, github: GitHub) -> None:
    publish_pair(github)
    found = install(shop)
    assert found.status_code == 201, found.text
    assert found.json()["missing_integrations"] == [f"custom:{SHORT}"]
    with db_session() as db:
        assert db.scalar(select(OwnIntegration)) is None


def test_karten14_ac8_nothing_is_offered_that_the_catalog_does_not_list(shop: TestClient, github: GitHub) -> None:
    github.publish(CARD)
    seen = check(shop, "queue-size").json()
    assert seen["offered_integrations"] == []
    assert seen["missing_integrations"] == [f"custom:{SHORT}"]
    refused = install(shop, with_integrations=[f"{AUTHOR}/{SHORT}"])
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "bad_integration_choice"


def test_karten14_ac8_nothing_is_offered_when_the_connection_is_here(shop: TestClient, github: GitHub) -> None:
    publish_pair(github)
    assert shop.post("/api/v1/own-integrations", json={"yaml": INTEGRATION}, headers=CSRF).status_code == 201
    seen = check(shop, "queue-size").json()
    assert seen["offered_integrations"] == []
    assert seen["missing_integrations"] == []


def test_karten14_all_or_nothing_when_an_offered_connection_is_wrong(shop: TestClient, github: GitHub) -> None:
    publish_pair(github)
    broken = b"nexdeck: integration\nshort: bookstack-own\n"
    github.files[f"entries/{AUTHOR}/{SHORT}/definition.yaml"] = broken
    github.entries[0]["sha256"] = hashlib.sha256(broken).hexdigest()
    refused = install(shop, with_integrations=[f"{AUTHOR}/{SHORT}"])
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "import_invalid"
    assert cards() == {}
    with db_session() as db:
        assert db.scalar(select(OwnIntegration)) is None


def test_karten14_an_own_connection_can_be_installed_alone(shop: TestClient, github: GitHub) -> None:
    github.publish(INTEGRATION)
    found = shop.post(f"{BASE}/{SHORT}/install", json={"accept_risk": True}, headers=CSRF)
    assert found.status_code == 201, found.text
    assert found.json()["integration"] == SHORT
    assert found.json()["slug"] is None
    assert shop.get("/api/v1/workshop/catalog").json()["entries"][0]["installed"]["slug"] == SHORT


def test_karten14_installing_checks_the_card_like_an_import_does(shop: TestClient, github: GitHub) -> None:
    broken = changed("requests:", "requestz:", card_text())
    github.publish(card_text())
    github.files[f"entries/{AUTHOR}/{SLUG}/definition.yaml"] = broken.encode()
    github.entries[0]["sha256"] = hashlib.sha256(broken.encode()).hexdigest()
    refused = install(shop)
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "import_invalid"
    assert cards() == {}


def test_karten14_ec5_a_shop_that_is_off_installs_nothing(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    shop.put("/api/v1/workshop/settings", json={"enabled": False}, headers=CSRF)
    before = len(github.requests)
    refused = install(shop)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "shop_off"
    assert len(github.requests) == before


def test_karten14_ac1_a_user_cannot_install(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    create_user(shop, "member")
    login(shop, "member", "another-long-password")
    assert install(shop).status_code == 403
    assert check(shop).status_code == 403
    assert shop.get(f"{BASE}/{SLUG}").status_code == 403
    assert shop.get(f"{BASE}/{SLUG}/image/light").status_code == 403
    assert shop.post(f"{BASE}/{SLUG}/preview", json={"integration_id": 1}, headers=CSRF).status_code == 403
    assert cards() == {}
    with db_session() as db:
        assert db.get(Setting, "workshop").value.get("risk", []) == []
