"""The topology page: a UniFi network as a plan, with the traffic on every link.

What a console tells, measured on one with 22 devices (Network 9, 19.10.2026):

* The classic API's ``stat/device`` carries byte counters for every port, and
  each device names the device it uplinks to (``uplink.uplink_mac``) and the
  port on it (``uplink.uplink_remote_port``). ``stat/sta`` names the switch and
  the port of every wired client. The Integration API has none of that.
* The gateway sends a new report every two seconds or so, switches and access
  points every 65 to 90 seconds. A link between two switches therefore shows
  a value that is up to a minute and a half old, and the page says how old.
* ⚠️ Now and then a switch sends a report whose counters have not moved since
  the one before, every port at once, while the other end of the same cable
  shows traffic (the gateway's port to the core switch carried 12.7 Mbit/s
  during one). Such a report is no measurement. UniFi's own rate fields read
  zero in it, which is why the rates are worked out here from the counters:
  a report that stands still is left out, and the next one spreads its bytes
  over both intervals.

A link is measured at its upper end, the port of the device closer to the
internet, because that is where the counters move; a switch's own uplink
counters stood at zero on nearly every report. A mesh link has no port and is
measured at the access point that hangs on it.
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..adapters.base import AdapterError

#: How often a console is asked at most, however many browsers have the page open.
POLL_SECONDS = 10.0
#: Rates kept per link for the little chart in the side panel.
HISTORY = 60
#: Bounds for what a browser may store on a page.
MAX_IDS = 2000
MAX_COORD = 100_000.0

KIND = {"udm": "gateway", "ugw": "gateway", "uxg": "gateway", "usw": "switch", "uap": "ap"}
#: Children are laid out switches first, then access points, by name.
RANK = {"switch": 0, "gateway": 0, "ap": 1}
INTERNET = "internet"

Key = tuple[str, ...]


# ---------------------------------------------------------------------------
# Rates from counters
# ---------------------------------------------------------------------------


@dataclass
class Meter:
    """What a connection remembers between two looks at the console."""

    #: Counter pair (sent, received) per port or uplink, from the last report taken.
    base: dict[Key, tuple[float, float]] = field(default_factory=dict)
    #: The ``last_seen`` of the last report taken, per device.
    seen: dict[str, float] = field(default_factory=dict)
    #: Rate pair (sent, received) in bit/s; ``None`` while nothing is known.
    rates: dict[Key, tuple[float | None, float | None]] = field(default_factory=dict)
    #: The ``last_seen`` values taken, per device, for how often it reports.
    reports: dict[str, deque] = field(default_factory=dict)
    #: (time, down, up) per link, appended when its measuring device reported.
    history: dict[str, deque] = field(default_factory=dict)


def _counters(device: dict[str, Any]) -> dict[Key, tuple[float, float]]:
    mac = str(device.get("mac") or "").lower()
    found: dict[Key, tuple[float, float]] = {}
    for port in device.get("port_table") or []:
        if port.get("up") and port.get("port_idx") is not None:
            found[("port", mac, str(port["port_idx"]))] = (float(port.get("tx_bytes") or 0), float(port.get("rx_bytes") or 0))
    uplink = device.get("uplink") or {}
    if uplink.get("tx_bytes") is not None or uplink.get("rx_bytes") is not None:
        found[("uplink", mac)] = (float(uplink.get("tx_bytes") or 0), float(uplink.get("rx_bytes") or 0))
    return found


def _reported(device: dict[str, Any]) -> dict[Key, tuple[float, float]]:
    """UniFi's own rates (bytes per second), only to have a value on first sight."""
    mac = str(device.get("mac") or "").lower()
    found: dict[Key, tuple[float, float]] = {}
    for port in device.get("port_table") or []:
        if port.get("up") and port.get("port_idx") is not None:
            found[("port", mac, str(port["port_idx"]))] = (float(port.get("tx_bytes-r") or 0) * 8, float(port.get("rx_bytes-r") or 0) * 8)
    uplink = device.get("uplink") or {}
    if uplink:
        found[("uplink", mac)] = (float(uplink.get("tx_bytes-r") or 0) * 8, float(uplink.get("rx_bytes-r") or 0) * 8)
    return found


