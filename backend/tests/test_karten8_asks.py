"""KARTEN-8 AC-4, EC-9: a blank that takes a number, checked before anything leaves.

The kind ``number`` is new beside ``text``, ``url`` and ``choice``; those three behave as before (their own tests in
``test_picked_from_a_list.py`` and the tests of the adapters that use them).
"""

from __future__ import annotations

import pytest

from app.adapters.base import Action, AdapterError, Ask, WidgetData, fill_in
from app.services.collector import collector
from app.services.state import live

WIDGET = 9_008
KIB = Ask(name="ask.kib", label={"en": "KiB per second?", "de": "KiB je Sekunde?"}, kind="number", min=0, max=100000, step=1)


@pytest.fixture(autouse=True)
def _clean():
    live.forget(WIDGET)
    yield
    live.forget(WIDGET)


@pytest.mark.parametrize(("value", "taken"), [(0, 0), (100000, 100000), (512, 512), ("512", 512), (" 7 ", 7), (12.0, 12), ("1e3", 1000)])
def test_karten8_ec9_a_number_inside_the_range_goes_through_as_a_number(value, taken) -> None:
    got = fill_in(KIB, value)
    assert got == taken and type(got) is int


@pytest.mark.parametrize(
    "value",
    [-1, 100001, 1.5, "1.5", "abc", "", None, True, False, [5], {"v": 5}, float("nan"), float("inf"), "0x10", "5 KiB", "1_000"],
)
def test_karten8_ec9_a_number_outside_the_range_or_of_the_wrong_type_is_refused(value) -> None:
    with pytest.raises(AdapterError) as refused:
        fill_in(KIB, value)
    assert refused.value.code == "bad_value"


def test_karten8_ec9_steps_count_from_the_smallest_value_and_a_step_with_a_point_takes_points() -> None:
    half = Ask(name="ask.h", label="H", kind="number", min=0.5, max=10, step=0.25)
    assert fill_in(half, 0.75) == 0.75 and fill_in(half, "2") == 2
    with pytest.raises(AdapterError):
        fill_in(half, 0.6)
    tens = Ask(name="ask.t", label="T", kind="number", min=5, step=10)
    assert fill_in(tens, 25) == 25
    with pytest.raises(AdapterError):
        fill_in(tens, 20)


def test_karten8_ec9_a_number_without_bounds_takes_any_number() -> None:
    free = Ask(name="ask.f", label="F", kind="number")
    assert fill_in(free, -3.25) == -3.25 and fill_in(free, 10**6) == 10**6


def test_karten8_ec9_the_guard_refuses_a_wrong_number_before_the_adapter_sees_it() -> None:
    live.set(WIDGET, WidgetData(actions=[Action(id="button:limit", label="Limit", params={}, asks=[KIB])]))
    assert collector._refuse_unless_offered(WIDGET, "button:limit", {"ask.kib": "250"}) == {"ask.kib": 250}
    for wrong in (-5, "fast", 250.5, None):
        with pytest.raises(AdapterError) as refused:
            collector._refuse_unless_offered(WIDGET, "button:limit", {"ask.kib": wrong})
        assert refused.value.code == "bad_value", wrong


def test_karten8_ac4_the_other_kinds_of_blank_still_give_text() -> None:
    assert fill_in(Ask(name="q", label="Q"), "  hello ") == "hello"
    with pytest.raises(AdapterError):
        fill_in(Ask(name="q", label="Q"), 5)
