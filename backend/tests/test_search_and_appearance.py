"""The bar that leaves the house, and the look of the installation.

Both are one setting each, both are read by everybody and written by the
administrator alone. What is tested here is the line between those two, and
the checks that keep a bad address or a style sheet with a hole in it out.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import appearance, search

from .conftest import CSRF, create_user, login, setup_admin


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    setup_admin(client)
    return client


@pytest.fixture
def user_client(client: TestClient) -> TestClient:
    """A plain account, signed in, beside the administrator's own session."""
    setup_admin(client)
    create_user(client, "kim")
    plain = TestClient(client.app)
    login(plain, "kim", "another-long-password")
    return plain


# -- who may read and who may write --------------------------------------------


def test_everyone_signed_in_reads_the_search_targets(user_client: TestClient) -> None:
    """The bar needs them on every page, so a plain account may read them."""
    answer = user_client.get("/api/v1/settings/search")
    assert answer.status_code == 200
    assert answer.json()["enabled"] is True
    assert [target["name"] for target in answer.json()["targets"]][:1] == ["DuckDuckGo"]


def test_only_an_administrator_changes_them(user_client: TestClient) -> None:
    answer = user_client.put("/api/v1/settings/search", headers=CSRF, json={"enabled": False, "targets": []})
    assert answer.status_code == 403


def test_a_signed_out_browser_reads_nothing(client: TestClient) -> None:
    assert client.get("/api/v1/settings/search").status_code == 401
    assert client.get("/api/v1/settings/appearance").status_code == 401


def test_suggestions_are_for_the_administrator_alone(user_client: TestClient) -> None:
    assert user_client.get("/api/v1/settings/search/suggestions").status_code == 403


# -- the search targets --------------------------------------------------------


def test_a_target_is_stored_and_comes_back(admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/search", headers=CSRF, json={
        "enabled": True,
        "targets": [{"name": "Wiki", "url": "https://en.wikipedia.org/w/index.php?search={query}", "prefix": "w", "icon": "wikipedia"}],
    })
    assert answer.status_code == 200
    assert answer.json()["targets"] == [{"name": "Wiki", "url": "https://en.wikipedia.org/w/index.php?search={query}", "prefix": "w", "icon": "wikipedia"}]
    assert admin_client.get("/api/v1/settings/search").json()["targets"][0]["name"] == "Wiki"


def test_an_address_without_the_placeholder_is_refused(admin_client: TestClient) -> None:
    """Without {query} the target would open the same page for every word."""
    answer = admin_client.put("/api/v1/settings/search", headers=CSRF, json={
        "enabled": True, "targets": [{"name": "Nowhere", "url": "https://example.com/", "prefix": "", "icon": ""}],
    })
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "missing_query"


def test_an_address_that_is_not_a_web_address_is_refused(admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/search", headers=CSRF, json={
        "enabled": True, "targets": [{"name": "Bad", "url": "javascript:alert({query})", "prefix": "", "icon": ""}],
    })
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "bad_url"


def test_the_same_shortcut_twice_is_refused(admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/search", headers=CSRF, json={"enabled": True, "targets": [
        {"name": "One", "url": "https://a.example.com/?q={query}", "prefix": "a", "icon": ""},
        {"name": "Two", "url": "https://b.example.com/?q={query}", "prefix": "a", "icon": ""},
    ]})
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "duplicate_prefix"


def test_two_targets_may_both_have_no_shortcut(admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/search", headers=CSRF, json={"enabled": True, "targets": [
        {"name": "One", "url": "https://a.example.com/?q={query}", "prefix": "", "icon": ""},
        {"name": "Two", "url": "https://b.example.com/?q={query}", "prefix": "", "icon": ""},
    ]})
    assert answer.status_code == 200, "no shortcut is not a shortcut that clashes"


