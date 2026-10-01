"""The Proxmox cluster as a map: the cluster, its nodes, each node's guests."""

from __future__ import annotations

from app.adapters import get_adapter
from app.adapters.proxmox import map_of

NODES = [{"node": "pve", "status": "online", "cpu": 0.12, "mem": 4, "maxmem": 8}, {"node": "pve2", "status": "offline"}]
GUESTS = [
    {"node": "pve", "type": "qemu", "vmid": 101, "name": "media", "status": "running"},
    {"node": "pve", "type": "lxc", "vmid": 201, "name": "pihole", "status": "stopped"},
    {"node": "gone", "type": "lxc", "vmid": 9, "name": "orphan", "status": "running"},
]


def test_every_guest_hangs_under_its_node_and_a_node_that_is_off_is_red() -> None:
    data = map_of(NODES, GUESTS, show_stopped=True)
    places = {place["id"]: place for place in data.meta["topology"]["places"]}
    assert places["cluster"]["parent"] is None
    assert places["node/pve"]["detail"] == "CPU 12% · RAM 50%"
    assert places["node/pve2"]["status"] == "bad" and data.status == "bad"
    assert places["pve/qemu/101"]["parent"] == "node/pve" and places["pve/qemu/101"]["kind"] == "vm"
    assert places["pve/lxc/201"]["status"] == "unknown"
    assert places["gone/lxc/9"]["parent"] == "cluster", "a guest of a node it cannot see hangs on the cluster"
    assert data.primary["value"] == 2


def test_stopped_guests_can_be_left_out() -> None:
    ids = {place["id"] for place in map_of(NODES, GUESTS, show_stopped=False).meta["topology"]["places"]}
    assert "pve/lxc/201" not in ids and "pve/qemu/101" in ids


def test_the_demo_is_a_cluster_of_two() -> None:
    places = get_adapter("proxmox").demo("map", {"show_stopped": True}, 0).meta["topology"]["places"]
    assert [place["name"] for place in places if place["kind"] == "host"] == ["pve", "pve2"]
