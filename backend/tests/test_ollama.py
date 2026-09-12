"""Ollama, against the answers of a live Ollama 0.34.0 (11.09.2026)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

OL = "http://ollama.example.com:11434"
CONFIG = {"url": OL}
DIGEST = "1" * 64

#: ``/api/tags`` as measured, plus a second model made up in the same shape.
TAGS = {"models": [
    {"name": "smollm2:135m", "model": "smollm2:135m", "modified_at": "2026-09-11T20:21:11.530114689Z", "size": 270898672, "digest": DIGEST,
     "details": {"parent_model": "", "format": "gguf", "family": "llama", "families": ["llama"], "parameter_size": "134.52M",
                 "quantization_level": "F16", "context_length": 8192, "embedding_length": 576}, "capabilities": ["completion"]},
    {"name": "qwen2.5:0.5b", "model": "qwen2.5:0.5b", "modified_at": "2026-09-10T08:00:00Z", "size": 397821319, "digest": "0" * 64,
     "details": {"parent_model": "", "format": "gguf", "family": "qwen2", "families": ["qwen2"], "parameter_size": "494.03M",
                 "quantization_level": "Q4_K_M", "context_length": 32768, "embedding_length": 896}, "capabilities": ["completion"]},
]}

#: ``/api/ps`` with the small model loaded on a machine without a GPU. The size is memory, not the file.
PS = {"models": [
    {"name": "smollm2:135m", "model": "smollm2:135m", "size": 382027692, "digest": DIGEST,
     "details": {"parent_model": "", "format": "gguf", "family": "llama", "families": ["llama"], "parameter_size": "134.52M", "quantization_level": "F16"},
     "expires_at": "2026-09-11T20:24:49.925614077Z", "size_vram": 0, "context_length": 4096},
]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _server(ps: dict[str, Any] = PS, tags: dict[str, Any] = TAGS) -> None:
    respx.get(f"{OL}/api/ps").mock(return_value=httpx.Response(200, json=ps))
    respx.get(f"{OL}/api/tags").mock(return_value=httpx.Response(200, json=tags))


@respx.mock
async def test_the_loaded_models_with_the_memory_they_take(ctx: Context) -> None:
    _server()
    data = await get_adapter("ollama").fetch("loaded", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("smollm2:135m", "CPU · 134.52M · F16", "ok", "364.3 MB")]
    unload = data.items[0]["actions"][0]
    assert (unload.id, unload.params, unload.confirm) == ("unload", {"model": "smollm2:135m"}, True)
    assert data.secondary == [{"label": "Memory", "value": "364.3 MB"}] and data.metrics == {"memory_mb": 364.3}
    assert data.meta["actions_visible"] is True


def test_where_a_loaded_model_sits() -> None:
    adapter = get_adapter("ollama")
    rows = adapter._loaded([
        {**PS["models"][0], "name": "a", "model": "a", "size": 100, "size_vram": 100},
        {**PS["models"][0], "name": "b", "model": "b", "size": 80, "size_vram": 30},
    ]).items
    assert [row["subtitle"].split(" · ")[0] for row in rows] == ["GPU", "CPU and GPU"]
    empty = adapter._loaded([])
    assert empty.items == [] and empty.meta["empty"] == "No model is loaded." and empty.metrics == {"memory_mb": 0.0}


@respx.mock
async def test_installed_models_mark_the_loaded_ones(ctx: Context) -> None:
    _server()
    data = await get_adapter("ollama").fetch("installed", CONFIG, {"limit": 10}, ctx)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("qwen2.5:0.5b", "494.03M · Q4_K_M", "unknown", "379.4 MB"),
        ("smollm2:135m", "Loaded · 134.52M · F16", "ok", "258.3 MB"),
    ]
    assert data.secondary == [{"label": "On disk", "value": "637.7 MB"}]
    assert [row["title"] for row in (await get_adapter("ollama").fetch("installed", CONFIG, {"limit": 1}, ctx)).items] == ["qwen2.5:0.5b"]


@respx.mock
async def test_the_summary_counts_loaded_and_installed(ctx: Context) -> None:
    _server()
    data = await get_adapter("ollama").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Loaded", "value": 1}
    assert data.secondary == [{"label": "Installed", "value": 2}, {"label": "Memory", "value": "364.3 MB"}]
    assert data.metrics == {"loaded": 1.0, "memory_mb": 364.3}


@respx.mock
async def test_unloading_a_model(ctx: Context) -> None:
    """⚠️ Measured: no call of its own; a generate without a prompt and with keep_alive 0 unloads."""
    route = respx.post(f"{OL}/api/generate").mock(return_value=httpx.Response(200, json={
        "model": "smollm2:135m", "created_at": "2026-09-11T20:21:39.548711318Z", "response": "", "done": True, "done_reason": "unload"}))
    ctx.cache["resp:stale"] = (1e18, httpx.Response(200, json=PS))
    assert await get_adapter("ollama").action("loaded", "unload", {"model": "smollm2:135m"}, CONFIG, {}, ctx) == "Model unloaded."
    assert json.loads(route.calls.last.request.content) == {"model": "smollm2:135m", "keep_alive": 0}
    # The card must not show the unloaded model again from a remembered answer.
    assert "resp:stale" not in ctx.cache


@respx.mock
async def test_an_unload_that_did_not_happen(ctx: Context) -> None:
    adapter = get_adapter("ollama")
    respx.post(f"{OL}/api/generate").mock(side_effect=[
        httpx.Response(404, json={"error": "model 'gone:1b' not found"}),
        httpx.Response(200, json={"model": "smollm2:135m", "response": "Hello", "done": True, "done_reason": "stop"}),
    ])
    with pytest.raises(AdapterError) as gone:
        await adapter.action("loaded", "unload", {"model": "gone:1b"}, CONFIG, {}, ctx)
    assert gone.value.code == "action_failed" and "no such model" in gone.value.message
    # A 200 that is not an unload is not one either.
    with pytest.raises(AdapterError) as other:
        await adapter.action("loaded", "unload", {"model": "smollm2:135m"}, CONFIG, {}, ctx)
    assert other.value.code == "action_failed" and "did not say" in other.value.message
    with pytest.raises(AdapterError) as unknown:
        await adapter.action("loaded", "delete", {"model": "smollm2:135m"}, CONFIG, {}, ctx)
    assert unknown.value.code == "no_such_action"
    with pytest.raises(AdapterError) as nameless:
        await adapter.action("loaded", "unload", {}, CONFIG, {}, ctx)
    assert nameless.value.code == "missing_param"


@respx.mock
async def test_a_proxy_in_front_that_refuses(ctx: Context) -> None:
    """Ollama itself has none; a made-up token got 200. A refusal comes from in front of it."""
    respx.get(f"{OL}/api/ps").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed) as refused:
        await get_adapter("ollama").fetch("loaded", CONFIG, {}, ctx)
    assert "in front of Ollama" in refused.value.message


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{OL}/api/ps").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("ollama").fetch("summary", CONFIG, {}, ctx)
    assert failure.value.code == "unreachable"


@respx.mock
async def test_another_service_on_the_address(ctx: Context) -> None:
    respx.get(f"{OL}/api/ps").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("ollama").fetch("loaded", CONFIG, {}, ctx)
    assert other.value.code == "not_ollama"


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{OL}/api/version").mock(return_value=httpx.Response(200, json={"version": "0.34.0"}))
    _server()
    assert await get_adapter("ollama").test(CONFIG, ctx) == "Ollama 0.34.0 answers with 2 installed models."
