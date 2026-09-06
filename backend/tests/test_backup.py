"""Backups, and the ways one turns out to be worthless.

Each test here is one of them. A backup nobody notices is broken is worse
than no backup: it is the same loss, discovered later, after the operator has
already thrown the original away.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import pyzipper
from fastapi.testclient import TestClient

from app.services import backup

from .conftest import CSRF, create_user, login, setup_admin

PASSWORD = "an-archive-password"


def _make(client: TestClient, note: str = "") -> dict:
    made = client.post("/api/v1/backups", json={"note": note}, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()


def _archive(client: TestClient, name: str, password: str = PASSWORD) -> bytes:
    answer = client.post(f"/api/v1/backups/{name}/archive", json={"password": password}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    return answer.content


def _inside(blob: bytes, password: str = PASSWORD) -> dict[str, bytes]:
    with pyzipper.AESZipFile(io.BytesIO(blob)) as zip_file:
        zip_file.setpassword(password.encode("utf-8"))
        return {name: zip_file.read(name) for name in zip_file.namelist()}


# ---------------------------------------------------------------------------
# Writing one
# ---------------------------------------------------------------------------


def test_a_backup_holds_together(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    entry = _make(client, "before the migration")
    assert entry["kind"] == "manual"
    assert entry["note"] == "before the migration"
    assert entry["size"] > 0
    assert (data_dir / "backups" / entry["name"]).is_file()


def test_the_profile_lands_beside_it(client: TestClient, data_dir: Path) -> None:
    """Without it the list can only guess what a file is."""
    setup_admin(client)
    entry = _make(client)
    profile = json.loads((data_dir / "backups" / entry["name"].replace(".db", ".json")).read_text(encoding="utf-8"))
    assert profile["schema"] == backup.latest_schema()
    assert profile["contains"][0] == "nexdeck.db"
    assert "secret.key" not in profile["contains"], "the key joins when the archive is packed, not before"


def test_only_administrators(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    assert kim.get("/api/v1/backups").status_code == 403
    assert kim.post("/api/v1/backups", json={"note": ""}, headers=CSRF).status_code == 403


def test_the_list_says_what_can_go_back(client: TestClient) -> None:
    setup_admin(client)
    _make(client)
    listing = client.get("/api/v1/backups").json()
    assert listing["entries"][0]["restorable"] is True
    assert listing["folder"].endswith("backups")


def test_a_backup_from_a_newer_nexdeck_is_refused(client: TestClient) -> None:
    """⚠️ Forwards only. There is no migration that runs backwards, and a
    restore that half works is worse than one that refuses."""
    setup_admin(client)
    from app.services.backup import Profile, compatible

    ahead = Profile(version="9.9.9", schema=backup.latest_schema() + 1, created_at="", kind="manual")
    ok, reason = compatible(ahead)
    assert ok is False
    assert reason == "too_new"


def test_only_automatic_backups_are_swept(client: TestClient) -> None:
    """Somebody who deliberately made one must not lose it to a migration."""
    setup_admin(client)
    for index in range(backup.KEEP_AUTOMATIC + 2):
        backup.create(kind=backup.AUTOMATIC, note=f"run {index}")
    by_hand = _make(client, "keep me")
    backup.sweep()
    names = {entry["name"] for entry in client.get("/api/v1/backups").json()["entries"]}
    assert by_hand["name"] in names
    automatic = [entry for entry in backup.listing() if entry.kind == backup.AUTOMATIC]
    assert len(automatic) == backup.KEEP_AUTOMATIC


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------


def test_the_archive_carries_the_key(client: TestClient, data_dir: Path) -> None:
    """⚠️ The reason this feature exists at all. Every service credential in
    the database is encrypted with the key in secret.key. Restore the database
    without it and nexdeck makes a new key, after which not one connection can
    be read and nobody suspects the key."""
    setup_admin(client)
    # The ordinary installation keeps it in a file. The tests run with
    # NEXDECK_SECRET_KEY set, so the file has to be put there on purpose.
    (data_dir / "secret.key").write_text("a-key-from-a-file", encoding="utf-8")
    entry = _make(client)
    files = _inside(_archive(client, entry["name"]))
    assert "nexdeck.db" in files
    assert files["secret.key"].decode("utf-8").strip() == "a-key-from-a-file"


def test_the_archive_needs_a_password(client: TestClient) -> None:
    """With the key inside, the file hands over everything."""
    setup_admin(client)
    entry = _make(client)
    short = client.post(f"/api/v1/backups/{entry['name']}/archive", json={"password": "short"}, headers=CSRF)
    assert short.status_code == 422


def test_the_wrong_password_opens_nothing(client: TestClient) -> None:
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    with pytest.raises(RuntimeError):
        _inside(blob, "a-different-password")


def test_the_profile_in_the_archive_lists_what_is_really_in_it(client: TestClient) -> None:
    """⚠️ It used to be written before the packing and named secret.key even
    where only a note about it went in. Nothing in nexdeck reads the field, so
    the only reader it could mislead is the person opening the ZIP by hand on
    a day when nexdeck is what stopped working."""
    setup_admin(client)
    entry = _make(client)
    files = _inside(_archive(client, entry["name"]))
    listed = set(json.loads(files["nexdeck-backup.json"])["contains"])
    assert listed == set(files) - {"nexdeck-backup.json"}


def test_an_installation_without_a_key_file_says_so_in_the_archive(client: TestClient, data_dir: Path) -> None:
    """The key can live in NEXDECK_SECRET_KEY instead. Then it is in that
    machine's Docker file, and the archive must not look complete."""
    setup_admin(client)
    entry = _make(client)
    (data_dir / "secret.key").unlink(missing_ok=True)  # noqa: F841 - the point of the test
    files = _inside(_archive(client, entry["name"]))
    assert "secret.key" not in files
    assert "NO-KEY-IN-HERE.txt" in files
    assert b"NEXDECK_SECRET_KEY" in files["NO-KEY-IN-HERE.txt"]


