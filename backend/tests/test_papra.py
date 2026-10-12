"""Papra (issue #42). The answers are shaped after Papra's own sources
(``documents.routes.ts``, ``organizations.routes.ts``, ``api-keys.routes.ts``,
October 2026) and checked against a fresh instance on 12.10.2026; the names
and numbers are made up."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://papra:1221", "token": "papra-example-key"}
BASE = "http://papra:1221/api"
ORGANIZATIONS = {"organizations": [
    {"id": "org_household", "name": "Household", "createdAt": "2026-01-02T10:00:00.000Z"},
    {"id": "org_business", "name": "Small business", "createdAt": "2026-03-04T10:00:00.000Z"},
]}


def stats(count: int, size: int, deleted: int = 0) -> dict:
    return {"organizationStats": {
        "documentsCount": count, "documentsSize": size,
        "deletedDocumentsCount": deleted, "deletedDocumentsSize": 0,
        "totalDocumentsCount": count + deleted, "totalDocumentsSize": size,
    }}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_documents_card_counts_size_and_trash_of_the_first_organization(ctx: Context) -> None:
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(200, json=ORGANIZATIONS))
    route = respx.get(f"{BASE}/organizations/org_household/documents/statistics").mock(return_value=httpx.Response(200, json=stats(1240, 3 * 1024 ** 3, deleted=4)))
    data = await get_adapter("papra").fetch("library", CONFIG, {}, ctx)
    assert data.primary == {"label": "Documents", "value": 1240}
    assert data.secondary == [{"label": "Size", "value": "3.0 GB"}, {"label": "In the trash", "value": 4}]
    assert data.metrics == {"documents": 1240.0}
    assert route.calls.last.request.headers["Authorization"] == "Bearer papra-example-key"


@respx.mock
async def test_an_empty_trash_is_not_a_badge(ctx: Context) -> None:
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(200, json=ORGANIZATIONS))
    respx.get(f"{BASE}/organizations/org_household/documents/statistics").mock(return_value=httpx.Response(200, json=stats(3, 2048)))
    data = await get_adapter("papra").fetch("library", CONFIG, {}, ctx)
    assert [row["label"] for row in data.secondary] == ["Size"]


@respx.mock
async def test_the_organization_is_found_by_name_or_id(ctx: Context) -> None:
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(200, json=ORGANIZATIONS))
    business = respx.get(f"{BASE}/organizations/org_business/documents/statistics").mock(return_value=httpx.Response(200, json=stats(412, 10)))
    papra = get_adapter("papra")
    for named in ("small BUSINESS ", "org_business"):
        data = await papra.fetch("library", {**CONFIG, "organization": named}, {}, ctx)
        assert data.primary["value"] == 412
    # Both name the same organization, so the second answer is the one remembered.
    assert business.call_count == 1
    with pytest.raises(AdapterError) as failure:
        await papra.fetch("library", {**CONFIG, "organization": "Club"}, {}, ctx)
    assert failure.value.code == "unknown_organization"
    assert "Household, Small business" in (failure.value.hint or "")


@respx.mock
async def test_a_key_without_an_organization_says_so(ctx: Context) -> None:
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(200, json={"organizations": []}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("papra").fetch("library", CONFIG, {}, ctx)
    assert failure.value.code == "no_organization"


@respx.mock
async def test_the_latest_documents_are_newest_first_with_tags_and_a_link(ctx: Context) -> None:
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(200, json=ORGANIZATIONS))
    listed = respx.get(f"{BASE}/organizations/org_household/documents").mock(return_value=httpx.Response(200, json={
        "documents": [
            {"id": "doc_1", "name": "Electricity bill", "originalName": "scan-001.pdf", "createdAt": "2026-10-12T05:00:00.000Z",
             "tags": [{"id": "tag_1", "name": "bills", "color": "#d8ff75"}, {"id": "tag_2", "name": "energy", "color": "#00f"}]},
            {"id": "doc_2", "name": "", "originalName": "warranty.pdf", "createdAt": "2026-10-01T05:00:00.000Z", "tags": []},
        ],
        "documentsCount": 1240,
    }))
    data = await get_adapter("papra").fetch("recent", CONFIG, {"limit": 2}, ctx)
    first, second = data.items
    assert first["title"] == "Electricity bill" and first["subtitle"] == "bills, energy"
    assert first["url"] == "http://papra:1221/organizations/org_household/documents/doc_1"
    # A document without a name of its own is shown by the file it came from.
    assert second["title"] == "warranty.pdf" and second["subtitle"] == ""
    assert data.secondary == [{"label": "Documents", "value": 1240}]
    params = listed.calls.last.request.url.params
    assert (params["sortField"], params["sortOrder"], params["pageSize"], params["pageIndex"]) == ("createdAt", "desc", "2", "0")


@respx.mock
async def test_the_organizations_card_lists_each_with_its_documents(ctx: Context) -> None:
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(200, json=ORGANIZATIONS))
    respx.get(f"{BASE}/organizations/org_household/documents/statistics").mock(return_value=httpx.Response(200, json=stats(1240, 3 * 1024 ** 3)))
    respx.get(f"{BASE}/organizations/org_business/documents/statistics").mock(return_value=httpx.Response(200, json=stats(412, 870 * 1024 ** 2)))
    data = await get_adapter("papra").fetch("organizations", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["subtitle"]) for row in data.items] == [
        ("Household", 1240, "3.0 GB"),
        ("Small business", 412, "870.0 MB"),
    ]
    assert data.items[1]["url"] == "http://papra:1221/organizations/org_business"


@respx.mock
async def test_the_connection_test_names_a_missing_permission(ctx: Context) -> None:
    respx.get(f"{BASE}/api-keys/current").mock(return_value=httpx.Response(200, json={"apiKey": {"id": "ak_1", "name": "nexdeck", "permissions": ["documents:read"]}}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("papra").test(CONFIG, ctx)
    assert failure.value.code == "missing_permission"
    assert "organizations:read" in str(failure.value)


@respx.mock
async def test_the_connection_test_names_the_organization(ctx: Context) -> None:
    respx.get(f"{BASE}/api-keys/current").mock(return_value=httpx.Response(200, json={"apiKey": {"id": "ak_1", "name": "nexdeck", "permissions": ["organizations:read", "documents:read"]}}))
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(200, json=ORGANIZATIONS))
    assert await get_adapter("papra").test(CONFIG, ctx) == "Papra answers, organization Household."


@respx.mock
async def test_a_wrong_key_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(f"{BASE}/organizations").mock(return_value=httpx.Response(401, json={"error": {"message": "Unauthorized"}}))
    with pytest.raises(AuthFailed):
        await get_adapter("papra").fetch("library", CONFIG, {}, ctx)
