"""The one call nexdeck makes to the outside, and who may make it.

⚠️ Nothing tested any of this. The switch is off by default, and the promise
attached to it is a privacy promise: an installation that was never told to
look outside does not look outside. A test that only checked the button would
have let that promise break silently.

The other half is the button, which was refused while the switch was off. So
the administrator who deliberately keeps the daily call off, the one most
likely to want to look now and then, was the only one who could not.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.routers import system

from .conftest import CSRF, create_user, login, setup_admin

GITHUB = "https://api.github.com/repos/DerKezorm/nexdeck/releases/latest"


@pytest.fixture(autouse=True)
def forget_what_was_asked() -> None:
    """The answer is cached for six hours in a module global, so one test
    would otherwise answer the next one's question."""
    system._update_cache.clear()


def test_pressing_the_button_works_while_the_daily_check_is_off(client: TestClient) -> None:
    setup_admin(client)
    assert client.get("/api/v1/about").json()["update_check"] is False

    with respx.mock:
        asked = respx.get(GITHUB).mock(return_value=httpx.Response(200, json={"tag_name": "v9.9.9"}))
        answer = client.post("/api/v1/about/check", headers=CSRF)

    assert answer.status_code == 200, answer.text
    assert asked.called, "the button did not ask GitHub anything"
    assert answer.json()["latest_version"] == "9.9.9"


def test_the_answer_stays_visible_afterwards(client: TestClient) -> None:
    """⚠️ The About page filled in the version only while the switch was on,
    so with it off the page went back to "never checked" right after a
    successful press, and the press looked like it had failed."""
    setup_admin(client)
    with respx.mock:
        respx.get(GITHUB).mock(return_value=httpx.Response(200, json={"tag_name": "v9.9.9"}))
        client.post("/api/v1/about/check", headers=CSRF)

    # No mock at all now: an outbound call here would fail the test by trying
    # to reach the real internet, which the outbound guard forbids in tests.
    later = client.get("/api/v1/about").json()
    assert later["latest_version"] == "9.9.9"
    assert later["checked_at"]


def test_the_page_asks_nobody_while_the_switch_is_off(client: TestClient) -> None:
    """The promise behind the default. Opening the About page must not reach
    out, or the switch would mean nothing."""
    setup_admin(client)
    with respx.mock:
        asked = respx.get(GITHUB).mock(return_value=httpx.Response(200, json={"tag_name": "v9.9.9"}))
        client.get("/api/v1/about")
        assert not asked.called, "opening the About page called GitHub with the check switched off"


def test_the_page_asks_once_the_switch_is_on(client: TestClient) -> None:
    setup_admin(client)
    client.patch("/api/v1/settings", json={"update_check": True}, headers=CSRF)
    with respx.mock:
        asked = respx.get(GITHUB).mock(return_value=httpx.Response(200, json={"tag_name": "v9.9.9"}))
        page = client.get("/api/v1/about")
        assert asked.called, "the switch is on and nothing was asked"
    assert page.json()["latest_version"] == "9.9.9"


def test_only_an_administrator_may_press_it(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    with respx.mock:
        asked = respx.get(GITHUB).mock(return_value=httpx.Response(200, json={"tag_name": "v9.9.9"}))
        refused = kim.post("/api/v1/about/check", headers=CSRF)
        assert not asked.called, "a member's press reached GitHub"
    assert refused.status_code == 403, refused.text


def test_a_member_is_not_told_which_version_is_out(client: TestClient) -> None:
    """The About page is readable by everyone; the version outside is an
    administrator's business, and asking for it is their call."""
    setup_admin(client)
    with respx.mock:
        respx.get(GITHUB).mock(return_value=httpx.Response(200, json={"tag_name": "v9.9.9"}))
        client.post("/api/v1/about/check", headers=CSRF)

    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    assert kim.get("/api/v1/about").json()["latest_version"] is None


def test_github_being_unreachable_is_not_a_failed_request(client: TestClient) -> None:
    """⚠️ The button answers 200 with nothing found, rather than an error the
    browser has to interpret. GitHub being down is not this installation's
    fault and not something an operator can act on."""
    setup_admin(client)
    with respx.mock:
        respx.get(GITHUB).mock(side_effect=httpx.ConnectError("no route"))
        answer = client.post("/api/v1/about/check", headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["latest_version"] is None
    # It did try, and says when.
    assert answer.json()["checked_at"]
