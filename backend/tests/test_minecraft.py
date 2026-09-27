"""Minecraft, against the answers of a vanilla Java server 26.3, Paper 26.2 and Bedrock 1.26.52 (27.09.2026).

The Java and RakNet sides are raw sockets, so the servers here are small
asyncio servers on 127.0.0.1 that answer with what the live ones sent.
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter, minecraft
from app.adapters.base import AdapterError, Context, Unreachable

ADAPTER = get_adapter("minecraft")
NOBODY = "00000000-0000-0000-0000-000000000000"
BUILDER = "11111111-2222-4333-8444-555555555555"
FAN = "66666666-7777-4888-9999-aaaaaaaaaaaa"

#: What vanilla 26.3 said with two players listed and one anonymous.
VANILLA = {
    "description": "§6Gold §lbold§r plain",
    "players": {"max": 12, "online": 3, "sample": [
        {"id": NOBODY, "name": "Anonymous Player"},
        {"id": FAN, "name": "redstone_fan"},
        {"id": BUILDER, "name": "block_builder"},
    ]},
    "version": {"name": "26.3", "protocol": 777},
}
#: Paper 26.2 with the same kind of message of the day.
PAPER_MOTD = {"text": "", "extra": [{"text": "Gold ", "extra": [{"text": "bold", "bold": True}], "color": "gold"}, " plain"]}
#: Bedrock 1.26.52 over NetherNet, GET /v1/join on the game port.
JOIN = {"name": "Redstone Test Realm", "protocol": 2193, "version": "1.26.52", "level": "flatland", "players": 0,
        "maxPlayers": 8, "gameType": 0}
#: The same server over RakNet; the server's own id is made up.
MCPE = "MCPE;Redstone Test Realm;2193;1.26.52;0;8;4242424242424242424;flatland;Survival;1;19132;19133;0;0;0;"

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(minecraft, "TIMEOUT", 0.4)


def packet(payload: bytes) -> bytes:
    return minecraft.varint(len(payload)) + payload


def string(text: str) -> bytes:
    raw = text.encode()
    return minecraft.varint(len(raw)) + raw


async def read_packet(reader: asyncio.StreamReader) -> bytes:
    length = shift = 0
    while True:
        byte = (await reader.readexactly(1))[0]
        length |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return await reader.readexactly(length)


def answering(status: Any, *, pong: bool = True, seen: dict[str, Any] | None = None) -> Handler:
    """A Java server as the live one behaved: status, then the ping echoed."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        handshake = await read_packet(reader)
        request = await read_packet(reader)
        if seen is not None:
            seen["handshake"], seen["request"] = handshake, request
        writer.write(packet(b"\x00" + string(json.dumps(status))))
        await writer.drain()
        if pong:
            ping = await read_packet(reader)
            if seen is not None:
                seen["ping"] = ping
            writer.write(packet(ping))
            await writer.drain()
        writer.close()

    return handle


