"""CrowdSec, against the answers of a live CrowdSec 1.8.1 (11.09.2026), read with a bouncer key."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.crowdsec import _seconds

CS = "http://crowdsec.example.com"
CONFIG = {"url": CS, "api_key": "made-up-bouncer-key"}

#: Measured field for field; ``duration`` is the time left.
SHORT_BAN = {"duration": "29m29s", "id": 3, "origin": "cscli", "scenario": "ssh-bf test", "scope": "Ip", "type": "ban", "value": "203.0.113.7"}
RANGE = {"duration": "23h59m55s", "id": 2, "origin": "cscli", "scenario": "manual range", "scope": "Range", "type": "captcha", "value": "198.51.100.0/24"}
BAN = {"duration": "3h59m58s", "id": 1, "origin": "crowdsec", "scenario": "crowdsecurity/http-probing", "scope": "Ip", "type": "ban", "value": "192.0.2.10"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_go_durations_become_seconds() -> None:
    assert _seconds("29m29s") == 1769 and _seconds("23h59m55s") == 86395 and _seconds("1.5s") == 1.5
    assert _seconds(None) == 0 and _seconds("soon") == 0


@respx.mock
async def test_the_list_asks_only_for_this_installation_s_decisions(ctx: Context) -> None:
    """⚠️ Unfiltered, an enrolled installation hands out the whole community blocklist."""
    route = respx.get(f"{CS}/v1/decisions").mock(return_value=httpx.Response(200, json=[BAN, SHORT_BAN, RANGE]))
    data = await get_adapter("crowdsec").fetch("decisions", CONFIG, {"limit": 10}, ctx)
    sent = route.calls.last.request
    assert sent.headers["X-Api-Key"] == "made-up-bouncer-key" and sent.url.params["origins"] == "crowdsec,cscli"
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in data.items] == [
        ("203.0.113.7", "Ban · ssh-bf test", "29m 29s", "warn"),
        ("198.51.100.0/24", "Captcha · manual range", "23h 59m", "unknown"),
        ("192.0.2.10", "Ban · http-probing", "3h 59m", "warn"),
    ]
    assert data.secondary == [{"label": "Blocked", "value": 3}, {"label": "Ranges", "value": 1}]


@respx.mock
async def test_the_community_blocklist_only_on_request_and_named(ctx: Context) -> None:
    capi = {"duration": "160h", "id": 9, "origin": "CAPI", "scenario": "crowdsecurity/ssh-bf", "scope": "Ip", "type": "ban", "value": "203.0.113.200"}
    route = respx.get(f"{CS}/v1/decisions").mock(return_value=httpx.Response(200, json=[capi, BAN]))
    data = await get_adapter("crowdsec").fetch("decisions", CONFIG, {"limit": 10, "community": True}, ctx)
    assert "origins" not in route.calls.last.request.url.params
    assert data.items[0]["subtitle"] == "Ban · ssh-bf · CAPI"


@respx.mock
async def test_nothing_blocked_is_null_not_an_empty_list(ctx: Context) -> None:
    """⚠️ Measured: no decision at all is answered with the JSON null."""
    respx.get(f"{CS}/v1/decisions").mock(return_value=httpx.Response(200, text="null", headers={"Content-Type": "application/json"}))
    data = await get_adapter("crowdsec").fetch("decisions", CONFIG, {"limit": 10}, ctx)
    assert data.items == [] and data.meta["empty"] == "Nothing is blocked right now."
    assert await get_adapter("crowdsec").test(CONFIG, ctx) == "CrowdSec answers: 0 decisions made by this installation are active."


@respx.mock
async def test_the_summary_counts_bans_captchas_and_ranges(ctx: Context) -> None:
    respx.get(f"{CS}/v1/decisions").mock(return_value=httpx.Response(200, json=[BAN, SHORT_BAN, RANGE]))
    data = await get_adapter("crowdsec").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Blocked", "value": 3}
    assert data.secondary == [{"label": "Bans", "value": 2}, {"label": "Captchas", "value": 1}, {"label": "Ranges", "value": 1}]
    assert data.metrics == {"blocked": 3.0}


@respx.mock
async def test_a_wrong_key_and_another_service(ctx: Context) -> None:
    respx.get(f"{CS}/v1/decisions").mock(return_value=httpx.Response(403, json={"message": "access forbidden"}))
    with pytest.raises(AuthFailed):
        await get_adapter("crowdsec").test(CONFIG, ctx)
    respx.get(f"{CS}/v1/decisions").mock(return_value=httpx.Response(200, json={"decisions": []}))
    fresh = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as wrong:
        await get_adapter("crowdsec").fetch("summary", CONFIG, {}, fresh)
    assert wrong.value.code == "not_crowdsec"
