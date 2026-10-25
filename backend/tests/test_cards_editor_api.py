"""What the card editor asks of the server: probe, preview, examples, check, a save that notices another one (KARTEN-9, KARTEN-10)."""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import httpx
import jmespath
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.cards import demo, images, probe, store
from app.db import db_session, get_engine
from app.models import CardRecord, Event
from app.services.collector import collector

from .cards_sample import VALUE_CARD, changed
from .conftest import CSRF, create_user, login, setup_admin
from .test_cards_forms import POSTERS
from .test_cards_router import ADMIN, BASE, add, as_admin, as_user, connection, text_of

API = "/api/v1/cards"
ANSWER = {"totalRecords": 12, "records": [{"title": "A", "series": {"title": "X"}}]}


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    from app.routers import widgets as widget_routes

    widget_routes._images.clear()
    return client


def post(client: TestClient, path: str, body: dict[str, Any]) -> httpx.Response:
    return client.post(f"{API}/{path}", json=body, headers=CSRF)


def sonarr_serves(answer: Any = ANSWER, **more: Any) -> respx.Route:
    return respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=answer, **more))


def nodes_of(tree: dict[str, Any]) -> list[dict[str, Any]]:
    found = [tree]
    for child in tree.get("children", []):
        found += nodes_of(child)
    return found


# -- AC-1: only administrators -----------------------------------------------------------------------


EDITOR_CALLS = (
    ("post", "probe", {"integration_id": 1, "path": "/api/v3/queue"}),
    ("post", "preview", {"yaml": VALUE_CARD}),
    ("post", "demo", {"yaml": VALUE_CARD, "integration_id": 1}),
    ("post", "check", {"yaml": VALUE_CARD}),
    ("get", "preview-image?integration_id=1&path=%2Fx", None),
)


def test_karten9_ac1_every_address_of_the_editor_is_closed_to_anybody_but_an_administrator(admin: TestClient) -> None:
    add(admin)
    sonarr = connection(admin)
    create_user(admin, "visitor", role="guest")
    admin.post("/api/v1/auth/logout", headers=CSRF)
    for method, path, body in EDITOR_CALLS:
        answer = getattr(admin, method)(f"{API}/{path}", headers=CSRF, **({"json": body} if body else {}))
        assert answer.status_code == 401, (path, answer.status_code)
    for who in ("visitor", "ann"):
        if who == "ann":
            as_admin(admin)
            as_user(admin)
        else:
            login(admin, "visitor", "another-long-password")
        for method, path, body in EDITOR_CALLS:
            answer = getattr(admin, method)(f"{API}/{path}", headers=CSRF, **({"json": body} if body else {}))
            assert answer.status_code == 403, (who, path, answer.status_code)
        saved = admin.put(f"{API}/queue-size", json={"yaml": VALUE_CARD, "overwrite": True}, headers=CSRF)
        assert saved.status_code == 403
    as_admin(admin)
    assert sonarr and admin.get(f"{API}/queue-size").status_code == 200


# -- AC-3, EC-1: the tree ---------------------------------------------------------------------------


@respx.mock
def test_karten9_ac3_a_probe_answers_with_a_tree_of_names_types_and_values(admin: TestClient) -> None:
    sonarr = connection(admin)
    sonarr_serves()
    answer = post(admin, "probe", {"integration_id": sonarr, "path": "/api/v3/queue"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    root = body["tree"]
    assert (root["key"], root["path"], root["type"]) == (None, "@", "object") and body["cut"] is False
    by_path = {one["path"]: one for one in nodes_of(root)}
    assert by_path["totalRecords"] | {"children": None} == {"key": "totalRecords", "path": "totalRecords", "type": "number", "value": 12, "children": None}
    assert by_path["records"]["type"] == "array" and by_path["records[0].series.title"]["value"] == "X"
    assert by_path["records[0]"]["key"] == 0
    assert body["nodes"] == len(nodes_of(root))


WEIRD = {
    "a b": {"c.d": [{"1x": 5, "é": 2, '"q"': 3, "back\\slash": 4, "": 9, "x-y": [1, [2, 3]], "_ok": True, "nul": None}]},
    "list": [[1, 2], [3]],
    "0": "zero",
}


def test_karten9_ac3_every_path_of_the_tree_finds_exactly_the_value_of_its_node() -> None:
    tree = probe.build(WEIRD)["tree"]
    seen = 0
    for node in nodes_of(tree):
        found = jmespath.search(node["path"], WEIRD)
        if node["type"] == "object":
            assert isinstance(found, dict), node["path"]
        elif node["type"] == "array":
            assert isinstance(found, list), node["path"]
        else:
            assert found == node.get("value"), node["path"]
        seen += 1
    assert seen == 23, "a path of every kind was tried: spaces, dots, dashes, digits first, quotes, backslashes, empty names, lists in lists"


def test_karten9_ac3_a_root_that_is_a_list_has_paths_that_find_its_entries() -> None:
    data = [{"id": 7, "tags": ["a"]}, 3]
    for node in nodes_of(probe.build(data)["tree"]):
        found = jmespath.search(node["path"], data)
        assert node["type"] in ("object", "array") or found == node["value"], node["path"]


def test_karten9_ec1_a_large_answer_is_cut_to_five_hundred_nodes_and_the_cut_is_counted() -> None:
    big = {f"section{n}": {f"field{k}": k for k in range(40)} for n in range(30)}
    body = probe.build(big)
    assert body["nodes"] == 500 and body["cut"] is True
    assert len(nodes_of(body["tree"])) == 500
    # The first level is whole although the fields below do not all fit: a long section cannot starve its neighbours.
    assert len(body["tree"]["children"]) == 30
    left_out = sum(one.get("more", 0) for one in nodes_of(body["tree"]))
    assert 500 + left_out == 1 + 30 + 30 * 40


def test_karten9_ec1_a_long_list_shows_its_first_entries_and_says_how_many_more() -> None:
    body = probe.build({"rows": [{"n": n} for n in range(1234)]})
    rows = next(one for one in nodes_of(body["tree"]) if one["path"] == "rows")
    assert len(rows["children"]) == probe.ARRAY_SHOWN and rows["more"] == 1234 - probe.ARRAY_SHOWN and body["cut"] is True
    assert [one["key"] for one in rows["children"]] == list(range(probe.ARRAY_SHOWN))


def test_karten9_ec1_a_long_text_is_cut_to_two_hundred_characters_and_says_so() -> None:
    node = probe.build({"t": "x" * 5000, "s": "short"})["tree"]["children"]
    assert node[0]["value"] == "x" * 200 and node[0]["truncated"] is True
    assert node[1]["value"] == "short" and "truncated" not in node[1]


@respx.mock
def test_karten9_ec1_the_node_budget_holds_over_the_wire(admin: TestClient) -> None:
    sonarr = connection(admin)
    sonarr_serves({f"s{n}": [{"a": 1, "b": {"c": [1, 2, 3]}}] * 60 for n in range(40)})
    body = post(admin, "probe", {"integration_id": sonarr, "path": "/api/v3/queue"}).json()
    assert body["nodes"] <= 500 and body["cut"] is True and len(nodes_of(body["tree"])) == body["nodes"]


# -- EC-2: the way a card says it --------------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize(
    ("serves", "code", "status_code"),
    [
        (httpx.Response(401), "auth_failed", 502),
        (httpx.Response(403), "auth_failed", 502),
        (httpx.Response(500), "http_error", 502),
        (httpx.Response(302, headers={"location": "http://other.example.com/"}), "redirected", 502),
        (httpx.Response(200, text="<html>login</html>"), "not_json", 502),
        (httpx.Response(200, content=b'{"x": "' + b"a" * (2 * 1024 * 1024) + b'"}'), "answer_too_large", 502),
    ],
)
def test_karten9_ec2_a_probe_that_fails_says_why_the_way_the_card_does(admin: TestClient, serves: httpx.Response, code: str, status_code: int) -> None:
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=serves)
    answer = post(admin, "probe", {"integration_id": sonarr, "path": "/api/v3/queue"})
    detail = answer.json()["detail"]
    assert answer.status_code == status_code and detail["code"] == code and detail["message"] and detail["hint"], detail


