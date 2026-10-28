"""NUT, against the answers of a live upsd 2.8.2 with the dummy driver (27.10.2026).

The protocol is plain text over TCP, so the tests talk to a small server of their own on the loopback address
that plays the recorded answers back, line by line, the way upsd sends them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, WidgetData
from app.adapters.nut import NutAdapter, power_of, state_of

FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


ONLINE = recorded("nut_list_var_online.txt")
BATTERY = recorded("nut_list_var_battery.txt")
UPS_LIST = recorded("nut_list_ups.txt")


def parse(text: str) -> dict[str, str]:
    from app.adapters.nut import VAR_LINE, _unquote

    found = {}
    for line in text.splitlines():
        match = VAR_LINE.match(line)
        if match:
            found[match.group(2)] = _unquote(match.group(3))
    return found


class Upsd:
    """A server that answers like upsd: whatever ``answers`` maps a command to, ``ERR UNKNOWN-COMMAND`` otherwise."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.asked: list[str] = []
        self.connections = 0
        self.port = 0
        self.finished = asyncio.Event()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        while line := await reader.readline():
            command = line.decode().strip()
            self.asked.append(command)
            if command == "LOGOUT":
                writer.write(b"OK Goodbye\n")
                await writer.drain()
                break
            writer.write(self.answers.get(command, "ERR UNKNOWN-COMMAND\n").encode())
            await writer.drain()
        writer.close()
        self.finished.set()


@pytest.fixture
async def upsd() -> AsyncIterator[Callable[[dict[str, str]], Upsd]]:
    servers = []

    async def start(answers: dict[str, str]) -> Upsd:
        fake = Upsd(answers)
        server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
        fake.port = server.sockets[0].getsockname()[1]
        servers.append(server)
        return fake

    yield start  # type: ignore[misc]
    for server in servers:
        server.close()
        await server.wait_closed()


def config(fake: Upsd, **more: object) -> dict[str, object]:
    return {"host": "127.0.0.1", "port": fake.port, **more}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh(number: int = 1) -> Context:
    return Context(httpx.AsyncClient(), integration_id=number, widget_id=1, cache={})


async def test_the_ups_card_shows_charge_state_load_runtime_and_watts(upsd, ctx: Context) -> None:
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": ONLINE})
    data = await get_adapter("nut").fetch("ups", config(fake), {}, ctx)
    assert data.status == "ok" and data.primary == {"label": "Charge", "value": 100, "unit": "%"}
    assert data.secondary == [{"label": "State", "value": "On mains"}, {"label": "Load", "value": "18%"},
                              {"label": "Runtime", "value": "28m 30s"}, {"label": "Power", "value": "162 W"}]
    assert data.metrics == {"charge": 100.0, "load": 18.0, "runtime": 1710.0, "power": 162.0, "input_voltage": 231.0}
    # ⚠️ The adapter closes right after LOGOUT; the fake may not have read it yet.
    await asyncio.wait_for(fake.finished.wait(), 5)
    assert fake.asked == ["LIST UPS", "LIST VAR dummy", "LOGOUT"], "reading asks for nothing but the lists, and logs out"


async def test_on_battery_the_card_is_red_and_says_so(upsd) -> None:
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": BATTERY})
    data = await get_adapter("nut").fetch("ups", config(fake), {}, fresh())
    assert data.status == "bad" and data.meta == {"on_battery": True, "ups": "dummy"}
    assert data.secondary[0] == {"label": "State", "value": "On battery · Discharging"}
    assert data.primary["value"] == 96 and data.metrics["input_voltage"] == 0.0


async def test_power_and_details_cards(upsd) -> None:
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": ONLINE})
    power = await get_adapter("nut").fetch("power", config(fake), {}, fresh(1))
    assert power.primary == {"label": "Power", "value": 162.0, "unit": "W"}
    assert power.secondary[2] == {"label": "Input voltage", "value": "231 V"} and power.metrics == {"power": 162.0, "input_voltage": 231.0}
    details = await get_adapter("nut").fetch("details", config(fake), {}, fresh(2))
    rows = {row["label"]: row["value"] for row in details.secondary}
    assert rows["Model"] == "Example 1500VA" and rows["Output voltage"] == "230.0 V" and rows["Battery voltage"] == "27.3 V"
    assert rows["Temperature"] == "31.5 °C" and rows["Charge"] == "100%" and rows["Device"] == "dummy"


async def test_three_cards_on_one_connection_read_the_ups_once(upsd) -> None:
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": ONLINE})
    shared = fresh(5)
    for kind in ("ups", "power", "details"):
        await get_adapter("nut").fetch(kind, config(fake), {}, shared)
    assert fake.connections == 1


