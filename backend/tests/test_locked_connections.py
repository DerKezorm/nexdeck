"""A connection reserved for administrators, held against the four ways round it.

Widget options, a query string and a request path all carried a connection
number that nobody checked. Each test here is one of those ways, written as
the attack, so a rewrite that reopens it fails loudly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.jsonapi import join_path

from .conftest import CSRF, create_user, login, setup_admin


def _locked(client: TestClient, kind: str = "docker", name: str = "Locked engine") -> dict:
    """A connection only administrators may build on."""
    answer = client.post("/api/v1/integrations", json={
        "kind": kind, "name": name, "config": {}, "demo": True, "admin_only": True,
    }, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _open(client: TestClient, kind: str, name: str) -> dict:
    answer = client.post("/api/v1/integrations", json={
        "kind": kind, "name": name, "config": {}, "demo": True,
    }, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _member(client: TestClient, username: str = "kim") -> TestClient:
    create_user(client, username)
    other = TestClient(client.app)
    login(other, username, "another-long-password")
    return other


def _own_page(client: TestClient, name: str = "Kim") -> int:
    answer = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return int(answer.json()["pages"][0]["id"])


# ---------------------------------------------------------------------------
# 1. The merged calendar
# ---------------------------------------------------------------------------


def test_a_calendar_source_may_not_name_a_locked_connection(client: TestClient) -> None:
    """The attack: put the number of the boss's Radarr in a widget option.

    ``sources`` never went through a check, and the adapter resolved whatever
    stood in it, so the release calendar of a locked instance was one PATCH
    away.
    """
    setup_admin(client)
    locked = _locked(client, "radarr", "Radarr 4K")
    kim = _member(client)
    page = _own_page(kim)

    made = kim.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Calendar", "options": {"sources": [str(locked["id"])]},
    }, headers=CSRF)
    assert made.status_code == 403, made.text
    assert made.json()["detail"]["code"] == "integration_locked"


def test_a_saved_calendar_cannot_be_pointed_at_a_locked_connection_later(client: TestClient) -> None:
    """Creating it empty and patching it afterwards is the same door."""
    setup_admin(client)
    locked = _locked(client, "sonarr", "Sonarr private")
    kim = _member(client)
    page = _own_page(kim)

    made = kim.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Calendar", "options": {"sources": []},
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    widget_id = made.json().get("id") or made.json()["widget"]["id"]

    later = kim.patch(f"/api/v1/widgets/{widget_id}", json={"options": {"sources": [str(locked["id"])]}}, headers=CSRF)
    assert later.status_code == 403, later.text


def test_the_preview_is_not_the_way_around_the_check(client: TestClient) -> None:
    """A preview reaches the adapter with unsaved options.

    Without its own check the settings sheet would fetch the data and show it,
    and never save anything for anyone to find.
    """
    setup_admin(client)
    locked = _locked(client, "radarr", "Radarr 4K")
    kim = _member(client)
    page = _own_page(kim)
    made = kim.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Calendar", "options": {"sources": []},
    }, headers=CSRF)
    widget_id = made.json().get("id") or made.json()["widget"]["id"]

    peek = kim.post(f"/api/v1/widgets/{widget_id}/preview", json={"options": {"sources": [str(locked["id"])]}}, headers=CSRF)
    assert peek.status_code == 403, peek.text


def test_a_source_of_the_wrong_kind_is_refused(client: TestClient) -> None:
    """Only the kinds the field names may be merged, locked or not."""
    setup_admin(client)
    docker = _open(client, "docker", "Docker")
    page = _own_page(client, "Admin board")

    made = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Calendar", "options": {"sources": [str(docker["id"])]},
    }, headers=CSRF)
    assert made.status_code == 400, made.text
    assert made.json()["detail"]["code"] == "bad_source"


def test_a_source_that_is_not_a_number_is_refused(client: TestClient) -> None:
    """The field used to hold kind names, which the adapter swallowed as failures."""
    setup_admin(client)
    page = _own_page(client, "Admin board")
    made = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Calendar", "options": {"sources": ["radarr"]},
    }, headers=CSRF)
    assert made.status_code == 400, made.text
    assert made.json()["detail"]["code"] == "bad_source"


def test_an_administrator_may_still_merge_a_locked_connection(client: TestClient) -> None:
    """The check must not lock the owner out of his own connection."""
    setup_admin(client)
    locked = _locked(client, "radarr", "Radarr 4K")
    page = _own_page(client, "Admin board")
    made = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Calendar", "options": {"sources": [str(locked["id"])]},
    }, headers=CSRF)
    assert made.status_code == 201, made.text


# ---------------------------------------------------------------------------
# 2. The JSON card
# ---------------------------------------------------------------------------


def test_the_request_path_cannot_leave_the_base_url() -> None:
    """The path is a widget option; the address and the token are not.

    ``http://…`` in the path used to replace the whole address while the
    bearer token was still sent, so the card could be pointed at a server of
    the editor's own.
    """
    base = "https://service.example.com/api"
    assert join_path(base, "/status") == base + "/status"
    assert join_path(base, "status") == base + "/status"
    assert join_path(base, "") == base
    for escape in ("http://elsewhere.example.com/collect", "https://elsewhere.example.com", "//elsewhere.example.com/collect", "\\\\elsewhere.example.com"):
        assert join_path(base, escape).startswith(base + "/"), escape


def test_the_host_of_the_base_url_is_the_only_host_reached() -> None:
    """Whatever the path says, the request goes to the connection's own host."""
    from urllib.parse import urlparse

    base = "https://service.example.com/api"
    for path in ("http://elsewhere.example.com/x", "//elsewhere.example.com/x", "../../../x", "/x"):
        assert urlparse(join_path(base, path)).netloc == "service.example.com", path


