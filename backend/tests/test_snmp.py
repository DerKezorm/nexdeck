"""SNMP, against recorded answers of real switches and a live agent in this process.

The recordings under ``fixtures/snmp`` are excerpts of LibreNMS's test data,
cut to the OIDs nexdeck reads, plus two readings of a Net-SNMP agent taken by
the test bench itself. They are what an adapter for "every vendor" can be held
to without a rack of switches: eleven devices from eight makers, each with its
own idea of what a port is.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.adapters import snmp
from app.adapters import snmp_mib as mib
from app.adapters.base import AdapterError, Context

FIXTURES = Path(__file__).parent / "fixtures" / "snmp"


# ---------------------------------------------------------------------------
# Recorded answers
# ---------------------------------------------------------------------------


def read_snmprec(name: str) -> dict[str, Any]:
    """A ``.snmprec`` file as the plain values a walk would have handed back."""
    values: dict[str, Any] = {}
    for line in (FIXTURES / f"{name}.snmprec").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        oid, kind, value = line.split("|", 2)
        if kind == "4":
            values[oid] = value.encode()
        elif kind == "4x":
            values[oid] = bytes.fromhex(value)
        elif kind == "6":
            values[oid] = value
        elif kind == "64":
            values[oid] = value
        else:
            values[oid] = int(value)
    return values


class Recorded:
    """A ``Wire`` that answers from a recording instead of from the network."""

    def __init__(self, name: str, version: str = "2c") -> None:
        self.values = read_snmprec(name)
        self.version = version
        self.host = "203.0.113.7"
        self.port = 161
        self.asked: list[str] = []

    def load(self, name: str) -> None:
        self.values = read_snmprec(name)

    async def get(self, oids: tuple[str, ...]) -> dict[str, Any]:
        return {oid: self.values.get(oid) for oid in oids}

    async def walk(self, prefix: str) -> dict[str, Any]:
        self.asked.append(prefix)
        return {oid: value for oid, value in self.values.items()
                if oid.startswith(prefix + ".")}

    def close(self) -> None:
        return None


CONFIG = {"host": "203.0.113.7", "version": "2c", "community": "read-only"}


def context_with(wire: Recorded) -> Context:
    """A context that already holds the recording where the adapter looks for its wire."""
    return Context(httpx.AsyncClient(), cache={"snmp:wire": (snmp._fingerprint(CONFIG), wire)})


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second look at the counters is what the gap is for; the waiting is not."""
    monkeypatch.setattr(snmp, "FIRST_GAP", 0.0)


def ports_of(name: str) -> list[mib.Port]:
    return mib.front_ports(mib.parse_ports(read_snmprec(name)))


def test_a_cisco_stack_reads_as_one_switch() -> None:
    values = read_snmprec("ios_2960x")
    system = mib.add_entity(mib.parse_system(values), values)
    assert system.vendor == "Cisco"
    assert system.model == "WS-C2960X-48FPS-L"
    assert system.firmware == "15.0(2a)EX5"
    ports = ports_of("ios_2960x")
    # Three stack members with 48 ports each, their uplinks, and Fa0.
    assert len(ports) == 133
    first = next(port for port in ports if port.name == "Gi1/0/3")
    assert (first.up, first.speed, first.duplex, first.wide) == (True, 1000.0, "full", True)


def test_empty_stack_slots_are_not_ports() -> None:
    """⚠️ A Cisco SG350X with one member listed 216 ports, 188 of them notPresent."""
    values = read_snmprec("ciscosb_sg350x-24p")
    everything = mib.parse_ports(values)
    assert len([port for port in everything if port.physical]) > 200
    assert len(mib.front_ports(everything)) == 28
    assert mib.add_entity(mib.parse_system(values), values).model == "SG350X-24P-K9"


def test_a_switch_that_names_its_ports_by_number_gets_a_title() -> None:
    ports = ports_of("procurve_e2910")
    assert [port.name for port in ports[:2]] == ["1", "2"]
    assert mib.port_title(ports[0]) == "Port 1"
    assert mib.port_title(mib.Port(index=1, name="Gi1/0/1")) == "Gi1/0/1"


