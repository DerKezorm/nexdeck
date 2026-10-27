"""KARTEN-7: what a card of blocks becomes once the answers are in (AC-2, AC-4, AC-8, EC-1, EC-7, buttons, demo mode).

The browser only draws: the tree it gets in ``meta.blocks`` has every value worked out, every colour and step filled in.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import pytest
import respx
import yaml
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import RENDERER_MIN, Context, WidgetData
from app.adapters.custom import ADAPTER, present
from app.cards import blocks, images, load, pipeline, store
from app.db import db_session
from app.services import holders
from app.services.collector import collector

from .conftest import CSRF, setup_admin
from .karten7_sample import GLANCE, changed, with_blocks
from .test_cards_placing import BASE, connection, page_of, place


@pytest.fixture
def fresh(client: TestClient) -> None:
    """A database of its own, for a test that keeps a card without going through the API."""


ANSWERS: dict[str, Any] = {
    "host": {"name": "nas", "state": "up", "cpu": 42, "memory": 61},
    "containers": [
        {"id": "b2", "name": "web", "state": "running"},
        {"id": "a1", "name": "db", "state": "stopped"},
        {"id": "c3", "name": "cache", "state": "running"},
    ],
}


def made(text: str = GLANCE, answers: Any = None, **keywords: Any) -> WidgetData:
    definition = load.load_definition(text).definition
    return present(definition, pipeline.run(definition, {"sys": ANSWERS if answers is None else answers}), **keywords)


def tree(text: str = GLANCE, answers: Any = None, **keywords: Any) -> list[dict[str, Any]]:
    return made(text, answers, **keywords).meta["blocks"]


def one_block(**fields: Any) -> str:
    return with_blocks(fields, buttons=[], rows=None, main=None)


def kinds(nodes: list[dict[str, Any]]) -> list[Any]:
    """The kinds of a tree, nested: ``["row", ["symbol", "text"], "divider"]``."""
    out: list[Any] = []
    for node in nodes:
        out.append(node["type"])
        inner = node.get("children") or ([block for row in node["rows"] for block in row["blocks"]] if node["type"] == "list" else None)
        if inner:
            out.append(kinds(inner))
    return out


# -- AC-2: the tree arrives as it was written --------------------------------------------------------------


def test_karten7_ac2_the_tree_arrives_in_the_order_and_the_nesting_it_was_written_in() -> None:
    data = made()
    assert kinds(data.meta["blocks"]) == ["row", ["symbol", "text", "badge"], "value", "progress", "sparkline", "divider", "list", ["row", ["text", "badge", "button"], "row", ["text", "badge", "button"], "row", ["text", "badge", "button"]], "button"]
    assert data.meta["custom"] is True


def test_karten7_ac2_every_setting_arrives_with_its_default_so_the_browser_calculates_nothing() -> None:
    row, value, progress, sparkline, divider, listing, reboot = tree()
    assert row == {
        "type": "row", "gap": "m", "align": "start", "wrap": True, "children": row["children"],
    }
    symbol, text, badge = row["children"]
    assert symbol == {"type": "symbol", "icon": "server", "color": "accent", "size": "m"}
    assert text == {"type": "text", "value": {"text": "nas"}, "color": "text", "size": "m", "weight": "bold"}
    assert badge == {"type": "badge", "value": {"text": "up"}, "color": "green"}
    assert value == {"type": "value", "id": "cpu", "label": {"en": "CPU", "de": "Prozessor"}, "value": {"text": "42%", "number": 42, "cell": {"value": 42, "text": "42%", "format": "percent", "digits": None, "unit": ""}}, "size": "l", "color": "text"}
    assert progress == {"type": "progress", "value": {"text": "61", "number": 61}, "max": 100.0, "color": "accent"}
    assert sparkline == {"type": "sparkline", "id": "cpu_trend", "value": {"text": "42", "number": 42}, "metric": "b_cpu_trend"}
    assert divider == {"type": "divider"}
    assert listing["empty"] == {"en": "No containers", "de": "Keine Container"}
    assert reboot["type"] == "button"


def test_karten7_ac2_a_column_and_the_steps_of_gap_align_and_wrap_arrive_as_written() -> None:
    nodes = tree(with_blocks(
        {"type": "column", "gap": "none", "children": [{"type": "row", "gap": "l", "align": "between", "wrap": False, "children": [{"type": "divider"}]}]},
        buttons=[], rows=None, main=None,
    ))
    column = nodes[0]
    assert (column["type"], column["gap"]) == ("column", "none") and "align" not in column and "wrap" not in column
    assert (column["children"][0]["gap"], column["children"][0]["align"], column["children"][0]["wrap"]) == ("l", "between", False)


def test_karten7_ac2_a_text_of_the_author_stands_in_english_and_carries_every_language_for_the_browser() -> None:
    [plain, many] = tree(with_blocks({"type": "text", "text": "Hello"}, {"type": "text", "text": {"de": "Hallo", "en": "Hello"}}, buttons=[], rows=None, main=None))
    assert plain["value"] == {"text": "Hello"}
    assert many["value"] == {"text": "Hello", "local": {"de": "Hallo", "en": "Hello"}}


def test_karten7_ac2_a_unit_goes_behind_the_text_and_the_rules_give_the_status_the_browser_colours_by() -> None:
    nodes = tree(with_blocks(
        {"type": "value", "path": "host.cpu", "unit": "GHz", "rules": [{"op": ">", "than": 40, "then": "warn"}]},
        {"type": "value", "path": "host.cpu", "format": "percent", "unit": "%", "rules": [{"op": ">", "than": 90, "then": "bad"}]},
        {"type": "badge", "value": {"path": "host.state", "rules": [{"op": "==", "than": "up", "then": "bad"}]}},
        {"type": "progress", "value": {"path": "host.memory"}},
        buttons=[], rows=None, main=None,
    ))
    assert nodes[0]["value"]["text"] == "42 GHz" and nodes[0]["value"]["number"] == 42 and nodes[0]["value"]["status"] == "warn"
    assert nodes[1]["value"]["text"] == "42%" and "status" not in nodes[1]["value"], "no status where no rule applies, and no second percent sign"
    assert nodes[2]["value"] == {"text": "up", "status": "error"}
    assert "status" not in nodes[3]["value"]


def test_karten7_ac6_a_number_a_time_and_a_unit_arrive_with_what_the_browser_needs_to_write_them_in_its_own_language_and_zone() -> None:
    nodes = tree(with_blocks(
        {"type": "value", "path": "n", "format": "number", "digits": 1, "unit": {"en": "items", "de": "Stück"}},
        {"type": "value", "path": "t", "format": "datetime"},
        {"type": "value", "path": "b", "format": "bytes"},
        {"type": "value", "path": "w"},
        {"type": "text", "value": {"path": "n", "format": "number"}},
        {"type": "badge", "value": {"path": "n", "unit": "kg"}},
        buttons=[], rows=None, main=None,
    ), {"n": 1234.56, "t": "2025-10-27T22:20:00Z", "b": 5368709120, "w": "up"})
    number, moment, size, word, text, badge = (node["value"] for node in nodes)
    assert number["cell"] == {"value": 1234.6, "text": "1234.6", "format": "number", "digits": 1, "unit": {"en": "items", "de": "Stück"}}
    assert number["text"] == "1234.6 items", "what a browser without the cell would show"
    assert moment["cell"]["value"] == "2025-10-27T22:20:00Z" and moment["cell"]["format"] == "datetime"
    assert size["cell"]["format"] == "bytes" and size["cell"]["text"] == "5.0 GB", "bytes stay as the server wrote them, as on every form"
    assert "cell" not in word, "a plain word needs nothing written for a language"
    assert "cell" not in tree(with_blocks({"type": "progress", "value": {"path": "n", "unit": "kg"}}, buttons=[], rows=None, main=None), {"n": 5})[0]["value"]
    assert text["cell"]["format"] == "number" and badge["cell"]["unit"] == "kg"


def test_karten7_ac2_the_colour_of_the_rules_reaches_the_card_but_a_row_of_a_list_does_not_colour_the_card() -> None:
    assert made(GLANCE, {**ANSWERS, "host": {**ANSWERS["host"], "cpu": 95}}).status == "bad"
    on_a_row = changed(GLANCE, blocks=[{"type": "list", "item": [{"type": "text", "value": {"path": "state", "rules": [{"op": "==", "than": "stopped", "then": "bad"}]}}]}], buttons=[], main=None)
    assert made(on_a_row).status == "ok"
    assert made(GLANCE).status == "ok"


def test_karten7_ac2_the_rules_of_the_card_colour_it_as_on_every_form() -> None:
    text = changed(GLANCE, rules=[{"value": "host.state", "op": "==", "than": "up", "then": "warn"}])
    assert made(text).status == "warn"


def test_karten7_ac2_a_progress_bar_may_name_its_largest_value_in_the_answers() -> None:
    text = with_blocks(
        {"type": "progress", "value": "used", "max": {"path": "total"}}, {"type": "progress", "value": "used", "max": 8},
        {"type": "progress", "value": "used", "max": {"path": "missing"}}, {"type": "progress", "value": "used", "max": {"path": "zero"}},
        buttons=[], rows=None, main=None,
    )
    nodes = tree(text, {"used": 3, "total": 12, "zero": 0})
    assert [node["max"] for node in nodes] == [12.0, 8.0, 100.0, 100.0]


def test_karten7_ac2_a_progress_bar_needs_a_largest_value_above_zero() -> None:
    with pytest.raises(load.CardInvalid):
        load.load_definition(one_block(type="progress", value="used", max=0))


# -- AC-4: a list repeats its blocks for every row, at most 50 -----------------------------------------------


def rows_of(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return next(node for node in nodes if node["type"] == "list")["rows"]


def titles(nodes: list[dict[str, Any]]) -> list[str]:
    return [row["blocks"][0]["children"][0]["value"]["text"] for row in rows_of(nodes)]


def test_karten7_ac4_the_template_is_repeated_for_every_row_sorted_and_read_inside_the_row() -> None:
    assert titles(tree()) == ["cache", "db", "web"], "sorted by name, each row reading name relative to itself"
    states = [row["blocks"][0]["children"][1]["value"]["text"] for row in rows_of(tree())]
    assert states == ["running", "stopped", "running"]


def test_karten7_ac4_rows_are_filtered_before_they_are_counted() -> None:
    text = changed(GLANCE, rows={"select": "containers", "filter": [{"field": "state", "op": "==", "value": "running"}], "sort": {"field": "name"}})
    assert titles(tree(text)) == ["cache", "web"]


def test_karten7_ac4_a_list_shows_fifty_rows_at_most_and_ten_when_the_card_says_nothing() -> None:
    many = {**ANSWERS, "containers": [{"id": f"i{number}", "name": f"n{number:03}", "state": "up"} for number in range(120)]}
    assert len(rows_of(tree(changed(GLANCE, rows={"select": "containers", "limit": 50}), many))) == 50
    assert len(rows_of(tree(changed(GLANCE, rows={"select": "containers"}), many))) == 10
    with pytest.raises(load.CardInvalid):
        load.load_definition(changed(GLANCE, rows={"select": "containers", "limit": 51}))


def test_karten7_ac4_two_lists_on_one_card_repeat_their_own_template_for_the_same_rows() -> None:
    template = [{"type": "text", "value": "name"}]
    other = [{"type": "badge", "value": "state"}]
    text = with_blocks({"type": "list", "item": template}, {"type": "list", "item": other}, buttons=[], main=None)
    first, second = tree(text)
    assert [row["blocks"][0]["value"]["text"] for row in first["rows"]] == ["cache", "db", "web"]
    assert [row["blocks"][0]["value"]["text"] for row in second["rows"]] == ["running", "stopped", "running"]


def test_karten7_ac4_a_list_without_rows_in_the_answers_is_empty_and_keeps_its_words() -> None:
    nodes = tree(GLANCE, {"host": ANSWERS["host"], "containers": []})
    listing = next(node for node in nodes if node["type"] == "list")
    assert listing["rows"] == [] and listing["empty"] == {"en": "No containers", "de": "Keine Container"}
    assert made(GLANCE, {"host": ANSWERS["host"]}).items == []


# -- AC-8: the main value makes a number card ------------------------------------------------------------------


def test_karten7_ac8_the_main_value_is_the_number_of_the_card_like_that_of_a_card_of_one_number() -> None:
    data = made()
    assert data.primary == {"label": {"en": "CPU", "de": "Prozessor"}, "value": 42, "unit": "%", "format": "percent", "digits": None, "text": "42%"}
    assert data.metrics["value"] == 42.0


def test_karten7_ac8_without_a_main_value_there_is_no_number_and_no_value_metric() -> None:
    data = made(changed(GLANCE, main=None))
    assert data.primary is None and "value" not in data.metrics


def test_karten7_ac8_a_main_value_that_is_a_word_is_a_headline_but_no_metric() -> None:
    text = with_blocks({"type": "value", "id": "state", "path": "host.state"}, buttons=[], rows=None, main="state")
    data = made(text)
    assert data.primary["value"] == "up" and "value" not in data.metrics


def test_karten7_ac8_the_main_value_inside_a_list_is_none() -> None:
    # A value in a list is a value of a row; the schema already refuses a main value that points there.
    with pytest.raises(load.CardInvalid):
        load.load_definition(changed(GLANCE, blocks=[{"type": "list", "item": [{"type": "value", "id": "cpu", "path": "state"}]}], buttons=[]))


def test_karten7_ac8_a_card_of_blocks_with_a_main_value_is_a_tile_of_key_figures_and_one_without_is_not(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    with db_session() as db:
        store.create(db, GLANCE.replace("requires: [jsonapi]", "requires: [sonarr]"))
        store.create(db, changed(GLANCE.replace("requires: [jsonapi]", "requires: [sonarr]"), slug="no-main", main=None))
    page, sonarr = page_of(client), connection(client, "sonarr")
    figures = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.figures", "title": "Figures"}, headers=CSRF).json()["widget"]
    with_main = place(client, page, sonarr, kind="custom.builder", card="server-glance").json()["widget"]
    without = place(client, page, sonarr, kind="custom.builder", card="no-main").json()["widget"]
    assert holders.is_number_card("custom.builder", {"card": "server-glance"}) and not holders.is_number_card("custom.builder", {"card": "no-main"})
    assert not holders.is_number_card("custom.builder") and not holders.is_number_card("custom.builder", {"card": "gone"})
    taken = client.post(f"/api/v1/pages/{page}/place", json={"widget_id": with_main["id"], "into": "group", "group_id": figures["id"]}, headers=CSRF)
    assert taken.status_code == 200, taken.text
    refused = client.post(f"/api/v1/pages/{page}/place", json={"widget_id": without["id"], "into": "group", "group_id": figures["id"]}, headers=CSRF)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "not_a_number"


def test_karten7_ac8_key_figures_that_hold_cards_keep_only_the_number_cards_when_they_are_saved(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    with db_session() as db:
        store.create(db, GLANCE.replace("requires: [jsonapi]", "requires: [sonarr]"))
        store.create(db, changed(GLANCE.replace("requires: [jsonapi]", "requires: [sonarr]"), slug="no-main", main=None))
    page, sonarr = page_of(client), connection(client, "sonarr")
    yes = place(client, page, sonarr, kind="custom.builder", card="server-glance").json()["widget"]["id"]
    no = place(client, page, sonarr, kind="custom.builder", card="no-main").json()["widget"]["id"]
    made_figures = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.figures", "title": "F", "options": {"cards": [yes, no]}}, headers=CSRF)
    assert made_figures.status_code == 201, made_figures.text
    assert made_figures.json()["widget"]["options"]["cards"] == [yes]


def test_karten7_ac8_the_library_tells_which_cards_of_blocks_name_a_main_value(client: TestClient) -> None:
    setup_admin(client)
    with db_session() as db:
        store.create(db, GLANCE)
        store.create(db, changed(GLANCE, slug="no-main", main=None))
    cards = {card["slug"]: card for card in client.get("/api/v1/cards/library").json()["cards"]}
    assert (cards["server-glance"]["form"], cards["server-glance"]["main"]) == ("builder", "cpu")
    assert cards["no-main"]["main"] is None


# -- EC-1: a block without a value stays empty and nothing moves ----------------------------------------------------


def test_karten7_ec1_a_block_without_a_value_stays_empty_and_the_layout_keeps_its_shape() -> None:
    full = tree()
    bare = tree(GLANCE, {"host": {}, "containers": []})
    assert kinds(full)[:7] == kinds(bare)[:7], "the same blocks in the same places up to the list"
    row = bare[0]["children"]
    assert [child["value"] for child in row[1:]] == [None, None], "text and badge are empty, not gone"
    assert bare[1]["value"] is None and bare[2]["value"] is None and bare[3]["value"] is None
    assert bare[1]["label"] == {"en": "CPU", "de": "Prozessor"}, "the label stays where the value is missing"


def test_karten7_ec1_a_missing_main_value_leaves_the_card_without_a_number_instead_of_failing() -> None:
    data = made(GLANCE, {"host": {}, "containers": []})
    assert data.primary["value"] is None and "value" not in data.metrics and data.status == "ok"


def test_karten7_ec1_a_value_that_is_a_list_or_an_object_is_no_value_to_show() -> None:
    nodes = tree(with_blocks({"type": "text", "value": "host"}, {"type": "text", "value": "containers"}, buttons=[], rows=None, main=None))
    assert [node["value"] for node in nodes] == [None, None]


def test_karten7_ec1_an_empty_text_of_the_author_is_empty_too() -> None:
    assert tree(one_block(type="text", text=""))[0]["value"] is None


# -- EC-7: pictures ---------------------------------------------------------------------------------------------------


def picture(link: Any, **more: Any) -> str | None:
    text = with_blocks({"type": "image", "src": "pic", "height": "l"}, buttons=[], rows=None, main=None)
    [node] = tree(text, {"pic": link}, base=BASE, **more)
    assert node["type"] == "image" and node["height"] == "l"
    return node["src"]


def test_karten7_ec7_a_picture_with_an_http_address_goes_through_the_image_route_of_the_card() -> None:
    src = picture("https://img.example.com/a.png", widget_id=7)
    assert src is not None and src.startswith("/api/v1/widgets/7/image?path=")
    art = parse_qs(urlsplit(src).query)["path"][0]
    assert images.external_address(art) == "https://img.example.com/a.png"


def test_karten7_ec7_a_picture_on_the_connection_keeps_the_credentials_of_the_connection() -> None:
    src = picture("/poster/a.jpg", widget_id=7)
    assert src is not None
    art = parse_qs(urlsplit(src).query)["path"][0]
    assert images.connection_path(art, BASE) == "/poster/a.jpg"
    assert picture(f"{BASE}/poster/b.jpg", widget_id=7) is not None


@pytest.mark.parametrize("link", [None, "", "javascript:alert(1)", "data:image/png;base64,AAAA", "ftp://example.com/a.png", "//evil.example.com/a.png", "not an address", 42, {"a": 1}, ["x"], "file:///etc/passwd"])
def test_karten7_ec7_anything_that_is_no_http_address_and_no_path_is_the_placeholder(link: Any) -> None:
    assert picture(link, widget_id=7) is None


def test_karten7_ec7_a_picture_a_template_builds_may_only_lead_to_the_connection() -> None:
    text = with_blocks({"type": "image", "src": {"template": "/art/{id}"}}, buttons=[], rows=None, main=None)
    [node] = tree(text, {"id": "x"}, base=BASE, widget_id=3)
    assert images.connection_path(parse_qs(urlsplit(node["src"]).query)["path"][0], BASE) == "/art/x"
    external = with_blocks({"type": "image", "src": {"template": "https://evil.example.com/{id}"}}, buttons=[], rows=None, main=None)
    assert "card_picture_address" in [problem.code for problem in refused_codes(external)]


def refused_codes(text: str) -> list[Any]:
    with pytest.raises(load.CardInvalid) as caught:
        load.load_definition(text)
    return caught.value.problems


def test_karten7_ec7_a_formula_cannot_build_a_picture_address() -> None:
    assert [problem.code for problem in refused_codes(one_block(type="image", src={"formula": "{a} + {b}"}))] == ["card_picture_address"]


def test_karten7_ec7_in_the_preview_and_in_demo_mode_no_picture_is_asked_for() -> None:
    assert picture("https://img.example.com/a.png", pictures=False) is None


def test_karten7_ec7_without_a_card_to_ask_the_address_stays_the_one_the_preview_rewrites() -> None:
    src = picture("https://img.example.com/a.png")
    assert src is not None and src.startswith("proxy:")


def test_karten7_ec7_a_picture_inside_a_list_reads_its_address_inside_the_row() -> None:
    text = with_blocks({"type": "list", "item": [{"type": "image", "src": "poster"}]}, buttons=[], main=None)
    answers = {"containers": [{"id": "a", "name": "A", "poster": "/p/a.jpg"}, {"id": "b", "name": "B", "poster": "javascript:x"}]}
    rows = rows_of(tree(text, answers, base=BASE, widget_id=5))
    assert images.connection_path(parse_qs(urlsplit(rows[0]["blocks"][0]["src"]).query)["path"][0], BASE) == "/p/a.jpg"
    assert rows[1]["blocks"][0]["src"] is None


# -- sparklines ------------------------------------------------------------------------------------------------------------


def test_karten7_a_sparkline_records_its_number_under_b_and_its_id() -> None:
    data = made()
    assert data.metrics == {"b_cpu_trend": 42.0, "value": 42.0}
    two = with_blocks(
        {"type": "column", "children": [{"type": "sparkline", "id": "one", "value": "host.cpu"}]},
        {"type": "sparkline", "id": "two", "value": "host.memory"}, {"type": "sparkline", "id": "word", "value": "host.state"},
        buttons=[], rows=None, main=None,
    )
    assert made(two).metrics == {"b_one": 42.0, "b_two": 61.0}, "a word has no history; a block in a column is found too"


# -- buttons ------------------------------------------------------------------------------------------------------------


def test_karten7_a_button_on_a_row_carries_the_values_of_that_row_and_the_item_carries_it_for_the_guard() -> None:
    data = made()
    rows = rows_of(data.meta["blocks"])
    pressed = [row["blocks"][0]["children"][2]["action"] for row in rows]
    assert [one["id"] for one in pressed] == ["button:restart"] * 3
    assert [one["params"] for one in pressed] == [{"id": "c3"}, {"id": "a1"}, {"id": "b2"}]
    assert [row["actions"] for row in rows] == [[one] for one in pressed], "the row lists the buttons it draws"
    assert [[one["params"] for one in item["actions"]] for item in data.items] == [[{"id": "c3"}], [{"id": "a1"}], [{"id": "b2"}]]
    assert [item["title"] for item in data.items] == ["cache", "db", "web"]


def test_karten7_a_button_on_the_card_is_an_action_of_the_card_and_drawn_where_the_block_is() -> None:
    data = made()
    [offered] = data.actions
    assert (offered.id, offered.confirm, offered.danger, offered.params) == ("button:reboot", True, True, {})
    assert data.meta["blocks"][-1]["action"] == offered.model_dump()


def test_karten7_a_button_whose_value_is_missing_is_not_offered_and_its_place_stays() -> None:
    answers = {**ANSWERS, "containers": [{"name": "x", "state": "up"}, {"id": "../etc", "name": "y", "state": "up"}, {"id": "ok1", "name": "z", "state": "up"}]}
    data = made(GLANCE, answers)
    rows = rows_of(data.meta["blocks"])
    by_name = {row["blocks"][0]["children"][0]["value"]["text"]: row for row in rows}
    assert by_name["x"]["blocks"][0]["children"][2] == {"type": "button", "action": None}
    assert by_name["y"]["blocks"][0]["children"][2]["action"] is None and "actions" not in by_name["y"]
    assert by_name["z"]["blocks"][0]["children"][2]["action"]["params"] == {"id": "ok1"}
    assert [item.get("actions") for item in data.items if item["title"] in ("x", "y")] == [None, None]


def test_karten7_a_button_that_is_not_drawn_by_any_block_is_not_offered() -> None:
    reboot = [one for one in yaml.safe_load(GLANCE)["buttons"] if one["id"] == "reboot"]
    text = changed(GLANCE, blocks=[{"type": "divider"}], buttons=reboot, rows=None, main=None)
    data = made(text)
    assert data.actions == [] and data.items == []


def test_karten7_a_button_of_the_card_in_a_list_is_the_same_action_on_every_row() -> None:
    text = with_blocks({"type": "list", "item": [{"type": "button", "button": "reboot"}]}, main=None)
    data = made(text)
    rows = rows_of(data.meta["blocks"])
    assert len(rows) == 3 and {row["blocks"][0]["action"]["id"] for row in rows} == {"button:reboot"}
    assert [one.id for one in data.actions] == ["button:reboot"], "offered once, however often it is drawn"


# -- the kind, its floor, the demo mode -----------------------------------------------------------------------------------


def test_karten7_the_card_of_blocks_is_a_kind_of_the_custom_adapter_with_the_renderer_builder_and_a_floor() -> None:
    widget = get_adapter("custom").widget("builder")
    assert (widget.kind, widget.renderer) == ("builder", "builder")
    assert RENDERER_MIN["builder"] == (2, 2) and widget.min_size[0] >= 2 and widget.min_size[1] >= 2
    assert widget.default_size[0] >= widget.min_size[0] and widget.default_size[1] >= widget.min_size[1]
    assert not holders.is_number_card("custom.builder"), "whether it is a number is the card's to say, by its main value"


def test_karten7_the_size_a_definition_asks_for_never_goes_below_the_floor(fresh: None) -> None:
    with db_session() as db:
        store.create(db, changed(GLANCE, size={"w": 1, "h": 1}, min_size={"w": 1, "h": 1}))
    assert ADAPTER.widget("builder").min_size == (2, 2)
    from app.adapters.custom import sizes_of

    assert sizes_of({"card": "server-glance"}, (3, 3), (2, 2)) == ((2, 2), (2, 2))


def test_karten7_demo_mode_draws_the_example_answers_of_the_card_without_asking_a_service(fresh: None) -> None:
    with db_session() as db:
        store.create(db, GLANCE)
    data = ADAPTER.demo("builder", {"card": "server-glance"}, 0)
    nodes = data.meta["blocks"]
    assert nodes[0]["children"][1]["value"]["text"] == "nas" and data.primary["value"] == 42
    assert titles(nodes) == ["db", "web"]
    assert [row["blocks"][0]["children"][2]["action"]["params"] for row in rows_of(nodes)] == [{"id": "b2"}, {"id": "a1"}]


def test_karten7_demo_mode_without_example_answers_says_so(fresh: None) -> None:
    from app.adapters.base import AdapterError

    with db_session() as db:
        store.create(db, changed(GLANCE, demo=None))
    with pytest.raises(AdapterError) as caught:
        ADAPTER.demo("builder", {"card": "server-glance"}, 0)
    assert caught.value.code == "no_demo_data"


def test_karten7_demo_mode_shows_no_pictures(fresh: None) -> None:
    text = changed(GLANCE, blocks=[{"type": "image", "src": "host.pic"}], buttons=[], main=None, rows=None, demo={"sys": {"host": {"pic": "https://img.example.com/a.png"}}})
    with db_session() as db:
        store.create(db, text)
    assert ADAPTER.demo("builder", {"card": "server-glance"}, 0).meta["blocks"][0]["src"] is None


# -- on a board, through the collector ------------------------------------------------------------------------------------------

SERVICE = "http://svc.example.com:8080"


@pytest.fixture
def board(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, int]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    with db_session() as db:
        store.create(db, GLANCE)
    made_connection = client.post("/api/v1/integrations", json={"kind": "jsonapi", "name": "Glance", "config": {"url": SERVICE, "token": "secret-token-1"}}, headers=CSRF)
    assert made_connection.status_code == 201, made_connection.text
    page = page_of(client)
    widget = place(client, page, int(made_connection.json()["id"]), kind="custom.builder", card="server-glance")
    assert widget.status_code == 201, widget.text
    return client, int(widget.json()["widget"]["id"])


@respx.mock
def test_karten7_a_card_of_blocks_on_a_board_arrives_drawn_with_its_buttons_and_history(board: tuple[TestClient, int]) -> None:
    client, widget = board
    respx.get(f"{SERVICE}/api/system").mock(return_value=httpx.Response(200, json=ANSWERS))
    shown = client.post(f"/api/v1/widgets/{widget}/refresh", headers=CSRF)
    assert shown.status_code == 200, shown.text
    data = shown.json()
    assert data["error"] is None and kinds(data["meta"]["blocks"])[0] == "row"
    assert data["primary"]["value"] == 42 and data["metrics"]["b_cpu_trend"] == 42.0
    assert [one["id"] for one in data["actions"]] == ["button:reboot"]
    assert [item["actions"][0]["params"] for item in data["items"]] == [{"id": "c3"}, {"id": "a1"}, {"id": "b2"}]
    assert "secret-token-1" not in shown.text


@respx.mock
def test_karten7_a_button_on_a_row_of_a_card_of_blocks_runs_with_the_values_of_its_row(board: tuple[TestClient, int]) -> None:
    client, widget = board
    respx.get(f"{SERVICE}/api/system").mock(return_value=httpx.Response(200, json=ANSWERS))
    client.post(f"/api/v1/widgets/{widget}/refresh", headers=CSRF)
    restart = respx.post(f"{SERVICE}/api/containers/a1/restart").mock(return_value=httpx.Response(204))
    answer = client.post(f"/api/v1/widgets/{widget}/actions/button:restart", json={"params": {"id": "a1"}}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert restart.call_count == 1 and restart.calls.last.request.headers["authorization"] == "Bearer secret-token-1"
    refused = client.post(f"/api/v1/widgets/{widget}/actions/button:restart", json={"params": {"id": "../system/reboot"}}, headers=CSRF)
    assert refused.status_code >= 400 and restart.call_count == 1


@respx.mock
def test_karten7_a_picture_of_a_card_of_blocks_on_a_board_is_fetched_through_its_image_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    from app.routers import widgets as widget_routes

    widget_routes._images.clear()
    text = changed(GLANCE, blocks=[{"type": "image", "src": "host.pic"}], buttons=[], main=None, rows=None)
    with db_session() as db:
        store.create(db, text)
    made_connection = client.post("/api/v1/integrations", json={"kind": "jsonapi", "name": "Glance", "config": {"url": SERVICE, "token": "secret-token-1"}}, headers=CSRF)
    placed = place(client, page_of(client), int(made_connection.json()["id"]), kind="custom.builder", card="server-glance")
    widget = int(placed.json()["widget"]["id"])
    respx.get(f"{SERVICE}/api/system").mock(return_value=httpx.Response(200, json={"host": {"pic": "/img/a.png"}}))
    src = client.post(f"/api/v1/widgets/{widget}/refresh", headers=CSRF).json()["meta"]["blocks"][0]["src"]
    assert src.startswith(f"/api/v1/widgets/{widget}/image?path=")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    served = respx.get(f"{SERVICE}/img/a.png").mock(return_value=httpx.Response(200, content=png, headers={"content-type": "image/png"}))
    got = client.get(src)
    assert got.status_code == 200 and got.content == png
    assert served.calls.last.request.headers["authorization"] == "Bearer secret-token-1", "a picture on the connection is fetched with its credentials"
    forged = client.get(f"/api/v1/widgets/{widget}/image?path={quote('/img/other.png', safe='')}")
    assert forged.status_code >= 400


# -- the editor's calls --------------------------------------------------------------------------------------------------------------


def test_karten7_the_editor_can_check_and_preview_the_example_card_of_blocks(client: TestClient) -> None:
    setup_admin(client)
    assert client.post("/api/v1/cards/check", json={"yaml": GLANCE}, headers=CSRF).json() == {"ok": True}
    bad = client.post("/api/v1/cards/check", json={"yaml": GLANCE.replace("type: divider", "type: ruler")}, headers=CSRF).json()
    assert bad["ok"] is False and bad["problems"][0]["code"] == "card_bad_block" and bad["problems"][0]["line"]
    preview = client.post("/api/v1/cards/preview", json={"yaml": GLANCE, "demo": True}, headers=CSRF)
    assert preview.status_code == 200, preview.text
    out = preview.json()
    assert out["primary"]["value"] == 42 and kinds(out["meta"]["blocks"])[0] == "row" and len(rows_of(out["meta"]["blocks"])) == 2
    assert out["meta"]["blocks"][-1]["action"]["id"] == "button:reboot"


@respx.mock
def test_karten7_the_preview_of_a_card_of_blocks_rewrites_its_pictures_to_the_route_of_the_editor(client: TestClient) -> None:
    setup_admin(client)
    made_connection = client.post("/api/v1/integrations", json={"kind": "jsonapi", "name": "Glance", "config": {"url": SERVICE, "token": "secret-token-1"}}, headers=CSRF)
    number = int(made_connection.json()["id"])
    text = changed(GLANCE, blocks=[{"type": "column", "children": [{"type": "image", "src": "host.pic"}]}], buttons=[], main=None, rows=None)
    respx.get(f"{SERVICE}/api/system").mock(return_value=httpx.Response(200, json={"host": {"pic": "/img/a.png"}}))
    out = client.post("/api/v1/cards/preview", json={"yaml": text, "integration_id": number}, headers=CSRF).json()
    src = out["meta"]["blocks"][0]["children"][0]["src"]
    assert src.startswith(f"/api/v1/cards/preview-image?integration_id={number}&path=")


def test_karten7_the_schema_the_editor_reads_has_the_form_and_its_blocks(client: TestClient) -> None:
    setup_admin(client)
    document = client.get("/api/v1/cards/schema").json()
    assert "BuilderCard" in document["$defs"] and {f"{kind.capitalize()}Block" for kind in blocks.KINDS} <= set(document["$defs"])


def test_karten7_a_fetch_of_a_card_of_blocks_without_a_connection_says_the_connection_is_missing(fresh: None) -> None:
    import asyncio

    from app.adapters.base import AdapterError

    with db_session() as db:
        store.create(db, GLANCE)
    async def go() -> None:
        async with httpx.AsyncClient() as http:
            await ADAPTER.fetch("builder", {}, {"card": "server-glance"}, Context(http))

    with pytest.raises(AdapterError) as caught:
        asyncio.run(go())
    assert caught.value.code == "connection_missing"


def test_karten7_ec7_an_address_a_card_put_together_never_leaves_the_connection_even_if_the_check_were_skipped() -> None:
    # The check on saving refuses it; this holds the last line: a picture address that is not one value of the answers,
    # as it stands, may only be a path on the connection (the same rule as for the pictures of a list).
    from app.cards import schema

    data = {
        "nexdeck-card": 1, "slug": "x", "name": "X", "version": "1.0.0", "requires": ["jsonapi"], "requests": [{"id": "sys", "path": "/a"}],
        "form": "builder", "blocks": [{"type": "image", "src": {"template": "https://evil.example.com/{id}?d={id}"}}],
    }
    definition = schema.ADAPTER.validate_python(data)
    result = pipeline.run(definition, {"sys": {"id": "secret"}})
    assert result.tree[0]["link"] == "https://evil.example.com/secret?d=secret" and result.tree[0]["named"] is False
    assert present(definition, result, base=BASE, widget_id=1).meta["blocks"][0]["src"] is None


def test_karten7_ac2_a_rule_on_a_value_inside_a_row_or_a_column_colours_the_card_too() -> None:
    down = {**ANSWERS, "host": {**ANSWERS["host"], "state": "down"}}
    assert made(GLANCE, down).status == "bad", "the badge sits in a row"
    deeper = with_blocks(
        {"type": "column", "children": [{"type": "row", "children": [{"type": "badge", "value": {"path": "host.state", "rules": [{"op": "==", "than": "down", "then": "warn"}]}}]}]},
        buttons=[], rows=None, main=None,
    )
    assert made(deeper, down).status == "warn" and made(deeper).status == "ok"
