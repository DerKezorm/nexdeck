"""LubeLogger, against the answers of a live LubeLogger 1.7.4 (28.10.2026).

Two invented vehicles with an odometer reading each and four reminders.
Addresses and passwords are made up; the shapes are the measured ones: the
numbers as strings, the date in the server's locale, "0" for what does not
apply, and the 401 with Basic that every route gives once authentication is on.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

LL = "http://lubelogger.example.com:8080"
CONFIG = {"url": LL, "username": "admin", "password": "password-for-the-cards"}
ADAPTER = get_adapter("lubelogger")

WAGON = {"id": 1, "year": 2019, "make": "Example", "model": "Wagon", "licensePlate": "EX-123", "vehicleIdentifier": "LicensePlate"}
HATCH = {"id": 2, "year": 2012, "make": "Example", "model": "Hatch", "licensePlate": "EX-456", "vehicleIdentifier": "LicensePlate"}


def reminder(vehicle: str, identifier: str, description: str, urgency: str, metric: str, days: str, distance: str) -> dict[str, Any]:
    return {"vehicleId": vehicle, "id": identifier, "description": description, "urgency": urgency, "metric": metric,
            "userMetric": metric, "notes": None, "dueDate": "11/02/2026", "dueOdometer": "0", "dueDays": days,
            "dueDistance": distance, "tags": ""}


#: In the order the live server answered, which is not the order of urgency.
REMINDERS = [
    reminder("1", "1", "Oil change", "VeryUrgent", "Date", "4", "500"),
    reminder("1", "2", "Tyre swap", "PastDue", "Date", "-3", "0"),
    reminder("2", "3", "Inspection", "NotUrgent", "Date", "199", "0"),
    reminder("2", "4", "Timing belt", "NotUrgent", "Odometer", "0", "9000"),
]


def info(vehicle: dict[str, Any], odometer: int, **counts: int) -> dict[str, Any]:
    return {"vehicleData": vehicle, "veryUrgentReminderCount": 0, "urgentReminderCount": 0, "notUrgentReminderCount": 0,
            "pastDueReminderCount": 0, "lastReportedOdometer": odometer, "serviceRecordCount": 0, **counts}


INFO = [info(WAGON, 84500, veryUrgentReminderCount=1, pastDueReminderCount=1), info(HATCH, 131000, notUrgentReminderCount=2)]


def server(*, reminders: list[dict[str, Any]] | None = None) -> list[httpx.Request]:
    """A fake LubeLogger with authentication on, and the requests it saw."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        wanted = {"authorization": "Basic YWRtaW46cGFzc3dvcmQtZm9yLXRoZS1jYXJkcw=="}
        if request.headers.get("authorization") != wanted["authorization"] and request.headers.get("x-api-key") != "key-for-the-cards":
            return httpx.Response(401, headers={"WWW-Authenticate": "Basic"})
        routes: dict[str, Any] = {
            "/api/version": {"currentVersion": "1.7.4", "latestVersion": "1.7.4"},
            "/api/vehicles": [WAGON, HATCH],
            "/api/vehicle/info": INFO,
            "/api/vehicle/reminders/all": REMINDERS if reminders is None else reminders,
        }
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404, text="Not Found")

    respx.get(url__startswith=LL).mock(side_effect=answer)
    return seen


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_connection_test_names_the_version_and_counts_the_vehicles(ctx: Context) -> None:
    server()
    assert await ADAPTER.test(CONFIG, ctx) == "LubeLogger 1.7.4 answers with 2 vehicles."


@respx.mock
async def test_the_overview_adds_up_the_reminders_that_are_due_and_turns_red_for_a_past_one(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    # One past due and one very urgent; the two not urgent ones are not due.
    assert card.primary == {"label": "Due", "value": 2}
    assert card.secondary == [
        {"label": "Past due", "value": 1, "part": "past"},
        {"label": "Vehicles", "value": 2, "part": "vehicles"},
        {"label": "Not yet due", "value": 2, "part": "later"},
    ]
    assert card.status == "bad" and card.metrics == {"due": 2.0}


@respx.mock
async def test_the_reminders_come_most_urgent_first_with_days_or_distance_and_the_vehicle(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("reminders", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("Tyre swap", "2019 Example Wagon", "-3 d", "bad"),
        ("Oil change", "2019 Example Wagon", "4 d", "warn"),
        ("Inspection", "2012 Example Hatch", "199 d", "ok"),
        # ⚠️ By odometer the days are "0", which must not sort this one first.
        ("Timing belt", "2012 Example Hatch", "9000", "ok"),
    ]
    assert card.status == "bad"


@respx.mock
async def test_only_the_reminders_due_soon_can_be_asked_for(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("reminders", CONFIG, {"urgent": True, "limit": 5}, ctx)
    assert [row["title"] for row in card.items] == ["Tyre swap", "Oil change"]
    ctx.cache.clear()
    server(reminders=[])
    card = await ADAPTER.fetch("reminders", CONFIG, {"urgent": True}, ctx)
    assert card.items == [] and card.status == "ok"


@respx.mock
async def test_the_garage_shows_each_vehicle_with_its_odometer_and_its_worst_reminder(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("garage", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["value"], row["status"]) for row in card.items] == [
        ("2019 Example Wagon", "EX-123", "84500", "bad"), ("2012 Example Hatch", "EX-456", "131000", "ok")]


@respx.mock
async def test_without_credentials_nothing_is_sent_and_with_a_key_it_goes_in_the_header(ctx: Context) -> None:
    seen = server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("garage", {"url": LL}, {}, ctx)
    assert "authorization" not in seen[0].headers and "x-api-key" not in seen[0].headers
    ctx.cache.clear()
    await ADAPTER.fetch("garage", {"url": LL, "api_key": "key-for-the-cards"}, {}, ctx)
    assert seen[-1].headers["x-api-key"] == "key-for-the-cards" and "authorization" not in seen[-1].headers
    assert seen[-1].headers["culture-invariant"] == "true"


@respx.mock
async def test_a_wrong_password_is_an_authentication_failure(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("summary", {**CONFIG, "password": "wrong"}, {}, ctx)


@respx.mock
async def test_an_unreachable_service_is_reported_as_such(ctx: Context) -> None:
    respx.get(url__startswith=LL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)


@respx.mock
async def test_another_service_behind_the_address_is_named(ctx: Context) -> None:
    respx.get(url__startswith=LL).mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("garage", CONFIG, {}, ctx)
    assert caught.value.code == "not_lubelogger"


def test_the_demo_has_a_card_for_every_widget() -> None:
    for widget in ADAPTER.widgets:
        data: Any = ADAPTER.demo(widget.kind, {}, 3)
        assert data.primary or data.items
