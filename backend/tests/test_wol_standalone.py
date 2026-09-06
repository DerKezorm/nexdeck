"""Wake-on-LAN without a connection, and with the one that already exists.

A connection here meant one "integration" per machine before a single card
could exist. The card carries its own settings now. The awkward part is that
both have to work at once: cards built earlier hang off a connection and have
empty options.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=0, cache={})


WOL = get_adapter("wol")


def test_a_card_can_be_added_without_a_connection() -> None:
    """The whole point: one machine is one MAC, and that is a card's business."""
    assert WOL.needs_integration is False


def test_the_widget_offers_the_same_settings_the_connection_did() -> None:
    """Otherwise a card on its own could not be set up at all."""
    names = {field.name for field in WOL.widget("wake").options}
    assert {"mac", "host", "check_port", "broadcast", "port"} <= names


def test_the_card_wins_over_the_connection() -> None:
    """Somebody who edits the card means the card."""
    merged = WOL.settings({"mac": "00:00:00:00:00:01", "host": "old.example.com"}, {"mac": "00:00:00:00:00:02"})
    assert merged["mac"] == "00:00:00:00:00:02"
    assert merged["host"] == "old.example.com", "an untouched setting still comes from the connection"


def test_an_empty_option_does_not_blank_the_connection() -> None:
    """⚠️ Every card built before this adapter stood on its own has empty
    options. Letting an empty string win would have wiped their settings."""
    merged = WOL.settings({"mac": "00:00:00:00:00:01", "port": 9}, {"mac": "", "host": None, "broadcast": ""})
    assert merged["mac"] == "00:00:00:00:00:01"
    assert merged["port"] == 9


async def test_a_card_with_nothing_set_says_what_is_missing(ctx: Context) -> None:
    """Not "no data": the card has never been told which machine."""
    with pytest.raises(AdapterError) as raised:
        await WOL.fetch("wake", {}, {}, ctx)
    assert raised.value.code == "missing_mac"
    assert "MAC" in raised.value.message


async def test_a_card_on_its_own_reads_its_own_mac(ctx: Context) -> None:
    data = await WOL.fetch("wake", {}, {"mac": "00:1A:2B:3C:4D:5E"}, ctx)
    assert any(row["value"] == "00:1A:2B:3C:4D:5E" for row in data.secondary)


async def test_the_view_reaches_the_drawing(ctx: Context) -> None:
    """The renderer decides between the two looks from this."""
    plain = await WOL.fetch("wake", {}, {"mac": "00:1A:2B:3C:4D:5E"}, ctx)
    assert plain.meta["view"] == "detail", "the old look stays the default"
    big = await WOL.fetch("wake", {}, {"mac": "00:1A:2B:3C:4D:5E", "view": "icon"}, ctx)
    assert big.meta["view"] == "icon"


async def test_waking_uses_the_settings_of_the_card(ctx: Context) -> None:
    """The packet has to carry the card's address, not the connection's."""
    sent: list[tuple[bytes, str, int]] = []

    def record(packet: bytes, broadcast: str, port: int) -> None:
        sent.append((packet, broadcast, port))

    import app.adapters.wol as module

    original = module._send
    module._send = record
    try:
        answer = await WOL.action("wake", "wake", {}, {"mac": "00:00:00:00:00:01", "broadcast": "10.0.0.255"},
                                  {"mac": "00:1A:2B:3C:4D:5E", "broadcast": "192.0.2.255", "port": 9}, ctx)
    finally:
        module._send = original

    assert len(sent) == 1
    packet, broadcast, port = sent[0]
    assert broadcast == "192.0.2.255", "the card's broadcast, not the connection's"
    assert port == 9
    assert packet.startswith(b"\xff" * 6)
    assert packet[6:12] == bytes.fromhex("001A2B3C4D5E"), "the card's machine, not the connection's"
    assert "192.0.2.255" in answer


async def test_a_bad_mac_on_the_card_is_refused(ctx: Context) -> None:
    with pytest.raises(AdapterError) as raised:
        await WOL.action("wake", "wake", {}, {}, {"mac": "not a mac"}, ctx)
    assert raised.value.code == "bad_mac"


def test_the_demo_carries_the_view_too() -> None:
    """A card in the library preview has to draw the way it was chosen."""
    assert WOL.demo("wake", {}, 0).meta["view"] == "detail"
    assert WOL.demo("wake", {"view": "icon"}, 0).meta["view"] == "icon"


def test_every_view_the_field_offers_is_one_the_card_knows() -> None:
    """A choice in the settings that the drawing ignores is a dead control."""
    field = next(f for f in WOL.widget("wake").options if f.name == "view")
    offered = {value for value, _label in field.options}
    assert offered == {"detail", "icon"}


async def test_the_connection_still_carries_a_card_that_has_no_options(ctx: Context) -> None:
    """The card that exists today. It must not break."""
    data = await WOL.fetch("wake", {"mac": "00:1A:2B:3C:4D:5E", "broadcast": "255.255.255.255"}, {}, ctx)
    assert any(row["value"] == "00:1A:2B:3C:4D:5E" for row in data.secondary)
    assert data.actions and data.actions[0].id == "wake"


def _library_haystack(adapter: Any, widget: Any) -> str:
    """What the widget library searches, mirrored here.

    The list itself is built in the browser; this is the promise the backend
    has to keep for it: the technical name is part of what is offered.
    """
    return f"{adapter.kind} {widget.kind} {adapter.label}".lower()


def test_the_library_can_find_the_card_by_its_technical_name() -> None:
    """⚠️ "Wake-on-LAN" does not contain "wol", which is what somebody types."""
    assert "wol" in _library_haystack(WOL, WOL.widget("wake"))
    assert "wol" not in WOL.label.lower(), "if the label ever contains it, this test proves nothing"
