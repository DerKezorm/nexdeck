"""What the standard MIBs say, read without the network.

Everything in here takes the plain values a walk handed back, ``{oid: value}``
with the numeric OID as a dotted string, and turns them into ports, rates and
findings. Nothing here knows about pysnmp, which is what lets the tests feed it
recorded answers of real switches instead of a switch.

⚠️ Standard MIBs only: SNMPv2-MIB, IF-MIB, EtherLike-MIB, ENTITY-MIB,
POWER-ETHERNET-MIB and LLDP-MIB. A vendor is recognised from sysObjectID and
named, never read: every vendor MIB is a second adapter hiding inside this one,
and none of them can be tested without that vendor's switch on the desk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# -- SNMPv2-MIB, HOST-RESOURCES-MIB ------------------------------------------

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
#: The device's own uptime. sysUpTime is the agent's, which restarts with
#: the SNMP service and says nothing about the switch; many switches have
#: only that one, so this is asked for and used when it comes.
HR_SYSTEM_UPTIME = "1.3.6.1.2.1.25.1.1.0"
SYSTEM_OIDS = (SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_CONTACT, SYS_NAME, SYS_LOCATION, HR_SYSTEM_UPTIME)

# -- IF-MIB ------------------------------------------------------------------

IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_SPEED = "1.3.6.1.2.1.2.2.1.5"
IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"
IF_OPER = "1.3.6.1.2.1.2.2.1.8"
IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10"
IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"
IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_HC_IN_OCTETS = "1.3.6.1.2.1.31.1.1.1.6"
IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10"
IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
#: EtherLike-MIB, indexed by ifIndex like the rest.
DOT3_DUPLEX = "1.3.6.1.2.1.10.7.2.1.19"

#: The columns one reading walks, in the order it walks them.
#:
#: ⚠️ The 64-bit counters come first and the 32-bit ones are read as well.
#: At 1 Gbit/s a 32-bit octet counter runs over after about 34 seconds, which
#: is the refresh of a card: a rate from those two numbers is a guess about
#: how many times it went round. They are kept for the ports that have no
#: 64-bit counter, and for those the card says what that means.
PORT_COLUMNS = (
    IF_DESCR, IF_TYPE, IF_SPEED, IF_ADMIN, IF_OPER,
    IF_NAME, IF_ALIAS, IF_HIGH_SPEED,
    IF_HC_IN_OCTETS, IF_HC_OUT_OCTETS, IF_IN_OCTETS, IF_OUT_OCTETS,
    IF_IN_ERRORS, IF_OUT_ERRORS,
    DOT3_DUPLEX,
)
COUNTER_COLUMNS = (IF_HC_IN_OCTETS, IF_HC_OUT_OCTETS, IF_IN_OCTETS, IF_OUT_OCTETS)

#: ifType values that are a socket on the front of the box, or a bundle of
#: them. ethernetCsmacd (6) is what nearly every switch says for every port;
#: the others are older or rarer spellings of the same. 161 is a link
#: aggregation, which is where uplinks tend to live.
PORT_TYPES = frozenset({6, 7, 62, 69, 117, 161})
LAG_TYPE = 161

OPER_STATES = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "notPresent", 7: "lowerLayerDown"}
ADMIN_STATES = {1: "up", 2: "down", 3: "testing"}
DUPLEX = {2: "half", 3: "full"}

WRAP_32 = 2 ** 32

# -- ENTITY-MIB ----------------------------------------------------------------

ENT_CLASS = "1.3.6.1.2.1.47.1.1.1.1.5"
ENT_SOFTWARE = "1.3.6.1.2.1.47.1.1.1.1.10"
ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
ENT_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13"
ENT_FIRMWARE = "1.3.6.1.2.1.47.1.1.1.1.9"
ENT_CHASSIS = 3

# -- POWER-ETHERNET-MIB (RFC 3621) ---------------------------------------------

PETH_PORT_ADMIN = "1.3.6.1.2.1.105.1.1.1.3"
PETH_PORT_DETECTION = "1.3.6.1.2.1.105.1.1.1.6"
PETH_PORT_CLASS = "1.3.6.1.2.1.105.1.1.1.10"
PETH_MAIN_POWER = "1.3.6.1.2.1.105.1.3.1.1.2"
PETH_MAIN_STATUS = "1.3.6.1.2.1.105.1.3.1.1.3"
PETH_MAIN_CONSUMPTION = "1.3.6.1.2.1.105.1.3.1.1.4"
POE_COLUMNS = (PETH_MAIN_POWER, PETH_MAIN_STATUS, PETH_MAIN_CONSUMPTION,
               PETH_PORT_ADMIN, PETH_PORT_DETECTION, PETH_PORT_CLASS)
POE_DETECTION = {1: "disabled", 2: "searching", 3: "delivering power", 4: "fault", 5: "test", 6: "fault"}

# -- LLDP-MIB (IEEE 802.1AB-2005) ----------------------------------------------

LLDP_LOC_PORT_ID = "1.0.8802.1.1.2.1.3.7.1.3"
LLDP_LOC_PORT_DESC = "1.0.8802.1.1.2.1.3.7.1.4"
LLDP_REM_CHASSIS = "1.0.8802.1.1.2.1.4.1.1.5"
LLDP_REM_PORT_ID = "1.0.8802.1.1.2.1.4.1.1.7"
LLDP_REM_PORT_DESC = "1.0.8802.1.1.2.1.4.1.1.8"
LLDP_REM_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"
LLDP_COLUMNS = (LLDP_LOC_PORT_ID, LLDP_LOC_PORT_DESC, LLDP_REM_SYS_NAME, LLDP_REM_CHASSIS,
                LLDP_REM_PORT_DESC, LLDP_REM_PORT_ID)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

#: IANA private enterprise numbers, the number after 1.3.6.1.4.1 in sysObjectID.
#:
#: ⚠️ Recognised, never trusted for more than the name. 4413 is Broadcom's
#: switch software, which is also what older UniFi and EdgeSwitch models
#: report; 8072 is Net-SNMP, which is what any Linux box says, UniFi's newer
#: switches included. Both are named for what they are.
VENDORS: dict[int, str] = {
    9: "Cisco",
    11: "HP",
    43: "3Com",
    171: "D-Link",
    207: "Allied Telesis",
    674: "Dell",
    890: "Zyxel",
    1916: "Extreme Networks",
    1991: "Brocade",
    2011: "Huawei",
    2636: "Juniper",
    3955: "Linksys",
    4413: "Broadcom",
    4526: "Netgear",
    6027: "Dell",
    6574: "Synology",
    8072: "Net-SNMP",
    11863: "TP-Link",
    12356: "Fortinet",
    14823: "Aruba",
    14988: "MikroTik",
    24681: "QNAP",
    25506: "H3C",
    30065: "Arista",
    41112: "Ubiquiti",
    47196: "Aruba",
}

ENTERPRISES = (1, 3, 6, 1, 4, 1)


def vendor_of(sys_object_id: Any) -> str:
    """Who made it, from sysObjectID, or ``""`` when the number is not one we know."""
    parts = oid_parts(str(sys_object_id or ""))
    if len(parts) <= len(ENTERPRISES) or parts[: len(ENTERPRISES)] != ENTERPRISES:
        return ""
    return VENDORS.get(parts[len(ENTERPRISES)], "")


# ---------------------------------------------------------------------------
# Plain values
# ---------------------------------------------------------------------------


def oid_parts(oid: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in oid.strip().strip(".").split(".") if part != "")
    except ValueError:
        return ()


def column(values: dict[str, Any], prefix: str) -> dict[tuple[int, ...], Any]:
    """One column of a table: ``{index: value}`` for every OID under ``prefix``."""
    base = oid_parts(prefix)
    found: dict[tuple[int, ...], Any] = {}
    for oid, value in values.items():
        parts = oid_parts(oid)
        if len(parts) > len(base) and parts[: len(base)] == base:
            found[parts[len(base):]] = value
    return found


def text(value: Any) -> str:
    """An OCTET STRING as the text it almost always is.

    Some agents pad with NUL bytes, some send Latin-1. A value that is not
    text at all (a MAC address) comes out as colon-separated hex, which is
    how every switch's own web page writes it.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().strip("\x00").strip()
    if isinstance(value, bytes):
        raw = value.rstrip(b"\x00")
        if raw and any(byte < 32 and byte not in (9, 10, 13) for byte in raw):
            return mac(raw)
        try:
            return raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return raw.decode("latin-1").strip()
    return str(value).strip()


