"""Open WebUI, against the answers of a live Open WebUI 0.11.3 (11.09.2026)."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.openwebui import OpenWebUIAdapter

OW = "http://openwebui.example.com:8080"
CONFIG = {"url": OW, "api_key": "sk-made-up-key"}
NOW = 1789160100.0
ADMIN_ID = "00000000-0000-4000-8000-000000000001"


def account(number: int, name: str, role: str, seconds_ago: float, now: float = NOW) -> dict[str, Any]:
    """A row of ``/api/v1/users/`` as measured, with made-up ids and names."""
    return {"id": f"00000000-0000-4000-8000-00000000000{number}", "email": f"{name.split()[0].lower()}@example.com", "username": None, "role": role,
            "name": name, "profile_image_url": "/user.png", "profile_banner_image_url": None, "bio": None, "gender": None, "date_of_birth": None,
            "timezone": None, "presence_state": None, "status_emoji": None, "status_message": None, "status_expires_at": None, "info": None,
            "settings": None, "oauth": None, "scim": None, "last_active_at": int(now - seconds_ago), "updated_at": int(now - 900),
            "created_at": int(now - 900), "group_ids": []}


def accounts(now: float = NOW) -> list[dict[str, Any]]:
    # Newest activity first, as asked for; the admin is the key's own user and was active a moment ago because of it.
    return [account(1, "Admin", "admin", 4, now), account(2, "Robin Example", "user", 74, now),
            account(3, "Sam Example", "pending", 441, now), account(4, "Kim Example", "user", 2 * 86400, now)]


def everyone(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``/api/v1/users/all``: no last_active_at in it."""
    keep = ("status_emoji", "status_message", "status_expires_at", "id", "name", "email", "role", "bio")
    return {"users": [{**{key: row[key] for key in keep}, "groups": [], "is_active": False} for row in rows], "total": len(rows)}


ME = {"id": ADMIN_ID, "name": "Admin", "role": "admin", "email": "admin@example.com", "profile_image_url": "/user.png",
      "token": "sk-made-up-key", "token_type": "Bearer", "expires_at": None, "permissions": {}}

#: ``/api/models``: an Ollama model loaded, one made up in the same shape and not loaded,
#: one over an OpenAI-compatible connection with a prefix, and the arena.
MODELS = {"data": [
    {"id": "remote.smollm2:135m", "object": "model", "created": 1789158071, "owned_by": "openai", "connection_type": "external", "name": "remote.smollm2:135m",
     "openai": {"id": "remote.smollm2:135m", "object": "model", "created": 1789158071, "owned_by": "library", "connection_type": "external"},
     "provider": "", "urlIdx": 0, "actions": [], "filters": [], "tags": []},
    {"id": "smollm2:135m", "name": "smollm2:135m", "object": "model", "created": 0, "owned_by": "ollama",
     "ollama": {"name": "smollm2:135m", "model": "smollm2:135m", "size": 270898672,
                "details": {"parent_model": "", "format": "gguf", "family": "llama", "families": ["llama"], "parameter_size": "134.52M", "quantization_level": "F16"},
                "expires_at": 1789160626, "connection_type": "local", "urls": [0]},
     "loaded": True, "connection_type": "local", "tags": [], "actions": [], "filters": []},
    {"id": "qwen2.5:0.5b", "name": "qwen2.5:0.5b", "object": "model", "created": 0, "owned_by": "ollama",
     "ollama": {"name": "qwen2.5:0.5b", "model": "qwen2.5:0.5b", "size": 397821319,
                "details": {"parent_model": "", "format": "gguf", "family": "qwen2", "families": ["qwen2"], "parameter_size": "494.03M", "quantization_level": "Q4_K_M"},
                "connection_type": "local", "urls": [0]},
     "loaded": False, "connection_type": "local", "tags": [], "actions": [], "filters": []},
    {"id": "arena-model", "name": "Arena Model", "info": {"meta": {"description": "Submit your questions to anonymous AI chatbots and vote on the best response.", "model_ids": None}},
     "object": "model", "created": 0, "owned_by": "arena", "arena": True, "actions": [], "filters": [], "tags": []},
]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _server(now: float) -> respx.Route:
    rows = accounts(now)
    respx.get(f"{OW}/api/v1/auths/").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{OW}/api/v1/users/all").mock(return_value=httpx.Response(200, json=everyone(rows)))
    return respx.get(f"{OW}/api/v1/users/").mock(return_value=httpx.Response(200, json={"users": rows, "total": len(rows)}))


def test_users_waiting_for_approval_first_and_the_keys_own_user_without_a_time() -> None:
    data = OpenWebUIAdapter._users(accounts(), ADMIN_ID, {"limit": 8}, NOW)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("Sam Example", "Waiting for approval", "warn", "7 min"),
        ("Admin", "Administrator · Used by this card", "ok", ""),
        ("Robin Example", "User", "ok", "1 min"),
        ("Kim Example", "User", "ok", "2 d"),
    ]
    assert data.status == "warn" and data.secondary == [{"label": "Pending", "value": 1}]
    calm = OpenWebUIAdapter._users([row for row in accounts() if row["role"] != "pending"], ADMIN_ID, {"limit": 2}, NOW)
    assert calm.status == "ok" and calm.secondary == [] and [row["title"] for row in calm.items] == ["Admin", "Robin Example"]


