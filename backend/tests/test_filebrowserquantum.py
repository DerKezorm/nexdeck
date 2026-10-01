"""FileBrowser Quantum, measured against the 1.5 line on 01.10.2026; the
fixture is that instance's answer for its one source."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AuthFailed, Context, outbound_client

SOURCES = json.loads((Path(__file__).parent / "fixtures" / "filebrowserquantum_sources.json").read_text(encoding="utf-8"))
CONFIG = {"url": "http://files:80", "token": "jwt"}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_each_source_is_a_bar_of_its_disk_with_the_files_and_shares(ctx: Context) -> None:
    respx.get("http://files:80/api/settings/sources").mock(return_value=httpx.Response(200, json=SOURCES))
    respx.get("http://files:80/api/share/list").mock(return_value=httpx.Response(200, json=[{"hash": "a"}, {"hash": "b"}]))
    data = await get_adapter("filebrowserquantum").fetch("storage", CONFIG, {}, ctx)
    rows = {row["label"]: row for row in data.secondary}
    assert rows["files"]["unit"] == "%" and rows["files"]["value"] == 0.0
    assert "of 3.9 GB" in rows["files"]["hint"] and "3 files" in rows["files"]["hint"]
    assert rows["Files"]["value"] == 3 and rows["Shares"]["value"] == 2
    assert data.metrics == {"used": 2011136.0} and data.status == "ok"
    assert respx.calls.last.request.headers["Authorization"] == "Bearer jwt"


@respx.mock
async def test_a_token_without_the_share_permission_still_shows_the_storage(ctx: Context) -> None:
    respx.get("http://files:80/api/settings/sources").mock(return_value=httpx.Response(200, json=SOURCES))
    respx.get("http://files:80/api/share/list").mock(return_value=httpx.Response(404, json={"message": "not allowed"}))
    data = await get_adapter("filebrowserquantum").fetch("storage", CONFIG, {}, ctx)
    assert "Shares" not in {row["label"] for row in data.secondary}


@respx.mock
async def test_a_source_still_being_indexed_is_amber(ctx: Context) -> None:
    scanning = {"files": {**SOURCES["files"], "status": "indexing", "used": 0}}
    respx.get("http://files:80/api/settings/sources").mock(return_value=httpx.Response(200, json=scanning))
    respx.get("http://files:80/api/share/list").mock(return_value=httpx.Response(200, json=[]))
    data = await get_adapter("filebrowserquantum").fetch("storage", CONFIG, {}, ctx)
    assert data.status == "warn" and data.meta["status_reason"]


@respx.mock
async def test_a_wrong_token_is_refused_even_after_a_good_one_set_its_cookie(ctx: Context) -> None:
    """FileBrowser sets a session cookie on every good request; nexdeck's client keeps none."""
    route = respx.get("http://files:80/api/settings/sources")
    route.side_effect = [
        httpx.Response(200, json=SOURCES, headers={"Set-Cookie": "filebrowser_quantum_jwt=good; Path=/"}),
        httpx.Response(401, json={"message": "invalid token"}),
    ]
    respx.get("http://files:80/api/share/list").mock(return_value=httpx.Response(200, json=[]))
    adapter = get_adapter("filebrowserquantum")
    await adapter.fetch("storage", CONFIG, {}, ctx)
    ctx.cache.clear()
    with pytest.raises(AuthFailed):
        await adapter.fetch("storage", {**CONFIG, "token": "wrong"}, {}, ctx)
    assert "cookie" not in {key.lower() for key in route.calls.last.request.headers}
