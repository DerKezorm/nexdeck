"""llama.cpp server, against the answers of a live llama-server b11913 with a 135M model (27.10.2026)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.llamacpp import LlamaCppAdapter, _numbers

FIXTURES = Path(__file__).parent / "fixtures"
L = "http://llama.example.com:8080"
CONFIG = {"url": L, "api_key": "made-up-key"}


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


PROPS = fixture("llamacpp_props.json")
IDLE = fixture("llamacpp_slots_idle.json")
BUSY = fixture("llamacpp_slots_busy.json")
METRICS = (FIXTURES / "llamacpp_metrics.txt").read_text(encoding="utf-8")


def fresh(number: int = 1) -> Context:
    return Context(httpx.AsyncClient(), integration_id=number, widget_id=1, cache={})


def serve(slots: Any = IDLE, metrics: str = METRICS) -> respx.Route:
    props = respx.get(f"{L}/props").mock(return_value=httpx.Response(200, json=PROPS))
    respx.get(f"{L}/slots").mock(return_value=httpx.Response(200, json=slots))
    respx.get(f"{L}/metrics").mock(return_value=httpx.Response(200, text=metrics))
    return props


@respx.mock
async def test_the_server_card_names_model_slots_and_speed() -> None:
    route = serve()
    data = await get_adapter("llamacpp").fetch("server", CONFIG, {}, fresh())
    assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-key"
    assert data.primary == {"label": "Model", "value": "SmolLM2-135M-Instruct-GGUF:Q4_K_M", "unit": ""} and data.status == "ok"
    # 2092 tokens in 8.86596 seconds is the average since the start: the first look has nothing to subtract.
    assert data.secondary == [{"label": "Slots busy", "value": "0 / 2"}, {"label": "Tokens a second", "value": 236.0},
                              {"label": "Context per slot", "value": 1024}, {"label": "Quantisation", "value": "Q4_K - Medium"}]
    assert data.metrics == {"busy": 0.0, "tokens_per_second": 236.0}


@respx.mock
async def test_the_speed_is_what_was_made_since_the_last_look_and_is_kept_while_nothing_is_made() -> None:
    adapter, context = get_adapter("llamacpp"), fresh()
    serve()
    await adapter.fetch("server", CONFIG, {}, context)
    # 500 tokens in 5 seconds more: 100 a second, not the average of 236.
    later = METRICS.replace("tokens_predicted_total 2092", "tokens_predicted_total 2592").replace("tokens_predicted_seconds_total 8.86596", "tokens_predicted_seconds_total 13.86596")
    serve(metrics=later)
    context.forget_answers()
    assert (await adapter.fetch("server", CONFIG, {}, context)).metrics["tokens_per_second"] == 100.0
    # Nothing made since: the speed it had, not a zero that reads as a stopped server.
    context.forget_answers()
    assert (await adapter.fetch("server", CONFIG, {}, context)).metrics["tokens_per_second"] == 100.0


@respx.mock
async def test_every_slot_busy_is_yellow_one_busy_is_not() -> None:
    """⚠️ Measured: slot 1 was working on a long answer, slot 0 idle."""
    serve(slots=BUSY)
    data = await get_adapter("llamacpp").fetch("server", CONFIG, {}, fresh())
    assert data.status == "ok" and data.secondary[0] == {"label": "Slots busy", "value": "1 / 2"} and data.metrics["busy"] == 1.0
    both = [{**one, "is_processing": True} for one in IDLE]
    serve(slots=both)
    assert (await get_adapter("llamacpp").fetch("server", CONFIG, {}, fresh(2))).status == "warn"


def test_the_slots_card_with_and_without_the_progress_of_an_answer() -> None:
    working = {**BUSY[1], "next_token": [{"has_next_token": True, "n_remain": 969, "n_decoded": 531}]}
    data = LlamaCppAdapter._slots([BUSY[0], working])
    assert [(row["title"], row["subtitle"], row["status"]) for row in data.items] == [("Slot 0", "Idle", "unknown"), ("Slot 1", "Working · 531 tokens made", "ok")]
    assert data.secondary == [{"label": "Slots busy", "value": "1 / 2"}] and data.metrics == {"busy": 1.0}
    # Measured without a key: the busy slot carried next_token, and 510 tokens were made when it was looked at.
    assert LlamaCppAdapter._slots(BUSY).items[1]["subtitle"] == "Working · 510 tokens made"
    # With an API key the server sends no progress; a working slot is then just working.
    assert LlamaCppAdapter._slots([BUSY[0], {k: v for k, v in BUSY[1].items() if k != "next_token"}]).items[1]["subtitle"] == "Working"
    assert LlamaCppAdapter._slots([]).items == []


def test_the_counters_are_read_out_of_the_prometheus_text() -> None:
    numbers = _numbers(METRICS)
    assert numbers["tokens_predicted_total"] == 2092 and numbers["tokens_predicted_seconds_total"] == 8.86596


@respx.mock
async def test_without_metrics_the_card_is_there_without_a_speed() -> None:
    serve()
    respx.get(f"{L}/metrics").mock(return_value=httpx.Response(501, json={"error": {"message": "This server does not support metrics endpoint."}}))
    data = await get_adapter("llamacpp").fetch("server", CONFIG, {}, fresh())
    assert "Tokens a second" not in {row["label"] for row in data.secondary} and data.status == "ok"
    respx.get(f"{L}/slots").mock(return_value=httpx.Response(501, json={"error": {"message": "slots off"}}))
    only = await get_adapter("llamacpp").fetch("server", CONFIG, {}, fresh(2))
    assert only.secondary[0]["label"] == "Context per slot"
    with pytest.raises(AdapterError) as off:
        await get_adapter("llamacpp").fetch("slots", CONFIG, {}, fresh(3))
    assert off.value.code == "not_enabled" and "--no-slots" in off.value.message


@respx.mock
async def test_the_connection_test_names_the_build() -> None:
    serve()
    assert await get_adapter("llamacpp").test(CONFIG, fresh()) == "llama.cpp b11913-7aca0d2ea answers, 2 slots."


@respx.mock
async def test_a_missing_or_wrong_key_and_the_other_failures() -> None:
    """⚠️ Measured: ``/health`` is open, ``/props`` and the rest answer 401 ``Invalid API Key``."""
    adapter = get_adapter("llamacpp")
    respx.get(f"{L}/props").mock(return_value=httpx.Response(401, json={"error": {"message": "Invalid API Key", "type": "authentication_error", "code": 401}}))
    with pytest.raises(AuthFailed) as wrong:
        await adapter.fetch("server", CONFIG, {}, fresh(1))
    assert "rejected" in str(wrong.value)
    with pytest.raises(AuthFailed) as none:
        await adapter.fetch("server", {"url": L}, {}, fresh(2))
    assert "asks for an API key" in str(none.value)
    respx.get(f"{L}/props").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as other:
        await adapter.fetch("server", CONFIG, {}, fresh(3))
    assert other.value.code == "not_llamacpp"
    respx.get(f"{L}/props").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as html:
        await adapter.fetch("server", CONFIG, {}, fresh(4))
    assert html.value.code == "not_json"
    respx.get(f"{L}/props").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await adapter.fetch("server", CONFIG, {}, fresh(5))


def test_the_key_is_a_secret_and_the_cards_have_demo_data_that_moves() -> None:
    adapter = get_adapter("llamacpp")
    assert {field.name for field in adapter.fields if field.secret} == {"api_key"} and adapter.beta is True
    for widget in adapter.widgets:
        assert adapter.demo(widget.kind, {}, 0).error is None, widget.kind
    assert len({adapter.demo("server", {}, tick).metrics["tokens_per_second"] for tick in range(0, 300, 10)}) > 1
