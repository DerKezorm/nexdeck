"""Umami. The answers in ``fixtures/umami_v3_answers.json`` were recorded on
28.10.2026 from Umami 3.4.1 with PostgreSQL (three made-up websites, a few
visits sent to ``/api/send``; token and ids replaced).

⚠️ Umami 2 (``{"value", "prev"}`` per figure, ``{"x": n}`` for the visitors
online, ``url`` instead of ``path``) and Umami Cloud (API key) were not run:
their answers below are made up after the documentation, and the card stays a
beta for that reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client

REC: dict[str, Any] = json.loads((Path(__file__).parent / "fixtures" / "umami_v3_answers.json").read_text(encoding="utf-8"))
BASE = "https://umami.example.com"
API = f"{BASE}/api"
CONFIG = {"url": BASE, "username": "admin", "password": "made-up-password"}
ADAPTER = get_adapter("umami")
SITES = {"data": [{"id": "11111111-2222-3333-4444-555555555555", "name": "Blog", "domain": "blog.example.com"},
                  {"id": "66666666-7777-8888-9999-000000000000", "name": "Docs", "domain": "docs.example.com"}], "count": 2}
BLOG, DOCS = SITES["data"][0]["id"], SITES["data"][1]["id"]
R_BLOG, R_DOCS, R_EMPTY = (one["id"] for one in REC["websites"]["data"])
STATS_2 = {"pageviews": {"value": 900, "prev": 800}, "visitors": {"value": 300, "prev": 280}, "visits": {"value": 400, "prev": 0},
           "bounces": {"value": 100, "prev": 0}, "totaltime": {"value": 38000, "prev": 0}}
STATS_3 = {"pageviews": 900, "visitors": 300, "visits": 400, "bounces": 100, "totaltime": 38000, "comparison": {"pageviews": 800}}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(outbound_client(guard=False), integration_id=2, widget_id=2, cache={})


def umami(stats: dict = STATS_2, active: dict | None = None) -> None:
    respx.post(f"{API}/auth/login").mock(return_value=httpx.Response(200, json={"token": "made-up-token", "user": {"username": "admin"}}))
    respx.get(f"{API}/websites").mock(return_value=httpx.Response(200, json=SITES))
    respx.get(f"{API}/websites/{BLOG}/stats").mock(return_value=httpx.Response(200, json=stats))
    respx.get(f"{API}/websites/{BLOG}/active").mock(return_value=httpx.Response(200, json=active or {"x": 4}))
    respx.get(f"{API}/websites/{DOCS}/stats").mock(return_value=httpx.Response(200, json={"pageviews": {"value": 90}, "visitors": {"value": 60}}))
    respx.get(f"{API}/websites/{DOCS}/active").mock(return_value=httpx.Response(200, json={"x": 0}))


@respx.mock
async def test_the_site_card_reads_umami_2_and_umami_3_alike(ctx: Context) -> None:
    umami()
    two = await ADAPTER.fetch("site", CONFIG, {}, ctx)
    assert two.primary == {"label": "Visitors", "value": 300}
    assert two.secondary == [{"label": "Page views", "value": 900}, {"label": "Visits", "value": 400}, {"label": "Online now", "value": 4},
                             {"label": "Bounce rate", "value": "25%"}, {"label": "Visit time", "value": "1m 35s"}]
    assert two.metrics == {"visitors": 300.0, "pageviews": 900.0, "online": 4.0}
    respx.reset()
    umami(STATS_3, {"visitors": 4})
    three = await ADAPTER.fetch("site", CONFIG, {}, fresh())
    assert three.primary == two.primary and three.secondary == two.secondary


@respx.mock
async def test_the_period_is_sent_as_milliseconds(ctx: Context) -> None:
    umami()
    await ADAPTER.fetch("site", CONFIG, {"period": "week"}, ctx)
    request = next(call.request for call in respx.calls if call.request.url.path.endswith("/stats"))
    start, end = int(request.url.params["startAt"]), int(request.url.params["endAt"])
    assert end > 1_700_000_000_000 and end - start == 7 * 86400 * 1000
    assert request.headers["authorization"] == "Bearer made-up-token"


@respx.mock
async def test_the_websites_card_ranks_them_by_visitors_with_the_ones_online(ctx: Context) -> None:
    umami()
    data = await ADAPTER.fetch("websites", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["progress"]) for row in data.items] == [("Blog", "300", 100.0), ("Docs", "60", 20.0)]
    assert data.items[0]["subtitle"] == "blog.example.com · 900 views · 4 online" and data.items[1]["subtitle"] == "docs.example.com · 90 views"
    assert data.secondary == [{"label": "Websites", "value": 2}]


@respx.mock
async def test_a_website_is_found_by_name_domain_or_id_and_a_wrong_one_is_said(ctx: Context) -> None:
    umami()
    respx.get(f"{API}/websites/{DOCS}/metrics").mock(return_value=httpx.Response(200, json=[{"x": "/", "y": 40}, {"x": "/guide", "y": 20}]))
    for wanted in ("docs.example.com", "DOCS", DOCS):
        data = await ADAPTER.fetch("top", CONFIG, {"website": wanted}, fresh())
        assert [row["title"] for row in data.items] == ["/", "/guide"]
    with pytest.raises(AdapterError) as missing:
        await ADAPTER.fetch("top", CONFIG, {"website": "nowhere"}, fresh())
    assert missing.value.code == "no_website"


@respx.mock
async def test_the_top_card_asks_for_path_and_falls_back_to_url_for_umami_2(ctx: Context) -> None:
    umami()
    route = respx.get(f"{API}/websites/{BLOG}/metrics").mock(side_effect=lambda request: httpx.Response(
        400 if request.url.params["type"] == "path" else 200, json=[{"x": "/", "y": 30}, {"x": "/about", "y": 15}]))
    data = await ADAPTER.fetch("top", CONFIG, {"what": "pages", "limit": 5}, ctx)
    assert [(row["title"], row["value"], row["progress"]) for row in data.items] == [("/", "30", 100.0), ("/about", "15", 50.0)]
    assert [call.request.url.params["type"] for call in route.calls] == ["path", "url"] and route.calls.last.request.url.params["limit"] == "5"


@respx.mock
async def test_the_top_card_names_visits_without_a_referrer(ctx: Context) -> None:
    umami()
    respx.get(f"{API}/websites/{BLOG}/metrics").mock(return_value=httpx.Response(200, json=[{"x": "", "y": 12}, {"x": "news.example.org", "y": 6}]))
    data = await ADAPTER.fetch("top", CONFIG, {"what": "referrers"}, ctx)
    assert data.items[0]["title"] == "Direct" and data.items[0]["subtitle"] == "No referrer"
    assert respx.calls.last.request.url.params["type"] == "referrer"


@respx.mock
async def test_a_token_that_ran_out_is_replaced_once_and_a_wrong_password_is_said(ctx: Context) -> None:
    umami()
    login = respx.post(f"{API}/auth/login").mock(return_value=httpx.Response(200, json={"token": "made-up-token"}))
    route = respx.get(f"{API}/websites").mock(side_effect=[httpx.Response(401, json={"error": "Unauthorized"}), httpx.Response(200, json=SITES)])
    ctx.cache["umami:token"] = "old-token"
    assert len(await ADAPTER._websites(CONFIG, ctx)) == 2
    assert login.call_count == 1 and route.call_count == 2 and ctx.cache["umami:token"] == "made-up-token"
    assert route.calls[0].request.headers["authorization"] == "Bearer old-token"
    login.mock(return_value=httpx.Response(401, json={"error": "Unauthorized"}))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.test(CONFIG, fresh())
    assert "rejected the user name" in wrong.value.message
    with pytest.raises(AuthFailed) as nobody:
        await ADAPTER.test({"url": BASE}, fresh())
    assert "wants a user name" in nobody.value.message


@respx.mock
async def test_umami_cloud_uses_an_api_key_and_its_own_address(ctx: Context) -> None:
    route = respx.get("https://api.umami.is/v1/websites").mock(return_value=httpx.Response(200, json=SITES))
    cloud = {"url": "https://api.umami.is", "api_key": "made-up-key"}
    assert await ADAPTER.test(cloud, ctx) == "Umami accepts the sign-in, 2 websites."
    assert route.calls.last.request.headers["x-umami-api-key"] == "made-up-key" and "authorization" not in route.calls.last.request.headers
    route.mock(return_value=httpx.Response(401, json={"error": "Unauthorized"}))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.test(cloud, fresh())
    assert "API key" in wrong.value.message


@respx.mock
async def test_a_wrong_address_a_site_free_umami_and_an_unreachable_one(ctx: Context) -> None:
    umami()
    respx.get(f"{API}/websites").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test(CONFIG, ctx)
    assert elsewhere.value.code == "not_umami"
    respx.get(f"{API}/websites").mock(return_value=httpx.Response(200, json={"data": [], "count": 0}))
    with pytest.raises(AdapterError) as empty:
        await ADAPTER.fetch("site", CONFIG, {}, fresh())
    assert empty.value.code == "no_website"
    respx.get(f"{API}/websites").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("websites", CONFIG, {}, fresh())


def umami_three() -> None:
    """The recorded Umami 3.4.1, as it answers for its three websites."""
    respx.post(f"{API}/auth/login").mock(return_value=httpx.Response(200, json=REC["login"]))
    respx.get(f"{API}/websites").mock(return_value=httpx.Response(200, json=REC["websites"]))
    respx.get(f"{API}/websites/{R_BLOG}/stats").mock(return_value=httpx.Response(200, json=REC["stats"]))
    respx.get(f"{API}/websites/{R_BLOG}/active").mock(return_value=httpx.Response(200, json=REC["active"]))
    for other in (R_DOCS, R_EMPTY):
        respx.get(f"{API}/websites/{other}/stats").mock(return_value=httpx.Response(200, json=REC["stats_empty"] if other == R_EMPTY else {**REC["stats"], "visitors": 2, "pageviews": 3, "visits": 2, "bounces": 1}))
        respx.get(f"{API}/websites/{other}/active").mock(return_value=httpx.Response(200, json=REC["active_empty"]))

    def metrics(request: httpx.Request) -> httpx.Response:
        wanted = request.url.params["type"]
        if wanted not in ("path", "referrer", "country", "browser", "device"):
            return httpx.Response(400, json=REC["metrics_url_refused"])
        return httpx.Response(200, json=REC[f"metrics_{wanted}"])

    respx.get(url__regex=rf"{API}/websites/[^/]+/metrics").mock(side_effect=metrics)


@respx.mock
async def test_the_site_card_against_the_recorded_umami_3(ctx: Context) -> None:
    umami_three()
    data = await ADAPTER.fetch("site", CONFIG, {}, ctx)
    assert data.primary == {"label": "Visitors", "value": 5}
    assert data.secondary == [{"label": "Page views", "value": 9}, {"label": "Visits", "value": 5}, {"label": "Online now", "value": 4},
                              {"label": "Bounce rate", "value": "20%"}, {"label": "Visit time", "value": "1s"}]
    assert data.metrics == {"visitors": 5.0, "pageviews": 9.0, "online": 4.0}
    empty = await ADAPTER.fetch("site", CONFIG, {"website": "Leer"}, fresh())
    assert empty.primary == {"label": "Visitors", "value": 0} and [row["label"] for row in empty.secondary] == ["Page views", "Visits", "Online now"]


@respx.mock
async def test_the_websites_card_against_the_recorded_umami_3(ctx: Context) -> None:
    umami_three()
    data = await ADAPTER.fetch("websites", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["progress"]) for row in data.items] == [("Blog", "5", 100.0), ("Docs", "2", 40.0), ("Leer", "0", 0.0)]
    assert data.items[0]["subtitle"] == "blog.example.com · 9 views · 4 online" and data.secondary == [{"label": "Websites", "value": 3}]
    assert respx.calls[1].request.url.params["pageSize"] == "100"


@respx.mock
async def test_every_ranking_against_the_recorded_umami_3(ctx: Context) -> None:
    umami_three()
    seen = {}
    for what in ("pages", "referrers", "countries", "browsers", "devices"):
        data = await ADAPTER.fetch("top", CONFIG, {"what": what, "limit": 2}, fresh())
        seen[what] = [(row["title"], row["value"]) for row in data.items]
    assert seen == {"pages": [("/", "3"), ("/blog/self-hosting", "3")], "referrers": [("news.example.org", "1"), ("search.example.net", "1")],
                    "countries": [("US", "3"), ("AU", "1")], "browsers": [("chrome", "1"), ("firefox", "1")], "devices": [("laptop", "3"), ("mobile", "1")]}
    # Umami 3 knows path, so the fallback to url is not needed: one request per ranking.
    assert sum(1 for call in respx.calls if call.request.url.path.endswith("/metrics")) == 5
    respx.get(url__regex=rf"{API}/websites/[^/]+/metrics").mock(return_value=httpx.Response(200, json=REC["metrics_empty"]))
    nothing = await ADAPTER.fetch("top", CONFIG, {"website": "Leer"}, fresh())
    assert nothing.items == [] and nothing.meta["empty"] == "No visits in this period."


@respx.mock
async def test_the_sign_in_errors_umami_3_gives(ctx: Context) -> None:
    umami_three()
    respx.post(f"{API}/auth/login").mock(return_value=httpx.Response(401, json=REC["login_wrong"]))
    with pytest.raises(AuthFailed) as wrong:
        await ADAPTER.test(CONFIG, ctx)
    assert "rejected the user name" in wrong.value.message
    respx.post(f"{API}/auth/login").mock(return_value=httpx.Response(404, text="<html>404</html>"))
    with pytest.raises(AdapterError) as elsewhere:
        await ADAPTER.test(CONFIG, fresh())
    assert elsewhere.value.code == "not_umami"
    respx.post(f"{API}/auth/login").mock(return_value=httpx.Response(200, json=REC["login"]))
    respx.get(f"{API}/websites").mock(return_value=httpx.Response(401, json=REC["unauthorized"]))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, fresh())