def test_a_unifi_switch_keeps_its_ports_out_of_the_interface_table() -> None:
    """⚠️ ifTable holds the Linux interfaces inside the switch, ifXTable the real ports."""
    ports = ports_of("edgeswitch_us-8")
    assert [port.name for port in ports] == [f"GigabitEthernet 1/{number}" for number in range(1, 9)]
    assert sum(1 for port in ports if port.up) == 2
    assert all(port.ether for port in ports)


def test_vlan_interfaces_that_call_themselves_ethernet_are_left_out() -> None:
    """TP-Link JetStream reports its VLAN interfaces with ifType 6."""
    ports = ports_of("jetstream_t1600g-28ts")
    assert not [port for port in ports if port.name.lower().startswith("vlan")]
    assert [port.name for port in ports if "Vlan-interface" in port.name] == []
    assert len(ports) == 32


def test_a_device_without_etherlike_keeps_every_ethernet_interface() -> None:
    """MikroTik fills no EtherLike-MIB, so the rule about it must not empty the card."""
    ports = ports_of("routeros_crs317")
    assert len(ports) == 19
    assert not any(port.ether for port in ports)


def test_the_vendor_comes_from_sysobjectid() -> None:
    for name, vendor in (("procurve_e2910", "HP"), ("jetstream_t1600g-28ts", "TP-Link"),
                         ("netgear_gs324tp", "Netgear"), ("zynos_xs1930-12hp", "Zyxel"),
                         ("routeros_crs317", "MikroTik"), ("edgeswitch_us-8", "Ubiquiti"),
                         ("arubaos-cx_10.16", "Aruba"), ("dlink_dgs-1510-28xmp-me", "D-Link")):
        assert mib.parse_system(read_snmprec(name)).vendor == vendor
    assert mib.vendor_of("1.3.6.1.4.1.99999.1") == ""
    assert mib.vendor_of("") == ""


def test_a_device_without_wide_counters_is_named_as_such() -> None:
    ports = ports_of("zynos_xs1930-12hp")
    assert ports and not any(port.wide for port in ports)


# ---------------------------------------------------------------------------
# PoE
# ---------------------------------------------------------------------------


def test_poe_in_milliwatts_is_recognised() -> None:
    """⚠️ A Netgear GS324TP reports a budget of 190 and a consumption of 3800."""
    poe = mib.parse_poe(read_snmprec("netgear_gs324tp"))
    assert (poe.budget, poe.used) == (190.0, 3.8)
    assert mib.parse_poe(read_snmprec("ios_2960x")).used == 115.0


def test_a_device_without_poe_says_so_instead_of_showing_nothing() -> None:
    data = snmp._poe(mib.parse_poe(read_snmprec("routeros_crs317")))
    assert data.status == "unknown"
    assert data.meta["empty"] == "This device reports no PoE through the standard MIB"
    assert data.secondary == [] and data.metrics == {}


def test_poe_ports_are_listed_with_what_they_deliver() -> None:
    poe = mib.parse_poe({
        f"{mib.PETH_PORT_ADMIN}.1.1": 1, f"{mib.PETH_PORT_DETECTION}.1.1": 3, f"{mib.PETH_PORT_CLASS}.1.1": 5,
        f"{mib.PETH_PORT_ADMIN}.1.2": 2, f"{mib.PETH_PORT_DETECTION}.1.2": 1,
        f"{mib.PETH_PORT_ADMIN}.1.3": 1, f"{mib.PETH_PORT_DETECTION}.1.3": 4,
        f"{mib.PETH_MAIN_POWER}.1": 65, f"{mib.PETH_MAIN_CONSUMPTION}.1": 30,
    })
    data = snmp._poe(poe)
    assert data.status == "bad"
    assert [(item["title"], item["subtitle"], item["status"]) for item in data.items] == [
        ("PoE port 1", "delivering power · class 4", "ok"),
        ("PoE port 2", "switched off", "unknown"),
        ("PoE port 3", "fault", "bad"),
    ]
    assert {"label": "Powered ports", "value": 1} in data.secondary


# ---------------------------------------------------------------------------
# LLDP
# ---------------------------------------------------------------------------


