"""Synology MFA enrolment tests."""

from unittest.mock import AsyncMock

import pytest

from app.adapters.synology import SynologyAdapter
from app.adapters.base import AdapterError, AuthFailed


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Context:
    def __init__(self, payload):
        self.cache = {}
        self.request = AsyncMock(
            return_value=Response(payload)
        )


CONFIG = {
    "url": "https://nas.example:5001",
    "username": "testuser",
    "password": "testpassword",
    "insecure": True,
}


@pytest.mark.asyncio
async def test_enrolment_success():
    ctx = Context({
        "success": True,
        "data": {"sid": "session", "did": "trusted-device"},
    })

    result = await SynologyAdapter().enrol_mfa(
        CONFIG, ctx, "123456"
    )

    assert result == "trusted-device"
    data = ctx.request.call_args_list[0].kwargs["data"]
    assert data["otp_code"] == "123456"
    assert data["enable_device_token"] == "yes"

    assert ctx.request.await_count == 2
    logout = ctx.request.call_args_list[1].kwargs["data"]
    assert logout["method"] == "logout"
    assert logout["_sid"] == "session"
    assert logout["session"] == "nexdeck"


@pytest.mark.asyncio
async def test_enrolment_bad_otp():
    ctx = Context({
        "success": False,
        "error": {"code": 404},
    })

    with pytest.raises(AuthFailed):
        await SynologyAdapter().enrol_mfa(
            CONFIG, ctx, "123456"
        )


@pytest.mark.asyncio
async def test_enrolment_missing_device():
    ctx = Context({
        "success": True,
        "data": {"sid": "session"},
    })

    with pytest.raises(AdapterError):
        await SynologyAdapter().enrol_mfa(
            CONFIG, ctx, "123456"
        )
