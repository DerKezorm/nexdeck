"""Whose boards the list shows, what stands in the menu, and locked connections."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str) -> dict:
    response = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _names(client: TestClient, all_boards: bool = False) -> list[str]:
    query = "?all_boards=true" if all_boards else ""
    return [board["name"] for board in client.get(f"/api/v1/boards{query}").json()]


def test_the_list_holds_my_boards_and_the_ones_shared_with_me(client: TestClient) -> None:
    """An administrator may open everything, which is not the same as owning it.

    Ten colleagues with boards used to fill his list and his menu; now he asks
    for that on purpose.
    """
    setup_admin(client)
    create_user(client, "kim")
    create_user(client, "robin")
    _board(client, "Mine")

    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    kims = _board(kim, "Kim's lab")
    shared = _board(kim, "Shared with the boss")

    robin = TestClient(client.app)
    login(robin, "robin", "another-long-password")
    _board(robin, "Robin's corner")

    # "Home" is the board the wizard leaves behind, and it belongs to the administrator.
    assert sorted(_names(client)) == ["Home", "Mine"], "somebody else's board is not the administrator's business by default"
    assert sorted(_names(client, all_boards=True)) == ["Home", "Kim's lab", "Mine", "Robin's corner", "Shared with the boss"]

    # A share puts a board in the list of the person it was shared with.
    admin_id = client.get("/api/v1/auth/me").json()["id"]
    kim.put(f"/api/v1/boards/{shared['slug']}/shares", json={"shares": [{"user_id": admin_id, "level": "view"}]}, headers=CSRF)
    assert sorted(_names(client)) == ["Home", "Mine", "Shared with the boss"]

    # Kim sees her own two and nothing of Robin's.
    assert sorted(_names(kim)) == ["Kim's lab", "Shared with the boss"]
    assert _names(robin) == ["Robin's corner"]
    assert kims["name"] not in _names(robin)


def test_a_board_can_stay_out_of_the_menu(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Rarely")
    assert board["in_menu"] is True, "a new board is in the menu"

    changed = client.patch(f"/api/v1/boards/{board['slug']}", json={"in_menu": False}, headers=CSRF)
    assert changed.status_code == 200
    listed = next(entry for entry in client.get("/api/v1/boards").json() if entry["id"] == board["id"])
    assert listed["in_menu"] is False
    assert listed["name"] in _names(client), "out of the menu is not out of the list"
    assert client.get(f"/api/v1/boards/{board['slug']}").status_code == 200, "and the address still works"


def test_a_locked_connection_is_the_administrators_alone(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    locked = client.post(
        "/api/v1/integrations",
        json={"kind": "radarr", "name": "Radarr", "config": {"url": "http://radarr:7878", "api_key": "secret"}, "admin_only": True},
        headers=CSRF,
    )
    assert locked.status_code == 201, locked.text
    integration_id = locked.json()["id"]
    assert locked.json()["admin_only"] is True

    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    board = _board(kim, "Kim's lab")
    page_id = board["pages"][0]["id"]

    # Not in her list at all.
    assert [entry["name"] for entry in kim.get("/api/v1/integrations").json()] == []
    assert [entry["name"] for entry in client.get("/api/v1/integrations").json()] == ["Radarr"]

    # And not to be built on.
    refused = kim.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "radarr.queue", "integration_id": integration_id}, headers=CSRF)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "integration_locked"

    # The administrator builds with it and shares the board; her card runs.
    admin_board = _board(client, "Operations")
    admin_page = admin_board["pages"][0]["id"]
    created = client.post(f"/api/v1/pages/{admin_page}/widgets", json={"kind": "radarr.queue", "integration_id": integration_id}, headers=CSRF)
    assert created.status_code == 201, created.text
    kim_id = next(user["id"] for user in client.get("/api/v1/users").json() if user["username"] == "kim")
    client.put(f"/api/v1/boards/{admin_board['slug']}/shares", json={"shares": [{"user_id": kim_id, "level": "view"}]}, headers=CSRF)
    seen = kim.get(f"/api/v1/boards/{admin_board['slug']}")
    assert seen.status_code == 200
    assert [widget["kind"] for widget in seen.json()["pages"][0]["widgets"]] == ["radarr.queue"]


def test_unlocking_gives_the_connection_back(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    integration = client.post(
        "/api/v1/integrations",
        json={"kind": "radarr", "name": "Radarr", "config": {"url": "http://radarr:7878", "api_key": "secret"}, "admin_only": True},
        headers=CSRF,
    ).json()

    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    assert kim.get("/api/v1/integrations").json() == []

    client.patch(f"/api/v1/integrations/{integration['id']}", json={"admin_only": False}, headers=CSRF)
    assert [entry["name"] for entry in kim.get("/api/v1/integrations").json()] == ["Radarr"]
    board = _board(kim, "Kim's lab")
    built = kim.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "radarr.queue", "integration_id": integration["id"]}, headers=CSRF)
    assert built.status_code == 201
