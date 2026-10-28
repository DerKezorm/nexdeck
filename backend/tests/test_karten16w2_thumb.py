"""KARTEN-16 (change W2): the thumb on the discussion of an entry, set from nexdeck in the name of the administrator."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import User
from app.workshop import github_login, thumbs

from .conftest import ADMIN, CSRF, create_user, login
from .karten14_sample import REPO, card_text
from .karten16_sample import Hub

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]

BASE = "/api/v1/workshop"
ENTRY = "4242/queue-size"
THUMB = f"{BASE}/entries/{ENTRY}/thumb"
NO_RIGHT = "The Workshop app may not react to discussions yet. Rate it on GitHub instead."


@pytest.fixture
def github(hub: Hub) -> Hub:
    return hub


def sign_in(client: TestClient, hub: Hub, moment: list[float], person: dict[str, Any]) -> None:
    assert client.post(f"{BASE}/github/login", headers=CSRF).status_code == 200
    hub.sign_in_as(person)
    moment[0] += 6
    done = client.post(f"{BASE}/github/login/poll", headers=CSRF).json()
    assert done["status"] == "signed_in", done


def graphql(hub: Hub) -> list[dict[str, Any]]:
    return hub.graphql


def test_karten16w2_a_shop_that_is_off_answers_409_and_asks_github_nothing(client: TestClient, hub: Hub) -> None:
    from .conftest import setup_admin

    setup_admin(client)
    assert client.get(THUMB).status_code == 409 and client.get(THUMB).json()["detail"]["code"] == "shop_off"
    put = client.put(THUMB, json={"on": True}, headers=CSRF)
    assert put.status_code == 409 and put.json()["detail"]["code"] == "shop_off"
    assert hub.requests == []


def test_karten16w2_only_administrators_and_only_with_the_csrf_header(shop: TestClient, hub: Hub) -> None:
    hub.publish(card_text(), discussion=hub.open_discussion())
    assert shop.put(THUMB, json={"on": True}).status_code == 403, "no header"
    create_user(shop, "plain")
    login(shop, "plain", "another-long-password")
    assert shop.get(THUMB).status_code == 403
    assert shop.put(THUMB, json={"on": True}, headers=CSRF).status_code == 403
    shop.cookies.clear()
    assert shop.get(THUMB).status_code == 401
    assert graphql(hub) == []


def test_karten16w2_not_signed_in_nothing_is_asked_of_graphql_and_a_thumb_needs_the_sign_in(shop: TestClient, hub: Hub) -> None:
    hub.publish(card_text(), discussion=hub.open_discussion())
    assert shop.get(THUMB).json() == {"signed_in": False, "on": None}
    put = shop.put(THUMB, json={"on": True}, headers=CSRF)
    assert put.status_code == 409 and put.json()["detail"]["code"] == "github_login_needed"
    assert graphql(hub) == []


def test_karten16w2_an_entry_without_a_discussion_is_not_asked_about(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    hub.publish(card_text())
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    assert shop.get(THUMB).json() == {"signed_in": True, "on": None}
    put = shop.put(THUMB, json={"on": True}, headers=CSRF)
    assert put.status_code == 409 and put.json()["detail"]["code"] == "no_discussion"
    assert graphql(hub) == []


def test_karten16w2_the_thumb_is_set_read_and_taken_away_with_the_token_of_the_administrator(
    shop: TestClient, hub: Hub, moment: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXDECK_WORKSHOP_TOKEN", "ghp_the-key-of-the-shop-0123456789")
    named = hub.open_discussion()
    hub.publish(card_text(), discussion=named)
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    assert shop.get(THUMB).json() == {"signed_in": True, "on": False}
    assert shop.put(THUMB, json={"on": True}, headers=CSRF).json() == {"on": True}
    assert hub.discussions[named["id"]]["thumbs"] == {"someone"}
    assert shop.get(THUMB).json() == {"signed_in": True, "on": True}
    assert shop.put(THUMB, json={"on": True}, headers=CSRF).json() == {"on": True}, "setting it again changes nothing"
    assert hub.discussions[named["id"]]["thumbs"] == {"someone"}
    assert shop.put(THUMB, json={"on": False}, headers=CSRF).json() == {"on": False}
    assert hub.discussions[named["id"]]["thumbs"] == set()
    assert shop.get(THUMB).json() == {"signed_in": True, "on": False}
    token = next(iter(hub.tokens))
    assert graphql(hub) and all(one["token"] == token for one in graphql(hub)), "never the key of the shop"
    assert {one["variables"]["id"] for one in graphql(hub)} == {named["id"]}


def test_karten16w2_a_catalog_that_names_only_the_address_is_looked_up_by_it(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    named = hub.open_discussion("D_kwDOother9", 9)
    hub.publish(card_text(), discussion=named["url"])
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    assert shop.get(THUMB).json() == {"signed_in": True, "on": False}
    assert shop.put(THUMB, json={"on": True}, headers=CSRF).json() == {"on": True}
    assert hub.discussions["D_kwDOother9"]["thumbs"] == {"someone"}
    assert shop.get(THUMB).json() == {"signed_in": True, "on": True}
    # The entry as shown keeps the address, whichever way the catalog names it.
    assert shop.get(f"{BASE}/entries/{ENTRY}").json()["discussion"] == named["url"]


def test_karten16w2_an_address_outside_the_workshop_repository_is_not_used(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    hub.publish(card_text(), discussion="https://github.com/somebody/else/discussions/1")
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    assert shop.get(THUMB).json() == {"signed_in": True, "on": None}
    assert shop.put(THUMB, json={"on": True}, headers=CSRF).status_code == 409
    assert graphql(hub) == []


def test_karten16w2_a_subject_id_in_the_request_is_never_used(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    named = hub.open_discussion()
    stranger = hub.open_discussion("D_kwDOstranger", 99)
    hub.discussions["D_kwDOstranger"]["url"] = "https://github.com/somebody/else/discussions/99"
    hub.publish(card_text(), discussion=named)
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    put = shop.put(THUMB, json={"on": True, "subjectId": stranger["id"], "id": stranger["id"], "discussion": stranger}, headers=CSRF)
    assert put.status_code == 200 and put.json() == {"on": True}
    assert hub.discussions[stranger["id"]]["thumbs"] == set()
    assert hub.discussions[named["id"]]["thumbs"] == {"someone"}
    assert [one["variables"] for one in graphql(hub)] == [{"id": named["id"]}]


def test_karten16w2_an_administrator_never_uses_the_sign_in_of_another(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    named = hub.open_discussion()
    hub.publish(card_text(), discussion=named)
    sign_in(shop, hub, moment, hub.person("first", 11))
    create_user(shop, "second", role="admin")
    login(shop, "second", "another-long-password")
    # The second one is not signed in: his thumb is refused, and nothing goes out with the token of the first.
    assert shop.get(THUMB).json() == {"signed_in": False, "on": None}
    put = shop.put(THUMB, json={"on": True}, headers=CSRF)
    assert put.status_code == 409 and put.json()["detail"]["code"] == "github_login_needed"
    assert graphql(hub) == []
    sign_in(shop, hub, moment, hub.person("second-account", 22))
    assert shop.put(THUMB, json={"on": True}, headers=CSRF).status_code == 200
    assert hub.discussions[named["id"]]["thumbs"] == {"second-account"}
    login(shop, ADMIN["username"], ADMIN["password"])
    assert shop.get(THUMB).json() == {"signed_in": True, "on": False}, "the first one has no thumb of his own there"
    assert {one["login"] for one in graphql(hub)} == {"first", "second-account"}


def test_karten16w2_without_the_right_the_answer_is_the_sentence_and_the_code(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    hub.publish(card_text(), discussion=hub.open_discussion())
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    hub.discussion_rights = False
    for sent in (shop.put(THUMB, json={"on": True}, headers=CSRF), shop.get(THUMB)):
        assert sent.status_code == 403
        assert sent.json()["detail"] == {"code": "github_no_discussions", "message": NO_RIGHT}
    assert shop.get(f"{BASE}/github").json()["signed_in"] is True, "the sign-in stays"


def test_karten16w2_a_token_github_refuses_asks_for_a_new_sign_in(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    hub.publish(card_text(), discussion=hub.open_discussion())
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    hub.revoke_everything()
    put = shop.put(THUMB, json={"on": True}, headers=CSRF)
    assert put.status_code == 409 and put.json()["detail"]["code"] == "github_login_needed"
    assert shop.get(f"{BASE}/github").json()["signed_in"] is False
    assert shop.get(THUMB).json() == {"signed_in": False, "on": None}


def test_karten16w2_a_thumb_for_an_entry_the_catalog_does_not_have_is_404(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    hub.publish(card_text(), discussion=hub.open_discussion())
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    assert shop.get(f"{BASE}/entries/4242/none/thumb").status_code == 404
    assert shop.put(f"{BASE}/entries/4242/none/thumb", json={"on": True}, headers=CSRF).status_code == 404
    assert shop.put(THUMB, json={}, headers=CSRF).status_code == 422
    assert graphql(hub) == []


def test_karten16w2_the_token_is_in_no_answer_and_no_log(shop: TestClient, hub: Hub, moment: list[float], caplog: pytest.LogCaptureFixture) -> None:
    hub.publish(card_text(), discussion=hub.open_discussion())
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    token = next(iter(hub.tokens))
    with caplog.at_level("DEBUG"):
        seen = [shop.get(THUMB), shop.put(THUMB, json={"on": True}, headers=CSRF)]
        hub.discussion_rights = False
        seen += [shop.put(THUMB, json={"on": True}, headers=CSRF)]
    assert all(token not in one.text for one in seen) and token not in caplog.text


def test_karten16w2_two_clicks_at_once_wait_for_each_other_per_administrator_and_entry(
    shop: TestClient, hub: Hub, moment: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = hub.open_discussion("D_kwDOone", 1), hub.open_discussion("D_kwDOtwo", 2)
    hub.publish(card_text(), discussion=first)
    hub.publish(card_text(slug="other-card"), discussion=second)
    sign_in(shop, hub, moment, hub.person("someone", 4242))
    shop.get(f"{BASE}/catalog")  # the catalog is in the memory
    from app.workshop import catalog as shop_catalog

    found, _ = asyncio.run(shop_catalog.load(REPO))
    inside = {"now": 0, "most": 0}
    real = github_login.call

    async def slow(*args: Any, **more: Any) -> Any:
        inside["now"] += 1
        inside["most"] = max(inside["most"], inside["now"])
        await asyncio.sleep(0.02)
        try:
            return await real(*args, **more)
        finally:
            inside["now"] -= 1

    monkeypatch.setattr(github_login, "call", slow)

    async def clicks(entries: list[str]) -> None:
        with db_session() as db:
            user = db.scalar(select(User).where(User.username == "admin"))
            assert user is not None
            await asyncio.gather(*(thumbs.put(db, user, found.by_id[one], REPO, True) for one in entries))

    thumbs.forget()
    asyncio.run(clicks([ENTRY, ENTRY]))
    assert inside["most"] == 1, "the same entry, the same administrator: one at a time"
    inside["most"] = 0
    thumbs.forget()
    asyncio.run(clicks([ENTRY, "4242/other-card"]))
    assert inside["most"] == 2, "another entry does not wait"
