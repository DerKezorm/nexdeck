"""Caddy. The answers in the fixtures were recorded from Caddy 2.11.7 on 27.10.2026
with a Caddyfile of five sites (a proxy with an active check and one dead
upstream, a proxy without checks, a path split, a file server, a redirect);
the host names are made up."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {"url": "http://caddy:2019"}
BASE = "http://caddy:2019"


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def served(metrics: str | None = None) -> None:
    """Caddy as recorded: servers, upstreams and the metrics."""
    respx.get(f"{BASE}/config/apps/http/servers/").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "caddy_servers.json").read_text(encoding="utf-8"))))
    respx.get(f"{BASE}/reverse_proxy/upstreams").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "caddy_upstreams.json").read_text(encoding="utf-8"))))
    respx.get(f"{BASE}/metrics").mock(return_value=httpx.Response(
        200, text=metrics if metrics is not None else (FIXTURES / "caddy_metrics.txt").read_text(encoding="utf-8")))


@respx.mock
async def test_the_overview_counts_sites_and_the_upstream_that_does_not_answer(ctx: Context) -> None:
    served()
    data = await get_adapter("caddy").fetch("overview", CONFIG, {}, ctx)
    # app, plain, old and files have a host; the :9001 server answers without one.
    assert data.primary == {"label": "Sites", "value": 5}
    assert data.secondary == [
        {"label": "Upstreams", "value": 4},
        {"label": "Down", "value": 1},
        {"label": "Last reload", "value": "Worked"},
    ]
    assert data.status == "bad"
    assert data.metrics == {"sites": 5.0, "upstreams_down": 1.0}


@respx.mock
async def test_a_failed_reload_turns_the_overview_red_even_when_every_upstream_is_up(ctx: Context) -> None:
    served("caddy_config_last_reload_successful 0\ncaddy_reverse_proxy_upstreams_healthy{upstream=\"127.0.0.1:9001\"} 1\n")
    data = await get_adapter("caddy").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "bad"
    assert {"label": "Last reload", "value": "Failed"} in data.secondary


@respx.mock
async def test_without_metrics_the_sites_are_still_shown_and_nothing_is_called_down(ctx: Context) -> None:
    served()
    respx.get(f"{BASE}/metrics").mock(return_value=httpx.Response(404, text="not found"))
    data = await get_adapter("caddy").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "ok"
    assert [row["label"] for row in data.secondary] == ["Upstreams", "Down"]


@respx.mock
async def test_the_sites_card_names_what_each_host_does_and_puts_the_broken_first(ctx: Context) -> None:
    served()
    data = await get_adapter("caddy").fetch("sites", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    assert rows["app.example.com"]["status"] == "warn"
    assert rows["app.example.com"]["value"] == "1 of 2 up"
    assert rows["app.example.com"]["subtitle"] == "Proxy · 127.0.0.1:9001, 127.0.0.1:9999"
    # The split by path is one site with two upstreams, both up.
    assert rows["plain.example.com"]["status"] == "ok" and rows["plain.example.com"]["value"] == "Up"
    assert rows["plain.example.com"]["subtitle"] == "Proxy · 127.0.0.1:9002, 127.0.0.1:9003"
    assert rows["files.example.com"]["subtitle"] == "Files" and rows["files.example.com"]["value"] == ""
    assert rows["old.example.com"]["subtitle"] == "Redirect"
    # A route without a host is named by the port it listens on.
    assert ":9001" in rows
    assert data.items[0]["title"] == "app.example.com"
    assert data.status == "warn"


@respx.mock
async def test_only_problems_leaves_out_the_healthy_sites(ctx: Context) -> None:
    served()
    data = await get_adapter("caddy").fetch("sites", CONFIG, {"only_problems": True}, ctx)
    assert [row["title"] for row in data.items] == ["app.example.com"]


@respx.mock
async def test_a_site_whose_every_upstream_is_down_is_red(ctx: Context) -> None:
    served("caddy_reverse_proxy_upstreams_healthy{upstream=\"127.0.0.1:9001\"} 0\ncaddy_reverse_proxy_upstreams_healthy{upstream=\"127.0.0.1:9999\"} 0\n")
    data = await get_adapter("caddy").fetch("sites", CONFIG, {}, ctx)
    first = data.items[0]
    assert (first["title"], first["status"], first["value"]) == ("app.example.com", "bad", "Down")
    assert data.status == "bad"


@respx.mock
async def test_the_upstreams_card_takes_the_verdict_from_the_metrics_not_from_fails(ctx: Context) -> None:
    served()
    data = await get_adapter("caddy").fetch("upstreams", CONFIG, {}, ctx)
    # Recorded: the dead upstream shows fails 0 in the API and 0 in the gauge.
    assert data.items[0] == {"title": "127.0.0.1:9999", "subtitle": "", "status": "bad", "value": "Down"}
    assert {row["value"] for row in data.items[1:]} == {"Up"}
    assert data.secondary == [{"label": "Upstreams", "value": 4}, {"label": "Down", "value": 1}]
    assert data.metrics == {"upstreams_down": 1.0}


@respx.mock
async def test_passive_failures_without_a_verdict_turn_an_upstream_yellow(ctx: Context) -> None:
    served("")
    respx.get(f"{BASE}/reverse_proxy/upstreams").mock(return_value=httpx.Response(
        200, json=[{"address": "app:8080", "num_requests": 2, "fails": 3}]))
    data = await get_adapter("caddy").fetch("upstreams", CONFIG, {}, ctx)
    assert data.items == [{"title": "app:8080", "subtitle": "2 in flight · 3 failed", "status": "warn", "value": ""}]


@respx.mock
async def test_the_connection_test_counts_the_sites(ctx: Context) -> None:
    served()
    assert await get_adapter("caddy").test(CONFIG, ctx) == "Caddy answers, 5 site(s)."


@respx.mock
async def test_basic_authentication_is_sent_when_a_user_is_set(ctx: Context) -> None:
    served()
    await get_adapter("caddy").fetch("overview", {**CONFIG, "username": "ops", "password": "example-pass"}, {}, ctx)
    sent = respx.calls.last.request.headers["Authorization"]
    assert sent.startswith("Basic ")


@respx.mock
async def test_a_proxy_that_refuses_the_credentials_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(f"{BASE}/config/apps/http/servers/").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed):
        await get_adapter("caddy").fetch("overview", CONFIG, {}, ctx)


@respx.mock
async def test_a_site_instead_of_the_admin_api_says_so(ctx: Context) -> None:
    respx.get(f"{BASE}/config/apps/http/servers/").mock(return_value=httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("caddy").fetch("overview", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"


@respx.mock
async def test_an_unreachable_admin_api_is_unreachable(ctx: Context) -> None:
    respx.get(f"{BASE}/config/apps/http/servers/").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("caddy").fetch("overview", CONFIG, {}, ctx)


def test_an_upstream_is_named_as_the_metrics_name_it() -> None:
    from app.adapters.caddy import _dial

    assert [_dial(one) for one in ("tcp/app:80", "http://app:80", "https://app:443", "app:80")] == [
        "app:80", "app:80", "app:443", "app:80"]