def observe(meter: Meter, device: dict[str, Any]) -> bool:
    """Take one device's report into the meter. True when it was a new measurement."""
    mac = str(device.get("mac") or "").lower()
    if device.get("last_seen") is None:
        return False
    seen = float(device["last_seen"])
    if meter.seen.get(mac) == seen:
        return False
    # How often a device reports counts every report, the ones that stand still too.
    reports = meter.reports.setdefault(mac, deque(maxlen=20))
    if not reports or reports[-1] != seen:
        reports.append(seen)
    counters = _counters(device)
    before = {key: meter.base[key] for key in counters if key in meter.base}
    if mac in meter.seen and before and all(counters[key] == before[key] for key in before):
        # A report whose counters stand still: see the module's docstring.
        return False
    interval = seen - meter.seen[mac] if mac in meter.seen else 0.0
    guesses = _reported(device)
    blank = not any(sent or received for sent, received in guesses.values())
    for key, (sent, received) in counters.items():
        old = meter.base.get(key)
        if old is not None and interval > 0 and sent >= old[0] and received >= old[1]:
            meter.rates[key] = ((sent - old[0]) * 8 / interval, (received - old[1]) * 8 / interval)
        else:
            # First sight, or the device started again and its counters with it.
            guess = guesses.get(key)
            meter.rates[key] = guess if guess is not None and not blank else (None, None)
    meter.base.update(counters)
    meter.seen[mac] = seen
    return True


def every(meter: Meter, mac: str) -> float | None:
    """How many seconds lie between two new values from this device, as far as seen."""
    values = list(meter.reports.get(mac, ()))
    gaps = [b - a for a, b in zip(values, values[1:], strict=False) if b > a]
    return round(statistics.median(gaps)) if gaps else None


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def _port(device: dict[str, Any], index: Any) -> dict[str, Any]:
    return next((p for p in device.get("port_table") or [] if p.get("port_idx") == index), {})


def _port_ref(device: dict[str, Any] | None, index: Any) -> dict[str, Any]:
    """A port by number, with its name when someone gave it one ("Port 5" is no name)."""
    if index is None:
        return {"index": None, "name": ""}
    name = str(_port(device or {}, index).get("name") or "")
    return {"index": index, "name": "" if name in ("", f"Port {index}") else name}


def _bits(mbps: Any) -> float | None:
    try:
        value = float(mbps)
    except (TypeError, ValueError):
        return None
    return value * 1e6 if value > 0 else None


def guess_kind(client: dict[str, Any]) -> str:
    """An icon for a wired client, from its name and maker. A guess; "other" when unsure."""
    words = " ".join(str(client.get(k) or "") for k in ("name", "hostname", "oui", "dev_vendor")).lower()
    for kind, hints in (
        ("nas", ("nas", "synology", "qnap", "unraid", "truenas")),
        ("tv", ("tv", "appletv", "apple-tv", "shield", "roku")),
        ("printer", ("printer", "drucker", "epson", "brother", "laserjet", "canon")),
        ("camera", ("camera", "kamera", "cam-", "doorbell")),
        ("server", ("server", "proxmox", "pve", "docker", "esxi", "raspberry", "homeassistant", "home-assistant", "nuc")),
        ("computer", ("desktop", "laptop", "macbook", "imac", "workstation", "-pc", "pc-", "dock")),
        ("phone", ("voip", "phone", "gigaset", "yealink", "snom")),
    ):
        if any(hint in words for hint in hints):
            return kind
    return "other"


