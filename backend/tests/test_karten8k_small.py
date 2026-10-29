"""Etappe 8, small things found afterwards (karten8k): the words of a problem fill all their placeholders."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.cards import load

from .cards_sample import changed
from .conftest import CSRF, setup_admin
from .karten12_sample import PLAIN, separated
from .test_board_yaml_edit import _board, _card, _save, _text


def problems(text: str) -> list[load.Problem]:
    try:
        load.load_definition(text)
    except load.CardInvalid as failure:
        return list(failure.problems)
    raise AssertionError("the text was taken")


def test_karten8k_a_form_that_is_none_of_the_forms_names_the_forms_the_interface_can_fill_in() -> None:
    found = problems(changed("form: value", "form: gauge"))
    form = next(one for one in found if one.path == "form")
    # The interface says "This must be one of {{expected}}": the parameter it is given is `expected`, and no code asks for `pattern` without sending one.
    assert form.code == "card_not_allowed"
    assert form.params == {"expected": "value, stats, list, posters, builder"}


def test_karten8k_a_pattern_problem_sends_the_pattern_its_words_ask_for() -> None:
    found = problems(changed("every: 30s", "every: 5x"))
    one = next(one for one in found if one.path == "requests[0].every")
    assert one.code == "card_bad_form" and set(one.params) == {"pattern"} and one.params["pattern"]


# -- the answer of PUT /boards/{slug}/yaml shows the board after the change ---------------------------------------


def test_karten8k_the_answer_of_a_change_by_yaml_is_the_board_after_it(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Home")
    page = board["pages"][0]["id"]
    _card(client, page, "core.markdown", title="Notes", options={"content": "old"})
    _card(client, page, "core.clock", title="Clock")
    document = _text(client, board["slug"])
    cards = {card["title"]: card for card in document["pages"][0]["widgets"]}
    cards["Notes"]["title"] = "Shopping"
    cards["Notes"]["options"] = {"content": "milk"}
    document["pages"][0]["widgets"] = [cards["Notes"], {"kind": "core.clock", "title": "New clock"}]
    document["board"]["name"] = "House"
    answer = _save(client, board["slug"], document)
    assert answer.status_code == 200, answer.text
    after = client.get(f"/api/v1/boards/{board['slug']}").json()
    assert answer.json()["name"] == "House"
    shown = {card["title"]: card["options"] for card in answer.json()["pages"][0]["widgets"]}
    assert set(shown) == {"Shopping", "New clock"} and shown["Shopping"]["content"] == "milk"
    assert answer.json()["pages"] == after["pages"], "the answer is the board a request for it gives straight after"


# -- a document of a file that names no short name is told apart by its place -----------------------------------


def test_karten8k_documents_without_a_short_name_are_named_by_their_line_not_by_none(client: TestClient) -> None:
    setup_admin(client)
    nameless = changed("slug: queue-size\n", "", PLAIN)
    seen = client.post("/api/v1/cards/import/check", json={"text": separated(PLAIN, nameless, nameless)}, headers=CSRF)
    assert seen.status_code == 200, seen.text
    ids = [one["id"] for one in seen.json()["documents"]]
    assert ids[0] == "card:queue-size"
    assert len(set(ids)) == 3 and not any("None" in one for one in ids), ids
    assert all(one.startswith("card:#") for one in ids[1:])
    assert [one["line"] for one in seen.json()["documents"][1:]] == [int(one.split("#")[1]) for one in ids[1:]]
