"""Regression tests for recovery-material preflight."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recovery_preflight import assess_recovery_material


@pytest.fixture
def workspace(tmp_path):
    data = tmp_path / "data"
    backups = data / "backups"
    backups.mkdir(parents=True)

    name = "nexdeck-manual-test.db"
    database = backups / name
    database.write_bytes(b"SQLite test placeholder")

    profile = {
        "contains": [
            "nexdeck.db",
            "avatars/example.png",
        ]
    }

    database.with_suffix(".json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    extras = backups / "nexdeck-manual-test-files"
    (extras / "avatars").mkdir(parents=True)
    (extras / "avatars" / "example.png").write_bytes(b"image")

    key = data / "secret.key"
    key.write_text("test-key", encoding="utf-8")
    key.chmod(0o600)

    return data, name


def test_complete_material_present(workspace):
    data, name = workspace
    result = assess_recovery_material(data, name)

    assert result.ready is True
    assert result.reason == "material_present"
    assert result.key_source == "file"
    assert result.files_checked == 1


def test_missing_key_rejected(workspace):
    data, name = workspace
    (data / "secret.key").unlink()

    result = assess_recovery_material(data, name)

    assert result.ready is False
    assert result.reason == "missing_key"


def test_insecure_key_permissions_rejected(workspace):
    data, name = workspace
    (data / "secret.key").chmod(0o644)

    result = assess_recovery_material(data, name)

    assert result.ready is False
    assert result.reason == "insecure_key_permissions"


def test_environment_key_requires_plan(workspace):
    data, name = workspace

    result = assess_recovery_material(
        data,
        name,
        environment_key_configured=True,
    )

    assert result.ready is False
    assert result.reason == "external_key_requires_recovery_plan"


def test_missing_extra_rejected(workspace):
    data, name = workspace
    extra = (
        data / "backups"
        / "nexdeck-manual-test-files"
        / "avatars"
        / "example.png"
    )
    extra.unlink()

    result = assess_recovery_material(data, name)

    assert result.ready is False
    assert result.reason == "missing_extra"


def test_extra_symlink_rejected(workspace):
    data, name = workspace
    extra = (
        data / "backups"
        / "nexdeck-manual-test-files"
        / "avatars"
        / "example.png"
    )
    extra.unlink()
    extra.symlink_to(data / "secret.key")

    result = assess_recovery_material(data, name)

    assert result.ready is False
    assert result.reason == "unsafe_extra"


@pytest.mark.parametrize(
    "entry",
    [
        "../secret.key",
        "avatars/../secret.key",
        "avatars/subfolder/file.png",
        "avatars\\example.png",
        "/etc/passwd",
    ],
)
def test_unsafe_extra_paths_rejected(workspace, entry):
    data, name = workspace
    profile_path = data / "backups" / name.replace(".db", ".json")
    profile_path.write_text(
        json.dumps({"contains": ["nexdeck.db", entry]})
    )

    result = assess_recovery_material(data, name)

    assert result.ready is False


def test_symlinked_extra_directory_rejected(workspace):
    data, name = workspace

    extras = data / "backups" / "nexdeck-manual-test-files"
    avatars = extras / "avatars"
    original = extras / "original"

    avatars.rename(original)
    avatars.symlink_to(original, target_is_directory=True)

    result = assess_recovery_material(data, name)

    assert result.ready is False


def test_realistic_backup_profile_with_multiple_extras(workspace):
    data, name = workspace
    backups = data / "backups"
    extras = backups / "nexdeck-manual-test-files"

    for directory, filename in (
        ("uploads", "document.pdf"),
        ("brand", "logo.png"),
    ):
        folder = extras / directory
        folder.mkdir()
        (folder / filename).write_bytes(b"test-content")

    profile_path = backups / name.replace(".db", ".json")
    profile = json.loads(profile_path.read_text())
    profile["contains"] = [
        "nexdeck.db",
        "avatars/example.png",
        "uploads/document.pdf",
        "brand/logo.png",
    ]
    profile_path.write_text(json.dumps(profile))

    result = assess_recovery_material(data, name)

    assert result.ready is True
    assert result.files_checked == 3


def test_database_only_profile_accepted_with_key(workspace):
    data, name = workspace
    profile_path = data / "backups" / name.replace(".db", ".json")
    profile_path.write_text(
        json.dumps({"contains": ["nexdeck.db"]})
    )

    result = assess_recovery_material(data, name)

    assert result.ready is True
    assert result.files_checked == 0


def test_missing_snapshot_database_rejected(workspace):
    data, name = workspace
    (data / "backups" / name).unlink()

    result = assess_recovery_material(data, name)

    assert result.ready is False
    assert result.reason == "missing_database"


def test_symlinked_backups_directory_rejected(workspace):
    data, name = workspace
    backups = data / "backups"
    original = data / "original-backups"

    backups.rename(original)
    backups.symlink_to(original, target_is_directory=True)

    result = assess_recovery_material(data, name)

    assert result.ready is False


def test_rejects_colon_attachment_path(workspace):
    import json

    data, name = workspace

    profile_path = (
        data / "backups" / name
    ).with_suffix(".json")

    profile = json.loads(profile_path.read_text())

    profile["contains"] = [
        "nexdeck.db",
        "avatars/example:alternate.png",
    ]

    profile_path.write_text(json.dumps(profile))

    assessment = assess_recovery_material(data, name)

    assert not assessment.ready
    assert assessment.reason == "invalid_extra_path"
