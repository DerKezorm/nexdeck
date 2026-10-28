"""KARTEN-14 after the review: replacing an own connection through the shop tells what it throws away and waits for a word."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from app.db import db_session
from app.models import Integration

from .conftest import CSRF
from .karten12_sample import INTEGRATION, SHORT
from .karten14_sample import AUTHOR, GitHub

pytest_plugins = ["tests.karten14_sample"]
BASE = "/api/v1/workshop"
ENTRY = f"{BASE}/entries/{AUTHOR}/{SHORT}"
KEY = f"integration:{SHORT}"


def stored(number: int) -> dict[str, str]:
    with db_session() as db:
        return dict(db.get(Integration, number).config or {})


def with_a_connection(shop: TestClient, github: GitHub, clock: list[float]) -> int:
    """The own connection is installed from the shop, one connection of its kind holds values, and a newer text turns a field into a secret."""
    github.publish(INTEGRATION)
    assert shop.post(ENTRY + "/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    made = shop.post(
        "/api/v1/integrations", json={"kind": f"custom:{SHORT}", "name": "Books", "config": {"url": "http://books.example.com", "token_id": "abc", "token_secret": "s3cret"}}, headers=CSRF,
    )
    assert made.status_code == 201, made.text
    data = yaml.safe_load(INTEGRATION)
    for field in data["fields"]:
        if field["name"] == "token_id":
            field["type"] = "secret"
    github.publish(yaml.safe_dump(data, sort_keys=False), version="1.1.0")
    clock[0] += 700
    return made.json()["id"]


def test_karten14_review_the_check_names_the_fields_that_replacing_throws_away(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    with_a_connection(shop, github, clock)
    checked = shop.post(ENTRY + "/install/check", json={}, headers=CSRF).json()
    assert checked["documents"][0]["exists"] is True
    assert checked["documents"][0]["dropped_fields"] == ["token_id"]


def test_karten14_review_replacing_waits_for_the_word_about_what_is_thrown_away(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    number = with_a_connection(shop, github, clock)
    refused = shop.post(ENTRY + "/install", json={"accept_risk": True, "choices": {KEY: "replace"}}, headers=CSRF)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "dropped_not_confirmed"
    assert detail["documents"] == [{"id": KEY, "fields": ["token_id"]}]
    assert stored(number)["token_id"] == "abc"
    done = shop.post(ENTRY + "/install", json={"accept_risk": True, "choices": {KEY: "replace"}, "confirm_dropped": True}, headers=CSRF)
    assert done.status_code == 201, done.text
    assert "token_id" not in stored(number)
    assert "token_secret" in stored(number)


def test_karten14_review_a_copy_throws_nothing_away_and_asks_nothing(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    number = with_a_connection(shop, github, clock)
    done = shop.post(ENTRY + "/install", json={"accept_risk": True, "choices": {KEY: "copy"}}, headers=CSRF)
    assert done.status_code == 201, done.text
    assert stored(number)["token_id"] == "abc"


def test_karten14_review_replacing_with_the_same_fields_asks_nothing(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(INTEGRATION)
    assert shop.post(ENTRY + "/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    github.publish(INTEGRATION + "# a newer comment\n", version="1.1.0")
    clock[0] += 700
    done = shop.post(ENTRY + "/install", json={"accept_risk": True, "choices": {KEY: "replace"}}, headers=CSRF)
    assert done.status_code == 201, done.text
