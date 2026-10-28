"""Nachlauf of the first real run: what the server tells and refuses after the Card shop was used (W3, N2, N3, N5, N6, N7)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF
from .karten3_sample import MEMOS
from .karten14_sample import card_text
from .karten16_sample import Hub
from .test_karten16_submit import (
    BASE,
    ME,
    SLUG,
    add_card,
    check,
    codes,
    install_from_another,
    share,
    sign_in,
)

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]


@pytest.fixture
def github(hub: Hub) -> Hub:
    return hub


@pytest.fixture
def me(shop: TestClient, hub: Hub, moment: list[float]) -> TestClient:
    """An administrator with the shop on, signed in to GitHub as 'someone' (4242), and a card of his own."""
    sign_in(shop, hub, moment, hub.person("someone", ME))
    add_card(shop)
    return shop


def shop_view(client: TestClient, slug: str) -> dict[str, Any]:
    return next(one for one in client.get("/api/v1/cards").json()["cards"] if one["slug"] == slug)["shop"]


# -- W3: nothing to share while it is as it came from the shop ------------------------------------------------------


def test_karten8n_w3_a_card_as_it_came_from_the_shop_says_so_and_is_not_shared(me: TestClient, hub: Hub, clock: list[float]) -> None:
    slug = install_from_another(me, hub, clock)
    assert shop_view(me, slug)["locally_changed"] is False
    assert "unchanged_from_shop" in codes(check(me, slug=slug))
    refused = share(me, slug=slug)
    assert refused.status_code == 400 and hub.issues == []
    assert "unchanged_from_shop" in [one["code"] for one in refused.json()["detail"]["problems"]]


def test_karten8n_w3_a_card_changed_after_it_came_is_shared_as_based_on_the_other(me: TestClient, hub: Hub, clock: list[float]) -> None:
    slug = install_from_another(me, hub, clock)
    me.put(f"/api/v1/cards/{slug}", json={"yaml": card_text(slug=slug) + "# mine\n", "overwrite": True}, headers=CSRF)
    assert shop_view(me, slug)["locally_changed"] is True
    found = check(me, slug=slug)
    assert "unchanged_from_shop" not in codes(found)
    assert found["based_on"] == "777/their-card" and found["mode"] == "new"


def test_karten8n_w3_an_own_entry_as_it_came_back_is_not_shared_but_changed_it_is_an_update(me: TestClient, hub: Hub, clock: list[float]) -> None:
    me.delete(f"/api/v1/cards/{SLUG}", headers=CSRF)
    hub.publish(card_text(), author=str(ME))
    clock[0] += 700
    assert me.post(f"{BASE}/entries/{ME}/{SLUG}/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    assert shop_view(me, SLUG)["locally_changed"] is False
    assert "unchanged_from_shop" in codes(check(me))
    newer = card_text(version="1.1.0") + "# next\n"
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": newer, "overwrite": True}, headers=CSRF)
    assert shop_view(me, SLUG)["locally_changed"] is True
    found = check(me)
    assert "unchanged_from_shop" not in codes(found) and found["mode"] == "update" and found["based_on"] is None


def test_karten8n_w3_a_card_of_your_own_has_no_shop_part(me: TestClient) -> None:
    mine = next(one for one in me.get("/api/v1/cards").json()["cards"] if one["slug"] == SLUG)
    assert mine["shop"] is None
    assert "unchanged_from_shop" not in codes(check(me))


def test_karten8n_w3_a_connection_from_the_shop_is_told_in_the_list_and_not_shared_until_changed(me: TestClient, hub: Hub) -> None:
    hub.publish(MEMOS, author="777")
    short = hub.entries[-1]["slug"]
    found = me.post(f"{BASE}/entries/777/{short}/install", json={"accept_risk": True}, headers=CSRF)
    assert found.status_code == 201, found.text
    row = next(one for one in me.get("/api/v1/own-integrations").json() if one["short"] == short)
    assert row["shop_ref"] == f"777/{short}" and row["locally_changed"] is False
    assert "unchanged_from_shop" in codes(check(me, type="integration", slug=short))
    assert share(me, type="integration", slug=short, category="other").status_code == 400
    me.put(f"/api/v1/own-integrations/{short}", json={"yaml": MEMOS + "# mine\n"}, headers=CSRF)
    row = next(one for one in me.get("/api/v1/own-integrations").json() if one["short"] == short)
    assert row["locally_changed"] is True
    again = check(me, type="integration", slug=short)
    assert "unchanged_from_shop" not in codes(again) and again["based_on"] == f"777/{short}"


def test_karten8n_w3_a_connection_of_your_own_is_not_called_changed(me: TestClient) -> None:
    made = me.post("/api/v1/own-integrations", json={"yaml": MEMOS}, headers=CSRF)
    row = next(one for one in me.get("/api/v1/own-integrations").json() if one["short"] == made.json()["short"])
    assert row["shop_ref"] == "" and row["locally_changed"] is False