def test_profile_pictures_travel_with_it(client: TestClient, data_dir: Path) -> None:
    """⚠️ They live as files beside the database; the database only holds the
    name. Without them an installation comes back with everybody's picture
    gone, and nobody connects that to the restore."""
    setup_admin(client)
    avatars = data_dir / "avatars"
    avatars.mkdir(parents=True, exist_ok=True)
    (avatars / "someone.png").write_bytes(b"not really a png")
    entry = _make(client)
    files = _inside(_archive(client, entry["name"]))
    assert files.get("avatars/someone.png") == b"not really a png"


def test_the_files_are_taken_at_the_moment_of_the_backup(client: TestClient, data_dir: Path) -> None:
    """⚠️ Not read out of the live directory weeks later. A backup is a
    moment, and the pictures belong to that moment."""
    setup_admin(client)
    avatars = data_dir / "avatars"
    avatars.mkdir(parents=True, exist_ok=True)
    (avatars / "someone.png").write_bytes(b"the old one")
    entry = _make(client)
    (avatars / "someone.png").write_bytes(b"the new one")
    files = _inside(_archive(client, entry["name"]))
    assert files["avatars/someone.png"] == b"the old one"


def test_a_name_from_outside_cannot_leave_the_folder(client: TestClient) -> None:
    """⚠️ The name comes out of a URL, and the live database sits one
    directory up from the backups."""
    setup_admin(client)
    for bad in ("../nexdeck.db", "..%2Fnexdeck.db", "nexdeck.db", "does-not-exist.db"):
        answer = client.post(f"/api/v1/backups/{bad}/archive", json={"password": PASSWORD}, headers=CSRF)
        assert answer.status_code >= 400, bad
        assert "zip" not in answer.headers.get("content-type", ""), bad