class Listening:
    """A TCP server on 127.0.0.1 for as long as the block runs."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.port = 0

    async def __aenter__(self) -> Listening:
        async def guarded(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await self.handler(reader, writer)
            except (asyncio.IncompleteReadError, ConnectionError):
                pass

        self.server = await asyncio.start_server(guarded, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.server.close()


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def java(port: int) -> dict[str, Any]:
    return {"edition": "java", "host": "127.0.0.1", "port": port}


# -- Java --------------------------------------------------------------------


async def test_the_status_card_from_the_vanilla_answer(ctx: Context) -> None:
    seen: dict[str, Any] = {}
    async with Listening(answering(VANILLA, seen=seen)) as server:
        card = await ADAPTER.fetch("status", java(server.port), {}, ctx)
    assert card.status == "ok"
    assert card.primary == {"label": "Players", "value": 3, "unit": "/ 12"}
    rows = {row["part"]: row["value"] for row in card.secondary}
    assert rows["version"] == "26.3" and rows["motd"] == "Gold bold plain"
    assert rows["latency"].endswith(" ms") and "world" not in rows
    assert card.metrics["players_online"] == 3.0 and "latency_ms" in card.metrics
    # The handshake: id 0, protocol -1, the host as typed, the port, next state 1 (status).
    assert seen["handshake"] == b"\x00" + minecraft.varint(-1) + string("127.0.0.1") + struct.pack(">H", server.port) + b"\x01"
    assert seen["request"] == b"\x00"
    assert seen["ping"][:1] == b"\x01" and len(seen["ping"]) == 9


async def test_the_test_button_names_version_and_players(ctx: Context) -> None:
    async with Listening(answering(VANILLA)) as server:
        assert await ADAPTER.test(java(server.port), ctx) == "Minecraft 26.3 answers with 3 of 12 players."


def test_colour_codes_and_components_become_plain_text() -> None:
    # ⚠️ Vanilla: a string with the old codes; Paper: a component with extra.
    assert minecraft.plain(VANILLA["description"]) == "Gold bold plain"
    assert minecraft.plain(PAPER_MOTD) == "Gold bold plain"
    assert minecraft.plain("§x§a§b§c§d§e§fhex colour") == "hex colour"
    assert minecraft.plain([{"text": "A lobby"}, "\n", {"text": "§cline  two"}]) == "A lobby · line two"
    assert minecraft.plain(None) == "" and minecraft.plain(42) == ""


async def test_named_players_first_then_the_anonymous_and_the_rest(ctx: Context) -> None:
    status = {**VANILLA, "players": {**VANILLA["players"], "online": 17}}
    async with Listening(answering(status)) as server:
        card = await ADAPTER.fetch("players", java(server.port), {}, ctx)
    assert [(row["title"], row.get("value")) for row in card.items] == [
        ("block_builder", None),
        ("redstone_fan", None),
        # ⚠️ "Allow Server Listings" off: the id of all zeros.
        ("Anonymous players", "1"),
        # Seventeen online, three in the sample.
        ("More players", "14"),
    ]
    assert card.status == "ok"


async def test_hidden_players_are_not_an_empty_server(ctx: Context) -> None:
    # ⚠️ hide-online-players=true: two on, no sample at all.
    hidden = {**VANILLA, "players": {"max": 12, "online": 2}}
    async with Listening(answering(hidden)) as server:
        card = await ADAPTER.fetch("players", java(server.port), {}, ctx)
    assert card.items == [] and card.meta["empty"] == "The server hides who is online."
    empty = {**VANILLA, "players": {"max": 12, "online": 0}}
    async with Listening(answering(empty)) as server:
        card = await ADAPTER.fetch("players", java(server.port), {}, ctx)
    assert card.items == [] and card.meta["empty"] == "Nobody is playing."
    # An empty list with players on is hidden just the same.
    blank = {**VANILLA, "players": {"max": 12, "online": 2, "sample": []}}
    async with Listening(answering(blank)) as server:
        card = await ADAPTER.fetch("players", java(server.port), {}, ctx)
    assert card.meta["empty"] == "The server hides who is online."


async def test_a_server_without_the_ping_still_gets_a_latency(ctx: Context) -> None:
    async with Listening(answering(VANILLA, pong=False)) as server:
        card = await ADAPTER.fetch("status", java(server.port), {}, ctx)
    assert card.status == "ok" and "latency_ms" in card.metrics


async def test_offline_is_a_state_of_the_card_and_a_failure_of_the_test(ctx: Context, quick: None) -> None:
    config = java(free_port())
    card = await ADAPTER.fetch("status", config, {}, ctx)
    assert card.status == "bad" and card.primary == {"label": "Server", "value": "Offline"}
    assert card.metrics == {}, "a server that does not answer has no player count, not a zero"
    players = await ADAPTER.fetch("players", config, {}, ctx)
    assert players.status == "bad" and players.items == []
    with pytest.raises(Unreachable, match="Nothing answers"):
        await ADAPTER.test(config, ctx)


async def test_a_port_that_takes_the_connection_and_says_nothing(ctx: Context, quick: None) -> None:
    # ⚠️ A starting server: accepted, then closed without a byte.
    async def hang_up(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    async with Listening(hang_up) as server:
        card = await ADAPTER.fetch("status", java(server.port), {}, ctx)
        assert card.status == "warn" and card.primary == {"label": "Server", "value": "No answer"}
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.test(java(server.port), ctx)
    assert caught.value.code == "no_answer"

    async def mute(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(3)

    async with Listening(mute) as server:
        card = await ADAPTER.fetch("status", java(server.port), {}, ctx)
    assert card.status == "warn"


async def test_an_address_nobody_answers_at_is_offline(ctx: Context, quick: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(host: str, port: int) -> Any:
        await asyncio.sleep(5)

    monkeypatch.setattr(minecraft.asyncio, "open_connection", never)
    card = await ADAPTER.fetch("status", java(25565), {}, ctx)
    assert card.status == "bad"


@pytest.mark.parametrize("reply", [
    b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
    b"SSH-2.0-OpenSSH_9.2p1\r\n",
    # A length far beyond any status answer.
    minecraft.varint(50_000_000) + b"\x00",
    # The right packet id with text that is no JSON.
    packet(b"\x00" + string("not json")),
    # JSON, but not a status.
    packet(b"\x00" + string("[1, 2]")),
    # A whole status, but under a packet id that is not the status answer.
    packet(b"\x01" + string(json.dumps(VANILLA))),
])
async def test_another_service_on_the_port_is_named(ctx: Context, quick: None, reply: bytes) -> None:
    async def other(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(reply)
        await writer.drain()
        writer.close()

    async with Listening(other) as server:
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.fetch("status", java(server.port), {}, ctx)
    assert caught.value.code == "not_minecraft"


def test_host_and_port_as_people_type_them() -> None:
    assert minecraft._settings({"host": "minecraft://mc.example.com:25570"}) == ("java", "mc.example.com", 25570)
    assert minecraft._settings({"host": "mc.example.com"}) == ("java", "mc.example.com", 25565)
    assert minecraft._settings({"edition": "bedrock", "host": "mc.example.com"}) == ("bedrock", "mc.example.com", 19132)
    assert minecraft._settings({"host": "mc.example.com:1", "port": 25599}) == ("java", "mc.example.com", 25599)
    assert minecraft._settings({"host": "[2001:db8::7]", "port": 25565}) == ("java", "2001:db8::7", 25565)
    for broken in ({"host": ""}, {"host": "mc.example.com", "port": 70000}, {"host": "mc.example.com", "port": "abc"}):
        with pytest.raises(AdapterError):
            minecraft._settings(broken)
    # The same barred addresses as every other connection.
    with pytest.raises(AdapterError) as caught:
        minecraft._settings({"host": "169.254.169.254"})
    assert caught.value.code == "forbidden_host"


# -- Bedrock -----------------------------------------------------------------


class RakNetServer(asyncio.DatagramProtocol):
    """Answers an unconnected ping the way BDS 1.26.52 did with transport=raknet."""

    def __init__(self, motd: str = MCPE) -> None:
        self.motd = motd.encode()
        self.pings: list[bytes] = []

    def connection_made(self, transport: Any) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Any) -> None:
        self.pings.append(data)
        self.transport.sendto(b"\x1c" + data[1:9] + struct.pack(">q", 4242424242424242424) + minecraft.MAGIC
                              + struct.pack(">H", len(self.motd)) + self.motd, addr)


async def raknet(motd: str = MCPE) -> tuple[Any, RakNetServer, int]:
    transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: RakNetServer(motd), local_addr=("127.0.0.1", 0))
    return transport, protocol, transport.get_extra_info("sockname")[1]


def bedrock(port: int) -> dict[str, Any]:
    return {"edition": "bedrock", "host": "127.0.0.1", "port": port}


async def test_bedrock_over_nethernet(ctx: Context, quick: None) -> None:
    # ⚠️ The default transport: HTTP on the game port, the UDP ping unanswered.
    port = free_port(socket.SOCK_DGRAM)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"http://127.0.0.1:{port}/v1/join").mock(return_value=httpx.Response(200, json={**JOIN, "players": 3}))
        card = await ADAPTER.fetch("status", bedrock(port), {}, ctx)
        players = await ADAPTER.fetch("players", bedrock(port), {}, ctx)
        assert await ADAPTER.test(bedrock(port), ctx) == "Bedrock 1.26.52 answers with 3 of 8 players."
    assert card.primary == {"label": "Players", "value": 3, "unit": "/ 8"}
    assert {row["part"]: row["value"] for row in card.secondary if row["part"] != "latency"} == {
        "version": "1.26.52", "motd": "Redstone Test Realm", "world": "flatland · Survival"}
    assert card.meta["transport"] == "nethernet"
    # ⚠️ Bedrock names nobody.
    assert players.items == [] and players.meta["empty"] == "Bedrock servers do not say who is online."


async def test_bedrock_over_raknet(ctx: Context, quick: None) -> None:
    transport, server, port = await raknet()
    try:
        with respx.mock(assert_all_called=False) as mock:
            mock.get(f"http://127.0.0.1:{port}/v1/join").mock(side_effect=httpx.ConnectError("refused"))
            card = await ADAPTER.fetch("status", bedrock(port), {}, ctx)
            players = await ADAPTER.fetch("players", bedrock(port), {}, ctx)
    finally:
        transport.close()
    assert card.status == "ok" and card.meta["transport"] == "raknet"
    assert card.primary == {"label": "Players", "value": 0, "unit": "/ 8"}
    assert {row["part"]: row["value"] for row in card.secondary if row["part"] != "latency"} == {
        "version": "1.26.52", "motd": "Redstone Test Realm", "world": "flatland · Survival"}
    assert players.meta["empty"] == "Nobody is playing."
    # Unconnected ping: id 1, a time, the magic, a client id.
    ping = server.pings[0]
    assert ping[:1] == b"\x01" and ping[9:25] == minecraft.MAGIC and len(ping) == 33


async def test_bedrock_that_nobody_answers_for_is_offline(ctx: Context, quick: None) -> None:
    port = free_port(socket.SOCK_DGRAM)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"http://127.0.0.1:{port}/v1/join").mock(side_effect=httpx.ConnectTimeout("slow"))
        card = await ADAPTER.fetch("status", bedrock(port), {}, ctx)
        with pytest.raises(Unreachable):
            await ADAPTER.test(bedrock(port), ctx)
    assert card.status == "bad" and card.primary["value"] == "Offline"


@pytest.mark.parametrize("reply", [
    httpx.Response(404, text="Not Found"),
    httpx.Response(200, json={"status": "ok"}),
    httpx.Response(500, json=JOIN),
])
async def test_a_web_server_on_the_bedrock_port_is_named(ctx: Context, quick: None, reply: httpx.Response) -> None:
    port = free_port(socket.SOCK_DGRAM)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"http://127.0.0.1:{port}/v1/join").mock(return_value=reply)
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.fetch("status", bedrock(port), {}, ctx)
    assert caught.value.code == "not_minecraft"


@pytest.mark.parametrize("motd", ["SOMETHING;else", "GAME;Redstone Test Realm;2193;1.26.52;0;8;1;flatland;Survival;1;19132;19133;"])
async def test_a_raknet_answer_that_is_no_minecraft_is_not_taken(ctx: Context, quick: None, motd: str) -> None:
    transport, _server, port = await raknet(motd)
    try:
        with respx.mock(assert_all_called=False) as mock:
            mock.get(f"http://127.0.0.1:{port}/v1/join").mock(side_effect=httpx.ConnectError("refused"))
            with pytest.raises(AdapterError) as caught:
                await ADAPTER.fetch("status", bedrock(port), {}, ctx)
    finally:
        transport.close()
    assert caught.value.code == "not_minecraft"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(12):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary or card.meta.get("empty")
