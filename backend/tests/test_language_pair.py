"""The two languages in the top bar belong to the account.

Everybody starts with English and German, as before. The active language is
always one of the two, whichever way it was chosen, and no code outside the
supported list gets stored at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import languages
from app.migrations import MIGRATIONS

from .conftest import ADMIN, CSRF, create_user, login, setup_admin

ROOT = Path(__file__).resolve().parents[2]


def _me(client: TestClient, **fields: object) -> dict:
    response = client.patch("/api/v1/auth/me", json=fields, headers=CSRF)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def third_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """A third language, so a pair can be left at all."""
    monkeypatch.setattr(languages, "SUPPORTED", (*languages.SUPPORTED, "xx"))


def test_a_new_account_has_english_and_german(client: TestClient) -> None:
    created = setup_admin(client)
    assert created["locale"] == "en"
    assert created["language_pair"] == ["en", "de"]
    assert client.get("/api/v1/auth/me").json()["language_pair"] == ["en", "de"]


def test_the_pair_is_saved_with_the_account(client: TestClient) -> None:
    setup_admin(client)
    assert _me(client, language_pair=["de", "en"])["language_pair"] == ["de", "en"]
    client.post("/api/v1/auth/logout", headers=CSRF)
    login(client, ADMIN["username"], ADMIN["password"])
    assert client.get("/api/v1/auth/me").json()["language_pair"] == ["de", "en"]


@pytest.mark.parametrize(
    "fields",
    [
        {"locale": "fr"},
        {"locale": ""},
        {"language_pair": ["en", "fr"]},
        {"language_pair": ["en", "en"]},
        {"language_pair": ["en"]},
        {"language_pair": ["en", "de", "de"]},
    ],
)
def test_unknown_codes_and_crooked_pairs_are_refused(client: TestClient, fields: dict) -> None:
    setup_admin(client)
    refused = client.patch("/api/v1/auth/me", json=fields, headers=CSRF)
    assert refused.status_code == 422, refused.text
    me = client.get("/api/v1/auth/me").json()
    assert (me["locale"], me["language_pair"]) == ("en", ["en", "de"]), "a refused change keeps the old one"


def test_the_other_ways_in_check_the_code_as_well(client: TestClient) -> None:
    assert client.post("/api/v1/setup", json={**ADMIN, "locale": "fr"}).status_code == 422
    setup_admin(client)
    new = client.post("/api/v1/users", json={"username": "ben", "password": "long-enough-1", "locale": "fr"}, headers=CSRF)
    assert new.status_code == 422, new.text
    ben = create_user(client, "ben")
    assert client.patch(f"/api/v1/users/{ben['id']}", json={"locale": "fr"}, headers=CSRF).status_code == 422
    assert client.patch("/api/v1/settings", json={"default_locale": "fr"}, headers=CSRF).status_code == 422
    assert client.patch("/api/v1/settings", json={"default_locale": "de"}, headers=CSRF).status_code == 200


def test_a_language_from_outside_takes_the_button_that_was_not_active(client: TestClient, third_language: None) -> None:
    setup_admin(client)
    me = _me(client, locale="xx")
    assert (me["locale"], me["language_pair"]) == ("xx", ["en", "xx"]), "English was on, so German gives way"

    _me(client, language_pair=["en", "de"])
    _me(client, locale="de")
    me = _me(client, locale="xx")
    assert (me["locale"], me["language_pair"]) == ("xx", ["xx", "de"]), "German was on and stays one press away"


def test_a_language_inside_the_pair_leaves_the_pair_alone(client: TestClient) -> None:
    setup_admin(client)
    me = _me(client, locale="de")
    assert (me["locale"], me["language_pair"]) == ("de", ["en", "de"])


def test_giving_the_active_button_another_language_switches_to_it(client: TestClient, third_language: None) -> None:
    setup_admin(client)
    _me(client, locale="de")
    me = _me(client, language_pair=["en", "xx"])
    assert (me["locale"], me["language_pair"]) == ("xx", ["en", "xx"])
    me = _me(client, language_pair=["de", "xx"])
    assert (me["locale"], me["language_pair"]) == ("xx", ["de", "xx"]), "the active language kept its button"


def test_both_at_once_mean_the_language_within_the_new_pair(client: TestClient, third_language: None) -> None:
    setup_admin(client)
    me = _me(client, language_pair=["de", "xx"], locale="xx")
    assert (me["locale"], me["language_pair"]) == ("xx", ["de", "xx"])


def test_setup_and_a_new_account_keep_the_chosen_language_in_the_pair(client: TestClient, third_language: None) -> None:
    created = client.post("/api/v1/setup", json={**ADMIN, "locale": "xx"}).json()
    assert (created["locale"], created["language_pair"]) == ("xx", ["en", "xx"])
    ben = client.post("/api/v1/users", json={"username": "ben", "password": "long-enough-1", "locale": "de"}, headers=CSRF).json()
    assert (ben["locale"], ben["language_pair"]) == ("de", ["en", "de"])
    changed = client.patch(f"/api/v1/users/{ben['id']}", json={"locale": "xx"}, headers=CSRF).json()
    assert (changed["locale"], changed["language_pair"]) == ("xx", ["xx", "de"])


def test_a_broken_stored_pair_reads_as_the_default() -> None:
    assert languages.read_pair("en,de") == ["en", "de"]
    for stored in ("", "en", "en,en", "en,fr", "en,de,en", "EN,DE"):
        assert languages.read_pair(stored) == ["en", "de"], stored


def test_the_step_gives_every_older_account_english_and_german() -> None:
    step = {version: function for version, _description, function in MIGRATIONS}[16]
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, locale VARCHAR(8))"))
        connection.execute(text("INSERT INTO users (id, locale) VALUES (1, 'de'), (2, 'en')"))
        step(connection)
        step(connection)  # a second run finds the column and leaves it
        rows = connection.execute(text("SELECT id, locale, language_pair FROM users ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [(1, "de", "en,de"), (2, "en", "en,de")]


def test_the_frontend_offers_the_same_languages_the_server_accepts() -> None:
    source = (ROOT / "frontend" / "src" / "i18n" / "index.ts").read_text(encoding="utf-8")
    block = re.search(r"export const LANGUAGES: Record<string, string> = \{([^}]*)\}", source)
    assert block, "LANGUAGES is no longer written the way this guard reads it"
    codes = re.findall(r"(\w+): '", block.group(1))
    assert len(codes) >= 2, "the guard found no languages"
    assert tuple(codes) == languages.SUPPORTED
    assert set(languages.DEFAULT_PAIR) <= set(codes)
