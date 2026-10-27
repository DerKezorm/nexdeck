"""FRITZ!Box: the line, seen from the router itself.

The box speaks no JSON. What it does speak is TR-064 over SOAP on port 49000,
and the part of it that answers without any credentials is the IGD subset:
connection state, external address, uptime and the current rates. That is
exactly what a line card needs, so without a user this adapter asks for
nothing else.

⚠️ The IGD subset is there only while "Transmit status information over UPnP"
is switched on under Home Network > Network > Network Settings. Without it the
box answers every action with UPnP error 401, "Invalid Action", as HTTP 500,
and ``igddesc.xml`` is a 404. "Allow access for applications" is a different
switch: it opens TR-064 proper, which wants a user. Measured on a 6591 Cable
with FRITZ!OS 8.25 (27.10.2026), where the first was off and the second on.

⚠️ A box that runs as a bridge or modem in front of another router says
"Unconfigured" with an uptime of 0 over IGD, while TR-064 with a user says
"Connected" and the real uptime, measured on the same box in the same minute.
That is what the optional user is for: with one, status, address, uptime and
the current rates come from TR-064, which also works with UPnP switched off.
The first value of ``X_AVM-DE_GetOnlineMonitor`` is the IGD rate to the byte.
"""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

import httpx

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

#: The same over TR-064, which wants a user. A cable or fibre line is an IP
#: connection, a DSL line with PPPoE the other one.
SIGNED_COMMON = ("/upnp/control/wancommonifconfig1", "urn:dslforum-org:service:WANCommonInterfaceConfig:1")
SIGNED_IP = ("/upnp/control/wanipconnection1", "urn:dslforum-org:service:WANIPConnection:1")
SIGNED_PPP = ("/upnp/control/wanpppconn1", "urn:dslforum-org:service:WANPPPConnection:1")

ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
    ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body>{call}</s:Body></s:Envelope>"
)

#: An answer of this size is not a FRITZ!Box answering; it is parsed by no one.
MAX_ANSWER = 256 * 1024

#: What the box says over IGD for an action it does not offer right now.
INVALID_ACTION = "401"