def test_neighbours_are_matched_by_the_name_the_device_gives_its_port() -> None:
    """Cisco SB says ``gi1/0/1`` in lldpLocPortId, which is its ifName."""
    values = read_snmprec("ciscosb_sg350x-24p")
    ports = mib.front_ports(mib.parse_ports(values))
    found = mib.parse_neighbours(values, ports)
    named = {next(port.name for port in ports if port.index == index): who for index, who in found.items()}
    assert named["gi1/0/14"] == "neighbour-1 (gi10)"
    assert set(named) == {"gi1/0/14", "gi1/0/16", "gi1/0/17", "te1/0/1", "te1/0/2"}


def test_neighbours_fall_back_to_the_port_number_as_an_ifindex() -> None:
    """ProCurve numbers its LLDP ports the way it numbers its interfaces."""
    values = read_snmprec("procurve_e2910")
    ports = mib.front_ports(mib.parse_ports(values))
    found = mib.parse_neighbours(values, ports)
    assert set(found) <= {port.index for port in ports}
    assert found


def test_the_name_beats_the_number_when_the_two_disagree() -> None:
    """⚠️ Cisco IOS numbers its LLDP ports 1, 2, 3 while its ifIndexes are
    10101, 10102. Taking the number for an ifIndex would hang the neighbour
    on whatever interface happens to carry that number, and on a stack that
    is a real port somewhere else."""
    ports = [mib.Port(index=10101, name="Gi1/0/1", type=6), mib.Port(index=10102, name="Gi1/0/2", type=6),
             mib.Port(index=1, name="Fa0", type=6)]
    values = {
        f"{mib.LLDP_LOC_PORT_ID}.1": b"Gi1/0/2",
        f"{mib.LLDP_REM_SYS_NAME}.0.1.1": b"router",
        f"{mib.LLDP_REM_PORT_DESC}.0.1.1": b"ether5",
    }
    assert mib.parse_neighbours(values, ports) == {10102: "router (ether5)"}


def test_a_neighbour_on_no_port_of_ours_is_dropped() -> None:
    ports = [mib.Port(index=1, name="Gi1/0/1")]
    values = {f"{mib.LLDP_REM_SYS_NAME}.0.9.1": b"router"}
    assert mib.parse_neighbours(values, ports) == {}


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


def _counters(port: mib.Port, at: float, uptime: float | None = 100.0) -> mib.Counters:
    return mib.counters_of([port], at, uptime)


def test_two_readings_of_a_real_agent_give_a_rate() -> None:
    first = mib.parse_ports(read_snmprec("netsnmp_bench_1"))
    second = mib.parse_ports(read_snmprec("netsnmp_bench_2"))
    before = mib.counters_of(first, 0.0, mib.parse_system(read_snmprec("netsnmp_bench_1")).agent_uptime)
    now = mib.counters_of(second, 20.2, mib.parse_system(read_snmprec("netsnmp_bench_2")).agent_uptime)
    rate = mib.rates(before, now, second)[2]
    assert rate.down is not None and rate.up is not None
    # 24978 -> 26739 octets in 20.2 seconds.
    assert round(rate.down) == round((26739 - 24978) * 8 / 20.2)
    assert rate.why == ""


def test_the_first_reading_says_so_instead_of_showing_zero() -> None:
    port = mib.Port(index=1, name="p", in_octets=10, out_octets=10, wide=True)
    rate = mib.rates(None, _counters(port, 0.0), [port])[1]
    assert (rate.down, rate.up, rate.why) == (None, None, "first reading")


def test_a_narrow_counter_that_went_round_once_is_still_read() -> None:
    port = mib.Port(index=1, name="p", speed=100.0, in_octets=100, out_octets=100, wide=False)
    before = _counters(mib.Port(index=1, name="p", in_octets=mib.WRAP_32 - 100, out_octets=0, wide=False), 0.0)
    rate = mib.rates(before, _counters(port, 10.0), [port])[1]
    assert rate.down == 200 * 8 / 10


def test_a_narrow_counter_on_a_fast_port_gives_no_rate() -> None:
    """⚠️ At 1 Gbit/s a 32-bit octet counter runs over after 34 seconds."""
    port = mib.Port(index=1, name="p", speed=1000.0, in_octets=100, out_octets=100, wide=False)
    before = _counters(mib.Port(index=1, name="p", in_octets=mib.WRAP_32 - 100, out_octets=0, wide=False), 0.0)
    rate = mib.rates(before, _counters(port, 60.0), [port])[1]
    assert (rate.down, rate.why) == (None, "counter too narrow")


