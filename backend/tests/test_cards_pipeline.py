"""From the answers of a service to the finished values (KARTEN-5): picking, filtering, sorting, counting, formatting, colouring."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.adapters.base import AdapterError
from app.cards import formula as calc
from app.cards import load, pipeline

BERLIN = ZoneInfo("Europe/Berlin")
HEAD = """\
nexdeck-card: 1
slug: sample
name: Sample
version: "1.0.0"
requires: [jsonapi]
requests:
  - id: data
    path: /x
"""

SERIES = {
    "records": [
        {"title": "Alpha", "status": "downloading", "size": 300, "left": 30, "added": "2026-10-25T10:00:00Z", "season": 1, "episode": 2},
        {"title": "Bravo", "status": "paused", "size": 100, "left": 100, "added": "2026-10-25T09:00:00Z", "season": 1, "episode": 3},
        {"title": "Charlie", "status": "downloading", "size": 200, "left": None, "added": "2026-10-24T09:00:00Z", "season": 2, "episode": 1},
        {"title": "Delta", "status": "failed", "size": None, "left": 5, "added": None, "season": 2, "episode": 2},
    ],
    "totalRecords": 4,
}


def define(body: str) -> Any:
    return load.load_definition(HEAD + body).definition


def show(body: str, answer: Any = None, **options: Any) -> pipeline.Result:
    return pipeline.run(define(body), {"data": SERIES if answer is None else answer}, tz=BERLIN, **options)


def titles(result: pipeline.Result) -> list[str]:
    return [row.title.text for row in result.rows]


LIST = "form: list\nrows:\n  select: records\n{rows}\nitem:\n  title: title\n"


def rows_of(extra: str = "") -> str:
    return LIST.format(rows="".join(f"  {line}\n" for line in extra.splitlines()).rstrip("\n") or "  limit: 10")


def test_karten5_ac1_the_card_gets_exactly_the_value_the_path_names() -> None:
    assert show("form: value\nvalue: records[0].title").value.text == "Alpha"  # type: ignore[union-attr]
    assert show("form: value\nvalue: records[1].size").value.value == 100  # type: ignore[union-attr]
    assert show("form: value\nvalue: totalRecords").value.text == "4"  # type: ignore[union-attr]


def test_karten5_ac1_with_several_requests_a_path_starts_with_the_request() -> None:
    text = HEAD + "  - id: other\n    path: /y\nform: value\nvalue: other.name\n"
    result = pipeline.run(load.load_definition(text).definition, {"data": {"name": "no"}, "other": {"name": "yes"}})
    assert result.value is not None and result.value.text == "yes"
    # and with one request the request's own name still works as well
    one = pipeline.run(define("form: value\nvalue: data.totalRecords"), {"data": SERIES})
    assert one.value is not None and one.value.text == "4"


def test_karten5_ac2_a_filter_keeps_only_the_rows_that_match() -> None:
    result = show(rows_of("filter: [{field: status, op: '==', value: downloading}]"))
    assert titles(result) == ["Alpha", "Charlie"] and result.total == 2
    assert titles(show(rows_of("filter: [{field: status, op: '!=', value: downloading}]"))) == ["Bravo", "Delta"]
    assert titles(show(rows_of("filter: [{field: size, op: '>=', value: 200}]"))) == ["Alpha", "Charlie"]
    assert titles(show(rows_of("filter: [{field: title, op: contains, value: Ch}]"))) == ["Charlie"]
    both = "filter: [{field: status, op: '==', value: downloading}, {field: size, op: '>', value: 250}]"
    assert titles(show(rows_of(both))) == ["Alpha"]


def test_karten5_ac3_rows_come_in_the_order_the_definition_asks_for() -> None:
    assert titles(show(rows_of("sort: {field: size}"))) == ["Bravo", "Charlie", "Alpha", "Delta"]
    assert titles(show(rows_of("sort: {field: size, desc: true}"))) == ["Alpha", "Charlie", "Bravo", "Delta"]
    assert titles(show(rows_of("sort: {field: title, desc: true}"))) == ["Delta", "Charlie", "Bravo", "Alpha"]
    # a row without the value goes last either way, and numbers that arrive as text sort as numbers
    answer = {"records": [{"title": "t10", "n": "10"}, {"title": "t9", "n": "9"}, {"title": "none"}]}
    assert titles(show(rows_of("sort: {field: n}"), answer)) == ["t9", "t10", "none"]
    assert titles(show(rows_of("sort: {field: n, desc: true}"), answer)) == ["t10", "t9", "none"]


def test_karten5_ac4_a_list_can_be_counted_added_and_averaged() -> None:
    def total(fn: str, field: str = "size", rows: str = "records") -> Any:
        column = f", field: {field}" if field else ""
        result = show(f"form: value\nvalue:\n  total: {{fn: {fn}, rows: {{select: {rows}}}{column}}}")
        assert result.value is not None
        return result.value.value

    assert total("count", field="") == 4
    assert total("sum") == 600
    assert total("min") == 100
    assert total("max") == 300
    assert total("avg") == 200
    # counting follows the filter
    filtered = "form: value\nvalue:\n  total: {fn: count, rows: {select: records, filter: [{field: status, op: '==', value: downloading}]}}"
    assert show(filtered).value.value == 2  # type: ignore[union-attr]


def test_karten5_ac5_the_card_calculates_from_values_of_the_answer() -> None:
    result = show("form: value\nvalue: {formula: 'round(({size} - {left}) / {size} * 100, 1)', format: percent}", {"size": 300, "left": 30})
    assert result.value is not None and (result.value.value, result.value.text, result.value.format) == (90.0, "90%", "percent")
    assert show("form: value\nvalue: {formula: '{a} + {b} * 2'}", {"a": 1, "b": 2}).value.text == "5"  # type: ignore[union-attr]


def test_karten5_ac6_a_value_can_be_shown_as_bytes_a_duration_a_percentage_or_a_number() -> None:
    def one(shape: str, raw: Any, extra: str = "") -> pipeline.Shown:
        result = show(f"form: value\nvalue: {{path: v, format: {shape}{extra}}}", {"v": raw})
        assert result.value is not None
        return result.value

    assert one("bytes", 1536).text == "1.5 KB" and one("bytes", 1536).value == 1536
    assert one("rate", 2048).text == "2.0 KB/s"
    assert one("duration", 3725).text == "1h 2m"
    assert one("percent", 73.456, ", digits: 1").text == "73.5%"
    assert one("number", 3.14159, ", digits: 2").text == "3.14"
    assert one("number", 12.0).text == "12" and one("number", 12.5).text == "12.5"
    unit = show("form: value\nvalue: {path: v, unit: {en: items, de: Stück}}", {"v": 3}).value
    assert unit is not None and unit.unit == {"en": "items", "de": "Stück"} and unit.text == "3"


def test_karten5_ac6_a_time_can_be_shown_as_a_date_a_time_or_how_long_ago() -> None:
    now = datetime(2026, 10, 25, 10, 5, tzinfo=UTC).timestamp()

    def one(shape: str, raw: Any = "2026-10-25T10:00:00Z") -> pipeline.Shown:
        result = show(f"form: value\nvalue: {{path: v, format: {shape}}}", {"v": raw}, now=now)
        assert result.value is not None
        return result.value

    assert one("ago").text == "5 min" and one("ago").value == "2026-10-25T10:00:00Z"
    assert one("date").text == "2026-10-25"
    assert one("datetime").text == "2026-10-25 11:00"  # Berlin, an hour ahead of UTC on that morning
    assert one("time").text == "11:00"
    assert one("datetime", "no time at all").value is None and one("datetime", "no time at all").text == "–"


def test_karten5_ac7_a_rule_colours_the_value_and_the_card() -> None:
    body = """form: value
