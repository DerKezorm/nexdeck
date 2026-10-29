"""B5 of the second security review: keys that are the names of machines are data, also when they read like a field name.

``nas01`` or ``pve-node2`` as a key goes to the provider as ``<keyN>`` and is made up in the examples, like a host with a
dot. Field names of real answers with a number in them (from the tests of the adapters) stay as they are.
"""

from __future__ import annotations

from app.cards import ai, demo
from tests.test_fortigate import envelope
from tests.test_octoprint import PRINTER_TWO_HEADS

NODES = {"nodes": {"nas01": {"cpu": 3}, "pve-node2": {"cpu": 1}, "node3": {"cpu": 2}}}
#: Real answers: OctoPrint's heaters (tool0, tool1), FortiGate's interfaces (wan1, internal1), Glances' load, hashes, .NET tuples.
REAL = {
    "printer": PRINTER_TWO_HEADS,
    "interfaces": envelope({"wan1": {"name": "wan1", "link": True}, "internal1": {"name": "internal1", "link": False}}),
    "load": {"min1": 0.4, "min5": 0.3, "min15": 0.2, "cpucore": 4},
    "file": {"sha256": "x", "md5": "y", "mp3": True, "ipv6": False, "icon192": "a.png", "Item1": 1, "Item2": 2, "cpu0": 5, "eth0": 1},
}


def test_karten8t_b5_machine_names_as_keys_go_as_stand_ins_without_the_tick() -> None:
    shown = ai.shape(NODES)
    for name in ("nas01", "pve-node2", "node3"):
        assert name not in shown, name
    assert "nodes.<key1>.cpu: number" in shown


def test_karten8t_b5_machine_names_as_keys_are_made_up_in_the_examples() -> None:
    made, _cut = demo.disguise({"r": NODES})
    keys = set(made["r"]["nodes"])
    assert len(keys) == 3 and not keys & {"nas01", "pve-node2", "node3"}
    assert all(key.startswith("host") for key in keys)


def test_karten8t_b5_field_names_of_real_answers_with_a_number_stay() -> None:
    shown = ai.shape(REAL, values=True)
    for path in ("printer.temperature.tool0.actual", "printer.temperature.tool1.target", "printer.temperature.bed", "load.min15",
                 "file.sha256", "file.Item1", "file.icon192", "file.cpu0", "file.eth0", "file.ipv6"):
        assert f"{path}:" in shown, path
    assert "wan1" in shown and "internal1" in shown
    made, _cut = demo.disguise({"r": REAL})
    assert set(made["r"]["printer"]["temperature"]) == {"bed", "chamber", "tool0", "tool1"}
    assert set(made["r"]["load"]) == set(REAL["load"])
