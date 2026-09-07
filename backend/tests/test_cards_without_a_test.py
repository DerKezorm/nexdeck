"""Cards in confirmed adapters that no test had ever fetched.

⚠️ A card counts as confirmed here because somebody once looked at it against a
live service. Nothing kept it that way: a parser can be rewritten, an option
renamed, a helper changed under it, and the only thing that notices is the
person whose dashboard goes blank.

These are the ones that carry numbers through the helpers this block changed,
so a regression would put back exactly the bug the block is about. The rest of
the untested cards are still untested, and that is written down rather than
quietly left.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- adguard -------------------------------------------------------------------

ADGUARD = "http://dns.example.com"


def _adguard(**stats: object) -> None:
    respx.get(f"{ADGUARD}/control/stats").mock(return_value=httpx.Response(200, json={
        "num_dns_queries": 20_000, "num_blocked_filtering": 3_400, "avg_processing_time": 0.021,
        "top_blocked_domains": [{"ads.example.com": 812}, {"track.example.com": 405}],
        **stats,
    }))
    respx.get(f"{ADGUARD}/control/status").mock(return_value=httpx.Response(200, json={
        "version": "v0.107.60", "protection_enabled": True}))


@respx.mock
async def test_adguard_shows_the_share_it_blocked(ctx: Context) -> None:
    _adguard()
    data = await get_adapter("adguard").fetch("summary", {"url": ADGUARD, "username": "admin", "password": "x"}, {}, ctx)
    assert data.primary == {"label": "Blocked", "value": 17.0, "unit": "%"}
    assert data.metrics == {"blocked_percent": 17.0, "queries": 20_000.0}
    assert [action.id for action in data.actions] == ["disable"]


@respx.mock
async def test_adguard_that_has_answered_nothing_shows_no_share(ctx: Context) -> None:
    """0 percent blocked reads as "everything got through"."""
    _adguard(num_dns_queries=0, num_blocked_filtering=0)
    data = await get_adapter("adguard").fetch("summary", {"url": ADGUARD, "username": "admin", "password": "x"}, {}, ctx)
    assert data.primary["value"] is None
    assert "blocked_percent" not in data.metrics


@respx.mock
async def test_adguard_lists_the_domains_it_blocks_most(ctx: Context) -> None:
    _adguard()
    data = await get_adapter("adguard").fetch("top", {"url": ADGUARD, "username": "admin", "password": "x"}, {"limit": 1}, ctx)
    assert [(item["title"], item["value"]) for item in data.items] == [("ads.example.com", 812)]


# -- beszel --------------------------------------------------------------------

BESZEL = "http://beszel.example.com:8090"


def _beszel(systems: list[dict]) -> None:
    respx.post(f"{BESZEL}/api/collections/users/auth-with-password").mock(
        return_value=httpx.Response(200, json={"token": "beszel-token"}))
    respx.get(f"{BESZEL}/api/collections/systems/records").mock(
        return_value=httpx.Response(200, json={"items": systems}))


@respx.mock
async def test_beszel_measures_one_host(ctx: Context) -> None:
    _beszel([
        {"name": "nas", "status": "up", "info": {"cpu": 7.2, "mp": 61.4, "dp": 44.0, "u": 86_400}},
        {"name": "pve", "status": "up", "info": {"cpu": 22.0, "mp": 38.0, "dp": 12.0, "u": 3_600}},
    ])
    config = {"url": BESZEL, "username": "a@example.com", "password": "x"}
    data = await get_adapter("beszel").fetch("system", config, {"system": "pve"}, ctx)
    assert data.primary == {"label": "CPU", "value": 22.0, "unit": "%"}
    assert data.metrics == {"cpu": 22.0, "memory": 38.0}
    assert respx.calls.last.request.headers["Authorization"] == "beszel-token"


@respx.mock
async def test_beszel_says_which_host_is_down(ctx: Context) -> None:
    _beszel([
        {"name": "nas", "status": "up", "info": {"cpu": 7.2, "mp": 61.4, "dp": 44.0}},
        {"name": "vps", "status": "down", "info": {}},
    ])
    config = {"url": BESZEL, "username": "a@example.com", "password": "x"}
    data = await get_adapter("beszel").fetch("systems", config, {}, ctx)
    assert [(item["title"], item["status"]) for item in data.items] == [("nas", "ok"), ("vps", "bad")]
    assert data.status == "bad"
    assert data.items[0]["subtitle"] == "mem 61% · disk 44%"


@respx.mock
async def test_beszel_names_a_host_it_does_not_know(ctx: Context) -> None:
    from app.adapters.base import AdapterError

    _beszel([{"name": "nas", "status": "up", "info": {}}])
    with pytest.raises(AdapterError) as refused:
        await get_adapter("beszel").fetch("system", {"url": BESZEL, "username": "a@example.com", "password": "x"},
                                          {"system": "gone"}, ctx)
    assert refused.value.code == "no_such_host"


# -- glances -------------------------------------------------------------------

GLANCES = "http://glances.example.com:61208"


@respx.mock
async def test_glances_reads_load_memory_and_a_temperature(ctx: Context) -> None:
    respx.get(f"{GLANCES}/api/4/quicklook").mock(return_value=httpx.Response(200, json={"cpu": 18.4}))
    respx.get(f"{GLANCES}/api/4/mem").mock(return_value=httpx.Response(200, json={"percent": 63.1}))
    respx.get(f"{GLANCES}/api/4/load").mock(return_value=httpx.Response(200, json={"min1": 1.42}))
    respx.get(f"{GLANCES}/api/4/sensors").mock(return_value=httpx.Response(200, json=[
        {"label": "Package id 0", "value": 47, "unit": "C", "type": "temperature_core"},
    ]))
    data = await get_adapter("glances").fetch("system", {"url": GLANCES}, {}, ctx)
    assert data.primary == {"label": "CPU", "value": 18.4, "unit": "%"}
    assert {row["label"]: row["value"] for row in data.secondary} == {"Memory": 63.1, "Load": 1.42, "Temp": 47}
    assert data.metrics == {"cpu": 18.4, "memory": 63.1}


@respx.mock
async def test_glances_leaves_out_what_is_not_a_disk(ctx: Context) -> None:
    """⚠️ tmpfs and the like are mounted like disks and are not ones."""
    respx.get(f"{GLANCES}/api/4/fs").mock(return_value=httpx.Response(200, json=[
        {"mnt_point": "/", "percent": 71.0, "used": 120e9, "size": 170e9},
        {"mnt_point": "/etc/hosts", "percent": 71.0, "used": 120e9, "size": 170e9},
    ]))
    data = await get_adapter("glances").fetch("disks", {"url": GLANCES}, {}, ctx)
    assert [item["title"] for item in data.items] == ["/"]
    assert data.items[0]["value"] == "71%" and data.items[0]["status"] == "ok"


# -- nzbget --------------------------------------------------------------------

NZBGET = "http://nzbget.example.com:6789"


@respx.mock
async def test_nzbget_reads_the_queue_over_json_rpc(ctx: Context) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        import json as jsonlib

        method = jsonlib.loads(request.content)["method"]
        if method == "status":
            return httpx.Response(200, json={"result": {
                "DownloadRate": 12_000_000, "DownloadPaused": False,
                "RemainingSizeMB": 4_096, "FreeDiskSpaceMB": 500_000}})
        return httpx.Response(200, json={"result": [
            {"NZBName": "Something.2026", "FileSizeMB": 8_192, "RemainingSizeMB": 4_096, "NZBID": 41, "Status": "DOWNLOADING"},
        ]})

    respx.post(f"{NZBGET}/jsonrpc").mock(side_effect=answer)
    data = await get_adapter("nzbget").fetch("queue", {"url": NZBGET, "password": "x"}, {}, ctx)
    assert data.items[0]["title"] == "Something.2026"
    assert data.items[0]["progress"] == 50.0
    assert data.items[0]["subtitle"] == "8.0 GB · 5m 57s left"
    assert data.metrics["download"] == round(12_000_000 / 1024 / 1024, 2)
    assert {chip["label"]: chip["value"] for chip in data.secondary}["Queue"] == 1


@respx.mock
async def test_nzbget_hands_its_refusal_on_in_words(ctx: Context) -> None:
    """⚠️ A JSON-RPC error comes back inside a 200, so the status code says
    nothing and the message is the only thing there is.
    """
    from app.adapters.base import AdapterError

    respx.post(f"{NZBGET}/jsonrpc").mock(return_value=httpx.Response(200, json={
        "error": {"code": -32601, "message": "Invalid method"}}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nzbget").fetch("queue", {"url": NZBGET, "password": "x"}, {}, ctx)
    assert "Invalid method" in str(refused.value)
