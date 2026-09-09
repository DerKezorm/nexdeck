"""A row may offer a file, and the server hands it over as a download.

⚠️ The address behind this is the same shape as an action: whoever may look at
the board may ask for a file, so what may be asked for has to be the list the
card last delivered. Left open it would read "fetch any path from this widget's
service, with the server's credentials", and a kiosk display counts as a
viewer.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.adapters.base import saveable
from app.services.state import live
from tests.conftest import CSRF, setup_admin

METUBE = "http://metube.example.com"
FILE = "/download/A%20lock%2C%20taken%20apart.webm"
DONE = {
    "id": "aBcDeFgHiJk", "url": "https://videos.example.com/watch?v=aBcDeFgHiJk",
    "title": "A lock, taken apart", "status": "finished", "filename": "A lock, taken apart.webm",
    "size": 474_489, "timestamp": 1_788_898_037_170_208_067,
}


def _card(client: TestClient) -> int:
    integration = client.post(
        "/api/v1/integrations",
        json={"kind": "metube", "name": "MeTube", "config": {"url": METUBE}, "demo": False},
        headers=CSRF,
    ).json()
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    widget = client.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "metube.downloads", "integration_id": integration["id"]},
        headers=CSRF,
    )
    assert widget.status_code == 201, widget.text
    return int(widget.json()["widget"]["id"])


@respx.mock
def _deliver(client: TestClient, widget_id: int) -> dict:
    """Refresh the card so it really offers the row, the way a board does."""
    respx.get(f"{METUBE}/history").mock(return_value=httpx.Response(
        200, json={"queue": [], "pending": [], "done": [DONE]}))
    answer = client.post(f"/api/v1/widgets/{widget_id}/refresh", headers=CSRF)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_a_finished_row_offers_its_file(client: TestClient) -> None:
    setup_admin(client)
    widget_id = _card(client)
    data = _deliver(client, widget_id)
    assert data["items"][0]["file"] == {"path": FILE, "name": "A lock, taken apart.webm", "size": 474489.0}


@respx.mock
def test_the_file_arrives_as_a_download_with_its_own_name(client: TestClient) -> None:
    setup_admin(client)
    widget_id = _card(client)
    _deliver(client, widget_id)
    respx.get(f"{METUBE}{FILE}").mock(return_value=httpx.Response(
        200, content=b"webm-bytes", headers={"content-type": "video/webm"}))
    answer = client.get(f"/api/v1/widgets/{widget_id}/file", params={"path": FILE})
    assert answer.status_code == 200, answer.text
    assert answer.content == b"webm-bytes"
    # ⚠️ attachment, or the browser plays the video instead of saving it.
    assert answer.headers["content-disposition"].startswith("attachment;")
    assert "A%20lock%2C%20taken%20apart.webm" in answer.headers["content-disposition"]


@respx.mock
def test_a_path_the_card_never_offered_is_refused(client: TestClient) -> None:
    """The guard. Without it this address fetches anything the server can reach
    on that service, for anybody who may look at the board."""
    setup_admin(client)
    widget_id = _card(client)
    _deliver(client, widget_id)
    reached = respx.get(url__startswith=METUBE).mock(return_value=httpx.Response(200, content=b"secret"))
    for path in ("/download/something%20else.webm", "/config.json", FILE + "x", "/download/", ""):
        answer = client.get(f"/api/v1/widgets/{widget_id}/file", params={"path": path})
        assert answer.status_code == 404, f"{path!r} went through: {answer.status_code}"
        assert answer.json()["detail"]["code"] == "no_such_file"
    assert not reached.called, "the server went to the service for a path no card had offered"


def test_a_card_that_has_never_been_read_offers_no_file(client: TestClient) -> None:
    setup_admin(client)
    widget_id = _card(client)
    live.forget(widget_id)
    answer = client.get(f"/api/v1/widgets/{widget_id}/file", params={"path": FILE})
    assert answer.status_code == 404, answer.text


@respx.mock
def test_the_name_comes_from_the_card_not_from_the_request(client: TestClient) -> None:
    """⚠️ A name out of the query string would be a caller writing a response
    header. It is looked up in the delivered row instead, and the row is the
    only place a name can come from."""
    setup_admin(client)
    widget_id = _card(client)
    _deliver(client, widget_id)
    respx.get(f"{METUBE}{FILE}").mock(return_value=httpx.Response(200, content=b"x"))
    answer = client.get(
        f"/api/v1/widgets/{widget_id}/file",
        params={"path": FILE, "name": 'evil"; x=1', "filename": "other.exe"},
    )
    assert answer.status_code == 200, answer.text
    disposition = answer.headers["content-disposition"]
    assert "evil" not in disposition and "other.exe" not in disposition
    assert "A%20lock%2C%20taken%20apart.webm" in disposition


def test_a_failed_row_offers_no_file(client: TestClient) -> None:
    """⚠️ A failure lands in ``done`` with a filename MeTube worked out before
    it tried. Offering it is a button that fetches a file nobody wrote."""
    from app.adapters import get_adapter

    rows = get_adapter("metube")._rows(
        {"queue": [], "pending": [], "done": [{**DONE, "status": "error", "msg": "ERROR: no"}]}, "done", 8)
    assert "file" not in rows[0]


def test_a_filename_cannot_walk_out_of_the_download_folder() -> None:
    """The name comes from the service, so it is not ours to trust either."""
    from app.adapters import get_adapter

    metube = get_adapter("metube")
    for name in ("../config.json", "a/b.webm", "..\\x", ""):
        rows = metube._rows({"queue": [], "pending": [], "done": [{**DONE, "filename": name}]}, "done", 8)
        assert "file" not in rows[0], name


def test_the_helper_writes_the_shape_the_guard_reads() -> None:
    assert saveable("/download/x.webm", "x.webm", 12) == {"path": "/download/x.webm", "name": "x.webm", "size": 12.0}
    assert saveable("/download/x.webm", "x.webm") == {"path": "/download/x.webm", "name": "x.webm"}
