"""S3 (security review, stage 8): demo answers with a key or a password are not shared.

Demo answers are copied from a probe, and a service names its own key in some of them. A value under a key that sounds
like access (``apiKey``, ``password``, ``session_token``) that is no placeholder, and any value that is a credential of a
connection of this installation, is a secret in demo answers: saving warns, sharing is refused with ``secret_in_demo``
(place and key, never the value), and making demo answers from real ones hides such values at once.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.cards import credentials, load
from app.cards import demo as card_demo
from app.workshop import submit

from .cards_sample import DEMO_LINE, VALUE_CARD, changed
from .conftest import CSRF
from .test_cards_editor_api import admin  # noqa: F401 - the fixture
from .test_karten16_submit import (  # noqa: F401 - the fixtures
    add_card,
    check,
    codes,
    github,
    me,
    share,
)

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]

KEY = "0123456789abcdef" * 2  # a Sonarr key has 32 hex digits

PROBE_CARD = f"""\
nexdeck-card: 1
slug: queue-size
name: {{en: Queue size}}
description: {{en: Shows how many episodes wait in the queue of your Sonarr.}}
version: 1.0.0
requires: [sonarr]
requests:
  - id: host
    path: /api/v3/config/host
form: value
value: {{path: host.instanceName}}
demo:
  host: {{instanceName: Sonarr, apiKey: "{KEY}", password: "hunter2hunter2"}}
"""


def test_karten8s_s3_the_probe_of_the_review_a_demo_with_the_key_and_a_password_is_not_shared() -> None:
    load.load_definition(PROBE_CARD)  # the card itself is still accepted: saving only warns
    one = submit.Subject("card", "queue-size", PROBE_CARD, "local", "", False)
    found = submit.read_definition(one)
    assert [(one["code"], one["path"]) for one in found] == [("secret_in_demo", "demo.host.apiKey"), ("secret_in_demo", "demo.host.password")]
    assert all(KEY not in one["message"] and "hunter2" not in one["message"] for one in found)
    assert "apiKey" in found[0]["message"] and "demo.host.apiKey" in found[0]["message"]


@pytest.mark.parametrize(
    "key",
    ["apikey", "API_KEY", "X-ApiKey", "token", "refresh_token", "Secret", "password", "db_passwd", "Authorization",
     "cookie", "sessionId", "private_key", "client_secret", "aws_access_key"],
)
def test_karten8s_s3_a_value_under_a_key_that_sounds_like_access_is_a_secret(key: str) -> None:
    assert credentials.demo_secrets({"a": {key: "abc"}}) == [(f"demo.a.{key}", key)]
    assert credentials.demo_secrets({"a": {"list": [{key: 12345}]}}) == [(f"demo.a.list[0].{key}", key)]


@pytest.mark.parametrize("value", ["", "   ", None, True, False, "[hidden]", "…", "...", "•••", "xxx", "XXXX-XXXX", "xxxxxxxx", "<your key>", "<…>"])
def test_karten8s_s3_empty_null_and_placeholders_are_no_secret(value: Any) -> None:
    assert credentials.demo_secrets({"a": {"apiKey": value, "nested": {"password": value}}}) == []


def test_karten8s_s3_other_keys_are_not_judged_by_their_name_and_a_list_takes_the_name_of_its_key() -> None:
    demo = {"a": {"title": "secret plans", "monkey": "x", "tokens": ["one", "[hidden]"], "keyword": "abc"}}
    assert credentials.demo_secrets(demo) == [("demo.a.tokens[0]", "tokens")]


def test_karten8s_s3_a_value_that_is_a_credential_of_a_connection_here_is_a_secret_under_any_key() -> None:
    known = frozenset({"pw-of-the-nas-123"})
    demo = {"a": {"instance": "pw-of-the-nas-123", "other": "pw-of-the-nas-1234", "n": [" pw-of-the-nas-123 "]}}
    assert credentials.demo_secrets(demo, known) == [("demo.a.instance", "instance"), ("demo.a.n[0]", "n")]


def test_karten8s_s3_making_demo_answers_hides_such_values_at_once() -> None:
    answers = {"host": {"instanceName": "Sonarr", "apiKey": KEY, "session": {"token": "abc-123-xyz", "expires": 1700000000}, "pin": 1234, "api_key": "<key>"}}
    made, _cut = card_demo.disguise(answers, timedelta(days=40))
    host = made["host"]
    assert host["apiKey"] == "[hidden]" and host["session"]["token"] == "[hidden]"
    assert host["api_key"] != "[hidden]" and host["api_key"].startswith("<")
    assert host["instanceName"] != "[hidden]" and host["pin"] != "[hidden]"
    assert credentials.demo_secrets(made) == []


def test_karten8s_s3_saving_warns_with_the_place_and_the_key_never_the_value(admin: TestClient) -> None:  # noqa: F811
    text = changed(DEMO_LINE, 'demo:\n  queue: {totalRecords: 4, records: [], apiKey: "key-of-the-sonarr-0001"}\n')
    made = admin.post("/api/v1/cards", json={"yaml": text}, headers=CSRF)
    assert made.status_code == 201, made.text
    assert made.json()["warnings"] == [{"code": "secret_in_demo", "path": "demo.queue.apiKey", "key": "apiKey"}]
    assert "key-of-the-sonarr-0001" not in str(made.json()["warnings"])
    again = admin.put("/api/v1/cards/queue-size", json={"yaml": VALUE_CARD}, headers=CSRF)
    assert again.status_code == 200 and again.json()["warnings"] == []


def test_karten8s_s3_saving_warns_of_a_credential_of_a_connection_of_this_installation(admin: TestClient) -> None:  # noqa: F811
    stored = "-".join(("the", "sonarr", "key", "of", "this", "house"))
    made = admin.post("/api/v1/integrations", json={"kind": "sonarr", "name": "Series", "config": {"url": "http://sonarr.example.com:8989", "api_key": stored}}, headers=CSRF)
    assert made.status_code in (200, 201), made.text
    text = changed(DEMO_LINE, f'demo:\n  queue: {{totalRecords: 4, records: [{{title: "{stored}"}}]}}\n')
    saved = admin.post("/api/v1/cards", json={"yaml": text}, headers=CSRF)
    assert saved.json()["warnings"] == [{"code": "secret_in_demo", "path": "demo.queue.records[0].title", "key": "title"}]


def test_karten8s_s3_sharing_is_refused_with_secret_in_demo(me: TestClient) -> None:  # noqa: F811
    text = changed(DEMO_LINE, 'demo:\n  queue: {totalRecords: 4, records: [], password: "hunter2hunter2"}\n')
    assert me.put("/api/v1/cards/queue-size", json={"yaml": text}, headers=CSRF).status_code == 200
    found = check(me)
    assert "secret_in_demo" in codes(found)
    refused = share(me)
    assert refused.status_code == 400
    problems = refused.json()["detail"]["problems"] if "detail" in refused.json() else refused.json()["problems"]
    assert [one["path"] for one in problems if one["code"] == "secret_in_demo"] == ["demo.queue.password"]
    assert "hunter2hunter2" not in refused.text