def test_a_wide_counter_that_went_backwards_was_reset() -> None:
    port = mib.Port(index=1, name="p", in_octets=5, out_octets=5, wide=True)
    before = _counters(mib.Port(index=1, name="p", in_octets=900, out_octets=900, wide=True), 0.0)
    rate = mib.rates(before, _counters(port, 30.0), [port])[1]
    assert (rate.down, rate.why) == (None, "counter reset")


def test_a_restarted_agent_gives_no_rate() -> None:
    port = mib.Port(index=1, name="p", in_octets=5, out_octets=5, wide=True)
    before = _counters(mib.Port(index=1, name="p", in_octets=900, out_octets=900, wide=True), 0.0, uptime=5000.0)
    rate = mib.rates(before, _counters(port, 30.0, uptime=12.0), [port])[1]
    assert (rate.down, rate.why) == (None, "restarted")


def test_errors_count_only_what_came_in_between() -> None:
    port = mib.Port(index=1, name="p", in_errors=10, out_errors=2)
    before = mib.counters_of([mib.Port(index=1, name="p", in_errors=8, out_errors=2)], 0.0, 100.0)
    assert mib.new_errors(before, _counters(port, 30.0)) == {1: 2}
    # A counter that went backwards was reset, and a reset is not an error.
    assert mib.new_errors(_counters(port, 0.0), mib.counters_of(
        [mib.Port(index=1, name="p", in_errors=0, out_errors=0)], 30.0, 100.0)) == {}


def test_a_rate_is_written_in_bits() -> None:
    assert mib.bits_text(0) == "0 bit/s"
    assert mib.bits_text(1500) == "1.5 kbit/s"
    assert mib.bits_text(12_000_000) == "12 Mbit/s"
    assert mib.bits_text(2_500_000_000) == "2.5 Gbit/s"
    assert mib.bits_text(None) == "?"


def test_a_speed_beyond_the_32_bit_gauge_comes_from_ifhighspeed() -> None:
    assert mib._speed(10000, 4294967295) == 10000.0
    assert mib._speed(None, 4294967295) is None
    assert mib._speed(None, 100_000_000) == 100.0


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


async def test_every_card_of_a_real_switch_draws() -> None:
    wire = Recorded("ios_2960x")
    ctx = context_with(wire)
    overview = await snmp.ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert overview.primary == {"label": "Ports up", "value": "49 / 133"}
    assert {"label": "Firmware", "value": "15.0(2a)EX5", "part": "firmware"} in overview.secondary

    ports = await snmp.ADAPTER.fetch("ports", CONFIG, {}, ctx)
    row = next(item for item in ports.items if item["title"] == "Gi1/0/3")
    assert row["status"] == "ok" and "1 Gbit/s · full duplex" in row["subtitle"]
    assert ports.metrics == {"ports_up": 49.0}

    only_up = await snmp.ADAPTER.fetch("ports", CONFIG, {"hide_down": True}, ctx)
    assert len(only_up.items) == 49

    traffic = await snmp.ADAPTER.fetch("traffic", CONFIG, {"port": "Gi1/0/3"}, ctx)
    assert traffic.primary["label"] == "In"
    assert set(traffic.metrics) == {"down_bps", "up_bps"}

    poe = await snmp.ADAPTER.fetch("poe", CONFIG, {}, ctx)
    assert {"label": "Budget", "value": "370 W"} in poe.secondary


async def test_the_cards_of_one_device_share_one_reading() -> None:
    """Five cards on one switch must not be five walks of every column."""
    wire = Recorded("ios_2960x")
    ctx = context_with(wire)
    await snmp.ADAPTER.fetch("ports", CONFIG, {}, ctx)
    after_first = len(wire.asked)
    await snmp.ADAPTER.fetch("findings", CONFIG, {}, ctx)
    await snmp.ADAPTER.fetch("traffic", CONFIG, {"port": "Gi1/0/1"}, ctx)
    assert len(wire.asked) == after_first


async def test_a_port_that_is_gone_is_said_rather_than_drawn_empty() -> None:
    ctx = context_with(Recorded("ios_2960x"))
    with pytest.raises(AdapterError) as caught:
        await snmp.ADAPTER.fetch("traffic", CONFIG, {"port": "Gi9/0/9"}, ctx)
    assert caught.value.code == "no_port_picked"
    with pytest.raises(AdapterError):
        await snmp.ADAPTER.fetch("traffic", CONFIG, {}, ctx)


