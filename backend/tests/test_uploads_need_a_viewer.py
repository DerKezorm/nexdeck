"""An uploaded file is served to somebody signed in or to a wall display, and to nobody else.

⚠️ The address was public, with the running number of the upload in it and a
file name that was never compared, so ``/api/v1/assets/1/x``, ``/2/x`` and on
handed every background, icon and photo of every account to anybody who could
reach the installation. It was public for kiosk displays, and those have
carried a cookie of their own since 0.6: an ``<img>`` sends it like any other
request. Found on 12.09.2026.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import CSRF, setup_admin

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _upload(client: TestClient) -> str:
    answer = client.post("/api/v1/assets", params={"kind": "picture"}, files={"file": ("rack.png", PNG, "image/png")}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()["url"]


def test_a_stranger_gets_nothing_by_counting(client: TestClient) -> None:
    setup_admin(client)
    url = _upload(client)
    stranger = TestClient(client.app)
    assert stranger.get(url).status_code == 401
    number = url.split("/")[4]
    assert stranger.get(f"/api/v1/assets/{number}/x").status_code == 401

    mine = client.get(url)
    assert mine.status_code == 200
    assert mine.content == PNG
    assert mine.headers["cache-control"].startswith("private"), "a shared cache must not keep what needs a viewer"


def test_a_wall_display_still_gets_its_pictures(client: TestClient) -> None:
    setup_admin(client, demo=True)
    url = _upload(client)
    slug = client.get("/api/v1/boards").json()[0]["slug"]
    made = client.post(f"/api/v1/boards/{slug}/kiosk-tokens", json={"name": "Hall"}, headers=CSRF)
    assert made.status_code == 201, made.text

    display = TestClient(client.app)
    assert display.get(url).status_code == 401, "without its cookie the display is a stranger"
    door = display.post("/api/v1/kiosk/session", json={"token": made.json()["token"]}, headers=CSRF)
    assert door.status_code == 200, door.text
    assert display.get(url).status_code == 200
