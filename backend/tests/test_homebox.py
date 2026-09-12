"""Homebox, against the answers of a live Homebox v0.26.2 (11.09.2026)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.homebox import HomeboxAdapter, _warranty_rows

HB = "http://homebox.example.com"
CONFIG = {"url": HB, "api_key": "hb_made_up_key"}
TODAY = date(2026, 9, 11)
HEADER = ("HB.import_ref,HB.parent_import_ref,HB.location,HB.tags,HB.asset_id,HB.archived,HB.url,HB.name,HB.quantity,HB.description,"
          "HB.insured,HB.notes,HB.purchase_price,HB.purchase_from,HB.purchase_date,HB.manufacturer,HB.model_number,HB.serial_number,"
          "HB.lifetime_warranty,HB.warranty_expires,HB.warranty_details,HB.sold_to,HB.sold_price,HB.sold_date,HB.sold_notes")
#: As the export hands it out: the locations come first, and they are rows as well.
EXPORT = "\n".join([
    HEADER,
    ",,,,,false,/location/made-up-attic,Attic,1,,false,,0,,,,,,false,,,,0,,",
    ",,Attic,,000-001,false,/item/made-up-drill,Cordless Drill,1,,false,,129.99,,,,,,false,2026-10-01,,,0,,",
    ",,Attic,,000-002,false,/item/made-up-coffee,Coffee Machine,1,,false,,349,,,,,,false,2027-03-30,,,0,,",
    ",,Attic,,000-003,false,/item/made-up-router,Wifi Router,1,,false,,89.5,,,,,,false,2026-09-01,,,0,,",
    ",,Attic,,000-004,false,/item/made-up-shelf,Bookshelf,1,,false,,60,,,,,,false,,,,0,,",
    ",,Attic,,000-005,false,/item/made-up-dishwasher,Dishwasher,1,,false,,499,,,,,,true,,,,0,,",
    ",,Attic,,000-006,false,/item/made-up-batteries,AA Batteries,4,,false,,5,,,,,,false,,,,0,,",
    ",,Attic,,000-007,false,/item/made-up-kettle,Old Kettle,1,,false,,25,,,,,,false,2026-07-01,,,0,,",
]) + "\n"
STATISTICS = {"totalUsers": 1, "totalItems": 6, "totalLocations": 8, "totalTags": 6, "totalItemPrice": 1147.49, "totalWithWarranty": 3}
GROUP = {"id": "made-up-group", "name": "Example Home", "createdAt": "2026-09-11T21:32:44.452292198Z", "updatedAt": "2026-09-11T21:32:44.452292339Z", "currency": "USD"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _rows() -> list[dict[str, str]]:
    return _warranty_rows(EXPORT)


@respx.mock
async def test_the_inventory_in_numbers(ctx: Context) -> None:
    statistics = respx.get(f"{HB}/api/v1/groups/statistics").mock(return_value=httpx.Response(200, json=STATISTICS))
    respx.get(f"{HB}/api/v1/groups").mock(return_value=httpx.Response(200, json=GROUP))
    data = await get_adapter("homebox").fetch("inventory", CONFIG, {}, ctx)
    assert statistics.calls.last.request.headers["Authorization"] == "Bearer hb_made_up_key"
    assert data.primary == {"label": "Things", "value": 6}
    # ⚠️ Measured: the statistics count four batteries at 5.00 as 20.00.
    assert data.secondary == [{"label": "Total value", "value": "1,147.49 USD"}, {"label": "Locations", "value": 8}]
    assert data.metrics == {"items": 6.0}


def test_warranties_that_end_soon_and_those_that_just_ended() -> None:
    data = HomeboxAdapter._warranties(_rows(), TODAY, HB, {})
    assert [(row["title"], row["subtitle"], row["status"], row["value"], row["url"]) for row in data.items] == [
        ("Wifi Router", "Expired · Attic · 2026-09-01", "bad", "", f"{HB}/item/made-up-router"),
        ("Cordless Drill", "Attic · 2026-10-01", "warn", "20 d", f"{HB}/item/made-up-drill"),
    ]
    assert data.secondary == [{"label": "Ending soon", "value": 1}] and data.status == "bad"


def test_a_longer_look_ahead() -> None:
    data = HomeboxAdapter._warranties(_rows(), TODAY, HB, {"days": 365})
    assert [(row["title"], row["status"], row["value"]) for row in data.items] == [
        ("Wifi Router", "bad", ""), ("Cordless Drill", "warn", "20 d"), ("Coffee Machine", "ok", "200 d")]
    assert data.secondary == [{"label": "Ending soon", "value": 2}]
    assert len(HomeboxAdapter._warranties(_rows(), TODAY, HB, {"days": 365, "limit": 1}).items) == 1


def test_nothing_ending_is_a_calm_card() -> None:
    data = HomeboxAdapter._warranties(_rows(), date(2026, 12, 1), HB, {"days": 30})
    assert data.items == [] and data.status == "ok" and data.meta["empty"] == "No warranty ends in this time."


def test_the_export_is_read_as_csv() -> None:
    rows = _warranty_rows(HEADER + "\n" + ',,Attic,,000-008,false,/item/made-up-saw,"Saw, with a comma",1,,false,,10,,,,,,false,2026-09-20,,,0,,\n')
    assert [(row["HB.name"], row["HB.warranty_expires"]) for row in rows] == [("Saw, with a comma", "2026-09-20")]
    with pytest.raises(AdapterError) as other:
        _warranty_rows("name,price\nsomething,1\n")
    assert other.value.code == "not_homebox"


def test_a_location_is_not_an_item_even_with_a_date() -> None:
    """Locations are rows of the same export and entities of the same schema; only /item/ rows are things."""
    assert _warranty_rows(HEADER + "\n" + ",,,,,false,/location/made-up-garage,Garage,1,,false,,0,,,,,,false,2026-09-20,,,0,,\n") == []


@respx.mock
async def test_the_warranty_card_reads_the_export(ctx: Context) -> None:
    export = respx.get(f"{HB}/api/v1/entities/export").mock(return_value=httpx.Response(200, text=EXPORT, headers={"Content-Type": "text/csv"}))
    data = await get_adapter("homebox").fetch("warranties", CONFIG, {"days": 3650}, ctx)
    assert export.calls.last.request.headers["Authorization"] == "Bearer hb_made_up_key"
    assert {row["title"] for row in data.items} == {"Wifi Router", "Cordless Drill", "Coffee Machine"}


@respx.mock
async def test_a_rejected_key(ctx: Context) -> None:
    """⚠️ Measured: a made-up key gets 401 "valid authorization token is required"."""
    respx.get(f"{HB}/api/v1/groups/statistics").mock(return_value=httpx.Response(401, json={"error": "valid authorization token is required"}))
    with pytest.raises(AuthFailed):
        await get_adapter("homebox").fetch("inventory", CONFIG, {}, ctx)


@respx.mock
async def test_an_unreachable_server(ctx: Context) -> None:
    respx.get(f"{HB}/api/v1/entities/export").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("homebox").fetch("warranties", CONFIG, {}, ctx)


@respx.mock
async def test_the_connection_test(ctx: Context) -> None:
    respx.get(f"{HB}/api/v1/status").mock(return_value=httpx.Response(200, json={
        "health": True, "title": "Homebox", "build": {"version": "v0.26.2", "commit": "made-up", "buildTime": ""},
        "latest": {"version": "v0.26.3", "date": "2026-06-14 01:57:51 +0000 UTC"}, "demo": False, "allowRegistration": True}))
    respx.get(f"{HB}/api/v1/groups/statistics").mock(return_value=httpx.Response(200, json=STATISTICS))
    assert await get_adapter("homebox").test(CONFIG, ctx) == "Homebox v0.26.2 answers with 6 items."
