"""UptimeRobot, against an answer written after the documentation of API v2 (27.10.2026). Never measured against an account."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.uptimerobot import API, UptimeRobotAdapter

CONFIG = {"api_key": "u1234567-made-up-key"}


def monitor(identifier: int, name: str, status: int, kind: int = 1, url: str = "https://www.example.com/", ratio: str = "99.98") -> dict:
    return {"id": identifier, "friendly_name": name, "url": url, "type": kind, "sub_type": "", "keyword_type": None, "keyword_value": "",
            "interval": 300, "status": status, "create_datetime": 1789000000, "custom_uptime_ratio": ratio,
            "response_times": [{"datetime": 1789171000, "value": 212}]}


MONITORS = [
    monitor(1, "Main site", 2),
    monitor(2, "Blog", 9, url="https://blog.example.com/", ratio="97.1"),
    monitor(3, "Mail", 2, kind=4, url="mail.example.com", ratio="100"),
    monitor(4, "Flaky", 8, ratio="99.5"),
    monitor(5, "Staging", 0, url="https://staging.example.com"),
    monitor(6, "New one", 1),
]


def answer(monitors: list[dict], total: int | None = None) -> dict:
    return {"stat": "ok", "pagination": {"offset": 0, "limit": 50, "total": len(monitors) if total is None else total}, "monitors": monitors}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_list_down_first_with_type_host_and_uptime(ctx: Context) -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, json=answer(MONITORS)))
    data = await get_adapter("uptimerobot").fetch("monitors", CONFIG, {}, ctx)
    assert [(row["title"], row["status"], row["value"]) for row in data.items] == [
        ("Blog", "bad", "down"), ("Flaky", "warn", "down"), ("New one", "unknown", ""), ("Staging", "unknown", ""),
        ("Mail", "ok", "100%"), ("Main site", "ok", "99.98%")]
    rows = {row["title"]: row for row in data.items}
    assert rows["Blog"]["subtitle"] == "HTTP · blog.example.com"
    assert rows["Staging"]["subtitle"] == "HTTP · staging.example.com · Paused" and rows["New one"]["subtitle"].endswith("Not checked yet")
    assert rows["Mail"]["subtitle"] == "Port"
    assert data.status == "bad" and data.metrics == {"down": 2.0} and data.secondary == [{"label": "Up", "value": 2}, {"label": "Down", "value": 2}]
    # The key travels in the body of a POST, never in the address.
    sent = route.calls.last.request
    assert parse_qs(sent.content.decode())["api_key"] == [CONFIG["api_key"]] and "api_key" not in str(sent.url)
    assert parse_qs(sent.content.decode())["custom_uptime_ratios"] == ["30"]


@respx.mock
async def test_the_summary_counts_up_and_names_who_is_down(ctx: Context) -> None:
    respx.post(API).mock(return_value=httpx.Response(200, json=answer(MONITORS)))
    data = await get_adapter("uptimerobot").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Monitors up", "value": 2, "unit": "/ 5"} and data.status == "bad"
    assert data.secondary == [{"label": "Down", "value": 2}, {"label": "Paused", "value": 1}]
    assert data.meta["status_reason"] == "Down: Blog, Flaky" and data.meta["ring"] == [{"label": "Up", "value": 2.0}, {"label": "Down", "value": 2.0}]
    assert data.metrics == {"down": 2.0}


def test_a_monitor_that_only_seems_down_is_yellow_not_red() -> None:
    data = UptimeRobotAdapter._card("summary", [monitor(1, "A", 2), monitor(2, "B", 8)], {})
    assert data.status == "warn"
    assert UptimeRobotAdapter._card("summary", [monitor(1, "A", 2)], {}).status == "ok"
    assert UptimeRobotAdapter._card("summary", [], {}).status == "unknown"


def test_the_name_filter_decides_what_is_counted_and_coloured() -> None:
    data = UptimeRobotAdapter._card("summary", MONITORS, {"filter": "main"})
    assert data.status == "ok" and data.primary["unit"] == "/ 1" and data.metrics == {"down": 0.0}
    listed = UptimeRobotAdapter._card("monitors", MONITORS, {"filter": "MAIL"})
    assert [row["title"] for row in listed.items] == ["Mail"]
    assert len(UptimeRobotAdapter._card("monitors", MONITORS, {"limit": 2}).items) == 2


@respx.mock
async def test_more_than_one_page_is_read_until_the_total(ctx: Context) -> None:
    first = [monitor(number, f"Site {number}", 2) for number in range(50)]
    second = [monitor(100 + number, f"Other {number}", 2) for number in range(7)]
    route = respx.post(API).mock(side_effect=[httpx.Response(200, json=answer(first, total=57)), httpx.Response(200, json=answer(second, total=57))])
    assert await get_adapter("uptimerobot").test(CONFIG, ctx) == "UptimeRobot answers with 57 monitors."
    assert route.call_count == 2
    assert parse_qs(route.calls[1].request.content.decode())["offset"] == ["50"]


@respx.mock
async def test_a_rejected_key_is_a_refusal_with_status_200(ctx: Context) -> None:
    respx.post(API).mock(return_value=httpx.Response(200, json={"stat": "fail", "error": {
        "type": "invalid_parameter", "parameter_name": "api_key", "passed_value": "u1234567-made-up-key", "message": "api_key is invalid."}}))
    with pytest.raises(AuthFailed):
        await get_adapter("uptimerobot").fetch("monitors", CONFIG, {}, ctx)


@respx.mock
async def test_other_refusals_and_failures(ctx: Context) -> None:
    adapter = get_adapter("uptimerobot")
    respx.post(API).mock(return_value=httpx.Response(200, json={"stat": "fail", "error": {"type": "not_authorized", "message": "You are not\nauthorized."}}))
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("monitors", CONFIG, {}, ctx)
    assert refused.value.code == "refused" and refused.value.message == "UptimeRobot refused: You are not authorized."
    respx.post(API).mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(AdapterError) as slow:
        await adapter.fetch("monitors", CONFIG, {}, ctx)
    assert slow.value.code == "rate_limited" and "ten requests" in slow.value.hint
    respx.post(API).mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as html:
        await adapter.fetch("monitors", CONFIG, {}, ctx)
    assert html.value.code == "not_json"
    respx.post(API).mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(Unreachable):
        await adapter.fetch("monitors", CONFIG, {}, ctx)


def test_the_key_is_a_secret_and_the_cards_have_demo_data_that_moves() -> None:
    adapter = get_adapter("uptimerobot")
    assert {field.name for field in adapter.fields if field.secret} == {"api_key"} and adapter.beta is True
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options}
        assert adapter.demo(widget.kind, options, 0).error is None
    assert {adapter.demo("summary", {}, tick).status for tick in range(0, 900, 15)} >= {"ok", "bad"}
