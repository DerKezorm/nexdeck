"""A Notes card is written from the card itself, and a save never writes over
a change made elsewhere in the meantime."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas import NOTE_LIMIT

from .conftest import CSRF, create_user, setup_admin


def _note(client: TestClient, content: str | None = "- [ ] milk") -> tuple[dict, dict]:
    board = client.post("/api/v1/boards", json={"name": "Kitchen"}, headers=CSRF).json()
    body: dict = {"kind": "core.markdown"}
    if content is not None:
        body["options"] = {"content": content, "keep": "this"}
    card = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json=body, headers=CSRF).json()["widget"]
    return board, card


def _stored(client: TestClient, board: dict) -> dict:
    return client.get(f"/api/v1/boards/{board['slug']}").json()["pages"][0]["widgets"][0]["options"]


def test_the_text_is_saved_and_nothing_else_is_touched(client: TestClient) -> None:
    setup_admin(client)
    board, card = _note(client)
    saved = client.put(f"/api/v1/widgets/{card['id']}/note", json={"content": "- [x] milk", "based_on": "- [ ] milk"}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert _stored(client, board) == {"content": "- [x] milk", "keep": "this"}


def test_a_save_over_a_change_made_elsewhere_is_refused_with_the_stored_text(client: TestClient) -> None:
    setup_admin(client)
    board, card = _note(client)
    first = client.put(f"/api/v1/widgets/{card['id']}/note", json={"content": "- [ ] milk\n- [ ] eggs", "based_on": "- [ ] milk"}, headers=CSRF)
    assert first.status_code == 200
    late = client.put(f"/api/v1/widgets/{card['id']}/note", json={"content": "- [ ] milk\n- [ ] bread", "based_on": "- [ ] milk"}, headers=CSRF)
    assert late.status_code == 409
    assert late.json()["detail"] == {"code": "note_changed", "message": "The note was changed elsewhere while you were typing.",
                                     "current": "- [ ] milk\n- [ ] eggs"}
    assert _stored(client, board)["content"] == "- [ ] milk\n- [ ] eggs"
    # The same text twice is no conflict: a save repeated after a lost answer.
    again = client.put(f"/api/v1/widgets/{card['id']}/note", json={"content": "- [ ] milk\n- [ ] eggs", "based_on": "- [ ] milk"}, headers=CSRF)
    assert again.status_code == 200


def test_a_new_card_starts_from_the_text_it_shows(client: TestClient) -> None:
    setup_admin(client)
    board, card = _note(client, content=None)
    from app.adapters import get_adapter

    shown = next(f.default for f in get_adapter("core").widget("markdown").options if f.name == "content")
    saved = client.put(f"/api/v1/widgets/{card['id']}/note", json={"content": "Mine now", "based_on": shown}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert _stored(client, board)["content"] == "Mine now"


def test_only_notes_only_writers_and_not_endlessly_long(client: TestClient) -> None:
    setup_admin(client)
    board, card = _note(client)
    clock = client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.clock"}, headers=CSRF).json()["widget"]
    assert client.put(f"/api/v1/widgets/{clock['id']}/note", json={"content": "x", "based_on": ""}, headers=CSRF).json()["detail"]["code"] == "not_a_note"
    assert client.put(f"/api/v1/widgets/{card['id']}/note", json={"content": "x" * (NOTE_LIMIT + 1), "based_on": "- [ ] milk"}, headers=CSRF).status_code == 422

    create_user(client, "reader")
    client.put(f"/api/v1/boards/{board['slug']}/shares", json={"shares": [{"user_id": None, "role": "user", "level": "view"}]}, headers=CSRF)
    reader = TestClient(client.app)
    assert reader.post("/api/v1/auth/login", json={"username": "reader", "password": "another-long-password"}).status_code == 200
    refused = reader.put(f"/api/v1/widgets/{card['id']}/note", json={"content": "- [x] milk", "based_on": "- [ ] milk"}, headers=CSRF)
    assert refused.status_code == 403
    assert _stored(client, board)["content"] == "- [ ] milk"
