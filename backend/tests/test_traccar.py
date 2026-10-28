"""Traccar, against the answers of a live Traccar 6.16.0 (28.10.2026).

Three invented devices, two of which had sent a position through OsmAnd.
Addresses and tokens are made up; the shapes are the measured ones, the
ids that differ between a position and its device included, and the 400 a
broken token gets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

TC = "http://traccar.example.com:8082"
TOKEN = "token-for-the-cards"
CONFIG = {"url": TC, "token": TOKEN}
ADAPTER = get_adapter("traccar")


def device(identifier: int, name: str, status: str, updated: timedelta | None, **fields: Any) -> dict[str, Any]:
    stamp = (datetime.now(UTC) - updated).strftime("%Y-%m-%dT%H:%M:%S.000+00:00") if updated is not None else None
    entry = {"id": identifier, "attributes": {}, "groupId": 0, "calendarId": 0, "name": name, "uniqueId": f"unit-{identifier}",
             "status": status, "lastUpdate": stamp, "positionId": 0, "phone": None, "model": None, "contact": None,
             "category": None, "disabled": False, "expirationTime": None}
    entry.update(fields)
    return entry


def position(identifier: int, device_id: int, battery: float, motion: bool) -> dict[str, Any]:
    return {"id": identifier, "attributes": {"batteryLevel": battery, "distance": 0.0, "totalDistance": 0.0, "motion": motion},
            "deviceId": device_id, "protocol": "osmand", "valid": True, "latitude": 52.5, "longitude": 13.4, "speed": 40.0}


def devices() -> list[dict[str, Any]]:
    # Built when asked, not when the module is read: the ages are relative to now.
    return [
        device(1, "Delivery van", "online", timedelta(seconds=40)),
        device(3, "Old trailer", "offline", None),
        device(2, "Spare bike", "online", timedelta(minutes=5)),
        device(4, "Sold scooter", "offline", timedelta(days=90), disabled=True),
    ]


#: ⚠️ The position's own id (1, 2) is not its device's id (2, 1).
POSITIONS = [position(1, 2, 14.0, False), position(2, 1, 76.0, True)]


def server() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/server":
            return httpx.Response(200, json={"id": 1, "registration": False, "newServer": False, "version": "6.16.0"})
        header = request.headers.get("Authorization")
        # ⚠️ A token that is not one of the server's is a 400 with a stack trace.
        if header is None:
            return httpx.Response(401, text="jakarta.ws.rs.WebApplicationException: HTTP 401 Unauthorized\n\tat org.traccar...")
        if header != f"Bearer {TOKEN}":
            return httpx.Response(400, text="java.lang.ArrayIndexOutOfBoundsException: arraycopy: source index -97\n\tat org.traccar...")
        routes: dict[str, Any] = {"/api/devices": devices(), "/api/positions": POSITIONS}
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404, text="Not Found")

    respx.get(url__startswith=TC).mock(side_effect=answer)


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_devices_that_are_not_disabled(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "Traccar 6.16.0 answers with 3 devices."


@respx.mock
async def test_the_overview_counts_online_offline_and_moving_by_the_device_id(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Online", "value": 2}
    # Only the van (device 1, position 2) moves; the bike's position 1 says no.
    assert card.secondary == [
        {"label": "Offline", "value": 1, "part": "offline"},
        {"label": "Moving", "value": 1, "part": "moving"},
        {"label": "Devices", "value": 3, "part": "total"},
    ]
    assert card.metrics == {"online": 2.0}


@respx.mock
async def test_the_devices_list_the_offline_ones_first_with_battery_and_age(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("devices", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Old trailer", "", "never", "warn"),
        ("Delivery van", "76 %", "0 min", "ok"),
        # A battery under twenty percent is yellow although the bike is online.
        ("Spare bike", "14 %", "5 min", "warn"),
    ]
    # Never the coordinates.
    assert "52.5" not in repr(card.model_dump())


@respx.mock
async def test_only_the_offline_devices_can_be_asked_for(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("devices", CONFIG, {"offline": True}, ctx)
    assert [row["title"] for row in card.items] == ["Old trailer"]


@respx.mock
async def test_a_token_the_server_does_not_know_is_an_authentication_failure_although_it_is_a_400(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "token": "nope"}, {}, ctx)
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "token": ""}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=TC).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("devices", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=TC).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert caught.value.code == "not_traccar"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
