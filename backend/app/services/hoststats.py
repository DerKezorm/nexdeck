"""The machine nexdeck runs on, read from what the Linux kernel writes anyway.

No agent and no library: /proc for processors, memory, load and uptime,
/sys for temperatures, statvfs for one file system.

Whose numbers these are was measured on 25.09.2026 on a Debian 13 host with
Docker 29.8: a container limited to 256 MB and one processor read the same
MemTotal, the same four processors and the same uptime from /proc as the
host. /proc/meminfo and /proc/stat are not namespaced; a container's limits
live in its cgroup. So nexdeck in Docker reads the machine without anything
mounted. Only under LXCFS, as in some LXC containers, does /proc describe the
container, and then the container is the machine the card is about.

The file system is the one exception: "/" inside a container is its overlay.
The card therefore defaults to the file system nexdeck keeps its data on,
which is a volume of the host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROC = Path("/proc")
SYS = Path("/sys")

#: Sensors outside this span are reading nonsense, not heat.
SANE_CELSIUS = (-40.0, 150.0)


class NoProc(Exception):
    """This machine has no /proc to read: Windows, macOS."""


@dataclass
class Machine:
    cpu: float | None = None
    #: busy and total jiffies, kept for the next reading.
    sample: tuple[int, int] | None = None
    cores: int = 0
    memory_total: int = 0
    memory_used: int = 0
    swap_total: int = 0
    swap_used: int = 0
    load: tuple[float, float, float] | None = None
    uptime: float | None = None
    temperature: tuple[float, str] | None = None
    disk_total: int = 0
    disk_used: int = 0
    disk_path: str = ""
    missing: list[str] = field(default_factory=list)


def _cpu_sample(proc: Path) -> tuple[tuple[int, int], int]:
    """busy and total jiffies of all processors together, and how many there are."""
    lines = (proc / "stat").read_text(encoding="ascii", errors="replace").splitlines()
    total_line = next(line for line in lines if line.startswith("cpu "))
    numbers = [int(part) for part in total_line.split()[1:]]
    # user nice system idle iowait irq softirq steal; guest time is already inside user.
    counted = numbers[:8]
    idle = counted[3] + (counted[4] if len(counted) > 4 else 0)
    total = sum(counted)
    cores = sum(1 for line in lines if line.startswith("cpu") and line[3:4].isdigit())
    return (total - idle, total), cores


def cpu_share(now: tuple[int, int], before: tuple[int, int] | None) -> float | None:
    """Busy per cent between two readings; with none before, since the machine started."""
    busy, total = now
    if before is not None:
        busy, total = busy - before[0], total - before[1]
    if total <= 0:
        return None
    return round(100 * busy / total, 1)


def _meminfo(proc: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in (proc / "meminfo").read_text(encoding="ascii", errors="replace").splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            # The kernel writes kB and means KiB.
            values[name.strip()] = int(parts[0]) * 1024
    return values


def warmest(sys: Path) -> tuple[float, str] | None:
    """The hottest sensor the kernel reports, and its name."""
    found: list[tuple[float, str]] = []
    for zone in sorted((sys / "class" / "thermal").glob("thermal_zone*")):
        reading = _millidegrees(zone / "temp")
        if reading is not None:
            found.append((reading, _first_line(zone / "type") or zone.name))
    for chip in sorted((sys / "class" / "hwmon").glob("hwmon*")):
        chip_name = _first_line(chip / "name") or chip.name
        for sensor in sorted(chip.glob("temp*_input")):
            reading = _millidegrees(sensor)
            if reading is not None:
                label = _first_line(sensor.with_name(sensor.name.replace("_input", "_label")))
                found.append((reading, f"{chip_name} {label}".strip() if label else chip_name))
    return max(found, key=lambda entry: entry[0]) if found else None


def _millidegrees(path: Path) -> float | None:
    try:
        value = int(path.read_text(encoding="ascii").strip()) / 1000
    except (OSError, ValueError):
        return None
    return round(value, 1) if SANE_CELSIUS[0] <= value <= SANE_CELSIUS[1] else None


def _first_line(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0]
    except (OSError, IndexError):
        return ""


def read(disk: str, before: tuple[int, int] | None = None, proc: Path | None = None, sys: Path | None = None) -> Machine:
    """One look at the machine. ``before`` is the CPU sample of the previous look."""
    proc, sys = proc or PROC, sys or SYS
    if not (proc / "stat").is_file():
        raise NoProc(str(proc))
    machine = Machine()
    machine.sample, machine.cores = _cpu_sample(proc)
    machine.cpu = cpu_share(machine.sample, before)
    try:
        memory = _meminfo(proc)
        machine.memory_total = memory.get("MemTotal", 0)
        available = memory.get("MemAvailable")
        if available is None:
            # Kernels before 3.14 do not write MemAvailable.
            available = memory.get("MemFree", 0) + memory.get("Buffers", 0) + memory.get("Cached", 0)
        machine.memory_used = max(0, machine.memory_total - available)
        machine.swap_total = memory.get("SwapTotal", 0)
        machine.swap_used = max(0, machine.swap_total - memory.get("SwapFree", 0))
    except OSError:
        machine.missing.append("memory")
    try:
        first = (proc / "loadavg").read_text(encoding="ascii").split()[:3]
        machine.load = (float(first[0]), float(first[1]), float(first[2]))
    except (OSError, ValueError, IndexError):
        machine.missing.append("load")
    try:
        machine.uptime = float((proc / "uptime").read_text(encoding="ascii").split()[0])
    except (OSError, ValueError, IndexError):
        machine.missing.append("uptime")
    machine.temperature = warmest(sys)
    try:
        stats = os.statvfs(disk)
        machine.disk_total = stats.f_blocks * stats.f_frsize
        machine.disk_used = (stats.f_blocks - stats.f_bfree) * stats.f_frsize
        machine.disk_path = disk
    except (OSError, AttributeError):
        # AttributeError: os.statvfs does not exist on Windows.
        machine.missing.append("disk")
    return machine

