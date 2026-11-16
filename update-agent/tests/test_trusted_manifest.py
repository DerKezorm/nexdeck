"""Security tests for descriptor-based manifest reading."""

import os

import pytest

from manifest_security import (
    ManifestSecurityError,
    MAX_MANIFEST_BYTES,
    read_trusted_manifest,
)


def create_manifest(tmp_path, content='{"deployment_id":"test"}'):
    directory = tmp_path / "enrollment"
    directory.mkdir(mode=0o700)

    path = directory / "deployment.json"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)

    return path


def test_valid_manifest_read(tmp_path):
    path = create_manifest(tmp_path)

    assert read_trusted_manifest(
        path,
        expected_uid=os.getuid(),
    ) == '{"deployment_id":"test"}'


def test_symlink_file_rejected(tmp_path):
    path = create_manifest(tmp_path)
    link = path.parent / "linked.json"
    link.symlink_to(path)

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            link,
            expected_uid=os.getuid(),
        )


def test_symlink_directory_rejected(tmp_path):
    path = create_manifest(tmp_path)
    link = tmp_path / "linked"
    link.symlink_to(path.parent, target_is_directory=True)

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            link / "deployment.json",
            expected_uid=os.getuid(),
        )


@pytest.mark.parametrize("mode", [0o620, 0o606, 0o666])
def test_writable_file_rejected(tmp_path, mode):
    path = create_manifest(tmp_path)
    path.chmod(mode)

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )


def test_writable_directory_rejected(tmp_path):
    path = create_manifest(tmp_path)
    path.parent.chmod(0o777)

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )


def test_hardlink_rejected(tmp_path):
    path = create_manifest(tmp_path)
    os.link(path, path.parent / "another.json")

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )


def test_directory_as_manifest_rejected(tmp_path):
    path = create_manifest(tmp_path)

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            path.parent,
            expected_uid=os.getuid(),
        )


def test_oversized_manifest_rejected(tmp_path):
    path = create_manifest(
        tmp_path,
        "x" * (MAX_MANIFEST_BYTES + 1),
    )

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )


def test_invalid_utf8_rejected(tmp_path):
    path = create_manifest(tmp_path)
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )


def test_relative_path_rejected():
    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            __import__("pathlib").Path("deployment.json"),
            expected_uid=os.getuid(),
        )


def test_unexpected_owner_rejected(tmp_path):
    path = create_manifest(tmp_path)

    with pytest.raises(ManifestSecurityError):
        read_trusted_manifest(
            path,
            expected_uid=os.getuid() + 1,
        )


def test_manifest_changed_during_read_rejected(tmp_path, monkeypatch):
    """Reject a file whose metadata changes during reading."""
    import manifest_security

    path = create_manifest(tmp_path)
    original_fstat = manifest_security.os.fstat

    target = path.stat()
    calls = 0

    def changing_fstat(fd):
        nonlocal calls

        details = original_fstat(fd)

        if (
            details.st_dev == target.st_dev
            and details.st_ino == target.st_ino
        ):
            calls += 1

            if calls == 3:
                values = list(details)
                # stat_result's nanosecond attributes are not
                # preserved by constructing from its tuple.
                class ChangedStat:
                    def __getattr__(self, name):
                        if name == "st_mtime_ns":
                            return details.st_mtime_ns + 1
                        return getattr(details, name)

                return ChangedStat()

        return details

    monkeypatch.setattr(
        manifest_security.os,
        "fstat",
        changing_fstat,
    )

    with pytest.raises(
        ManifestSecurityError,
        match="changed during reading",
    ):
        read_trusted_manifest(
            path,
            expected_uid=os.getuid(),
        )

    assert calls >= 3


def test_manifest_unchanged_read_succeeds(tmp_path):
    """A stable manifest remains readable."""
    path = create_manifest(tmp_path)

    result = read_trusted_manifest(
        path,
        expected_uid=os.getuid(),
    )

    assert result == '{"deployment_id":"test"}'


def test_directory_replacement_does_not_redirect_reader(
    tmp_path,
    monkeypatch,
):
    """An opened directory descriptor must not follow replacement."""
    import manifest_security

    original = create_manifest(
        tmp_path,
        '{"deployment_id":"original"}',
    )

    replacement = tmp_path / "replacement"
    replacement.mkdir(mode=0o700)

    replacement_file = replacement / "deployment.json"
    replacement_file.write_text(
        '{"deployment_id":"replacement"}',
        encoding="utf-8",
    )
    replacement_file.chmod(0o600)

    real_open = manifest_security.os.open
    replaced = False

    def replacing_open(path, flags, *args, **kwargs):
        nonlocal replaced

        fd = real_open(path, flags, *args, **kwargs)

        if path == "enrollment" and not replaced:
            replaced = True

            original.parent.rename(
                tmp_path / "enrollment-old"
            )

            replacement.rename(
                tmp_path / "enrollment"
            )

        return fd

    monkeypatch.setattr(
        manifest_security.os,
        "open",
        replacing_open,
    )

    with pytest.raises(
        ManifestSecurityError,
        match="Manifest directory changed during reading",
    ):
        read_trusted_manifest(
            original,
            expected_uid=os.getuid(),
        )

    assert replaced
