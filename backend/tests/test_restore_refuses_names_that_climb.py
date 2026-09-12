"""An archive with a file name that leads out of its folder is refused before anything is replaced.

⚠️ The accompanying files are picked by their first folder, and ``avatars/..``
has ``avatars`` as its first folder. The check before writing refused a slash
and a backslash in the rest of the name, not ``..``. By then the database had
already been swapped: writing to ``avatars/..`` hit the data directory itself,
and the restore stopped halfway, on the new database without its migrations,
with the old key in memory and nobody signed out. Found on 12.09.2026.
"""

from __future__ import annotations

import io

import pytest
import pyzipper
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import User
from app.services import backup

from .conftest import CSRF, create_user, setup_admin

PASSWORD = "a-long-enough-password"


def _an_archive(client: TestClient) -> bytes:
    made = client.post("/api/v1/backups", json={"note": "for the test"}, headers=CSRF)
    assert made.status_code in (200, 201), made.text
    packed = client.post(f"/api/v1/backups/{made.json()['name']}/archive", json={"password": PASSWORD}, headers=CSRF)
    assert packed.status_code == 200, packed.text
    return packed.content


def _with_an_extra(archive: bytes, name: str) -> bytes:
    out = io.BytesIO()
    with pyzipper.AESZipFile(io.BytesIO(archive)) as source, pyzipper.AESZipFile(
        out, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as target:
        source.setpassword(PASSWORD.encode())
        target.setpassword(PASSWORD.encode())
        for entry in source.namelist():
            target.writestr(entry, source.read(entry))
        target.writestr(name, b"not a picture")
    return out.getvalue()


@pytest.mark.parametrize("name", ["avatars/..", "uploads/.", "avatars/../secret.key", "uploads/one\\..\\two"])
def test_an_archive_with_a_climbing_name_is_refused_and_nothing_changes(client: TestClient, name: str) -> None:
    setup_admin(client)
    archive = _with_an_extra(_an_archive(client), name)
    # Made after the archive, so a restore that went through would take it away.
    create_user(client, "after-the-archive")

    with pytest.raises(backup.BackupError) as looked:
        backup.inspect(archive, PASSWORD)
    assert looked.value.code == "not_a_backup"

    with pytest.raises(backup.BackupError) as refused:
        backup.restore(archive, PASSWORD)
    assert refused.value.code == "not_a_backup"
    with db_session() as db:
        assert db.scalar(select(User).where(User.username == "after-the-archive")) is not None


def test_an_archive_with_ordinary_names_still_goes_back(client: TestClient) -> None:
    setup_admin(client)
    archive = _with_an_extra(_an_archive(client), "uploads/7.png")
    verdict = backup.restore(archive, PASSWORD)
    assert verdict.restorable
