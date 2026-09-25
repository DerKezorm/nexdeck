"""The public address card: which service is asked, what it shows, and when it says the address changed."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import CACHE_PREFIX, AdapterError, Context


def _fresh_answers(ctx: Context) -> None:
    """Forget the minute of answers the card keeps, and nothing else."""
    for key in [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]:
        del ctx.cache[key]


def _ctx(widget_id: int, cache: dict | None = None) -> Context:
    return Context(httpx.AsyncClient(), integration_id=None, widget_id=widget_id, cache={} if cache is None else cache)


@respx.mock
async def test_ipify_is_asked_for_the_family_the_card_wants() -> None:
    v4 = respx.get("https://api.ipify.org", params={"format": "json"}).mock(return_value=httpx.Response(200, json={"ip": "203.0.113.57"}))
    v6 = respx.get("https://api64.ipify.org", params={"format": "json"}).mock(return_value=httpx.Response(200, json={"ip": "2001:db8::57"}))
    adapter = get_adapter("publicip")
    card = await adapter.fetch("address", {}, {}, _ctx(1))
    assert card.primary == {"label": "Address", "value": "203.0.113.57"} and card.secondary == [] and card.status == "ok"
    card = await adapter.fetch("address", {}, {"family": "any"}, _ctx(2))
    assert card.primary["value"] == "2001:db8::57"
    assert v4.call_count == 1 and v6.call_count == 1


@respx.mock
async def test_ipwhois_adds_the_provider_and_the_place() -> None:
    respx.get("https://ipwho.is/").mock(return_value=httpx.Response(200, json={
        "ip": "203.0.113.57", "success": True, "city": "Berlin", "country": "Germany",
        "connection": {"asn": 64500, "org": "Example Org", "isp": "Example Telecom"},
    }))
    card = await get_adapter("publicip").fetch("address", {}, {"provider": "ipwhois"}, _ctx(1))
    assert card.secondary == [{"label": "Provider", "value": "Example Telecom"}, {"label": "Place", "value": "Berlin, Germany"}]


@respx.mock
async def test_a_change_is_told_for_an_hour_and_the_old_address_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.adapters.publicip as module

    answers = iter(["203.0.113.57", "203.0.113.57", "203.0.113.99", "203.0.113.99"])
    respx.get("https://api.ipify.org").mock(side_effect=lambda request: httpx.Response(200, json={"ip": next(answers)}))
    clock = [1_000_000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    adapter = get_adapter("publicip")
    shared: dict = {}
    ctx = _ctx(1, shared)

    first = await adapter.fetch("address", {}, {}, ctx)
    _fresh_answers(ctx)
    same = await adapter.fetch("address", {}, {}, ctx)
    assert first.status == same.status == "ok" and same.secondary == [], "the first answer after a start is no change"

    _fresh_answers(ctx)
    clock[0] += 900
    changed = await adapter.fetch("address", {}, {}, ctx)
    assert changed.status == "warn" and changed.meta["status_reason"]
    assert changed.secondary == [{"label": "Before", "value": "203.0.113.57"}]

    _fresh_answers(ctx)
    clock[0] += module.FRESH_SECONDS + 1
    later = await adapter.fetch("address", {}, {}, ctx)
    assert later.status == "ok" and later.secondary == [{"label": "Before", "value": "203.0.113.57"}], "an hour on it is news no longer"


@respx.mock
async def test_two_cards_do_not_take_each_other_for_a_change() -> None:
    """⚠️ Cards without a connection share one cache; the last address must be kept per card."""
    respx.get("https://api.ipify.org").mock(return_value=httpx.Response(200, json={"ip": "203.0.113.57"}))
    respx.get("https://api64.ipify.org").mock(return_value=httpx.Response(200, json={"ip": "2001:db8::57"}))
    adapter = get_adapter("publicip")
    shared: dict = {}
    for _ in range(2):
        v4 = await adapter.fetch("address", {}, {}, _ctx(1, shared))
        v6 = await adapter.fetch("address", {}, {"family": "any"}, _ctx(2, shared))
        _fresh_answers(_ctx(1, shared))
    assert v4.status == v6.status == "ok" and v4.secondary == v6.secondary == []


@respx.mock
async def test_the_mask_leaves_the_last_block() -> None:
    respx.get("https://api.ipify.org").mock(return_value=httpx.Response(200, json={"ip": "203.0.113.57"}))
    card = await get_adapter("publicip").fetch("address", {}, {"mask": True}, _ctx(1))
    assert card.primary["value"] == "•••.•••.•••.57"
    from app.adapters.publicip import masked

    assert masked("2001:db8::57") == "•••:57"


@respx.mock
async def test_what_is_not_an_address_is_an_error_not_a_value() -> None:
    adapter = get_adapter("publicip")
    respx.get("https://api.ipify.org").mock(return_value=httpx.Response(200, json={"ip": "<script>"}))
    with pytest.raises(AdapterError) as bad:
        await adapter.fetch("address", {}, {}, _ctx(1))
    assert bad.value.code == "bad_answer"
    respx.get("https://ipwho.is/").mock(return_value=httpx.Response(200, json={"success": False, "message": "You've hit the monthly limit"}))
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("address", {}, {"provider": "ipwhois"}, _ctx(2))
    assert refused.value.code == "refused" and "monthly limit" in refused.value.message
    respx.get("https://api64.ipify.org").mock(return_value=httpx.Response(429))
    with pytest.raises(AdapterError) as limited:
        await adapter.fetch("address", {}, {"family": "any"}, _ctx(3))
    assert limited.value.code == "http_error" and "429" in limited.value.message


def test_the_demo_shows_an_address_from_the_documentation_range() -> None:
    card = get_adapter("publicip").demo("address", {}, 0)
    assert card.primary["value"].startswith("203.0.113.")