async def test_the_test_says_what_the_device_can_and_cannot_do() -> None:
    """⚠️ Whether the device has 64-bit counters decides whether its traffic
    cards can work at all, and it is the one thing nobody can see from outside."""
    wide = await snmp.ADAPTER.test(CONFIG, context_with(Recorded("ios_2960x")))
    assert "Cisco" in wide and "133 ports" in wide and "64-bit counters" in wide

    narrow = await snmp.ADAPTER.test(CONFIG, context_with(Recorded("zynos_xs1930-12hp")))
    assert "only 32-bit counters" in narrow and "16 ports" in narrow


async def test_the_port_picker_offers_what_the_device_has() -> None:
    ctx = context_with(Recorded("procurve_e2910"))
    offered = await snmp.ADAPTER.choices("port", CONFIG, ctx)
    assert offered[0][0] == "1" and offered[0][1].startswith("Port 1")
    assert len(offered) == 24


def test_findings_name_what_is_wrong() -> None:
    ports = [
        mib.Port(index=1, name="Gi1/0/1", alias="Uplink to router", type=6, oper="down"),
        mib.Port(index=2, name="Gi1/0/2", type=6, oper="up", speed=100.0, duplex="full"),
        mib.Port(index=3, name="Gi1/0/3", type=6, oper="up", speed=1000.0, duplex="half"),
        mib.Port(index=4, name="Gi1/0/4", type=6, oper="up", speed=1000.0, duplex="full"),
    ]
    reading = snmp.Reading(at=0, system=mib.System(name="core"), ports=ports, rates={},
                           counters=mib.Counters(at=0, agent_uptime=None))
    data = snmp._findings(reading, {4: 7}, {})
    assert data.status == "bad"
    assert [(item["title"], item["subtitle"]) for item in data.items] == [
        ("Gi1/0/1", "uplink is down"),
        ("Gi1/0/2", "runs at 100 Mbit/s"),
        ("Gi1/0/3", "half duplex"),
        ("Gi1/0/4", "7 errors in the last hour"),
    ]
    assert data.meta["uplinks_down"] == ["Gi1/0/1"]

    # With another port named as the uplink, the one that is down is just a
    # port with nothing plugged in; with the slow links switched off, only
    # what is really broken is left.
    quiet = snmp._findings(reading, {}, {"uplink": "Gi1/0/4", "slow": False})
    assert quiet.status == "warn"
    assert [item["title"] for item in quiet.items] == ["Gi1/0/3"]
    gone = snmp._findings(reading, {}, {"uplink": "Gi1/0/9", "slow": False})
    assert {"title": "Gi1/0/9", "subtitle": "uplink not on this device any more", "status": "warn"} in gone.items


def test_a_calm_device_says_what_it_looked_at() -> None:
    reading = snmp.Reading(at=0, system=mib.System(name="core"),
                           ports=[mib.Port(index=1, name="Gi1/0/1", type=6, oper="up", speed=1000.0)],
                           rates={}, counters=mib.Counters(at=0, agent_uptime=None))
    assert snmp._findings(reading, {}, {}).meta["empty"] == "core answers · 1 of 1 ports up · nothing to report"


def test_an_uplink_going_down_is_told_once() -> None:
    before = snmp.WidgetData(meta={"uplinks_down": [], "device": "core"})
    after = snmp.WidgetData(meta={"uplinks_down": ["Gi1/0/1"], "device": "core"})
    found = snmp.ADAPTER.detect("findings", before, after, {})
    assert [(one.event, one.title, one.level) for one in found] == [
        ("link_down", "Uplink Gi1/0/1 on core is down", "bad")]
    assert snmp.ADAPTER.detect("findings", after, after, {}) == []
    assert snmp.ADAPTER.detect("ports", before, after, {}) == []


def test_every_widget_draws_in_demo_mode() -> None:
    for widget in snmp.ADAPTER.widgets:
        data = snmp.ADAPTER.demo(widget.kind, {}, 3)
        assert data.status in ("ok", "warn", "bad", "unknown")
    assert snmp.ADAPTER.demo_choices("port")[0][0] == "Gi1/0/1"


# ---------------------------------------------------------------------------
# The wire, against an agent running in this process
# ---------------------------------------------------------------------------


