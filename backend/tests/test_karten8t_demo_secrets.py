"""B8 of the second security review: the rule for credentials in demo data covers every spelling, from one shared place.

``credential_names.is_access_name`` is the rule of the demo data (saving warns, sharing refuses, the Workshop's check is red)
and of the made-up examples (``demo._made_up`` hides such values). Before, ``X-Api-Key``, ``privateKey`` or ``pwd`` went past.
"""

from __future__ import annotations

import pytest

from app import credential_names
from app.cards import credentials, demo

SPELLED_OTHERWISE = ["X-Api-Key", "privateKey", "accessKey", "passphrase", "pwd", "auth", "Api Key", "auth.token", "x_auth_token", "ClientSecret"]
#: Names from real answers of the adapters' tests that hold no credential.
PLAIN = ["title", "monkey", "keyword", "author", "users", "username", "login", "userName", "status", "sizeleft", "trackedDownloadState",
         "episodeFileCount", "hostname", "address", "uptime", "name", "id", "sha256", "passed", "tokens_used_today"]


@pytest.mark.parametrize("name", SPELLED_OTHERWISE)
def test_karten8t_b8_a_credential_spelled_otherwise_is_found_in_demo_data(name: str) -> None:
    assert credential_names.is_access_name(name)
    assert credentials.demo_secrets({"r": {name: "k7Hq2pLw9Z0a", "title": "Dune"}}) == [(f"demo.r.{name}", name)]


@pytest.mark.parametrize("name", PLAIN[:-1])
def test_karten8t_b8_plain_names_and_names_that_only_say_who_asks_stay(name: str) -> None:
    assert not credentials.access_key(name), name
    assert credentials.demo_secrets({"r": {name: "something"}}) == []


def test_karten8t_b8_the_parts_of_the_old_list_still_count_inside_a_word() -> None:
    for name in ("xapikey", "db_passwd", "aws_access_key", "sessionId", "refresh_token", "tokens_used_today"):
        assert credentials.access_key(name), name


def test_karten8t_b8_examples_made_from_real_answers_hide_such_values() -> None:
    made, _cut = demo.disguise({"r": {"X-Api-Key": "k7Hq2pLw9Z0a", "privateKey": "k7Hq2pLw9Z0c", "title": "Dune"}})
    assert made["r"]["X-Api-Key"] == credentials.HIDDEN and made["r"]["privateKey"] == credentials.HIDDEN
    assert made["r"]["title"] != credentials.HIDDEN
    assert credentials.demo_secrets(made) == []
