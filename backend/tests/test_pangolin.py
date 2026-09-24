"""Pangolin, against answers shaped as its source writes them (1.23, September 2026).

The envelope, the paging and the fields come from ``listSites.ts``,
``listResources.ts`` and ``listAllSiteResourcesByOrg.ts``; the refusals word
for word from the integration middlewares and ``formatError.ts``.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

URL = "https://api.pangolin.example.com"
CONFIG = {"url": URL, "api_key": "key-id.key-secret", "org_id": "home"}


def _page(key: str, rows: list[dict], total: int | None = None, page: int = 1) -> dict:
    return {"data": {key: rows, "pagination": {"total": len(rows) if total is None else total, "pageSize": 200, "page": page}},
            "success": True, "error": False, "message": "ok", "status": 200}


def _refusal(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"data": None, "success": False, "error": True, "message": message, "status": status, "stack": None})


SITES = [
    {"siteId": 1, "niceId": "home-lab", "name": "Home lab", "type": "newt", "online": True, "address": "100.89.128.4/32", "resourceCount": 3, "status": "approved", "newtVersion": "1.9.0"},
    {"siteId": 2, "niceId": "cabin", "name": "Cabin", "type": "wireguard", "online": False, "address": "100.89.128.12/32", "resourceCount": 1, "status": "approved"},
    # A local site comes without ``online``: listSites drops it.
    {"siteId": 3, "niceId": "vps", "name": "VPS", "type": "local", "resourceCount": 0, "status": "approved"},
    {"siteId": 4, "niceId": "new", "name": "New site", "type": "newt", "online": False, "resourceCount": 0, "status": "pending"},
]

RESOURCES = [
    {"resourceId": 1, "name": "Jellyfin", "fullDomain": "media.example.com", "enabled": True, "health": "healthy", "proxyPort": None,
     "targets": [{"targetId": 1, "ip": "192.168.1.20", "port": 8096, "enabled": True, "healthStatus": "healthy", "siteName": "Home lab"}],
     "sites": [{"siteId": 1, "siteName": "Home lab", "siteNiceId": "home-lab", "online": True}]},
    {"resourceId": 2, "name": "Weather station", "fullDomain": "weather.example.com", "enabled": True, "health": "unhealthy",
     "targets": [], "sites": [{"siteId": 2, "siteName": "Cabin", "siteNiceId": "cabin", "online": False}]},
    {"resourceId": 3, "name": "Minecraft", "fullDomain": None, "proxyPort": 25565, "enabled": False, "health": "unknown", "targets": [], "sites": []},
]

PRIVATE = [
    {"siteResourceId": 1, "name": "NAS shares", "destination": "192.168.1.20", "enabled": True, "siteNames": ["Home lab"], "siteOnlines": [True]},
    {"siteResourceId": 2, "name": "Cabin camera", "destination": "10.0.5.3", "enabled": True, "siteNames": ["Cabin"], "siteOnlines": [False]},
]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _serve() -> dict[str, respx.Route]:
    return {
        "sites": respx.get(f"{URL}/v1/org/home/sites").mock(return_value=httpx.Response(200, json=_page("sites", SITES))),
        "resources": respx.get(f"{URL}/v1/org/home/resources").mock(return_value=httpx.Response(200, json=_page("resources", RESOURCES))),
        "private": respx.get(f"{URL}/v1/org/home/site-resources").mock(return_value=httpx.Response(200, json=_page("siteResources", PRIVATE))),
    }


@respx.mock
async def test_sites_say_online_offline_local_and_pending(ctx: Context) -> None:
    routes = _serve()
    data = await get_adapter("pangolin").fetch("sites", CONFIG, {}, ctx)
    assert routes["sites"].calls.last.request.headers["Authorization"] == "Bearer key-id.key-secret"
    assert [(item["title"], item["value"], item["status"]) for item in data.items] == [
        ("Cabin", "Offline", "bad"),
        ("New site", "Pending", "warn"),
        ("Home lab", "Online", "ok"),
        ("VPS", "Local", "ok"),
    ]
    assert data.items[2]["subtitle"] == "newt · 100.89.128.4/32"


@respx.mock
async def test_only_offline_keeps_the_sites_that_need_a_look(ctx: Context) -> None:
    _serve()
    data = await get_adapter("pangolin").fetch("sites", CONFIG, {"only_offline": True}, ctx)
    assert [item["title"] for item in data.items] == ["Cabin", "New site"]


@respx.mock
async def test_public_resources_carry_their_health(ctx: Context) -> None:
    routes = _serve()
    data = await get_adapter("pangolin").fetch("resources", CONFIG, {}, ctx)
    assert not routes["private"].called, "only what the card shows is asked for"
    assert [(item["title"], item["subtitle"], item["value"], item["status"]) for item in data.items] == [
        ("Weather station", "weather.example.com · Cabin", "Unhealthy", "bad"),
        ("Jellyfin", "media.example.com · Home lab", "Healthy", "ok"),
        ("Minecraft", "port 25565", "Disabled", "unknown"),
    ]


@respx.mock
async def test_private_resources_are_away_with_their_site(ctx: Context) -> None:
    _serve()
    data = await get_adapter("pangolin").fetch("resources", CONFIG, {"show": "private"}, ctx)
    assert [(item["title"], item["value"], item["status"]) for item in data.items] == [("Cabin camera", "Offline", "bad"), ("NAS shares", "Private", "ok")]
    both = await get_adapter("pangolin").fetch("resources", CONFIG, {"show": "both", "only_problems": True}, Context(httpx.AsyncClient(), cache={}))
    assert [item["title"] for item in both.items] == ["Cabin camera", "Weather station"]


@respx.mock
async def test_an_older_resource_names_its_site_itself_and_has_only_target_health(ctx: Context) -> None:
    older = [{"resourceId": 9, "name": "Wiki", "fullDomain": "wiki.example.com", "enabled": True, "siteName": "Home lab",
              "targets": [{"enabled": True, "healthStatus": "healthy"}, {"enabled": True, "healthStatus": "unhealthy"}]}]
    respx.get(f"{URL}/v1/org/home/resources").mock(return_value=httpx.Response(200, json=_page("resources", older)))
    data = await get_adapter("pangolin").fetch("resources", CONFIG, {}, ctx)
    assert data.items == [{"title": "Wiki", "subtitle": "wiki.example.com · Home lab", "value": "Unhealthy", "status": "bad"}]


@respx.mock
async def test_status_adds_it_up(ctx: Context) -> None:
    _serve()
    data = await get_adapter("pangolin").fetch("status", CONFIG, {}, ctx)
    assert data.status == "bad"
    assert data.primary == {"label": "Sites online", "value": "2/4"}
    assert data.secondary == [
        {"label": "Offline", "value": 1},
        {"label": "Public resources", "value": 3},
        {"label": "Private resources", "value": 2},
        {"label": "Unhealthy", "value": 1},
    ]


@respx.mock
async def test_every_page_is_read(ctx: Context) -> None:
    first = [{"siteId": n, "name": f"Site {n:03}", "type": "newt", "online": True} for n in range(200)]
    second = [{"siteId": 200, "name": "Site 200", "type": "newt", "online": False}]

    def answer(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(200, json=_page("sites", first if page == 1 else second, total=201, page=page))

    route = respx.get(f"{URL}/v1/org/home/sites").mock(side_effect=answer)
    data = await get_adapter("pangolin").fetch("sites", CONFIG, {"only_offline": True}, ctx)
    assert route.call_count == 2
    assert [item["title"] for item in data.items] == ["Site 200"]


@respx.mock
async def test_a_url_with_v1_is_taken_as_well(ctx: Context) -> None:
    route = respx.get(f"{URL}/v1/org/home/sites").mock(return_value=httpx.Response(200, json=_page("sites", [])))
    await get_adapter("pangolin").fetch("sites", {**CONFIG, "url": f"{URL}/v1"}, {}, ctx)
    assert route.called


@respx.mock
async def test_the_connection_test_asks_all_three_lists(ctx: Context) -> None:
    _serve()
    message = await get_adapter("pangolin").test(CONFIG, ctx)
    assert message == "Pangolin answers with 4 sites, 3 public and 2 private resources."


@respx.mock
async def test_a_missing_permission_is_named(ctx: Context) -> None:
    respx.get(f"{URL}/v1/org/home/sites").mock(return_value=httpx.Response(200, json=_page("sites", SITES)))
    respx.get(f"{URL}/v1/org/home/resources").mock(return_value=_refusal(403, "Key does not have permission perform this action"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pangolin").test(CONFIG, ctx)
    assert "List Resources" in failure.value.message
    assert "Key does not have permission perform this action" in failure.value.message


@respx.mock
async def test_a_key_of_another_organization_is_told_so(ctx: Context) -> None:
    respx.get(f"{URL}/v1/org/home/sites").mock(return_value=_refusal(403, "Key does not have access to this organization"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pangolin").fetch("sites", CONFIG, {}, ctx)
    assert failure.value.message == "The key does not belong to the organization home."


@respx.mock
async def test_a_wrong_key_is_refused(ctx: Context) -> None:
    respx.get(f"{URL}/v1/org/home/sites").mock(return_value=_refusal(401, "Invalid API key"))
    with pytest.raises(AuthFailed) as failure:
        await get_adapter("pangolin").fetch("sites", CONFIG, {}, ctx)
    assert "Invalid API key" in failure.value.message


@respx.mock
async def test_no_integration_api_is_explained(ctx: Context) -> None:
    respx.get(f"{URL}/v1/org/home/sites").mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pangolin").fetch("sites", CONFIG, {}, ctx)
    assert "enable_integration_api" in failure.value.hint


@respx.mock
async def test_the_dashboard_instead_of_the_api_is_not_taken_for_an_empty_list(ctx: Context) -> None:
    respx.get(f"{URL}/v1/org/home/sites").mock(return_value=httpx.Response(200, text="<!doctype html><html></html>"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("pangolin").fetch("sites", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"


def test_the_demo_draws_every_card() -> None:
    pangolin = get_adapter("pangolin")
    assert pangolin.demo("status", {}, 0).secondary[1] == {"label": "Public resources", "value": 5}
    assert len(pangolin.demo("sites", {}, 0).items) == 4
    assert len(pangolin.demo("resources", {"show": "both"}, 0).items) == 7