def mac(raw: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in raw)


def number(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@dataclass
class System:
    name: str = ""
    description: str = ""
    object_id: str = ""
    vendor: str = ""
    location: str = ""
    contact: str = ""
    #: Seconds. The device's when it has HOST-RESOURCES-MIB, the agent's otherwise.
    uptime: float | None = None
    #: sysUpTime in seconds, always the agent's: a restart of the agent resets the counters too.
    agent_uptime: float | None = None
    model: str = ""
    firmware: str = ""
    serial: str = ""


def parse_system(values: dict[str, Any]) -> System:
    ticks = number(values.get(SYS_UPTIME))
    host_ticks = number(values.get(HR_SYSTEM_UPTIME))
    object_id = str(values.get(SYS_OBJECT_ID) or "")
    agent = ticks / 100 if ticks is not None else None
    return System(
        name=text(values.get(SYS_NAME)),
        description=text(values.get(SYS_DESCR)),
        object_id=object_id,
        vendor=vendor_of(object_id),
        location=text(values.get(SYS_LOCATION)),
        contact=text(values.get(SYS_CONTACT)),
        uptime=host_ticks / 100 if host_ticks is not None else agent,
        agent_uptime=agent,
    )


def add_entity(system: System, values: dict[str, Any]) -> System:
    """Model, firmware and serial number from ENTITY-MIB, where the device has it.

    The first chassis wins. A stack reports one per member, and the first is
    the one whose firmware the others run.
    """
    classes = column(values, ENT_CLASS)
    chassis = sorted(index for index, kind in classes.items() if number(kind) == ENT_CHASSIS)
    if not chassis:
        return system
    index = chassis[0]
    model = text(column(values, ENT_MODEL).get(index))
    software = text(column(values, ENT_SOFTWARE).get(index)) or text(column(values, ENT_FIRMWARE).get(index))
    system.model = model or system.model
    system.firmware = software or system.firmware
    system.serial = text(column(values, ENT_SERIAL).get(index)) or system.serial
    return system


def short_description(description: str, limit: int = 80) -> str:
    """The first line of sysDescr, which is where every vendor puts the product."""
    line = description.replace("\r", "\n").split("\n", 1)[0].strip()
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------


@dataclass
class Port:
    index: int
    name: str
    description: str = ""
    alias: str = ""
    type: int = 0
    admin: str = "up"
    oper: str = "unknown"
    #: Mbit/s, only meaningful while the link is up.
    speed: float | None = None
    duplex: str = ""
    in_octets: int | None = None
    out_octets: int | None = None
    #: True when the octets came from the 64-bit counters.
    wide: bool = False
    in_errors: int | None = None
    out_errors: int | None = None
    #: True when EtherLike-MIB has a row for it, which only real Ethernet ports have.
    ether: bool = False

    @property
    def up(self) -> bool:
        return self.oper == "up"

    @property
    def enabled(self) -> bool:
        return self.admin == "up"

    @property
    def physical(self) -> bool:
        return self.type in PORT_TYPES

    @property
    def lag(self) -> bool:
        return self.type == LAG_TYPE


def parse_ports(values: dict[str, Any]) -> list[Port]:
    """Every interface the device lists, in ifIndex order."""
    descr = column(values, IF_DESCR)
    kinds = column(values, IF_TYPE)
    speeds = column(values, IF_SPEED)
    admins = column(values, IF_ADMIN)
    opers = column(values, IF_OPER)
    names = column(values, IF_NAME)
    aliases = column(values, IF_ALIAS)
    high = column(values, IF_HIGH_SPEED)
    hc_in = column(values, IF_HC_IN_OCTETS)
    hc_out = column(values, IF_HC_OUT_OCTETS)
    lo_in = column(values, IF_IN_OCTETS)
    lo_out = column(values, IF_OUT_OCTETS)
    in_errors = column(values, IF_IN_ERRORS)
    out_errors = column(values, IF_OUT_ERRORS)
    duplex = column(values, DOT3_DUPLEX)

    indexes = sorted({key for key in (*descr, *names, *opers) if len(key) == 1})
    ports: list[Port] = []
    for key in indexes:
        wide = hc_in.get(key) is not None and hc_out.get(key) is not None
        kind = number(kinds.get(key))
        oper = OPER_STATES.get(number(opers.get(key)) or 0, "unknown")
        if kind is None and key in duplex:
            # ⚠️ Measured in a recording of a UniFi US-8 (firmware 5.76):
            # ifTable holds only the Linux interfaces inside the switch, and
            # the eight real ports exist in ifXTable and EtherLike-MIB alone.
            # EtherLike says the port is Ethernet, and a known duplex says it
            # has a link: RFC 3635 reports "unknown" for a port that is down.
            kind = 6
            if key not in opers:
                oper = "up" if number(duplex.get(key)) in DUPLEX else "down"
        ports.append(Port(
            index=key[0],
            name=text(names.get(key)) or text(descr.get(key)) or f"Interface {key[0]}",
            description=text(descr.get(key)),
            alias=text(aliases.get(key)),
            type=kind or 0,
            admin=ADMIN_STATES.get(number(admins.get(key)) or 0, "up"),
            oper=oper,
            speed=_speed(number(high.get(key)), number(speeds.get(key))),
            duplex=DUPLEX.get(number(duplex.get(key)) or 0, ""),
            in_octets=number(hc_in.get(key)) if wide else number(lo_in.get(key)),
            out_octets=number(hc_out.get(key)) if wide else number(lo_out.get(key)),
            wide=wide,
            in_errors=number(in_errors.get(key)),
            out_errors=number(out_errors.get(key)),
            ether=key in duplex,
        ))
    return ports


def _speed(high: int | None, low: int | None) -> float | None:
    """Mbit/s, from ifHighSpeed where there is one.

    ⚠️ ifSpeed is a 32-bit gauge in bit/s and stops at 4,294,967,295, so a
    10 Gbit port reads as 4.3 Gbit/s there. ifHighSpeed is in Mbit/s and has
    no such ceiling.
    """
    if high:
        return float(high)
    if low:
        if low >= WRAP_32 - 1:
            return None
        return low / 1_000_000
    return None


def speed_text(mbit: float | None) -> str:
    if not mbit:
        return ""
    if mbit >= 1000:
        return f"{mbit / 1000:g} Gbit/s"
    return f"{mbit:g} Mbit/s"


def bits_text(bits_per_second: float | None) -> str:
    """A rate as a network person reads it: in bits, in powers of a thousand."""
    if bits_per_second is None:
        return "?"
    value = float(bits_per_second)
    for unit in ("bit/s", "kbit/s", "Mbit/s", "Gbit/s"):
        if value < 1000 or unit == "Gbit/s":
            return f"{value:.0f} {unit}" if unit == "bit/s" or value >= 10 else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} Gbit/s"