def test_a_backup_can_be_deleted_with_everything_that_belongs_to_it(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    entry = _make(client)
    assert client.delete(f"/api/v1/backups/{entry['name']}", headers=CSRF).status_code == 204
    left = list((data_dir / "backups").iterdir())
    assert left == [], f"something stayed behind: {left}"


# ---------------------------------------------------------------------------
# Putting one back
# ---------------------------------------------------------------------------


def _upload(client: TestClient, blob: bytes, password: str = PASSWORD, confirm: str = "admin", path: str = "restore"):
    return client.post(
        f"/api/v1/backups/{path}",
        files={"file": ("backup.zip", blob, "application/zip")},
        data={"password": password, "confirm": confirm},
        headers=CSRF,
    )


def test_looking_inside_changes_nothing(client: TestClient) -> None:
    """⚠️ Separate from restoring, and that is the point. Whoever presses the
    button should have seen what they are about to put back."""
    setup_admin(client)
    entry = _make(client, "a note that has to come back")
    blob = _archive(client, entry["name"])
    create_user(client, "kim")

    seen = _upload(client, blob, path="inspect")
    assert seen.status_code == 200, seen.text
    assert seen.json()["note"] == "a note that has to come back"
    assert seen.json()["restorable"] is True
    assert client.get("/api/v1/users").json(), "and nothing was replaced"
    assert any(u["username"] == "kim" for u in client.get("/api/v1/users").json())


def test_a_restore_puts_the_old_state_back(client: TestClient) -> None:
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    create_user(client, "kim")
    assert any(u["username"] == "kim" for u in client.get("/api/v1/users").json())

    done = _upload(client, blob)
    assert done.status_code == 200, done.text

    after = TestClient(client.app)
    after.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse-battery"})
    assert not any(u["username"] == "kim" for u in after.get("/api/v1/users").json()), "kim came after the backup"


def test_a_restore_signs_everybody_out(client: TestClient) -> None:
    """⚠️ This does not happen by itself. Session cookies are signed with the
    secret key, and a backup of the same installation carries the same key, so
    everybody would stay signed in and look at a state from two days ago
    without noticing."""
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    assert _upload(client, blob).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_a_restore_backs_the_current_state_up_first(client: TestClient) -> None:
    """⚠️ If the archive turns out to be the broken one, that copy is the only
    way back."""
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    before = {one.name for one in backup.folder().glob("*.db")}

    assert _upload(client, blob).status_code == 200

    made = {one.name for one in backup.folder().glob("*.db")} - before
    assert made, "nothing was written before the restore"
    assert any("before-restore" in name for name in made), made


def test_a_restore_needs_the_administrators_own_name(client: TestClient) -> None:
    """⚠️ Not a checkbox. A checkbox is one careless click, and this is the
    one action that cannot be undone from inside nexdeck."""
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    create_user(client, "kim")

    for wrong in ("", "yes", "ADMIN", "kim"):
        refused = _upload(client, blob, confirm=wrong)
        assert refused.status_code == 400, wrong
        assert refused.json()["detail"]["code"] == "confirm_mismatch"
    assert any(u["username"] == "kim" for u in client.get("/api/v1/users").json()), "and nothing happened"


def test_the_wrong_password_restores_nothing(client: TestClient) -> None:
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    create_user(client, "kim")

    refused = _upload(client, blob, password="wrong-password")
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "wrong_password"
    assert any(u["username"] == "kim" for u in client.get("/api/v1/users").json())


def test_something_that_is_not_a_backup_is_refused(client: TestClient) -> None:
    setup_admin(client)
    for rubbish in (b"", b"not a zip at all", b"PK\x03\x04 but empty"):
        refused = _upload(client, rubbish)
        assert refused.status_code == 400, rubbish[:12]
        assert refused.json()["detail"]["code"] in ("not_a_backup", "empty_file", "wrong_password")


def test_only_administrators_may_restore(client: TestClient) -> None:
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    assert _upload(kim, blob, confirm="kim").status_code == 403


def test_the_pictures_come_back_too(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    avatars = data_dir / "avatars"
    avatars.mkdir(parents=True, exist_ok=True)
    (avatars / "someone.png").write_bytes(b"the original")
    entry = _make(client)
    blob = _archive(client, entry["name"])

    (avatars / "someone.png").write_bytes(b"changed since")
    assert _upload(client, blob).status_code == 200
    assert (avatars / "someone.png").read_bytes() == b"the original"


def test_the_key_comes_back_too(client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Without it every stored credential is unreadable afterwards, and the
    key is the last thing anybody suspects."""
    monkeypatch.delenv("NEXDECK_SECRET_KEY", raising=False)
    from app import config, crypto

    config.reset_settings_cache()
    crypto.forget_key()
    (data_dir / "secret.key").write_text("the-key-of-this-installation", encoding="utf-8")

    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])

    # Straight through the service, not the HTTP route: overwriting the key
    # invalidates the session cookie signed with it, so the request that asks
    # for the restore would be the first casualty of its own change.
    (data_dir / "secret.key").write_text("some-other-key", encoding="utf-8")
    backup.restore(blob, PASSWORD)
    assert (data_dir / "secret.key").read_text(encoding="utf-8").strip() == "the-key-of-this-installation"


def test_the_environment_variable_beats_the_key_in_the_archive(client: TestClient, data_dir: Path) -> None:
    """⚠️ Somebody who does not know this searches for a long time. The
    variable wins, so a restored archive whose key differs leaves every stored
    credential unreadable, and the warning in the log is the only clue."""
    setup_admin(client)
    (data_dir / "secret.key").write_text("a-key-from-a-file", encoding="utf-8")
    entry = _make(client)
    blob = _archive(client, entry["name"])
    (data_dir / "secret.key").unlink()

    # The fixture sets NEXDECK_SECRET_KEY, so this models the Docker case.
    backup.restore(blob, PASSWORD)
    assert not (data_dir / "secret.key").exists(), "no file was written where the variable rules"


def test_credentials_are_readable_again_after_a_restore(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The one that decides whether a restore was worth anything.

    crypto remembers the key it derived once per process. Without forgetting
    it, the service keeps using the key from before the restore and considers
    every credential it just put back unreadable, which looks exactly like a
    corrupt backup.
    """
    monkeypatch.delenv("NEXDECK_SECRET_KEY", raising=False)
    from app import config, crypto
    from app.services.integrations import resolve_config

    config.reset_settings_cache()
    crypto.forget_key()

    setup_admin(client)
    made = client.post(
        "/api/v1/integrations",
        json={"kind": "radarr", "name": "Radarr", "config": {"url": "http://radarr:7878", "api_key": "the-secret-key"}},
        headers=CSRF,
    )
    assert made.status_code == 201, made.text
    entry = _make(client)
    blob = _archive(client, entry["name"])

    backup.restore(blob, PASSWORD)

    from sqlalchemy import select

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        row = db.scalar(select(Integration).where(Integration.kind == "radarr"))
        assert row is not None, "the connection came back"
        assert resolve_config(row)["api_key"] == "the-secret-key", "and it can still be read"


# ---------------------------------------------------------------------------
# The guards inside the service, reached without going through a route
# ---------------------------------------------------------------------------


def test_a_name_that_climbs_out_of_the_folder_is_refused(client: TestClient) -> None:
    """⚠️ Straight at the service. Through HTTP the browser and the router
    normalise "../" away long before it gets here, so a test that only goes
    through a URL proves nothing about this check, and the live database sits
    exactly one directory up."""
    setup_admin(client)
    for bad in ("../nexdeck.db", "..\nexdeck.db", "sub/other.db", "", "."):
        with pytest.raises(backup.BackupError) as raised:
            backup.file(bad)
        assert raised.value.code == "no_such_backup", bad


def test_an_archive_is_never_built_without_a_password(client: TestClient) -> None:
    """⚠️ Also straight at the service. The route demands eight characters,
    so this guard is the one that holds if anything else ever calls in."""
    setup_admin(client)
    entry = _make(client)
    with pytest.raises(backup.BackupError) as raised:
        backup.archive(entry["name"], "")
    assert raised.value.code == "no_password"


def test_the_write_ahead_log_of_the_old_database_is_removed(client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The one that corrupts silently. A ``-wal`` left from the old
    database gets replayed into the new one, and those changes come from a
    completely different database."""
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])

    (data_dir / "nexdeck.db-wal").write_bytes(b"a write-ahead log from somewhere else")

    # Watched rather than looked for afterwards: the steps that finish a
    # restore open the database again and make a fresh log of their own, so
    # by the time the call returns there is always a file there. The question
    # is whether the old one was taken away before the new database landed.
    removed: list[str] = []
    original = backup._stubbornly_delete

    def watched(path, tries: int = 20) -> None:
        removed.append(path.name)
        original(path, tries)

    monkeypatch.setattr(backup, "_stubbornly_delete", watched)
    backup.restore(blob, PASSWORD)
    assert removed == ["nexdeck.db-wal", "nexdeck.db-shm"], removed


def test_a_restore_from_another_installation_can_still_be_read(client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The case that makes forgetting the derived key matter.

    Restoring a backup of the *same* installation keeps the same key, so
    nothing notices. A backup from another machine brings a different one, and
    a process that kept the old derived key considers every credential it just
    put back unreadable, which looks exactly like a corrupt archive.
    """
    monkeypatch.delenv("NEXDECK_SECRET_KEY", raising=False)
    from app import config, crypto
    from app.services.integrations import resolve_config

    config.reset_settings_cache()
    crypto.forget_key()
    (data_dir / "secret.key").write_text("the-key-of-the-other-machine", encoding="utf-8")

    setup_admin(client)
    made = client.post(
        "/api/v1/integrations",
        json={"kind": "radarr", "name": "Radarr", "config": {"url": "http://radarr:7878", "api_key": "a-credential"}},
        headers=CSRF,
    )
    assert made.status_code == 201, made.text
    entry = _make(client)
    blob = _archive(client, entry["name"])

    # A different machine: another key, and a process that has already used it.
    (data_dir / "secret.key").write_text("the-key-of-this-machine", encoding="utf-8")
    crypto.forget_key()
    assert crypto.encrypt("warm up the derived key")

    backup.restore(blob, PASSWORD)

    from sqlalchemy import select

    from app.db import db_session
    from app.models import Integration

    with db_session() as db:
        row = db.scalar(select(Integration).where(Integration.kind == "radarr"))
        assert row is not None
        assert resolve_config(row)["api_key"] == "a-credential"


def test_the_preview_says_where_the_key_would_come_from(client: TestClient) -> None:
    """⚠️ Two questions, not one. Whether the archive brings a key, and
    whether this installation would ignore it. Asking only the first made the
    preview look reassuring in the one case that ruins an installation."""
    setup_admin(client)
    entry = _make(client)
    blob = _archive(client, entry["name"])
    seen = _upload(client, blob, path="inspect").json()
    # The fixture sets NEXDECK_SECRET_KEY, and there is no key file, so this
    # is the Docker case: nothing in the archive, the variable rules here.
    assert seen["key_inside"] is False
    assert seen["key_from_env"] is True