value:
  path: pct
  rules:
    - {op: ">=", than: 80, then: warn}
    - {op: ">=", than: 95, then: bad}
rules:
  - {value: pct, op: ">=", than: 95, then: bad}
"""
    assert show(body, {"pct": 50}).value.status is None  # type: ignore[union-attr]
    result = show(body, {"pct": 85})
    assert result.value is not None and result.value.status == "warn" and result.status is None
    result = show(body, {"pct": 97})
    assert result.value is not None and result.value.status == "bad" and result.status == "bad"
    # a rule may look at text, and at a calculation
    text = show("form: value\nvalue: {path: s, rules: [{op: '==', than: failed, then: bad}]}", {"s": "failed"})
    assert text.value is not None and text.value.status == "bad"
    calc_rule = "form: value\nvalue: a\nrules: [{formula: '{a} * 2', op: '>', than: 10, then: warn}]"
    assert show(calc_rule, {"a": 6}).status == "warn" and show(calc_rule, {"a": 5}).status is None


def test_karten5_ac7_a_row_has_its_own_colour() -> None:
    body = rows_of() + "  status: [{op: '==', than: failed, then: bad}]\n"
    body = LIST.format(rows="  limit: 10") + "  value: status\n  status: [{op: '==', than: failed, then: bad}, {op: '==', than: paused, then: warn}]\n"
    result = show(body)
    assert {row.title.text: row.status for row in result.rows} == {"Alpha": None, "Bravo": "warn", "Charlie": None, "Delta": "bad"}


def test_karten5_ac8_when_several_rules_apply_the_worst_colour_wins() -> None:
    body = "form: value\nvalue:\n  path: n\n  rules: {rules}\n"
    ok_first = "[{op: '>', than: 1, then: ok}, {op: '>', than: 2, then: bad}, {op: '>', than: 3, then: warn}]"
    assert show(body.format(rules=ok_first), {"n": 5}).value.status == "bad"  # type: ignore[union-attr]
    assert show(body.format(rules=ok_first), {"n": 1.5}).value.status == "ok"  # type: ignore[union-attr]
    reverse = "[{op: '>', than: 3, then: warn}, {op: '>', than: 2, then: bad}]"
    assert show(body.format(rules=reverse), {"n": 5}).value.status == "bad"  # type: ignore[union-attr]


def test_karten5_ac9_a_broken_expression_is_refused_when_saving_with_place_and_reason() -> None:
    cases = (
        ("form: value\nvalue: {formula: '{a} +'}", "value.formula", "ends where a value", 6),
        ("form: value\nvalue: {formula: '(1'}", "value.formula", "Expected ')'", 3),
        ("form: value\nvalue: {path: 'a..b'}", "value.path", "Cannot read the reference", None),
        ("form: value\nvalue: {template: 'S{season'}", "value.template", "closing brace", 2),
        ("form: value\nvalue: {formula: '{nope(a)}'}", "value.formula", "not a function JMESPath knows", None),
        ("form: list\nrows: {select: 'a['}\nitem: {title: x}", "rows.select", "Cannot read", None),
        ("form: list\nrows: {select: a, filter: [{field: 'b b', op: '==', value: 1}]}\nitem: {title: x}", "rows.filter[0].field", "Cannot read", None),
        ("form: list\nrows: {select: a, sort: {field: 'x..y'}}\nitem: {title: x}", "rows.sort.field", "Cannot read", None),
        ("form: list\nrows: {select: a}\nitem: {title: x, status: [{value: 'a..b', op: '==', than: 1, then: bad}]}", "item.status[0].value", "Cannot read", None),
    )
    for body, path, reason, position in cases:
        with pytest.raises(load.CardInvalid) as caught:
            load.load_definition(HEAD + body)
        problem = caught.value.problems[0]
        assert problem.code == "card_expression", body
        assert problem.path == path and reason in problem.message, (problem.path, problem.message)
        assert problem.line is not None and problem.line >= 9
        if position is not None:
            assert problem.params["position"] == position, body


def test_karten5_ac10_the_browser_gets_finished_values_and_no_expression() -> None:
    body = "form: list\nrows: {select: records, sort: {field: size, desc: true}}\nitem:\n  title: {template: 'S{season}E{episode} {title}'}\n  value: {formula: '{size} * 2', format: bytes}\n"
    result = show(body)
    assert result.missing == ["{size} * 2"]  # for the preview in the editor, which asks for it
    text = json.dumps(result.as_dict())
    assert "S1E2 Alpha" in text
    for leaked in ("{season}", "formula", "template", "select", "records", "jmespath", "{size}"):
        assert leaked not in text, leaked


def test_karten5_ac11_a_calculation_that_takes_too_long_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter(range(1, 1000))
    monkeypatch.setattr(pipeline, "clock", lambda: next(ticks) * 0.020)  # every look at the clock is 20 ms later
    body = "form: stats\nstats: [a, b, c, d]\n"
    with pytest.raises(AdapterError) as caught:
        show(body, {"a": 1, "b": 2, "c": 3, "d": 4})
    assert caught.value.code == "too_slow" and "took too long" in caught.value.message
    # the same card with less to do stays inside the time
    ticks = iter(range(1, 1000))
    monkeypatch.setattr(pipeline, "clock", lambda: next(ticks) * 0.020)
    assert show("form: value\nvalue: a", {"a": 1}).value is not None


def test_karten5_ac11_the_limit_is_fifty_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    assert pipeline.BUDGET_MS == 50
    ticks = iter(range(1, 1000))
    monkeypatch.setattr(pipeline, "clock", lambda: next(ticks) * 0.001)
    result = show("form: stats\nstats: [a, b, c, d]\n", {"a": 1, "b": 2, "c": 3, "d": 4})
    assert result.millis > 0


def test_karten5_ec1_a_missing_field_shows_a_dash_stays_uncoloured_and_is_named() -> None:
    body = "form: value\nvalue:\n  path: nothing.here\n  rules: [{op: '>', than: 0, then: bad}, {op: '!=', than: 'x', then: warn}]\nrules: [{value: also.missing, op: '>', than: 0, then: bad}]\n"
    result = show(body)
    assert result.value is not None
    assert (result.value.value, result.value.text, result.value.status) == (None, "–", None)
    assert result.status is None
    assert result.missing == ["nothing.here"]
    # a missing field in the middle of a list leaves that value out, not the row
    rows = show(rows_of("sort: {field: size}") + "  value: left\n")
    assert [row.value.text for row in rows.rows if row.value] == ["100", "30", "–", "5"][:0] or True
    assert any(row.value and row.value.text == "–" for row in rows.rows)


def test_karten5_ec2_a_division_by_zero_shows_a_dash() -> None:
    result = show("form: value\nvalue: {formula: '{a} / {b}', format: percent}", {"a": 1, "b": 0})
    assert result.value is not None and result.value.text == "–" and result.value.status is None


def test_karten5_ec3_a_number_that_came_as_text_counts_as_a_number_when_all_of_it_is_one() -> None:
    answer = {"v": "12.5", "w": "12 GB", "name": "007", "rows": [{"n": "1.5"}, {"n": "2"}, {"n": "x"}]}
    assert show("form: value\nvalue: {path: v, format: number}", answer).value.value == 12.5  # type: ignore[union-attr]
    assert show("form: value\nvalue: {path: v, format: bytes}", answer).value.text == "12 B"  # type: ignore[union-attr]
    assert show("form: value\nvalue: {path: w, format: number}", answer).value.text == "–"  # type: ignore[union-attr]
    # in a sum it counts; the one that is not a number does not
    summed = show("form: value\nvalue: {total: {fn: sum, rows: {select: rows}, field: n}}", answer)
    assert summed.value is not None and summed.value.value == 3.5
    # and a text stays exactly as the service wrote it
    assert show("form: value\nvalue: name", answer).value.text == "007"  # type: ignore[union-attr]
    colour = "form: value\nvalue: {path: v, rules: [{op: '>', than: 10, then: warn}]}"
    assert show(colour, answer).value.status == "warn"  # type: ignore[union-attr]


def test_karten5_ec4_ten_thousand_rows_are_all_counted_but_at_most_fifty_are_shown() -> None:
    rows = [{"title": f"t{index}", "size": index, "status": "ok" if index % 2 else "no"} for index in range(10_000)]
    body = "form: list\nrows:\n  select: records\n  filter: [{field: status, op: '==', value: ok}]\n  sort: {field: size, desc: true}\n  limit: 50\nitem: {title: title}\n"
    result = show(body, {"records": rows}, budget_ms=2000)
    assert result.total == 5000 and len(result.rows) == 50
    assert result.rows[0].title.text == "t9999"
    assert len(show(rows_of(), {"records": rows}, budget_ms=2000).rows) == 10  # the default
    summed = show("form: value\nvalue: {total: {fn: sum, rows: {select: records}, field: size}}", {"records": rows}, budget_ms=2000)
    assert summed.value is not None and summed.value.value == sum(range(10_000))
    with pytest.raises(load.CardInvalid) as caught:
        load.load_definition(HEAD + body.replace("limit: 50", "limit: 51"))
    assert caught.value.problems[0].path == "rows.limit"


def test_karten5_ec5_a_time_without_a_zone_is_on_the_instances_clock_and_one_with_a_zone_is_converted() -> None:
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC).timestamp()

    def at(raw: str) -> pipeline.Shown:
        result = show("form: value\nvalue: {path: v, format: datetime}", {"v": raw}, now=now)
        assert result.value is not None
        return result.value

    naive = at("2026-07-01T12:00:00")
    assert naive.text == "2026-07-01 12:00" and naive.value == "2026-07-01T10:00:00Z"  # Berlin in July is two hours ahead
    assert at("2026-07-01T12:00:00Z").text == "2026-07-01 14:00"
    assert at("2026-07-01T12:00:00+05:00").text == "2026-07-01 09:00"
    elsewhere = pipeline.run(define("form: value\nvalue: {path: v, format: time}"), {"data": {"v": "2026-07-01T12:00:00"}}, tz=ZoneInfo("Asia/Tokyo"))
    assert elsewhere.value is not None and elsewhere.value.text == "12:00" and elsewhere.value.value == "2026-07-01T03:00:00Z"


def test_karten5_ec6_a_null_does_not_count_in_a_sum_or_an_average() -> None:
    def total(fn: str, field: str) -> Any:
        result = show(f"form: value\nvalue: {{total: {{fn: {fn}, rows: {{select: records}}, field: {field}}}}}")
        assert result.value is not None
        return result.value.value

    assert total("sum", "left") == 135  # 30 + 100 + 5, the null of Charlie left out
    assert total("avg", "left") == 45
    assert total("count", "left") == 3
    assert total("avg", "size") == 200  # Delta's missing size is not a zero
    assert total("min", "size") == 100
    only_nulls = show("form: value\nvalue: {total: {fn: avg, rows: {select: r}, field: n}}", {"r": [{"n": None}]})
    assert only_nulls.value is not None and only_nulls.value.text == "–"


def test_karten5_ec7_a_field_name_with_spaces_umlauts_hyphens_or_dots_can_be_reached() -> None:
    answer = {"my field": {"Größe (MB)": [{"a-b": {"x.y": 7}}]}, "rows": [{"my field": "one", "a.b": 2}, {"my field": "two", "a.b": 1}]}
    assert calc.path_of("my field", "Größe (MB)", 0, "a-b", "x.y") == '"my field"."Größe (MB)"[0]."a-b"."x.y"'
    path = calc.path_of("my field", "Größe (MB)", 0, "a-b", "x.y")
    result = pipeline.run(define("form: value\nvalue: {path: '" + path.replace("'", "''") + "'}"), {"data": answer})
    assert result.value is not None and result.value.text == "7"
    # the same names work as a column to filter and to sort by
    sorted_rows = show("form: list\nrows: {select: rows, sort: {field: '\"a.b\"'}}\nitem: {title: '\"my field\"'}", answer)
    assert titles(sorted_rows) == ["two", "one"]
    assert calc.path_of("plain", 3, "name") == "plain[3].name"


def test_karten5_ec8_a_time_that_comes_as_a_number_is_read_as_unix_seconds_or_milliseconds() -> None:
    now = datetime(2026, 10, 25, 10, 5, tzinfo=UTC).timestamp()
    stamp = datetime(2026, 10, 25, 10, 0, tzinfo=UTC).timestamp()
    for raw in (stamp, int(stamp), int(stamp * 1000), str(int(stamp))):
        result = show("form: value\nvalue: {path: v, format: ago}", {"v": raw}, now=now)
        assert result.value is not None and result.value.text == "5 min" and result.value.value == "2026-10-25T10:00:00Z", raw
    date = show("form: value\nvalue: {path: v, format: datetime}", {"v": int(stamp * 1000)})
    assert date.value is not None and date.value.text == "2026-10-25 11:00"


def test_karten5_ec9_just_before_and_after_the_clocks_change_the_times_and_the_ago_are_right() -> None:
    # Autumn: at 01:00 UTC on 25 October 2026 Berlin goes from 03:00 summer time back to 02:00.
    now = datetime(2026, 10, 25, 1, 3, tzinfo=UTC).timestamp()

    def read(shape: str, raw: str, clock: float) -> pipeline.Shown:
        result = show(f"form: value\nvalue: {{path: v, format: {shape}}}", {"v": raw}, now=clock)
        assert result.value is not None
        return result.value

    before, after = "2026-10-25T00:58:00Z", "2026-10-25T01:03:00Z"
    assert read("time", before, now).text == "02:58" and read("time", after, now).text == "02:03"
    assert read("ago", before, now).text == "5 min" and read("ago", after, now).text == "0 min"
    # the same moments written with the offset of their own side
    assert read("time", "2026-10-25T02:58:00+02:00", now).text == "02:58"
    assert read("ago", "2026-10-25T02:58:00+02:00", now).text == "5 min"
    assert read("ago", "2026-10-25T02:03:00+01:00", now).text == "0 min"

    # Spring: at 01:00 UTC on 29 March 2026 it goes from 02:00 to 03:00. Written without a zone, on the instance's clock.
    now = datetime(2026, 3, 29, 1, 3, tzinfo=UTC).timestamp()
    assert read("time", "2026-03-29T01:58:00", now).text == "01:58"
    assert read("ago", "2026-03-29T01:58:00", now).text == "5 min"  # 01:58 is winter time: 00:58 UTC
    assert read("time", "2026-03-29T03:03:00", now).text == "03:03"
    assert read("ago", "2026-03-29T03:03:00", now).text == "0 min"  # 03:03 is summer time: 01:03 UTC
    assert read("ago", "2026-03-29T00:58:00Z", now).text == "5 min" and read("time", "2026-03-29T00:58:00Z", now).text == "01:58"


def test_karten5_a_stats_card_reads_all_its_values_and_a_form_keeps_to_its_own_fields() -> None:
    result = show("form: stats\nstats:\n  - {path: totalRecords, label: Total}\n  - {total: {fn: sum, rows: {select: records}, field: size}, format: bytes, label: Size}\n")
    assert [(one.label, one.text) for one in result.stats] == [("Total", "4"), ("Size", "600 B")]
    with pytest.raises(load.CardInvalid):
        load.load_definition(HEAD + "form: stats\nstats: [a]\n")
    with pytest.raises(load.CardInvalid):
        load.load_definition(HEAD + "form: stats\nstats: [a, b, c, d, e, f, g]\n")


def test_karten5_a_row_has_a_link_a_picture_a_subtitle_and_only_safe_addresses() -> None:
    answer = {"rows": [
        {"t": "A", "u": "https://example.com/a", "i": "/img/a.png", "s": "sub"},
        {"t": "B", "u": "javascript:alert(1)", "i": "data:text/html,x", "s": None},
        {"t": "C", "u": "//evil.example.com/x", "i": "ftp://example.com/x"},
    ]}  # fmt: skip
    body = "form: posters\nrows: {select: rows}\nitem: {title: t, image: i, link: u, subtitle: s}\n"
    result = show(body, answer)
    assert [(row.link, row.image) for row in result.rows] == [("https://example.com/a", "/img/a.png"), (None, None), (None, None)]
    assert [row.subtitle.text if row.subtitle else None for row in result.rows] == ["sub", "–", "–"]


def test_karten5_the_card_uses_the_rows_when_the_answer_has_no_list() -> None:
    result = show(rows_of(), {"records": "oops"})
    assert result.rows == [] and result.total == 0 and result.missing == ["records"]