def front_ports(ports: list[Port]) -> list[Port]:
    """The sockets on the box, and the bundles made of them.

    ⚠️ Several kinds of interface claim to be ports and are not, all measured
    in recordings of real switches. A stackable switch lists every port of
    every stack member it could have, and the missing ones say
    ``notPresent``: a Cisco SG350X with one member listed 216 ports, 188 of
    them not there. TP-Link JetStream reports its VLAN interfaces as
    Ethernet, and a UniFi switch its Linux interfaces inside (``vtss.ifh``,
    ``vtss.vlan.2``). Neither has a row in EtherLike-MIB, which every real
    port on those devices has; so on a device that fills EtherLike-MIB at
    all, only what is in it counts, bundles aside. MikroTik fills none of
    it, and there every Ethernet interface stays.
    """
    ether_like = any(port.ether for port in ports)
    return [
        port for port in ports
        if port.physical and port.oper != "notPresent"
        and (port.ether or port.lag or not ether_like)
        and not port.name.lower().startswith("vlan")
    ]


def port_title(port: Port) -> str:
    """HP and Aruba call their ports "1", "2": a row titled 1 is a number, not a port."""
    return f"Port {port.name}" if port.name.isdigit() else port.name


def is_uplink(port: Port, picked: str) -> bool:
    """The port named in the card, or one somebody described as an uplink on the switch."""
    if picked:
        return port.name == picked
    return "uplink" in port.alias.lower()


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


