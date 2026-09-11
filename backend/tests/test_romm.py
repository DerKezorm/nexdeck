"""RomM, against the answers of a live RomM 5.2.0 (11.09.2026)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

RM = "http://romm.example.com"
CONFIG = {"url": RM, "token": "made-up-token"}


def platform(identifier: int, slug: str, name: str, roms: int, size: int) -> dict[str, Any]:
    return {"id": identifier, "slug": slug, "fs_slug": slug, "name": name, "display_name": name, "custom_name": "", "rom_count": roms,
            "fs_size_bytes": size, "created_at": "2026-09-11T12:56:53+00:00", "is_identified": True, "missing_from_fs": False, "firmware": []}


def rom(identifier: int, name: str, file: str, platform_name: str, created: str) -> dict[str, Any]:
    return {"id": identifier, "name": name, "fs_name": file, "platform_id": 1, "platform_display_name": platform_name, "platform_custom_name": None,
            "created_at": created, "updated_at": created, "fs_size_bytes": 4096, "is_identified": False, "missing_from_fs": False}


#: Measured: in the order RomM listed them, which is not by size.
PLATFORMS = [platform(1, "gba", "Game Boy Advance", 2, 8192), platform(2, "n64", "Nintendo 64", 1, 16384),
             platform(3, "snes", "Super Nintendo Entertainment System", 1, 8192)]
STATS = {"PLATFORMS": 3, "ROMS": 4, "SAVES": 0, "STATES": 0, "SCREENSHOTS": 0, "TOTAL_FILESIZE_BYTES": 32768}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_platforms_the_biggest_first(ctx: Context) -> None:
    route = respx.get(f"{RM}/api/platforms").mock(return_value=httpx.Response(200, json=[*PLATFORMS[1:], PLATFORMS[0]]))
    data = await get_adapter("romm").fetch("platforms", CONFIG, {"limit": 10}, ctx)
    assert route.calls.last.request.headers["Authorization"] == "Bearer made-up-token"
    assert [(row["title"], row["subtitle"], row["value"]) for row in data.items] == [
        ("Game Boy Advance", "8.0 KB", "2"), ("Nintendo 64", "16.0 KB", "1"), ("Super Nintendo Entertainment System", "8.0 KB", "1")]
    assert data.secondary == [{"label": "Games", "value": 4}]


@respx.mock
async def test_a_custom_platform_name_wins(ctx: Context) -> None:
    respx.get(f"{RM}/api/platforms").mock(return_value=httpx.Response(200, json=[{**PLATFORMS[2], "custom_name": "SNES"}]))
    data = await get_adapter("romm").fetch("platforms", CONFIG, {}, ctx)
    assert data.items[0]["title"] == "SNES"


@respx.mock
async def test_the_games_added_last(ctx: Context) -> None:
    route = respx.get(f"{RM}/api/roms").mock(return_value=httpx.Response(200, json={
        "items": [rom(2, "Tiny Knight", "Tiny Knight (USA).gba", "Game Boy Advance", "2026-09-11T12:56:54+00:00"),
                  rom(3, "", "Kart Rally (Europe).z64", "Nintendo 64", "2026-09-11T12:56:54+00:00")],
        "total": 4, "limit": 2, "offset": 0}))
    data = await get_adapter("romm").fetch("recent", CONFIG, {"limit": 2}, ctx)
    assert dict(route.calls.last.request.url.params) == {"order_by": "created_at", "order_dir": "desc", "limit": "2"}
    assert [(row["title"], row["subtitle"]) for row in data.items] == [("Tiny Knight", "Game Boy Advance"), ("Kart Rally (Europe).z64", "Nintendo 64")]
    assert all(row["value"] for row in data.items)


@respx.mock
async def test_the_summary(ctx: Context) -> None:
    respx.get(f"{RM}/api/stats").mock(return_value=httpx.Response(200, json=STATS))
    data = await get_adapter("romm").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Games", "value": 4}
    assert data.secondary == [{"label": "Platforms", "value": 3}, {"label": "Size", "value": "32.0 KB"}]
    assert data.metrics == {"games": 4.0}
    respx.get(f"{RM}/api/stats").mock(return_value=httpx.Response(200, json={**STATS, "SAVES": 12}))
    saved = await get_adapter("romm").fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
    assert saved.secondary[-1] == {"label": "Saves", "value": 12}


@respx.mock
async def test_the_three_ways_romm_refuses(ctx: Context) -> None:
    for status, expected in ((401, AuthFailed), (403, AuthFailed), (500, AdapterError)):
        respx.get(f"{RM}/api/platforms").mock(return_value=httpx.Response(status, text="Internal Server Error" if status == 500 else '{"detail": "Forbidden"}'))
        with pytest.raises(expected) as refused:
            await get_adapter("romm").fetch("platforms", CONFIG, {}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))
        if status == 403:
            assert "roms.read and platforms.read" in refused.value.message
        if status == 500:
            # ⚠️ Measured: this is what a token RomM does not know gets.
            assert "token" in refused.value.message and not isinstance(refused.value, AuthFailed)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{RM}/api/heartbeat").mock(return_value=httpx.Response(200, json={"SYSTEM": {"VERSION": "5.2.0", "SHOW_SETUP_WIZARD": False},
                                                                                 "FILESYSTEM": {"FS_PLATFORMS": ["gba", "n64", "snes"]}}))
    respx.get(f"{RM}/api/platforms").mock(return_value=httpx.Response(200, json=PLATFORMS))
    assert await get_adapter("romm").test(CONFIG, ctx) == "RomM 5.2.0 answers with 3 platforms."
