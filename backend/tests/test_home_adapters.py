"""The house block: the document archive and the router in the hallway.

The FRITZ!Box speaks SOAP, so the recorded answers here are XML. What is
tested is the parsing, because that is the part that breaks when AVM renames
a field.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


# -- paperless-ngx -------------------------------------------------------------


@respx.mock
async def test_paperless_reads_the_statistics_document(ctx: Context) -> None:
    config = {"url": "http://paperless:8000", "token": "tok"}
    respx.get("http://paperless:8000/api/statistics/").mock(return_value=httpx.Response(200, json={
        "documents_total": 3481, "documents_inbox": 4, "inbox_tag": 5,
        "tag_count": 38, "correspondent_count": 62, "document_type_count": 14,
    }))
    data = await get_adapter("paperless").fetch("library", config, {}, ctx)
    assert data.primary == {"label": "Documents", "value": 3481}
    assert {entry["label"]: entry["value"] for entry in data.secondary} == {"Inbox": 4, "Tags": 38, "Correspondents": 62}
    assert data.metrics == {"documents": 3481.0, "inbox": 4.0}
    # Paperless wants "Token", not "Bearer"; that one word is the usual failure.
    assert respx.calls.last.request.headers["Authorization"] == "Token tok"


@respx.mock
async def test_paperless_puts_a_name_to_the_correspondent_number(ctx: Context) -> None:
    """A document names its correspondent by number. Without the lookup the
    line would read "12" where a name belongs."""
    config = {"url": "http://paperless:8000", "token": "tok"}
    respx.get("http://paperless:8000/api/documents/").mock(return_value=httpx.Response(200, json={"count": 3481, "results": [
        {"title": "Electricity bill", "correspondent": 12, "added": "2026-09-04T07:12:00Z"},
    ]}))
    respx.get("http://paperless:8000/api/correspondents/").mock(return_value=httpx.Response(200, json={"results": [
        {"id": 12, "name": "City works"}, {"id": 13, "name": "Tax office"},
    ]}))
    data = await get_adapter("paperless").fetch("recent", config, {"limit": 3}, ctx)
    assert data.items[0] == {"title": "Electricity bill", "subtitle": "City works · 2026-09-04"}


@respx.mock
async def test_paperless_takes_a_correspondent_that_is_already_a_name(ctx: Context) -> None:
    config = {"url": "http://paperless:8000", "token": "tok"}
    respx.get("http://paperless:8000/api/documents/").mock(return_value=httpx.Response(200, json={"count": 1, "results": [
        {"title": "Payslip", "correspondent": "Harbour Logistics", "added": "2026-08-31T06:00:00Z"},
    ]}))
    respx.get("http://paperless:8000/api/correspondents/").mock(return_value=httpx.Response(200, json={"results": []}))
    data = await get_adapter("paperless").fetch("recent", config, {}, ctx)
    assert data.items[0]["subtitle"] == "Harbour Logistics · 2026-08-31"


# -- fritz!box -----------------------------------------------------------------


def _soap(body: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<s:Body>{body}</s:Body></s:Envelope>"
    )


STATUS = _soap(
    '<u:GetStatusInfoResponse xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1">'
    "<NewConnectionStatus>Connected</NewConnectionStatus>"
    "<NewUptime>793440</NewUptime>"
    "<NewLastConnectionError>ERROR_NONE</NewLastConnectionError>"
    "</u:GetStatusInfoResponse>"
)
ADDRESS = _soap(
    '<u:GetExternalIPAddressResponse xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1">'
    "<NewExternalIPAddress>203.0.113.77</NewExternalIPAddress>"
    "</u:GetExternalIPAddressResponse>"
)
TRAFFIC = _soap(
    '<u:GetAddonInfosResponse xmlns:u="urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1">'
    "<NewByteSendRate>128000</NewByteSendRate>"
    "<NewByteReceiveRate>2097152</NewByteReceiveRate>"
    "<NewTotalBytesSent>1000000</NewTotalBytesSent>"
    "<NewTotalBytesReceived>2000000</NewTotalBytesReceived>"
    "<NewX_AVM_DE_TotalBytesSent64>6194000000000</NewX_AVM_DE_TotalBytesSent64>"
    "<NewX_AVM_DE_TotalBytesReceived64>41000000000000</NewX_AVM_DE_TotalBytesReceived64>"
    "</u:GetAddonInfosResponse>"
)
LINK = _soap(
    '<u:GetCommonLinkPropertiesResponse xmlns:u="urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1">'
    "<NewLayer1DownstreamMaxBitRate>250000000</NewLayer1DownstreamMaxBitRate>"
    "<NewLayer1UpstreamMaxBitRate>50000000</NewLayer1UpstreamMaxBitRate>"
    "<NewPhysicalLinkStatus>Up</NewPhysicalLinkStatus>"
    "</u:GetCommonLinkPropertiesResponse>"
)


@respx.mock
async def test_fritzbox_reads_the_line_out_of_three_soap_answers(ctx: Context) -> None:
    config = {"url": "http://fritz.box:49000"}

    def answer(request: httpx.Request) -> httpx.Response:
        action = request.headers.get("SOAPAction", "")
        for name, body in (("GetStatusInfo", STATUS), ("GetExternalIPAddress", ADDRESS), ("GetAddonInfos", TRAFFIC)):
            if action.endswith(f"#{name}"):
                return httpx.Response(200, text=body)
        return httpx.Response(500, text="")

    respx.post(url__startswith="http://fritz.box:49000/igdupnp/control/").mock(side_effect=answer)
    data = await get_adapter("fritzbox").fetch("connection", config, {}, ctx)
    assert data.status == "ok"
    assert data.primary == {"label": "Down", "value": "2.0 MB/s"}
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Up"] == "125.0 KB/s"
    assert values["Public address"] == "203.0.113.77"
    assert values["Uptime"] == "9d 4h"
    assert data.metrics == {"down": 2097152.0, "up": 128000.0}
    # The envelope has to name the action, or the box answers with a fault.
    assert respx.calls[0].request.headers["SOAPAction"].endswith("#GetStatusInfo")
    assert b"GetStatusInfo" in respx.calls[0].request.content


@respx.mock
async def test_fritzbox_says_when_the_line_is_down(ctx: Context) -> None:
    config = {"url": "http://fritz.box:49000"}
    down = STATUS.replace("Connected", "Disconnected")

    def answer(request: httpx.Request) -> httpx.Response:
        action = request.headers.get("SOAPAction", "")
        for name, body in (("GetStatusInfo", down), ("GetExternalIPAddress", ADDRESS), ("GetAddonInfos", TRAFFIC)):
            if action.endswith(f"#{name}"):
                return httpx.Response(200, text=body)
        return httpx.Response(500, text="")

    respx.post(url__startswith="http://fritz.box:49000/igdupnp/control/").mock(side_effect=answer)
    data = await get_adapter("fritzbox").fetch("connection", config, {}, ctx)
    assert data.status == "bad"
    assert data.meta["status_reason"] == "The connection is disconnected."


@respx.mock
async def test_fritzbox_prefers_the_counters_that_do_not_wrap(ctx: Context) -> None:
    """The plain counters are 32 bit and start over every four gigabytes. On a
    line that has run for a week they are nonsense."""
    config = {"url": "http://fritz.box:49000"}

    def answer(request: httpx.Request) -> httpx.Response:
        action = request.headers.get("SOAPAction", "")
        return httpx.Response(200, text=LINK if action.endswith("#GetCommonLinkProperties") else TRAFFIC)

    respx.post(url__startswith="http://fritz.box:49000/igdupnp/control/").mock(side_effect=answer)
    data = await get_adapter("fritzbox").fetch("line", config, {}, ctx)
    values = {entry["label"]: entry["value"] for entry in data.secondary}
    assert values["Sync down"] == "250.0 Mbit/s" and values["Sync up"] == "50.0 Mbit/s"
    assert values["Received"] == "37.3 TB" and values["Sent"] == "5.6 TB"
    assert data.status == "ok"


@respx.mock
async def test_fritzbox_says_so_when_the_address_is_not_a_box(ctx: Context) -> None:
    """Port 80 answers with the web interface: HTML, not SOAP."""
    config = {"url": "http://fritz.box:49000"}
    respx.post(url__startswith="http://fritz.box:49000/igdupnp/control/").mock(
        return_value=httpx.Response(200, text="<!DOCTYPE html><html><body>Login"),
    )
    with pytest.raises(AdapterError, match="did not answer with SOAP"):
        await get_adapter("fritzbox").fetch("connection", config, {}, ctx)


# -- every one of them ---------------------------------------------------------


@pytest.mark.parametrize("kind", ["paperless", "fritzbox"])
def test_every_house_adapter_has_demo_data_for_every_widget(kind: str) -> None:
    adapter = get_adapter(kind)
    assert adapter.widgets, kind
    for widget in adapter.widgets:
        options = {field.name: field.default for field in widget.options}
        for tick in (0, 7, 41):
            data = adapter.demo(widget.kind, options, tick)
            assert data.items or data.primary or data.secondary, f"{kind}/{widget.kind} at tick {tick} is empty"