async def test_the_connection_test_names_the_model(upsd, ctx: Context) -> None:
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": ONLINE})
    assert await get_adapter("nut").test(config(fake), ctx) == "upsd answers for dummy (Example 1500VA)."
    several = UPS_LIST.replace("END LIST UPS", 'UPS second "Another"\nEND LIST UPS')
    fake = await upsd({"LIST UPS": several, "LIST VAR dummy": ONLINE})
    assert (await get_adapter("nut").test(config(fake), ctx)).endswith(", 2 UPS in all.")


async def test_the_named_ups_is_the_one_read(upsd) -> None:
    several = UPS_LIST.replace("END LIST UPS", 'UPS second "Another"\nEND LIST UPS')
    second = ONLINE.replace("VAR dummy ", "VAR second ").replace("LIST VAR dummy", "LIST VAR second").replace('"100"', '"55"')
    fake = await upsd({"LIST UPS": several, "LIST VAR dummy": ONLINE, "LIST VAR second": second})
    data = await get_adapter("nut").fetch("ups", config(fake, ups="second"), {}, fresh())
    assert data.primary["value"] == 55 and data.meta["ups"] == "second"
    assert "LIST VAR second" in fake.asked and "LIST VAR dummy" not in fake.asked
    with pytest.raises(AdapterError) as missing:
        await get_adapter("nut").fetch("ups", config(fake, ups="third"), {}, fresh(2))
    assert missing.value.code == "no_such_ups" and "dummy, second" in missing.value.hint
    for bad in ("two words", "a\nLIST", 'q"uote', "x" * 80):
        with pytest.raises(AdapterError) as refused:
            await get_adapter("nut").fetch("ups", config(fake, ups=bad), {}, fresh(3))
        assert refused.value.code == "bad_param", bad
    assert not any("two words" in line or "quote" in line for line in fake.asked), "a bad name never reaches the wire"


def test_charge_below_what_the_ups_calls_low_is_red_and_below_its_warning_yellow() -> None:
    low = {**parse(ONLINE), "battery.charge": "19"}
    assert NutAdapter._card("ups", "dummy", low).status == "bad"
    warning = {**parse(ONLINE), "battery.charge": "45"}
    assert NutAdapter._card("ups", "dummy", warning).status == "warn"
    assert NutAdapter._card("ups", "dummy", {**parse(ONLINE), "battery.charge": "51"}).status == "ok"
    # Without limits of its own, under half is a warning, like the UPS card through PeaNUT.
    bare = {"ups.status": "OL", "battery.charge": "40"}
    assert NutAdapter._card("ups", "ups", bare).status == "warn"


def test_a_ups_without_a_charge_is_not_at_zero() -> None:
    """⚠️ Small models keep battery.charge to themselves; a dial at 0 would read as an empty battery."""
    data = NutAdapter._card("ups", "ups", {"ups.status": "OL", "ups.load": "12"})
    assert data.primary == {"label": "Charge", "value": None, "unit": ""}
    assert "charge" not in data.metrics and data.metrics == {"load": 12.0}
    assert [row["value"] for row in data.secondary if row["label"] in ("Runtime", "Power")] == ["?", "?"]


def test_watts_are_what_the_ups_says_or_its_rated_watts_times_the_load() -> None:
    assert power_of({"ups.realpower": "162.4", "ups.load": "50", "ups.realpower.nominal": "900"}) == 162.4
    assert power_of({"ups.load": "20", "ups.realpower.nominal": "900"}) == 180.0
    # ⚠️ The VA rating is apparent power; it is not watts and is not made into them.
    assert power_of({"ups.load": "20", "ups.power.nominal": "1500"}) is None
    assert power_of({}) is None


def test_the_status_flags_in_words() -> None:
    assert state_of({"ups.status": "OL CHRG"}) == ("On mains · Charging", "warn", False)
    assert state_of({"ups.status": "OB DISCHRG LB"}) == ("On battery · Discharging · Battery low", "bad", True)
    assert state_of({"ups.status": "OL RB"})[1] == "bad"
    assert state_of({"ups.status": "OL SOMETHING"}) == ("On mains · SOMETHING", "warn", False)
    assert state_of({}) == ("Unknown", "warn", False)


def up(on_battery: bool, charge: int = 96) -> WidgetData:
    return NutAdapter._card("ups", "dummy", {**parse(ONLINE), "ups.status": "OB DISCHRG" if on_battery else "OL", "battery.charge": str(charge)})


