"""Offline recovery assembler integration tests."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from recovery_assembler import assemble_recovery_package


@pytest.fixture
def assembly_workspace(tmp_path):
    data = tmp_path / "nexdeck-data"
    backups = data / "backups"
    recovery = tmp_path / "recovery"

    backups.mkdir(parents=True)
    recovery.mkdir()

    name = "nexdeck-manual-test-20261112.db"
    database = backups / name

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE example "
            "(id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO example(value) VALUES ('original')"
        )

    profile = {
        "version": "test",
        "schema": 1,
        "created_at": "2026-11-12T09:00:00+00:00",
        "kind": "manual",
        "note": "Pre-update restore point",
        "contains": [
            "nexdeck.db",
            "avatars/example.png",
            "uploads/document.pdf",
        ],
        "emptied": [],
    }

    database.with_suffix(".json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    extras = backups / (
        database.stem + "-files"
    )

    (extras / "avatars").mkdir(parents=True)
    (extras / "uploads").mkdir()

    (extras / "avatars" / "example.png").write_bytes(
        b"test-avatar"
    )

    (extras / "uploads" / "document.pdf").write_bytes(
        b"test-document"
    )

    key = data / "secret.key"
    key.write_text(
        "disposable-test-encryption-key",
        encoding="utf-8",
    )
    key.chmod(0o600)

    return data, recovery, name


def test_assembles_complete_recovery_point(
    assembly_workspace,
):
    data, recovery, name = assembly_workspace

    original_database = (
        data / "backups" / name
    ).read_bytes()

    result = assemble_recovery_package(
        data,
        name,
        recovery,
        "recovery-test-001",
    )

    assert result.is_dir()

    preserved = result / "data"

    expected = {
        "nexdeck.db",
        "nexdeck-backup.json",
        "secret.key",
        "avatars/example.png",
        "uploads/document.pdf",
    }

    manifest = json.loads(
        (result / "manifest.json").read_text()
    )

    actual = {
        record["path"]
        for record in manifest["files"]
    }

    assert actual == expected

    with sqlite3.connect(
        preserved / "nexdeck.db"
    ) as connection:
        value = connection.execute(
            "SELECT value FROM example"
        ).fetchone()[0]

    assert value == "original"

    assert (
        preserved / "secret.key"
    ).read_text() == "disposable-test-encryption-key"

    assert (
        data / "backups" / name
    ).read_bytes() == original_database


def test_rejects_environment_key(
    assembly_workspace,
):
    data, recovery, name = assembly_workspace

    with pytest.raises(
        Exception,
        match="external_key_requires_recovery_plan",
    ):
        assemble_recovery_package(
            data,
            name,
            recovery,
            "recovery-test-002",
            environment_key_configured=True,
        )

    assert not (
        recovery / "recovery-test-002"
    ).exists()


def test_rejects_missing_attachment(
    assembly_workspace,
):
    data, recovery, name = assembly_workspace

    extras = (
        data / "backups" /
        (Path(name).stem + "-files")
    )

    (
        extras / "avatars" / "example.png"
    ).unlink()

    with pytest.raises(Exception):
        assemble_recovery_package(
            data,
            name,
            recovery,
            "recovery-test-003",
        )

    assert not (
        recovery / "recovery-test-003"
    ).exists()


def test_rejects_corrupt_database(assembly_workspace):
    data, recovery, name = assembly_workspace

    (data / "backups" / name).write_bytes(
        b"not a sqlite database"
    )

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-corrupt-db"
        )

    assert not (recovery / "attack-corrupt-db").exists()


def test_rejects_symlink_attachment(assembly_workspace):
    data, recovery, name = assembly_workspace

    extras = data / "backups" / (
        Path(name).stem + "-files"
    )

    attachment = extras / "avatars" / "example.png"
    attachment.unlink()
    attachment.symlink_to(data / "secret.key")

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-symlink"
        )

    assert not (recovery / "attack-symlink").exists()


def test_rejects_undeclared_attachment(assembly_workspace):
    data, recovery, name = assembly_workspace

    extras = data / "backups" / (
        Path(name).stem + "-files"
    )

    (extras / "uploads" / "unexpected.txt").write_text(
        "not in the backup profile"
    )

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-extra"
        )

    assert not (recovery / "attack-extra").exists()


def test_rejects_duplicate_profile_entries(assembly_workspace):
    data, recovery, name = assembly_workspace

    profile_path = (
        data / "backups" / name
    ).with_suffix(".json")

    profile = json.loads(profile_path.read_text())
    profile["contains"].append("avatars/example.png")

    profile_path.write_text(json.dumps(profile))

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-duplicate"
        )

    assert not (recovery / "attack-duplicate").exists()


def test_rejects_duplicate_recovery_id(assembly_workspace):
    data, recovery, name = assembly_workspace

    assemble_recovery_package(
        data, name, recovery, "attack-existing"
    )

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-existing"
        )

    assert (recovery / "attack-existing").is_dir()


def test_rejects_symlinked_backups_directory(
    assembly_workspace, tmp_path
):
    data, recovery, name = assembly_workspace

    original = data / "backups"
    relocated = tmp_path / "relocated-backups"

    original.rename(relocated)
    original.symlink_to(relocated, target_is_directory=True)

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-backups-link"
        )

    assert not (recovery / "attack-backups-link").exists()


def test_rejects_symlinked_attachment_directory(
    assembly_workspace, tmp_path
):
    data, recovery, name = assembly_workspace

    extras = data / "backups" / (
        Path(name).stem + "-files"
    )

    original = extras / "avatars"
    relocated = tmp_path / "relocated-avatars"

    original.rename(relocated)
    original.symlink_to(relocated, target_is_directory=True)

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-avatar-dir"
        )

    assert not (recovery / "attack-avatar-dir").exists()


def test_rejects_symlinked_secret_key(
    assembly_workspace, tmp_path
):
    data, recovery, name = assembly_workspace

    key = data / "secret.key"
    relocated = tmp_path / "relocated-secret.key"

    key.rename(relocated)
    key.symlink_to(relocated)

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-key-link"
        )

    assert not (recovery / "attack-key-link").exists()


def test_rejects_profile_path_traversal(
    assembly_workspace
):
    data, recovery, name = assembly_workspace

    profile_path = (
        data / "backups" / name
    ).with_suffix(".json")

    profile = json.loads(profile_path.read_text())

    profile["contains"].append(
        "uploads/../../secret.key"
    )

    profile_path.write_text(json.dumps(profile))

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-traversal"
        )

    assert not (recovery / "attack-traversal").exists()


def test_rejects_database_corrupted_during_assembly(
    assembly_workspace, monkeypatch
):
    import recovery_assembler

    data, recovery, name = assembly_workspace
    original_copy = recovery_assembler.copy_regular_file

    def corrupting_copy(
        source_dir_fd,
        source_name,
        destination_dir_fd,
        destination_name,
    ):
        result = original_copy(
            source_dir_fd,
            source_name,
            destination_dir_fd,
            destination_name,
        )

        if destination_name == "nexdeck.db":
            fd = __import__("os").open(
                destination_name,
                __import__("os").O_WRONLY,
                dir_fd=destination_dir_fd,
            )
            try:
                __import__("os").pwrite(
                    fd, b"CORRUPTED DATABASE", 0
                )
            finally:
                __import__("os").close(fd)

        return result

    monkeypatch.setattr(
        recovery_assembler,
        "copy_regular_file",
        corrupting_copy,
    )

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-copy-corruption"
        )

    assert not (
        recovery / "attack-copy-corruption"
    ).exists()


def test_rejects_profile_changed_during_assembly(
    assembly_workspace, monkeypatch
):
    import os
    import recovery_assembler

    data, recovery, name = assembly_workspace
    original_copy = recovery_assembler.copy_regular_file

    def changing_copy(
        source_dir_fd,
        source_name,
        destination_dir_fd,
        destination_name,
    ):
        result = original_copy(
            source_dir_fd,
            source_name,
            destination_dir_fd,
            destination_name,
        )

        if destination_name == "nexdeck-backup.json":
            fd = os.open(
                destination_name,
                os.O_WRONLY | os.O_TRUNC,
                dir_fd=destination_dir_fd,
            )
            try:
                os.write(
                    fd,
                    json.dumps({
                        "kind": "manual",
                        "note": "Changed after validation",
                        "contains": ["nexdeck.db"],
                    }).encode(),
                )
            finally:
                os.close(fd)

        return result

    monkeypatch.setattr(
        recovery_assembler,
        "copy_regular_file",
        changing_copy,
    )

    with pytest.raises(Exception):
        assemble_recovery_package(
            data, name, recovery, "attack-profile-change"
        )

    assert not (
        recovery / "attack-profile-change"
    ).exists()


def test_rejects_colon_attachment_before_publication(
    assembly_workspace,
):
    import json

    data, recovery, name = assembly_workspace

    profile_path = (
        data / "backups" / name
    ).with_suffix(".json")

    profile = json.loads(profile_path.read_text())

    profile["contains"] = [
        "nexdeck.db",
        "avatars/example:alternate.png",
    ]

    profile_path.write_text(json.dumps(profile))

    target = recovery / "attack-colon"

    with pytest.raises(Exception):
        assemble_recovery_package(
            data,
            name,
            recovery,
            "attack-colon",
        )

    assert not target.exists()
