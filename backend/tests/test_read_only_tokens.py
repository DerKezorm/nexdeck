"""A token that may only read.

A token used to carry every right of its account, so the one handed to a
dashboard on a tablet or to a monitoring script could delete boards. A new
token reads and nothing else; each test here is one way it might still write.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from starlette.requests import Request

from app import deps
from app.db import db_session, get_engine
from app.models import ApiToken, Page

from .conftest import CSRF, setup_admin
from .test_guards import api_routes

#: Written out here, not taken from ``deps``: a guard that reads its rule from the code it guards proves nothing.
SAFE = {"GET", "HEAD", "OPTIONS"}


def _token(client: TestClient, **body: object) -> dict:
    answer = client.post("/api/v1/tokens", json={"name": "script", **body}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _concrete(path: str) -> str:
    """A route's path with a plausible value in every placeholder."""
    return re.sub(r"\{[^}]+\}", "1", path)


def _refused(answer) -> bool:  # noqa: ANN001
    try:
        return answer.status_code == 403 and answer.json()["detail"]["code"] == "token_read_only"
    except (ValueError, KeyError, TypeError):
        return False


@pytest.fixture
def lab(client: TestClient) -> dict:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    return {"client": client, "board": board, "read": _token(client)["token"], "full": _token(client, scope="full")["token"]}


def test_a_new_token_reads_unless_full_access_is_asked_for(lab: dict) -> None:
    listed = [entry["scope"] for entry in lab["client"].get("/api/v1/tokens").json()]
    assert listed == ["read", "full"]
    refused = lab["client"].post("/api/v1/tokens", json={"name": "odd", "scope": "admin"}, headers=CSRF)
    assert refused.status_code == 422


def test_a_reading_token_reads(lab: dict) -> None:
    script = TestClient(lab["client"].app)
    assert script.get("/api/v1/boards", headers=_bearer(lab["read"])).status_code == 200
    assert script.get(f"/api/v1/boards/{lab['board']['slug']}", headers=_bearer(lab["read"])).status_code == 200
    assert script.get("/api/v1/auth/me", headers=_bearer(lab["read"])).json()["auth_kind"] == "token"


def test_a_reading_token_writes_nowhere(lab: dict) -> None:
    """Every route of the app, every method that is not a read, with the token that may only read.

    Not a list of the routes somebody thought of: the routes the app has. A
    route added next year is in here the day it is added.
    """
    script = TestClient(lab["client"].app)
    checked: list[str] = []
    through: list[str] = []
    for route in api_routes():
        for method in sorted(route.methods - SAFE):
            key = f"{method} {route.path}"
            checked.append(key)
            answer = script.request(method, _concrete(route.path), headers=_bearer(lab["read"]), json={})
            if not _refused(answer):
                through.append(f"{key} -> {answer.status_code}")
    assert len(checked) >= 120, "the route table shrank; is the app wired?"
    assert through == [], "a token that may only read got past these:\n  " + "\n  ".join(through)


def test_the_same_routes_still_answer_a_token_with_full_access(lab: dict) -> None:
    """The guard above must not pass because every token is refused everything."""
    script = TestClient(lab["client"].app)
    made = script.post("/api/v1/boards", json={"name": "From a script"}, headers=_bearer(lab["full"]))
    assert made.status_code == 201, made.text
    refused = script.post("/api/v1/boards", json={"name": "From a reader"}, headers=_bearer(lab["read"]))
    assert _refused(refused)
    assert "may only read" in refused.json()["detail"]["message"]
    assert [b["name"] for b in script.get("/api/v1/boards", headers=_bearer(lab["full"])).json()].count("From a reader") == 0


def test_a_reading_token_cannot_withdraw_tokens_or_sign_anyone_out(lab: dict) -> None:
    script = TestClient(lab["client"].app)
    listed = lab["client"].get("/api/v1/tokens").json()
    for entry in listed:
        assert _refused(script.delete(f"/api/v1/tokens/{entry['id']}", headers=_bearer(lab["read"])))
    assert _refused(script.post("/api/v1/auth/logout", headers=_bearer(lab["read"])))
    assert len(lab["client"].get("/api/v1/tokens").json()) == len(listed)


def test_the_gets_that_set_something_going_are_closed_to_a_reading_token(lab: dict) -> None:
    """A transcode on the media server, a path of the caller's own on the service, the installation's push keys."""
    script = TestClient(lab["client"].app)
    for path in ("/api/v1/widgets/1/image?path=/library/sections/all/refresh", "/api/v1/widgets/1/audio/7",
                 "/api/v1/widgets/1/audio/7/hls/master.m3u8", "/api/v1/push/key"):
        assert _refused(script.get(path, headers=_bearer(lab["read"]))), path
        assert not _refused(script.get(path, headers=_bearer(lab["full"]))), path


def test_a_reading_token_leaves_a_new_network_plan_unwritten(lab: dict) -> None:
    client = lab["client"]
    unifi = client.post("/api/v1/integrations", json={"kind": "unifi", "name": "UniFi", "demo": True,
                                                      "config": {"url": "https://unifi.example.com", "api_key": "a-key"}}, headers=CSRF).json()
    made = client.post(f"/api/v1/boards/{lab['board']['slug']}/pages", json={"name": "Network", "kind": "topology",
                                                                             "integration_id": unifi["id"]}, headers=CSRF)
    page = next(p for p in made.json()["pages"] if p["kind"] == "topology")
    script = TestClient(client.app)
    seen = script.get(f"/api/v1/pages/{page['id']}/topology", headers=_bearer(lab["read"])).json()
    assert seen["layout"]["seeded"] is True, "the reader sees the first arrangement"
    with db_session() as db:
        stored = db.get(Page, page["id"])
        assert stored is not None and not stored.topology.get("seeded") and not stored.topology.get("placed")
    assert client.get(f"/api/v1/pages/{page['id']}/topology").json()["layout"]["seeded"] is True


def test_the_second_wall_holds_without_the_middleware(lab: dict) -> None:
    """``deps`` refuses the token on its own, should a route ever be mounted past the middleware."""
    scope = {"type": "http", "method": "DELETE", "path": "/api/v1/boards/lab", "headers": [
        (b"authorization", f"Bearer {lab['read']}".encode())], "query_string": b"", "state": {}}
    with db_session() as db, pytest.raises(Exception) as caught:
        deps.optional_user(Request(scope), db)
    assert getattr(caught.value, "detail", {}).get("code") == "token_read_only"
    scope["method"] = "GET"
    with db_session() as db:
        assert deps.optional_user(Request(scope), db) is not None


def test_tokens_from_before_keep_their_full_rights(lab: dict) -> None:
    """The column arrives with ``full`` in every row that is there; only new tokens start at reading."""
    from app.migrations import MIGRATIONS

    with get_engine().begin() as connection:
        connection.execute(text("ALTER TABLE api_tokens DROP COLUMN scope"))
    step = {version: function for version, _description, function in MIGRATIONS}[25]
    with get_engine().begin() as connection:
        step(connection)
    with db_session() as db:
        assert set(db.scalars(select(ApiToken.scope))) == {"full"}
    script = TestClient(lab["client"].app)
    made = script.post("/api/v1/boards", json={"name": "Old script"}, headers=_bearer(lab["read"]))
    assert made.status_code == 201, "the token made as a reader is a token from before now"