def test_suggestions_come_out_of_the_connected_services(admin_client: TestClient) -> None:
    made = admin_client.post("/api/v1/integrations", headers=CSRF, json={
        "kind": "radarr", "name": "Radarr", "config": {"url": "https://radarr.example.com/", "api_key": "k"},
        "enabled": True, "demo": False,
    })
    assert made.status_code in (200, 201)
    targets = admin_client.get("/api/v1/settings/search/suggestions").json()["targets"]
    assert any(target["url"] == "https://radarr.example.com/add/new?term={query}" for target in targets)
    admin_client.delete(f"/api/v1/integrations/{made.json()['id']}", headers=CSRF)


def test_a_demo_service_is_not_suggested(admin_client: TestClient) -> None:
    """A demo connection has no address worth opening."""
    made = admin_client.post("/api/v1/integrations", headers=CSRF, json={"kind": "radarr", "name": "Demo", "config": {}, "enabled": True, "demo": True})
    targets = admin_client.get("/api/v1/settings/search/suggestions").json()["targets"]
    assert targets == []
    admin_client.delete(f"/api/v1/integrations/{made.json()['id']}", headers=CSRF)


# -- the look ------------------------------------------------------------------


def test_the_accent_is_the_preset_until_a_colour_of_ones_own_is_set() -> None:
    assert appearance.colour_of({"preset": "cyan", "accent": ""}) == "#22d3ee"
    assert appearance.colour_of({"preset": "amber", "accent": ""}) == "#fbbf24"
    assert appearance.colour_of({"preset": "cyan", "accent": "#FF00AA"}) == "#ff00aa"
    # Something that is not a colour falls back rather than reaching the page.
    assert appearance.colour_of({"preset": "cyan", "accent": "red"}) == "#22d3ee"


def test_the_look_is_stored_and_read_back(admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={"preset": "violet", "accent": "", "css": ".card { border-radius: 4px; }"})
    assert answer.status_code == 200
    assert answer.json()["colour"] == "#a78bfa"
    assert admin_client.get("/api/v1/settings/appearance").json()["css"] == ".card { border-radius: 4px; }"


def test_a_colour_that_is_not_one_is_refused(admin_client: TestClient) -> None:
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={"preset": "cyan", "accent": "rgb(1,2,3)", "css": ""})
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "bad_colour"


@pytest.mark.parametrize("css", [
    "</style><script>fetch('https://evil.example.com')</script>",
    "</STYLE ><script>x</script>",
    "@import url('https://evil.example.com/theme.css');",
    "@IMPORT 'https://evil.example.com/theme.css';",
    ".a { background: url(javascript:alert(1)); }",
    ".a { width: expression(alert(1)); }",
])
def test_a_style_sheet_that_reaches_out_is_refused(css: str, admin_client: TestClient) -> None:
    """CSS runs no code, but @import fetches, and a closed tag is a hole. The
    sheet is written by one administrator and shown to everybody."""
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={"preset": "cyan", "accent": "", "css": css})
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "css_refused"


def test_an_ordinary_style_sheet_is_kept(admin_client: TestClient) -> None:
    css = ".card { border-radius: 4px; }\n.dot { box-shadow: none; }\n/* a comment about style */"
    answer = admin_client.put("/api/v1/settings/appearance", headers=CSRF, json={"preset": "cyan", "accent": "", "css": css})
    assert answer.status_code == 200 and answer.json()["css"] == css


def test_a_style_sheet_longer_than_the_cap_is_refused() -> None:
    with pytest.raises(appearance.AppearanceError) as refused:
        appearance.check_css("a{}" * 10_000)
    assert refused.value.code == "css_too_long"


def test_only_an_administrator_changes_the_look(user_client: TestClient) -> None:
    assert user_client.put("/api/v1/settings/appearance", headers=CSRF, json={"preset": "rose", "accent": "", "css": ""}).status_code == 403


def test_the_search_url_puts_the_words_in_safely() -> None:
    target = {"url": "https://example.com/?q={query}"}
    assert search.build(target, "dune part two&x=1") == "https://example.com/?q=dune%20part%20two%26x%3D1"
