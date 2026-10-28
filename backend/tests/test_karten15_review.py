"""KARTEN-15 after the review: a button that asks, warns or answers differently is a changed button and is confirmed one by one."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF
from .karten8_sample import DOWNLOADS, button, with_buttons
from .karten14_sample import AUTHOR, GitHub

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
