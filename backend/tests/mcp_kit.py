"""What the MCP tests share: switching it on, making keys, speaking JSON-RPC, a card with buttons."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import WidgetData
from app.services import mcp
from app.services.collector import collector
from app.services.state import live

from .conftest import CSRF


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No brake left over from another test, and a press does not refetch the card behind the test's back."""
    mcp.forget_calls()

    async def _no_refresh(_widget_id: int) -> None:
        return None

    monkeypatch.setattr(collector, "refresh", _no_refresh)


def switch(client: TestClient, *, allowed: bool = True, max_level: str = "act", oauth_allowed: bool = False,
           blocked_tools: list[str] | None = None) -> dict:
    answer = client.put("/api/v1/mcp/admin", json={"allowed": allowed, "max_level": max_level, "oauth_allowed": oauth_allowed,
                                                    "blocked_tools": blocked_tools or []}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    return answer.json()


def make_key(client: TestClient, level: str = "read", *, name: str = "Claude", boards: list[int] | None = None,
             expires_days: int | None = None, rights: dict[str, str] | None = None) -> tuple[dict, str]:
    answer = client.post("/api/v1/mcp/keys", json={"name": name, "level": level, "boards": boards, "expires_days": expires_days},
                         headers=CSRF)
    assert answer.status_code == 201, answer.text
    made = answer.json()
    if rights:
        set_to = client.put(f"/api/v1/mcp/keys/{made['key']['id']}/rights", json={"tool_rights": rights}, headers=CSRF)
        assert set_to.status_code == 200, set_to.text
    return made["key"], made["token"]


def rpc(client: TestClient, token: str | None, method: str, params: dict | None = None, *, number: int | None = 1,
        headers: dict[str, str] | None = None):  # noqa: ANN201 - a response
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    if number is not None:
        message["id"] = number
    sent = dict(headers or {})
    if token is not None:
        sent["Authorization"] = f"Bearer {token}"
    return client.post("/api/mcp", content=json.dumps(message), headers={"Content-Type": "application/json", **sent})


def names(client: TestClient, token: str) -> list[str]:
    answer = rpc(client, token, "tools/list")
    assert answer.status_code == 200, answer.text
    return [tool["name"] for tool in answer.json()["result"]["tools"]]


def call(client: TestClient, token: str, tool: str, **arguments: Any) -> dict:
    """``{"error": bool, "value": ...}``: the tool's answer, parsed."""
    answer = rpc(client, token, "tools/call", {"name": tool, "arguments": arguments})
    assert answer.status_code == 200, answer.text
    result = answer.json()["result"]
    text = result["content"][0]["text"]
    try:
        value = json.loads(text)
    except ValueError:
        value = text
    return {"error": result["isError"], "value": value}


def board(client: TestClient, name: str = "Lab") -> dict:
    answer = client.post("/api/v1/boards", json={"name": name}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def docker_card(client: TestClient, page_id: int, title: str = "Host") -> dict:
    """A Docker card in the demo, offering a harmless Restart and a dangerous Stop for one container."""
    made = client.post("/api/v1/integrations", json={"kind": "docker", "name": f"Docker {title}", "config": {}, "demo": True}, headers=CSRF)
    assert made.status_code == 201, made.text
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "docker.containers", "title": title,
                                                                    "integration_id": made.json()["id"]}, headers=CSRF)
    assert answer.status_code == 201, answer.text
    widget = answer.json()["widget"]
    collector.unschedule(widget["id"])
    offer(widget["id"])
    return widget


def offer(widget_id: int, *, restart: bool = True) -> None:
    actions = [{"id": "stop", "label": "Stop", "danger": True, "params": {"id": "c1"}}]
    if restart:
        actions.insert(0, {"id": "restart", "label": "Restart", "params": {"id": "c1"}})
    live.set(widget_id, WidgetData(status="warn", meta={"status_reason": "plex is slow"}, items=[
        {"id": "c1", "title": "plex", "subtitle": "Up 3 days", "state": "running", "actions": actions},
    ]))
