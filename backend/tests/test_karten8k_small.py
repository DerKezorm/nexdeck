"""Etappe 8, small things found afterwards (karten8k): the words of a problem fill all their placeholders."""

from __future__ import annotations

from app.cards import load

from .cards_sample import VALUE_CARD, changed


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