def build(
    devices: list[dict[str, Any]],
    stations: list[dict[str, Any]],
    health: list[dict[str, Any]],
    models: dict[str, str],
    meter: Meter,
    now: float,
) -> dict[str, Any]:
    """Nodes, links and wired clients, with rates, from one look at the console."""
    devices = [d for d in devices if d.get("mac")]
    by_mac = {str(d["mac"]).lower(): d for d in devices}
    fresh = {str(d["mac"]).lower() for d in devices if observe(meter, d)}
    gateway = next((d for d in devices if KIND.get(str(d.get("type"))) == "gateway"), None)
    wan = next((h for h in health if h.get("subsystem") == "wan"), {})

    # A port that leads to another UniFi device is not a client port, whatever stat/sta says.
    uplinks = {(str((d.get("uplink") or {}).get("uplink_mac") or "").lower(), (d.get("uplink") or {}).get("uplink_remote_port")) for d in devices}
    wired = [
        c for c in stations
        if c.get("is_wired") and str(c.get("sw_mac") or "").lower() in by_mac and c.get("mac")
        and (str(c["sw_mac"]).lower(), c.get("sw_port")) not in uplinks
    ]
    per_device: dict[str, int] = {}
    for client in wired:
        per_device[str(client["sw_mac"]).lower()] = per_device.get(str(client["sw_mac"]).lower(), 0) + 1

    nodes: list[dict[str, Any]] = [{
        "id": INTERNET, "name": "Internet", "model": str(wan.get("isp_name") or ""), "kind": "internet",
        "status": "offline" if wan.get("status") == "error" else "ok", "every": None,
        "facts": {"isp": str(wan.get("isp_name") or ""), "isp_organization": str(wan.get("isp_organization") or "")},
    }]
    for device in devices:
        mac = str(device["mac"]).lower()
        kind = KIND.get(str(device.get("type")), "switch")
        online = device.get("state") == 1
        stats = device.get("system-stats") or {}
        facts: dict[str, Any] = {"ip": str(device.get("ip") or ""), "firmware": str(device.get("version") or "")}
        if online:
            facts["uptime"] = int(device.get("uptime") or 0)
        elif device.get("last_seen"):
            facts["last_seen_ago"] = max(0, int(now - float(device["last_seen"])))
        for name, source in (("cpu", stats.get("cpu")), ("memory", stats.get("mem")), ("temperature", device.get("general_temperature"))):
            try:
                facts[name] = round(float(source))
            except (TypeError, ValueError):
                pass
        node = {
            "id": mac, "name": str(device.get("name") or models.get(mac) or device.get("model") or mac),
            "model": models.get(mac) or str(device.get("model") or ""), "kind": kind,
            "status": "ok" if online else "offline", "every": every(meter, mac), "facts": facts,
            "wired_clients": per_device.get(mac, 0),
        }
        if kind == "ap":
            node["wifi_clients"] = int(device.get("num_sta") or 0)
        nodes.append(node)

    def link(link_id: str, a: str, b: str, port_a: dict, port_b: dict, kind: str, speed: float | None,
             meter_mac: str, key: Key, flip: bool, online: bool) -> dict[str, Any]:
        """``flip``: the counter's "received" is the way down the tree (a WAN port, a mesh AP)."""
        sent, received = meter.rates.get(key, (None, None)) if online else (None, None)
        down, up = (received, sent) if flip else (sent, received)
        history = meter.history.setdefault(link_id, deque(maxlen=HISTORY))
        if meter_mac in fresh and online and down is not None:
            history.append((meter.seen.get(meter_mac, now), down, up))
        return {
            "id": link_id, "a": a, "b": b, "port_a": port_a, "port_b": port_b, "kind": kind,
            "state": "up" if online else "down", "speed": speed, "down": down, "up": up,
            "meter": meter_mac, "at": meter.seen.get(meter_mac) if online else None, "every": every(meter, meter_mac),
            "history": {"down": [h[1] for h in history], "up": [h[2] for h in history]},
        }

    links: list[dict[str, Any]] = []
    if gateway is not None:
        gw = str(gateway["mac"]).lower()
        uplink = gateway.get("uplink") or {}
        links.append(link(
            f"link:{INTERNET}", INTERNET, gw, {"index": None, "name": ""}, {"index": uplink.get("port_idx"), "name": "WAN"},
            "wan", _bits(uplink.get("speed") or uplink.get("max_speed")), gw, ("uplink", gw), True, gateway.get("state") == 1,
        ))
    children: list[tuple[int, str, dict[str, Any]]] = []
    for device in devices:
        mac = str(device["mac"]).lower()
        uplink = device.get("uplink") or {}
        parent = by_mac.get(str(uplink.get("uplink_mac") or "").lower())
        if device is gateway or parent is None:
            continue
        pmac = str(parent["mac"]).lower()
        online = device.get("state") == 1
        if uplink.get("type") == "wireless":
            rate = max(float(uplink.get("tx_rate") or 0), float(uplink.get("rx_rate") or 0)) * 1000
            item = link(f"link:{mac}", pmac, mac, {"index": None, "name": ""}, {"index": None, "name": ""}, "wifi",
                        rate or None, mac, ("uplink", mac), True, online)
        else:
            index = uplink.get("uplink_remote_port")
            speed = _bits(_port(parent, index).get("speed") or uplink.get("speed"))
            item = link(f"link:{mac}", pmac, mac, _port_ref(parent, index), _port_ref(device, uplink.get("port_idx")), "wire",
                        speed, pmac, ("port", pmac, str(index)), False, online)
        children.append((RANK.get(KIND.get(str(device.get("type")), ""), 2), str(device.get("name") or "").lower(), item))
    links += [item for _, _, item in sorted(children, key=lambda c: (c[0], c[1]))]

    clients: list[dict[str, Any]] = []
    client_links: list[dict[str, Any]] = []
    for client in sorted(wired, key=lambda c: (str(c["sw_mac"]).lower(), c.get("sw_port") or 0)):
        cid = str(client["mac"]).lower()
        switch = by_mac[str(client["sw_mac"]).lower()]
        smac = str(switch["mac"]).lower()
        index = client.get("sw_port")
        speed = _bits(_port(switch, index).get("speed"))
        clients.append({
            "id": cid, "name": str(client.get("name") or client.get("hostname") or client.get("oui") or cid),
            "kind": guess_kind(client), "ip": str(client.get("ip") or ""), "at": smac, "port": _port_ref(switch, index), "speed": speed,
        })
        client_links.append(link(f"client:{cid}", smac, cid, _port_ref(switch, index), {"index": None, "name": ""}, "wire",
                                 speed, smac, ("port", smac, str(index)), False, switch.get("state") == 1))
    return {"nodes": nodes, "links": links, "clients": clients, "client_links": client_links}