@respx.mock
def test_karten9_ec2_a_service_that_does_not_answer_is_unreachable(admin: TestClient) -> None:
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(side_effect=httpx.ConnectError("down"))
    answer = post(admin, "probe", {"integration_id": sonarr, "path": "/api/v3/queue"})
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "unreachable"


@respx.mock
@pytest.mark.parametrize("path", ["http://evil.example.com/x", "//evil.example.com/x", "/../admin", "relative", "/%2e%2e/b"])
def test_karten9_ec2_a_path_that_leaves_the_connection_is_refused_before_anything_is_asked(admin: TestClient, path: str) -> None:
    sonarr = connection(admin)
    reached = respx.route().mock(return_value=httpx.Response(200, json={}))
    answer = post(admin, "probe", {"integration_id": sonarr, "path": path})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "bad_path" and not reached.called


@respx.mock
def test_karten9_ec2_a_connection_that_is_missing_off_or_not_readable_is_refused_cleanly(admin: TestClient) -> None:
    gone = post(admin, "probe", {"integration_id": 999, "path": "/x"})
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "no_integration"
    off = connection(admin)
    admin.patch(f"/api/v1/integrations/{off}", json={"enabled": False}, headers=CSRF)
    assert post(admin, "probe", {"integration_id": off, "path": "/x"}).json()["detail"]["code"] == "no_integration"
    session_kind = admin.post("/api/v1/integrations", json={"kind": "qbittorrent", "name": "Torrents", "config": {"url": BASE, "username": "u", "password": "p"}}, headers=CSRF).json()["id"]
    reached = respx.route().mock(return_value=httpx.Response(200, json={}))
    refused = post(admin, "probe", {"integration_id": session_kind, "path": "/x"})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "no_raw_access" and not reached.called


# -- EC-4: the chronicle holds the question, never the answer ------------------------------------------


