"""Tests for descriptor-relative directory traversal."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from secure_directory import open_directory_chain
from snapshot import SnapshotError


def test_opens_normal_directory(tmp_path):
    target = tmp_path / "first" / "second"
    target.mkdir(parents=True)

    with open_directory_chain(target) as fd:
        assert os.fstat(fd).st_ino == target.stat().st_ino


def test_rejects_relative_path():
    with pytest.raises(SnapshotError):
        with open_directory_chain(Path("relative/path")):
            pass


def test_rejects_intermediate_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "child").mkdir()

    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(OSError):
        with open_directory_chain(link / "child"):
            pass


def test_rejects_final_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()

    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(OSError):
        with open_directory_chain(link):
            pass


def test_descriptor_closed_after_context(tmp_path):
    descriptor = None

    with open_directory_chain(tmp_path) as fd:
        descriptor = fd
        os.fstat(fd)

    with pytest.raises(OSError):
        os.fstat(descriptor)
