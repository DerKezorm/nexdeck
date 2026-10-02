"""Homebox, against the answers of a live Homebox v0.26.2 (11.09.2026)."""

from __future__ import annotations

from datetime import UTC, date, datetime

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


@pytest.fixture
def on_the_measured_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card reads the day from the clock, and the router's warranty ended on 01.09.2026: from 01.10.2026
    on it was more than 30 days ago and left the card, which turned two tests red. They now stand on TODAY."""
    from app.adapters import homebox

    class Measured(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=tz or UTC)

    monkeypatch.setattr(homebox, "datetime", Measured)


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
    assert data.secondary == [{"label": "Total value", "value": "1,147.49 USD", "part": "value"},
                              {"label": "Locations", "value": 8, "part": "locations"}]
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
async def test_the_warranty_card_reads_the_export(ctx: Context, on_the_measured_day: None) -> None:
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


# -- measured again on 26.09.2026, v0.26.2 and v0.25.0 side by side ----------

ACCOUNT = {"url": HB, "username": "tester@example.com", "password": "a-password-for-the-cards"}
TOKEN = {"token": "Bearer made-up-session-token", "expiresAt": "2026-10-03T21:39:38.427325409Z", "attachmentToken": "made-up"}
PLACES = [{"id": "a", "name": "Garage", "total": 134}, {"id": "b", "name": "Office", "total": 1199}, {"id": "c", "name": "Kitchen", "total": 349.9}]
TAGS = [{"id": "d", "name": "Tools", "total": 129}, {"id": "e", "name": "Kitchen", "total": 349.9}, {"id": "f", "name": "Electronics", "total": 1682.9}]


@respx.mock
async def test_without_a_key_the_account_signs_in_once(ctx: Context) -> None:
    """⚠️ Homebox 0.25 has no API keys; its token already says Bearer."""
    login = respx.post(f"{HB}/api/v1/users/login").mock(return_value=httpx.Response(200, json=TOKEN))
    statistics = respx.get(f"{HB}/api/v1/groups/statistics").mock(return_value=httpx.Response(200, json=STATISTICS))
    respx.get(f"{HB}/api/v1/groups").mock(return_value=httpx.Response(200, json=GROUP))
    await get_adapter("homebox").fetch("inventory", ACCOUNT, {}, ctx)
    await get_adapter("homebox").fetch("inventory", ACCOUNT, {}, ctx)
    assert login.call_count == 1
    assert statistics.calls.last.request.headers["Authorization"] == "Bearer made-up-session-token"
    import json
    assert json.loads(login.calls.last.request.content) == {"username": "tester@example.com", "password": "a-password-for-the-cards", "stayLoggedIn": False}


@respx.mock
async def test_a_token_let_go_early_is_replaced_once(ctx: Context) -> None:
    login = respx.post(f"{HB}/api/v1/users/login").mock(side_effect=[httpx.Response(200, json=TOKEN),
                                                                     httpx.Response(200, json={**TOKEN, "token": "Bearer a-new-one"})])
    respx.get(f"{HB}/api/v1/groups/statistics").mock(side_effect=[httpx.Response(401, json={"error": "unauthorized"}),
                                                                  httpx.Response(200, json=STATISTICS)])
    data = await get_adapter("homebox").fetch("inventory", ACCOUNT, {"currency": "EUR"}, ctx)
    assert data.primary == {"label": "Things", "value": 6} and login.call_count == 2


@respx.mock
async def test_a_wrong_password_and_a_key_on_an_old_homebox(ctx: Context) -> None:
    respx.post(f"{HB}/api/v1/users/login").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(AuthFailed, match="e-mail or the password"):
        await get_adapter("homebox").fetch("inventory", ACCOUNT, {}, ctx)
    respx.get(f"{HB}/api/v1/groups/statistics").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(AuthFailed, match="before 0.26 have no keys"):
        await get_adapter("homebox").fetch("inventory", CONFIG, {}, ctx)


@respx.mock
async def test_the_export_falls_back_to_the_old_address_and_remembers_it(ctx: Context, on_the_measured_day: None) -> None:
    new = respx.get(f"{HB}/api/v1/entities/export").mock(return_value=httpx.Response(404, text="404 page not found"))
    old = respx.get(f"{HB}/api/v1/items/export").mock(return_value=httpx.Response(200, text=EXPORT))
    data = await get_adapter("homebox").fetch("warranties", CONFIG, {"days": 3650}, ctx)
    assert {row["title"] for row in data.items} == {"Wifi Router", "Cordless Drill", "Coffee Machine"}
    assert ctx.cache["homebox_export"] == "/items/export"
    # The answers are cached as well; without them only the remembered address is asked.
    remembered = {"homebox_export": ctx.cache["homebox_export"]}
    await get_adapter("homebox").fetch("warranties", CONFIG, {"days": 30}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache=remembered))
    assert new.call_count == 1 and old.call_count == 2, "the old address first once it is known"


@respx.mock
async def test_a_given_currency_spares_the_question_and_the_value_can_stay_off(ctx: Context) -> None:
    respx.get(f"{HB}/api/v1/groups/statistics").mock(return_value=httpx.Response(200, json=STATISTICS))
    group = respx.get(f"{HB}/api/v1/groups").mock(return_value=httpx.Response(200, json=GROUP))
    data = await get_adapter("homebox").fetch("inventory", CONFIG, {"currency": "EUR"}, ctx)
    assert data.secondary[0]["value"] == "1,147.49 EUR" and not group.called
    await get_adapter("homebox").fetch("inventory", CONFIG, {"show_value": False}, ctx)
    assert not group.called, "no currency needed for a value that is not shown"


@respx.mock
async def test_value_by_place_largest_first_with_shares(ctx: Context) -> None:
    respx.get(f"{HB}/api/v1/groups").mock(return_value=httpx.Response(200, json=GROUP))
    respx.get(f"{HB}/api/v1/groups/statistics/locations").mock(return_value=httpx.Response(200, json=PLACES))
    data = await get_adapter("homebox").fetch("worth", CONFIG, {}, ctx)
    assert [(row["title"], row["value"], row["subtitle"], row["progress"]) for row in data.items] == [
        ("Office", "1,199.00 USD", "71 %", 71.2), ("Kitchen", "349.90 USD", "21 %", 20.8), ("Garage", "134.00 USD", "8 %", 8.0)]
    assert "not listed" in data.meta["notice"]


@respx.mock
async def test_value_by_tag(ctx: Context) -> None:
    respx.get(f"{HB}/api/v1/groups/statistics/tags").mock(return_value=httpx.Response(200, json=TAGS))
    data = await get_adapter("homebox").fetch("worth", CONFIG, {"by": "tag", "currency": "EUR", "limit": 2}, ctx)
    assert [(row["title"], row["value"]) for row in data.items] == [("Electronics", "1,682.90 EUR"), ("Kitchen", "349.90 EUR")]
    assert "counts for both" in data.meta["notice"]


@pytest.mark.parametrize("kind", [widget.kind for widget in get_adapter("homebox").widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(3):
        card = get_adapter("homebox").demo(kind, {}, tick)
        assert card.items or card.primary