@respx.mock
def test_karten9_ec4_the_chronicle_has_the_probe_with_connection_and_path_and_nothing_of_the_answer(admin: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    sonarr = connection(admin)
    secret = {"password": "hunter2-secret", "records": [{"title": "Private Film Title"}]}
    sonarr_serves(secret)
    with caplog.at_level("DEBUG"):
        assert post(admin, "probe", {"integration_id": sonarr, "path": "/api/v3/queue"}).status_code == 200
    with db_session() as db:
        [line] = db.scalars(select(Event).where(Event.kind == "card_probe")).all()
        assert line.integration_id == sonarr and line.name == "My sonarr" and line.detail == "/api/v3/queue" and line.user_id
        everything = json.dumps([[getattr(one, column.name) for column in Event.__table__.columns] for one in db.scalars(select(Event))], default=str)
    assert "hunter2" not in everything and "Private Film" not in everything
    assert "hunter2" not in caplog.text and "Private Film" not in caplog.text
    listed = [one["kind"] for one in admin.get("/api/v1/chronicle").json()["events"]]
    assert "card_probe" in listed
    as_user(admin)
    assert "card_probe" not in [one["kind"] for one in admin.get("/api/v1/chronicle").json()["events"]], "only administrators see it"


# -- AC-9: the preview ---------------------------------------------------------------------------


@respx.mock
def test_karten9_ac9_a_preview_with_a_connection_is_what_the_card_shows_on_a_board(admin: TestClient) -> None:
    sonarr = connection(admin)
    route = sonarr_serves()
    answer = post(admin, "preview", {"yaml": VALUE_CARD, "integration_id": sonarr})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["primary"]["value"] == 12 and data["primary"]["unit"] == "items" and data["status"] == "warn"
    assert data["meta"]["custom"] is True and data["metrics"] == {"value": 12.0}
    assert route.calls.last.request.headers["x-api-key"] == "key-1"


@respx.mock
async def test_karten9_ac9_a_preview_and_the_card_on_a_board_show_the_same_values(admin: TestClient) -> None:
    from app.services.state import live

    sonarr = connection(admin)
    sonarr_serves()
    add(admin)
    page = admin.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()["pages"][0]["id"]
    widget = admin.post(f"/api/v1/pages/{page}/widgets", json={"kind": "custom.value", "integration_id": sonarr, "options": {"card": "queue-size"}}, headers=CSRF).json()["widget"]["id"]
    await collector.refresh(widget)
    on_board = live.get(widget)
    shown = post(admin, "preview", {"yaml": VALUE_CARD, "integration_id": sonarr}).json()
    assert shown["primary"] == on_board.primary and shown["status"] == on_board.status and shown["metrics"] == on_board.metrics


def test_karten9_ac9_a_preview_without_a_connection_or_asked_for_demo_uses_the_demo_data_and_asks_nobody(admin: TestClient) -> None:
    sonarr = connection(admin)
    with respx.mock(assert_all_called=False) as router:
        reached = router.route().mock(return_value=httpx.Response(200, json=ANSWER))
        alone = post(admin, "preview", {"yaml": VALUE_CARD})
        chosen = post(admin, "preview", {"yaml": VALUE_CARD, "integration_id": sonarr, "demo": True})
        assert not reached.called
    assert alone.status_code == chosen.status_code == 200
    assert alone.json()["primary"]["value"] == 4 and chosen.json()["primary"]["value"] == 4


def test_karten9_ac9_a_card_without_demo_data_says_so_when_there_is_nothing_to_read_from(admin: TestClient) -> None:
    bare = re.sub(r"demo:\n  queue: .*\n", "", VALUE_CARD)
    answer = post(admin, "preview", {"yaml": bare})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "no_demo_data" and answer.json()["detail"]["hint"]


def test_karten9_ac9_a_definition_with_problems_is_refused_the_way_saving_refuses_it(admin: TestClient) -> None:
    answer = post(admin, "preview", {"yaml": changed("form: value", "form: dial")})
    saved = admin.post(API, json={"yaml": changed("form: value", "form: dial")}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"] == saved.json()["detail"]
    assert answer.json()["detail"]["code"] == "card_invalid" and answer.json()["detail"]["problems"][0]["line"]
    assert admin.get(API).json()["cards"] == [], "a preview saves nothing"


@respx.mock
def test_karten9_ac9_a_connection_of_a_kind_the_card_does_not_name_is_the_same_error_as_on_the_card(admin: TestClient) -> None:
    lidarr = connection(admin, "lidarr")
    reached = respx.route().mock(return_value=httpx.Response(200, json={}))
    answer = post(admin, "preview", {"yaml": VALUE_CARD, "integration_id": lidarr})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "kind_mismatch" and not reached.called


@respx.mock
def test_karten9_ac9_a_failing_service_is_told_like_a_probe(admin: TestClient) -> None:
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(401))
    answer = post(admin, "preview", {"yaml": VALUE_CARD, "integration_id": sonarr})
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "auth_failed"


@respx.mock
def test_karten9_ac9_an_answer_too_slow_to_work_out_is_an_error_of_the_card_not_a_hang(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.base import AdapterError
    from app.cards import pipeline

    def too_slow(*_args: Any, **_more: Any) -> None:
        raise AdapterError("Too slow.", code="too_slow", hint="Ask for less.")

    sonarr = connection(admin)
    sonarr_serves()
    monkeypatch.setattr(pipeline, "run", too_slow)
    answer = post(admin, "preview", {"yaml": VALUE_CARD, "integration_id": sonarr})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "too_slow"


# -- AC-9: the pictures of a preview --------------------------------------------------------------------


PNG = b"\x89PNG\r\n\x1a\n"
RECORDS = {"records": [
    {"title": "A", "series": "X", "poster": "/p/a.jpg", "url": "https://example.com/a"},
    {"title": "B", "series": "Y", "poster": "https://img.example.com/b.jpg", "url": "https://example.com/b"},
]}


def covers() -> str:
    return POSTERS.replace("requires: [sonarr, radarr]", "requires: [sonarr]")


@respx.mock
def test_karten9_ac9_the_pictures_of_a_preview_load_for_an_administrator_through_the_connection(admin: TestClient) -> None:
    sonarr = connection(admin)
    sonarr_serves(RECORDS)
    own = respx.get(f"{BASE}/p/a.jpg").mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    foreign = respx.get("https://img.example.com/b.jpg").mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    data = post(admin, "preview", {"yaml": covers(), "integration_id": sonarr}).json()
    arts = [item["art"] for item in data["items"]]
    assert all(art.startswith(f"/api/v1/cards/preview-image?integration_id={sonarr}&path=") for art in arts), arts
    first, second = (admin.get(art) for art in arts)
    assert first.status_code == second.status_code == 200 and first.content == PNG
    assert own.calls.last.request.headers["x-api-key"] == "key-1", "a path on the connection keeps its credentials"
    sent = {name.lower() for name in foreign.calls.last.request.headers}
    assert not sent & {"x-api-key", "authorization", "cookie"}, "the key of the connection went to another host"


@respx.mock
def test_karten9_ac9_demo_data_shows_no_pictures_of_the_service(admin: TestClient) -> None:
    data = post(admin, "preview", {"yaml": covers()}).json()
    assert all("art" not in item for item in data["items"])


@respx.mock
def test_karten9_ac9_the_picture_route_of_the_preview_fetches_nothing_that_no_card_named(admin: TestClient) -> None:
    sonarr = connection(admin)
    reached = respx.route().mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    for path in ("/api/v3/system/status", "/_connection?u=%2Fsecret&s=" + "0" * 32, "/_external?u=http%3A%2F%2Fevil.example.com%2Fa.png&s=" + "0" * 32, "//evil.example.com/a", "http://evil.example.com/a.png"):
        answer = admin.get(f"{API}/preview-image", params={"integration_id": sonarr, "path": path})
        assert answer.status_code == 400, (path, answer.status_code)
    assert not reached.called


@respx.mock
def test_karten9_ac9_a_signature_for_one_connection_does_not_open_another(admin: TestClient) -> None:
    sonarr = connection(admin)
    other = admin.post("/api/v1/integrations", json={"kind": "sonarr", "name": "Second", "config": {"url": "http://second.example.com:8080", "api_key": "key-2"}}, headers=CSRF).json()["id"]
    reached = respx.route().mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    art = images.reference("/p/a.jpg", BASE).removeprefix("proxy:")
    assert admin.get(f"{API}/preview-image", params={"integration_id": sonarr, "path": art}).status_code == 200
    answer = admin.get(f"{API}/preview-image", params={"integration_id": other, "path": art})
    assert answer.status_code == 400 and not any("second.example.com" in str(call.request.url) for call in reached.calls)


@respx.mock
@pytest.mark.parametrize("address", ["http://127.0.0.1:8080/a.png", "http://169.254.169.254/latest/a.png", "http://10.0.0.5/a.png", "http://localhost/a.png"])
def test_karten9_ac9_the_picture_route_of_the_preview_keeps_the_network_rule_for_a_foreign_address(admin: TestClient, address: str) -> None:
    sonarr = connection(admin)
    reached = respx.route().mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    art = images.reference(address, BASE).removeprefix("proxy:")
    answer = admin.get(f"{API}/preview-image", params={"integration_id": sonarr, "path": art})
    assert answer.status_code == 404 and answer.json()["detail"]["code"] == "forbidden_host" and not reached.called


# -- AC-10: examples made from real answers --------------------------------------------------------------


REAL = {
    "records": [
        {
            "title": f"Private Film {n}", "year": 2000 + n, "size": 5_368_709_120 + n, "ratio": 4.25 + n / 10, "ok": n % 2 == 0, "nothing": None,
            "added": "2026-10-01T12:30:00Z", "on": "2026-10-02", "poster": f"https://image.tmdb.example.org/t/p/{n}/abc.jpg",
            "path": f"/MediaCover/{n}/poster.jpg", "owner": f"anna.weber{n}@family.example.org", "host": f"nas{n}.home.arpa", "ip": f"10.20.30.{n + 1}",
            "mac": f"aa:bb:cc:dd:ee:{n:02x}", "code": f"S01E0{n}", "tags": ["secret", "Holiday 2025"], "nested": {"city": "Springfield", "count": 7 + n},
        }
        for n in range(30)
    ],
    "total": 12345, "name": "Anna's Server", "version": "1.41.3.9314", "stamp": 1_761_998_400,
}
KEPT_STRINGS = {"2026-10-01T12:30:00Z", "2026-10-02"}


def leaves(value: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        return [leaf for key, one in value.items() for leaf in leaves(one, f"{path}.{key}")]
    if isinstance(value, list):
        return [leaf for n, one in enumerate(value) for leaf in leaves(one, f"{path}[{n}]")]
    return [(path, value)]


def keys_of(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: keys_of(one) for key, one in value.items()}
    if isinstance(value, list):
        return [keys_of(one) for one in value]
    return type(value).__name__ if not isinstance(value, bool) else "bool"


def test_karten9_ac10_nothing_of_a_text_or_a_number_comes_out_as_it_went_in() -> None:
    made, cut = demo.disguise({"queue": REAL})
    assert cut is True
    kept = {**REAL, "records": REAL["records"][: len(made["queue"]["records"])]}
    before, after = leaves(kept), leaves(made["queue"])
    assert [path for path, _ in before] == [path for path, _ in after], "the same places"
    checked = 0
    for (path, old), (_same, new) in zip(before, after, strict=True):
        if isinstance(old, bool) or old is None or old in KEPT_STRINGS or old == REAL["stamp"]:
            assert new == old, path
        else:
            assert new != old, (path, old)
            checked += 1
    assert checked > 150
    text_out = json.dumps(made)
    for word in ("Private Film", "anna.weber", "family.example.org", "home.arpa", "10.20.30.", "Anna", "Springfield", "Holiday", "tmdb", "5368709120"):
        assert word not in text_out, word


def test_karten9_ac10_keys_the_shape_booleans_null_and_dates_stay() -> None:
    made, _cut = demo.disguise({"queue": REAL})
    shape = keys_of(made["queue"])
    assert list(shape) == list(keys_of(REAL)) and set(shape["records"][0]) == set(keys_of(REAL["records"][0]))
    first = made["queue"]["records"][0]
    assert first["nothing"] is None and first["ok"] is True and made["queue"]["records"][1]["ok"] is False
    assert first["added"] == "2026-10-01T12:30:00Z" and first["on"] == "2026-10-02"
    assert made["queue"]["stamp"] == REAL["stamp"], "a moment in time is a date"
    assert isinstance(first["size"], int) and isinstance(first["ratio"], float) and isinstance(first["tags"][0], str)


def test_karten9_ac10_lists_are_cut_and_the_answer_fits_into_a_definition() -> None:
    made, cut = demo.disguise({"queue": REAL})
    assert cut and len(made["queue"]["records"]) <= demo.ENTRIES[0]
    assert len(json.dumps(made)) <= demo.MAX_CHARS
    huge, shortened = demo.disguise({"a": [{"text": "word " * 60, "n": n} for n in range(500)]})
    assert shortened and len(json.dumps(huge)) <= demo.MAX_CHARS and len(huge["a"]) < demo.ENTRIES[0] + 1


def test_karten9_ac10_addresses_become_addresses_on_example_com_and_the_documentation_ranges() -> None:
    made, _cut = demo.disguise({"queue": REAL})
    first = made["queue"]["records"][0]
    assert re.fullmatch(r"https://example\.com/[0-9a-f]{10}\.jpg", first["poster"]) and re.fullmatch(r"https://example\.com/[0-9a-f]{10}\.jpg", first["path"])
    assert re.fullmatch(r"user-[0-9a-f]{6}@example\.com", first["owner"]) and re.fullmatch(r"host-[0-9a-f]{5}\.example", first["host"])
    assert re.fullmatch(r"192\.0\.2\.\d{1,3}", first["ip"]) and first["mac"].startswith("02:00:00:00:")


def test_karten9_ac10_the_same_value_is_the_same_stand_in_everywhere_and_two_values_are_two() -> None:
    again = {"other": {"deep": [{"name": "Private Film 3", "n": 12345}]}, "x": [{"name": "Private Film 4"}]}
    made, _ = demo.disguise({"queue": REAL, **again})
    assert made["other"]["deep"][0]["name"] == made["queue"]["records"][3]["title"]
    assert made["other"]["deep"][0]["n"] == made["queue"]["total"]
    assert made["x"][0]["name"] != made["other"]["deep"][0]["name"]
    assert demo.disguise({"queue": REAL}) == demo.disguise({"queue": REAL}), "the same input, the same examples"


@pytest.mark.parametrize("number", [0, 1, -2, 3, 4, 7, 50, 99, 100, 365, 1080, 5_368_709_120, -17, 0.5, 4.25, 99.9, 100.0, 1e-5, 12345.678, 10**30])
def test_karten9_ac10_a_number_becomes_another_number_of_about_its_size(number: float) -> None:
    out = demo.disguise_number(number)
    assert out != number and type(out) is type(number)
    if abs(number) > 3:
        assert 0.3 * abs(number) <= abs(out) <= 1.7 * abs(number) or abs(number) < 1
    if 0 <= number <= 100:
        assert 0 <= out <= 100 or number < 3, "a percentage stays within a hundred"


@pytest.mark.parametrize("word", ["ok", "A", "I", "Hello World", "S01E02 - Pilot", "x264", "4K", "Müller", "1080p", "Ünïcode ²", "ok.", "a-b_c"])
def test_karten9_ac10_every_kind_of_text_changes_and_keeps_its_punctuation(word: str) -> None:
    out = demo.disguise_text(word)
    assert out != word and out
    assert re.sub(r"[^\W_]+", "", out) == re.sub(r"[^\W_]+", "", word), "spaces and punctuation stay where they were"


@pytest.mark.parametrize("word", ["", " ", "---", "·", "%", "2026-10-01", "2026-10-01T12:30:00+02:00", "12:30", "Mon, 02 Jan 2006 15:04:05 GMT"])
def test_karten9_ac10_a_date_a_time_and_a_text_without_letters_or_digits_stay(word: str) -> None:
    assert demo.disguise_text(word) == word


def test_karten9_ac10_a_text_of_a_thousand_characters_is_cut_first() -> None:
    made, cut = demo.disguise({"q": {"t": "word " * 400, "u": "x" * 5000}})
    assert cut and len(made["q"]["t"]) <= demo.TEXT_CHARS and len(made["q"]["u"]) <= demo.TEXT_CHARS


def test_karten9_ac10_answers_too_large_for_a_definition_even_cut_to_one_entry_are_refused() -> None:
    from app.adapters.base import AdapterError

    with pytest.raises(AdapterError) as failure:
        demo.disguise({"q": {f"key{n}": "word " * 50 for n in range(2000)}})
    assert failure.value.code == "demo_too_large"


@respx.mock
def test_karten9_ac10_the_endpoint_asks_every_request_and_answers_with_made_up_examples(admin: TestClient) -> None:
    sonarr = connection(admin)
    sonarr_serves({"totalRecords": 12, "records": [{"title": f"Private Film {n}", "size": 100 * n} for n in range(30)]})
    answer = post(admin, "demo", {"yaml": VALUE_CARD, "integration_id": sonarr})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    queue = body["demo"]["queue"]
    assert list(body["demo"]) == ["queue"] and body["cut"] is True and len(queue["records"]) == 10
    assert queue["totalRecords"] != 12 and "Private Film" not in json.dumps(body)
    # What came back is a good demo: taking it over gives a card that still works.
    taken = VALUE_CARD.split("demo:")[0] + "demo:\n  queue: " + json.dumps(queue) + "\n"
    assert post(admin, "check", {"yaml": taken}).json() == {"ok": True}
    assert post(admin, "preview", {"yaml": taken}).status_code == 200


@respx.mock
def test_karten9_ac10_the_endpoint_refuses_a_connection_of_the_wrong_kind_and_a_failing_service(admin: TestClient) -> None:
    lidarr = connection(admin, "lidarr")
    assert post(admin, "demo", {"yaml": VALUE_CARD, "integration_id": lidarr}).json()["detail"]["code"] == "kind_mismatch"
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(500))
    assert post(admin, "demo", {"yaml": VALUE_CARD, "integration_id": sonarr}).json()["detail"]["code"] == "http_error"


# -- the line in the YAML view (KARTEN-10) --------------------------------------------------------------


def test_karten10_the_check_says_ok_or_lists_every_problem_with_its_line(admin: TestClient) -> None:
    assert post(admin, "check", {"yaml": VALUE_CARD}).json() == {"ok": True}
    wrong = changed("form: value", "form: dial")
    body = post(admin, "check", {"yaml": wrong}).json()
    assert body["ok"] is False and body["problems"] == admin.post(API, json={"yaml": wrong}, headers=CSRF).json()["detail"]["problems"]
    assert body["problems"][0]["line"] and body["problems"][0]["code"]
    assert admin.get(API).json()["cards"] == [], "checking saves nothing"
    broken = post(admin, "check", {"yaml": "name: [unclosed"}).json()
    assert broken["ok"] is False and broken["problems"][0]["code"] == "card_yaml"


# -- EC-3: two administrators --------------------------------------------------------------------------


def read(client: TestClient, slug: str = "queue-size") -> dict[str, Any]:
    return client.get(f"{API}/{slug}").json()


def test_karten9_ec3_a_save_over_a_text_somebody_saved_meanwhile_is_refused_with_who_and_when(admin: TestClient) -> None:
    add(admin)
    opened = read(admin)["updated_at"]
    second = create_user(admin, "second", role="admin")
    login(admin, "second", "another-long-password")
    mine = changed('version: "1.0.0"', 'version: "1.1.0"')
    assert admin.put(f"{API}/queue-size", json={"yaml": mine, "base": opened}, headers=CSRF).status_code == 200
    as_admin(admin)
    theirs = changed('version: "1.0.0"', 'version: "2.0.0"')
    refused = admin.put(f"{API}/queue-size", json={"yaml": theirs, "base": opened}, headers=CSRF)
    detail = refused.json()["detail"]
    assert refused.status_code == 409 and detail["code"] == "card_changed_meanwhile" and detail["by"] == "second" and detail["at"]
    assert second and read(admin)["version"] == "1.1.0", "nothing was overwritten"
    assert detail["at"] == read(admin)["updated_at"]


def test_karten9_ec3_overwrite_saves_anyway_and_reload_gives_the_new_base(admin: TestClient) -> None:
    add(admin)
    opened = read(admin)["updated_at"]
    admin.put(f"{API}/queue-size", json={"yaml": changed('version: "1.0.0"', 'version: "1.1.0"'), "base": opened}, headers=CSRF)
    theirs = changed('version: "1.0.0"', 'version: "2.0.0"')
    forced = admin.put(f"{API}/queue-size", json={"yaml": theirs, "base": opened, "overwrite": True}, headers=CSRF)
    assert forced.status_code == 200 and forced.json()["version"] == "2.0.0"
    fresh = forced.json()["updated_at"]
    assert admin.put(f"{API}/queue-size", json={"yaml": theirs, "base": fresh}, headers=CSRF).status_code == 200, "the answer carries the base for the next save"


def test_karten9_ec3_a_save_without_a_base_works_as_it_always_did(admin: TestClient) -> None:
    add(admin)
    assert admin.put(f"{API}/queue-size", json={"yaml": VALUE_CARD}, headers=CSRF).status_code == 200


def test_karten9_ec3_two_saves_in_the_same_second_have_two_different_times(admin: TestClient) -> None:
    add(admin)
    times = [read(admin)["updated_at"]]
    for number in range(5):
        saved = admin.put(f"{API}/queue-size", json={"yaml": changed('version: "1.0.0"', f'version: "1.0.{number + 1}"'), "base": times[-1]}, headers=CSRF)
        assert saved.status_code == 200, saved.text
        times.append(saved.json()["updated_at"])
    assert len(set(times)) == len(times)


def test_karten9_ec3_even_a_clock_that_stands_still_does_not_repeat_a_time(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    add(admin)
    before = read(admin)["updated_at"]
    with db_session() as db:
        stuck = db.scalar(select(CardRecord.updated_at).where(CardRecord.slug == "queue-size"))
    monkeypatch.setattr(store, "utcnow", lambda: stuck)
    saved = admin.put(f"{API}/queue-size", json={"yaml": changed('version: "1.0.0"', 'version: "1.0.1"'), "base": before}, headers=CSRF)
    assert saved.status_code == 200 and saved.json()["updated_at"] != before
    refused = admin.put(f"{API}/queue-size", json={"yaml": VALUE_CARD, "base": before}, headers=CSRF)
    assert refused.status_code == 409, "the old base is a different time even when the clock did not move"


def test_karten9_ec3_a_base_that_is_no_time_is_refused(admin: TestClient) -> None:
    add(admin)
    answer = admin.put(f"{API}/queue-size", json={"yaml": VALUE_CARD, "base": "yesterday"}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "bad_base"


def test_karten9_ec3_who_saved_last_is_still_named_after_that_account_was_deleted(admin: TestClient) -> None:
    add(admin)
    opened = read(admin)["updated_at"]
    second = create_user(admin, "second", role="admin")
    login(admin, "second", "another-long-password")
    admin.put(f"{API}/queue-size", json={"yaml": changed('version: "1.0.0"', 'version: "1.1.0"'), "base": opened}, headers=CSRF)
    as_admin(admin)
    assert admin.delete(f"/api/v1/users/{second['id']}?boards=hand_over", headers=CSRF).status_code == 204
    detail = admin.put(f"{API}/queue-size", json={"yaml": VALUE_CARD, "base": opened}, headers=CSRF).json()["detail"]
    assert detail["code"] == "card_changed_meanwhile" and detail["by"] in (ADMIN["username"], None)


def test_karten9_ec3_a_save_that_loses_to_a_text_with_problems_changes_nothing(admin: TestClient) -> None:
    add(admin)
    opened = read(admin)["updated_at"]
    bad = admin.put(f"{API}/queue-size", json={"yaml": changed("form: value", "form: dial"), "base": opened}, headers=CSRF)
    assert bad.status_code == 400 and read(admin)["updated_at"] == opened, "a refused text does not move the time"


# -- the column and the old database -------------------------------------------------------------------


def test_karten9_the_database_of_an_earlier_build_gets_the_column_and_the_cards_stay(admin: TestClient) -> None:
    from app.migrations import MIGRATIONS

    add(admin)
    engine = get_engine()
    old = "id, slug, kind, yaml_source, definition, origin, shop_ref, shop_version, users_may_place, created_by, created_at, updated_at"
    with engine.begin() as connection_:
        # The table as an earlier build made it: the same, without the last column.
        connection_.execute(text(f"CREATE TABLE card_old AS SELECT {old} FROM card_definitions"))
        connection_.execute(text("DROP TABLE card_definitions"))
        connection_.execute(text(
            "CREATE TABLE card_definitions (id INTEGER NOT NULL PRIMARY KEY, slug VARCHAR(60) NOT NULL, kind VARCHAR(20) NOT NULL, yaml_source TEXT NOT NULL, "
            "definition JSON NOT NULL, origin VARCHAR(10) NOT NULL, shop_ref VARCHAR(200) NOT NULL, shop_version VARCHAR(20) NOT NULL, "
            "users_may_place BOOLEAN NOT NULL, created_by INTEGER REFERENCES users (id) ON DELETE SET NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        connection_.execute(text("CREATE UNIQUE INDEX ix_card_definitions_slug ON card_definitions (slug)"))
        connection_.execute(text(f"INSERT INTO card_definitions ({old}) SELECT {old} FROM card_old"))
        connection_.execute(text("DROP TABLE card_old"))
        columns = {row[1] for row in connection_.execute(text("PRAGMA table_info(card_definitions)"))}
    assert "updated_by" not in columns
    step = {version: function for version, _description, function in MIGRATIONS}[25]
    with engine.begin() as connection_:
        step(connection_)
        step(connection_)
        columns = {row[1] for row in connection_.execute(text("PRAGMA table_info(card_definitions)"))}
    assert "updated_by" in columns
    store.invalidate()
    opened = read(admin)
    assert opened["slug"] == "queue-size"
    admin.put(f"{API}/queue-size", json={"yaml": changed('version: "1.0.0"', 'version: "1.2.0"'), "base": opened["updated_at"]}, headers=CSRF)
    refused = admin.put(f"{API}/queue-size", json={"yaml": VALUE_CARD, "base": opened["updated_at"]}, headers=CSRF)
    detail = refused.json()["detail"]
    assert refused.status_code == 409 and detail["by"] == ADMIN["username"]


def test_karten9_the_short_name_of_the_picture_address_is_kept(admin: TestClient) -> None:
    answer = add(admin, text_of("preview-image"))
    assert answer.status_code == 400 and answer.json()["detail"]["first"] == "card_slug_reserved"


# -- AC-13: saved means live ----------------------------------------------------------------------------


@respx.mock
async def test_karten9_ac13_a_saved_text_shows_on_every_board_at_once_and_stands_in_the_journal(
    admin: TestClient, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.sse import board_topic, hub
    from app.services.state import live

    sonarr = connection(admin)
    sonarr_serves()
    add(admin)
    ids = []
    boards = []
    for name in ("One", "Two"):
        board = admin.post("/api/v1/boards", json={"name": name}, headers=CSRF).json()
        boards.append(board["id"])
        ids.append(admin.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "custom.value", "integration_id": sonarr, "options": {"card": "queue-size"}}, headers=CSRF).json()["widget"]["id"])
    for widget in ids:
        await collector.refresh(widget)
        assert live.get(widget).primary["unit"] == "items"
    listening = [hub.subscribe({board_topic(one)}) for one in boards]
    scheduled: list[int] = []
    monkeypatch.setattr(collector, "schedule", scheduled.append)
    with caplog.at_level("INFO", logger="nexdeck.cards"):
        saved = admin.put(f"{API}/queue-size", json={"yaml": changed("unit: items", "unit: rows"), "base": read(admin)["updated_at"]}, headers=CSRF)
    assert saved.status_code == 200 and sorted(scheduled) == sorted(ids), "every widget of the card fetches again"
    assert [one.queue.qsize() for one in listening] == [1, 1], "every open board is told"
    for one in listening:
        hub.unsubscribe(one)
    for widget in ids:
        await collector.refresh(widget)
        assert live.get(widget).primary["unit"] == "rows", "the new text is what every board shows"
    assert "Custom card 'queue-size' changed by" in caplog.text
    with db_session() as db:
        lines = [(one.kind, one.name, one.detail, one.user_id is not None) for one in db.scalars(select(Event).where(Event.kind == "card_definition_changed"))]
    assert lines == [("card_definition_changed", "queue-size", "text changed", True)]


def test_karten9_ac10_no_whole_number_and_no_decimal_in_a_wide_range_is_ever_left_as_it_was() -> None:
    for number in range(-400, 2000):
        assert demo.disguise_number(number) != number, number
    for step in range(-300, 3000):
        number = step / 10
        assert demo.disguise_number(number) != number, number


# -- corrections after the review ------------------------------------------------------------------------


def signed(path: str) -> str:
    return images.reference(path, BASE).removeprefix("proxy:")


def widget_of_connection(admin: TestClient, sonarr: int) -> int:
    add(admin)
    page = admin.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()["pages"][0]["id"]
    made = admin.post(f"/api/v1/pages/{page}/widgets", json={"kind": "custom.value", "integration_id": sonarr, "options": {"card": "queue-size"}}, headers=CSRF)
    return int(made.json()["widget"]["id"])


@respx.mock
@pytest.mark.parametrize("target", ["https://evil.example.org/steal.png", "http://svc.example.com:9090/a.png", "https://svc.example.com:8080/a.png", "http://other.example.com:8080/a.png"])
def test_karten9_a_picture_that_the_service_passes_on_to_another_host_is_not_followed_and_takes_no_key(admin: TestClient, target: str) -> None:
    """⚠️ Another scheme, host or port is another place: the key of the connection must not go there."""
    sonarr = connection(admin)
    respx.get(f"{BASE}/p/a.jpg").mock(return_value=httpx.Response(302, headers={"location": target}))
    elsewhere = respx.route().mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    widget = widget_of_connection(admin, sonarr)
    for url in (f"{API}/preview-image", f"/api/v1/widgets/{widget}/image"):
        params = {"path": signed("/p/a.jpg"), **({"integration_id": sonarr} if url.startswith(API) else {})}
        answer = admin.get(url, params=params)
        assert answer.status_code == 404 and answer.json()["detail"]["code"] == "no_image", (url, answer.status_code)
    assert not elsewhere.called, "nothing was asked of the other place"


@respx.mock
def test_karten9_a_picture_that_the_service_moves_within_its_own_address_is_followed_with_the_key(admin: TestClient) -> None:
    sonarr = connection(admin)
    respx.get(f"{BASE}/p/a.jpg").mock(return_value=httpx.Response(302, headers={"location": "/p/b.jpg"}))
    moved = respx.get(f"{BASE}/p/b.jpg").mock(return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    widget = widget_of_connection(admin, sonarr)
    for url, extra in ((f"{API}/preview-image", {"integration_id": sonarr}), (f"/api/v1/widgets/{widget}/image", {})):
        answer = admin.get(url, params={"path": signed("/p/a.jpg"), **extra})
        assert answer.status_code == 200 and answer.content == PNG, url
    assert moved.calls.last.request.headers["x-api-key"] == "key-1"


@respx.mock
def test_karten9_a_picture_that_is_passed_on_in_circles_ends_in_the_placeholder_not_in_a_hang(admin: TestClient) -> None:
    sonarr = connection(admin)
    respx.get(f"{BASE}/p/a.jpg").mock(return_value=httpx.Response(302, headers={"location": "/p/a.jpg"}))
    answer = admin.get(f"{API}/preview-image", params={"integration_id": sonarr, "path": signed("/p/a.jpg")})
    assert answer.status_code == 404 and answer.json()["detail"]["code"] == "no_image"


@respx.mock
@pytest.mark.parametrize("path", ["/api/v3/queue?apikey=SuperSecret123456", "/api/v3/queue?token=abcdef0123456789abcdef", "/api/v3/ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"])
def test_karten9_ec4_a_path_with_a_secret_in_it_is_refused_like_a_card_and_leaves_no_trace(admin: TestClient, caplog: pytest.LogCaptureFixture, path: str) -> None:
    sonarr = connection(admin)
    reached = respx.route().mock(return_value=httpx.Response(200, json={}))
    with caplog.at_level("DEBUG"):
        answer = post(admin, "probe", {"integration_id": sonarr, "path": path})
    detail = answer.json()["detail"]
    assert answer.status_code == 400 and detail["code"] == "card_secret_value" and detail["message"] and not reached.called
    # The same word the card gives for the same line.
    card = admin.post(f"{API}/check", json={"yaml": changed("path: /api/v3/queue", f"path: {path}")}, headers=CSRF).json()
    assert [problem["code"] for problem in card["problems"]] == ["card_secret_value"]
    with db_session() as db:
        everything = json.dumps([[getattr(one, column.name) for column in Event.__table__.columns] for one in db.scalars(select(Event))], default=str)
    secret = path.split("=")[-1].split("/")[-1]
    assert secret not in everything and secret not in caplog.text and secret not in answer.text


@respx.mock
def test_karten9_ec4_a_probe_that_failed_stands_in_the_chronicle_with_its_reason_and_nothing_of_the_answer(admin: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    sonarr = connection(admin)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(500, text="Private Film Title exploded"))
    with caplog.at_level("DEBUG"):
        assert post(admin, "probe", {"integration_id": sonarr, "path": "/api/v3/queue"}).status_code == 502
        assert post(admin, "probe", {"integration_id": 999, "path": "/api/v3/queue"}).status_code == 404
    with db_session() as db:
        lines = [(one.level, one.integration_id, one.detail) for one in db.scalars(select(Event).where(Event.kind == "card_probe").order_by(Event.id))]
        everything = json.dumps([[getattr(one, column.name) for column in Event.__table__.columns] for one in db.scalars(select(Event))], default=str)
    assert lines == [("warn", sonarr, "[http_error] /api/v3/queue"), ("warn", None, "[no_integration] /api/v3/queue")]
    assert "Private Film" not in everything and "Private Film" not in caplog.text


def test_karten9_ec3_two_saves_at_the_same_moment_cannot_both_win(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The comparison and the write are one step (``store.saving``); a slow write makes the race certain."""
    add(admin)
    opened = read(admin)["updated_at"]
    real = store.update

    def slow(*args: Any, **more: Any) -> Any:
        time.sleep(0.4)
        return real(*args, **more)

    monkeypatch.setattr(store, "update", slow)
    out: list[int] = []
    barrier = threading.Barrier(2)

    def go(version: str) -> None:
        barrier.wait()
        saved = admin.put(f"{API}/queue-size", json={"yaml": changed('version: "1.0.0"', f'version: "{version}"'), "base": opened}, headers=CSRF)
        out.append(saved.status_code)

    threads = [threading.Thread(target=go, args=(version,)) for version in ("2.0.0", "3.0.0")]
    for one in threads:
        one.start()
    for one in threads:
        one.join()
    assert sorted(out) == [200, 409]
