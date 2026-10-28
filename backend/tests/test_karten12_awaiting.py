"""KARTEN-12 AC-7: a custom card a member brings onto a board in a file, where he could not have placed it, waits for an administrator.

The same answer whether the card is saved here or not (nobody learns which short names exist), and the card never runs
until an administrator saves it again or releases the card for users.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import forget_all_custom
from app.db import db_session
from app.models import Widget
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF, login, setup_admin
from .karten12_sample import PLAIN

API = "/api/v1/boards"
CARD = "queue-size"


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    yield client
    forget_all_custom()


def member_of(admin: TestClient, name: str = "kim") -> TestClient:
    made = admin.post("/api/v1/users", json={"username": name, "password": "another-long-password", "role": "user"}, headers=CSRF)
    assert made.status_code in (201, 409), made.text
    member = TestClient(admin.app)
    login(member, name, "another-long-password")
    return member


def connection(admin: TestClient) -> int:
    """A connection in demo mode a member may use: the card's data comes from its demo, no service is asked."""
    body = {"kind": "sonarr", "name": "Shows", "demo": True, "config": {"url": "http://sonarr.example.com:8989", "api_key": "key-1"}}
    made = admin.post("/api/v1/integrations", json=body, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


def board_file(card: str = CARD, **options: Any) -> str:
    widget = {"kind": "custom.value", "integration": "Shows", "options": {"card": card, **options}}
    return yaml.safe_dump({"board": {"name": "Probe"}, "integrations": [{"kind": "sonarr", "name": "Shows"}], "pages": [{"name": "P", "widgets": [widget]}]})


def marks(client: TestClient, board: str) -> list[Any]:
    """The mark of each card on the first page, as the board is read afresh."""
    return [options_of(one["id"]).get("awaiting_admin") for one in client.get(f"{API}/{board}").json()["pages"][0]["widgets"]]


def import_file(client: TestClient, text: str):  # noqa: ANN202
    return client.post(f"{API}/import", json={"yaml_text": text}, headers=CSRF)


def options_of(widget_id: int) -> dict[str, Any]:
    with db_session() as db:
        return dict(db.scalar(select(Widget.options).where(Widget.id == widget_id)) or {})


async def code_of(widget_id: int) -> str | None:
    await collector.refresh(widget_id)
    return (live.get(widget_id).meta or {}).get("code")


def without_numbers(value: Any) -> Any:
    """An answer without what differs between two imports anyway: row numbers, the board's short name, times."""
    if isinstance(value, dict):
        return {key: without_numbers(item) for key, item in value.items() if key not in ("id", "i", "slug", "updated_at", "created_at") and not key.endswith("_id")}
    if isinstance(value, list):
        return [without_numbers(item) for item in value]
    return value


def test_karten12_ac7_a_member_learns_nothing_about_which_cards_are_saved(admin: TestClient) -> None:
    connection(admin)
    member = member_of(admin)
    missing = import_file(member, board_file())
    assert admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF).status_code == 201  # saved, not released
    saved = import_file(member, board_file())
    assert missing.status_code == saved.status_code == 201, saved.text
    assert without_numbers(missing.json()) == without_numbers(saved.json())
    for answer in (missing, saved):
        assert options_of(answer.json()["pages"][0]["widgets"][0]["id"]) == {"card": CARD, "awaiting_admin": True}


def test_karten12_ac7_editing_his_own_board_as_text_tells_him_nothing_either(admin: TestClient) -> None:
    connection(admin)
    member = member_of(admin)
    board = member.post(API, json={"name": "Mine"}, headers=CSRF).json()

    def put(card: str):  # noqa: ANN202
        exported = yaml.safe_load(member.get(f"{API}/{board['slug']}/export?ids=true").text)
        exported["pages"][0]["widgets"] = [{"kind": "custom.value", "integration": "Shows", "options": {"card": card}}]
        return member.put(f"{API}/{board['slug']}/yaml", json={"yaml_text": yaml.safe_dump(exported)}, headers=CSRF)

    ghost = put("ghost-card")
    assert admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF).status_code == 201
    saved = put(CARD)
    assert ghost.status_code == saved.status_code == 200, saved.text
    assert marks(member, board["slug"]) == [True]


async def test_karten12_ac7_a_card_made_later_does_not_run_on_his_board_until_it_is_released(admin: TestClient) -> None:
    shows = connection(admin)
    member = member_of(admin)
    made = import_file(member, board_file())
    assert made.status_code == 201, made.text
    widget = made.json()["pages"][0]["widgets"][0]["id"]
    assert await code_of(widget) == "definition_missing"
    assert admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF).status_code == 201  # made later, not released
    # What the reviewer did: the member ties the card to a connection; it still does not run.
    patched = member.patch(f"/api/v1/widgets/{widget}", json={"integration_id": shows, "options": {"card": CARD}}, headers=CSRF)
    assert patched.status_code == 200, patched.text
    assert options_of(widget)["awaiting_admin"] is True
    assert await code_of(widget) == "definition_missing"
    preview = member.post(f"/api/v1/widgets/{widget}/preview", json={"options": {"card": CARD}, "integration_id": shows}, headers=CSRF)
    assert preview.json()["meta"]["code"] == "definition_missing"
    assert member.get(f"/api/v1/widgets/{widget}/image", params={"path": "/api/v3/series"}).status_code == 404
    # Released for users: it runs like any released card; taken back: it waits again.
    admin.put(f"/api/v1/cards/{CARD}/users", json={"allowed": True}, headers=CSRF)
    assert await code_of(widget) != "definition_missing" and live.get(widget).status != "unknown"
    admin.put(f"/api/v1/cards/{CARD}/users", json={"allowed": False}, headers=CSRF)
    assert await code_of(widget) == "definition_missing"


def test_karten12_ac7_only_an_administrator_lets_the_card_go(admin: TestClient) -> None:
    shows = connection(admin)
    member = member_of(admin)
    made = import_file(member, board_file())
    board, widget = made.json()["slug"], made.json()["pages"][0]["widgets"][0]["id"]
    assert admin.post("/api/v1/cards", json={"yaml": PLAIN}, headers=CSRF).status_code == 201
    # The member's text without the mark, the same card under its number and once more as a new card: both keep waiting.
    exported = yaml.safe_load(member.get(f"{API}/{board}/export?ids=true").text)
    card = exported["pages"][0]["widgets"][0]
    card["options"] = {"card": CARD}
    exported["pages"][0]["widgets"].append({**card, "id": None, "options": {"card": CARD, "awaiting_admin": False}})
    edited = member.put(f"{API}/{board}/yaml", json={"yaml_text": yaml.safe_dump(exported)}, headers=CSRF)
    assert edited.status_code == 200, edited.text
    assert marks(member, board) == [True, True]
    # An administrator's save takes the mark away.
    assert admin.patch(f"/api/v1/widgets/{widget}", json={"integration_id": shows, "options": {"card": CARD, "awaiting_admin": True}}, headers=CSRF).status_code == 200
    assert "awaiting_admin" not in options_of(widget)


def test_karten12_ac7_an_administrator_imports_as_before(admin: TestClient) -> None:
    connection(admin)
    made = import_file(admin, board_file(awaiting_admin=True))  # what a file says about the mark counts for nothing
    assert made.status_code == 201, made.text
    assert options_of(made.json()["pages"][0]["widgets"][0]["id"]) == {"card": CARD}
