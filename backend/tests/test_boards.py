"""Boards, pages, widgets, layouts, permissions, kiosk, export and import."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str = "Lab") -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _widget(client: TestClient, page_id: int, kind: str = "core.clock", **extra: object) -> dict:
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": kind, **extra}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()["widget"]


def test_board_pages_widgets_and_layouts(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page = board["pages"][0]
    widget = _widget(client, page["id"], title="Clock")
    assert widget["renderer"] == "clock"
    view = client.get(f"/api/v1/boards/{board['slug']}").json()
    layout = view["pages"][0]["layouts"]["lg"]
    assert [item["i"] for item in layout] == [str(widget["id"])]
    # Layouts are saved per breakpoint and unknown widgets are dropped.
    response = client.put(f"/api/v1/pages/{page['id']}/layouts", json={"lg": [{"i": str(widget["id"]), "x": 3, "y": 0, "w": 4, "h": 2}, {"i": "999", "x": 0, "y": 0, "w": 1, "h": 1}]}, headers=CSRF)
    assert response.status_code == 200
    assert response.json()["layouts"]["lg"] == [{"i": str(widget["id"]), "x": 3, "y": 0, "w": 4, "h": 2}]
    # Removing the widget removes its layout entry.
    assert client.delete(f"/api/v1/widgets/{widget['id']}", headers=CSRF).status_code == 204
    view = client.get(f"/api/v1/boards/{board['slug']}").json()
    assert view["pages"][0]["layouts"]["lg"] == []
    # The last page cannot be deleted.
    assert client.delete(f"/api/v1/pages/{page['id']}", headers=CSRF).status_code == 409


def test_unknown_widget_kind_and_mismatched_integration(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page_id = board["pages"][0]["id"]
    assert client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "nope.nothing"}, headers=CSRF).status_code == 400
    integration = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "R", "config": {"url": "http://r", "api_key": "k"}}, headers=CSRF).json()
    response = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "sonarr.queue", "integration_id": integration["id"]}, headers=CSRF)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "kind_mismatch"


def test_other_users_need_a_share(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Private")
    create_user(client, "sam")
    sam = TestClient(client.app)
    login(sam, "sam", "another-long-password")
    assert sam.get(f"/api/v1/boards/{board['slug']}").status_code == 403
    assert board["slug"] not in [b["slug"] for b in sam.get("/api/v1/boards").json()]
    # View share: may open, may not edit or act.
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"role": "user", "level": "view"}]}, headers=CSRF)
    opened = sam.get(f"/api/v1/boards/{board['slug']}")
    assert opened.status_code == 200
    assert opened.json()["permission"] == "view"
    assert sam.patch(f"/api/v1/boards/{board['slug']}", json={"name": "Hacked"}, headers=CSRF).status_code == 403
    widget = _widget(client, board["pages"][0]["id"], kind="core.markdown")
    assert sam.post(f"/api/v1/widgets/{widget['id']}/actions/anything", json={"params": {}}, headers=CSRF).status_code == 403
    # Act share: the levels are cumulative, so acting includes editing.
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": sam.get("/api/v1/auth/me").json()["id"], "level": "act"}]}, headers=CSRF)
    assert sam.get(f"/api/v1/boards/{board['slug']}").json()["permission"] == "act"
    assert sam.patch(f"/api/v1/boards/{board['slug']}", json={"name": "Renamed by Sam"}, headers=CSRF).status_code == 200
    assert sam.post(f"/api/v1/widgets/{widget['id']}/actions/anything", json={"params": {}}, headers=CSRF).status_code == 400, "acting is allowed; the action itself does not exist"
    # Only the owner deletes.
    assert sam.delete(f"/api/v1/boards/{board['slug']}", headers=CSRF).status_code == 403


def test_kiosk_token_opens_exactly_its_board(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Wall")
    other = _board(client, "Other")
    created = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "hall", "cycle_seconds": 30}, headers=CSRF).json()
    token = created["token"]
    assert token.startswith("nk_") and created["url"] == f"/k/{token}"
    display = TestClient(client.app)
    assert display.get("/api/v1/kiosk").status_code == 401
    view = display.get("/api/v1/kiosk", headers={"X-Kiosk-Token": token})
    assert view.status_code == 200
    assert view.json()["slug"] == board["slug"]
    assert view.json()["kiosk"]["cycle_seconds"] == 30
    assert view.json()["permission"] == "view"
    assert display.get(f"/api/v1/boards/{other['slug']}", headers={"X-Kiosk-Token": token}).status_code == 403
    # Without allow_actions, actions are refused; the token never reaches other addresses.
    widget = _widget(client, board["pages"][0]["id"], kind="core.markdown")
    assert display.post(f"/api/v1/widgets/{widget['id']}/actions/x", json={"params": {}}, headers={"X-Kiosk-Token": token}).status_code == 403
    assert display.get("/api/v1/boards", headers={"X-Kiosk-Token": token}).status_code == 401
    # Revoked tokens are gone.
    client.delete(f"/api/v1/kiosk-tokens/{created['id']}", headers=CSRF)
    assert display.get("/api/v1/kiosk", headers={"X-Kiosk-Token": token}).status_code == 401


def test_export_and_import_roundtrip(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Media")
    page_id = board["pages"][0]["id"]
    integration = client.post("/api/v1/integrations", json={"kind": "radarr", "name": "Movies", "config": {"url": "http://radarr:7878", "api_key": "secret-key"}}, headers=CSRF).json()
    _widget(client, page_id, kind="radarr.queue", integration_id=integration["id"], title="Queue")
    _widget(client, page_id, kind="core.markdown", title="Notes", options={"content": "hello"})
    exported = client.get(f"/api/v1/boards/{board['slug']}/export")
    assert exported.status_code == 200
    text = exported.text
    assert "secret-key" not in text, "secrets never leave in a board file"
    assert "${NEXDECK_RADARR_" in text
    assert "radarr.queue" in text and "core.markdown" in text
    imported = client.post("/api/v1/boards/import", json={"yaml_text": text, "slug": "media-copy"}, headers=CSRF)
    assert imported.status_code == 201, imported.text
    copy = imported.json()
    assert copy["slug"] == "media-copy"
    kinds = sorted(w["kind"] for w in copy["pages"][0]["widgets"])
    assert kinds == ["core.markdown", "radarr.queue"]
    queue = next(w for w in copy["pages"][0]["widgets"] if w["kind"] == "radarr.queue")
    assert queue["integration_id"] == integration["id"], "integrations are matched by name, not duplicated"
    assert client.post("/api/v1/boards/import", json={"yaml_text": "not: [valid"}, headers=CSRF).status_code == 400


def test_history_endpoint_lists_metrics_of_live_widgets(client: TestClient) -> None:
    setup_admin(client, demo=True)
    board = client.get("/api/v1/boards").json()[0]
    response = client.get(f"/api/v1/boards/{board['slug']}/history")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_widget_preview_shows_draft_options_without_saving(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    page = board["pages"][0]
    widget = _widget(client, page["id"], options={"seconds": False})
    response = client.post(f"/api/v1/widgets/{widget['id']}/preview", json={"options": {"seconds": True, "label": "Draft"}}, headers=CSRF)
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["seconds"] is True
    assert response.json()["meta"]["label"] == "Draft"
    # Nothing was saved: the stored widget still has the old options.
    view = client.get(f"/api/v1/boards/{board['slug']}").json()
    assert view["pages"][0]["widgets"][0]["options"] == {"seconds": False}
    assert view["pages"][0]["widgets"][0]["client_only"] is True
    assert view["pages"][0]["widgets"][0]["default_size"] == [3, 2]


def test_widget_preview_needs_edit_permission(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client)
    widget = _widget(client, board["pages"][0]["id"])
    create_user(client, "viewer")
    shared = client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "view"}]}, headers=CSRF)
    assert shared.status_code in (200, 204), shared.text
    viewer = TestClient(client.app)
    login(viewer, "viewer", "another-long-password")
    assert viewer.get(f"/api/v1/boards/{board['slug']}").status_code == 200
    assert viewer.post(f"/api/v1/widgets/{widget['id']}/preview", json={"options": {}}, headers=CSRF).status_code == 403


def test_migration_gives_old_nexview_widgets_the_logo(client: TestClient) -> None:
    from sqlalchemy import text

    from app.db import get_engine
    from app.migrations import MIGRATIONS, schema_version

    setup_admin(client)
    board = _board(client)
    integration = client.post("/api/v1/integrations", json={"kind": "nexview", "name": "N", "config": {"url": "http://n", "api_key": "k"}}, headers=CSRF).json()
    widget = _widget(client, board["pages"][0]["id"], kind="nexview.requests", integration_id=integration["id"], icon="lucide:clapperboard")
    other = _widget(client, board["pages"][0]["id"], kind="core.clock", icon="lucide:clapperboard")
    assert schema_version() >= 2
    step = {version: function for version, _description, function in MIGRATIONS}[2]
    with get_engine().begin() as connection:
        step(connection)
        icons = dict(connection.execute(text("SELECT id, icon FROM widgets")).all())
    assert icons[widget["id"]] == "nexview"
    assert icons[other["id"]] == "lucide:clapperboard", "only Nexview widgets change"


async def test_problems_widget_lists_the_yellow_and_red_cards_of_its_board(client: TestClient) -> None:
    import httpx

    from app.adapters import get_adapter
    from app.adapters.base import Context, WidgetData
    from app.services.state import live

    setup_admin(client)
    board = _board(client)
    page_id = board["pages"][0]["id"]
    second = client.post(f"/api/v1/boards/{board['slug']}/pages", json={"name": "Media"}, headers=CSRF).json()
    unifi = _widget(client, page_id, title="UniFi Network")
    radarr = _widget(client, second["pages"][-1]["id"] if "pages" in second else second["id"], title="Radarr")
    fine = _widget(client, page_id, title="Clock")
    problems = _widget(client, page_id, kind="core.problems", title="Problems")
    live.set(unifi["id"], WidgetData(status="warn", meta={"status_reason": "3 device(s) offline"}))
    live.set(radarr["id"], WidgetData(status="unknown", error="The service could not be reached.", meta={"code": "unreachable"}))
    live.set(fine["id"], WidgetData(status="ok"))
    ctx = Context(httpx.AsyncClient(), widget_id=problems["id"], cache={})
    data = await get_adapter("core").fetch("problems", {}, {}, ctx)
    assert data.status == "bad"
    assert [(item["title"], item["status"], item["subtitle"], item["value"]) for item in data.items] == [
        ("Radarr", "bad", "The service could not be reached.", "Media"),
        ("UniFi Network", "warn", "3 device(s) offline", "Overview"),
    ]
    assert data.items[0]["error_code"] == "unreachable"
    live.set(unifi["id"], WidgetData(status="ok"))
    live.set(radarr["id"], WidgetData(status="ok"))
    calm = await get_adapter("core").fetch("problems", {}, {}, ctx)
    assert calm.status == "ok" and calm.items == [] and calm.meta["empty"] == "Everything is fine"


def test_widget_images_come_through_the_server_with_the_service_token(client: TestClient) -> None:
    import respx
    from httpx import Response

    setup_admin(client)
    board = _board(client)
    integration = client.post("/api/v1/integrations", json={"kind": "plex", "name": "P", "config": {"url": "http://plex:32400", "token": "tok"}}, headers=CSRF).json()
    widget = _widget(client, board["pages"][0]["id"], kind="plex.recent", integration_id=integration["id"])
    with respx.mock:
        poster = respx.get("http://plex:32400/library/metadata/10/thumb/1").mock(return_value=Response(200, content=b"\x89PNG...", headers={"content-type": "image/png"}))
        first = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/library/metadata/10/thumb/1"})
        assert first.status_code == 200 and first.headers["content-type"] == "image/png" and first.content.startswith(b"\x89PNG")
        assert poster.calls.last.request.headers["X-Plex-Token"] == "tok", "the token stays between server and service"
        second = client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/library/metadata/10/thumb/1"})
        assert second.status_code == 200 and poster.call_count == 1, "the second request is served from the cache"
        assert client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "http://evil.example.com/x.png"}).status_code == 400
        respx.get("http://plex:32400/login").mock(return_value=Response(200, text="<html>", headers={"content-type": "text/html"}))
        assert client.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/login"}).status_code == 404
    other = TestClient(client.app)
    assert other.get(f"/api/v1/widgets/{widget['id']}/image", params={"path": "/library/metadata/10/thumb/1"}).status_code in (401, 403), "no session, no image"
