"""SNMP: any managed switch or network device, through the standard MIBs.

⚠️ One adapter for every vendor, and that is the point of it. Cisco, HP,
Aruba, Netgear, TP-Link, Zyxel, D-Link, MikroTik and the rest all answer the
same IF-MIB, and the ports, their speeds and their counters are what a
homelab wants to see. Whatever only one vendor's MIB knows (CPU, temperature,
power per port) is left out: it cannot be tested without that vendor's switch.

⚠️ Read only. Nothing in here sends an SNMP SET, and ``Wire`` has no method
that could.

The parsing lives in ``snmp_mib`` and never touches the network; this module
does the asking and turns the answers into cards.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import warnings
from dataclasses import dataclass, field
from typing import Any

from . import demo as fake
from . import snmp_mib as mib
from .base import (
    Adapter,
    AdapterError,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    duration_short,
    guard_outbound,
    join_parts,
    measured,
    percent,
)

#: pysnmp's AES goes through ``cryptography``, which moved CFB mode to its
#: "decrepit" corner and warns on every first use. CFB is what RFC 3826 says
#: SNMPv3 encrypts with; there is nothing for us to change, and a warning in
#: the log every restart would read like something is wrong.
warnings.filterwarnings("ignore", message="CFB has been moved", category=UserWarning)

#: Seconds per request and how often it is sent again. A switch on the same
#: network answers in milliseconds; two seconds is patience, not hope.
TIMEOUT = 2.0
RETRIES = 1
#: Rows per GETBULK. Small enough that the answer fits one UDP packet on
#: every switch measured, large enough that a 48-port column is two requests.
BULK = 25
#: The most rows one column may have. A core switch with thousands of VLAN
#: interfaces is not what this card is for, and an agent that never says
#: "end of view" must not keep a card asking forever.
MAX_ROWS = 4000

#: Cards on the same device within this many seconds share one reading.
READ_SECONDS = 10.0
#: The first reading has nothing to subtract from; a second look at the
#: counters this long after it gives a rate straight away.
FIRST_GAP = 2.0
#: How long found errors stay on the findings card.
ERROR_WINDOW = 3600.0

VERSIONS = (("3", "SNMPv3, encrypted"), ("2c", "SNMPv2c, community"))
AUTH_PROTOCOLS = (
    ("sha", "SHA-1"), ("sha224", "SHA-224"), ("sha256", "SHA-256"),
    ("sha384", "SHA-384"), ("sha512", "SHA-512"), ("md5", "MD5, outdated"),
)
PRIV_PROTOCOLS = (
    ("aes", "AES-128"), ("aes192", "AES-192"), ("aes256", "AES-256"),
    ("aes192c", "AES-192, Cisco variant"), ("aes256c", "AES-256, Cisco variant"),
    ("des", "DES, outdated"), ("none", "None, sign only"),
)

SILENT_V2C = (
    "No answer usually has one of three causes: SNMP is switched off on the device; the device only answers "
    "the addresses on its SNMP access list and nexdeck's is not on it; or the community is wrong, which a "
    "v2c device never says, it just stays silent. Check the port as well, 161 unless somebody changed it."
)
SILENT_V3 = (
    "SNMPv3 answers a wrong user or password, so this is not that. Usually SNMP is switched off on the device, "
    "SNMPv3 is not enabled on it, or the device only answers the addresses on its access list and nexdeck's is "
    "not on it. Check the port as well, 161 unless somebody changed it."
)


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """A pysnmp value as Python: bytes, int, a dotted OID, or None for "not there"."""
    from pyasn1.type import univ
    from pysnmp.proto import rfc1902, rfc1905

    if isinstance(value, (rfc1905.NoSuchObject, rfc1905.NoSuchInstance, rfc1905.EndOfMibView, univ.Null)):
        return None
    if isinstance(value, rfc1902.IpAddress):
        return ".".join(str(byte) for byte in value.asOctets())
    if isinstance(value, univ.ObjectIdentifier):
        return ".".join(str(part) for part in value)
    if isinstance(value, univ.OctetString):
        return bytes(value.asOctets())
    if isinstance(value, univ.Integer):
        return int(value)
    return str(value)


def _settings(config: dict[str, Any]) -> tuple[str, int, str]:
    host = str(config.get("host") or "").strip()
    for scheme in ("udp://", "snmp://", "http://", "https://"):
        if host.lower().startswith(scheme):
            host = host[len(scheme):]
    host = host.strip("/").strip()
    if not host:
        raise AdapterError("This connection names no device.", code="bad_url", hint="Enter the address of the switch.")
    try:
        port = int(config.get("port") or 161)
    except (TypeError, ValueError):
        port = 0
    if not 0 < port < 65536:
        raise AdapterError("That is not a port number.", code="bad_url", hint="SNMP listens on 161 unless somebody changed it.")
    # The same addresses are barred as for every other connection: link-local
    # and the cloud metadata service. Checked by name, like there.
    guard_outbound(f"http://[{host}]" if ":" in host else f"http://{host}")
    version = "2c" if str(config.get("version") or "3").strip().lower() in ("2c", "2", "v2c") else "3"
    return host, port, version


class Wire:
    """One device, asked over pysnmp. Gets and walks, nothing else."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.host, self.port, self.version = _settings(config)
        self.config = config
        self._engine: Any = None
        self._target: Any = None

    # -- credentials -----------------------------------------------------------

    def _auth(self, *, without_privacy: bool = False) -> Any:
        from pysnmp.hlapi.v3arch import asyncio as h

        if self.version == "2c":
            community = str(self.config.get("community") or "")
            if not community:
                raise AdapterError("SNMPv2c needs a community.", code="auth_failed",
                                   hint="Enter the read-only community set up on the device.")
            return h.CommunityData(community, mpModel=1)
        user = str(self.config.get("username") or "").strip()
        if not user:
            raise AdapterError("SNMPv3 needs a user.", code="auth_failed",
                               hint="Enter the SNMPv3 user set up on the device.")
        auth_protocols = {
            "sha": h.usmHMACSHAAuthProtocol, "sha224": h.usmHMAC128SHA224AuthProtocol,
            "sha256": h.usmHMAC192SHA256AuthProtocol, "sha384": h.usmHMAC256SHA384AuthProtocol,
            "sha512": h.usmHMAC384SHA512AuthProtocol, "md5": h.usmHMACMD5AuthProtocol,
        }
        # ⚠️ AES-192 and AES-256 were never standardised, and there are two
        # ways to stretch the key. Net-SNMP and most others follow the
        # Blumenthal draft; Cisco follows Reeder. pysnmp calls the Reeder one
        # plain "AesCfb256". Both are offered, named by who uses them.
        priv_protocols = {
            "aes": h.usmAesCfb128Protocol,
            "aes192": h.usmAesBlumenthalCfb192Protocol, "aes256": h.usmAesBlumenthalCfb256Protocol,
            "aes192c": h.usmAesCfb192Protocol, "aes256c": h.usmAesCfb256Protocol,
            "des": h.usmDESPrivProtocol,
        }
        auth_key = str(self.config.get("auth_password") or "")
        if not auth_key:
            # A v3 user without authentication sends everything in the clear
            # and signs nothing; that is v2c with more steps.
            raise AdapterError("SNMPv3 needs an authentication password.", code="auth_failed",
                               hint="nexdeck does not use SNMPv3 without authentication.")
        if len(auth_key) < 8:
            raise AdapterError("SNMPv3 passwords are at least eight characters long.", code="auth_failed",
                               hint="The device would refuse a shorter one as well. Check the authentication password.")
        auth_protocol = auth_protocols.get(str(self.config.get("auth_protocol") or "sha"), h.usmHMACSHAAuthProtocol)
        privacy = str(self.config.get("priv_protocol") or "aes")
        if without_privacy or privacy == "none":
            return h.UsmUserData(user, auth_key, authProtocol=auth_protocol)
        priv_key = str(self.config.get("priv_password") or "")
        if not priv_key:
            raise AdapterError("SNMPv3 with encryption needs an encryption password.", code="auth_failed",
                               hint="Enter it, or set encryption to none if the device's user has none.")
        if len(priv_key) < 8:
            raise AdapterError("SNMPv3 passwords are at least eight characters long.", code="auth_failed",
                               hint="Check the encryption password.")
        return h.UsmUserData(user, auth_key, priv_key, authProtocol=auth_protocol,
                             privProtocol=priv_protocols.get(privacy, h.usmAesCfb128Protocol))

    # -- plumbing ----------------------------------------------------------------

    async def _open(self) -> tuple[Any, Any]:
        from pysnmp.error import PySnmpError
        from pysnmp.hlapi.v3arch import asyncio as h

        if self._engine is None:
            self._engine = h.SnmpEngine()
        if self._target is None:
            kind = h.Udp6TransportTarget if ":" in self.host else h.UdpTransportTarget
            try:
                self._target = await kind.create((self.host, self.port), timeout=TIMEOUT, retries=RETRIES)
            except PySnmpError as error:
                raise AdapterError(f"The name {self.host} does not resolve to an address.", code="unreachable",
                                   hint="Check the spelling, or enter the device's IP address instead.") from error
        return self._engine, self._target

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.close_dispatcher()
            except Exception:  # noqa: BLE001 - closing a socket that is already gone is not news
                pass
        self._engine = None
        self._target = None

    async def _ask(self, command: str, oids: tuple[str, ...], repetitions: int = BULK) -> list[tuple[str, Any]]:
        from pysnmp.hlapi.v3arch import asyncio as h
        from pysnmp.smi.error import WrongValueError

        engine, target = await self._open()
        try:
            auth = self._auth()
            binds = [h.ObjectType(h.ObjectIdentity(oid)) for oid in oids]
            if command == "get":
                indication, status, index, answers = await h.get_cmd(
                    engine, auth, target, h.ContextData(), *binds, lookupMib=False)
            else:
                indication, status, index, answers = await h.bulk_cmd(
                    engine, auth, target, h.ContextData(), 0, repetitions, *binds, lookupMib=False)
        except WrongValueError as error:
            raise AdapterError("SNMPv3 passwords are at least eight characters long.", code="auth_failed",
                               hint="The device would refuse a shorter one as well.") from error
        if indication:
            await self._explain(indication)
        if status:
            name = status.prettyPrint() if hasattr(status, "prettyPrint") else str(status)
            if name == "tooBig" and command == "bulk" and repetitions > 1:
                return await self._ask(command, oids, max(1, repetitions // 2))
            if name in ("authorizationError", "noAccess"):
                hint = "Give the SNMP user or community a view that includes the standard MIBs (1.3.6.1.2.1)."
                if self.version == "3" and str(self.config.get("priv_protocol") or "aes") == "none":
                    hint += " Or the device lets this user in only with encryption: set encryption to match."
                raise AdapterError(
                    "The device accepted the credentials but does not let them read this.", code="auth_failed",
                    hint=hint)
            raise AdapterError(f"The device refused the request: {name}.", code="device_error")
        return [(".".join(str(part) for part in bind[0]), _plain(bind[1])) for bind in answers]

    async def _explain(self, indication: Any) -> None:
        """Turn pysnmp's error into what went wrong, in words.

        ⚠️ Measured against Net-SNMP 5.9 on 22.09.2026: a wrong community and
        a closed port both look like silence; a wrong v3 user and a wrong
        authentication password are answered with a report; a wrong
        encryption password is silence again. That last one is found out by
        asking once more without encryption: if that gets an answer, user and
        password are right and only the encryption is not.
        """
        name = type(indication).__name__ if not isinstance(indication, str) else indication
        if name == "RequestTimedOut":
            if self.version == "3" and str(self.config.get("priv_protocol") or "aes") != "none":
                if await self._answers_without_privacy():
                    raise AdapterError(
                        "The user and the authentication password are right, the encryption is not.", code="auth_failed",
                        hint="Check the encryption password and the encryption protocol. AES-192 and AES-256 come in "
                             "two variants; Cisco uses the one marked Cisco.")
            raise AdapterError("The device did not answer.", code="unreachable",
                               hint=SILENT_V2C if self.version == "2c" else SILENT_V3)
        user = str(self.config.get("username") or "")
        if name == "UnknownUserName":
            raise AdapterError(f"The device does not know the SNMPv3 user {user}.", code="auth_failed",
                               hint="User names are case-sensitive, and on most switches the SNMPv3 user is set up "
                                    "separately from the account you sign in with.")
        if name == "WrongDigest":
            raise AdapterError("The device knows the user, but the authentication password or protocol is wrong.",
                               code="auth_failed",
                               hint="Check both: SHA-1 and SHA-256 are different protocols, and the same password "
                                    "under the wrong one fails the same way.")
        if name == "UnsupportedSecurityLevel":
            raise AdapterError("The user exists, but not with this level of security.", code="auth_failed",
                               hint="The device's user is set up with encryption and this connection has none, or "
                                    "the other way round. Set encryption to match.")
        if name == "DecryptionError":
            raise AdapterError("The encryption password or protocol is wrong.", code="auth_failed",
                               hint="Check the encryption password and the encryption protocol.")
        if name == "NotInTimeWindow":
            raise AdapterError("The device's SNMPv3 clock is out of step with this request.", code="device_error",
                               hint="This usually settles on the next try.")
        raise AdapterError(f"SNMP failed: {indication}.", code="device_error")

    async def _answers_without_privacy(self) -> bool:
        from pysnmp.hlapi.v3arch import asyncio as h

        engine = h.SnmpEngine()
        try:
            target = await h.UdpTransportTarget.create((self.host, self.port), timeout=TIMEOUT, retries=0) \
                if ":" not in self.host else await h.Udp6TransportTarget.create((self.host, self.port), timeout=TIMEOUT, retries=0)
            indication, _status, _index, _answers = await h.get_cmd(
                engine, self._auth(without_privacy=True), target, h.ContextData(),
                h.ObjectType(h.ObjectIdentity(mib.SYS_NAME)), lookupMib=False)
        except Exception:  # noqa: BLE001 - this only decides which message to show
            return False
        finally:
            engine.close_dispatcher()
        # An answer of any kind, a refusal of the security level included,
        # means the user and the authentication password were accepted.
        return not indication or type(indication).__name__ in ("UnsupportedSecurityLevel",)

    # -- asking ------------------------------------------------------------------

    async def get(self, oids: tuple[str, ...]) -> dict[str, Any]:
        return dict(await self._ask("get", oids))

    async def walk(self, prefix: str) -> dict[str, Any]:
        """Every value under ``prefix``, in as few GETBULKs as the device allows."""
        base = mib.oid_parts(prefix)
        found: dict[str, Any] = {}
        current = prefix
        while len(found) < MAX_ROWS:
            answers = await self._ask("bulk", (current,))
            moved = False
            for oid, value in answers:
                parts = mib.oid_parts(oid)
                if parts[: len(base)] != base or len(parts) <= len(base):
                    return found
                if value is None:
                    # endOfMibView: nothing comes after this.
                    return found
                if oid in found:
                    # An agent that hands back the same row twice is going round in circles.
                    return found
                found[oid] = value
                current = oid
                moved = True
            if not moved:
                return found
        return found


# ---------------------------------------------------------------------------
# One reading
# ---------------------------------------------------------------------------


@dataclass
class Reading:
    at: float
    system: mib.System
    ports: list[mib.Port]
    rates: dict[int, mib.Rate]
    counters: mib.Counters
    errors: dict[int, int] = field(default_factory=dict)


def _fingerprint(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()


class SnmpAdapter(Adapter):
    kind = "snmp"
    label = "SNMP (switches and network devices)"
    category = "network"
    description = ("Ports, link speeds, traffic, PoE and findings of any managed switch or network device that "
                   "speaks SNMP, from the standard MIBs.")
    icon = "lucide:network"
    docs_url = "https://datatracker.ietf.org/doc/html/rfc2863"
    #: Vendors people type into the search. They all speak the standard MIBs
    #: this adapter reads, which is what makes one adapter enough.
    keywords = ("snmp", "switch", "cisco", "netgear", "tp-link", "tplink", "zyxel", "hp", "hpe", "aruba",
                "procurve", "d-link", "dlink", "juniper", "dell", "mikrotik", "ubiquiti", "edgeswitch",
                "allied telesis", "extreme", "brocade", "huawei", "h3c", "arista", "fortinet", "linksys",
                "omada", "managed switch", "if-mib", "lldp", "poe")
    guide = (
        "Switch SNMP on in the device's web interface, usually under System, Management or Security.",
        "Prefer SNMPv3: create a user with SHA authentication and AES encryption and read-only access.",
        "If the device keeps an SNMP access list, add the address nexdeck runs on.",
        "Only if the device has no SNMPv3: set a read-only community that is neither public nor private.",
        "Enter the address here and press Test. A silent device is almost always one of the first three steps.",
    )
    fields = (
        Field("host", "Host", required=True, placeholder="switch.example.com or 192.0.2.10",
              help="The address of the device itself. SNMP has no web address, so no http:// in front."),
        Field("port", "Port", type="number", default=161, help="161 unless somebody changed it on the device."),
        Field("version", "SNMP version", type="select", default="3", options=VERSIONS,
              help="SNMPv3 signs and encrypts. Use SNMPv2c only on a device that has nothing else."),
        Field("community", "Community", type="password", secret=True, only_when=("version", "2c"),
              help="SNMPv2c sends the community and every answer unencrypted through the network. Use a "
                   "read-only community, and neither public nor private."),
        Field("username", "User", only_when=("version", "3"),
              help="The SNMPv3 user set up on the device, usually not the account you sign in with."),
        Field("auth_protocol", "Authentication", type="select", default="sha", options=AUTH_PROTOCOLS,
              only_when=("version", "3")),
        Field("auth_password", "Authentication password", type="password", secret=True, only_when=("version", "3"),
              help="At least eight characters; SNMPv3 refuses shorter ones."),
        Field("priv_protocol", "Encryption", type="select", default="aes", options=PRIV_PROTOCOLS,
              only_when=("version", "3"),
              help="AES-192 and AES-256 come in two variants; Cisco devices use the one marked Cisco."),
        Field("priv_password", "Encryption password", type="password", secret=True, only_when=("version", "3"),
              help="Often the same as the authentication password; the device decides."),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="Device",
            description="Name, maker, model, firmware and uptime, and how many ports are up.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=60,
            metrics=("ports_up",),
            parts=(("model", "Model"), ("firmware", "Firmware"), ("uptime", "Uptime"), ("location", "Location")),
        ),
        WidgetType(
            kind="ports",
            label="Ports",
            description="Every port with its state and speed, the duplex and what LLDP says is on the other end.",
            renderer="list",
            default_size=(3, 4),
            refresh_seconds=60,
            metrics=("ports_up",),
            options=(
                Field("scope", "Which interfaces", type="select", default="ports",
                      options=(("ports", "Ports and link aggregations"), ("all", "Every interface, VLANs included"))),
                Field("hide_down", "Only ports with a link", type="bool", default=False),
            ),
            parts=(("speed", "Speed"), ("duplex", "Duplex"), ("alias", "Description"), ("neighbour", "Neighbour"),
                   ("value", "Traffic")),
        ),
        WidgetType(
            kind="traffic",
            label="Port traffic",
            description="What goes through one port, in and out, with its history.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=30,
            metrics=("down_bps", "up_bps"),
            options=(Field("port", "Port", type="choices", required=True,
                           help="Pick the connection first; the ports of that device appear here."),),
        ),
        WidgetType(
            kind="findings",
            label="Findings",
            description="What is wrong: an uplink down, ports with errors, links at 100 Mbit/s or in half duplex.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=60,
            options=(
                Field("uplink", "Uplink", type="choices",
                      help="The port the device hangs on. Empty: every port whose description on the device "
                           "contains the word uplink."),
                Field("slow", "Report links at 100 Mbit/s or less", type="bool", default=True,
                      help="On a gigabit switch that is usually a cable or a device holding the port back."),
            ),
        ),
        WidgetType(
            kind="poe",
            label="PoE",
            description="Power over ethernet: the budget, what is drawn, and which ports deliver power.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("poe_watts",),
        ),
    )

    # -- plumbing ----------------------------------------------------------------

    def default_link(self, config: dict[str, Any]) -> str:
        # Most switches serve their own web interface on the same address.
        try:
            host, _port, _version = _settings(config)
        except AdapterError:
            return ""
        return f"http://[{host}]" if ":" in host else f"http://{host}"

    def _wire(self, config: dict[str, Any], ctx: Context) -> Wire:
        print_ = _fingerprint(config)
        held = ctx.cache.get("snmp:wire")
        if held and held[0] == print_:
            return held[1]
        if held:
            held[1].close()
        wire = Wire(config)
        ctx.cache["snmp:wire"] = (print_, wire)
        return wire

    async def close(self, config: dict[str, Any], ctx: Context) -> None:
        held = ctx.cache.pop("snmp:wire", None)
        if held:
            held[1].close()

    def _lock(self, ctx: Context) -> asyncio.Lock:
        lock = ctx.cache.get("snmp:lock")
        if not isinstance(lock, asyncio.Lock):
            lock = asyncio.Lock()
            ctx.cache["snmp:lock"] = lock
        return lock

    async def _walk_all(self, wire: Wire, columns: tuple[str, ...]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for prefix in columns:
            values.update(await wire.walk(prefix))
        return values

    async def _reading(self, config: dict[str, Any], ctx: Context) -> Reading:
        """The ports and their counters, shared by every card of this device for a few seconds."""
        async with self._lock(ctx):
            last: Reading | None = ctx.cache.get("snmp:reading")
            if last is not None and time.monotonic() - last.at < READ_SECONDS:
                return last
            wire = self._wire(config, ctx)
            system = mib.parse_system(await wire.get(mib.SYSTEM_OIDS))
            values = await self._walk_all(wire, mib.PORT_COLUMNS)
            ports = mib.parse_ports(values)
            now = mib.counters_of(ports, time.monotonic(), system.agent_uptime)
            before = last.counters if last is not None else None
            if before is None:
                # ⚠️ Nothing to subtract from yet. Rather than a card that
                # says "measuring" for its first half minute, look at the
                # counters once more a moment later.
                await asyncio.sleep(FIRST_GAP)
                values.update(await self._walk_all(wire, mib.COUNTER_COLUMNS))
                ports = mib.parse_ports(values)
                before = now
                now = mib.counters_of(ports, time.monotonic(), system.agent_uptime)
            reading = Reading(
                at=time.monotonic(), system=system, ports=ports,
                rates=mib.rates(before, now, ports), counters=now,
                errors=mib.new_errors(last.counters if last is not None else None, now),
            )
            self._remember_errors(ctx, reading)
            ctx.cache["snmp:reading"] = reading
            return reading

    def _remember_errors(self, ctx: Context, reading: Reading) -> None:
        log: list[tuple[float, int, int]] = ctx.cache.setdefault("snmp:errors", [])
        log.extend((reading.at, index, count) for index, count in reading.errors.items())
        cutoff = reading.at - ERROR_WINDOW
        log[:] = [entry for entry in log if entry[0] >= cutoff]

    def _recent_errors(self, ctx: Context) -> dict[int, int]:
        found: dict[int, int] = {}
        for _at, index, count in ctx.cache.get("snmp:errors", []):
            found[index] = found.get(index, 0) + count
        return found

    async def _kept(self, key: str, seconds: float, config: dict[str, Any], ctx: Context,
                    columns: tuple[str, ...]) -> dict[str, Any]:
        """A slower table (LLDP, ENTITY-MIB, PoE), asked for again only every so often."""
        hit = ctx.cache.get(key)
        if hit and time.monotonic() - hit[0] < seconds:
            return hit[1]
        async with self._lock(ctx):
            values = await self._walk_all(self._wire(config, ctx), columns)
        ctx.cache[key] = (time.monotonic(), values)
        return values

    # -- hooks -------------------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        wire = self._wire(config, ctx)
        system = mib.parse_system(await wire.get(mib.SYSTEM_OIDS))
        if not system.name and not system.description and not system.object_id:
            raise AdapterError("The device answered, but without a name or a description.", code="device_error",
                               hint="Its SNMP view may be limited; give it one that includes 1.3.6.1.2.1.")
        speeds = await wire.walk(mib.IF_HC_IN_OCTETS)
        values: dict[str, Any] = {}
        for prefix in (mib.IF_TYPE, mib.IF_OPER, mib.IF_NAME, mib.DOT3_DUPLEX):
            values.update(await wire.walk(prefix))
        count = len(mib.front_ports(mib.parse_ports(values)))
        who = system.name or mib.short_description(system.description, 40) or "The device"
        maker = f" ({system.vendor})" if system.vendor else ""
        version = "SNMPv2c, unencrypted" if wire.version == "2c" else "SNMPv3"
        counters = "64-bit counters" if speeds else "only 32-bit counters, so fast ports show no traffic"
        ports_text = "1 port" if count == 1 else f"{count} ports"
        return f"{who}{maker} answers over {version}: {ports_text}, {counters}."

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field not in ("port", "uplink"):
            return await super().choices(field, config, ctx)
        reading = await self._reading(config, ctx)
        return [(port.name, f"{mib.port_title(port)} · {port.alias}" if port.alias else mib.port_title(port))
                for port in mib.front_ports(reading.ports)]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field not in ("port", "uplink"):
            return []
        return [(name, f"{name} · {alias}" if alias else name) for name, alias, *_rest in DEMO_PORTS]

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        reading = await self._reading(config, ctx)
        if widget_kind == "ports":
            neighbours = mib.parse_neighbours(
                await self._kept("snmp:lldp", 300, config, ctx, mib.LLDP_COLUMNS), reading.ports)
            return _ports(reading, neighbours, options)
        if widget_kind == "traffic":
            return _traffic(reading, options)
        if widget_kind == "findings":
            return _findings(reading, self._recent_errors(ctx), options)
        if widget_kind == "poe":
            return _poe(mib.parse_poe(await self._kept("snmp:poe", 50, config, ctx, mib.POE_COLUMNS)))
        entity = await self._kept("snmp:entity", 3600, config, ctx,
                                  (mib.ENT_CLASS, mib.ENT_MODEL, mib.ENT_SOFTWARE, mib.ENT_FIRMWARE, mib.ENT_SERIAL))
        return _overview(mib.add_entity(reading.system, entity), reading.ports)

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """An uplink that went down. Only on the change: one that stays down is not news every minute."""
        if widget_kind != "findings" or before is None or before.error:
            return []
        was = set((before.meta or {}).get("uplinks_down") or [])
        device = str((after.meta or {}).get("device") or "The device")
        return [
            Detected(event="link_down", title=f"Uplink {name} on {device} is down", level="bad",
                     key=f"link_down:{device}:{name}", quiet_seconds=1800)
            for name in (after.meta or {}).get("uplinks_down") or [] if name not in was
        ]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        return _demo(widget_kind, options, tick)


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _duplex(port: mib.Port) -> str:
    return {"full": "full duplex", "half": "half duplex"}.get(port.duplex, "")


def _rate_text(rate: mib.Rate | None) -> str:
    if rate is None or rate.down is None or rate.up is None:
        return ""
    return f"↓ {mib.bits_text(rate.down)} ↑ {mib.bits_text(rate.up)}"


def _shown(ports: list[mib.Port], scope: str) -> list[mib.Port]:
    return list(ports) if scope == "all" else mib.front_ports(ports)


def _overview(system: mib.System, ports: list[mib.Port]) -> WidgetData:
    front = mib.front_ports(ports)
    up = sum(1 for port in front if port.up)
    maker = system.vendor or "Unknown maker"
    secondary = [
        {"label": "Maker", "value": maker},
        {"label": "Model", "value": system.model or mib.short_description(system.description, 48) or "?", "part": "model"},
    ]
    if system.firmware:
        secondary.append({"label": "Firmware", "value": system.firmware, "part": "firmware"})
    secondary.append({"label": "Uptime", "value": duration_short(system.uptime), "part": "uptime"})
    if system.location:
        secondary.append({"label": "Location", "value": system.location, "part": "location"})
    return WidgetData(
        primary={"label": "Ports up", "value": f"{up} / {len(front)}"},
        secondary=secondary,
        metrics={"ports_up": float(up)},
        meta={"device": system.name},
    )


def _ports(reading: Reading, neighbours: dict[int, str], options: dict[str, Any]) -> WidgetData:
    shown = _shown(reading.ports, str(options.get("scope") or "ports"))
    items: list[dict[str, Any]] = []
    for port in shown:
        if options.get("hide_down") and not port.up:
            continue
        if not port.enabled:
            state = "disabled"
        elif port.up:
            state = ""
        else:
            state = "no link"
        facts = [
            ("speed", mib.speed_text(port.speed) if port.up else state),
            ("duplex", _duplex(port) if port.up else ""),
            ("alias", port.alias),
            ("neighbour", f"→ {neighbours[port.index]}" if port.index in neighbours else ""),
        ]
        item: dict[str, Any] = {
            "id": f"if-{port.index}",
            "title": mib.port_title(port),
            "subtitle": join_parts(options, *facts) or state,
            "status": ("warn" if port.duplex == "half" else "ok") if port.up else "unknown",
        }
        rate = _rate_text(reading.rates.get(port.index)) if port.up else ""
        if rate:
            item["value"] = rate
        items.append(item)
    front = mib.front_ports(reading.ports)
    up = sum(1 for port in front if port.up)
    return WidgetData(
        items=items,
        secondary=[
            {"label": "Device", "value": reading.system.name or "?"},
            {"label": "Ports up", "value": f"{up} / {len(front)}"},
        ],
        metrics={"ports_up": float(up)},
        meta={"empty": "No port has a link" if options.get("hide_down") else "The device lists no ports"},
    )


def _traffic(reading: Reading, options: dict[str, Any]) -> WidgetData:
    wanted = str(options.get("port") or "").strip()
    if not wanted:
        raise AdapterError("No port is picked for this card.", code="no_port_picked",
                           hint="Open the card settings and pick one.")
    port = next((one for one in reading.ports if one.name == wanted), None)
    if port is None:
        raise AdapterError(f"The device has no port {wanted} any more.", code="no_port_picked",
                           hint="Open the card settings and pick the port again.")
    rate = reading.rates.get(port.index)
    down = rate.down if rate else None
    up = rate.up if rate else None
    secondary = [
        {"label": "Out", "value": mib.bits_text(up) if up is not None else "?"},
        {"label": "Link", "value": (mib.speed_text(port.speed) or "up") if port.up else "no link"},
    ]
    busiest = max((value for value in (down, up) if value is not None), default=None)
    if busiest is not None and port.speed and port.up:
        secondary.append({"label": "Load", "value": f"{percent(busiest, port.speed * 1_000_000) or 0:.0f}%"})
    meta: dict[str, Any] = {}
    if rate and (rate.down is None or rate.up is None) and rate.why == "counter too narrow":
        meta["status_reason"] = ("This port has only 32-bit counters, which go round faster than they are read "
                                 "at this speed.")
    return WidgetData(
        status="ok" if port.up else "unknown",
        primary={"label": "In", "value": mib.bits_text(down) if down is not None else None},
        secondary=secondary,
        metrics=measured({"down_bps": down, "up_bps": up}),
        meta=meta,
    )


def _findings(reading: Reading, errors: dict[int, int], options: dict[str, Any]) -> WidgetData:
    picked = str(options.get("uplink") or "").strip()
    slow = options.get("slow") is not False
    items: list[dict[str, Any]] = []
    uplinks_down: list[str] = []
    front = mib.front_ports(reading.ports)
    for port in front:
        uplink = mib.is_uplink(port, picked)
        if uplink and port.enabled and not port.up:
            uplinks_down.append(port.name)
            items.append({"title": mib.port_title(port), "subtitle": "uplink is down", "status": "bad"})
            continue
        if not port.up:
            continue
        if port.duplex == "half":
            items.append({"title": mib.port_title(port), "subtitle": "half duplex", "status": "warn"})
        if slow and port.speed is not None and port.speed <= 100:
            items.append({"title": mib.port_title(port), "subtitle": f"runs at {mib.speed_text(port.speed)}", "status": "warn"})
        count = errors.get(port.index, 0)
        if count:
            items.append({"title": mib.port_title(port), "subtitle": f"{count} errors in the last hour", "status": "warn"})
    if picked and not any(port.name == picked for port in reading.ports):
        items.append({"title": picked, "subtitle": "uplink not on this device any more", "status": "warn"})
    order = {"bad": 0, "warn": 1, "unknown": 2}
    items.sort(key=lambda item: order.get(str(item["status"]), 3))
    up = sum(1 for port in front if port.up)
    status = "bad" if uplinks_down else ("warn" if items else "ok")
    name = reading.system.name or "The device"
    return WidgetData(
        status=status,
        items=items,
        meta={
            "empty": f"{name} answers · {up} of {len(front)} ports up · nothing to report",
            "uplinks_down": uplinks_down,
            "device": name,
            **({"status_reason": f"{len(uplinks_down)} uplink(s) down"} if uplinks_down else {}),
        },
    )


def _poe(poe: mib.Poe) -> WidgetData:
    if not poe.known:
        # ⚠️ Said, not drawn as zero. A switch without PoE and one that keeps
        # it in its own MIB both look like this, and 0 W would claim a
        # measurement nobody made.
        return WidgetData(
            status="unknown",
            meta={"empty": "This device reports no PoE through the standard MIB"},
        )
    items = [
        {
            "title": f"PoE port {one.port}" if one.group <= 1 else f"PoE port {one.group}/{one.port}",
            "subtitle": " · ".join(part for part in (
                one.state if one.enabled else "switched off",
                f"class {one.power_class}" if one.power_class is not None and one.state == "delivering power" else "",
            ) if part),
            "status": "bad" if one.state == "fault" else ("ok" if one.state == "delivering power" else "unknown"),
        }
        for one in poe.ports
    ]
    delivering = sum(1 for one in poe.ports if one.state == "delivering power")
    share = percent(poe.used, poe.budget)
    secondary = [
        {"label": "Drawn", "value": f"{poe.used:g} W" if poe.used is not None else "?"},
        {"label": "Budget", "value": f"{poe.budget:g} W" if poe.budget is not None else "?"},
    ]
    if share is not None:
        secondary.append({"label": "Used", "value": f"{share:.0f}%"})
    if poe.ports:
        secondary.append({"label": "Powered ports", "value": delivering})
    faults = any(one.state == "fault" for one in poe.ports)
    return WidgetData(
        status="bad" if poe.faulty or faults else ("warn" if share is not None and share >= 90 else "ok"),
        items=items,
        secondary=secondary,
        metrics=measured({"poe_watts": poe.used}),
        meta={"empty": "The device lists no PoE ports, only its budget"},
    )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

#: name, description, speed in Mbit/s or 0 for no link, duplex, neighbour
DEMO_PORTS: tuple[tuple[str, str, int, str, str], ...] = (
    ("Gi1/0/1", "Uplink router", 1000, "full", "router (ether2)"),
    ("Gi1/0/2", "NAS", 1000, "full", "nas (eth0)"),
    ("Gi1/0/3", "Access point hall", 1000, "full", "ap-hall (eth0)"),
    ("Gi1/0/4", "Server", 1000, "full", "pve (enp1s0)"),
    ("Gi1/0/5", "Printer", 100, "full", ""),
    ("Gi1/0/6", "", 0, "", ""),
    ("Gi1/0/7", "Camera garden", 100, "half", ""),
    ("Gi1/0/8", "", 0, "", ""),
)


def _demo_reading(tick: int) -> Reading:
    ports = []
    rates: dict[int, mib.Rate] = {}
    for number, (name, alias, speed, duplex, _neighbour) in enumerate(DEMO_PORTS, start=1):
        ports.append(mib.Port(index=number, name=name, alias=alias, type=6, oper="up" if speed else "down",
                              speed=float(speed) or None, duplex=duplex, wide=True))
        if speed:
            rates[number] = mib.Rate(fake.walk(f"snmp-in-{number}", tick, 0.2e6, speed * 0.3e6),
                                     fake.walk(f"snmp-out-{number}", tick, 0.1e6, speed * 0.1e6))
    system = mib.System(name="core-switch", vendor="Cisco", model="WS-C2960X-24PS-L", firmware="15.2(7)E9",
                        uptime=41 * 86400 + tick, location="Rack")
    return Reading(at=0, system=system, ports=ports, rates=rates, counters=mib.Counters(at=0, agent_uptime=None))


def _demo(widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
    reading = _demo_reading(tick)
    if widget_kind == "ports":
        neighbours = {number: neighbour for number, (*_rest, neighbour) in enumerate(DEMO_PORTS, start=1) if neighbour}
        return _ports(reading, neighbours, options)
    if widget_kind == "traffic":
        return _traffic(reading, {"port": options.get("port") or DEMO_PORTS[0][0]})
    if widget_kind == "findings":
        errors = {4: 12} if fake.flicker("snmp-errors", tick, 0.3) else {}
        return _findings(reading, errors, options)
    if widget_kind == "poe":
        used = fake.walk("snmp-poe", tick, 28, 41)
        return _poe(mib.Poe(budget=370.0, used=round(used, 1), faulty=False, ports=[
            mib.PoePort(1, 3, True, "delivering power", 4),
            mib.PoePort(1, 5, True, "delivering power", 2),
            mib.PoePort(1, 6, True, "searching", None),
            mib.PoePort(1, 7, True, "delivering power", 0),
            mib.PoePort(1, 8, False, "disabled", None),
        ]))
    return _overview(reading.system, reading.ports)


ADAPTER = SnmpAdapter()
