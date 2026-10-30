"""B2 of a review of 1.0.2 in the Card shop: picture paths shown before installing, and confirmed when an update brings one."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi.testclient import TestClient

from .conftest import CSRF
from .karten8_sample import DOWNLOADS
from .karten14_sample import AUTHOR, GitHub

SLUG = "downloads"
ENTRY = f"/api/v1/workshop/entries/{AUTHOR}/{SLUG}"
PICTURE = "/api/v2/torrents/{hash}/thumb.jpg"

pytest_plugins = ["tests.karten14_sample"]


def text(version: str, picture: str | None) -> str:
    data: dict[str, Any] = yaml.safe_load(DOWNLOADS)
    data["version"], data["buttons"] = version, []
    if picture is not None:
        data["item"]["image"] = {"template": picture}
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def test_karten8u_b2_the_detail_and_the_check_before_installing_show_the_picture_paths(shop: TestClient, github: GitHub) -> None:
    github.publish(text("1.0.0", PICTURE))
    detail = shop.get(ENTRY)
    assert detail.status_code == 200, detail.text
    assert detail.json()["pictures"] == [{"kind": "jsonapi", "path": PICTURE}]
    checked = shop.post(f"{ENTRY}/install/check", json={}, headers=CSRF)
    assert checked.status_code == 200, checked.text
    assert checked.json()["entry"]["pictures"] == [{"kind": "jsonapi", "path": PICTURE}]


def test_karten8u_b2_an_update_with_a_new_picture_path_waits_for_the_administrator(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(text("1.0.0", None))
    assert shop.post(f"{ENTRY}/install", json={"accept_risk": True}, headers=CSRF).status_code == 201
    github.publish(text("1.1.0", PICTURE))
    clock[0] += 700
    assert shop.get("/api/v1/workshop/catalog").status_code == 200
    told = shop.get(f"/api/v1/workshop/updates/{SLUG}")
    assert told.status_code == 200, told.text
    assert told.json()["pictures_to_confirm"] == [PICTURE]
    assert told.json()["permissions"]["pictures"] == {"added": [PICTURE], "removed": []}
    refused = shop.post(f"/api/v1/workshop/updates/{SLUG}/accept", json={"expected_version": "1.1.0"}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "pictures_not_confirmed", refused.text
    taken = shop.post(f"/api/v1/workshop/updates/{SLUG}/accept", json={"expected_version": "1.1.0", "confirmed_pictures": [PICTURE]}, headers=CSRF)
    assert taken.status_code == 200 and taken.json()["status"] == "updated", taken.text
