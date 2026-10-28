"""KARTEN-14 after the review: what the shop shows of an entry is read from its checked definition, and a definition has to be what its entry says."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import CardRecord, OwnIntegration

from .conftest import CSRF
from .karten3_sample import changed as change_integration
from .karten8_sample import DOWNLOADS, button, with_buttons
from .karten12_sample import CARD, INTEGRATION, SHORT
from .karten14_sample import AUTHOR, GitHub, card_text

pytest_plugins = ["tests.karten14_sample"]
BASE = "/api/v1/workshop"
SONARR = {"kind": "sonarr", "name": "My Sonarr", "config": {"url": "http://svc.example.com:8989", "api_key": "k"}}
#: What a catalog may say about a card that has a DELETE button and reads through jsonapi.
LIES = {"class": "read", "buttons": [], "reads": [], "requires": ["pihole"]}


def lying_downloads(github: GitHub) -> None:
    github.publish(with_buttons(button(id="wipe", path="/api/wipe", method="DELETE"), text=DOWNLOADS), **LIES)


def acts(body: dict) -> list[tuple[str, str]]:
    return [(one["method"], one["path"]) for one in body["buttons"]]


def test_karten14_review_the_detail_shows_the_definition_and_says_what_the_catalog_said_otherwise(shop: TestClient, github: GitHub) -> None:
    lying_downloads(github)
    seen = shop.get(f"{BASE}/entries/{AUTHOR}/downloads").json()
    assert seen["class"] == "buttons"
    assert ("DELETE", "/api/wipe") in acts(seen)
    assert [one["path"] for one in seen["reads"]] == ["/api/v2/torrents/info"]
    assert [one["kind"] for one in seen["requires"]] == ["jsonapi"]
    assert seen["verified"] is True
    assert set(seen["claims_differ"]) == {"class", "buttons", "reads", "requires"}


def test_karten14_review_a_catalog_that_tells_the_truth_has_nothing_to_say(shop: TestClient, github: GitHub) -> None:
    text = with_buttons(button(id="wipe", path="/api/wipe", method="DELETE"), text=DOWNLOADS)
    github.publish(text)
    seen = shop.get(f"{BASE}/entries/{AUTHOR}/downloads").json()
    github.entries[0]["reads"] = [{"kind": "jsonapi", "path": one["path"]} for one in seen["reads"]]
    github.entries[0]["buttons"] = [{"label": "x", "method": one["method"], "path": one["path"]} for one in seen["buttons"]]
    github.entries[0]["class"] = "buttons"
    from app.workshop import catalog

    catalog.forget()
    again = shop.get(f"{BASE}/entries/{AUTHOR}/downloads").json()
    assert again["verified"] is True
    assert again["claims_differ"] == []


def test_karten14_review_the_list_is_the_words_of_the_catalog_and_says_so(shop: TestClient, github: GitHub) -> None:
    lying_downloads(github)
    one = shop.get(f"{BASE}/catalog").json()["entries"][0]
    assert one["verified"] is False
    assert one["class"] == "read"


def test_karten14_review_the_check_before_installing_shows_the_definition(shop: TestClient, github: GitHub) -> None:
    lying_downloads(github)
    checked = shop.post(f"{BASE}/entries/{AUTHOR}/downloads/install/check", json={}, headers=CSRF).json()
    assert checked["entry"]["class"] == "buttons"
    assert ("DELETE", "/api/wipe") in acts(checked["entry"])
    assert "buttons" in checked["entry"]["claims_differ"]


def test_karten14_review_a_card_fits_by_the_kinds_its_definition_names(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), requires=["pihole"])
    assert shop.post("/api/v1/integrations", json=SONARR, headers=CSRF).status_code == 201
    assert shop.get(f"{BASE}/catalog").json()["entries"][0]["fits"] is False
    seen = shop.get(f"{BASE}/entries/{AUTHOR}/queue-size").json()
    assert seen["fits"] is True
    assert [one["kind"] for one in seen["connections"]] == ["sonarr"]


def test_karten14_review_an_own_connection_is_offered_by_what_the_definition_needs(shop: TestClient, github: GitHub) -> None:
    github.publish(INTEGRATION)
    github.publish(card_text(slug="withown", text=CARD), requires=[])
    seen = shop.get(f"{BASE}/entries/{AUTHOR}/withown").json()
    assert [(one["slug"], one["verified"]) for one in seen["offered_integrations"]] == [(SHORT, True)]
    checked = shop.post(f"{BASE}/entries/{AUTHOR}/withown/install/check", json={}, headers=CSRF).json()
    assert [(one["slug"], one["verified"]) for one in checked["offered_integrations"]] == [(SHORT, True)]


def test_karten14_review_a_definition_that_cannot_be_read_shows_nothing_of_it(shop: TestClient, github: GitHub) -> None:
    broken = "nexdeck-card: 1\nslug: queue-size\nnot: valid\n"
    github.publish(card_text())
    github.entries[0]["sha256"] = hashlib.sha256(broken.encode()).hexdigest()
    github.files[github.entries[0]["files"]["definition"]] = broken.encode()
    seen = shop.get(f"{BASE}/entries/{AUTHOR}/queue-size")
    assert seen.status_code == 200
    body = seen.json()
    assert body["class"] == "unknown" and body["reads"] == [] and body["buttons"] == []
    assert body["verified"] is False
    assert body["files_warning"]["code"] == "definition_unreadable"


# -- a definition has to be what its entry says it is -----------------------------------------------------------------------


def own_connections() -> int:
    with db_session() as db:
        return len(db.scalars(select(OwnIntegration)).all())


def test_karten14_review_a_card_entry_whose_file_is_an_own_connection_is_not_installed(shop: TestClient, github: GitHub) -> None:
    github.publish(INTEGRATION, type="card")
    found = shop.post(f"{BASE}/entries/{AUTHOR}/{SHORT}/install", json={"accept_risk": True}, headers=CSRF)
    assert found.status_code == 409, found.text
    assert found.json()["detail"]["code"] == "type_mismatch"
    assert own_connections() == 0


def test_karten14_review_an_entry_for_an_own_connection_whose_file_is_a_card_is_not_installed(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), type="integration")
    found = shop.post(f"{BASE}/entries/{AUTHOR}/queue-size/install", json={"accept_risk": True}, headers=CSRF)
    assert found.status_code == 409
    assert found.json()["detail"]["code"] == "type_mismatch"
    with db_session() as db:
        assert db.scalar(select(CardRecord)) is None


def test_karten14_review_the_check_and_the_preview_refuse_a_file_of_the_wrong_type_too(shop: TestClient, github: GitHub) -> None:
    github.publish(INTEGRATION, type="card")
    assert shop.post(f"{BASE}/entries/{AUTHOR}/{SHORT}/install/check", json={}, headers=CSRF).json()["detail"]["code"] == "type_mismatch"
    previewed = shop.post(f"{BASE}/entries/{AUTHOR}/{SHORT}/preview", json={"integration_id": 1}, headers=CSRF)
    assert previewed.status_code == 409 and previewed.json()["detail"]["code"] == "type_mismatch"


def test_karten14_review_the_detail_of_an_entry_of_the_wrong_type_says_so(shop: TestClient, github: GitHub) -> None:
    github.publish(INTEGRATION, type="card")
    body = shop.get(f"{BASE}/entries/{AUTHOR}/{SHORT}").json()
    assert body["files_warning"]["code"] == "type_mismatch"
    assert body["class"] == "unknown"


def test_karten14_review_an_update_that_is_another_type_is_refused(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(card_text())
    assert shop.post(f"{BASE}/entries/{AUTHOR}/queue-size/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    clock[0] += 700
    other = change_integration(INTEGRATION, short="queue-size")
    github.publish(other, version="1.1.0", type="card", slug="queue-size")
    assert shop.get(f"{BASE}/catalog").status_code == 200
    detail = shop.get(f"{BASE}/updates/queue-size")
    assert detail.status_code == 409 and detail.json()["detail"]["code"] == "type_mismatch"
    assert shop.post(f"{BASE}/updates/queue-size/accept", json={}, headers=CSRF).status_code == 409
    with db_session() as db:
        assert db.scalar(select(CardRecord.shop_version).where(CardRecord.slug == "queue-size")) == "1.0.0"
