"""Regression tests for the update agent's backup verification."""

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compose_runner import ComposeRunner, UpdateError


@pytest.fixture
def backup_workspace(tmp_path):
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)

    deployment = SimpleNamespace(data_directory=data)
    runner = ComposeRunner(deployment)

    name = "nexdeck-manual-test-Pre-update-restore-point.db"
    database = backups / name

    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)"
    )
    connection.execute(
        "INSERT INTO example (value) VALUES ('verified')"
    )
    connection.commit()
    connection.close()

    profile = {
        "version": "test",
        "schema": 1,
        "created_at": "2026-11-11T17:00:00+00:00",
        "kind": "manual",
        "note": "Pre-update restore point",
        "contains": ["nexdeck.db"],
        "emptied": [],
    }

    database.with_suffix(".json").write_text(
        json.dumps(profile), encoding="utf-8"
    )

    return runner, database


def test_valid_backup_accepted(backup_workspace):
    runner, database = backup_workspace
    runner.verify_backup(database.name)


def test_missing_backup_rejected(backup_workspace):
    runner, _ = backup_workspace

    with pytest.raises(UpdateError):
        runner.verify_backup("nexdeck-manual-missing.db")


def test_corrupt_database_rejected(backup_workspace):
    runner, database = backup_workspace
    database.write_bytes(b"Not a SQLite database" * 500)

    with pytest.raises(UpdateError):
        runner.verify_backup(database.name)


def test_missing_profile_rejected(backup_workspace):
    runner, database = backup_workspace
    database.with_suffix(".json").unlink()

    with pytest.raises(UpdateError):
        runner.verify_backup(database.name)


def test_wrong_backup_note_rejected(backup_workspace):
    runner, database = backup_workspace
    profile_path = database.with_suffix(".json")
    profile = json.loads(profile_path.read_text())
    profile["note"] = "Unrelated backup"
    profile_path.write_text(json.dumps(profile))

    with pytest.raises(UpdateError):
        runner.verify_backup(database.name)


@pytest.mark.parametrize(
    "filename",
    [
        "../nexdeck-manual-test.db",
        "/tmp/nexdeck-manual-test.db",
        "nexdeck-automatic-test.db",
        "nexdeck-manual-test.db/../../other.db",
    ],
)
def test_unsafe_backup_name_rejected(backup_workspace, filename):
    runner, _ = backup_workspace

    with pytest.raises(UpdateError):
        runner.verify_backup(filename)
