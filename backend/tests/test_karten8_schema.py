"""KARTEN-8: what a definition may say about its buttons (AC-1, AC-10, EC-1 as far as the definition goes)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from app.cards import load, schema

from .karten8_sample import DOWNLOADS, button, with_buttons


def refused(text: str) -> load.CardInvalid:
    with pytest.raises(load.CardInvalid) as caught:
        load.load_definition(text)
    return caught.value


def codes(failure: load.CardInvalid) -> list[str]:
    return [problem.code for problem in failure.problems]


def line_of(text: str, needle: str) -> int:
    return next(number for number, line in enumerate(text.splitlines(), start=1) if needle in line)


def test_karten8_ac1_a_button_with_label_icon_method_path_and_body_is_accepted_and_kept() -> None:
    loaded = load.load_definition(DOWNLOADS)
    pause, limit, delete = loaded.definition.buttons
    assert (pause.id, pause.label, pause.icon, pause.where, pause.method, pause.send) == ("pause", {"en": "Pause", "de": "Pausieren"}, "pause", "row", "POST", "form")
    assert pause.body == {"hashes": "{hash}"} and pause.placeholders() == [(("body", "hashes"), "hash")]
    assert limit.where == "card" and limit.confirm and limit.asks[0].type == "number" and (limit.asks[0].min, limit.asks[0].max, limit.asks[0].step) == (0, 100000, 1)
    assert delete.method == "DELETE" and delete.danger and delete.placeholders() == [(("path",), "hash")]
    assert [one["id"] for one in loaded.data["buttons"]] == ["pause", "limit", "delete"]


def test_karten8_ac1_a_card_without_buttons_is_what_it_was() -> None:
    data = yaml.safe_load(DOWNLOADS)
    del data["buttons"]
    loaded = load.load_definition(yaml.safe_dump(data, sort_keys=False))
    assert loaded.definition.buttons == [] and loaded.data["buttons"] == []


@pytest.mark.parametrize("method", ["post", "PUT", "patch", "DELETE"])
def test_karten8_ac1_the_four_methods_that_change_something_are_taken_in_any_case(method: str) -> None:
    assert load.load_definition(with_buttons(button(method=method))).definition.buttons[0].method == method.upper()


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "CONNECT", ""])
def test_karten8_ac1_a_button_never_reads_get_and_the_rest_is_refused(method: str) -> None:
    assert "card_not_allowed" in codes(refused(with_buttons(button(method=method))))


def test_karten8_ac1_a_nested_body_with_a_list_and_typed_values_is_accepted() -> None:
    body = {"name": "SeriesSearch", "seriesId": "{id}", "options": {"ids": ["{id}", 7], "monitored": True, "note": None}}
    loaded = load.load_definition(with_buttons(button(body=body)))
    assert loaded.definition.buttons[0].body == body


def test_karten8_ac10_ten_buttons_are_fine_and_the_eleventh_is_refused_with_its_own_code() -> None:
    ten = [button(id=f"b{number}") for number in range(10)]
    assert len(load.load_definition(with_buttons(*ten)).definition.buttons) == 10
    text = with_buttons(*ten, button(id="b10"))
    failure = refused(text)
    assert codes(failure) == ["card_too_many_buttons"]
    assert failure.problems[0].params == {"limit": 10, "count": 11}
    assert failure.problems[0].line == line_of(text, "buttons:")


@pytest.mark.parametrize("form", ["value", "stats"])
def test_karten8_ac10_a_button_on_every_row_needs_a_form_with_rows(form: str) -> None:
    shapes: dict[str, Any] = {"value": {"value": "total"}, "stats": {"stats": ["a", "b"]}}
    text = with_buttons(button(where="row"), form=form, rows=None, item=None, **shapes[form])
    failure = refused(text)
    assert codes(failure) == ["card_button_no_rows"]
    assert failure.problems[0].path == "buttons[0].where" and failure.problems[0].line == line_of(text, "where: row")
    assert load.load_definition(with_buttons(button(where="card"), form=form, rows=None, item=None, **shapes[form]))


def test_karten8_ac10_a_button_on_every_row_hangs_on_a_list_and_on_pictures() -> None:
    assert load.load_definition(with_buttons(button(where="row"))).definition.buttons[0].where == "row"
    pictures = with_buttons(button(where="row"), form="posters", item={"image": "poster", "title": "name"})
    assert load.load_definition(pictures).definition.buttons[0].where == "row"


def test_karten8_ac10_two_buttons_with_one_id_are_refused_at_the_second() -> None:
    text = with_buttons(button(id="same", path="/a"), button(id="same", path="/b"))
    failure = refused(text)
    assert codes(failure) == ["card_duplicate_button"] and failure.problems[0].path == "buttons[1].id"
    assert failure.problems[0].line == line_of(text, "path: /b") - 3


@pytest.mark.parametrize("name", ["Pause", "1go", "go-now", "x" * 31, ""])
def test_karten8_ac10_a_button_id_is_a_short_name(name: str) -> None:
    assert "card_bad_form" in codes(refused(with_buttons(button(id=name))))


@pytest.mark.parametrize(
    "path",
    ["api/go", "//evil.example.com/x", "/api/../admin", "/api/%2e%2e/admin", "/api/x%2fy", "/a\\b", "/a b", "/a;/b", "/a/{x}/../b"],
)
def test_karten8_ec1_a_path_that_leaves_the_address_is_refused_with_its_line(path: str) -> None:
    text = with_buttons(button(path=path))
    failure = refused(text)
    assert set(codes(failure)) <= {"card_bad_path"} and failure.problems[0].path == "buttons[0].path"


@pytest.mark.parametrize("path", ["/api/{id}/start", "/api/items/{item.id}?force={ask.force}", "/x/{a}{b}"])
def test_karten8_ec1_placeholders_in_a_path_are_fine_where_a_plain_value_would_be(path: str) -> None:
    asks = [{"name": "force", "label": "Force?", "type": "choice", "options": [{"value": "true", "label": "Yes"}]}] if "ask." in path else []
    assert load.load_definition(with_buttons(button(path=path, asks=asks))).definition.buttons[0].path == path


@pytest.mark.parametrize(
    "where",
    [{"path": "/api/{}"}, {"path": "/api/{a b}"}, {"path": "/api/{x"}, {"path": "/api/x}"}, {"path": "/api/{a.b.c.d.e.f}"},
     {"path": "/api/{a[0]}"}, {"body": {"x": "{1abc}"}}, {"body": {"x": "{ask.Big}"}}, {"body": {"x": "{{id}}"}}],
)
def test_karten8_ac1_a_placeholder_is_a_field_name_or_a_blank_and_nothing_else(where: dict[str, Any]) -> None:
    assert "card_bad_placeholder" in codes(refused(with_buttons(button(**where))))


def test_karten8_ac1_a_blank_used_in_a_button_must_be_declared_and_is_named_with_its_line() -> None:
    text = with_buttons(button(body={"minutes": "{ask.minutes}"}))
    failure = refused(text)
    assert codes(failure) == ["card_unknown_ask"] and failure.problems[0].params == {"name": "minutes"}
    assert failure.problems[0].path == "buttons[0].body.minutes" and failure.problems[0].line == line_of(text, "minutes:")


@pytest.mark.parametrize(
    "body",
    [
        {"a": {"b": {"c": {"d": 1}}}},  # four levels
        {f"k{number}": number for number in range(31)},
        {"a": [1] * 30},  # one key and thirty entries
        {"a": float("nan")},
    ],
)
def test_karten8_ac1_a_body_is_small_and_plain(body: dict[str, Any]) -> None:
    assert "card_button_body" in codes(refused(with_buttons(button(body=body))))


def test_karten8_ac1_a_body_sent_as_a_form_is_flat() -> None:
    assert "card_button_body" in codes(refused(with_buttons(button(send="form", body={"a": {"b": 1}}))))
    assert "card_button_body" in codes(refused(with_buttons(button(send="form", body={"a": [1]}))))
    assert load.load_definition(with_buttons(button(send="form", body={"a": "{x}", "b": 2})))


def test_karten8_ac1_a_body_is_an_object() -> None:
    assert "card_wrong_type" in codes(refused(with_buttons(button(body=["{id}"]))))


@pytest.mark.parametrize(
    "ask",
    [
        {"name": "n", "label": "N?", "type": "number", "min": 5, "max": 1},
        {"name": "n", "label": "N?", "type": "number", "options": [{"value": "a", "label": "A"}]},
        {"name": "n", "label": "N?", "type": "text", "min": 1},
        {"name": "n", "label": "N?", "type": "choice"},
        {"name": "n", "label": "N?", "type": "choice", "max_length": 4, "options": [{"value": "a", "label": "A"}]},
    ],
)
def test_karten8_ec9_a_blank_takes_the_settings_of_its_type_only(ask: dict[str, Any]) -> None:
    assert "card_button_ask" in codes(refused(with_buttons(button(asks=[ask], body={"x": "{ask.n}"}))))


@pytest.mark.parametrize(
    ("ask", "code"),
    [
        ({"name": "n", "label": "N?", "type": "number", "step": 0}, "card_out_of_range"),
        ({"name": "n", "label": "N?", "type": "text", "max_length": 401}, "card_out_of_range"),
        ({"name": "n", "label": "N?", "type": "choice", "options": [{"value": str(n), "label": "x"} for n in range(31)]}, "card_too_many"),
        ({"name": "n", "label": "", "type": "text"}, "card_blank"),
        ({"name": "N", "label": "N?", "type": "text"}, "card_bad_form"),
        ({"name": "n", "label": "N?", "type": "date"}, "card_not_allowed"),
    ],
)
def test_karten8_ec9_the_limits_of_a_blank(ask: dict[str, Any], code: str) -> None:
    assert code in codes(refused(with_buttons(button(asks=[ask], body={"x": "{ask.n}"}))))


def test_karten8_ec9_two_blanks_of_one_button_have_two_names() -> None:
    twice = [{"name": "n", "label": "N?", "type": "text"}, {"name": "n", "label": "M?", "type": "text"}]
    assert "card_duplicate_button" in codes(refused(with_buttons(button(asks=twice, body={"x": "{ask.n}"}))))


def test_karten8_ec9_a_choice_written_as_a_bare_number_is_its_text() -> None:
    ask = {"name": "n", "label": "N?", "type": "choice", "options": [{"value": 7, "label": "Seven"}]}
    loaded = load.load_definition(with_buttons(button(asks=[ask], body={"x": "{ask.n}"})))
    assert loaded.definition.buttons[0].asks[0].options[0].value == "7"


@pytest.mark.parametrize(
    ("where", "what"),
    [
        ({"path": "/api/go?apikey=" + "0123456789abcdef" * 2}, "card_secret_value"),
        ({"body": {"auth": "Bearer " + "abcdefghijklmnop"}}, "card_secret_value"),
        ({"body": {"token": "{id}"}}, "card_secret_field"),
        ({"body": {"x": "ghp" + "_abcdefghijklmnopqrstuvwxyz0123"}}, "card_secret_value"),
        ({"answer": "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc"}, "card_secret_value"),
        ({"headers": {"X-Api-Key": "x"}}, "card_secret_field"),
    ],
)
def test_karten8_ac1_the_secret_scanner_reads_the_path_the_body_and_the_answer_of_a_button(where: dict[str, Any], what: str) -> None:
    failure = refused(with_buttons(button(**where)))
    assert what in codes(failure) and failure.problems[0].path.startswith("buttons[0].")


def test_karten8_ac1_an_answer_is_a_path_into_the_answer_and_a_broken_one_is_refused_with_its_line() -> None:
    assert load.load_definition(with_buttons(button(answer="result.message"))).definition.buttons[0].answer == "result.message"
    text = with_buttons(button(answer="result[?"))
    failure = refused(text)
    assert codes(failure)[0].startswith("card_expression") and failure.problems[0].path == "buttons[0].answer"
    assert failure.problems[0].line == line_of(text, "answer:")


def test_karten8_ac1_a_field_a_button_does_not_know_is_refused() -> None:
    failure = refused(with_buttons(button(url="http://elsewhere.example.com")))
    assert codes(failure) == ["card_unknown_field"] and failure.problems[0].path == "buttons[0].url"


def test_karten8_ac1_the_json_schema_shows_every_field_of_a_button() -> None:
    found = schema.json_schema()
    text = json.dumps(found)
    shown = found["$defs"]["Button"]["properties"]
    assert set(shown) == {"id", "label", "icon", "where", "method", "path", "send", "body", "confirm", "danger", "asks", "answer"}
    assert set(found["$defs"]["ButtonAsk"]["properties"]) == {"name", "label", "type", "min", "max", "step", "max_length", "options"}
    assert "DELETE" in text and '"GET"' not in json.dumps(shown["method"])
    for form in ("ValueCard", "StatsCard", "ListCard", "PostersCard"):
        assert found["$defs"][form]["properties"]["buttons"]["maxItems"] == 10, form


def test_karten8_ac1_the_sample_of_the_shared_sheet_loads() -> None:
    sheet = yaml.safe_load(DOWNLOADS)
    sheet["requires"] = ["qbittorrent"]
    assert load.load_definition(yaml.safe_dump(sheet, sort_keys=False)).definition.buttons[0].id == "pause"
