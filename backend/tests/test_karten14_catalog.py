"""KARTEN-14: the catalog (AC-3, AC-5, AC-10, AC-11, AC-12, EC-2, EC-6), the pictures through the server and the preview (AC-6, EC-1)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.workshop import catalog

from .cards_sample import changed
from .conftest import CSRF
from .karten14_sample import AUTHOR, PNG, GitHub, card_text

KEY = "ghp_example-key-040719639"
SONARR = {"kind": "sonarr", "name": "My Sonarr", "config": {"url": "http://svc.example.com:8989", "api_key": "k"}}

#: The pretend GitHub, the clock of the shop and the signed-in administrator with the shop on.
pytest_plugins = ["tests.karten14_sample"]


def read(client: TestClient):  # noqa: ANN202
    return client.get("/api/v1/workshop/catalog")


def test_karten14_ac3_the_catalog_lists_cards_with_what_they_need(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text("queue-size"))
    github.publish(card_text("other-card"), thumbs=9)
    found = read(shop)
    assert found.status_code == 200, found.text
    body = found.json()
    assert [one["slug"] for one in body["entries"]] == ["queue-size", "other-card"]
    first = body["entries"][0]
    assert first["author"] == {"id": AUTHOR, "login": "someone"}
    assert first["requires"][0]["kind"] == "sonarr"
    assert first["requires"][0]["label"] == "Sonarr"
    assert first["thumbs"] == 3
    assert first["images"]["light"] == f"/api/v1/workshop/entries/{AUTHOR}/queue-size/image/light"
    assert first["license"] == "MIT"
    assert body["warning"] is None


def test_karten14_ac3_what_fits_my_connections(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text("queue-size"))
    assert read(shop).json()["entries"][0]["fits"] is False
    made = shop.post("/api/v1/integrations", json=SONARR, headers=CSRF)
    assert made.status_code == 201, made.text
    one = read(shop).json()["entries"][0]
    assert one["fits"] is True
    assert one["connections"] == [{"id": made.json()["id"], "name": "My Sonarr", "kind": "sonarr"}]
    # Both lookups came from one look at GitHub.
    assert github.count("catalog.json") == 1


def test_karten14_ec2_a_card_for_a_newer_nexdeck_says_so(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text("queue-size"), min_nexdeck="99.0.0")
    one = read(shop).json()["entries"][0]
    assert one["needs_newer"] is True
    assert one["min_nexdeck"] == "99.0.0"


def test_karten14_ac12_the_catalog_is_fetched_once_in_ten_minutes(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(card_text())
    read(shop)
    read(shop)
    assert github.count("catalog.json") == 1
    clock[0] += 599
    read(shop)
    assert github.count("catalog.json") == 1
    clock[0] += 2
    read(shop)
    assert github.count("catalog.json") == 2


def test_karten14_ac10_github_out_of_reach_is_said_in_a_sentence(shop: TestClient, github: GitHub) -> None:
    github.mode = "down"
    found = read(shop)
    assert found.status_code == 502
    assert found.json()["detail"] == {"code": "github_unreachable", "message": "GitHub cannot be reached. Cards you installed keep working."}


def test_karten14_ac10_an_older_catalog_is_shown_when_github_goes_away(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(card_text())
    assert read(shop).json()["warning"] is None
    github.mode = "down"
    clock[0] += 700
    found = read(shop)
    assert found.status_code == 200
    assert [one["slug"] for one in found.json()["entries"]] == ["queue-size"]
    assert found.json()["warning"]["code"] == "github_unreachable"


def test_karten14_ac10_a_failed_look_is_not_repeated_at_every_click(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.mode = "down"
    read(shop)
    read(shop)
    read(shop)
    assert github.count("catalog.json") == 1
    clock[0] += 61
    read(shop)
    assert github.count("catalog.json") == 2


@pytest.mark.parametrize(("status", "code"), [(401, "github_rejected"), (404, "github_rejected"), (429, "github_rate_limited"), (500, "github_unreachable")])
def test_karten14_ac11_what_github_says_to_a_request_it_refuses(shop: TestClient, github: GitHub, status: int, code: str) -> None:
    github.mode = status
    found = read(shop)
    assert found.status_code == 502
    assert found.json()["detail"]["code"] == code


def test_karten14_ac11_the_private_repository_is_read_with_the_key_of_the_operator(
    shop: TestClient, github: GitHub, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    github.publish(card_text())
    monkeypatch.setenv("NEXDECK_WORKSHOP_TOKEN", KEY)
    with caplog.at_level("DEBUG"):
        found = read(shop)
    assert found.status_code == 200
    assert [request.headers.get("authorization") for request in github.requests] == [f"Bearer {KEY}"]
    assert {request.url.host for request in github.requests} == {"api.github.com"}
    # The key is in no answer and no line of the log.
    assert KEY not in found.text
    assert KEY not in shop.get("/api/v1/workshop/state").text
    assert KEY not in caplog.text


def test_karten14_without_a_key_none_is_sent(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    read(shop)
    assert [request.headers.get("authorization") for request in github.requests] == [None]


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[]", b'{"format": 2, "entries": [{}]}', b'{"format": 1, "entries": "x"}', b'{"format": 1, "entries": [{"id": "x"}]}'],
)
def test_karten14_ec6_a_broken_catalog_is_an_error_and_not_an_empty_list(shop: TestClient, github: GitHub, raw: bytes) -> None:
    github.catalog_override = raw
    found = read(shop)
    assert found.status_code == 502
    assert found.json()["detail"]["code"] == "catalog_invalid"


def test_karten14_ec6_an_empty_catalog_is_an_error(shop: TestClient, github: GitHub) -> None:
    found = read(shop)
    assert found.status_code == 502
    assert found.json()["detail"]["code"] == "catalog_empty"


def test_karten14_ec6_a_broken_catalog_hides_behind_no_older_good_one(shop: TestClient, github: GitHub, clock: list[float]) -> None:
    github.publish(card_text())
    assert read(shop).status_code == 200
    github.catalog_override = b"{"
    clock[0] += 700
    assert read(shop).json()["detail"]["code"] == "catalog_invalid"


@pytest.mark.parametrize("path", ["../secrets.txt", "/etc/passwd", "entries/../../x", "a//b", "entries/%2e%2e/x"])
def test_karten14_ec6_an_entry_with_a_path_out_of_the_repository_is_refused(shop: TestClient, github: GitHub, path: str) -> None:
    found = github.publish(card_text())
    found["files"]["readme"] = path
    assert read(shop).json()["detail"]["code"] == "catalog_invalid"


def test_karten14_ec6_an_entry_listed_twice_is_shown_once(shop: TestClient, github: GitHub) -> None:
    found = github.publish(card_text())
    github.entries.append(json.loads(json.dumps(found)))
    assert [one["id"] for one in read(shop).json()["entries"]] == [found["id"]]


def test_karten14_ac5_the_detail_has_the_texts_of_the_entry(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    found = shop.get(f"/api/v1/workshop/entries/{AUTHOR}/queue-size")
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["readme"] == "About queue-size."
    assert body["changelog"] == "Changes of 1.0.0."
    assert body["files_warning"] is None
    assert body["updated_at"] == "2026-10-20T10:00:00Z"
    assert shop.get(f"/api/v1/workshop/entries/{AUTHOR}/missing").status_code == 404


def test_karten14_ac5_a_text_that_cannot_be_fetched_leaves_the_rest_of_the_page(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    del github.files[f"entries/{AUTHOR}/queue-size/CHANGELOG.md"]
    body = shop.get(f"/api/v1/workshop/entries/{AUTHOR}/queue-size").json()
    assert body["readme"] == "About queue-size."
    assert body["changelog"] is None
    assert body["files_warning"]["code"] == "github_rejected"


def test_karten14_a_picture_comes_from_the_server_and_is_kept(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    first = shop.get(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/image/light")
    assert first.status_code == 200
    assert first.content == PNG
    assert first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "private, max-age=3600"
    shop.get(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/image/light")
    assert github.count("preview-light.png") == 1
    assert shop.get(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/image/sepia").status_code == 404


def test_karten14_a_picture_that_is_no_png_is_not_passed_on(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.files[f"entries/{AUTHOR}/queue-size/preview-dark.png"] = b"<html>no</html>"
    assert shop.get(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/image/dark").status_code == 404


def test_karten14_nothing_but_the_catalog_of_the_setting_is_asked(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    read(shop)
    shop.get(f"/api/v1/workshop/entries/{AUTHOR}/queue-size")
    assert {request.url.host for request in github.requests} == {"api.github.com"}
    assert all(request.url.path.startswith("/repos/DerKezorm/nexdeck-workshop/contents/") for request in github.requests)
    assert all(request.method == "GET" for request in github.requests)


def test_karten14_ac6_the_preview_runs_on_the_definition_of_the_catalog(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    number = shop.post("/api/v1/integrations", json=SONARR, headers=CSRF).json()["id"]
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as network:
        network.route(host="api.github.com").mock(side_effect=github.answer)
        network.get("http://svc.example.com:8989/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 7, "records": []}))
        found = shop.post(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/preview", json={"integration_id": number}, headers=CSRF)
    assert found.status_code == 200, found.text
    assert found.json()["primary"]["value"] == 7
    # It was only looked at.
    assert shop.get("/api/v1/cards").json()["cards"] == []


def test_karten14_ac6_an_own_connection_has_no_preview(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), type="integration")
    found = shop.post(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/preview", json={"integration_id": 1}, headers=CSRF)
    assert found.status_code == 400
    assert found.json()["detail"]["code"] == "no_preview"


def test_karten14_ec1_a_definition_that_differs_from_the_catalog_is_not_used(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text())
    github.files[f"entries/{AUTHOR}/queue-size/definition.yaml"] = changed("Queue", "Evil", card_text()).encode()
    found = shop.post(f"/api/v1/workshop/entries/{AUTHOR}/queue-size/preview", json={"integration_id": 1}, headers=CSRF)
    assert found.status_code == 409
    assert found.json()["detail"]["code"] == "checksum_mismatch"


def _real_catalog() -> dict:
    """The first real catalog of the workshop, with a made-up author and the digests left out (filled in here)."""
    data = json.loads((Path(__file__).parent / "fixtures" / "workshop_catalog_real.json").read_bytes())
    for one in data["entries"]:
        one["sha256"] = "0" * 64
    return data


def test_karten14_the_catalog_the_workshop_writes_is_read_whole() -> None:
    """The first real catalog of the workshop (28.10.2026): author IDs are numbers and an own integration has no version."""
    data = _real_catalog()
    read = catalog.parse(json.dumps(data).encode())
    assert [entry.id for entry in read.entries] == [one["id"] for one in data["entries"]]
    assert all(entry.author.id == "4071963" for entry in read.entries)


def test_karten14_one_entry_that_cannot_be_read_leaves_the_others() -> None:
    data = _real_catalog()
    data["entries"][0]["sha256"] = "not a digest"
    read = catalog.parse(json.dumps(data).encode())
    assert len(read.entries) == len(data["entries"]) - 1
