"""Read-only update agent protocol tests."""

from pathlib import Path

import httpx
import pytest

from app.services import update_agent


SOCKET = Path("/tmp/nexdeck-test-agent.sock")
TOKEN = "test-only-agent-token"
DEPLOYMENT = "nexdeck-test"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "deployment_id": DEPLOYMENT,
                "available": True,
                "can_update": True,
            },
            (True, True, "ready"),
        ),
        (
            {
                "deployment_id": "another-deployment",
                "available": True,
                "can_update": True,
            },
            (False, False, "deployment_mismatch"),
        ),
        (
            {
                "deployment_id": DEPLOYMENT,
                "available": False,
                "can_update": True,
            },
            (False, False, "agent_unavailable"),
        ),
        (
            ["invalid", "response"],
            (False, False, "agent_invalid_response"),
        ),
    ],
)
def test_agent_responses(monkeypatch, payload, expected):
    def handler(request):
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.url.path == "/v1/status"
        return httpx.Response(200, json=payload)

    original_transport = httpx.HTTPTransport

    monkeypatch.setattr(
        update_agent.httpx,
        "HTTPTransport",
        lambda **kwargs: httpx.MockTransport(handler),
    )

    result = update_agent.read_agent_status(
        SOCKET, TOKEN, DEPLOYMENT
    )

    assert (
        result["available"],
        result["can_update"],
        result["reason"],
    ) == expected


def test_agent_connection_failure(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("Agent offline")

    monkeypatch.setattr(
        update_agent.httpx,
        "HTTPTransport",
        lambda **kwargs: httpx.MockTransport(handler),
    )

    result = update_agent.read_agent_status(
        SOCKET, TOKEN, DEPLOYMENT
    )

    assert result["available"] is False
    assert result["can_update"] is False
    assert result["reason"] == "agent_unreachable"


@pytest.mark.parametrize(
    "payload",
    [
        {"deployment_id": DEPLOYMENT, "available": True},
        {"deployment_id": DEPLOYMENT, "can_update": True},
        {"deployment_id": DEPLOYMENT, "available": "true", "can_update": True},
        {"deployment_id": DEPLOYMENT, "available": True, "can_update": 1},
    ],
)
def test_malformed_agent_status_fails_closed(monkeypatch, payload):
    def handler(request):
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        update_agent.httpx,
        "HTTPTransport",
        lambda **kwargs: httpx.MockTransport(handler),
    )

    result = update_agent.read_agent_status(SOCKET, TOKEN, DEPLOYMENT)

    assert result["available"] is False
    assert result["can_update"] is False
    assert result["reason"] == "agent_invalid_response"


@pytest.mark.parametrize("status_code", [401, 403])
def test_agent_authentication_failure(monkeypatch, status_code):
    def handler(request):
        return httpx.Response(status_code)

    monkeypatch.setattr(
        update_agent.httpx,
        "HTTPTransport",
        lambda **kwargs: httpx.MockTransport(handler),
    )

    result = update_agent.read_agent_status(SOCKET, TOKEN, DEPLOYMENT)

    assert result["available"] is False
    assert result["can_update"] is False
    assert result["reason"] == "agent_auth_failed"