@dataclass
class Counters:
    """The counters of one moment, kept for the next reading to subtract from."""

    at: float
    agent_uptime: float | None
    octets: dict[int, tuple[int | None, int | None, bool]] = field(default_factory=dict)
    errors: dict[int, int] = field(default_factory=dict)


def counters_of(ports: list[Port], at: float, agent_uptime: float | None) -> Counters:
    return Counters(
        at=at,
        agent_uptime=agent_uptime,
        octets={port.index: (port.in_octets, port.out_octets, port.wide) for port in ports},
        errors={port.index: (port.in_errors or 0) + (port.out_errors or 0)
                for port in ports if port.in_errors is not None or port.out_errors is not None},
    )


@dataclass
class Rate:
    #: bit/s, or None when the two readings cannot say.
    down: float | None
    up: float | None
    #: Why there is no number, in a word the card can show.
    why: str = ""


def _delta(old: int | None, new: int | None, wide: bool, seconds: float, speed_mbit: float | None) -> int | None:
    if old is None or new is None:
        return None
    if new >= old:
        delta = new - old
    elif wide:
        # A 64-bit counter does not run over in the life of a switch; going
        # down means it was reset.
        return None
    else:
        delta = new + WRAP_32 - old
    if not wide:
        # ⚠️ One wrap can be seen, two cannot. If the link is fast enough to
        # have gone round more than once between the readings, any number
        # here is a guess, and the card says so instead of showing it.
        most = (speed_mbit or 0) * 1_000_000 / 8 * seconds
        if most >= WRAP_32:
            return None
    return delta


