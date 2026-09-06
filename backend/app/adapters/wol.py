"""Wake-on-LAN: one card, one button, one MAC address.

The only adapter that talks to nothing. It sends a magic packet into the
local network and, if it was given an address, looks whether the machine
answers there.

⚠️ The card carries its own settings. A connection here would have meant one
"integration" per machine before a single card could exist, which is not what
a connection is for. Connections still resolve, because some exist already and
their cards must keep running; what stands on the widget wins.

⚠️ The packet is a broadcast. It reaches the machine only from a container
that shares the network with it, so nexdeck has to run with
``network_mode: host`` or the broadcast address of the right subnet has to be
set by hand. That is the one thing operators get wrong, so the field says it.
"""

from __future__ import annotations

import asyncio
import re
import socket
import time
from typing import Any

from .base import Action, Adapter, AdapterError, Context, Field, WidgetData, WidgetType

MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
#: How long a machine counts as just woken, so the card can say something.
JUST_WOKEN = 300


def mac_bytes(text: str) -> bytes:
    """The six bytes of a MAC address, or a readable refusal."""
    cleaned = str(text or "").strip()
    if not MAC.match(cleaned):
        raise AdapterError(
            "That is not a MAC address.",
            code="bad_mac",
            hint="Six pairs of hex digits, separated by colons: 00:1A:2B:3C:4D:5E.",
        )
    return bytes(int(part, 16) for part in re.split(r"[:-]", cleaned))


def magic_packet(mac: bytes) -> bytes:
    """Six 0xFF bytes, then the address sixteen times. That is the whole protocol."""
    return b"\xff" * 6 + mac * 16