@respx.mock
async def test_the_users_card_asks_for_the_most_recently_active(ctx: Context) -> None:
    route = _server(time.time())
    data = await get_adapter("openwebui").fetch("users", CONFIG, {"limit": 8}, ctx)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-made-up-key"
    assert dict(request.url.params) == {"order_by": "last_active_at", "direction": "desc", "page": "1"}
    assert [row["title"] for row in data.items] == ["Sam Example", "Admin", "Robin Example", "Kim Example"]


@respx.mock
async def test_the_summary_leaves_the_keys_own_user_out_of_active(ctx: Context) -> None:
    """⚠️ Measured: every request with a key sets its owner's last_active_at to now."""
    _server(time.time())
    data = await get_adapter("openwebui").fetch("summary", CONFIG, {}, ctx)
    assert data.primary == {"label": "Users", "value": 4}
    # Robin 74 s ago counts, Sam 441 s ago does not, and the admin is the card itself.
    assert data.secondary == [{"label": "Active", "value": 1}, {"label": "Pending", "value": 1}]
    assert data.metrics == {"users": 4.0, "active": 1.0} and data.status == "warn"


@respx.mock
async def test_models_loaded_first_with_their_connection(ctx: Context) -> None:
    respx.get(f"{OW}/api/models").mock(return_value=httpx.Response(200, json=MODELS))
    data = await get_adapter("openwebui").fetch("models", CONFIG, {"limit": 10}, ctx)
    assert [(row["title"], row["subtitle"], row["status"], row["value"]) for row in data.items] == [
        ("smollm2:135m", "Loaded · Ollama · 134.52M", "ok", "258.3 MB"),
        ("qwen2.5:0.5b", "Ollama · 494.03M", "unknown", "379.4 MB"),
        ("remote.smollm2:135m", "OpenAI", "unknown", ""),
    ]
    assert data.secondary == [{"label": "Loaded", "value": 1}]
    assert [row["title"] for row in OpenWebUIAdapter._models(MODELS["data"], {"limit": 1}).items] == ["smollm2:135m"]


@respx.mock
async def test_the_three_refusals_are_told_apart(ctx: Context) -> None:
    """⚠️ Measured: a made-up key and a user's key both get 401; only the detail differs."""
    adapter = get_adapter("openwebui")
    route = respx.get(f"{OW}/api/models")
    for status, detail, words in (
        (401, "Your session has expired or the token is invalid. Please sign in again.", "rejected the API key"),
        (401, "You do not have permission to access this resource. Please contact your administrator for assistance.", "API key of an administrator"),
        (403, "Use of API key is not enabled in the environment.", "switched off"),
    ):
        route.mock(return_value=httpx.Response(status, json={"detail": detail}))
        ctx.cache.clear()
        with pytest.raises(AuthFailed) as refused:
            await adapter.fetch("models", CONFIG, {}, ctx)
        assert words in refused.value.message


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{OW}/api/models").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("openwebui").fetch("models", CONFIG, {}, ctx)
    assert failure.value.code == "unreachable"


@respx.mock
async def test_another_service_on_the_address(ctx: Context) -> None:
    respx.get(f"{OW}/api/v1/auths/").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as other:
        await get_adapter("openwebui").fetch("users", CONFIG, {}, ctx)
    assert other.value.code == "not_openwebui"


@respx.mock
async def test_the_connection_test_names_a_key_that_is_not_an_administrators(ctx: Context) -> None:
    respx.get(f"{OW}/api/version").mock(return_value=httpx.Response(200, json={"version": "0.11.3", "deployment_id": ""}))
    me = respx.get(f"{OW}/api/v1/auths/").mock(return_value=httpx.Response(200, json=ME))
    adapter = get_adapter("openwebui")
    assert await adapter.test(CONFIG, ctx) == "Open WebUI 0.11.3 answers for Admin."
    me.mock(return_value=httpx.Response(200, json={**ME, "name": "Robin Example", "role": "user"}))
    assert "not an administrator's" in await adapter.test(CONFIG, ctx)
