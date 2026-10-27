"""Spoolman, against the answers of Spoolman 0.27.0 (27.10.2026)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

SM = "http://spoolman.example.com:7912"
CONFIG = {"url": SM}
ADAPTER = get_adapter("spoolman")
FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def serve(spools: Any = None) -> None:
    respx.get(f"{SM}/api/v1/info").mock(return_value=httpx.Response(200, json=recorded("spoolman_info.json")))
    respx.get(f"{SM}/api/v1/spool").mock(return_value=httpx.Response(200, json=recorded("spoolman_spools.json") if spools is None else spools))


@respx.mock
async def test_the_test_names_the_version_and_the_spools(ctx: Context) -> None:
    serve()
    assert await ADAPTER.test(CONFIG, ctx) == "Spoolman 0.27.0 answers with 4 spools."


@respx.mock
async def test_the_stock_adds_up_what_is_known(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("stock", CONFIG, {}, ctx)
    # 805 + 60 + 500 grams; the spool nobody weighed is left out of the sum, not counted as empty.
    assert card.primary == {"label": "Filament left", "value": 1.36, "unit": "kg"}
    assert [(row["label"], row["value"]) for row in card.secondary] == [("Spools", 4), ("Running low", 1)]
    assert card.status == "warn"
    assert card.metrics == {"remaining_kg": 1.365, "low_spools": 1.0}


@respx.mock
async def test_the_line_for_running_low_is_the_cards_own(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("stock", CONFIG, {"low_percent": 5}, ctx)
    assert card.status == "ok" and card.metrics["low_spools"] == 0.0
    assert [row["label"] for row in card.secondary] == ["Spools"]
    card = await ADAPTER.fetch("stock", CONFIG, {"low_percent": "nonsense"}, Context(httpx.AsyncClient(), cache={}))
    assert card.metrics["low_spools"] == 1.0


@respx.mock
async def test_the_spools_come_emptiest_first_and_the_unweighed_last(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("spools", CONFIG, {}, ctx)
    assert [(item["id"], item["value"], item["progress"], item["status"]) for item in card.items] == [
        (2, "60 g", 6.0, "warn"),
        (3, "500 g", 50.0, "ok"),
        (1, "805 g", 80.5, "ok"),
        # ⚠️ No weight anywhere: unknown, not empty.
        (5, "?", None, "unknown"),
    ]
    assert card.items[0]["title"] == "Example Filaments PLA Signal Red"
    assert card.items[0]["subtitle"] == "PLA · Shelf A"
    assert card.items[3]["title"] == "Mystery" and card.items[3]["subtitle"] == "ABS"


@respx.mock
async def test_an_empty_spool_that_is_not_archived_is_red(ctx: Context) -> None:
    spools = recorded("spoolman_spools.json")
    spools[1]["remaining_weight"] = 0.0
    serve(spools)
    card = await ADAPTER.fetch("spools", CONFIG, {}, ctx)
    assert card.items[0]["id"] == 2 and card.items[0]["status"] == "bad"


@respx.mock
async def test_the_list_keeps_to_its_limit(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("spools", CONFIG, {"limit": 2}, ctx)
    assert [item["id"] for item in card.items] == [2, 3]


@respx.mock
async def test_a_spoolman_without_spools_says_so(ctx: Context) -> None:
    serve([])
    card = await ADAPTER.fetch("spools", CONFIG, {}, ctx)
    assert card.items == [] and card.meta["empty"] == "No spool in Spoolman."
    stock = await ADAPTER.fetch("stock", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert stock.primary["value"] == 0 and stock.metrics == {"low_spools": 0.0}


@respx.mock
async def test_spools_nobody_weighed_make_no_total(ctx: Context) -> None:
    serve([recorded("spoolman_spools.json")[3]])
    card = await ADAPTER.fetch("stock", CONFIG, {}, ctx)
    # ⚠️ A total of zero would be written into the history as if it had been measured.
    assert card.metrics == {"low_spools": 0.0}


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("stock", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("spools", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert not used


@respx.mock
async def test_a_proxy_that_asks_for_a_sign_in_is_an_auth_failure(ctx: Context) -> None:
    respx.get(f"{SM}/api/v1/info").mock(return_value=httpx.Response(401, text="no"))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, ctx)


@respx.mock
async def test_unreachable_and_not_spoolman(ctx: Context) -> None:
    respx.get(f"{SM}/api/v1/spool").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("stock", CONFIG, {}, ctx)
    respx.get(f"{SM}/api/v1/spool").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("stock", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "not_spoolman"
    respx.get(f"{SM}/api/v1/spool").mock(return_value=httpx.Response(200, json={"something": "else"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("stock", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "not_spoolman"
    respx.get(f"{SM}/api/v1/info").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "not_spoolman"
    respx.get(f"{SM}/api/v1/spool").mock(return_value=httpx.Response(404, json={}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("spools", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert caught.value.code == "http_error"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.primary or card.items
        assert card.secondary