def rates(before: Counters | None, now: Counters, ports: list[Port]) -> dict[int, Rate]:
    """Bit/s per port between two readings."""
    found: dict[int, Rate] = {}
    if before is None:
        return {port.index: Rate(None, None, "first reading") for port in ports}
    seconds = now.at - before.at
    restarted = (
        before.agent_uptime is not None and now.agent_uptime is not None
        and now.agent_uptime + 1 < before.agent_uptime
    )
    for port in ports:
        if seconds <= 0 or restarted:
            found[port.index] = Rate(None, None, "restarted" if restarted else "first reading")
            continue
        old = before.octets.get(port.index)
        new = now.octets.get(port.index)
        if not old or not new or old[2] != new[2]:
            found[port.index] = Rate(None, None, "first reading")
            continue
        wide = new[2]
        down = _delta(old[0], new[0], wide, seconds, port.speed)
        up = _delta(old[1], new[1], wide, seconds, port.speed)
        why = "" if down is not None and up is not None else ("counter too narrow" if not wide else "counter reset")
        found[port.index] = Rate(
            down * 8 / seconds if down is not None else None,
            up * 8 / seconds if up is not None else None,
            why,
        )
    return found


def new_errors(before: Counters | None, now: Counters) -> dict[int, int]:
    """Errors that appeared between two readings, per port. A counter that went down was reset."""
    if before is None:
        return {}
    found = {}
    for index, count in now.errors.items():
        old = before.errors.get(index)
        if old is not None and count > old:
            found[index] = count - old
    return found


# ---------------------------------------------------------------------------
# LLDP
# ---------------------------------------------------------------------------


