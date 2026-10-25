"""The calculation language of a custom card (KARTEN-5): what it can do, and that it can do nothing else."""

from __future__ import annotations

from typing import Any

import pytest

from app.cards import formula as calc


def run(text: str, data: dict[str, Any] | None = None) -> Any:
    return calc.evaluate(calc.compile_formula(text), lambda ref: ref.search(data or {}))


def test_karten5_ac5_calculates_with_brackets_and_rounds() -> None:
    assert run("1 + 2 * 3") == 7
    assert run("(1 + 2) * 3") == 9
    assert run("10 / 4 - 1") == 1.5
    assert run("-(2 + 3) * 2") == -10
    # "used out of the total, times 100": the example of the specification
    assert run("round({used} / {total} * 100, 1)", {"used": 5, "total": 30}) == 16.7
    assert run("round(2.5)") == 3
    assert run("round(-2.5)") == -3
    assert run("round({x}, 2)", {"x": 1.005}) == 1.01
    assert run("max(1, 7, 3) - min(4, 2) + abs(-1)") == 6


def test_karten5_ac5_comparisons_give_yes_or_no() -> None:
    assert run("{a} >= 80", {"a": 80}) is True
    assert run("{a} != 80", {"a": 80}) is False
    assert run("{a} == 5", {"a": "5"}) is True
    assert run("{a} < 5", {"a": "text"}) is None


def test_karten5_ac5_a_reference_is_a_whole_expression_of_the_answer() -> None:
    data = {"disk": {"used": 4, "sizes": [1, 2, 3]}, "records": [{"size": 10}, {"size": 5}]}
    assert run("{disk.used} * 2", data) == 8
    assert run("{records[0].size} + {records[1].size}", data) == 15
    assert run("{sum(records[].size)} / {length(records)}", data) == 7.5
    assert run('{disk."used"} + 1', data) == 5


def test_karten5_ec2_rounding_a_number_too_large_to_round_is_nothing_not_an_error() -> None:
    """``round({x}, 2)`` with 1e300 raised decimal.InvalidOperation and the card turned red with a server error."""
    assert run("round({x}, 2)", {"x": 1e300}) is None
    assert run("round({x})", {"x": -1e300}) is None
    assert run("round({x}, 2)", {"x": 12345678901.236}) == 12345678901.24


def test_karten5_ec2_dividing_by_zero_is_nothing_not_an_error() -> None:
    assert run("1 / 0") is None
    assert run("{a} / {b}", {"a": 1, "b": 0}) is None
    assert run("{a} / ({b} - {b})", {"a": 1, "b": 3}) is None


def test_karten5_ec1_a_value_that_is_missing_makes_the_result_nothing() -> None:
    assert run("{a} + 1", {}) is None
    assert run("{a} + 1", {"a": None}) is None
    assert run("round({a}, 1)", {}) is None
    assert run("{a} > 3", {}) is None


def test_karten5_ec3_a_text_that_is_all_a_number_counts_as_one() -> None:
    assert run("{a} * 2", {"a": "12.5"}) == 25
    assert run("{a} * 2", {"a": " 12.5 "}) == 25
    assert run("{a} * 2", {"a": "12,5"}) is None
    assert run("{a} * 2", {"a": "12 GB"}) is None
    assert run("{a} * 2", {"a": "nan"}) is None
    assert run("{a} * 2", {"a": True}) is None
    assert calc.as_number("1e3") == 1000
    assert calc.as_number("inf") is None


def test_karten5_ac9_a_broken_formula_names_the_place_and_the_reason() -> None:
    for text, position, reason in (
        ("1 +", 3, "ends where a value"),
        ("(1 + 2", 6, "Expected ')'"),
        ("1 2", 2, "Unexpected"),
        ("{a..b} + 1", 3, "Cannot read the reference"),
        ("{a", 0, "closing brace"),
        ("foo(1)", 0, "not known here"),
        ("round(1, 2, 3)", 0, "takes 1 to 2"),
        ("", 0, "empty"),
    ):
        with pytest.raises(calc.FormulaError) as caught:
            calc.compile_formula(text)
        assert caught.value.position == position, (text, caught.value.position)
        assert reason in caught.value.message, (text, caught.value.message)


def test_karten5_ac9_a_broken_template_names_the_place_and_the_reason() -> None:
    with pytest.raises(calc.FormulaError) as caught:
        calc.compile_template("S{season")
    assert caught.value.position == 1 and "closing brace" in caught.value.message
    with pytest.raises(calc.FormulaError) as caught:
        calc.compile_template("a } b")
    assert caught.value.position == 2


def test_karten5_formula_can_run_nothing_but_arithmetic() -> None:
    # A text from a shared card never reaches a Python interpreter: these are only unreadable.
    for hostile in ("__import__('os').system('x')", "().__class__", "open('f')", "1; 2", "a.b", "{a}.real", "lambda: 1", "1 if 1 else 2"):
        with pytest.raises(calc.FormulaError):
            calc.compile_formula(hostile)
    # ... and inside braces it is a JMESPath expression, which cannot call anything of the system either
    with pytest.raises(calc.FormulaError):
        calc.compile_formula("{__import__('os')}")


def test_karten5_a_type_that_does_not_fit_finds_nothing_instead_of_failing() -> None:
    assert run("{sum(a)} + 1", {"a": ["x", "y"]}) is None
    assert run("{avg(a)}", {"a": []}) is None


def test_karten5_a_lookup_that_nests_too_deeply_finds_nothing_instead_of_failing() -> None:
    class Deep:
        def search(self, data: Any) -> Any:
            raise RecursionError

    assert calc.Ref("x", Deep()).search({"x": 1}) is None


def test_karten5_formula_has_limits_for_length_and_depth() -> None:
    with pytest.raises(calc.FormulaError, match="longer than"):
        calc.compile_formula("1+" * 300 + "1")
    with pytest.raises(calc.FormulaError, match="nested deeper"):
        calc.compile_formula("(" * 40 + "1" + ")" * 40)
    with pytest.raises(calc.FormulaError, match="nested deeper"):
        calc.compile_formula("-" * 40 + "1")
    assert run("(" * 30 + "1" + ")" * 30) == 1
    with pytest.raises(calc.FormulaError, match="more than 200 parts"):
        calc.compile_formula("+".join(["1"] * 150))


def test_karten5_template_puts_values_into_text() -> None:
    template = calc.compile_template("S{seasonNumber}E{episodeNumber} {{literal}}")
    assert calc.render_template(template, lambda ref: ref.search({"seasonNumber": 2.0, "episodeNumber": "07"})) == "S2E07 {literal}"
    # a value that is missing makes the whole text missing: half a title is worse than none
    assert calc.render_template(template, lambda ref: ref.search({"seasonNumber": 2})) is None
    assert calc.render_template(calc.compile_template("{a}"), lambda ref: ref.search({"a": [1]})) is None
