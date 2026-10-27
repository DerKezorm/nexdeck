"""KARTEN-3: describing an own connection, keeping it, changing it, deleting it (AC-1, AC-2, AC-7, AC-11, AC-12, EC-1, EC-5, EC-6, EC-10)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import REGISTRY, get_adapter
from app.db import db_session
from app.models import Integration

from .conftest import CSRF
from .karten3_sample import HEADER, MEMOS, changed, example
from .test_cards_editor_api import admin  # noqa: F401 - the fixture

API = "/api/v1/own-integrations"


def make(client: TestClient, text: str) -> httpx.Response:
    return client.post(API, json={"yaml": text}, headers=CSRF)


def problems_of(response: httpx.Response) -> list[dict[str, Any]]:
    return response.json()["detail"]["problems"]  # type: ignore[no-any-return]


def codes_of(response: httpx.Response) -> set[str]:
    return {one["code"] for one in problems_of(response)}


def connect(client: TestClient, kind: str, config: dict[str, Any]) -> int:
    response = client.post("/api/v1/integrations", json={"kind": kind, "name": "Mine", "config": config}, headers=CSRF)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_karten3_ac1_a_description_is_checked_like_a_card_and_every_problem_comes_with_its_line(admin: TestClient) -> None:  # noqa: F811
    bad = changed(HEADER, **{"fields.0.name": "Bad Name", "nobody": "x", "name": ""})
    response = make(admin, bad)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "integration_invalid"
    found = {one["path"]: one for one in problems_of(response)}
    assert set(found) == {"fields[0].name", "nobody", "name"}
    assert found["nobody"]["code"] == "card_unknown_field" and found["fields[0].name"]["code"] == "card_bad_form"
    assert all(one["line"] for one in problems_of(response))
    # what a schema cannot say comes in one answer too
    worse = changed(HEADER, **{"auth.value": "Token {nobody}", "test": "http://elsewhere.example.com/x"})
    found = {one["path"]: one for one in problems_of(make(admin, worse))}
    assert found["auth.value"]["code"] == "card_integration_placeholder_unknown"
    assert found["test"]["code"] == "card_integration_path" and found["test"]["line"]
    assert admin.get(API).json() == []


def test_karten3_ac1_a_card_is_no_connection_and_the_other_way_round(admin: TestClient) -> None:  # noqa: F811
    from .cards_sample import VALUE_CARD

    response = make(admin, VALUE_CARD)
    assert response.status_code == 400 and codes_of(response) == {"card_integration_marker"}
    card = admin.post("/api/v1/cards", json={"yaml": HEADER}, headers=CSRF)
    assert card.status_code == 400


def test_karten3_ac2_the_fields_are_text_secret_number_and_switch_with_a_label_and_a_help_and_the_address_comes_first(admin: TestClient) -> None:  # noqa: F811
    text = changed(
        HEADER,
        fields=[
            {"name": "name", "type": "text", "label": "Name", "help": "Who."},
            {"name": "key", "type": "secret", "label": "Key", "required": True},
            {"name": "port", "type": "number", "label": "Port", "default": 80},
            {"name": "fast", "type": "switch", "label": "Fast", "default": True},
        ],
        auth={"type": "header", "header": "X-Key", "value": "{key}"},
    )
    assert make(admin, text).status_code == 201
    adapters = {one["kind"]: one for one in admin.get("/api/v1/adapters").json()}
    adapter = adapters["custom:bookstack-own"]
    assert [one["name"] for one in adapter["fields"]] == ["url", "name", "key", "port", "fast", "insecure"]
    by_name = {one["name"]: one for one in adapter["fields"]}
    assert by_name["url"]["required"] and by_name["url"]["type"] == "url"
    assert (by_name["key"]["type"], by_name["key"]["secret"], by_name["key"]["required"]) == ("password", True, True)
    assert by_name["port"]["type"] == "number" and by_name["fast"]["type"] == "bool"
    assert by_name["name"]["help"] == "Who." and by_name["name"]["label"] == "Name"
    assert adapter["custom"] is True and adapters["sonarr"]["custom"] is False


def test_karten3_ac2_a_field_name_the_form_keeps_for_itself_or_that_stands_twice_is_refused(admin: TestClient) -> None:  # noqa: F811
    for name in ("url", "insecure", "ticket"):
        bad = changed(HEADER, fields=[{"name": name, "label": "X"}], auth={"type": "none"})
        response = make(admin, bad)
        assert response.status_code == 400 and "card_integration_field_reserved" in codes_of(response), name
    twice = changed(HEADER, fields=[{"name": "a", "label": "A"}, {"name": "a", "label": "B"}], auth={"type": "none"})
    assert "card_duplicate_key" in codes_of(make(admin, twice))
    many = changed(HEADER, fields=[{"name": f"f{n}", "label": "F"} for n in range(13)], auth={"type": "none"})
    assert "card_too_many" in codes_of(make(admin, many))


def test_karten3_ac12_the_fifty_first_is_refused_with_a_message(admin: TestClient) -> None:  # noqa: F811
    for number in range(50):
        assert make(admin, changed(HEADER, short=f"own-{number}")).status_code == 201
    response = make(admin, changed(HEADER, short="one-too-many"))
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "integration_limit"
    assert "50" in response.json()["detail"]["message"]
    assert len(admin.get(API).json()) == 50


@pytest.mark.parametrize("short", ["sonarr", "radarr", "custom", "core", "docker"])
def test_karten3_ec1_a_short_name_of_a_built_in_kind_is_refused(admin: TestClient, short: str) -> None:  # noqa: F811
    response = make(admin, changed(HEADER, short=short))
    assert response.status_code == 400 and "card_integration_short_taken" in codes_of(response)
    assert "custom:" + short not in REGISTRY


def test_karten3_ec1_a_short_name_may_be_used_once_and_does_not_change(admin: TestClient) -> None:  # noqa: F811
    assert make(admin, MEMOS).status_code == 201
    again = make(admin, MEMOS)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "integration_exists"
    other = admin.put(f"{API}/memos", json={"yaml": changed(MEMOS, short="other")}, headers=CSRF)
    assert other.status_code == 400 and "card_integration_short_changed" in codes_of(other)


def test_karten3_ac1_no_key_stands_in_a_description(admin: TestClient) -> None:  # noqa: F811
    for value in ("Bearer abcdefgh12345678", "ghp_" + "a1" * 15, "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0NTY3.abcdef1234"):
        response = make(admin, changed(HEADER, **{"auth.value": value}))
        assert response.status_code == 400 and "card_secret_value" in codes_of(response), value


def test_karten3_ac1_paths_stay_under_the_address_and_only_read(admin: TestClient) -> None:  # noqa: F811
    for path in ("//other.example.com/x", "/a/../b", "https://other.example.com/", "no-slash"):
        assert "card_integration_path" in codes_of(make(admin, changed(HEADER, test=path))), path
    acting = make(admin, changed(HEADER, test="/api/server?action=restart"))
    assert "card_integration_path_acts" in codes_of(acting)
    reads = make(admin, changed(HEADER, reads=[{"path": "/api/items/delete", "label": "No"}]))
    assert "card_integration_path_acts" in codes_of(reads)


def test_karten4_ec3_the_project_on_github_is_written_as_owner_name_or_as_its_address(admin: TestClient) -> None:  # noqa: F811
    for good in ("owner/name", "https://github.com/owner/name"):
        assert make(admin, changed(HEADER, short=f"gh-{len(good)}", github=good)).status_code == 201, good
    for bad in ("justaname", "https://example.com/owner/name", "owner/name/extra", "owner/..", "owner/.", "https://github.com/owner/../", "owner/..git"):
        assert "card_integration_github" in codes_of(make(admin, changed(HEADER, github=bad))), bad


def test_karten3_the_session_description_must_say_where_the_ticket_is_and_how_it_travels(admin: TestClient) -> None:  # noqa: F811
    assert "card_integration_ticket_json" in codes_of(make(admin, changed(MEMOS, **{"auth.ticket": {"from": "json"}})))
    assert "card_integration_pass_header" in codes_of(make(admin, changed(MEMOS, **{"auth.pass": {"as": "header"}})))
    assert "card_integration_pass_cookie" in codes_of(make(admin, changed(MEMOS, **{"auth.pass": {"as": "cookie"}})))
    assert "card_integration_expression" in codes_of(make(admin, changed(MEMOS, **{"auth.ticket": {"from": "json", "at": "a["}})))
    assert "card_integration_auth_needs" in codes_of(make(admin, changed(MEMOS, **{"auth.login": None})))
    assert "card_integration_placeholder_unknown" in codes_of(make(admin, changed(MEMOS, **{"auth.pass.value": "Bearer {nobody}"})))
    assert make(admin, MEMOS).status_code == 201


def test_karten3_only_administrators_describe_connections(client: TestClient) -> None:
    from .conftest import create_user, login, setup_admin

    setup_admin(client)
    create_user(client, "member")
    client.post("/api/v1/auth/logout", headers=CSRF)
    login(client, "member", "another-long-password")
    assert client.get(API).status_code == 403
    assert make(client, MEMOS).status_code == 403
    assert client.get(f"{API}/template").status_code == 403
    assert client.post(f"{API}/check", json={"yaml": MEMOS}, headers=CSRF).status_code == 403
    # the one description, to read, to change and to delete, is the administrators' as well
    assert client.get(f"{API}/memos").status_code == 403
    assert client.put(f"{API}/memos", json={"yaml": MEMOS}, headers=CSRF).status_code == 403
    assert client.delete(f"{API}/memos", headers=CSRF).status_code == 403


def test_karten3_a_description_stays_within_30_reads_and_64_kb(admin: TestClient) -> None:  # noqa: F811
    thirty = [{"path": f"/api/items/{number}", "label": f"Item {number}"} for number in range(30)]
    assert make(admin, changed(HEADER, short="reads-30", reads=thirty)).status_code == 201
    too_many = make(admin, changed(HEADER, short="reads-31", reads=thirty + [{"path": "/api/items/30", "label": "Item 30"}]))
    assert too_many.status_code == 400 and codes_of(too_many)
    assert admin.get(f"{API}/reads-31").status_code == 404
    long_text = make(admin, HEADER + "# " + "x" * 65_000)
    assert long_text.status_code == 400 and long_text.json()["detail"]["code"] == "integration_invalid"
    assert admin.get(f"{API}/bookstack-own").status_code == 404


def test_karten3_the_template_and_the_check_and_the_listing(admin: TestClient) -> None:  # noqa: F811
    template = admin.get(f"{API}/template").json()["yaml"]
    assert "example" in template.lower() or "my-service" in template
    assert admin.post(f"{API}/check", json={"yaml": template}, headers=CSRF).json() == {"ok": True}
    bad = admin.post(f"{API}/check", json={"yaml": changed(HEADER, short="sonarr")}, headers=CSRF).json()
    assert bad["ok"] is False and bad["problems"][0]["code"] == "card_integration_short_taken"
    assert admin.get(API).json() == []
    made = make(admin, MEMOS)
    assert made.status_code == 201
    one = made.json()
    assert one["short"] == "memos" and one["kind"] == "custom:memos" and one["connections"] == 0 and one["yaml"] == MEMOS
    listed = admin.get(API).json()
    assert [row["short"] for row in listed] == ["memos"] and "yaml" not in listed[0]
    assert admin.get(f"{API}/memos").json()["yaml"] == MEMOS
    assert admin.get(f"{API}/nobody").status_code == 404
    assert admin.get(f"{API}/nobody").json()["detail"]["code"] == "integration_not_found"


def test_karten3_ac11_a_change_holds_for_the_kind_at_once_and_a_second_administrator_is_told(admin: TestClient) -> None:  # noqa: F811
    made = make(admin, HEADER).json()
    old = get_adapter("custom:bookstack-own")
    saved = admin.put(f"{API}/bookstack-own", json={"yaml": changed(HEADER, name="Books", test="/api/other")}, headers=CSRF)
    assert saved.status_code == 200 and saved.json()["name"] == "Books"
    now = get_adapter("custom:bookstack-own")
    assert now is not old and now.label == "Books" and now.definition.test == "/api/other"
    # the editor read the old moment: a save over a newer one is told, unless it says overwrite
    late = admin.put(f"{API}/bookstack-own", json={"yaml": HEADER, "base": made["updated_at"]}, headers=CSRF)
    assert late.status_code == 409 and late.json()["detail"]["code"] == "integration_changed_meanwhile"
    assert late.json()["detail"]["by"] == "admin" and late.json()["detail"]["at"].endswith("Z")
    forced = admin.put(f"{API}/bookstack-own", json={"yaml": HEADER, "base": made["updated_at"], "overwrite": True}, headers=CSRF)
    assert forced.status_code == 200 and get_adapter("custom:bookstack-own").label == "BookStack"


def test_karten3_ec10_a_field_that_leaves_the_description_leaves_every_connection_secrets_included(admin: TestClient) -> None:  # noqa: F811
    assert make(admin, HEADER).status_code == 201
    number = connect(admin, "custom:bookstack-own", {"url": "http://svc.example.com", "token_id": "abc", "token_secret": "s3cret-value"})
    with db_session() as db:
        assert "token_secret" in db.get(Integration, number).config
    smaller = changed(HEADER, fields=[{"name": "token_id", "label": "Token ID"}], auth={"type": "header", "header": "X-Id", "value": "{token_id}"})
    assert admin.put(f"{API}/bookstack-own", json={"yaml": smaller}, headers=CSRF).status_code == 200
    with db_session() as db:
        config = db.get(Integration, number).config
    assert "token_secret" not in config and config["token_id"] == "abc" and config["url"] == "http://svc.example.com"
    # a field that changes its type loses the value too: a stored secret is not text
    retyped = changed(smaller, **{"fields.0.type": "secret"})
    assert admin.put(f"{API}/bookstack-own", json={"yaml": retyped}, headers=CSRF).status_code == 200
    with db_session() as db:
        assert "token_id" not in db.get(Integration, number).config


def test_karten3_ac7_a_secret_is_stored_encrypted_and_never_given_back(admin: TestClient) -> None:  # noqa: F811
    assert make(admin, HEADER).status_code == 201
    number = connect(admin, "custom:bookstack-own", {"url": "http://svc.example.com", "token_id": "abc", "token_secret": "s3cret-value-9"})
    with db_session() as db:
        stored = db.get(Integration, number).config
    assert stored["token_secret"] != "s3cret-value-9" and "s3cret" not in str(stored)
    shown = admin.get("/api/v1/integrations").json()[0]
    assert shown["config"]["token_secret"] == "********" and "s3cret" not in str(shown)
    assert shown["config"]["token_id"] == "abc" and shown["kind"] == "custom:bookstack-own"
    assert "s3cret" not in admin.get(f"{API}/bookstack-own").text


def test_karten3_ec5_a_required_field_left_empty_is_not_saved(admin: TestClient) -> None:  # noqa: F811
    assert make(admin, HEADER).status_code == 201
    body = {"kind": "custom:bookstack-own", "name": "Mine", "config": {"url": "http://svc.example.com", "token_id": "a"}}
    response = admin.post("/api/v1/integrations", json=body, headers=CSRF)
    assert response.status_code == 400 and "token_secret" in response.text


def test_karten3_ec6_a_deleted_kind_leaves_its_connections_and_a_description_with_the_same_name_brings_them_back(admin: TestClient) -> None:  # noqa: F811
    assert make(admin, HEADER).status_code == 201
    number = connect(admin, "custom:bookstack-own", {"url": "http://svc.example.com", "token_id": "a", "token_secret": "b" * 12})
    assert admin.delete(f"{API}/bookstack-own", headers=CSRF).status_code == 204
    assert "custom:bookstack-own" not in REGISTRY
    with db_session() as db:
        assert db.get(Integration, number) is not None
    assert make(admin, HEADER).status_code == 201
    assert "custom:bookstack-own" in REGISTRY
    shown = admin.get("/api/v1/integrations").json()
    assert [row["id"] for row in shown] == [number] and shown[0]["config"]["token_secret"] == "********"


def test_karten3_ec11_the_descriptions_are_read_again_at_the_start_and_after_a_restored_backup(admin: TestClient) -> None:  # noqa: F811
    from app.cards import integration_store

    assert make(admin, HEADER).status_code == 201
    REGISTRY.pop("custom:bookstack-own")
    with db_session() as db:
        assert integration_store.load_all(db) == 1
    assert get_adapter("custom:bookstack-own").label == "BookStack"
    assert make(admin, example("memos-cookie")).status_code == 201


CARD = """\
nexdeck-card: 1
slug: books-count
name: Books
version: "1.0.0"
requires: [custom:bookstack-own]
requests:
  - id: books
    path: /api/books
