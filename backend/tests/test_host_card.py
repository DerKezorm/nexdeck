"""The host card: what it reads out of /proc and /sys, and what it makes of it.

A small /proc and /sys are written into a temporary folder, so this runs on
Windows too, where there is no /proc at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context
from app.services import hoststats

STAT = "cpu  {user} 0 {system} {idle} {iowait} 0 0 0 0 0\ncpu0 1 0 1 1 0 0 0 0 0 0\ncpu1 1 0 1 1 0 0 0 0 0 0\nintr 1 2 3\n"
MEMINFO = """MemTotal:        8000000 kB
MemFree:          500000 kB
MemAvailable:    2000000 kB
Buffers:          100000 kB
Cached:          1000000 kB
SwapTotal:       1000000 kB
SwapFree:         750000 kB
"""


def machine(tmp_path: Path, *, user: int = 300, system: int = 100, idle: int = 500, iowait: int = 100,
            meminfo: str = MEMINFO, sensors: bool = True) -> tuple[Path, Path]:
    proc, sys = tmp_path / "proc", tmp_path / "sys"
    proc.mkdir(exist_ok=True)
    (proc / "stat").write_text(STAT.format(user=user, system=system, idle=idle, iowait=iowait), encoding="ascii")
    (proc / "meminfo").write_text(meminfo, encoding="ascii")
    (proc / "loadavg").write_text("0.52 0.61 0.70 2/345 6789\n", encoding="ascii")
    (proc / "uptime").write_text("1134000.12 4000000.00\n", encoding="ascii")
    if sensors:
        zone = sys / "class" / "thermal" / "thermal_zone0"
        zone.mkdir(parents=True, exist_ok=True)
        (zone / "temp").write_text("41000\n", encoding="ascii")
        (zone / "type").write_text("acpitz\n", encoding="ascii")
        chip = sys / "class" / "hwmon" / "hwmon1"
        chip.mkdir(parents=True, exist_ok=True)
        (chip / "name").write_text("coretemp\n", encoding="ascii")
        (chip / "temp1_input").write_text("57500\n", encoding="ascii")
        (chip / "temp1_label").write_text("Package id 0\n", encoding="ascii")
        (chip / "temp2_input").write_text("999999\n", encoding="ascii")  # a sensor reading nonsense
    return proc, sys


@pytest.fixture
def disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file system of 100 GB with 40 used; os.statvfs does not exist on Windows."""
    gib = 1024 ** 3
    monkeypatch.setattr(hoststats.os, "statvfs",
                        lambda path: SimpleNamespace(f_blocks=100 * gib // 4096, f_bfree=60 * gib // 4096, f_frsize=4096), raising=False)


def test_one_look_reads_every_part(tmp_path: Path, disk: None) -> None:
    proc, sys = machine(tmp_path)
    seen = hoststats.read("/data", proc=proc, sys=sys)
    assert seen.cpu == 40.0, "400 busy of 1000 jiffies since the start, iowait counted as idle"
    assert seen.cores == 2 and seen.sample == (400, 1000)
    assert seen.memory_total == 8_000_000 * 1024 and seen.memory_used == 6_000_000 * 1024, "used is total minus available"
    assert seen.swap_used == 250_000 * 1024
    assert seen.load == (0.52, 0.61, 0.70) and seen.uptime == 1134000.12
    assert seen.temperature == (57.5, "coretemp Package id 0"), "the warmest sane sensor, named"
    assert seen.disk_used * 100 // seen.disk_total == 40 and seen.missing == []


def test_the_processor_share_is_between_two_looks(tmp_path: Path, disk: None) -> None:
    proc, sys = machine(tmp_path)
    first = hoststats.read("/data", proc=proc, sys=sys)
    machine(tmp_path, user=390, system=110, idle=590, iowait=110)
    second = hoststats.read("/data", first.sample, proc=proc, sys=sys)
    assert second.cpu == 50.0, "100 busy of 200 jiffies between the two looks"


def test_an_old_kernel_without_memavailable_still_has_memory(tmp_path: Path, disk: None) -> None:
    old = "\n".join(line for line in MEMINFO.splitlines() if not line.startswith("MemAvailable")) + "\n"
    proc, sys = machine(tmp_path, meminfo=old, sensors=False)
    seen = hoststats.read("/data", proc=proc, sys=sys)
    assert seen.memory_used == (8_000_000 - 500_000 - 100_000 - 1_000_000) * 1024
    assert seen.temperature is None


def test_without_proc_the_card_says_what_to_use_instead(tmp_path: Path) -> None:
    with pytest.raises(hoststats.NoProc):
        hoststats.read("/data", proc=tmp_path / "nothing", sys=tmp_path / "nothing")


async def test_the_card_draws_rows_and_keeps_its_sample(tmp_path: Path, disk: None, monkeypatch: pytest.MonkeyPatch) -> None:
    proc, sys = machine(tmp_path)
    monkeypatch.setattr(hoststats, "PROC", proc)
    monkeypatch.setattr(hoststats, "SYS", sys)
    ctx = Context(httpx.AsyncClient(), integration_id=None, widget_id=7, cache={})
    card = await get_adapter("core").fetch("host", {}, {"disk": "/data"}, ctx)
    rows = {row["label"]: row for row in card.secondary}
    assert card.primary == {"label": "CPU", "value": 40.0, "unit": "%"}
    assert list(rows) == ["Memory", "Swap", "Load", "Temperature", "Disk", "Uptime"]
    assert rows["Memory"]["value"] == 75.0 and rows["Memory"]["hint"] == "5.7 GB of 7.6 GB"
    assert rows["Load"]["value"] == "0.52 0.61 0.70" and rows["Load"]["hint"] == "2 cores"
    assert rows["Temperature"] == {"label": "Temperature", "value": 57.5, "unit": "°C", "hint": "coretemp Package id 0"}
    assert rows["Disk"]["value"] == 40.0 and rows["Disk"]["hint"].endswith("· /data")
    assert rows["Uptime"]["value"] == "13d 3h"
    assert card.metrics == {"cpu": 40.0, "memory": 75.0} and card.status == "ok"
    assert ctx.cache["host:cpu:7"] == (400, 1000), "the next look measures from this one"
    hidden = await get_adapter("core").fetch("host", {}, {"disk": "/data", "temperature": False}, ctx)
    assert "Temperature" not in {row["label"] for row in hidden.secondary}


async def test_on_a_machine_without_proc_the_card_explains(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hoststats, "PROC", tmp_path / "nothing")
    ctx = Context(httpx.AsyncClient(), integration_id=None, widget_id=7, cache={})
    with pytest.raises(AdapterError) as refused:
        await get_adapter("core").fetch("host", {}, {}, ctx)
    assert refused.value.code == "no_proc" and "Glances" in (refused.value.hint or "")


def test_the_demo_is_a_machine() -> None:
    card = get_adapter("core").demo("host", {}, 0)
    assert card.primary["label"] == "CPU" and {row["label"] for row in card.secondary} >= {"Memory", "Disk", "Uptime"}
