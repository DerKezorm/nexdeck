"""Linkwarden, against the answers of a live Linkwarden 2.16.3 (11.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

LW = "http://linkwarden.example.com"
CONFIG = {"url": LW, "token": "made-up-token"}


def collection(identifier: int, name: str, links: int) -> dict[str, Any]:
    return {"id": identifier, "name": name, "description": "", "icon": None, "color": "#0ea5e9", "parentId": None, "isPublic": False,
            "ownerId": 1, "createdById": 1, "createdAt": "2026-09-11T11:08:00.974Z", "_count": {"links": links}, "members": []}


def link(identifier: int, name: str, url: str, where: dict[str, Any], tags: list[str], pinned: bool = False) -> dict[str, Any]:
    return {"id": identifier, "name": name, "type": "url", "description": "", "createdById": 1, "collectionId": where["id"], "url": url,
            "textContent": None, "preview": None, "image": None, "pdf": None, "readable": None, "lastPreserved": None,
            "createdAt": "2026-09-11T11:08:01.668Z", "updatedAt": "2026-09-11T11:08:09.866Z",
            "tags": [{"id": index, "name": tag, "ownerId": 1} for index, tag in enumerate(tags, 1)],
            "collection": {key: where[key] for key in ("id", "name", "ownerId")}, "pinnedBy": [{"id": 1}] if pinned else []}


HOMELAB = collection(1, "Homelab", 2)
#: ⚠️ Measured: made by Linkwarden itself for the link saved without a collection.
UNORGANIZED = collection(2, "Unorganized", 1)
LINKS = [
    link(3, "Net example", "https://example.net/", UNORGANIZED, []),
    link(2, "Example Domain", "https://example.org/", HOMELAB, ["docs", "network", "extra"]),
    link(1, "", "https://example.com/", HOMELAB, ["docs"], pinned=True),
]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_latest_links_with_collection_and_tags(ctx: Context) -> None:
    route = respx.get(f"{LW}/api/v1/links").mock(return_value=httpx.Response(200, json={"response": LINKS}))
    data = await get_adapter("linkwarden").fetch("recent", CONFIG, {"limit": 8}, ctx)
    assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-token"
    assert dict(route.calls.last.request.url.params) == {"sort": "0"}
    assert [(row["title"], row["subtitle"], row["url"]) for row in data.items] == [
        ("Net example", "example.net · Unorganized", "https://example.net/"),
        ("Example Domain", "example.org · Homelab · docs, network", "https://example.org/"),
        # Without a name of its own the host stands in.
        ("example.com", "example.com · Homelab · docs", "https://example.com/"),
    ]
    assert all(row["value"] for row in data.items) and data.meta["empty"] == "No links saved yet."
    await get_adapter("linkwarden").fetch("recent", CONFIG, {"limit": 2, "pinned": True}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert route.calls.last.request.url.params["pinnedOnly"] == "true"


@respx.mock
async def test_the_summary_adds_up_the_collections(ctx: Context) -> None:
    respx.get(f"{LW}/api/v1/collections").mock(return_value=httpx.Response(200, json={"response": [HOMELAB, UNORGANIZED]}))
    respx.get(f"{LW}/api/v2/dashboard").mock(return_value=httpx.Response(200, json={"data": {
        "links": LINKS, "collectionLinks": {}, "numberOfPinnedLinks": 1, "numberOfTags": 2}, "message": "Dashboard data fetched successfully."}))
    data = await get_adapter("linkwarden").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Links", "value": 3}
    assert data.secondary == [{"label": "Collections", "value": 2}, {"label": "Pinned", "value": 1}, {"label": "Tags", "value": 2}]
    assert data.metrics == {"links": 3.0}


@respx.mock
async def test_a_rejected_token_and_something_else(ctx: Context) -> None:
    respx.get(f"{LW}/api/v1/links").mock(return_value=httpx.Response(401, json={"response": "You must be logged in."}))
    with pytest.raises(AuthFailed):
        await get_adapter("linkwarden").fetch("recent", CONFIG, {}, ctx)
    respx.get(f"{LW}/api/v1/collections").mock(return_value=httpx.Response(200, json={"response": "not a list"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("linkwarden").fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert other.value.code == "not_linkwarden"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{LW}/api/v1/collections").mock(return_value=httpx.Response(200, json={"response": [HOMELAB, UNORGANIZED]}))
    respx.get(f"{LW}/api/v1/config").mock(return_value=httpx.Response(200, json={"response": {"DISABLE_REGISTRATION": None, "INSTANCE_VERSION": "v2.16.3"}}))
    assert await get_adapter("linkwarden").test(CONFIG, ctx) == "Linkwarden 2.16.3 answers with 3 links."
