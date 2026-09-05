"""FRITZ!Box: the line, seen from the router itself.

The box speaks no JSON. What it does speak is TR-064 over SOAP on port 49000,
and the part of it that answers without any credentials is the IGD subset:
connection state, external address, uptime and the current rates. That is
exactly what a line card needs, so this adapter asks for nothing else and
therefore needs no password.

⚠️ The box only answers when "Allow access for applications" is switched on
under Home Network > Network > Network settings. It is on by default.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
)

#: The two IGD services and where they listen.
COMMON = ("/igdupnp/control/WANCommonIFC1", "urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1")
CONNECTION = ("/igdupnp/control/WANIPConn1", "urn:schemas-upnp-org:service:WANIPConnection:1")

ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
    ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    '<s:Body><u:{action} xmlns:u="{service}" /></s:Body></s:Envelope>'
)

#: An answer of this size is not a FRITZ!Box answering; it is parsed by no one.
MAX_ANSWER = 256 * 1024


class FritzboxAdapter(Adapter):
    kind = "fritzbox"
    label = "FRITZ!Box"
    category = "network"
    description = "Connection state, external address, uptime and what is going over the line."
    icon = "fritzbox"
    docs_url = "https://avm.de/service/schnittstellen/"
    fields = (
        Field(
            "url", "URL", type="url", required=True, default="http://fritz.box:49000",
            placeholder="http://fritz.box:49000",
            help="Port 49000, not the web interface. The box has to allow access for applications.",
        ),
    )
    widgets = (
        WidgetType(
            kind="connection",
            label="Connection",
            description="Whether the line is up, the address the world sees, and the current rates.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("down", "up"),
        ),
        WidgetType(
            kind="line",
            label="Line",
            description="What the line was sold as, and what went over it since the last reconnect.",
            renderer="stats",
            default_size=(3, 2),
            refresh_seconds=120,
            metrics=("sync_down", "sync_up"),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return "http://fritz.box"

    async def _soap(self, config: dict[str, Any], ctx: Context, service: tuple[str, str], action: str, cache: float = 20) -> dict[str, str]:
        path, urn = service
        response = await ctx.request(
            "POST",
            f"{base_url(config)}{path}",
            headers={"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f"{urn}#{action}"},
            content=ENVELOPE.format(action=action, service=urn).encode("utf-8"),
            # A POST is not cached by the context; the box is quick enough.
            cache_seconds=cache,
        )
        if response.status_code >= 400:
            raise AdapterError(
                f"The box answered with HTTP {response.status_code}.",
                code="http_error",
                hint="Check the port and whether the box allows access for applications.",
            )
        if len(response.content) > MAX_ANSWER:
            raise AdapterError("The answer is too large for a FRITZ!Box.", code="not_soap", hint="The URL probably points at something else.")
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as error:
            raise AdapterError(
                "The box did not answer with SOAP.",
                code="not_soap",
                hint="Port 49000 is the one that speaks TR-064; 80 is the web interface.",
            ) from error
        values: dict[str, str] = {}
        for element in root.iter():
            name = element.tag.rsplit("}", 1)[-1]
            if name.startswith("New"):
                values[name] = (element.text or "").strip()
        return values

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._soap(config, ctx, CONNECTION, "GetStatusInfo", cache=0)
        state = status.get("NewConnectionStatus") or "?"
        return f"The FRITZ!Box answers; the connection is {state.lower()}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "line":
            common = await self._soap(config, ctx, COMMON, "GetCommonLinkProperties", cache=120)
            sync_down = float(common.get("NewLayer1DownstreamMaxBitRate") or 0)
            sync_up = float(common.get("NewLayer1UpstreamMaxBitRate") or 0)
            traffic = await self._soap(config, ctx, COMMON, "GetAddonInfos", cache=60)
            link = common.get("NewPhysicalLinkStatus") or "?"
            return WidgetData(
                status="ok" if link.lower() == "up" else "bad",
                secondary=[
                    {"label": "Sync down", "value": f"{sync_down / 1_000_000:.1f} Mbit/s"},
                    {"label": "Sync up", "value": f"{sync_up / 1_000_000:.1f} Mbit/s"},
                    {"label": "Received", "value": human_bytes(self._total(traffic, "Received"))},
                    {"label": "Sent", "value": human_bytes(self._total(traffic, "Sent"))},
                ],
                metrics={"sync_down": sync_down, "sync_up": sync_up},
            )

        status = await self._soap(config, ctx, CONNECTION, "GetStatusInfo", cache=30)
        traffic = await self._soap(config, ctx, COMMON, "GetAddonInfos", cache=20)
        address = await self._soap(config, ctx, CONNECTION, "GetExternalIPAddress", cache=120)
        state = status.get("NewConnectionStatus") or "?"
        connected = state.lower() == "connected"
        down = float(traffic.get("NewByteReceiveRate") or 0)
        up = float(traffic.get("NewByteSendRate") or 0)
        return WidgetData(
            status="ok" if connected else "bad",
            primary={"label": "Down", "value": f"{human_bytes(down)}/s"},
            secondary=[
                {"label": "Up", "value": f"{human_bytes(up)}/s"},
                {"label": "Public address", "value": address.get("NewExternalIPAddress") or "?"},
                {"label": "Uptime", "value": duration_short(float(status.get("NewUptime") or 0))},
            ],
            metrics={"down": down, "up": up},
            meta={"status_reason": "" if connected else f"The connection is {state.lower()}."},
        )

    @staticmethod
    def _total(traffic: dict[str, str], direction: str) -> float:
        """The plain counters are 32 bit and wrap every four gigabytes; AVM's
        own ones do not, so they come first."""
        wide = traffic.get(f"NewX_AVM_DE_TotalBytes{direction}64")
        return float(wide or traffic.get(f"NewTotalBytes{direction}") or 0)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "line":
            return WidgetData(
                status="ok",
                secondary=[
                    {"label": "Sync down", "value": "250.0 Mbit/s"},
                    {"label": "Sync up", "value": "50.0 Mbit/s"},
                    {"label": "Received", "value": human_bytes(fake.counter("fritz-in", tick, 4.1e13, 4e8))},
                    {"label": "Sent", "value": human_bytes(fake.counter("fritz-out", tick, 6.2e12, 8e7))},
                ],
                metrics={"sync_down": 250_000_000.0, "sync_up": 50_000_000.0},
            )
        down = fake.walk("fritz-down", tick, 40_000, 4_800_000, period=90)
        up = fake.walk("fritz-up", tick, 10_000, 900_000, period=70)
        return WidgetData(
            status="ok",
            primary={"label": "Down", "value": f"{human_bytes(down)}/s"},
            secondary=[
                {"label": "Up", "value": f"{human_bytes(up)}/s"},
                {"label": "Public address", "value": "203.0.113.77"},
                {"label": "Uptime", "value": "9d 4h"},
            ],
            metrics={"down": down, "up": up},
            meta={"status_reason": ""},
        )


ADAPTER = FritzboxAdapter()