def test_the_mains_going_away_and_coming_back_is_told_once_each() -> None:
    adapter = get_adapter("nut")
    [gone] = adapter.detect("ups", up(False), up(True), {})
    assert (gone.event, gone.level, gone.title, gone.key) == ("ups_on_battery", "bad", "dummy runs on battery", "ups_on_battery:dummy")
    assert gone.body == "charge 96%, about 28m 30s left"
    [back] = adapter.detect("ups", up(True), up(False, 91), {})
    assert (back.event, back.level, back.title, back.body) == ("ups_online", "ok", "dummy is back on mains", "charge 91%")
    assert adapter.detect("ups", up(True), up(True), {}) == []
    assert adapter.detect("ups", up(False), up(False), {}) == []
    # Not on the first look, not on a card with an error, not on the other cards of the same UPS.
    assert adapter.detect("ups", None, up(True), {}) == []
    assert adapter.detect("ups", up(False), WidgetData(error="unreachable"), {}) == []
    assert adapter.detect("details", up(False), up(True), {}) == []


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def test_a_port_nobody_listens_on(ctx: Context) -> None:
    with pytest.raises(Unreachable):
        await get_adapter("nut").fetch("ups", {"host": "127.0.0.1", "port": free_port()}, {}, ctx)


async def test_the_server_names_what_is_wrong(upsd) -> None:
    adapter = get_adapter("nut")
    # ⚠️ Measured: with the driver dead, upsd still lists the UPS and answers the variables with this.
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": "ERR DRIVER-NOT-CONNECTED\n"})
    with pytest.raises(AdapterError) as dead:
        await adapter.fetch("ups", config(fake), {}, fresh(1))
    assert dead.value.code == "nut_driver_not_connected" and "driver" in dead.value.message
    fake = await upsd({"LIST UPS": "ERR ACCESS-DENIED\n"})
    with pytest.raises(AuthFailed):
        await adapter.fetch("ups", config(fake), {}, fresh(2))
    fake = await upsd({"LIST UPS": "BEGIN LIST UPS\nEND LIST UPS\n"})
    with pytest.raises(AdapterError) as empty:
        await adapter.fetch("ups", config(fake), {}, fresh(3))
    assert empty.value.code == "no_device"
    fake = await upsd({"LIST VAR dummy": "ERR DATA-STALE\n", "LIST UPS": UPS_LIST})
    with pytest.raises(AdapterError) as stale:
        await adapter.fetch("ups", config(fake), {}, fresh(4))
    assert stale.value.code == "nut_data_stale"


async def test_something_that_is_not_upsd(upsd) -> None:
    fake = await upsd({"LIST UPS": "HTTP/1.1 400 Bad Request\n"})
    with pytest.raises(AdapterError) as web:
        await get_adapter("nut").fetch("ups", config(fake), {}, fresh())
    assert web.value.code == "not_nut" and "3493" in web.value.hint


async def test_a_line_about_another_ups_is_not_this_ups(upsd) -> None:
    mixed = ONLINE.replace("END LIST VAR dummy", 'VAR other battery.charge "1"\nEND LIST VAR dummy')
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": mixed})
    assert (await get_adapter("nut").fetch("ups", config(fake), {}, fresh())).primary["value"] == 100


async def test_values_with_quotes_and_backslashes_are_read_as_upsd_writes_them(upsd) -> None:
    text = 'BEGIN LIST VAR dummy\nVAR dummy device.model "The \\"Big\\" One \\\\ 2"\nVAR dummy ups.status "OL"\nEND LIST VAR dummy\n'
    fake = await upsd({"LIST UPS": UPS_LIST, "LIST VAR dummy": text})
    data = await get_adapter("nut").fetch("details", config(fake), {}, fresh())
    assert next(row["value"] for row in data.secondary if row["label"] == "Model") == 'The "Big" One \\ 2'


def test_the_address_may_be_typed_the_way_people_copy_it() -> None:
    from app.adapters.nut import _target

    assert _target({"host": "nut.example.com"}) == ("nut.example.com", 3493)
    assert _target({"host": "nut://nut.example.com:3500/"}) == ("nut.example.com", 3500)
    assert _target({"host": "nut.example.com", "port": "3600"}) == ("nut.example.com", 3600)
    for bad in ({"host": ""}, {"host": "nut.example.com", "port": "99999"}, {"host": "169.254.169.254"}):
        with pytest.raises(AdapterError):
            _target(bad)


def test_the_cards_have_demo_data_that_moves() -> None:
    adapter = get_adapter("nut")
    for widget in adapter.widgets:
        assert adapter.demo(widget.kind, {}, 0).error is None, widget.kind
    states = {adapter.demo("ups", {}, tick).status for tick in range(0, 3000, 5)}
    assert states >= {"ok", "bad"}, "the demo has an outage now and then"
    assert adapter.beta is True and not any(field.secret for field in adapter.fields)
