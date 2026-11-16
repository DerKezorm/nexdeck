"""Tests for the read-only recovery inventory."""

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "recovery.py"
)

spec = importlib.util.spec_from_file_location(
    "nexdeck_agent_recovery",
    MODULE_PATH,
)

recovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = recovery
spec.loader.exec_module(recovery)


def test_empty_directory(tmp_path):
    assert recovery.inventory_directory(tmp_path) == []


def test_single_file_checksum(tmp_path):
    content = b"NexDeck recovery test"
    (tmp_path / "test.txt").write_bytes(content)

    records = recovery.inventory_directory(tmp_path)

    assert len(records) == 1
    assert records[0].path == "test.txt"
    assert records[0].size == len(content)
    assert records[0].sha256 == hashlib.sha256(
        content
    ).hexdigest()


def test_nested_directories(tmp_path):
    boards = tmp_path / "boards"
    boards.mkdir()

    (boards / "dashboard.yaml").write_text(
        "name: Test Dashboard\n",
        encoding="utf-8",
    )

    records = recovery.inventory_directory(tmp_path)

    assert len(records) == 1
    assert records[0].path == "boards/dashboard.yaml"


def test_sorted_inventory(tmp_path):
    (tmp_path / "z.txt").write_text("z")
    (tmp_path / "a.txt").write_text("a")

    records = recovery.inventory_directory(tmp_path)

    assert [record.path for record in records] == [
        "a.txt",
        "z.txt",
    ]


def test_symlinked_file_rejected(tmp_path):
    target = tmp_path / "actual.txt"
    target.write_text("secret")

    link = tmp_path / "linked.txt"
    link.symlink_to(target)

    with pytest.raises(recovery.RecoveryError):
        recovery.inventory_directory(tmp_path)


def test_symlinked_directory_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()

    link = tmp_path / "linked"
    link.symlink_to(actual, target_is_directory=True)

    with pytest.raises(recovery.RecoveryError):
        recovery.inventory_directory(tmp_path)


def test_symlinked_root_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()

    link = tmp_path / "linked"
    link.symlink_to(actual, target_is_directory=True)

    with pytest.raises(recovery.RecoveryError):
        recovery.inventory_directory(link)


def test_missing_root_rejected(tmp_path):
    with pytest.raises(recovery.RecoveryError):
        recovery.inventory_directory(
            tmp_path / "missing"
        )


def test_regular_file_root_rejected(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("not a directory")

    with pytest.raises(recovery.RecoveryError):
        recovery.inventory_directory(path)


def test_fifo_rejected(tmp_path):
    import os

    fifo = tmp_path / "special.pipe"
    os.mkfifo(fifo)

    with pytest.raises(recovery.RecoveryError):
        recovery.inventory_directory(tmp_path)


def test_direct_hash_matches_sha256(tmp_path):
    content = b"Verified NexDeck recovery"
    path = tmp_path / "payload.bin"
    path.write_bytes(content)

    assert recovery.sha256_file(path) == hashlib.sha256(
        content
    ).hexdigest()


def test_direct_hash_rejects_symlink(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("private data")

    link = tmp_path / "link.txt"
    link.symlink_to(target)

    with pytest.raises(OSError):
        recovery.sha256_file(link)


def test_direct_hash_rejects_fifo(tmp_path):
    import os

    fifo = tmp_path / "special.pipe"
    os.mkfifo(fifo)

    with pytest.raises(recovery.RecoveryError):
        recovery.sha256_file(fifo)


def test_direct_hash_rejects_directory(tmp_path):
    with pytest.raises(recovery.RecoveryError):
        recovery.sha256_file(tmp_path)


def test_direct_hash_rejects_missing_file(tmp_path):
    with pytest.raises(OSError):
        recovery.sha256_file(tmp_path / "missing.txt")
