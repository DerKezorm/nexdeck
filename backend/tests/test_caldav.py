"""A CalDAV calendar through the iCal connection: Radicale answers a GET,
Nextcloud and Baïkal hand out ``?export``, every server answers a REPORT.
Measured against Radicale 3 on 01.10.2026; the other two ways are shaped
after what those servers send."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context
from app.adapters.ical import calendar_data

TOMORROW = (date.today() + timedelta(days=1)).strftime("%Y%m%d")
EVENT = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:1\r\nDTSTART:{TOMORROW}T090000Z\r\nSUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
URL = "https://cloud.example.com/remote.php/dav/calendars/alex/personal/"
CONFIG = {"url": URL, "name": "Family", "username": "alex", "password": "app-password"}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_nextcloud_hands_out_the_calendar_with_export(ctx: Context) -> None:
    # The route with the query first: respx takes the first route that fits.
    exported = respx.get(URL, params={"export": ""}).mock(return_value=httpx.Response(200, text=EVENT))
    respx.get(URL).mock(return_value=httpx.Response(200, text="<html>This is the WebDAV interface.</html>"))
    data = await get_adapter("ical").fetch("events", CONFIG, {"days": 7}, ctx)
    assert [item["title"] for item in data.items] == ["Dentist"]
    assert exported.calls.last.request.headers["Authorization"].startswith("Basic ")


@respx.mock
async def test_a_server_without_export_answers_a_report(ctx: Context) -> None:
    respx.get(URL, params={"export": ""}).mock(return_value=httpx.Response(404))
    respx.get(URL).mock(return_value=httpx.Response(405))
    multistatus = ("<?xml version='1.0'?><d:multistatus xmlns:d='DAV:' xmlns:cal='urn:ietf:params:xml:ns:caldav'><d:response><d:propstat><d:prop>"
                   f"<cal:calendar-data>{EVENT.replace('&', '&amp;')}</cal:calendar-data></d:prop></d:propstat></d:response></d:multistatus>")
    report = respx.route(method="REPORT", url=URL).mock(return_value=httpx.Response(207, text=multistatus))
    data = await get_adapter("ical").fetch("events", CONFIG, {"days": 7}, ctx)
    assert [item["title"] for item in data.items] == ["Dentist"]
    assert report.calls.last.request.headers["Depth"] == "1"


@respx.mock
async def test_a_refused_password_says_so(ctx: Context) -> None:
    respx.get(URL).mock(return_value=httpx.Response(401))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("ical").fetch("events", CONFIG, {"days": 7}, ctx)
    assert refused.value.code == "auth_failed"


@respx.mock
async def test_an_ics_link_still_costs_one_request(ctx: Context) -> None:
    feed = respx.get("https://example.com/family.ics").mock(return_value=httpx.Response(200, text=EVENT))
    await get_adapter("ical").fetch("events", {"url": "https://example.com/family.ics"}, {"days": 7}, ctx)
    assert feed.call_count == 1 and len(respx.calls) == 1
    assert "Authorization" not in feed.calls.last.request.headers


def test_calendar_data_is_unescaped_and_kept_per_event() -> None:
    xml = "<C:calendar-data>BEGIN:VCALENDAR&#13;\nSUMMARY:A &amp; B\nEND:VCALENDAR</C:calendar-data><C:calendar-data/>"
    assert calendar_data(xml) == ["BEGIN:VCALENDAR\r\nSUMMARY:A & B\nEND:VCALENDAR"]