def with_ages(data: dict[str, Any], now: float) -> dict[str, Any]:
    """Seconds since each value was measured, worked out when the answer goes out, not when it was read."""
    def aged(item: dict[str, Any]) -> dict[str, Any]:
        at = item.get("at")
        return {**{k: v for k, v in item.items() if k != "at"}, "age": None if at is None else max(0.0, round(now - float(at), 1))}

    return {**data, "links": [aged(link) for link in data["links"]], "client_links": [aged(link) for link in data["client_links"]]}


# ---------------------------------------------------------------------------
# Reading a console
# ---------------------------------------------------------------------------


async def snapshot(adapter: Any, config: dict[str, Any], ctx: Any, *, demo: bool) -> dict[str, Any]:
    """The plan of one connection, read at most every ``POLL_SECONDS`` for everyone."""
    lock = ctx.cache.setdefault("topology:lock", asyncio.Lock())
    async with lock:
        hit = ctx.cache.get("topology:snapshot")
        if hit and hit[0] > time.monotonic():
            return hit[1]
        meter = ctx.cache.setdefault("topology:meter", Meter())
        now = time.time()
        if demo:
            devices, stations, health, models = demo_console(now)
        else:
            devices = await adapter.classic(config, ctx, "/stat/device")
            stations = await adapter.classic(config, ctx, "/stat/sta")
            health = await _kept(ctx, "topology:health", 60, lambda: adapter.classic(config, ctx, "/stat/health"))
            models = await _kept(ctx, "topology:models", 600, lambda: adapter.model_names(config, ctx))
        if not isinstance(devices, list) or not devices:
            raise AdapterError("The console reported no devices.", code="no_devices", hint="Check the site of the connection.")
        data = build(devices, stations or [], health or [], models or {}, meter, now)
        ctx.cache["topology:snapshot"] = (time.monotonic() + POLL_SECONDS - 0.5, data)
        return data


