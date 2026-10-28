"""KARTEN-12 EC-1, EC-5: a file the YAML reader cannot read is refused with a reason on every import route, never with a 500,
and a board import never answers 500 after its board is in."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.adapters import forget_all_custom
from app.db import db_session
from app.models import Board, CardRecord
from app.services.collector import collector

from .conftest import CSRF, setup_admin
from .karten12_sample import INTEGRATION, PLAIN

API = "/api/v1/boards"
#: A control character the YAML reader refuses as soon as it sees the text, on the last line of the card.
BROKEN = PLAIN + "# end\x01\n"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    # A 500 comes back as an answer, not as an exception in the test.
    raw = TestClient(client.app, raise_server_exceptions=False)
    raw.cookies.update(client.cookies)
    yield raw
    forget_all_custom()


def board_file(*cards: str) -> str:
    return yaml.safe_dump({"board": {"name": "Probe"}, "pages": [{"name": "P", "widgets": [{"kind": "core.clock"}]}], "custom_cards": list(cards)})


def boards() -> int:
    with db_session() as db:
        return db.scalar(select(func.count()).select_from(Board)) or 0


def cards() -> int:
    with db_session() as db:
        return db.scalar(select(func.count()).select_from(CardRecord)) or 0


def problem(found: dict[str, Any]) -> dict[str, Any]:
    assert len(found["problems"]) == 1, found
    return found["problems"][0]


def test_karten12_ec1_a_control_character_is_a_problem_with_its_line_in_the_card_check(admin: TestClient) -> None:
    text = INTEGRATION + "---\n" + BROKEN
    answer = admin.post("/api/v1/cards/import/check", json={"text": text}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    first, second = answer.json()["documents"]
    assert first["problems"] == []
    found = problem(second)
    assert found["code"] == "card_yaml" and "U+0001" in found["message"]
    assert found["line"] == text.count("\n")  # the last line of the file, counted over the whole file
    integration = admin.post("/api/v1/cards/import/check", json={"text": INTEGRATION + "# end\x01\n"}, headers=CSRF)
    assert integration.status_code == 200 and problem(integration.json()["documents"][0])["code"] == "card_yaml"


def test_karten12_ec1_a_control_character_refuses_the_card_import_with_a_reason(admin: TestClient) -> None:
    answer = admin.post("/api/v1/cards/import", json={"text": BROKEN, "choices": {}}, headers=CSRF)
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "import_invalid"
    assert "U+0001" in answer.json()["detail"]["message"]
    saved = admin.post("/api/v1/cards", json={"yaml": BROKEN}, headers=CSRF)  # the editor's route reads the same way
    assert saved.status_code == 400, saved.text
    assert cards() == 0


def test_karten12_ec1_a_control_character_in_a_definition_of_a_board_file_is_named_by_the_check(admin: TestClient) -> None:
    answer = admin.post(f"{API}/import/check", json={"yaml_text": board_file(BROKEN)}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    (definition,) = answer.json()["definitions"]
    assert definition["status"] == "invalid" and problem(definition)["code"] == "card_yaml"
    # In the board file itself: the file is not read at all.
    whole = admin.post(f"{API}/import/check", json={"yaml_text": "board: {name: x}\npages: []\n# \x01\n"}, headers=CSRF)
    assert whole.status_code == 400 and whole.json()["detail"]["code"] == "bad_import"


def test_karten12_ec5_a_board_import_never_answers_500_once_its_board_is_in(admin: TestClient) -> None:
    before = boards()
    made = admin.post(f"{API}/import", json={"yaml_text": board_file(BROKEN), "definitions": "skip"}, headers=CSRF)
    assert made.status_code == 201, made.text
    assert made.json()["definitions"]["skipped"] == [] and boards() == before + 1
    refused = admin.post(f"{API}/import", json={"yaml_text": board_file(BROKEN), "definitions": "create"}, headers=CSRF)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "bad_import" and "U+0001" in refused.json()["detail"]["message"]
    assert boards() == before + 1 and cards() == 0
