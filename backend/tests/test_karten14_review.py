"""KARTEN-14 and KARTEN-15 after the review: the catalog and the repository setting as inputs that are not trusted, and the small leaks."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import Notice, OwnIntegration
from app.workshop import catalog, files

from .conftest import CSRF, create_user
from .karten3_sample import changed as change_integration
from .karten8_sample import DOWNLOADS, with_buttons
from .karten12_sample import INTEGRATION, SHORT
from .karten14_sample import AUTHOR, GitHub, card_text

pytest_plugins = ["tests.karten14_sample"]
BASE = "/api/v1/workshop"
KEY = "ghp_example-key-0123456789"


@pytest.mark.parametrize("field", ["definition", "readme", "changelog", "light", "dark"])
def test_karten14_review_a_path_with_a_line_break_at_its_end_is_not_a_path(shop: TestClient, github: GitHub, field: str) -> None:
    github.publish(card_text())
    github.entries[0]["files"][field] += "\n"
    found = shop.get(f"{BASE}/catalog")
    assert found.status_code == 502
    assert found.json()["detail"]["code"] == "catalog_invalid"


def test_karten14_review_a_redirect_to_another_host_is_not_followed(shop: TestClient, github: GitHub, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXDECK_WORKSHOP_TOKEN", KEY)
    github.publish(card_text())
    github.redirect = "https://stranger.example.com/catalog.json"
    catalog.forget()
    found = shop.get(f"{BASE}/catalog")
    assert not github.strangers
    assert found.status_code == 502
    assert found.json()["detail"]["code"] == "github_rejected"
    assert KEY not in found.text


def test_karten14_review_a_redirect_inside_the_api_of_github_is_followed(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.renamed = True
    catalog.forget()
    found = shop.get(f"{BASE}/catalog")
    assert found.status_code == 200, found.text
    assert github.requests[-1].url.path == "/repositories/1/contents/catalog.json"


def test_karten14_review_a_redirect_that_never_ends_is_given_up(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.redirect = "https://api.github.com/loop"
    catalog.forget()
    before = len(github.requests)
    found = shop.get(f"{BASE}/catalog")
    assert found.status_code == 502
    assert len(github.requests) - before == catalog.MAX_HOPS + 1


@pytest.mark.parametrize("repo", ["../..", "owner/..", "../x", "./.", "a/.", "a/b\n"])
def test_karten14_review_a_repository_that_climbs_is_refused(shop: TestClient, github: GitHub, repo: str) -> None:
    found = shop.put(f"{BASE}/settings", json={"repo": repo}, headers=CSRF)
    assert found.status_code == 400
    assert found.json()["detail"]["code"] == "bad_repo"
    assert shop.get(f"{BASE}/state").json()["repo"] == "DerKezorm/nexdeck-workshop"


def test_karten14_review_a_repository_with_dots_inside_a_name_is_fine(shop: TestClient, github: GitHub) -> None:
    assert shop.put(f"{BASE}/settings", json={"repo": "some.one/work-shop.v2"}, headers=CSRF).status_code == 200


def test_karten14_review_turning_the_shop_off_forgets_the_files_too(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    assert shop.get(f"{BASE}/catalog").status_code == 200
    assert shop.get(f"{BASE}/entries/{AUTHOR}/queue-size/image/light").status_code == 200
    assert shop.get(f"{BASE}/entries/{AUTHOR}/queue-size").status_code == 200
    assert files._files  # noqa: SLF001
    shop.put(f"{BASE}/settings", json={"enabled": False}, headers=CSRF)
    assert not files._files  # noqa: SLF001


def test_karten14_review_the_time_of_the_catalog_is_short(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.catalog_override = json.dumps({"format": 1, "generated_at": "g" * 3_000_000, "entries": github.entries}).encode()
    assert shop.get(f"{BASE}/catalog").status_code == 200
    assert len(shop.get(f"{BASE}/state").content) < 2000


def test_karten14_review_a_category_from_a_newer_catalog_is_other(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.publish(card_text(slug="games-card"), category="games")
    found = shop.get(f"{BASE}/catalog")
    assert found.status_code == 200, found.text
    assert {one["slug"]: one["category"] for one in found.json()["entries"]} == {"queue-size": "media", "games-card": "other"}


def test_karten14_review_a_plain_import_over_a_connection_of_the_shop_makes_it_one_of_this_installation(shop: TestClient, github: GitHub) -> None:
    github.publish(INTEGRATION)
    assert shop.post(f"{BASE}/entries/{AUTHOR}/{SHORT}/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    mine = change_integration(INTEGRATION, name="My own fork")
    done = shop.post("/api/v1/cards/import", json={"text": mine, "choices": {f"integration:{SHORT}": "replace"}}, headers=CSRF)
    assert done.status_code == 201, done.text
    with db_session() as db:
        piece = db.scalar(select(OwnIntegration).where(OwnIntegration.short == SHORT))
        assert (piece.shop_ref, piece.shop_version, piece.shop_hash) == ("", "", "")
    assert shop.get(f"{BASE}/entries/{AUTHOR}/{SHORT}").json()["installed"] is None


def test_karten14_review_the_bell_rings_once_for_an_entry_installed_twice(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    create_user(shop, "second", role="admin")
    github.publish(with_buttons(text=DOWNLOADS, version="1.0.0"))
    for choices in ({}, {"card:downloads": "copy"}):
        assert shop.post(f"{BASE}/entries/{AUTHOR}/downloads/install", json={"accept_risk": True, "choices": choices}, headers=CSRF).status_code == 201
    github.publish(with_buttons(text=DOWNLOADS, version="1.0.0"), removed={"level": "harmful", "reason": "steals data", "at": "2026-10-28T10:00:00Z"})
    clock[0] += 700
    assert shop.get(f"{BASE}/catalog").status_code == 200
    with db_session() as db:
        told: list[Any] = [(one.user_id, one.title) for one in db.scalars(select(Notice).where(Notice.event == "card_recalled"))]
    assert len(told) == 2, told
    assert len({user for user, _title in told}) == 2