def _send(packet: bytes, broadcast: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(5)
        sock.sendto(packet, (broadcast, port))
    finally:
        sock.close()


async def reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Does something answer on that port? A connection that opens is enough."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except (TimeoutError, OSError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


class WolAdapter(Adapter):
    kind = "wol"
    label = "Wake-on-LAN"
    category = "hosts"
    description = "One machine, one button: the magic packet that wakes it."
    icon = "lucide:power"
    docs_url = "https://en.wikipedia.org/wiki/Wake-on-LAN"
    needs_integration = False
    #: The older way. A card set up on its own leaves these empty.
    fields = (
        Field("mac", "MAC address", required=True, placeholder="00:1A:2B:3C:4D:5E",
              help="The network card of the machine to wake, six pairs of hex digits."),
        Field("host", "Address", help="Optional: where the machine answers when it is awake, so the card can say so."),
        Field("check_port", "Port for the check", type="number", default=22,
              help="A port that is open while the machine runs. 22 for SSH, 3389 for remote desktop, 445 for file sharing."),
        Field("broadcast", "Broadcast address", default="255.255.255.255",
              help="Only reaches the machine from the same network. Behind Docker, set the broadcast address of the subnet, for example 192.0.2.255."),
        Field("port", "Port", type="number", default=9, help="9 or 7; almost every card listens on 9."),
    )
    widgets = (
        WidgetType(
            kind="wake",
            label="Wake",
            description="The state of the machine, and the button that wakes it.",
            renderer="wol",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("awake",),
            options=(
                Field("mac", "MAC address", placeholder="00:1A:2B:3C:4D:5E",
                      help="The network card of the machine to wake, six pairs of hex digits."),
                Field("host", "Address", help="Optional: where the machine answers when it is awake, so the card can say so."),
                Field("check_port", "Port for the check", type="number", default=22,
                      help="A port that is open while the machine runs. 22 for SSH, 3389 for remote desktop, 445 for file sharing."),
                Field("broadcast", "Broadcast address", default="255.255.255.255",
                      help="Only reaches the machine from the same network. Behind Docker, set the broadcast address of the subnet, for example 192.0.2.255."),
                Field("port", "Port", type="number", default=9, help="9 or 7; almost every card listens on 9."),
                Field("view", "View", type="select", default="detail",
                      options=(("detail", "Details and a button"), ("icon", "One big button")),
                      help="The big button is meant for a small card: press it and the machine wakes."),
            ),
        ),
    )

    @staticmethod
    def settings(config: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        """The card's own settings over the connection's.

        ⚠️ Both have to work at once: cards built before this adapter stood on
        its own hang off a connection and have empty options, and a card built
        since has no connection at all. An empty option must not blank out a
        value that came from the connection.
        """
        merged = dict(config or {})
        for name, value in (options or {}).items():
            if value not in (None, ""):
                merged[name] = value
        return merged

    def _target(self, config: dict[str, Any]) -> tuple[str, int]:
        return str(config.get("host") or "").strip(), int(config.get("check_port") or 0)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        mac_bytes(str(config.get("mac") or ""))
        host, port = self._target(config)
        if not host:
            return "The address is in order. Whether the packet arrives shows on the first press."
        if await reachable(host, port):
            return f"{host} answers on port {port}; the machine is awake."
        return f"{host} does not answer on port {port}; the machine is asleep or the port is wrong."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        config = self.settings(config, options)
        mac = str(config.get("mac") or "").strip()
        if not mac:
            raise AdapterError(
                "No MAC address is set.",
                code="missing_mac",
                hint="Open the card's settings and enter the address of the machine's network card.",
            )
        host, port = self._target(config)
        woken = float(ctx.cache.get("wol_sent") or 0)
        recently = bool(woken and time.time() - woken < JUST_WOKEN)

        awake: bool | None = None
        if host and port:
            awake = await reachable(host, port)

        secondary: list[dict[str, Any]] = [{"label": "MAC", "value": mac.upper()}]
        if host:
            secondary.append({"label": "Address", "value": host})
        if recently:
            secondary.append({"label": "Woken", "value": f"{int(time.time() - woken)} s"})

        reason = ""
        if awake is False:
            reason = "The machine is asleep." if not recently else "The machine has not answered yet."
        return WidgetData(
            status="ok" if awake else ("unknown" if awake is None else "warn"),
            primary={"label": "Awake" if awake else ("Asleep" if awake is False else "Unknown"), "value": host or mac.upper()},
            secondary=secondary,
            actions=[Action(id="wake", label="Wake", icon="power")],
            metrics={"awake": 1.0 if awake else 0.0},
            meta={"status_reason": reason, "view": options.get("view") or "detail", "awake": awake},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "wake":
            raise AdapterError("This card only knows how to wake.", code="no_such_action")
        config = self.settings(config, options)
        packet = magic_packet(mac_bytes(str(config.get("mac") or "")))
        broadcast = str(config.get("broadcast") or "255.255.255.255").strip() or "255.255.255.255"
        port = int(config.get("port") or 9)
        try:
            await asyncio.to_thread(_send, packet, broadcast, port)
        except OSError as error:
            raise AdapterError(
                f"The packet could not be sent: {error.__class__.__name__}.",
                code="send_failed",
                hint="Check the broadcast address; from a container it has to be the one of the machine's subnet.",
            ) from error
        ctx.cache["wol_sent"] = time.time()
        return f"Magic packet sent to {broadcast}:{port}."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        awake = (tick // 20) % 2 == 0
        return WidgetData(
            status="ok" if awake else "warn",
            primary={"label": "Awake" if awake else "Asleep", "value": "workstation.example.com"},
            secondary=[
                {"label": "MAC", "value": "00:1A:2B:3C:4D:5E"},
                {"label": "Address", "value": "workstation.example.com"},
            ],
            actions=[Action(id="wake", label="Wake", icon="power")],
            metrics={"awake": 1.0 if awake else 0.0},
            meta={"status_reason": "" if awake else "The machine is asleep.", "view": options.get("view") or "detail", "awake": awake},
        )


ADAPTER = WolAdapter()
