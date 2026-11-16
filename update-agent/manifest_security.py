"""Security checks for administrator-controlled enrollment files.

Inspection only. No file modification or Docker operations.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class ManifestSecurityError(ValueError):
    """Enrollment file failed security verification."""


def inspect_manifest_file(
    path: Path,
    expected_uid: int = 0,
) -> os.stat_result:
    """Inspect a manifest without following its final symlink."""

    if not isinstance(path, Path):
        raise ManifestSecurityError(
            "Manifest path must be a Path"
        )

    if not path.is_absolute():
        raise ManifestSecurityError(
            "Manifest path must be absolute"
        )

    if ".." in path.parts:
        raise ManifestSecurityError(
            "Parent traversal is forbidden"
        )

    try:
        details = path.lstat()
    except OSError as exc:
        raise ManifestSecurityError(
            "Cannot inspect manifest"
        ) from exc

    if not stat.S_ISREG(details.st_mode):
        raise ManifestSecurityError(
            "Manifest must be a regular file"
        )

    if details.st_uid != expected_uid:
        raise ManifestSecurityError(
            "Manifest has unexpected owner"
        )

    if details.st_mode & 0o022:
        raise ManifestSecurityError(
            "Manifest is group or world writable"
        )

    if details.st_nlink != 1:
        raise ManifestSecurityError(
            "Manifest must not have multiple hard links"
        )

    return details


MAX_MANIFEST_BYTES = 64 * 1024


def read_trusted_manifest(
    path: Path,
    expected_uid: int = 0,
) -> str:
    """Read enrollment through verified directory and file descriptors.

    Every directory must be owned by expected_uid and must not be
    writable by group or others. Symbolic links are never followed.
    """

    if not isinstance(path, Path) or not path.is_absolute():
        raise ManifestSecurityError(
            "Manifest path must be absolute"
        )

    if ".." in path.parts or path == Path("/"):
        raise ManifestSecurityError(
            "Invalid manifest path"
        )

    if not isinstance(expected_uid, int) or expected_uid < 0:
        raise ManifestSecurityError(
            "Invalid expected owner"
        )

    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC
    )

    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | os.O_CLOEXEC
    )

    directory_fd = None
    directory_chain = []

    try:
        directory_fd = os.open("/", directory_flags)
        directory_chain.append(
            (None, None, directory_fd)
        )

        for component in path.parts[1:-1]:
            next_fd = os.open(
                component,
                directory_flags,
                dir_fd=directory_fd,
            )

            directory_chain.append(
                (directory_fd, component, next_fd)
            )
            directory_fd = next_fd

            details = os.fstat(directory_fd)

            if (
                not stat.S_ISDIR(details.st_mode)
                or details.st_uid not in (0, expected_uid)
                or details.st_mode & 0o022
            ):
                raise ManifestSecurityError(
                    "Untrusted manifest parent directory"
                )

        root_details = os.stat("/")
        if (
            root_details.st_uid not in (0, expected_uid)
            or root_details.st_mode & 0o022
        ):
            raise ManifestSecurityError(
                "Untrusted filesystem root"
            )

        file_fd = os.open(
            path.name,
            file_flags,
            dir_fd=directory_fd,
        )

        try:
            details = os.fstat(file_fd)

            if not stat.S_ISREG(details.st_mode):
                raise ManifestSecurityError(
                    "Manifest must be a regular file"
                )

            if details.st_uid != expected_uid:
                raise ManifestSecurityError(
                    "Manifest has unexpected owner"
                )

            if details.st_mode & 0o022:
                raise ManifestSecurityError(
                    "Manifest is group or world writable"
                )

            if details.st_nlink != 1:
                raise ManifestSecurityError(
                    "Manifest must have exactly one hard link"
                )

            if details.st_size > MAX_MANIFEST_BYTES:
                raise ManifestSecurityError(
                    "Manifest exceeds size limit"
                )

            before = os.fstat(file_fd)

            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                content = stream.read(MAX_MANIFEST_BYTES + 1)

            after = os.fstat(file_fd)

            if (
                before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
            ):
                raise ManifestSecurityError(
                    "Manifest changed during reading"
                )

            if len(content) > MAX_MANIFEST_BYTES:
                raise ManifestSecurityError(
                    "Manifest exceeds size limit"
                )

            for parent_fd, name, opened_fd in directory_chain[1:]:
                current = os.stat(
                    name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                opened = os.fstat(opened_fd)

                if (
                    current.st_dev != opened.st_dev
                    or current.st_ino != opened.st_ino
                ):
                    raise ManifestSecurityError(
                        "Manifest directory changed during reading"
                    )

            try:
                return content.decode("utf-8")
            except UnicodeError as exc:
                raise ManifestSecurityError(
                    "Manifest is not valid UTF-8"
                ) from exc

        finally:
            os.close(file_fd)

    except OSError as exc:
        raise ManifestSecurityError(
            "Cannot securely read deployment manifest"
        ) from exc

    finally:
        for _, _, opened_fd in reversed(directory_chain):
            os.close(opened_fd)