def parse_neighbours(values: dict[str, Any], ports: list[Port]) -> dict[int, str]:
    """``{ifIndex: "neighbour name (its port)"}`` from LLDP, where the device reports it.

    ⚠️ LLDP numbers its ports its own way. The local port is found by the
    name the device gives it in lldpLocPortId or lldpLocPortDesc, and only
    when neither matches an interface does the number itself count as an
    ifIndex, which is what most switches use. Measured in recordings: Cisco
    SB names it ``gi1/0/1``, ProCurve and Juniper give the ifIndex, D-Link
    gives a MAC address and puts the name nowhere.
    """
    if not ports:
        return {}
    by_name: dict[str, int] = {}
    for port in ports:
        for label in (port.name, port.description, port.alias):
            if label:
                by_name.setdefault(label.lower(), port.index)
    indexes = {port.index for port in ports}
    local: dict[int, int] = {}
    ids = column(values, LLDP_LOC_PORT_ID)
    descs = column(values, LLDP_LOC_PORT_DESC)
    for key in {*ids, *descs}:
        if len(key) != 1:
            continue
        for label in (text(descs.get(key)), text(ids.get(key))):
            if label and label.lower() in by_name:
                local[key[0]] = by_name[label.lower()]
                break

    names = column(values, LLDP_REM_SYS_NAME)
    chassis = column(values, LLDP_REM_CHASSIS)
    port_descs = column(values, LLDP_REM_PORT_DESC)
    port_ids = column(values, LLDP_REM_PORT_ID)
    found: dict[int, str] = {}
    for key in sorted({*names, *chassis}):
        # lldpRemTimeMark . lldpRemLocalPortNum . lldpRemIndex
        if len(key) != 3:
            continue
        number_ = key[1]
        index = local.get(number_, number_ if number_ in indexes else None)
        if index is None or index in found:
            continue
        who = text(names.get(key)) or text(chassis.get(key))
        if not who:
            continue
        where = text(port_descs.get(key)) or text(port_ids.get(key))
        found[index] = f"{who} ({where})" if where and where != who else who
    return found


# ---------------------------------------------------------------------------
# PoE
# ---------------------------------------------------------------------------


@dataclass
class PoePort:
    group: int
    port: int
    enabled: bool
    state: str
    power_class: int | None


@dataclass
class Poe:
    #: Watts the power supplies can give, over every PSE group.
    budget: float | None
    used: float | None
    faulty: bool
    ports: list[PoePort]

    @property
    def known(self) -> bool:
        return self.budget is not None or bool(self.ports)


def parse_poe(values: dict[str, Any]) -> Poe:
    budgets = [number(value) for value in column(values, PETH_MAIN_POWER).values()]
    used = [number(value) for value in column(values, PETH_MAIN_CONSUMPTION).values()]
    statuses = [number(value) for value in column(values, PETH_MAIN_STATUS).values()]
    admins = column(values, PETH_PORT_ADMIN)
    detections = column(values, PETH_PORT_DETECTION)
    classes = column(values, PETH_PORT_CLASS)
    ports = []
    for key in sorted({*admins, *detections}):
        if len(key) != 2:
            continue
        power_class = number(classes.get(key))
        ports.append(PoePort(
            group=key[0],
            port=key[1],
            enabled=number(admins.get(key)) != 2,
            state=POE_DETECTION.get(number(detections.get(key)) or 0, ""),
            # pethPsePortPowerClassifications counts class 0 as 1.
            power_class=power_class - 1 if power_class else None,
        ))
    known_budgets = [value for value in budgets if value is not None]
    known_used = [value for value in used if value is not None]
    budget = float(sum(known_budgets)) if known_budgets else None
    drawn = float(sum(known_used)) if known_used else None
    if budget and drawn and drawn > budget and drawn / 1000 <= budget:
        # ⚠️ Measured in a recording of a Netgear GS324TP: a budget of 190
        # and a consumption of 3800. RFC 3621 says watts for both; this one
        # counts the second in milliwatts. More than the budget cannot be
        # drawn, a thousandth of it can.
        drawn = drawn / 1000
    return Poe(
        budget=budget,
        used=drawn,
        faulty=3 in statuses,
        ports=ports,
    )