async def _kept(ctx: Any, key: str, seconds: float, load: Any) -> Any:
    hit = ctx.cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = await load()
    ctx.cache[key] = (time.monotonic() + seconds, value)
    return value


# ---------------------------------------------------------------------------
# What a browser may store on a topology page
# ---------------------------------------------------------------------------


def clean_layout(raw: Any, integration_id: int | None) -> dict[str, Any]:
    """The part of a topology page a browser writes: who stands where.

    ``placed``: network devices on the plan. ``clients``: wired clients fetched
    onto it. ``hidden``: devices put away in "found". ``positions``: id to x, y.
    Ids are MAC addresses and are only kept, never trusted for anything else.
    """
    raw = raw if isinstance(raw, dict) else {}

    def ids(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value[:MAX_IDS]:
            if isinstance(item, str) and 0 < len(item) <= 64 and item not in out:
                out.append(item)
        return out

    positions: dict[str, list[float]] = {}
    source = raw.get("positions") if isinstance(raw.get("positions"), dict) else {}
    for key, value in list(source.items())[:MAX_IDS]:
        if not (isinstance(key, str) and 0 < len(key) <= 64 and isinstance(value, (list, tuple)) and len(value) == 2):
            continue
        try:
            x, y = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y) and abs(x) <= MAX_COORD and abs(y) <= MAX_COORD:
            positions[key] = [round(x, 1), round(y, 1)]
    return {
        "integration_id": integration_id,
        "start": raw.get("start") if raw.get("start") in ("all", "empty") else "all",
        "seeded": bool(raw.get("seeded")),
        "placed": ids(raw.get("placed")),
        "clients": ids(raw.get("clients")),
        "hidden": ids(raw.get("hidden")),
        "positions": positions,
    }


