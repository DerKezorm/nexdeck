"""The app catalog (issue #37): an app set up once, placed as a tile on any board,
with several addresses and one picked for home or for the road."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import HealthCheck, Widget
from app.services.health import service_target

from .conftest import CSRF, create_user, login, setup_admin

HOME = "192.168.1.0/24"
TABLET = ("192.168.1.20", 50000)
OUTSIDE = ("203.0.113.9", 50000)
PAPERLESS = {
    "name": "Paperless",
    "icon": "paperless-ngx",
    "description": "Documents",
    "addresses": [
        {"label": "Proxy", "url": "https://paperless.home.example"},
        {"label": "Tailscale", "url": "https://paperless.tailnet.example"},
        {"label": "Direct", "url": "http://192.168.1.5:8000"},
    ],
    "home": "Direct",
    "away": "Tailscale",
}


def _app(client: TestClient, **changes: object) -> dict:
    answer = client.post("/api/v1/apps", json={**PAPERLESS, **changes}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _page(client: TestClient, name: str = "Desk") -> tuple[str, int]:
    answer = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    board = answer.json()
    return board["slug"], board["pages"][0]["id"]


def _tile(client: TestClient, page_id: int, **options: object) -> dict:
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.app", "options": options}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()["widget"]


def _shown(client: TestClient, slug: str, widget_id: int) -> dict:
    board = client.get(f"/api/v1/boards/{slug}").json()
    return next(widget for page in board["pages"] for widget in page["widgets"] if widget["id"] == widget_id)


def _browser(client: TestClient, where: tuple[str, int]) -> TestClient:
    return TestClient(client.app, client=where, cookies=client.cookies)


# -- the catalog ------------------------------------------------------------------


def test_an_app_is_kept_with_its_addresses(client: TestClient) -> None:
    setup_admin(client)
    made = _app(client)
    assert made["addresses"][1] == {"label": "Tailscale", "url": "https://paperless.tailnet.example"}
    assert (made["home"], made["away"], made["tiles"]) == ("Direct", "Tailscale", 0)
    assert [app["name"] for app in client.get("/api/v1/apps").json()] == ["Paperless"]


def test_what_an_app_cannot_be(client: TestClient) -> None:
    setup_admin(client)
    _app(client)
    refused = {
        "a second one of the same name": {**PAPERLESS},
        "no address": {**PAPERLESS, "name": "A", "addresses": []},
        "a script for a link": {**PAPERLESS, "name": "B", "addresses": [{"label": "X", "url": "javascript:alert(1)"}], "home": "", "away": ""},
        "a label twice": {**PAPERLESS, "name": "C", "addresses": [{"label": "X", "url": "https://a.example"}, {"label": "x", "url": "https://b.example"}], "home": "", "away": ""},
        "the automatic choice as a label": {**PAPERLESS, "name": "D", "addresses": [{"label": "auto", "url": "https://a.example"}], "home": "", "away": ""},
        "home naming no address": {**PAPERLESS, "name": "E", "home": "Kitchen"},
    }
    for why, body in refused.items():
        answer = client.post("/api/v1/apps", json=body, headers=CSRF)
        assert answer.status_code in (400, 409, 422), why


def test_members_may_read_the_catalog_and_not_change_it(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    create_user(client, "anna")
    login(client, "anna", "another-long-password")
    assert [one["name"] for one in client.get("/api/v1/apps").json()] == ["Paperless"]
    assert client.post("/api/v1/apps", json={**PAPERLESS, "name": "Mine"}, headers=CSRF).status_code == 403
    assert client.patch(f"/api/v1/apps/{app['id']}", json={"name": "Hers"}, headers=CSRF).status_code == 403
    assert client.delete(f"/api/v1/apps/{app['id']}", headers=CSRF).status_code == 403


# -- a tile that follows an app ----------------------------------------------------


def test_a_tile_takes_name_icon_and_address_from_its_app(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    tile = _tile(client, page_id, app_id=app["id"], address="Proxy")
    # No name of its own, so the app's, not "App tile".
    assert tile["own_title"] == "" and tile["title"] == "Paperless"
    shown = _shown(client, slug, tile["id"])
    assert shown["service_link"] == "https://paperless.home.example"
    assert shown["app"]["name"] == "Paperless" and shown["app"]["icon"] == "paperless-ngx"
    assert shown["app"]["addresses"] == ["Proxy", "Tailscale", "Direct"]


def test_changing_the_app_once_changes_every_tile(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    first, first_page = _page(client, "Anna")
    second, second_page = _page(client, "Ben")
    tiles = [(first, _tile(client, first_page, app_id=app["id"], address="Proxy")),
             (second, _tile(client, second_page, app_id=app["id"], address="Proxy"))]
    moved = [{**PAPERLESS["addresses"][0], "url": "https://docs.home.example"}, *PAPERLESS["addresses"][1:]]
    assert client.patch(f"/api/v1/apps/{app['id']}", json={"addresses": moved}, headers=CSRF).status_code == 200
    for slug, tile in tiles:
        assert _shown(client, slug, tile["id"])["service_link"] == "https://docs.home.example"


def test_automatic_opens_the_home_address_at_home_and_the_other_one_elsewhere(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    tile = _tile(client, page_id, app_id=app["id"], address="auto")
    # No home networks named: nexdeck cannot tell, and the outside address works from anywhere.
    assert _shown(client, slug, tile["id"])["service_link"] == "https://paperless.tailnet.example"
    # The networks are kept without switching the sign-in without a password on.
    answer = client.put("/api/v1/settings/home-network", json={"enabled": False, "networks": [HOME], "user_id": None}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert _shown(_browser(client, TABLET), slug, tile["id"])["service_link"] == "http://192.168.1.5:8000"
    assert _shown(_browser(client, OUTSIDE), slug, tile["id"])["service_link"] == "https://paperless.tailnet.example"


def test_a_fixed_address_stays_where_it_is(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    client.put("/api/v1/settings/home-network", json={"enabled": False, "networks": [HOME], "user_id": None}, headers=CSRF)
    tile = _tile(client, page_id, app_id=app["id"], address="Proxy")
    for where in (TABLET, OUTSIDE):
        assert _shown(_browser(client, where), slug, tile["id"])["service_link"] == "https://paperless.home.example"


def test_a_tile_cannot_follow_an_app_that_does_not_exist(client: TestClient) -> None:
    setup_admin(client)
    _slug, page_id = _page(client)
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.app", "options": {"app_id": 999}}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "unknown_app"


def test_the_check_follows_the_app_on_its_home_address(client: TestClient) -> None:
    """nexdeck runs at home, so an automatic tile is checked where home reaches it."""
    setup_admin(client)
    app = _app(client)
    _slug, page_id = _page(client)
    tile = _tile(client, page_id, app_id=app["id"], address="auto")
    fixed = _tile(client, page_id, app_id=app["id"], address="Proxy")
    with db_session() as db:
        for widget_id, wanted in ((tile["id"], "http://192.168.1.5:8000"), (fixed["id"], "https://paperless.home.example")):
            check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == widget_id))
            assert check is not None and check.target == "", "a check without a target follows the app on every round"
            assert service_target("http", db.get(Widget, widget_id), db) == wanted


def test_a_label_that_went_away_is_dropped_from_tiles_and_from_home(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    tile = _tile(client, page_id, app_id=app["id"], address="Direct")
    kept = PAPERLESS["addresses"][:2]
    answer = client.patch(f"/api/v1/apps/{app['id']}", json={"addresses": kept}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["home"] == "" and answer.json()["away"] == "Tailscale"
    shown = _shown(client, slug, tile["id"])
    assert shown["options"]["address"] == ""
    assert shown["service_link"] == "https://paperless.tailnet.example", "away is still named, so it is the automatic choice"


def test_deleting_an_app_leaves_its_tiles_standing_on_their_own(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    tile = _tile(client, page_id, app_id=app["id"], address="Proxy")
    answer = client.delete(f"/api/v1/apps/{app['id']}", headers=CSRF)
    assert answer.status_code == 200 and answer.json() == {"tiles_kept": 1}
    shown = _shown(client, slug, tile["id"])
    assert (shown["title"], shown["icon"], shown["link"]) == ("Paperless", "paperless-ngx", "https://paperless.home.example")
    assert shown["app"] is None and "app_id" not in shown["options"]
    with db_session() as db:
        check = db.scalar(select(HealthCheck).where(HealthCheck.widget_id == tile["id"]))
        assert check is not None and check.target == "https://paperless.home.example"


# -- export and import -------------------------------------------------------------


def test_an_export_names_the_app_and_carries_it_along(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    _tile(client, page_id, app_id=app["id"], address="auto")
    document = yaml.safe_load(client.get(f"/api/v1/boards/{slug}/export").text)
    options = document["pages"][0]["widgets"][0]["options"]
    assert options["app"] == "Paperless" and "app_id" not in options and options["address"] == "auto"
    assert document["apps"][0]["name"] == "Paperless" and document["apps"][0]["away"] == "Tailscale"
    assert "id" not in document["apps"][0]


def test_an_import_follows_an_app_of_the_same_name(client: TestClient) -> None:
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    _tile(client, page_id, app_id=app["id"], address="Proxy")
    text = client.get(f"/api/v1/boards/{slug}/export").text
    imported = client.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF)
    assert imported.status_code in (200, 201), imported.text
    widget = imported.json()["pages"][0]["widgets"][0]
    assert widget["options"]["app_id"] == app["id"] and widget["own_title"] == "" and widget["title"] == "Paperless"
    assert widget["service_link"] == "https://paperless.home.example"


def test_an_import_without_the_app_makes_a_tile_of_its_own(client: TestClient) -> None:
    """Over HTTP an import creates no app, as it creates no connection; the
    tile keeps the name, icon and address the file gives it."""
    setup_admin(client)
    app = _app(client)
    slug, page_id = _page(client)
    _tile(client, page_id, app_id=app["id"], address="auto")
    text = client.get(f"/api/v1/boards/{slug}/export").text
    client.delete(f"/api/v1/apps/{app['id']}", headers=CSRF)
    imported = client.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF)
    assert imported.status_code in (200, 201), imported.text
    widget = imported.json()["pages"][0]["widgets"][0]
    assert (widget["title"], widget["icon"], widget["link"]) == ("Paperless", "paperless-ngx", "https://paperless.tailnet.example")
    assert "app" not in widget["options"] and "app_id" not in widget["options"]
    assert client.get("/api/v1/apps").json() == []