form: value
value:
  path: total
  label: Books
"""


@respx.mock
def test_karten3_ec6_nothing_that_walks_over_connections_falls_over_when_their_kind_is_gone(admin: TestClient) -> None:  # noqa: F811
    from .test_cards_router import BASE, add, page_of, place

    respx.get(f"{BASE}/api/books").mock(return_value=httpx.Response(200, json={"total": 7}))
    assert make(admin, HEADER).status_code == 201
    assert add(admin, CARD).status_code == 201
    number = connect(admin, "custom:bookstack-own", {"url": BASE, "token_id": "a", "token_secret": "b" * 12})
    widget = place(admin, page_of(admin), number, card="books-count").json()["widget"]["id"]
    from .test_cards_editor_api import post

    assert post(admin, "preview", {"yaml": CARD, "integration_id": number}).status_code == 200
    board = admin.get("/api/v1/boards").json()[0]["slug"]

    assert admin.delete(f"{API}/bookstack-own", headers=CSRF).status_code == 204
    # the connection stands, says that its kind is missing, and shows none of its settings
    listed = admin.get("/api/v1/integrations")
    assert listed.status_code == 200 and listed.json()[0]["missing"] is True and listed.json()[0]["config"] == {}
    pressed = admin.post(f"/api/v1/integrations/{number}/test", headers=CSRF)
    assert pressed.status_code == 200 and pressed.json()["code"] == "integration_missing" and pressed.json()["message"] == "integration missing"
    # the card on it says the same instead of failing
    shown = post(admin, "preview", {"yaml": CARD, "integration_id": number})
    assert shown.status_code == 502 and shown.json()["detail"]["code"] == "integration_missing"
    assert admin.get(f"/api/v1/widgets/{widget}/data").status_code == 200
    # and the places that look at every connection go on
    for path in (
        "/api/v1/integrations/versions", f"/api/v1/integrations/{number}/choices/x", f"/api/v1/integrations/{number}/barred/x",
        f"/api/v1/boards/{board}", f"/api/v1/boards/{board}/export", "/api/v1/search", "/api/v1/search/suggestions",
        "/api/v1/cards/library", "/api/v1/cards", "/api/v1/cards/sources", "/api/v1/templates", "/api/v1/adapters",
    ):
        assert admin.get(path).status_code < 500, path
    renamed = admin.patch(f"/api/v1/integrations/{number}", json={"name": "Still mine"}, headers=CSRF)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Still mine"
    # a description with the same name brings it back at once
    assert make(admin, HEADER).status_code == 201
    back = admin.get("/api/v1/integrations").json()[0]
    assert back["missing"] is False and back["config"]["token_id"] == "a"
    assert admin.delete(f"/api/v1/integrations/{number}", headers=CSRF).status_code == 204


def test_karten3_ec11_a_restored_backup_brings_the_kinds_and_their_connections_with_their_secrets(client: TestClient) -> None:
    from .conftest import setup_admin
    from .test_backup import PASSWORD, _archive, _make, _upload

    setup_admin(client)
    assert make(client, HEADER).status_code == 201
    number = connect(client, "custom:bookstack-own", {"url": "http://svc.example.com", "token_id": "abc", "token_secret": "s3cret-value-9"})
    blob = _archive(client, _make(client)["name"], PASSWORD)
    assert client.delete(f"{API}/bookstack-own", headers=CSRF).status_code == 204
    assert client.put(f"{API}/memos", json={"yaml": MEMOS}, headers=CSRF).status_code == 404
    assert make(client, MEMOS).status_code == 201, "a kind that is not in the backup"
    assert "custom:bookstack-own" not in REGISTRY

    assert _upload(client, blob).status_code == 200
    # the running instance reads the restored descriptions without a restart
    assert "custom:bookstack-own" in REGISTRY and "custom:memos" not in REGISTRY
    after = TestClient(client.app)
    after.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse-battery"})
    assert [row["short"] for row in after.get(API).json()] == ["bookstack-own"]
    shown = after.get("/api/v1/integrations").json()
    assert [row["id"] for row in shown] == [number] and shown[0]["missing"] is False
    from app.services.integrations import resolve_config

    with db_session() as db:
        assert resolve_config(db.get(Integration, number))["token_secret"] == "s3cret-value-9"


@pytest.mark.parametrize("name", ["wikijs", "bookstack", "apikey-in-address", "memos", "memos-cookie"])
def test_karten3_the_example_descriptions_are_valid_and_hold_no_key(admin: TestClient, name: str) -> None:  # noqa: F811
    assert make(admin, example(name)).status_code == 201


def test_karten3_the_reads_of_the_description_are_offered_for_the_data_step_and_the_kind_is_among_the_sources(admin: TestClient) -> None:  # noqa: F811
    assert make(admin, MEMOS).status_code == 201
    reads = admin.get("/api/v1/cards/sources/custom:memos/reads")
    assert reads.status_code == 200
    assert reads.json() == {"reads": [{"path": "/api/v1/memos?pageSize=10", "label": "Latest notes", "widgets": []}]}
    sources = {one["kind"]: one for one in admin.get("/api/v1/cards/sources").json()}
    assert sources["custom:memos"] == {"kind": "custom:memos", "label": "Memos", "icon": "memos", "category": "other", "custom": True}
    assert sources["sonarr"]["custom"] is False
    assert admin.get("/api/v1/cards/sources/custom:nobody/reads").status_code == 404


def test_karten3_ac7_a_secret_is_never_in_the_export_of_a_board_only_a_reference_to_the_environment(admin: TestClient) -> None:  # noqa: F811
    assert make(admin, HEADER).status_code == 201
    number = connect(admin, "custom:bookstack-own", {"url": "http://svc.example.com", "token_id": "abc", "token_secret": "s3cret-value-9"})
    from .test_cards_router import add, page_of, place

    assert add(admin, CARD).status_code == 201
    assert place(admin, page_of(admin), number, card="books-count").status_code == 201
    slug = next(board["slug"] for board in admin.get("/api/v1/boards").json() if board["name"] == "Wall")
    exported = admin.get(f"/api/v1/boards/{slug}/export")
    assert exported.status_code == 200 and "s3cret" not in exported.text
    assert "${NEXDECK_CUSTOM_BOOKSTACK_OWN_" in exported.text and "_TOKEN_SECRET}" in exported.text


def test_karten3_ac6_the_sign_in_path_is_refused_when_it_names_a_word_that_acts(admin: TestClient) -> None:  # noqa: F811
    # The one POST of an own connection goes with the user name and the password: it must not reach a path that acts.
    for login in ("/api/v1/system/restart", "/api/v1/users/delete", "/api/factory-reset"):
        checked = admin.post(f"{API}/check", json={"yaml": changed(MEMOS, short="acting", **{"auth.login": login})}, headers=CSRF).json()
        assert checked["ok"] is False and [one["code"] for one in checked["problems"]] == ["card_integration_path_acts"], login
        assert checked["problems"][0]["path"].startswith("auth.login"), checked
    assert admin.post(f"{API}/check", json={"yaml": MEMOS}, headers=CSRF).json()["ok"] is True
