"""Offline recovery-package tests using disposable NexDeck data."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recovery_point import create_recovery_point


@pytest.fixture
def recovery_workspace(tmp_path):
    source = tmp_path / "source"
    recovery = tmp_path / "recovery"

    source.mkdir()
    recovery.mkdir()

    database = source / "nexdeck.db"

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO example (value) VALUES ('original')"
        )

    profile = {
        "version": "test",
        "schema": 1,
        "created_at": "2026-11-11T17:00:00+00:00",
        "kind": "manual",
        "note": "Pre-update restore point",
        "contains": [
            "nexdeck.db",
            "avatars/example.png",
            "uploads/document.pdf",
            "brand/logo.png",
        ],
        "emptied": [],
    }

    (source / "nexdeck-backup.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    (source / "secret.key").write_text(
        "disposable-test-secret",
        encoding="utf-8",
    )
    (source / "secret.key").chmod(0o600)

    for directory, filename in (
        ("avatars", "example.png"),
        ("uploads", "document.pdf"),
        ("brand", "logo.png"),
    ):
        folder = source / directory
        folder.mkdir()
        (folder / filename).write_bytes(
            f"original-{filename}".encode()
        )

    return source, recovery


def test_preserves_complete_recovery_material(recovery_workspace):
    source, recovery = recovery_workspace

    result = create_recovery_point(
        source,
        recovery,
        "nexdeck-update-test-001",
    )

    preserved = result / "data"
    manifest = json.loads(
        (result / "manifest.json").read_text()
    )

    expected = {
        "nexdeck.db",
        "nexdeck-backup.json",
        "secret.key",
        "avatars/example.png",
        "uploads/document.pdf",
        "brand/logo.png",
    }

    actual = {
        record["path"]
        for record in manifest["files"]
    }

    assert actual == expected

    for record in manifest["files"]:
        path = preserved / record["path"]

        assert path.is_file()
        assert path.stat().st_size == record["size"]
        assert hashlib.sha256(
            path.read_bytes()
        ).hexdigest() == record["sha256"]


def test_recovery_point_independent_of_source(recovery_workspace):
    source, recovery = recovery_workspace

    result = create_recovery_point(
        source,
        recovery,
        "nexdeck-update-test-002",
    )

    preserved_key = (
        result / "data" / "secret.key"
    ).read_bytes()

    preserved_avatar = (
        result / "data" / "avatars" / "example.png"
    ).read_bytes()

    (source / "secret.key").write_text("changed-test-secret")
    (source / "avatars" / "example.png").write_bytes(
        b"changed-avatar"
    )

    assert (
        result / "data" / "secret.key"
    ).read_bytes() == preserved_key

    assert (
        result / "data" / "avatars" / "example.png"
    ).read_bytes() == preserved_avatar


def test_preserved_sqlite_database_is_readable(recovery_workspace):
    source, recovery = recovery_workspace

    result = create_recovery_point(
        source,
        recovery,
        "nexdeck-update-test-003",
    )

    database = result / "data" / "nexdeck.db"

    with sqlite3.connect(
        f"file:{database}?mode=ro",
        uri=True,
    ) as connection:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        value = connection.execute(
            "SELECT value FROM example"
        ).fetchone()[0]

    assert integrity == "ok"
    assert value == "original"


def test_recovery_directories_are_private(recovery_workspace):
    source, recovery = recovery_workspace

    result = create_recovery_point(
        source,
        recovery,
        "nexdeck-update-permissions-001",
    )

    directories = [
        result,
        result / "data",
        result / "data" / "avatars",
        result / "data" / "uploads",
        result / "data" / "brand",
    ]

    for directory in directories:
        permissions = directory.stat().st_mode & 0o777

        assert permissions & 0o077 == 0, (
            f"Directory is accessible to group/others: "
            f"{directory.relative_to(result)} "
            f"({permissions:04o})"
        )


def test_recovery_files_are_private(recovery_workspace):
    source, recovery = recovery_workspace

    result = create_recovery_point(
        source,
        recovery,
        "nexdeck-update-permissions-002",
    )

    for path in result.rglob("*"):
        if not path.is_file():
            continue

        permissions = path.stat().st_mode & 0o777

        assert permissions & 0o077 == 0, (
            f"Recovery file accessible to group/others: "
            f"{path.relative_to(result)} "
            f"({permissions:04o})"
        )


def test_recovery_private_with_permissive_umask(
    recovery_workspace,
):
    """Private output must not depend on the process umask."""
    import os
    import subprocess

    source, recovery = recovery_workspace

    script = """
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from recovery_point import create_recovery_point

os.umask(0o000)

create_recovery_point(
    Path(sys.argv[2]),
    Path(sys.argv[3]),
    "nexdeck-update-umask-001",
)
"""

    agent_directory = str(
        Path(__file__).resolve().parents[1]
    )

    subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            agent_directory,
            str(source),
            str(recovery),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    result = recovery / "nexdeck-update-umask-001"

    for path in [result, *result.rglob("*")]:
        permissions = path.lstat().st_mode & 0o777

        assert permissions & 0o077 == 0, (
            f"Unsafe permissions: "
            f"{path.relative_to(result)} "
            f"({permissions:04o})"
        )