def free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


@pytest.fixture
async def agent(monkeypatch: pytest.MonkeyPatch):
    """A real SNMP agent on loopback: the protocol is what the error messages are made of.

    ⚠️ Answers of a recording prove the parsing. They prove nothing about a
    wrong user name, a wrong password or a device that says nothing at all,
    and those are the sentences somebody reads when the card stays empty.
    """
    from pysnmp.carrier.asyncio.dgram import udp
    from pysnmp.entity import config, engine
    from pysnmp.entity.rfc3413 import cmdrsp, context

    # A device on the other side of the room answers in milliseconds; the one
    # in this process does too, and a test must not wait two seconds for
    # silence that will not end.
    monkeypatch.setattr(snmp, "TIMEOUT", 0.4)
    monkeypatch.setattr(snmp, "RETRIES", 0)
    port = free_port()
    served = engine.SnmpEngine()
    config.add_transport(served, udp.DOMAIN_NAME, udp.UdpTransport().open_server_mode(("127.0.0.1", port)))
    config.add_v1_system(served, "area", "bench-community")
    config.add_v3_user(served, "bench", config.USM_AUTH_HMAC96_SHA, "bench-auth-pass",
                       config.USM_PRIV_CFB128_AES, "bench-priv-pass")
    config.add_vacm_user(served, 2, "area", "noAuthNoPriv", (1, 3, 6), (1, 3, 6))
    config.add_vacm_user(served, 3, "bench", "authPriv", (1, 3, 6), (1, 3, 6))
    served_context = context.SnmpContext(served)
    cmdrsp.GetCommandResponder(served, served_context)
    cmdrsp.NextCommandResponder(served, served_context)
    cmdrsp.BulkCommandResponder(served, served_context)
    yield port
    served.close_dispatcher()


def loopback(port: int, **extra: Any) -> dict[str, Any]:
    return {"host": "127.0.0.1", "port": port, **extra}


async def probe(config: dict[str, Any]) -> Any:
    ctx = Context(httpx.AsyncClient(), cache={})
    try:
        return await snmp.ADAPTER.test(config, ctx)
    finally:
        await snmp.ADAPTER.close(config, ctx)


async def test_an_agent_answers_over_both_versions(agent: int) -> None:
    over_v2c = await probe(loopback(agent, version="2c", community="bench-community"))
    assert "SNMPv2c, unencrypted" in over_v2c
    over_v3 = await probe(loopback(agent, version="3", username="bench", auth_password="bench-auth-pass",
                                   priv_password="bench-priv-pass"))
    assert "SNMPv3" in over_v3 and "unencrypted" not in over_v3


async def test_a_silent_device_names_all_three_causes(agent: int) -> None:
    """⚠️ A wrong community and a closed port look exactly alike over v2c."""
    with pytest.raises(AdapterError) as caught:
        await probe(loopback(agent, version="2c", community="not-the-one"))
    assert caught.value.code == "unreachable"
    for cause in ("switched off", "access list", "community is wrong"):
        assert cause in caught.value.hint
    with pytest.raises(AdapterError) as closed:
        await probe(loopback(free_port(), version="2c", community="bench-community"))
    assert closed.value.code == "unreachable"


async def test_v3_says_which_of_the_three_credentials_is_wrong(agent: int) -> None:
    good = dict(version="3", username="bench", auth_password="bench-auth-pass", priv_password="bench-priv-pass")
    with pytest.raises(AdapterError) as unknown:
        await probe(loopback(agent, **{**good, "username": "nobody"}))
    assert unknown.value.code == "auth_failed" and "does not know the SNMPv3 user nobody" in unknown.value.message

    with pytest.raises(AdapterError) as digest:
        await probe(loopback(agent, **{**good, "auth_password": "wrong-auth-pass"}))
    assert "authentication password or protocol is wrong" in digest.value.message

    with pytest.raises(AdapterError) as privacy:
        await probe(loopback(agent, **{**good, "priv_password": "wrong-priv-pass"}))
    assert "encryption" in privacy.value.message

    with pytest.raises(AdapterError) as level:
        await probe(loopback(agent, **{**good, "priv_protocol": "none"}))
    assert "level of security" in level.value.message


