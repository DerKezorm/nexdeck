"""KARTEN-12: the answers of the server the browser tests of the import read, kept in ``frontend/src/test/karten12Answers.json``.

The file is what the routes really answer, so the dialogs are tested against the server and not against what a test
imagines it says. This test asks the routes again and compares; with ``NEXDECK_WRITE_FIXTURES=1`` it writes the file.
Only invented names and example.com.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.adapters import forget_all_custom
from app.services.collector import collector

from .cards_sample import changed
from .conftest import CSRF, login, setup_admin
from .karten12_sample import INTEGRATION, PLAIN, card

TARGET = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "karten12Answers.json"
API = "/api/v1/boards"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    yield client
    forget_all_custom()


def member_of(admin: TestClient) -> TestClient:
    made = admin.post("/api/v1/users", json={"username": "kim", "password": "another-long-password", "role": "user"}, headers=CSRF)
    assert made.status_code == 201, made.text
    member = TestClient(admin.app)
    login(member, "kim", "another-long-password")
    return member


def board_file(cards: list[str], integrations: list[str]) -> str:
    return yaml.safe_dump(
        {"board": {"name": "Example"}, "pages": [{"name": "P", "widgets": [{"kind": "core.clock"}]}], "custom_cards": cards, "own_integrations": integrations},
        sort_keys=False,
    )


def answers(admin: TestClient) -> dict[str, Any]:
    assert admin.post("/api/v1/cards", json={"yaml": card("exists-same", PLAIN)}, headers=CSRF).status_code == 201
    assert admin.post("/api/v1/cards", json={"yaml": card("exists-diff", PLAIN)}, headers=CSRF).status_code == 201
    found: dict[str, Any] = {}
    mixed = board_file(
        [
            card("exists-same", PLAIN), changed('version: "1.0.0"', 'version: "5.0.0"', card("exists-diff", PLAIN)), card("brand-new", PLAIN),
            changed("form: value", "form: nonsense", card("broken-one", PLAIN)),
        ],
        [INTEGRATION],
    )
    found["board_file"] = mixed
    found["board_check_admin"] = admin.post(f"{API}/import/check", json={"yaml_text": mixed}, headers=CSRF).json()
    member = member_of(admin)
    found["board_check_member"] = member.post(f"{API}/import/check", json={"yaml_text": mixed}, headers=CSRF).json()
    # Refusals, as the dialogs get them.
    found["cards_import_invalid"] = admin.post("/api/v1/cards/import", json={"text": "hello: world\n---\n" + card("other-one", PLAIN), "choices": {}}, headers=CSRF).json()
    found["board_import_member_create"] = member.post(f"{API}/import", json={"yaml_text": mixed, "definitions": "create"}, headers=CSRF).json()
    found["board_import_bad"] = admin.post(f"{API}/import", json={"yaml_text": mixed, "definitions": "create"}, headers=CSRF).json()
    # What a board import reports about the definitions of its file, without what differs from run to run.
    good = board_file([card("exists-same", PLAIN), changed('version: "1.0.0"', 'version: "5.0.0"', card("exists-diff", PLAIN)), card("brand-new", PLAIN)], [INTEGRATION])
    found["board_file_good"] = good
    for who, client, body in (("member", member, {}), ("admin", admin, {"definitions": "create"})):
        made = client.post(f"{API}/import", json={"yaml_text": good, **body}, headers=CSRF)
        assert made.status_code == 201, made.text
        found[f"board_import_{who}"] = {"slug": "example", "definitions": made.json()["definitions"]}
    # The own integration of the file, now here, with a field renamed: replacing it throws the old one away.
    renamed = INTEGRATION.replace("token_secret", "token_renamed")
    found["integration_renamed"] = renamed
    found["cards_check_dropped"] = admin.post("/api/v1/cards/import/check", json={"text": renamed}, headers=CSRF).json()
    return found


def test_karten12_the_answers_the_browser_tests_read_are_the_servers(admin: TestClient) -> None:
    now = answers(admin)
    if os.environ.get("NEXDECK_WRITE_FIXTURES") == "1":
        TARGET.write_text(json.dumps(now, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    assert json.loads(TARGET.read_text(encoding="utf-8")) == now, "the server answers otherwise now: NEXDECK_WRITE_FIXTURES=1 writes the file anew"