# ---------------------------------------------------------------------------
# 3. The Docker discovery
# ---------------------------------------------------------------------------


def test_a_member_cannot_list_the_containers_of_a_locked_engine(client: TestClient) -> None:
    """The number stood in the query string and was loaded without a word."""
    setup_admin(client)
    locked = _locked(client)
    kim = _member(client)

    answer = kim.get(f"/api/v1/discovery/docker?integration_id={locked['id']}")
    assert answer.status_code == 403, answer.text
    assert answer.json()["detail"]["code"] == "integration_locked"


def test_a_member_cannot_turn_a_locked_engine_into_tiles(client: TestClient) -> None:
    """Applying suggestions goes through the same listing, so it is the same hole."""
    setup_admin(client)
    locked = _locked(client)
    kim = _member(client)
    page = _own_page(kim)

    answer = kim.post("/api/v1/discovery/docker/apply", json={
        "page_id": page, "integration_id": locked["id"], "containers": ["radarr"],
    }, headers=CSRF)
    assert answer.status_code == 403, answer.text


def test_an_administrator_still_sees_the_containers(client: TestClient) -> None:
    setup_admin(client)
    locked = _locked(client)
    answer = client.get(f"/api/v1/discovery/docker?integration_id={locked['id']}")
    assert answer.status_code == 200, answer.text
    assert answer.json(), "the demo engine should suggest something"


# ---------------------------------------------------------------------------
# 4. The log card
# ---------------------------------------------------------------------------


def test_reading_a_container_log_needs_more_than_looking(client: TestClient) -> None:
    """A log carries paths and tokens in tracebacks; ``view`` was not enough."""
    setup_admin(client)
    engine = _open(client, "docker", "Docker")
    board = client.post("/api/v1/boards", json={"name": "Ops"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    made = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "docker.logs", "title": "Logs", "integration_id": engine["id"], "options": {"container": "radarr"},
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    widget_id = made.json().get("id") or made.json()["widget"]["id"]

    kim_user = create_user(client, "kim")
    shared = client.put(f"/api/v1/boards/{board['slug']}/shares", json={
        "shares": [{"user_id": kim_user["id"], "level": "view"}],
    }, headers=CSRF)
    assert shared.status_code == 200, shared.text

    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    assert kim.get(f"/api/v1/boards/{board['slug']}").status_code == 200, "kim may look at the board"
    assert kim.get(f"/api/v1/widgets/{widget_id}/logs").status_code == 403
    assert kim.get(f"/api/v1/widgets/{widget_id}/logs/stream").status_code == 403


def test_a_share_that_may_act_reads_the_log(client: TestClient) -> None:
    """The level was raised, not closed off."""
    setup_admin(client)
    engine = _open(client, "docker", "Docker")
    board = client.post("/api/v1/boards", json={"name": "Ops"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    made = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "docker.logs", "title": "Logs", "integration_id": engine["id"], "options": {"container": "radarr"},
    }, headers=CSRF)
    widget_id = made.json().get("id") or made.json()["widget"]["id"]

    sam_user = create_user(client, "sam")
    granted = client.put(f"/api/v1/boards/{board['slug']}/shares", json={
        "shares": [{"user_id": sam_user["id"], "level": "act"}],
    }, headers=CSRF)
    assert granted.status_code == 200, granted.text
    sam = TestClient(client.app)
    login(sam, "sam", "another-long-password")
    assert sam.get(f"/api/v1/widgets/{widget_id}/logs").status_code == 200


def test_a_log_on_a_locked_engine_stays_with_the_administrator(client: TestClient) -> None:
    """A curated card on a locked connection is shared; a raw log is not.

    An administrator who shares a board shares what a card shows, and he chose
    what that is. A container log is unbounded output he cannot curate, so the
    lock still holds even for a share that may act.
    """
    setup_admin(client)
    locked = _locked(client)
    board = client.post("/api/v1/boards", json={"name": "Ops"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    made = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "docker.logs", "title": "Logs", "integration_id": locked["id"], "options": {"container": "radarr"},
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    widget_id = made.json().get("id") or made.json()["widget"]["id"]

    sam_user = create_user(client, "sam")
    granted = client.put(f"/api/v1/boards/{board['slug']}/shares", json={
        "shares": [{"user_id": sam_user["id"], "level": "act"}],
    }, headers=CSRF)
    assert granted.status_code == 200, granted.text

    sam = TestClient(client.app)
    login(sam, "sam", "another-long-password")
    answer = sam.get(f"/api/v1/widgets/{widget_id}/logs")
    assert answer.status_code == 403, answer.text
    assert answer.json()["detail"]["code"] == "integration_locked"
    assert client.get(f"/api/v1/widgets/{widget_id}/logs").status_code == 200, "the administrator still reads it"
