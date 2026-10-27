"""KARTEN-7: what a definition may say about its blocks (AC-1, AC-3, AC-5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.cards import blocks, load, schema

from .karten7_sample import GLANCE, changed, nested, with_blocks


def refused(text: str) -> load.CardInvalid:
    with pytest.raises(load.CardInvalid) as caught:
        load.load_definition(text)
    return caught.value


def codes(failure: load.CardInvalid) -> list[str]:
    return [problem.code for problem in failure.problems]


def one_block(**fields: Any) -> str:
    return with_blocks(fields, buttons=[], rows=None, main=None)


# -- AC-1: twelve blocks in four groups, each with fixed settings --------------------------------


def test_karten7_ac1_the_sample_card_is_accepted_and_its_blocks_keep_their_settings() -> None:
    loaded = load.load_definition(GLANCE)
    top = loaded.definition.blocks
    assert [one.type for one in top] == ["row", "value", "progress", "sparkline", "divider", "list", "button"]
    assert loaded.definition.main == "cpu" and loaded.definition.rows.select == "containers"
    assert (top[0].gap, top[0].align, top[0].wrap) == ("m", "start", True)
    assert [one["type"] for one in loaded.data["blocks"]] == ["row", "value", "progress", "sparkline", "divider", "list", "button"]


def test_karten7_ac1_there_are_twelve_blocks_in_four_groups_and_the_schema_knows_each_of_them() -> None:
    assert {group: len(kinds) for group, kinds in blocks.GROUPS.items()} == {"layout": 3, "content": 5, "data": 3, "action": 1}
    definitions = schema.json_schema()["$defs"]
    named = {name for name in definitions if name.endswith("Block")}
    assert named == {f"{kind.capitalize()}Block" for kind in blocks.KINDS} and len(blocks.KINDS) == 12
    card = definitions["BuilderCard"]["properties"]
    assert {"blocks", "main", "rows"} <= set(card)
    assert card["form"]["const"] == "builder"


def test_karten7_ac1_the_settings_of_each_block_have_their_defaults() -> None:
    loaded = load.load_definition(with_blocks(
        {"type": "row", "children": [{"type": "divider"}]}, {"type": "column", "children": [{"type": "divider"}]},
        {"type": "text", "text": "Hi"}, {"type": "badge", "text": "New"}, {"type": "symbol", "icon": "flame"},
        {"type": "image", "src": "poster"}, {"type": "progress", "value": "used"}, buttons=[], rows=None, main=None,
    ))
    row, column, text, badge, symbol, image, progress = loaded.definition.blocks
    assert (row.gap, row.align, row.wrap, column.gap) == ("m", "start", True, "m")
    assert (text.size, text.weight, text.color, badge.color, symbol.size, symbol.color) == ("m", "normal", "text", "muted", "m", "text")
    assert (image.height, progress.max, progress.color) == ("m", 100, "accent")


@pytest.mark.parametrize(
    "block",
    [
        {"type": "text"},
        {"type": "text", "text": "a", "value": "b"},
        {"type": "badge"},
        {"type": "symbol"},
        {"type": "image"},
        {"type": "progress"},
        {"type": "sparkline", "value": "x"},
        {"type": "list"},
        {"type": "button"},
        {"type": "value"},
    ],
)
def test_karten7_ac1_a_block_missing_what_it_needs_is_refused(block: dict[str, Any]) -> None:
    assert refused(one_block(**block)).problems


def test_karten7_ac1_a_block_nobody_knows_names_the_twelve_that_exist() -> None:
    problem = refused(one_block(type="carousel")).problems[0]
    assert (problem.code, problem.path) == ("card_bad_block", "blocks[0]")
    assert all(kind in problem.message for kind in blocks.KINDS)


def test_karten7_ac1_a_setting_the_block_does_not_have_is_refused_with_its_place() -> None:
    failure = refused(with_blocks({"type": "divider"}, {"type": "text", "text": "Hi", "css": "color: red"}, buttons=[], rows=None, main=None))
    assert [(one.code, one.path) for one in failure.problems] == [("card_unknown_field", "blocks[1].css")]


def test_karten7_ac1_a_problem_names_the_line_of_the_block() -> None:
    text = one_block(type="symbol", icon="flame", color="neon")
    failure = refused(text)
    assert failure.problems[0].line == next(number for number, line in enumerate(text.splitlines(), start=1) if "color: neon" in line)


def test_karten7_ac1_a_text_or_badge_takes_a_text_or_a_value_and_not_both() -> None:
    assert "card_one_of" in codes(refused(one_block(type="text", text="a", value="b")))
    assert "card_one_of" in codes(refused(one_block(type="badge")))


def test_karten7_ac1_a_sparkline_needs_an_id_because_the_history_is_kept_under_it() -> None:
    failure = refused(one_block(type="sparkline", value="cpu"))
    assert [(one.code, one.path) for one in failure.problems] == [("card_missing_field", "blocks[0].id")]


def test_karten7_ac1_a_list_inside_a_list_is_refused() -> None:
    inner = {"type": "list", "item": [{"type": "divider"}]}
    failure = refused(with_blocks({"type": "list", "item": [inner]}, buttons=[], main=None))
    assert codes(failure) == ["card_list_in_list"] and failure.problems[0].path == "blocks[0].item[0]"
    assert "card_list_in_list" in codes(refused(with_blocks({"type": "list", "item": [{"type": "row", "children": [inner]}]}, buttons=[], main=None)))


def test_karten7_ac1_a_list_needs_rows_and_a_sparkline_does_not_belong_in_one() -> None:
    assert codes(refused(with_blocks({"type": "list", "item": [{"type": "divider"}]}, buttons=[], rows=None, main=None))) == ["card_list_needs_rows"]
    inside = {"type": "list", "item": [{"type": "sparkline", "id": "s", "value": "x"}]}
    assert codes(refused(with_blocks(inside, buttons=[], main=None))) == ["card_sparkline_in_list"]


def test_karten7_ac1_a_list_whose_template_is_still_empty_is_taken_like_an_empty_row_or_column() -> None:
    # The editor starts a list as it starts a row, and takes the last block out of one the same way: both are valid.
    loaded = load.load_definition(with_blocks({"type": "list", "item": []}, {"type": "row", "children": []}, buttons=[], main=None))
    assert loaded.definition.blocks[0].item == []
    assert load.load_definition(with_blocks({"type": "list"}, buttons=[], main=None)).definition.blocks[0].item == []


def test_karten7_ac1_the_main_value_is_a_value_block_with_that_id() -> None:
    assert codes(refused(changed(main="nobody"))) == ["card_main_unknown"]
    # A progress bar with the id is no value; a value inside a list is a value of a row, not of the card.
    assert codes(refused(with_blocks({"type": "progress", "id": "cpu", "value": "x"}, buttons=[], rows=None))) == ["card_main_unknown"]
    inside = {"type": "list", "item": [{"type": "value", "id": "cpu", "path": "x"}]}
    assert codes(refused(with_blocks(inside, buttons=[]))) == ["card_main_unknown"]


def test_karten7_ac1_two_blocks_with_one_id_are_refused_and_so_is_an_id_that_is_not_a_name() -> None:
    twice = with_blocks({"type": "value", "id": "a", "path": "x"}, {"type": "value", "id": "a", "path": "y"}, buttons=[], rows=None, main=None)
    assert [(one.code, one.path) for one in refused(twice).problems] == [("card_duplicate_block", "blocks[1].id")]
    assert refused(one_block(type="value", id="Not A Name", path="x")).problems[0].path == "blocks[0].id"


def test_karten7_ac1_a_button_block_points_at_a_button_of_the_card() -> None:
    failure = refused(with_blocks({"type": "button", "button": "ghost"}, buttons=[], rows=None, main=None))
    assert [(one.code, one.path) for one in failure.problems] == [("card_unknown_button", "blocks[0].button")]


def test_karten7_ac1_a_button_on_every_row_belongs_inside_a_list() -> None:
    failure = refused(with_blocks({"type": "button", "button": "restart"}, rows=None, main=None))
    assert "card_button_outside_list" in codes(failure)


def test_karten7_ac1_the_buttons_of_every_row_are_for_a_card_with_a_list_only() -> None:
    # The rule of the buttons knows the builder: with a list in it, a button on the rows is fine, without one it is not.
    assert load.load_definition(GLANCE).definition.buttons[0].where == "row"
    assert "card_button_no_rows" in codes(refused(with_blocks({"type": "divider"}, rows=None, main=None)))


def test_karten7_ac1_the_expressions_of_the_blocks_are_checked_like_those_of_any_form() -> None:
    problem = refused(one_block(type="value", path="records[?")).problems[0]
    assert problem.code in ("card_expression", "card_expression_at") and problem.path == "blocks[0].path"


# -- AC-3: colours and steps only from the lists -----------------------------------------------


@pytest.mark.parametrize("color", blocks.COLORS)
def test_karten7_ac3_every_colour_of_the_list_is_taken(color: str) -> None:
    assert load.load_definition(one_block(type="symbol", icon="flame", color=color)).definition.blocks[0].color == color


@pytest.mark.parametrize("color", ["#ff0000", "red;", "rgb(1,2,3)", "teal", "RED", "var(--x)", "", "blink"])
def test_karten7_ac3_no_colour_outside_the_list_is_taken(color: str) -> None:
    assert [one.code for one in refused(one_block(type="symbol", icon="flame", color=color)).problems] == ["card_not_allowed"]


def test_karten7_ac3_the_colours_are_the_ones_the_frontend_has_as_tokens() -> None:
    css = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "styles" / "app.css").read_text(encoding="utf-8")
    own = {name for name in blocks.COLORS if f"--nd-c-{name}:" in css}
    theme = {"text", "accent", "green", "yellow", "red", "muted"}
    assert set(blocks.COLORS) == theme | own and own == {"blue", "violet", "pink", "orange"}


@pytest.mark.parametrize(
    ("block", "setting", "good", "bad"),
    [
        ({"type": "text", "text": "a"}, "size", "xl", "huge"),
        ({"type": "text", "text": "a"}, "weight", "bold", "900"),
        ({"type": "value", "path": "x"}, "size", "xs", "20px"),
        ({"type": "symbol", "icon": "flame"}, "size", "l", "m "),
        ({"type": "row", "children": [{"type": "divider"}]}, "gap", "none", "xl"),
        ({"type": "row", "children": [{"type": "divider"}]}, "align", "between", "stretch"),
        ({"type": "column", "children": [{"type": "divider"}]}, "gap", "l", "4px"),
        ({"type": "image", "src": "x"}, "height", "l", "100px"),
    ],
)
def test_karten7_ac3_sizes_and_gaps_are_steps_and_nothing_between(block: dict[str, Any], setting: str, good: str, bad: str) -> None:
    assert getattr(load.load_definition(one_block(**block, **{setting: good})).definition.blocks[0], setting) == good
    assert [one.code for one in refused(one_block(**block, **{setting: bad})).problems] == ["card_not_allowed"]


def test_karten7_ac3_there_is_no_place_for_html_or_css_in_a_block() -> None:
    for extra in ({"style": "x"}, {"class": "x"}, {"html": "<b>x</b>"}, {"width": 20}, {"css": "x"}):
        assert codes(refused(one_block(type="text", text="a", **extra))) == ["card_unknown_field"]
    properties = schema.json_schema()["$defs"]["TextBlock"]["properties"]
    assert set(properties) == {"id", "type", "text", "value", "size", "weight", "color"}


def test_karten7_ac3_a_text_is_kept_as_text_the_markup_in_it_is_not_taken_as_markup() -> None:
    loaded = load.load_definition(one_block(type="text", text="<script>alert(1)</script>"))
    assert loaded.definition.blocks[0].text == "<script>alert(1)</script>"


# -- AC-5: at most 100 blocks, counted through every row, column and list --------------------------


def test_karten7_ac5_a_hundred_blocks_are_taken() -> None:
    loaded = load.load_definition(with_blocks(*[{"type": "divider"}] * 100, buttons=[], rows=None, main=None))
    assert len(loaded.definition.blocks) == 100


def test_karten7_ac5_the_hundred_and_first_is_refused_with_a_clear_message() -> None:
    problem = refused(with_blocks(*[{"type": "divider"}] * 101, buttons=[], rows=None, main=None)).problems[0]
    assert (problem.code, problem.params) == ("card_too_many_blocks", {"limit": 100, "count": 101})
    assert problem.message == "A card has at most 100 blocks; this one has 101."


def test_karten7_ac5_blocks_inside_rows_columns_and_lists_count_too() -> None:
    inner = [{"type": "divider"}] * 50
    exact = with_blocks({"type": "row", "children": inner}, {"type": "column", "children": inner[:48]}, buttons=[], rows=None, main=None)
    assert len(load.load_definition(exact).definition.blocks) == 2  # two holders, 50 and 48 inside them
    over = with_blocks({"type": "row", "children": inner}, {"type": "column", "children": inner[:49]}, buttons=[], rows=None, main=None)
    assert codes(refused(over)) == ["card_too_many_blocks"]
    in_a_list = with_blocks({"type": "list", "item": inner * 2}, buttons=[], main=None)
    assert codes(refused(in_a_list)) == ["card_too_many_blocks"]


def test_karten7_ac5_the_depth_is_limited_to_six_levels() -> None:
    problem = refused(with_blocks(nested(7), buttons=[], rows=None, main=None)).problems[0]
    assert (problem.code, problem.params) == ("card_blocks_too_deep", {"limit": 6, "depth": 7})
    assert load.load_definition(with_blocks(nested(6), buttons=[], rows=None, main=None)).definition.blocks


def test_karten7_ac5_the_limit_is_checked_before_any_block_is_looked_at() -> None:
    data = yaml.safe_load(GLANCE)
    data["blocks"] = [1] * 101
    assert codes(refused(yaml.safe_dump(json.loads(json.dumps(data))))) == ["card_too_many_blocks"]


def test_karten7_ac5_the_schema_the_editor_reads_shows_the_limits() -> None:
    text = json.dumps(schema.json_schema())
    assert "100" in text and "6 levels" in text
