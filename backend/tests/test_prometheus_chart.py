"""Prometheus: several queries as curves on one chart, from /api/v1/query_range (issue #81).

The answers are in the shape Prometheus' HTTP API documents for ``query_range``: ``resultType`` ``matrix``, each
series with its ``metric`` labels and ``values`` as ``[seconds, "number"]``; a failure as ``status: error`` with
``errorType`` and ``error``, on HTTP 400 for a query that does not parse and 422 for one that fails while it runs.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter, prometheus
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.prometheus import parse_queries, split_line, stretch

URL = "http://prometheus.example.com:9090"
CONFIG = {"url": URL}
#: 2027-01-15 08:00:07 UTC; with the 6 hour stretch the step is 90 seconds and the end 08:00:00.
NOW = 1_800_000_007
END = 1_800_000_000
CPU = '100 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100'
MEMORY = "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)"


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prometheus, "clock", lambda: NOW)


def matrix(*series: tuple[dict[str, str], list[tuple[int, str]]]) -> dict[str, Any]:
    return {"status": "success", "data": {"resultType": "matrix", "result": [
        {"metric": metric, "values": [[at, value] for at, value in values]} for metric, values in series
    ]}}


def failure(kind: str, message: str) -> dict[str, Any]:
    return {"status": "error", "errorType": kind, "error": message}


def steps(*values: str, step: int = 90) -> list[tuple[int, str]]:
    """Samples ending at :data:`END`, one step apart."""
    return [(END - (len(values) - 1 - index) * step, value) for index, value in enumerate(values)]


def answering(answers: dict[str, httpx.Response]) -> respx.Route:
    """One route for query_range that answers each query with its own response."""
    def answer(request: httpx.Request) -> httpx.Response:
        return answers[request.url.params["query"]]
    return respx.get(f"{URL}/api/v1/query_range").mock(side_effect=answer)


async def chart(ctx: Context, queries: str, **options: Any) -> Any:
    return await get_adapter("prometheus").fetch("chart", CONFIG, {"queries": queries, "decimals": 1, **options}, ctx)


@respx.mock
async def test_two_queries_are_two_curves_with_their_colour_unit_and_the_first_as_the_big_number(ctx: Context) -> None:
    route = answering({
        CPU: httpx.Response(200, json=matrix(({}, steps("40.5", "41.25", "42.04")))),
        MEMORY: httpx.Response(200, json=matrix(({"instance": "node1:9100"}, steps("63", "64", "65")))),
    })
    data = await chart(ctx, f"CPU | {CPU} | violet | %\nMemory | {MEMORY} | #12ab9F | %", warn_above=40, bad_above=90)

    assert data.primary == {"label": "CPU", "value": 42.0, "unit": "%"}
    assert data.status == "warn"
    lines = data.meta["lines"]
    assert [(line["label"], line.get("colour"), line["unit"]) for line in lines] == [("CPU", "violet", "%"), ("Memory", "#12ab9F", "%")]
    assert lines[0]["points"] == [[END - 180, 40.5], [END - 90, 41.25], [END, 42.04]]
    assert data.meta["marks"] == [{"value": 40.0, "status": "warn"}, {"value": 90.0, "status": "bad"}]
    assert "failed" not in data.meta
    # The real history: one question per query, over six hours ending at a whole step.
    asked = [dict(call.request.url.params) for call in route.calls]
    assert asked == [
        {"query": CPU, "start": str(END - 21600), "end": str(END), "step": "90"},
        {"query": MEMORY, "start": str(END - 21600), "end": str(END), "step": "90"},
    ]


@respx.mock
async def test_the_stretch_sets_the_step_so_the_points_stay_few(ctx: Context) -> None:
    route = answering({"up": httpx.Response(200, json=matrix(({}, steps("1", step=15))))})
    await chart(ctx, "up", range="30m")
    await chart(ctx, "up", range="24h")
    await chart(ctx, "up", range="a week")
    params = [call.request.url.params for call in route.calls]
    assert [(int(one["end"]) - int(one["start"]), one["step"]) for one in params] == [(1800, "15"), (86400, "360"), (21600, "90")]
    assert stretch({"range": "30m"}, NOW) == (END - 1800, END, 15)
    # Each end a whole number of steps.
    assert all(int(one["end"]) % int(one["step"]) == 0 for one in params)


@respx.mock
async def test_a_regular_expression_with_alternatives_reaches_prometheus_whole(ctx: Context) -> None:
    query = 'sum(rate(node_cpu_seconds_total{mode=~"user|system"}[5m]))'
    route = answering({query: httpx.Response(200, json=matrix(({}, steps("2", "3"))))})
    data = await chart(ctx, f"Busy | {query} | green")
    assert route.calls.last.request.url.params["query"] == query
    assert data.meta["lines"][0]["colour"] == "green"
    assert split_line("a | b{x='p|q'} | c") == ["a", "b{x='p|q'}", "c"]
    assert split_line('a | b{x="p\\"|q"} | c') == ["a", 'b{x="p\\"|q"}', "c"]


@respx.mock
async def test_a_query_with_several_series_draws_one_curve_each_named_by_the_labels_that_differ(ctx: Context) -> None:
    query = "rate(node_network_receive_bytes_total[5m])"
    answering({query: httpx.Response(200, json=matrix(
        ({"__name__": "x", "device": "eth0", "instance": "node1:9100", "job": "node"}, steps("1", "2")),
        ({"__name__": "x", "device": "eth1", "instance": "node1:9100", "job": "node"}, steps("3", "4")),
    ))})
    data = await chart(ctx, f"In | {query} | orange | B/s")
    assert [(line["label"], line.get("colour"), line["unit"]) for line in data.meta["lines"]] == [("In eth0", "orange", "B/s"), ("In eth1", None, "B/s")]
    # Without a label the differing values alone name them.
    data = await chart(ctx, query)
    assert [line["label"] for line in data.meta["lines"]] == ["eth0", "eth1"]


@respx.mock
async def test_six_curves_at_most_on_one_card(ctx: Context) -> None:
    many = matrix(*(({"instance": f"node{index}"}, steps("1", "2")) for index in range(5)))
    answering({"a": httpx.Response(200, json=many), "b": httpx.Response(200, json=many)})
    data = await chart(ctx, "a\nb")
    assert [line["label"] for line in data.meta["lines"]] == ["node0", "node1", "node2", "node3", "node4", "node0"]
    assert len(parse_queries("\n".join(f"Q{index} | up" for index in range(9)))) == 6


@respx.mock
async def test_a_failing_query_is_named_with_prometheus_reason_and_the_others_still_draw(ctx: Context) -> None:
    answering({
        CPU: httpx.Response(200, json=matrix(({}, steps("10", "11")))),
        "rate(up[": httpx.Response(400, json=failure("bad_data", '1:9: parse error: unexpected end of input inside braces')),
        "absent_metric": httpx.Response(200, json=matrix()),
    })
    data = await chart(ctx, f"CPU | {CPU}\nBroken | rate(up[\nGone | absent_metric")
    assert [line["label"] for line in data.meta["lines"]] == ["CPU"]
    assert data.meta["failed"] == [
        {"label": "Broken", "error": "1:9: parse error: unexpected end of input inside braces"},
        {"label": "Gone", "error": "The query returned no series."},
    ]
    # Yellow, not red: what is there is right, something is missing.
    assert data.status == "warn"


@respx.mock
async def test_when_every_query_fails_the_card_says_what_prometheus_said(ctx: Context) -> None:
    answering({"slow": httpx.Response(422, json=failure("execution", "query processing would load too many samples into memory"))})
    with pytest.raises(AdapterError) as caught:
        await chart(ctx, "slow")
    assert (caught.value.code, caught.value.message) == ("query_error", "query processing would load too many samples into memory")


@respx.mock
async def test_when_no_query_finds_a_series_the_card_says_so(ctx: Context) -> None:
    answering({"nothing": httpx.Response(200, json=matrix()), "only_nan": httpx.Response(200, json=matrix(({}, steps("NaN", "NaN"))))})
    with pytest.raises(AdapterError) as caught:
        await chart(ctx, "nothing\nonly_nan")
    assert caught.value.code == "empty_result"


@respx.mock
async def test_nan_infinity_and_missing_steps_are_gaps_and_the_big_number_is_the_last_real_one(ctx: Context) -> None:
    values = [(END - 540, "5"), (END - 450, "NaN"), (END - 360, "6"),
              # Nothing at END - 270 and END - 180: the target was down.
              (END - 90, "+Inf"), (END, "-Inf")]
    answering({"temp": httpx.Response(200, json=matrix(({}, values)))})
    data = await chart(ctx, "Temp | temp | | °C", decimals=0)
    assert data.meta["lines"][0]["points"] == [
        [END - 540, 5.0], [END - 450, None], [END - 360, 6.0], [END - 270, None], [END - 90, None], [END, None],
    ]
    assert data.primary == {"label": "Temp", "value": 6, "unit": "°C"}
    # The answer is JSON a browser can read: no NaN anywhere in it.
    assert "NaN" not in data.model_dump_json() and "Infinity" not in data.model_dump_json()


@respx.mock
async def test_an_unreachable_server_or_a_refused_password_fails_the_whole_card(ctx: Context) -> None:
    respx.get(f"{URL}/api/v1/query_range").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await chart(ctx, "up\ndown")
    # Not named under the chart as one query that failed, even when another query got through before it.
    answering({"up": httpx.Response(200, json=matrix(({}, steps("1", "1")))), "down": httpx.Response(401, text="Unauthorized")})
    with pytest.raises(AuthFailed):
        await chart(ctx, "up\ndown")


@respx.mock
async def test_an_answer_that_is_no_prometheus_answer_is_refused(ctx: Context) -> None:
    respx.get(f"{URL}/api/v1/query_range").mock(return_value=httpx.Response(502, text="<html>Bad gateway</html>"))
    with pytest.raises(AdapterError) as caught:
        await chart(ctx, "up")
    assert caught.value.code == "http_error"
    respx.get(f"{URL}/api/v1/query_range").mock(return_value=httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}}))
    with pytest.raises(AdapterError) as caught:
        await chart(ctx, "up")
    assert caught.value.code == "not_a_series"


async def test_no_query_is_no_card(ctx: Context) -> None:
    with pytest.raises(AdapterError) as caught:
        await chart(ctx, "  \n | \n")
    assert caught.value.code == "missing_query"


def test_the_lines_of_the_setting_are_read_leniently() -> None:
    assert parse_queries("up\n\nLoad | node_load1 | turquoise | \nDisk | x | #00FF00 | GB\n") == [
        {"label": "", "query": "up", "colour": "", "unit": ""},
        # A colour that is not one of the list is dropped, the curve stays.
        {"label": "Load", "query": "node_load1", "colour": "", "unit": ""},
        {"label": "Disk", "query": "x", "colour": "#00FF00", "unit": "GB"},
    ]
    # A colour can never carry anything into a style.
    assert parse_queries("A | up | red;background:url(x)")[0]["colour"] == ""


@respx.mock
async def test_the_value_card_is_unchanged_and_refuses_nan(ctx: Context) -> None:
    respx.get(f"{URL}/api/v1/query").mock(side_effect=[
        httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [NOW, "42.04"]}]}}),
        httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [NOW, "NaN"]}]}}),
    ])
    options = {"query": "up", "label": "CPU", "unit": "%", "decimals": 1, "warn_above": 40}
    data = await get_adapter("prometheus").fetch("query", CONFIG, options, ctx)
    assert (data.status, data.primary, data.metrics) == ("warn", {"label": "CPU", "value": 42.0, "unit": "%"}, {"value": 42.04})
    with pytest.raises(AdapterError) as caught:
        await get_adapter("prometheus").fetch("query", CONFIG, {**options, "query": "0/0"}, ctx)
    assert caught.value.code == "not_a_number"


def test_the_demo_draws_three_curves_with_the_thresholds() -> None:
    data = get_adapter("prometheus").demo("chart", {"range": "30m", "bad_above": 45}, 3)
    assert [line["label"] for line in data.meta["lines"]] == ["CPU", "Memory", "Load"]
    assert len(data.meta["lines"][0]["points"]) == 120
    assert data.meta["marks"] == [{"value": 45.0, "status": "bad"}]
    assert data.primary["label"] == "CPU"
