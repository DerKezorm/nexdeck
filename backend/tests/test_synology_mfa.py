"""Tests for Synology trusted-device authentication."""

from unittest.mock import AsyncMock

import pytest

from app.adapters.synology import SynologyAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize("device_id", [None, "test-device-token"])
async def test_synology_login(device_id):
    class Response:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"sid": "test-sid"}}

    class Context:
        cache = {}

    ctx = Context()
    ctx.request = AsyncMock(return_value=Response())

    config = {
        "url": "https://nas.example:5001",
        "username": "testuser",
        "password": "testpassword",
        "insecure": True,
    }

    if device_id:
        config["device_id"] = device_id

    sid = await SynologyAdapter()._sid(config, ctx)

    assert sid == "test-sid"

    request = ctx.request.call_args
    assert request.args[0] == "POST"

    data = request.kwargs["data"]
    assert data["account"] == "testuser"
    assert data["passwd"] == "testpassword"
    assert data.get("device_id") == device_id

    if device_id:
        assert data["device_name"] == "NexDeck"
    else:
        assert "device_name" not in data
