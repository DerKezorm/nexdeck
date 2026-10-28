"""KARTEN-15 after the review: a button that asks, warns or answers differently is a changed button and is confirmed one by one."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import CardRecord, Notice
from app.workshop import updates

from .conftest import CSRF
from .karten8_sample import DOWNLOADS, button, with_buttons
from .karten14_sample import AUTHOR, GitHub, card_text

pytest_plugins = ["tests.karten14_sample"]
BASE = "/api/v1/workshop"
ASK = {"name": "n", "label": "How many?", "type": "number", "max": 5}


def card(version: str, *buttons: dict[str, Any]) -> str:
    return with_buttons(*buttons, text=DOWNLOADS, version=version)


def installed(shop: TestClient, github: GitHub, *buttons: dict[str, Any]) -> None:
    github.publish(card("1.0.0", *buttons))
    assert shop.post(f"{BASE}/entries/{AUTHOR}/downloads/install", json={"accept_risk": True}, headers=CSRF).status_code == 201


def newer(shop: TestClient, github: GitHub, clock: list[float], *buttons: dict[str, Any]) -> dict[str, Any]:
    github.publish(card("1.1.0", *buttons))
    clock[0] += 700
    assert shop.get(f"{BASE}/catalog").status_code == 200
    return shop.get(f"{BASE}/updates/downloads").json()


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ({"confirm": True}, {"confirm": False}),
        ({"danger": True}, {"danger": False}),
        ({"danger": False}, {"danger": True}),
        ({"asks": [ASK]}, {"asks": [{**ASK, "max": 5000}]}),
        ({}, {"asks": [ASK]}),
        ({"answer": "done"}, {"answer": "gone"}),
        ({"where": "card"}, {"where": "row"}),
    ],
    ids=["no_longer_asks", "no_longer_dangerous", "becomes_dangerous", "wider_range", "new_question", "other_answer", "other_place"],
)
def test_karten15_review_a_button_that_asks_or_answers_differently_is_a_changed_button(
    shop: TestClient, github: GitHub, clock: list[float], before: dict[str, Any], after: dict[str, Any],
) -> None:
    installed(shop, github, button(id="wipe", path="/api/wipe", method="DELETE", **before))
    detail = newer(shop, github, clock, button(id="wipe", path="/api/wipe", method="DELETE", **after))
    assert detail["buttons_to_confirm"] == ["wipe"]
    assert [one["after"]["id"] for one in detail["permissions"]["buttons"]["changed"]] == ["wipe"]
    refused = shop.post(f"{BASE}/updates/downloads/accept", json={}, headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "buttons_not_confirmed"
    assert shop.post(f"{BASE}/updates/downloads/accept", json={"confirmed_buttons": ["wipe"]}, headers=CSRF).status_code == 200


def test_karten15_review_the_change_shows_both_sides_of_what_a_button_asks(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    installed(shop, github, button(id="wipe", path="/api/wipe", method="DELETE", confirm=True, danger=True))
    detail = newer(shop, github, clock, button(id="wipe", path="/api/wipe", method="DELETE", confirm=False, danger=False))
    one = detail["permissions"]["buttons"]["changed"][0]
    assert (one["before"]["confirm"], one["before"]["danger"]) == (True, True)
    assert (one["after"]["confirm"], one["after"]["danger"]) == (False, False)


def test_karten15_review_a_new_label_or_symbol_alone_is_still_no_new_question(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    installed(shop, github, button(id="go", icon="play"))
    detail = newer(shop, github, clock, button(id="go", label="Run", icon="rocket"))
    assert detail["buttons_to_confirm"] == []


def test_karten15_review_leaving_out_a_plain_value_is_the_same_as_writing_it(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    installed(shop, github, button(id="go"))
    detail = newer(shop, github, clock, button(id="go", confirm=False, danger=False, asks=[], answer=None))
    assert detail["buttons_to_confirm"] == []


# -- the preview of a card that is gone, the words of a recall, a card without a note of its text -----------------------------


def test_karten15_review_a_card_that_was_taken_out_has_no_preview(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), removed={"level": "harmful", "reason": "bad", "at": "2026-10-28T10:00:00Z"})
    found = shop.post(f"{BASE}/entries/{AUTHOR}/queue-size/preview", json={"integration_id": 1}, headers=CSRF)
    assert found.status_code == 409
    assert found.json()["detail"]["code"] == "entry_removed"


def test_karten15_review_a_card_for_a_newer_nexdeck_has_no_preview(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), min_nexdeck="99.0.0")
    found = shop.post(f"{BASE}/entries/{AUTHOR}/queue-size/preview", json={"integration_id": 1}, headers=CSRF)
    assert found.status_code == 409
    assert found.json()["detail"]["code"] == "needs_newer_nexdeck"


def test_karten15_review_the_bell_of_a_recall_is_one_line_and_short(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    installed(shop, github)
    reason = "<script>alert(1)</script>" + "r" * 1900
    github.publish(card("1.0.0"), name="<b>Down</b>\nloads\r\nBcc: x@example.com", removed={"level": "harmful", "reason": reason, "at": "2026-10-28T10:00:00Z"})
    clock[0] += 700
    assert shop.get(f"{BASE}/catalog").status_code == 200
    with db_session() as db:
        notices = db.scalars(select(Notice).where(Notice.event == "card_recalled")).all()
        assert len(notices) == 1
        assert "\n" not in notices[0].title and "\r" not in notices[0].title
        assert notices[0].title.startswith("<b>Down</b> loads Bcc: x@example.com")
        assert len(notices[0].body) == updates.REASON_MAX


def test_karten15_review_a_card_without_a_note_of_its_text_is_not_called_changed(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    installed(shop, github)
    with db_session() as db:
        row = db.scalar(select(CardRecord).where(CardRecord.slug == "downloads"))
        row.shop_hash = ""
        row.yaml_source = row.yaml_source + "# my note\n"
        db.commit()
    detail = newer(shop, github, clock)
    assert detail["locally_changed"] is False
    done = shop.post(f"{BASE}/updates/downloads/accept", json={}, headers=CSRF)
    assert done.status_code == 200 and done.json()["status"] == "updated" and done.json()["copy_slug"] is None
