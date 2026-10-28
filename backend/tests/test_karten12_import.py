"""KARTEN-12: reading a file of cards and own connections and making them (AC-2, AC-3, AC-4, EC-1, EC-2, EC-5, EC-6, EC-7)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.adapters import get_adapter
from app.cards import store
from app.db import db_session
from app.models import CardRecord, Event, OwnIntegration
from app.services.collector import collector

from .cards_sample import changed
from .conftest import CSRF, create_user, login, setup_admin
from .karten8_sample import DOWNLOADS
from .karten12_sample import CARD, INTEGRATION, PLAIN, SHORT, card, separated

OWN = f"integration:{SHORT}"
VERSION = 'version: "1.0.0"'


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    return client


def check(client: TestClient, text: str):  # noqa: ANN202
    return client.post("/api/v1/cards/import/check", json={"text": text}, headers=CSRF)


def run(client: TestClient, text: str, choices: dict[str, str] | None = None):  # noqa: ANN202
    return client.post("/api/v1/cards/import", json={"text": text, "choices": choices or {}}, headers=CSRF)


def slugs() -> list[str]:
    with db_session() as db:
        return sorted(db.scalars(select(CardRecord.slug)))


def shorts() -> list[str]:
    with db_session() as db:
        return sorted(db.scalars(select(OwnIntegration.short)))


def text_of(slug: str) -> str:
    with db_session() as db:
        return db.scalar(select(CardRecord.yaml_source).where(CardRecord.slug == slug)) or ""


def code_of(response: Any) -> str:
    return str(response.json()["detail"]["code"])


def test_karten12_ac2_the_check_says_name_source_buttons_and_form_of_each_document(admin: TestClient) -> None:
    answer = check(admin, separated(DOWNLOADS, INTEGRATION))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["ok"] is True and body["missing_integrations"] == []
    first, second = body["documents"]
    assert (first["type"], first["slug"], first["form"], first["requires"]) == ("card", "downloads", "list", ["jsonapi"])
    assert first["name"] == {"en": "Downloads", "de": "Downloads"}
    assert [(one["label"], one["method"], one["path"]) for one in first["buttons"]] == [
        ({"en": "Pause", "de": "Pausieren"}, "POST", "/api/v2/torrents/pause"),
        ("Limit speed", "POST", "/api/v2/transfer/setDownloadLimit"),
        ("Delete", "DELETE", "/api/v2/torrents/{hash}"),
    ]
    assert (first["exists"], first["same"], first["problems"]) == (False, False, [])
    assert (second["type"], second["short"], second["name"], second["requires"], second["buttons"]) == ("integration", SHORT, "BookStack", [], [])
    assert admin.get("/api/v1/cards").json()["cards"] == [], "checking made something"


def test_karten12_ac2_the_check_knows_what_exists_and_what_is_the_same(admin: TestClient) -> None:
    admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF)
    same = check(admin, PLAIN).json()["documents"][0]
    assert (same["exists"], same["same"]) == (True, True)
    other = check(admin, changed(VERSION, 'version: "1.1.0"')).json()["documents"][0]
    assert (other["exists"], other["same"]) == (True, False)


def test_karten12_ac4_a_card_whose_own_connection_is_in_the_file_misses_nothing(admin: TestClient) -> None:
    assert check(admin, separated(CARD, INTEGRATION)).json()["missing_integrations"] == []
    assert check(admin, CARD).json()["missing_integrations"] == [f"custom:{SHORT}"]
    assert run(admin, separated(CARD, INTEGRATION)).status_code == 201
    assert check(admin, CARD).json()["missing_integrations"] == [], "the connection is here now"


def test_karten12_ac4_a_card_that_can_read_through_a_built_in_kind_misses_nothing(admin: TestClient) -> None:
    mixed = changed("requires: [sonarr, radarr]   # either one", f"requires: [sonarr, custom:{SHORT}]")
    assert check(admin, mixed).json()["missing_integrations"] == []


def test_karten12_ac4_the_card_is_made_without_its_connection_when_the_person_leaves_it_out(admin: TestClient) -> None:
    assert run(admin, separated(CARD, INTEGRATION), {OWN: "skip"}).status_code == 201
    assert slugs() == ["queue-size"] and shorts() == []


def test_karten12_ac4_a_file_makes_the_card_and_its_own_connection_which_works_at_once(admin: TestClient) -> None:
    answer = run(admin, separated(CARD, INTEGRATION))
    assert answer.status_code == 201, answer.text
    assert answer.json()["cards_added"] == ["queue-size"] and answer.json()["integrations_added"] == [SHORT]
    assert text_of("queue-size") == CARD, "the text is kept word for word"
    assert get_adapter(f"custom:{SHORT}") is not None


def test_karten12_ec7_pasted_text_and_a_file_read_the_same_way(admin: TestClient) -> None:
    bad = separated(PLAIN, changed("slug: queue-size", "slug: Wrong Name", CARD))
    assert check(admin, bad).json()["documents"][1]["problems"] == check(admin, bad.replace("\n", "\r\n")).json()["documents"][1]["problems"]
    refused = run(admin, bad)
    assert refused.status_code == 400 and code_of(refused) == "import_invalid"
    assert refused.json()["detail"]["documents"][1]["problems"] == check(admin, bad).json()["documents"][1]["problems"]


def test_karten12_ac3_a_name_that_is_taken_needs_a_choice_and_nothing_is_made_without_it(admin: TestClient) -> None:
    admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF)
    refused = run(admin, separated(PLAIN, card("another")))
    assert refused.status_code == 400 and code_of(refused) == "import_choice_missing"
    assert refused.json()["detail"]["key"] == "card:queue-size"
    assert slugs() == ["queue-size"], "the new card was made although the choice was missing"
    assert code_of(run(admin, PLAIN, {"card:queue-size": "maybe"})) == "import_choice_invalid"
    assert code_of(run(admin, PLAIN, {"card:nothing": "skip"})) == "import_choice_invalid"


def test_karten12_ac3_replace_changes_the_card_and_keeps_where_it_stands(admin: TestClient) -> None:
    admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF)
    admin.put("/api/v1/cards/queue-size/users", json={"allowed": True}, headers=CSRF)
    newer = changed(VERSION, 'version: "2.0.0"')
    answer = run(admin, newer, {"card:queue-size": "replace"})
    assert answer.status_code == 201, answer.text
    assert answer.json()["cards_replaced"] == ["queue-size"] and slugs() == ["queue-size"]
    assert text_of("queue-size") == newer
    assert admin.get("/api/v1/cards").json()["cards"][0]["version"] == "2.0.0"
    with db_session() as db:
        assert db.scalar(select(CardRecord.users_may_place)) is True


def test_karten12_ac3_copy_takes_a_free_short_name_each_time(admin: TestClient) -> None:
    admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF)
    first = run(admin, PLAIN, {"card:queue-size": "copy"})
    second = run(admin, PLAIN, {"card:queue-size": "copy"})
    assert first.json()["copies"] == {"card:queue-size": "queue-size-2"} and second.json()["copies"] == {"card:queue-size": "queue-size-3"}
    assert slugs() == ["queue-size", "queue-size-2", "queue-size-3"]
    assert text_of("queue-size-2") == changed("slug: queue-size", "slug: queue-size-2"), "only the short name differs, comments and all"


def test_karten12_ac3_skip_leaves_the_card_and_makes_nothing_of_it(admin: TestClient) -> None:
    admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF)
    answer = run(admin, changed(VERSION, 'version: "9.0.0"'), {"card:queue-size": "skip"})
    assert answer.status_code == 201 and answer.json()["skipped"] == ["card:queue-size"]
    assert text_of("queue-size") == PLAIN


def test_karten12_ac3_a_copied_own_connection_is_the_one_the_copied_card_reads_through(admin: TestClient) -> None:
    run(admin, separated(CARD, INTEGRATION))
    answer = run(admin, separated(CARD, INTEGRATION), {"card:queue-size": "copy", OWN: "copy"})
    assert answer.status_code == 201, answer.text
    assert answer.json()["copies"] == {"card:queue-size": "queue-size-2", OWN: f"{SHORT}-2"}
    assert shorts() == [SHORT, f"{SHORT}-2"]
    assert text_of("queue-size-2") == changed("slug: queue-size", "slug: queue-size-2", changed(f"requires: [custom:{SHORT}]", f"requires: [custom:{SHORT}-2]", CARD))
    assert text_of("queue-size") == CARD, "the first card keeps the first connection"
    assert get_adapter(f"custom:{SHORT}-2") is not None


def test_karten12_ac3_a_card_copied_alone_keeps_reading_through_the_connection_that_is_here(admin: TestClient) -> None:
    run(admin, separated(CARD, INTEGRATION))
    run(admin, CARD, {"card:queue-size": "copy"})
    assert f"requires: [custom:{SHORT}]" in text_of("queue-size-2")


def test_karten12_ac3_replace_of_an_own_connection_changes_its_description(admin: TestClient) -> None:
    run(admin, INTEGRATION)
    newer = INTEGRATION.replace("name: BookStack", "name: BookStack 2", 1)
    assert run(admin, newer, {OWN: "replace"}).status_code == 201
    assert admin.get(f"/api/v1/own-integrations/{SHORT}").json()["name"] == "BookStack 2"
    assert get_adapter(f"custom:{SHORT}").label == "BookStack 2"


def test_karten12_ec1_a_broken_document_is_named_with_its_line_in_the_file(admin: TestClient) -> None:
    broken = changed("form: value", "form: nonsense", card("second", PLAIN))
    file = separated(PLAIN, broken)
    where = [number for number, line in enumerate(file.split("\n"), 1) if line == "form: nonsense"]
    problems = check(admin, file).json()["documents"][1]["problems"]
    assert problems and problems[0]["line"] == where[0] and where[0] > len(PLAIN.split("\n"))
    assert check(admin, file).json()["documents"][0]["problems"] == []
    refused = run(admin, file)
    assert refused.status_code == 400 and slugs() == [], "a broken document stops the whole import"


def test_karten12_ec1_a_text_that_is_not_yaml_a_stranger_and_an_empty_file_are_refused_with_a_reason(admin: TestClient) -> None:
    assert check(admin, "a: [unclosed").json()["documents"][0]["problems"][0]["code"] == "import_unknown_document"
    assert check(admin, "nexdeck-card: [unclosed").json()["documents"][0]["problems"][0]["code"] == "card_yaml"
    assert check(admin, "name: just a mapping\n").json()["documents"][0]["type"] == "unknown"
    empty = check(admin, "---\n# nothing here\n---\n")
    assert empty.status_code == 400 and code_of(empty) == "import_empty"


def test_karten12_ec1_a_file_that_is_too_large_or_has_too_many_documents_is_refused(admin: TestClient) -> None:
    large = check(admin, PLAIN + "# " + "x" * 530_000)
    assert large.status_code == 400 and code_of(large) == "import_too_large" and "512" in large.json()["detail"]["message"]
    assert check(admin, separated(*[card(f"card-{n}", PLAIN) for n in range(20)])).status_code == 200
    many = separated(*[card(f"card-{n}", PLAIN) for n in range(21)])
    assert code_of(check(admin, many)) == "import_too_many"
    assert code_of(run(admin, many)) == "import_too_many"
    assert slugs() == []


def test_karten12_ec1_the_same_name_twice_in_one_file_is_refused(admin: TestClient) -> None:
    problems = check(admin, separated(PLAIN, PLAIN)).json()["documents"][1]["problems"]
    assert [one["code"] for one in problems] == ["import_twice"] and problems[0]["line"] > len(PLAIN.split("\n"))
    assert run(admin, separated(PLAIN, PLAIN)).status_code == 400 and slugs() == []


def test_karten12_ec2_a_file_for_a_newer_nexdeck_gets_the_message_of_a_newer_card(admin: TestClient) -> None:
    newer = changed("nexdeck-card: 1", "nexdeck-card: 2", PLAIN)
    ours = admin.post("/api/v1/cards/check", json={"yaml": newer}, headers=CSRF).json()["problems"][0]
    theirs = check(admin, separated(PLAIN, card("second", newer))).json()["documents"][1]["problems"][0]
    assert theirs["code"] == ours["code"] == "card_needs_newer_format" and theirs["message"] == ours["message"]
    assert theirs["params"] == ours["params"]
    assert run(admin, newer).status_code == 400 and slugs() == []


def test_karten12_ec5_a_card_that_does_not_fit_after_the_first_documents_leaves_nothing_behind(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "MAX_CARDS", 1)
    answer = run(admin, separated(INTEGRATION, card("first"), card("second")))
    assert answer.status_code == 409 and code_of(answer) == "too_many_cards"
    assert slugs() == [] and shorts() == []
    with pytest.raises(KeyError):
        get_adapter(f"custom:{SHORT}")
    with db_session() as db:
        assert db.scalar(select(func.count(Event.id)).where(Event.kind.like("card_definition_%"))) == 0
    monkeypatch.setattr(store, "MAX_CARDS", 200)
    assert run(admin, separated(INTEGRATION, card("first"), card("second"))).status_code == 201
    assert slugs() == ["first", "second"] and get_adapter(f"custom:{SHORT}") is not None


def test_karten12_ec5_a_failure_in_the_middle_of_making_leaves_nothing_behind(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    real = store.create
    made: list[str] = []

    def failing(db: Any, text: str, **more: Any) -> Any:
        if made:
            raise RuntimeError("the disk is gone")
        row = real(db, text, **more)
        made.append(row.slug)
        return row

    monkeypatch.setattr(store, "create", failing)
    with pytest.raises(RuntimeError):
        run(admin, separated(INTEGRATION, card("first"), card("second")))
    assert made == ["first"]
    assert slugs() == [] and shorts() == []
    with pytest.raises(KeyError):
        get_adapter(f"custom:{SHORT}")


def test_karten12_ec6_a_card_from_a_shop_export_comes_in_as_a_local_card(admin: TestClient) -> None:
    with db_session() as db:
        store.create(db, PLAIN, origin="shop", shop_ref="author/queue-size", shop_version="1.2.0")
    exported = admin.get("/api/v1/cards/queue-size/export").text
    run(admin, changed("slug: queue-size", "slug: other", exported))
    run(admin, exported, {"card:queue-size": "replace"})
    with db_session() as db:
        rows = list(db.scalars(select(CardRecord)))
        assert len(rows) == 2
        for row in rows:
            assert (row.origin, row.shop_ref, row.shop_version) == ("local", "", ""), row.slug


def test_karten12_the_chronicle_tells_what_an_import_made(admin: TestClient) -> None:
    run(admin, separated(CARD, INTEGRATION))
    run(admin, CARD, {"card:queue-size": "replace"})
    with db_session() as db:
        lines = [(one.kind, one.name) for one in db.scalars(select(Event).where(Event.kind.like("card_definition_%")).order_by(Event.id))]
    assert lines == [("card_definition_added", f"custom:{SHORT}"), ("card_definition_added", "queue-size"), ("card_definition_changed", "queue-size")]


def test_karten12_only_administrators_import(admin: TestClient) -> None:
    create_user(admin, "kim")
    member = TestClient(admin.app)
    login(member, "kim", "another-long-password")
    assert check(member, PLAIN).status_code == 403
    assert run(member, PLAIN).status_code == 403
    assert check(TestClient(admin.app), PLAIN).status_code == 401
    assert slugs() == []


def test_karten12_a_file_that_was_exported_comes_back_as_it_was(admin: TestClient) -> None:
    run(admin, separated(CARD, INTEGRATION))
    exported = admin.get("/api/v1/cards/queue-size/export").text
    admin.delete("/api/v1/cards/queue-size", headers=CSRF)
    admin.delete(f"/api/v1/own-integrations/{SHORT}", headers=CSRF)
    assert run(admin, exported).status_code == 201
    assert text_of("queue-size") == CARD
    assert admin.get(f"/api/v1/own-integrations/{SHORT}").json()["yaml"] == INTEGRATION
