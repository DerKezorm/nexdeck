"""dash. (dashdot), against the answers of a live dashdot 6.3.4 (27.10.2026)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Unreachable
from app.adapters.base import Context as Ctx
from app.adapters.dashdot import DashdotAdapter

FIXTURES = Path(__file__).parent / "fixtures"
DD = "http://dashdot.example.com:3001"
CONFIG = {"url": DD}


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"dashdot_{name}.json").read_text(encoding="utf-8"))


INFO, CPU, RAM, STORAGE, NETWORK = (fixture(name) for name in ("info", "load_cpu", "load_ram", "load_storage", "load_network"))


def fresh(number: int = 1) -> Ctx:
    return Ctx(httpx.AsyncClient(), integration_id=number, widget_id=1, cache={})


@respx.mock
async def test_the_four_cards_read_what_dashdot_measured() -> None:
    respx.get(f"{DD}/info").mock(return_value=httpx.Response(200, json=INFO))
    respx.get(f"{DD}/load/cpu").mock(return_value=httpx.Response(200, json=CPU))
    respx.get(f"{DD}/load/ram").mock(return_value=httpx.Response(200, json=RAM))
    respx.get(f"{DD}/load/storage").mock(return_value=httpx.Response(200, json=STORAGE))
    respx.get(f"{DD}/load/network").mock(return_value=httpx.Response(200, json=NETWORK))
    adapter, ctx = get_adapter("dashdot"), fresh()
    cpu = await adapter.fetch("cpu", CONFIG, {}, ctx)
    assert cpu.primary == {"label": "CPU", "value": 6, "unit": "%"} and cpu.metrics == {"load": 5.6} and cpu.status == "ok"
    assert cpu.secondary == [{"label": "Busiest core", "value": "14%"}, {"label": "Cores", "value": 4}]
    memory = await adapter.fetch("memory", CONFIG, {}, ctx)
    # 5073317888 of 8333967360 bytes.
    assert memory.primary["value"] == 61 and memory.metrics == {"used": 60.9} and memory.secondary[1] == {"label": "Total", "value": "7.8 GB"}
    storage = await adapter.fetch("storage", CONFIG, {}, ctx)
    assert storage.primary["value"] == 60 and storage.metrics == {"used": 60.1} and storage.status == "ok"
    network = await adapter.fetch("network", CONFIG, {}, ctx)
    # Bytes per second in, megabits per second out.
    assert network.primary == {"label": "Down", "metric": "down", "value": 0.2, "unit": "Mbit/s"} and network.secondary[0]["value"] == 0.1
    assert network.metrics == {"down": 0.2, "up": 0.1}


def test_storage_without_the_host_mounted_is_unknown_not_empty() -> None:
    """⚠️ Measured: a plain container answers ``[-1]``."""
    data = DashdotAdapter._storage([-1], [536870912000])
    assert data.status == "unknown" and data.primary["value"] is None and data.metrics == {}
    assert "privileged" in data.meta["status_reason"]
    assert DashdotAdapter._storage([], [1]).status == "unknown"


def test_a_full_disk_and_a_busy_processor_colour_the_card() -> None:
    assert DashdotAdapter._storage([96.0], [100.0]).status == "bad"
    assert DashdotAdapter._cpu([{"load": 85.0}, {"load": 95.0}]).status == "warn"
    assert DashdotAdapter._memory({"load": 99}, 100).status == "bad"
    assert DashdotAdapter._memory({"load": 1}, None).status == "unknown"


@respx.mock
async def test_the_connection_test_names_version_and_cores() -> None:
    respx.get(f"{DD}/info").mock(return_value=httpx.Response(200, json=INFO))
    assert await get_adapter("dashdot").test(CONFIG, fresh()) == "dashdot 6.3.4 answers, 4 cores."
    assert await get_adapter("dashdot").running_version(CONFIG, fresh(2)) == "6.3.4"


@respx.mock
async def test_not_dashdot_not_json_and_unreachable() -> None:
    adapter = get_adapter("dashdot")
    respx.get(f"{DD}/info").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as other:
        await adapter.fetch("memory", CONFIG, {}, fresh(1))
    assert other.value.code == "not_dashdot"
    respx.get(f"{DD}/info").mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(AdapterError) as html:
        await adapter.fetch("memory", CONFIG, {}, fresh(2))
    assert html.value.code == "not_json"
    respx.get(f"{DD}/load/cpu").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(AdapterError) as none:
        await adapter.fetch("cpu", CONFIG, {}, fresh(3))
    assert none.value.code == "no_data"
    respx.get(f"{DD}/load/cpu").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await adapter.fetch("cpu", CONFIG, {}, fresh(4))


def test_the_cards_have_demo_data_that_moves() -> None:
    adapter = get_adapter("dashdot")
    assert adapter.beta is True and not any(field.secret for field in adapter.fields)
    for widget in adapter.widgets:
        assert adapter.demo(widget.kind, {}, 0).error is None, widget.kind
    assert len({adapter.demo("cpu", {}, tick).primary["value"] for tick in range(0, 300, 10)}) > 1
