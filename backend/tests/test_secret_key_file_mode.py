"""The key that unlocks every stored secret is readable by its owner only.

⚠️ Since 07.09.2026 a new key file is written with 0600, but a file from an
installation set up before that was only ever read, and kept the 0644 the
umask gave it under Docker: every account on the host that can see the data
volume could decrypt every stored API key. Found on 12.09.2026.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import config


@pytest.fixture
def key_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("NEXDECK_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("NEXDECK_SECRET_KEY", raising=False)
    config.reset_settings_cache()
    yield tmp_path
    config.reset_settings_cache()


def test_a_key_file_from_an_older_installation_is_narrowed_to_its_owner(key_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = key_dir / "secret.key"
    key_file.write_text("a-key-from-before", encoding="utf-8")
    narrowed: list[tuple[str, int]] = []
    real_chmod = Path.chmod

    def recording(self: Path, mode: int, *args: object, **kwargs: object) -> None:
        narrowed.append((self.name, mode))
        real_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", recording)
    assert config.get_settings().resolved_secret_key() == "a-key-from-before"
    assert ("secret.key", 0o600) in narrowed
    if os.name != "nt":  # Windows has no mode bits to read back.
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_a_key_file_that_cannot_be_narrowed_is_still_read(key_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A read-only volume refuses chmod, and the installation must still start."""
    (key_dir / "secret.key").write_text("a-key-on-a-read-only-volume", encoding="utf-8")

    def refuse(self: Path, mode: int, *args: object, **kwargs: object) -> None:
        raise PermissionError("read-only file system")

    monkeypatch.setattr(Path, "chmod", refuse)
    assert config.get_settings().resolved_secret_key() == "a-key-on-a-read-only-volume"
