"""Minecraft: whether a Java or Bedrock server is up, how full it is, who is on it and what it says about itself.

Measured on 27.09.2026 without an account, the way a game client asks before
it joins: against the vanilla Java server 26.3 (protocol 777) and Paper 26.2
from ``itzg/minecraft-server``, with two players signed in by a small client
in offline mode, and against the Bedrock Dedicated Server 1.26.52.3 from
``itzg/minecraft-bedrock-server`` on both of its transports. Also measured: a
server still starting, a closed port, a port with SSH or a web server behind
it, and an address nobody answers at.

⚠️ Java speaks the Server List Ping over TCP: a handshake with the next
state 1, an empty status request, and one JSON document back, followed by a
ping the server echoes. The echo is the latency the card shows; it came back
in half the time of the status answer.

⚠️ The message of the day comes in two shapes. Vanilla hands back a plain
string with the old colour codes in it (``§6Gold §lbold§r``), Paper a chat
component whose ``extra`` holds further components and bare strings. Both are
flattened to text and the codes taken out.

⚠️ ``players.sample`` is missing whenever nobody is online, and also when the
server runs with ``hide-online-players=true``: then it says two players are
on and names none. A missing list with players online is "hidden", never
"empty".

⚠️ A player whose client has "Allow Server Listings" switched off stands in
the list as ``Anonymous Player`` with the id of all zeros. A client that never
says either way counts as switched off: the first test client that skipped
its client information was anonymous to the server list.

⚠️ While a server starts, the port is refused, then for about a second it
accepts a connection and closes it without a word. The card says "No answer"
in yellow for that rather than calling the server offline.

⚠️ Bedrock 1.26 no longer speaks RakNet by default. ``transport=nethernet``
is the new default: the game port is a TCP socket with an HTTP signalling
server on it, and the RakNet ping on UDP goes unanswered. ``GET /v1/join`` on
that port hands out name, version, world, players and slots as JSON, without
any sign-in. With ``transport=raknet`` the old UDP ping answers again
(``MCPE;name;protocol;version;players;max;...``) while the server logs that
RakNet is no longer supported. The adapter asks both at once and takes
whichever answers.

⚠️ Bedrock never names its players, on either transport.

⚠️ SRV records are not followed: the port has to be the one the server
listens on. A name lookup for them would need a DNS library of its own.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    guard_outbound,
    measured,
)

DEFAULT_PORT = {"java": 25565, "bedrock": 19132}
#: How long one connection or one answer may take. The collector gives a
#: card twenty seconds, and Bedrock asks two ways at once inside that.
TIMEOUT = 5.0
#: The largest status answer taken. A server icon is a few kilobytes of
#: base64; a megabyte is far beyond anything a server sends.
MAX_STATUS = 1024 * 1024
#: The id an anonymous player carries in the sample.
NOBODY = "00000000-0000-0000-0000-000000000000"
#: RakNet's offline message id, sixteen fixed bytes in every unconnected packet,
#: written in groups so that no secret scanner takes it for a key or a password.
MAGIC = bytes.fromhex("00ffff00 fefefefe fdfdfdfd 1234 5678")
CLIENT_GUID = 0x6E65786465636B21
CODES = re.compile("§.?")
MODE = {"0": "Survival", "1": "Creative", "2": "Adventure", "3": "Spectator"}


class Offline(Exception):
    """Nothing took the connection, or nothing came back at all."""


class Silent(Exception):
    """The port took the connection and said nothing: a server starting, most likely."""


class NotMinecraft(Exception):
    """Something answered, but not the way a Minecraft server does."""


@dataclass
class Answer:
    """One server's answer, whichever edition gave it."""

    edition: str
    online: int
    slots: int
    version: str = ""
    motd: str = ""
    latency: float | None = None
    world: str = ""
    mode: str = ""
    #: The names the server gave, or ``None`` when it gave no list at all.
    sample: list[dict[str, str]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def plain(text: Any) -> str:
    """A message of the day as text: components flattened, colour codes gone, one line."""
    flat = _flatten(text)
    lines = [" ".join(CODES.sub("", line).split()) for line in flat.splitlines()]
    return " · ".join(line for line in lines if line)


def _flatten(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten(one) for one in node)
    if isinstance(node, dict):
        return str(node.get("text") or "") + "".join(_flatten(one) for one in node.get("extra") or [])
    return ""


def varint(value: int) -> bytes:
    out = b""
    value &= 0xFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def _read_varint(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    for shift in range(5):
        if index >= len(data):
            raise NotMinecraft
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << (7 * shift)
        if not byte & 0x80:
            return value, index
    raise NotMinecraft


def _packet(payload: bytes) -> bytes:
    return varint(len(payload)) + payload


async def _next_varint(reader: asyncio.StreamReader, *, first: bool) -> int:
    """The length in front of a packet. Nothing at all before the first byte is silence, not garbage."""
    value = 0
    for shift in range(5):
        try:
            byte = (await asyncio.wait_for(reader.readexactly(1), TIMEOUT))[0]
        except (TimeoutError, asyncio.IncompleteReadError, ConnectionError) as error:
            if first and shift == 0:
                raise Silent from error
            raise NotMinecraft from error
        value |= (byte & 0x7F) << (7 * shift)
        if not byte & 0x80:
            return value
    raise NotMinecraft


def _settings(config: dict[str, Any]) -> tuple[str, str, int]:
    edition = "bedrock" if str(config.get("edition") or "java").lower() == "bedrock" else "java"
    host = str(config.get("host") or "").strip()
    for scheme in ("minecraft://", "http://", "https://", "tcp://", "udp://"):
        if host.lower().startswith(scheme):
            host = host[len(scheme):]
    host = host.strip("/").strip()
    port_text = str(config.get("port") or "").strip()
    if host.count(":") == 1:
        # "host:port" as people copy it out of the game's server list.
        host, _, typed = host.partition(":")
        port_text = port_text or typed
    host = host.strip("[]")
    if not host:
        raise AdapterError("This connection names no server.", code="bad_url", hint="Enter the address of the Minecraft server.")
    try:
        port = int(port_text) if port_text else DEFAULT_PORT[edition]
    except ValueError:
        port = 0
    if not 0 < port < 65536:
        raise AdapterError("That is not a port number.", code="bad_url",
                           hint="Java listens on 25565 and Bedrock on 19132 unless somebody changed it.")
    # ⚠️ Not HTTP, and still the same rule as every other connection:
    # link-local and the cloud metadata service are barred, by name.
    guard_outbound(f"http://{_bracketed(host)}:{port}")
    return edition, host, port


def _bracketed(host: str) -> str:
    return f"[{host}]" if ":" in host else host


# -- Java ------------------------------------------------------------------


async def ask_java(host: str, port: int) -> Answer:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT)
    except socket.gaierror as error:
        raise _no_such_name(host) from error
    except (TimeoutError, OSError) as error:
        raise Offline from error
    try:
        name = host.encode("utf-8")
        # Protocol -1: "whatever you speak". Vanilla and Paper both answered it.
        handshake = varint(0) + varint(-1) + varint(len(name)) + name + struct.pack(">H", port) + varint(1)
        started = time.perf_counter()
        writer.write(_packet(handshake) + _packet(varint(0)))
        await writer.drain()
        length = await _next_varint(reader, first=True)
        if not 0 < length <= MAX_STATUS:
            raise NotMinecraft
        try:
            body = await asyncio.wait_for(reader.readexactly(length), TIMEOUT)
        except (TimeoutError, asyncio.IncompleteReadError, ConnectionError) as error:
            raise NotMinecraft from error
        took = (time.perf_counter() - started) * 1000
        packet_id, index = _read_varint(body, 0)
        size, index = _read_varint(body, index)
        if packet_id != 0 or index + size > len(body):
            raise NotMinecraft
        try:
            status = json.loads(body[index:index + size].decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise NotMinecraft from error
        if not isinstance(status, dict) or not isinstance(status.get("players"), dict):
            raise NotMinecraft
        latency = await _pong(reader, writer)
        return _java_answer(status, took if latency is None else latency)
    except (ConnectionError, OSError) as error:
        raise NotMinecraft from error
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def _pong(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> float | None:
    """The round trip of the ping after the status, or ``None`` for a server that skips it."""
    payload = struct.pack(">q", 0x6E6578)
    try:
        started = time.perf_counter()
        writer.write(_packet(varint(1) + payload))
        await writer.drain()
        length = await _next_varint(reader, first=False)
        body = await asyncio.wait_for(reader.readexactly(length), TIMEOUT)
    except (NotMinecraft, TimeoutError, asyncio.IncompleteReadError, OSError):
        return None
    return (time.perf_counter() - started) * 1000 if body[1:] == payload else None


def _java_answer(status: dict[str, Any], latency: float) -> Answer:
    players = status.get("players") or {}
    version = status.get("version") if isinstance(status.get("version"), dict) else {}
    raw = players.get("sample")
    sample = None
    if isinstance(raw, list):
        sample = [
            {"name": plain(one.get("name")), "id": str(one.get("id") or "")}
            for one in raw if isinstance(one, dict) and plain(one.get("name"))
        ]
    return Answer(
        edition="java",
        online=_number(players.get("online")),
        slots=_number(players.get("max")),
        version=plain(version.get("name")),
        motd=plain(status.get("description")),
        latency=latency,
        sample=sample,
    )


def _number(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# -- Bedrock ---------------------------------------------------------------


class _RakNet(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.answer: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr: Any) -> None:
        if data[:1] == b"\x1c" and not self.answer.done():
            self.answer.set_result(data)

    def error_received(self, exc: Exception) -> None:
        # ICMP "port unreachable" arrives here, on Windows as a reset.
        if not self.answer.done():
            self.answer.set_exception(Offline())


async def ask_raknet(host: str, port: int) -> Answer:
    loop = asyncio.get_running_loop()
    try:
        transport, protocol = await asyncio.wait_for(
            loop.create_datagram_endpoint(_RakNet, remote_addr=(host, port)), TIMEOUT)
    except socket.gaierror as error:
        raise _no_such_name(host) from error
    except (TimeoutError, OSError) as error:
        raise Offline from error
    try:
        # UDP loses packets, so the ping goes out again after each quiet second.
        for _attempt in range(3):
            started = time.perf_counter()
            transport.sendto(b"\x01" + struct.pack(">q", int(time.time() * 1000)) + MAGIC + struct.pack(">Q", CLIENT_GUID))
            try:
                data = await asyncio.wait_for(asyncio.shield(protocol.answer), TIMEOUT / 4)
            except TimeoutError:
                continue
            return _raknet_answer(data, (time.perf_counter() - started) * 1000)
        raise Offline
    finally:
        transport.close()


def _raknet_answer(data: bytes, latency: float) -> Answer:
    if len(data) < 35 or data[17:33] != MAGIC:
        raise NotMinecraft
    size = struct.unpack(">H", data[33:35])[0]
    fields = data[35:35 + size].decode("utf-8", "replace").split(";")
    if len(fields) < 6 or fields[0] not in ("MCPE", "MCEE"):
        raise NotMinecraft
    return Answer(
        edition="bedrock",
        online=_number(fields[4]),
        slots=_number(fields[5]),
        version=fields[3],
        motd=plain(fields[1]),
        latency=latency,
        world=plain(fields[7]) if len(fields) > 7 else "",
        mode=fields[8] if len(fields) > 8 else "",
        extra={"transport": "raknet"},
    )


async def ask_nethernet(host: str, port: int, ctx: Context) -> Answer:
    started = time.perf_counter()
    try:
        response = await ctx.request("GET", f"http://{_bracketed(host)}:{port}/v1/join", timeout=TIMEOUT, auth_errors=False)
    except Unreachable as error:
        raise Offline from error
    latency = (time.perf_counter() - started) * 1000
    try:
        body = response.json()
    except ValueError as error:
        raise NotMinecraft from error
    if response.status_code != 200 or not isinstance(body, dict) or "maxPlayers" not in body:
        raise NotMinecraft
    return Answer(
        edition="bedrock",
        online=_number(body.get("players")),
        slots=_number(body.get("maxPlayers")),
        version=str(body.get("version") or ""),
        motd=plain(body.get("name")),
        latency=latency,
        world=plain(body.get("level")),
        mode=MODE.get(str(body.get("gameType")), ""),
        extra={"transport": "nethernet"},
    )


async def ask_bedrock(host: str, port: int, ctx: Context) -> Answer:
    """Both transports at once; the first real answer wins.

    ⚠️ Asked side by side, not one after the other: a server on the other
    transport would otherwise cost a full timeout on every refresh.
    """
    tasks = [asyncio.create_task(ask_nethernet(host, port, ctx)), asyncio.create_task(ask_raknet(host, port))]
    failures: list[BaseException] = []
    try:
        for next_done in asyncio.as_completed(tasks):
            try:
                return await next_done
            except (Offline, NotMinecraft, Silent) as error:
                failures.append(error)
    finally:
        for task in tasks:
            task.cancel()
    # Something that answers HTTP on the port but is no Bedrock server is a
    # wrong port, not a server that is down.
    if any(isinstance(one, NotMinecraft) for one in failures):
        raise NotMinecraft
    raise Offline


# -- the adapter -----------------------------------------------------------


class MinecraftAdapter(Adapter):
    kind = "minecraft"
    label = "Minecraft"
    category = "other"
    description = "Whether a Minecraft server is up, how many play on it, who they are and what the server says about itself."
    icon = "minecraft"
    beta = False
    docs_url = "https://minecraft.wiki/w/Java_Edition_protocol/Server_List_Ping"
    keywords = ("Java", "Bedrock", "Paper", "Spigot", "Server List Ping")
    fields = (
        Field("edition", "Edition", type="select", default="java",
              options=(("java", "Java Edition"), ("bedrock", "Bedrock Edition"))),
        Field("host", "Address", required=True, placeholder="minecraft.example.com",
              help="The host name or IP address of the server. No account is needed: the card asks what the game's server list asks."),
        Field("port", "Port", type="number",
              help="Empty means the edition's own: 25565 for Java, 19132 for Bedrock. SRV records are not followed."),
    )
    widgets = (
        WidgetType(kind="status", label="Minecraft server",
                   description="Online or offline, players and free slots, version, latency and the message of the day.",
                   renderer="value", default_size=(3, 2), refresh_seconds=60, metrics=("players_online", "latency_ms"),
                   parts=(("version", "Version"), ("latency", "Latency"), ("motd", "Message of the day"), ("world", "World"))),
        WidgetType(kind="players", label="Players online",
                   description="Who is playing right now, as far as the server tells. Bedrock servers never tell names.",
                   renderer="list", default_size=(2, 3), refresh_seconds=60),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        # A game server has no page to open.
        return ""

    async def _ask(self, config: dict[str, Any], ctx: Context) -> tuple[str, int, Answer]:
        edition, host, port = _settings(config)
        answer = await (ask_bedrock(host, port, ctx) if edition == "bedrock" else ask_java(host, port))
        return host, port, answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        edition, host, port = _settings(config)
        try:
            _, _, answer = await self._ask(config, ctx)
        except Offline as error:
            raise Unreachable(f"Nothing answers on {host}:{port}.") from error
        except Silent as error:
            raise AdapterError(f"{host}:{port} takes the connection but does not answer.", code="no_answer",
                               hint="A server that is still starting does this for a moment.") from error
        except NotMinecraft as error:
            raise _not_minecraft(edition) from error
        name = "Minecraft" if edition == "java" else "Bedrock"
        return f"{name} {answer.version or 'server'} answers with {answer.online} of {answer.slots} players."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        edition, host, port = _settings(config)
        try:
            _, _, answer = await self._ask(config, ctx)
        except Offline:
            return self._down(widget_kind, "Offline", "bad", f"Nothing answers on {host}:{port}.")
        except Silent:
            # ⚠️ What a starting server looks like for a second or so.
            return self._down(widget_kind, "No answer", "warn",
                              "The port takes the connection but the server says nothing; it may still be starting.")
        except NotMinecraft as error:
            raise _not_minecraft(edition) from error
        return self._players(answer) if widget_kind == "players" else self._status(answer)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _down(widget_kind: str, word: str, status: str, reason: str) -> WidgetData:
        if widget_kind == "players":
            return WidgetData(status=status, items=[], meta={"empty": reason})
        return WidgetData(status=status, primary={"label": "Server", "value": word},
                          meta={"status_reason": reason})

    @staticmethod
    def _status(answer: Answer) -> WidgetData:
        secondary: list[dict[str, Any]] = []
        if answer.version:
            secondary.append({"label": "Version", "value": answer.version, "part": "version"})
        if answer.latency is not None:
            secondary.append({"label": "Latency", "value": f"{round(answer.latency)} ms", "part": "latency"})
        if answer.motd:
            secondary.append({"label": "Message of the day", "value": answer.motd, "part": "motd"})
        world = " · ".join(one for one in (answer.world, answer.mode) if one)
        if world:
            secondary.append({"label": "World", "value": world, "part": "world"})
        return WidgetData(
            status="ok",
            primary={"label": "Players", "value": answer.online, "unit": f"/ {answer.slots}"},
            secondary=secondary,
            metrics=measured({"players_online": float(answer.online),
                              "latency_ms": None if answer.latency is None else round(answer.latency, 1)}),
            meta={"edition": answer.edition, **answer.extra},
        )

    @staticmethod
    def _players(answer: Answer) -> WidgetData:
        if answer.edition == "bedrock":
            # ⚠️ Neither transport names anybody.
            return WidgetData(status="ok", items=[], meta={
                "empty": "Nobody is playing." if not answer.online else "Bedrock servers do not say who is online.",
                "online": answer.online})
        sample = answer.sample or []
        named = [one for one in sample if one["id"] != NOBODY]
        anonymous = len(sample) - len(named)
        rows: list[dict[str, Any]] = [{"title": one["name"], "status": "ok"}
                                      for one in sorted(named, key=lambda one: one["name"].lower())]
        if anonymous:
            # ⚠️ "Allow Server Listings" switched off in their game.
            rows.append({"title": "Anonymous players", "subtitle": "They keep their name out of server lists.",
                         "value": str(anonymous), "status": "unknown"})
        rest = answer.online - len(sample)
        if sample and rest > 0:
            rows.append({"title": "More players", "subtitle": "The server lists only some of them.",
                         "value": str(rest), "status": "unknown"})
        if answer.online and not sample:
            # ⚠️ Missing with players on: hide-online-players, not an empty server.
            empty = "The server hides who is online."
        else:
            empty = "Nobody is playing."
        return WidgetData(status="ok", items=rows, meta={"empty": empty, "online": answer.online})

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        names = ["block_builder", "redstone_fan", "creeper_watch", "lava_surfer", "quiet_miner"]
        online = 1 + tick % len(names) if not fake.flicker("minecraft-empty", tick, 0.1) else 0
        answer = Answer(
            edition="java", online=online, slots=20, version="26.3",
            motd="A block_builder test world · Survival, no griefing",
            latency=fake.walk("minecraft-latency", tick, 3, 18),
            sample=[{"name": name, "id": f"00000000-0000-4000-8000-00000000000{index}"} for index, name in enumerate(names[:online])],
        )
        return self._players(answer) if widget_kind == "players" else self._status(answer)


def _not_minecraft(edition: str) -> AdapterError:
    return AdapterError(
        "Something answers on that port, but not a Minecraft server.", code="not_minecraft",
        hint="Check the port and the edition: Java listens on 25565 over TCP, Bedrock on 19132."
        if edition == "java" else "Check the port and the edition: Bedrock listens on 19132, Java on 25565.")


def _no_such_name(host: str) -> AdapterError:
    return AdapterError(f"The name {host} does not resolve.", code="unreachable", hint="Check the address of the server.")


ADAPTER = MinecraftAdapter()