async def test_a_device_that_only_stays_quiet_about_its_encryption_is_still_named() -> None:
    """⚠️ Net-SNMP answers a wrong encryption password with silence, measured
    on 22.09.2026. The difference from a device that is simply off is that the
    same user without encryption gets an answer."""
    wire = snmp.Wire({"host": "198.51.100.9", "version": "3", "username": "bench",
                      "auth_password": "bench-auth-pass", "priv_password": "bench-priv-pass"})

    async def answers(self: snmp.Wire) -> bool:
        return True

    snmp.Wire._answers_without_privacy = answers  # type: ignore[method-assign]
    try:
        with pytest.raises(AdapterError) as caught:
            await wire._explain("RequestTimedOut")
    finally:
        del snmp.Wire._answers_without_privacy
    assert caught.value.code == "auth_failed"
    assert "the encryption is not" in caught.value.message


async def test_a_short_password_is_refused_before_it_reaches_the_device(agent: int) -> None:
    with pytest.raises(AdapterError) as caught:
        await probe(loopback(agent, version="3", username="bench", auth_password="short",
                             priv_password="bench-priv-pass"))
    assert "eight characters" in caught.value.message


async def test_the_walk_stops_at_the_end_of_its_column(agent: int) -> None:
    wire = snmp.Wire(loopback(agent, version="2c", community="bench-community"))
    try:
        found = await wire.walk(mib.SYS_DESCR.removesuffix(".0"))
        assert list(found) == [mib.SYS_DESCR]
        system = mib.parse_system(await wire.get(mib.SYSTEM_OIDS))
        assert "PySNMP" in system.description and system.agent_uptime is not None
    finally:
        wire.close()


async def test_a_name_that_resolves_to_nothing_says_so() -> None:
    with pytest.raises(AdapterError) as caught:
        await probe({"host": "nothing.invalid", "version": "2c", "community": "x"})
    assert caught.value.code == "unreachable" and "does not resolve" in caught.value.message


# ---------------------------------------------------------------------------
# What the adapter may and may not do
# ---------------------------------------------------------------------------


def test_the_adapter_never_writes() -> None:
    """⚠️ Read only, and not as a promise in a docstring: an SNMP SET on a
    switch changes a port, a VLAN or the device's name."""
    source = (Path(snmp.__file__)).read_text(encoding="utf-8") + Path(mib.__file__).read_text(encoding="utf-8")
    for forbidden in ("set_cmd", "setCmd", "SET_CMD"):
        assert forbidden not in source
    assert snmp.ADAPTER.deeds == ()


def test_the_addresses_that_are_barred_everywhere_are_barred_here() -> None:
    for host in ("169.254.169.254", "fe80::1"):
        with pytest.raises(AdapterError):
            snmp._settings({"host": host})
    assert snmp._settings({"host": "http://switch.example.com/", "port": "161"}) == ("switch.example.com", 161, "3")
    with pytest.raises(AdapterError):
        snmp._settings({"host": "switch.example.com", "port": 99999})
    with pytest.raises(AdapterError):
        snmp._settings({"host": " "})


def test_the_adapter_stays_beta_until_a_real_switch_says_otherwise() -> None:
    """Recordings and an agent in this process are not a switch in a rack."""
    assert snmp.ADAPTER.beta is True


def test_the_vendors_people_search_for_lead_here() -> None:
    for vendor in ("cisco", "netgear", "tp-link", "zyxel", "hp", "aruba"):
        assert vendor in snmp.ADAPTER.keywords


async def test_a_second_connection_gets_its_own_wire() -> None:
    """The engine holds the SNMPv3 handshake of one device; two devices must not share it."""
    ctx = Context(httpx.AsyncClient(), cache={})
    first = snmp.ADAPTER._wire({"host": "203.0.113.7"}, ctx)
    assert snmp.ADAPTER._wire({"host": "203.0.113.7"}, ctx) is first
    second = snmp.ADAPTER._wire({"host": "203.0.113.8"}, ctx)
    assert second is not first
    await snmp.ADAPTER.close({"host": "203.0.113.8"}, ctx)
    assert "snmp:wire" not in ctx.cache


def test_nothing_waits_forever() -> None:
    assert snmp.TIMEOUT <= 5 and snmp.RETRIES <= 2 and snmp.MAX_ROWS <= 10000
    assert asyncio.iscoroutinefunction(snmp.Wire.walk)