class FritzboxAdapter(Adapter):
    kind = "fritzbox"
    label = "FRITZ!Box"
    category = "network"
    description = "Connection state, external address, uptime and what is going over the line."
    icon = "fritzbox"
    docs_url = "https://avm.de/service/schnittstellen/"
    # Confirmed 2026-10-27 against a 6591 Cable with FRITZ!OS 8.25, with and without a user.
    beta = False
    fields = (
        Field(
            "url", "URL", type="url", required=True, default="http://fritz.box:49000",
            placeholder="http://fritz.box:49000",
            help="Port 49000 with http, not the web interface. Without a user the box has to transmit status information over UPnP.",
        ),
        Field(
            "username", "User name",
            help="Optional. A FRITZ!Box user with the right \"FRITZ!Box settings\". "
                 "Needed when the box is a modem or bridge in front of another router, which shows no uptime otherwise.",
        ),
        Field("password", "Password", type="password", secret=True),
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

    @staticmethod
    def _user(config: dict[str, Any]) -> tuple[str, str] | None:
        username = str(config.get("username") or "").strip()
        password = str(config.get("password") or "")
        return (username, password) if username and password else None

    async def _soap(
        self, config: dict[str, Any], ctx: Context, service: tuple[str, str], action: str,
        cache: float = 20, arguments: str = "",
    ) -> dict[str, str]:
        path, urn = service
        url = base_url(config)
        # ⚠️ Port 49000 answers a TLS greeting with "HTTP/1.0 400 Bad Request",
        # which httpx reports as a ConnectError, and the card said "could not
        # be reached" while the box answered every time (27.10.2026).
        if httpx.URL(url).scheme == "https" and httpx.URL(url).port == 49000:
            raise AdapterError(
                "Port 49000 speaks http, not https.",
                code="https_on_plain_port",
                hint="Write http:// in front of the address.",
            )
        user = self._user(config) if path.startswith("/upnp/") else None
        # Without arguments the call stays the empty element it was measured with.
        call = (f'<u:{action} xmlns:u="{urn}">{arguments}</u:{action}>' if arguments
                else f'<u:{action} xmlns:u="{urn}" />')
        response = await ctx.request(
            "POST",
            f"{url}{path}",
            headers={"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f"{urn}#{action}"},
            content=ENVELOPE.format(call=call).encode("utf-8"),
            # A POST is not cached by the context; the box is quick enough.
            cache_seconds=cache,
            # The box asks for digest; httpx answers the challenge with the same body.
            auth=httpx.DigestAuth(*user) if user else None,
        )
        if len(response.content) > MAX_ANSWER:
            raise AdapterError("The answer is too large for a FRITZ!Box.", code="not_soap", hint="The URL probably points at something else.")
        if response.status_code >= 400:
            if user is None and self._fault(response.text) == INVALID_ACTION:
                raise AdapterError(
                    "The box does not transmit its status over UPnP.",
                    code="upnp_off",
                    hint='Switch on "Transmit status information over UPnP" under Home Network > Network > Network Settings, '
                         "or enter a FRITZ!Box user.",
                )
            raise AdapterError(
                f"The box answered with HTTP {response.status_code}.",
                code="http_error",
                hint="Check the port: 49000 with http.",
            )
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

    @staticmethod
    def _fault(text: str) -> str:
        """The UPnP error code in a SOAP fault, or "" when there is none."""
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            return ""
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "errorCode":
                return (element.text or "").strip()
        return ""

    async def _state(self, config: dict[str, Any], ctx: Context, cache: float, with_address: bool = True) -> tuple[str, float, str]:
        """Connection status, uptime in seconds and the public address."""
        if self._user(config) is None:
            status = await self._soap(config, ctx, CONNECTION, "GetStatusInfo", cache=cache)
            address = await self._soap(config, ctx, CONNECTION, "GetExternalIPAddress", cache=120) if with_address else {}
            return (status.get("NewConnectionStatus") or "?", float(status.get("NewUptime") or 0),
                    address.get("NewExternalIPAddress") or "")
        info = await self._soap(config, ctx, SIGNED_IP, "GetInfo", cache=cache)
        if (info.get("NewConnectionStatus") or "").lower() != "connected":
            # A DSL line dials in over PPP; a cable box does not offer that action at all.
            try:
                ppp = await self._soap(config, ctx, SIGNED_PPP, "GetInfo", cache=cache)
            except AdapterError:
                ppp = {}
            if (ppp.get("NewConnectionStatus") or "").lower() == "connected":
                info = ppp
        return (info.get("NewConnectionStatus") or "?", float(info.get("NewUptime") or 0),
                info.get("NewExternalIPAddress") or "")

    async def _rates(self, config: dict[str, Any], ctx: Context) -> tuple[float, float]:
        """Bytes per second down and up, right now."""
        if self._user(config) is None:
            traffic = await self._soap(config, ctx, COMMON, "GetAddonInfos", cache=20)
            return float(traffic.get("NewByteReceiveRate") or 0), float(traffic.get("NewByteSendRate") or 0)
        monitor = await self._soap(
            config, ctx, SIGNED_COMMON, "X_AVM-DE_GetOnlineMonitor", cache=20,
            arguments="<NewSyncGroupIndex>0</NewSyncGroupIndex>",
        )
        # Twenty samples each, the newest first.
        return self._first(monitor.get("Newds_current_bps")), self._first(monitor.get("Newus_current_bps"))

    @staticmethod
    def _first(samples: str | None) -> float:
        head = (samples or "").split(",", 1)[0].strip()
        try:
            return float(head)
        except ValueError:
            return 0.0

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        state, _uptime, _address = await self._state(config, ctx, cache=0, with_address=False)
        return f"The FRITZ!Box answers; the connection is {state.lower()}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "line":
            signed = self._user(config) is not None
            common = await self._soap(config, ctx, SIGNED_COMMON if signed else COMMON, "GetCommonLinkProperties", cache=120)
            sync_down = float(common.get("NewLayer1DownstreamMaxBitRate") or 0)
            sync_up = float(common.get("NewLayer1UpstreamMaxBitRate") or 0)
            link = common.get("NewPhysicalLinkStatus") or "?"
            secondary = [
                {"label": "Sync down", "metric": "sync_down", "value": f"{sync_down / 1_000_000:.1f} Mbit/s"},
                {"label": "Sync up", "metric": "sync_up", "value": f"{sync_up / 1_000_000:.1f} Mbit/s"},
            ]
            try:
                traffic = await self._soap(config, ctx, COMMON, "GetAddonInfos", cache=60)
            except AdapterError as failure:
                # TR-064 counts in 32 bit and starts over every four gigabytes:
                # no totals beat wrong ones. Without a user there is nothing to show.
                if not (signed and failure.code == "upnp_off"):
                    raise
            else:
                secondary += [
                    {"label": "Received", "value": human_bytes(self._total(traffic, "Received"))},
                    {"label": "Sent", "value": human_bytes(self._total(traffic, "Sent"))},
                ]
            return WidgetData(
                status="ok" if link.lower() == "up" else "bad",
                secondary=secondary,
                metrics={"sync_down": sync_down, "sync_up": sync_up},
            )

        state, uptime, address = await self._state(config, ctx, cache=30)
        down, up = await self._rates(config, ctx)
        connected = state.lower() == "connected"
        # Over IGD a box in bridge mode does not dial in itself: that is not a
        # line that is down, so the card does not turn red for it.
        unconfigured = state.lower() == "unconfigured" and self._user(config) is None
        secondary = [
            {"label": "Upload", "metric": "up", "value": f"{human_bytes(up)}/s"},
            {"label": "Public address", "value": address or "?"},
        ]
        if uptime > 0:
            secondary.append({"label": "Uptime", "value": duration_short(uptime)})
        if connected:
            reason = ""
        elif unconfigured:
            reason = "The box does not dial in itself. Enter a FRITZ!Box user for the state of the line."
        else:
            reason = f"The connection is {state.lower()}."
        return WidgetData(
            status="ok" if connected else "unknown" if unconfigured else "bad",
            primary={"label": "Download", "metric": "down", "value": f"{human_bytes(down)}/s"},
            secondary=secondary,
            metrics={"down": down, "up": up},
            meta={"status_reason": reason},
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
                    {"label": "Sync down", "metric": "sync_down", "value": "250.0 Mbit/s"},
                    {"label": "Sync up", "metric": "sync_up", "value": "50.0 Mbit/s"},
                    {"label": "Received", "value": human_bytes(fake.counter("fritz-in", tick, 4.1e13, 4e8))},
                    {"label": "Sent", "value": human_bytes(fake.counter("fritz-out", tick, 6.2e12, 8e7))},
                ],
                metrics={"sync_down": 250_000_000.0, "sync_up": 50_000_000.0},
            )
        down = fake.walk("fritz-down", tick, 40_000, 4_800_000, period=90)
        up = fake.walk("fritz-up", tick, 10_000, 900_000, period=70)
        return WidgetData(
            status="ok",
            primary={"label": "Download", "metric": "down", "value": f"{human_bytes(down)}/s"},
            secondary=[
                {"label": "Upload", "metric": "up", "value": f"{human_bytes(up)}/s"},
                {"label": "Public address", "value": "203.0.113.77"},
                {"label": "Uptime", "value": "9d 4h"},
            ],
            metrics={"down": down, "up": up},
            meta={"status_reason": ""},
        )


ADAPTER = FritzboxAdapter()