def seed(layout: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """The first look at a new page: every network device, or only the gateway."""
    devices = [n["id"] for n in data["nodes"]]
    gateway = [n["id"] for n in data["nodes"] if n["kind"] in ("internet", "gateway")]
    return {**layout, "seeded": True, "placed": devices if layout.get("start") != "empty" else gateway}


# ---------------------------------------------------------------------------
# A made-up network for demo mode, in the shape the console sends
# ---------------------------------------------------------------------------

_DEMO_DEVICES = (
    # mac suffix, name, type, model, uplink suffix, uplink port, own port, ports, wireless, online
    ("01", "Gateway", "udm", "UDM-Pro", None, None, None, 11, False, True),
    ("02", "Core switch", "usw", "USW-Pro-24-PoE", "01", 10, 25, 26, False, True),
    ("03", "Living room", "usw", "USW-Flex-Mini", "02", 12, 1, 5, False, True),
    ("04", "Office switch", "usw", "USW-Lite-8-PoE", "02", 14, 1, 8, False, True),
    ("05", "Living room AP", "uap", "U6-Pro", "03", 2, 1, 0, False, True),
    ("06", "Office AP", "uap", "U6-Lite", "04", 2, 1, 0, False, True),
    ("07", "Garden AP", "uap", "U6-Mesh", "05", None, None, 0, True, False),
)
#: Average bit/s down and up per link, by the device that hangs on it; the WAN under "01".
_DEMO_TRAFFIC = {"01": (160e6, 18e6), "02": (170e6, 24e6), "03": (60e6, 4e6), "04": (90e6, 12e6), "05": (35e6, 3e6), "06": (20e6, 2e6)}
_DEMO_CLIENTS = (
    # mac suffix, name, switch suffix, port, down, up
    ("11", "nas01", "02", 26, 640e6, 30e6),
    ("12", "pve", "02", 3, 8e6, 640e6),
    ("13", "docker", "02", 4, 12e6, 45e6),
    ("14", "homeassistant", "02", 6, 2e6, 1e6),
    ("15", "Front door camera", "02", 20, 40e3, 4e6),
    ("16", "TV", "03", 3, 25e6, 400e3),
    ("17", "Apple TV", "03", 4, 30e6, 1e6),
    ("18", "Workstation", "04", 3, 70e6, 9e6),
    ("19", "Printer", "04", 5, 1e3, 600.0),
)


def _mac(suffix: str) -> str:
    return f"02:00:5e:00:00:{suffix}"


def _demo_bytes(average_bits: float, t: float, phase: float) -> float:
    """A counter whose rate swings around the average with a five-minute period."""
    omega = 2 * math.pi / 300
    rate = average_bits / 8
    return rate * (t - 0.5 / omega * math.cos(omega * t + phase)) + 1e9


def demo_console(now: float) -> tuple[list[dict], list[dict], list[dict], dict[str, str]]:
    devices: list[dict[str, Any]] = []
    port_traffic: dict[tuple[str, int], tuple[float, float]] = {}
    for suffix, _name, _type, _model, up, up_port, _own, _ports, wireless, _online in _DEMO_DEVICES:
        if up and up_port is not None and not wireless:
            port_traffic[(up, up_port)] = _DEMO_TRAFFIC.get(suffix, (1e6, 1e6))
    for _suffix, _name, switch, port, down, up in _DEMO_CLIENTS:
        port_traffic[(switch, port)] = (down, up)
    for index, (suffix, name, kind, model, up, up_port, own, ports, wireless, online) in enumerate(_DEMO_DEVICES):
        period = 2.0 if kind == "udm" else 70.0 + 3 * index
        offset = index * 11.0
        seen = math.floor((now + offset) / period) * period - offset
        if not online:
            seen = now - 3 * 3600
        table = []
        for port in range(1, ports + 1):
            down, upward = port_traffic.get((suffix, port), (0.0, 0.0))
            active = (suffix, port) in port_traffic or port == own
            if not active:
                continue
            table.append({
                "port_idx": port, "name": f"Port {port}", "up": True, "speed": 10000 if port >= 25 else 1000,
                "tx_bytes": _demo_bytes(down, seen, port), "rx_bytes": _demo_bytes(upward, seen, port + 1.0),
                "tx_bytes-r": down / 8, "rx_bytes-r": upward / 8,
            })
        device: dict[str, Any] = {
            "mac": _mac(suffix), "name": name, "type": kind, "model": model, "state": 1 if online else 0,
            "last_seen": seen, "uptime": 41 * 86400 if online else 0, "ip": f"192.168.1.{index + 1}", "version": "7.1.68",
            "port_table": table, "num_sta": {"05": 18, "06": 6, "07": 0}.get(suffix, 0),
        }
        if kind == "udm":
            down, upward = _DEMO_TRAFFIC["01"]
            device["uplink"] = {"type": "wire", "port_idx": 9, "speed": 1000,
                                "rx_bytes": _demo_bytes(down, seen, 0.5), "tx_bytes": _demo_bytes(upward, seen, 1.5)}
            device["system-stats"] = {"cpu": "23", "mem": "58"}
        elif wireless:
            device["uplink"] = {"type": "wireless", "uplink_mac": _mac(up), "tx_rate": 600000, "rx_rate": 600000,
                                "rx_bytes": 0, "tx_bytes": 0}
        else:
            device["uplink"] = {"type": "wire", "uplink_mac": _mac(up), "uplink_remote_port": up_port, "port_idx": own}
        devices.append(device)
    stations = [{"mac": _mac(suffix), "name": name, "is_wired": True, "sw_mac": _mac(switch), "sw_port": port,
                 "ip": f"192.168.1.{40 + int(suffix)}"} for suffix, name, switch, port, _down, _up in _DEMO_CLIENTS]
    health = [{"subsystem": "wan", "status": "ok", "isp_name": "Example Fibre"}]
    return devices, stations, health, {}
