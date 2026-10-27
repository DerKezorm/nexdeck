"""KARTEN-8: a card offers its buttons as actions like every other card, on the card and on each row (AC-1, AC-2, EC-1)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.custom import present
from app.cards import load, pipeline

from .karten8_sample import DOWNLOADS, button, with_buttons
from .test_cards_editor_api import admin, post  # noqa: F401 - the fixture

ROWS = [{"name": "Ubuntu", "hash": "abc123", "progress": 50}, {"name": "Debian", "hash": "def456", "progress": 100}]


def shown(text: str, answers: dict[str, Any]) -> Any:
    definition = load.load_definition(text).definition
    return present(definition, pipeline.run(definition, answers))


def actions_of(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {one["id"]: one for one in item.get("actions") or []}


def test_karten8_ac1_a_button_on_the_card_is_an_action_with_label_icon_question_and_blank() -> None:
    data = shown(DOWNLOADS, {"torrents": ROWS})
    [limit] = data.actions
    assert limit.id == "button:limit" and limit.label == "Limit speed" and limit.icon == "gauge"
    assert limit.confirm is True and limit.danger is False and limit.params == {}
    [kib] = limit.asks
    assert (kib.name, kib.label, kib.kind, kib.min, kib.max, kib.step) == ("ask.kib", "KiB per second?", "number", 0, 100000, 1)


def test_karten8_ac2_every_row_gets_its_buttons_with_the_values_of_exactly_that_row() -> None:
    data = shown(DOWNLOADS, {"torrents": ROWS})
    first, second = (actions_of(item) for item in data.items)
    assert first["button:pause"]["params"] == {"hash": "abc123"} and second["button:pause"]["params"] == {"hash": "def456"}
    assert first["button:delete"]["params"] == {"hash": "abc123"} and second["button:delete"]["params"] == {"hash": "def456"}
    # the label in every language the author wrote: the browser picks, as for every other text of the card
    assert first["button:pause"]["label"] == {"en": "Pause", "de": "Pausieren"} and first["button:pause"]["icon"] == "pause"
    # dangerous asks first and twice: confirm is set with it
    assert first["button:delete"]["danger"] is True and first["button:delete"]["confirm"] is True
    assert "button:limit" not in first, "a button on the card does not hang on a row"


def test_karten8_ac2_a_value_keeps_its_type_and_a_dotted_path_reads_inside_the_row() -> None:
    rows = [{"name": "A", "info": {"id": 7, "paused": False, "note": None}}]
    text = with_buttons(button(where="row", path="/api/items/{info.id}", body={"paused": "{info.paused}", "note": "{info.note}"}))
    [item] = shown(text, {"torrents": rows}).items
    assert actions_of(item)["button:go"]["params"] == {"info.id": 7, "info.paused": False, "info.note": None}


@pytest.mark.parametrize("value", ["../admin", "a/b", "a\\b", "a?b=1", "a#b", "%2e%2e", "a b", "", "tab\there", "..", None])
def test_karten8_ec1_a_row_whose_value_cannot_go_into_the_path_gets_no_button_there(value: Any) -> None:
    rows = [{"name": "bad", "hash": value}, {"name": "good", "hash": "abc123"}]
    bad, good = (actions_of(item) for item in shown(DOWNLOADS, {"torrents": rows}).items)
    assert "button:delete" not in bad and good["button:delete"]["params"] == {"hash": "abc123"}
    # in the body the same value is fine: it goes in as a value, never as a piece of an address
    assert bad["button:pause"]["params"] == {"hash": value}


@pytest.mark.parametrize("value", [{"x": 1}, [1, 2], "missing"])
def test_karten8_ec1_a_row_without_the_field_or_with_an_object_there_gets_no_button(value: Any) -> None:
    row = {"name": "odd"} if value == "missing" else {"name": "odd", "hash": value}
    [item] = shown(DOWNLOADS, {"torrents": [row]}).items
    assert "actions" not in item


def test_karten8_ac1_a_button_on_the_card_reads_the_answer_and_is_left_out_when_the_field_is_missing() -> None:
    text = with_buttons(button(path="/api/queue/{queue.id}/clear", body={"count": "{queue.size}"}), form="value", value="queue.size", rows=None, item=None)
    data = shown(text, {"torrents": {"queue": {"id": 3, "size": 12}}})
    assert [(one.id, one.params) for one in data.actions] == [("button:go", {"queue.id": 3, "queue.size": 12})]
    # the name of the request may lead the path, as in a value of the card
    assert shown(text.replace("{queue.id}", "{torrents.queue.id}"), {"torrents": {"queue": {"id": 3, "size": 12}}}).actions[0].params["torrents.queue.id"] == 3
    assert shown(text, {"torrents": {"queue": {"size": 12}}}).actions == []


def test_karten8_ac1_with_several_requests_the_request_comes_first() -> None:
    text = with_buttons(
        button(path="/api/{one.id}", body={"b": "{two.name}"}),
        form="stats", stats=["one.id", "two.name"], rows=None, item=None,
        requests=[{"id": "one", "path": "/a"}, {"id": "two", "path": "/b"}], demo=None,
    )
    data = shown(text, {"one": {"id": "x1"}, "two": {"name": "Ann"}})
    assert data.actions[0].params == {"one.id": "x1", "two.name": "Ann"}


def test_karten8_ac1_a_choice_blank_hands_over_its_options_and_a_text_blank_its_length() -> None:
    asks = [
        {"name": "mode", "label": {"en": "Mode?", "de": "Art?"}, "type": "choice", "options": [{"value": "fast", "label": "Fast"}, {"value": 2, "label": "Two"}]},
        {"name": "note", "label": "Note?", "type": "text"},
        {"name": "long", "label": "Long?", "type": "text", "max_length": 300},
    ]
    text = with_buttons(button(asks=asks, body={"m": "{ask.mode}", "n": "{ask.note}", "l": "{ask.long}"}))
    [action] = shown(text, {"torrents": ROWS}).actions
    mode, note, long = action.asks
    assert (mode.name, mode.kind, [(one.value, one.label) for one in mode.options]) == ("ask.mode", "choice", [("fast", "Fast"), ("2", "Two")])
    assert mode.label == {"en": "Mode?", "de": "Art?"}
    assert (note.kind, note.max_length, long.max_length) == ("text", 100, 300)


def test_karten8_ac1_a_card_without_buttons_offers_no_action() -> None:
    data = shown(with_buttons(), {"torrents": ROWS})
    assert data.actions == [] and all("actions" not in item for item in data.items)


def test_karten8_ac2_pictures_carry_their_buttons_on_every_picture() -> None:
    text = with_buttons(button(where="row", path="/api/{hash}/play"), form="posters", item={"image": {"template": "/art/{hash}"}, "title": "name"})
    items = shown(text, {"torrents": ROWS}).items
    assert [actions_of(item)["button:go"]["params"] for item in items] == [{"hash": "abc123"}, {"hash": "def456"}]


def test_karten8_ac1_the_preview_draws_the_buttons_from_the_demo_answers(admin: TestClient) -> None:  # noqa: F811
    answer = post(admin, "preview", {"yaml": DOWNLOADS, "demo": True})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert [one["id"] for one in body["actions"]] == ["button:limit"]
    assert [actions_of(item)["button:pause"]["params"] for item in body["items"]] == [{"hash": "abc123"}, {"hash": "def456"}]
