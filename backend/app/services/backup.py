"""Backups: writing one, packing it, and putting one back.

A copy of the database next to the database is not a backup. Both sit on the
same volume; when that dies they die together. So a backup here has two
halves: a snapshot on disk, which is a restore point for a bad migration, and
``archive()``, which hands that snapshot to the operator as a file they can
carry off the machine. Only the second one is a backup.

⚠️ **The database alone is not enough.** Every service credential in it is
encrypted, and the key is not in the database. It sits beside it in
``secret.key``. Restore a database without that file and nexdeck quietly makes
a new key, after which not one connection can be read: no Radarr, no Plex, no
mail server, and no hint as to why.

⚠️ **Which is exactly why the archive carries a password.** With the key
inside, the file is everything somebody needs.

⚠️ **AES-ZIP and not a format of our own.** A format only nexdeck can open is
useless on the day nexdeck is what broke. A ZIP opens with 7-Zip, with WinRAR
and with the Explorer, so the data stays reachable without us.
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pyzipper

from .. import __version__
from ..config import get_settings
from ..db import paused_for_swap

logger = logging.getLogger("nexdeck.backup")

FOLDER = "backups"
AUTOMATIC = "automatic"
MANUAL = "manual"
PROFILE = "nexdeck-backup.json"
DATABASE = "nexdeck.db"
KEY_FILE = "secret.key"

#: How many automatic snapshots stay. Manual ones are never swept: somebody
#: who deliberately made a backup should not lose it to the next migration.
KEEP_AUTOMATIC = 5

#: Folders of loose files that belong to a backup.
#:
#: ⚠️ Avatars and uploads live as files beside the database; the database only
#: holds their names. Without them an installation comes back with everybody's
#: picture gone, and nobody connects that to the restore, because "the backup
#: was complete".
EXTRAS = ("avatars", "uploads")

#: Thrown out of the copy. Hours of work to refill, nothing to lose.
#:
#: ⚠️ This named ``widget_history``, a table that does not exist, so every
#: backup carried the whole chart history, the largest part of the database,
#: while its profile said nothing was emptied. The two tables hold a day at
#: most and fill again by themselves. Found on 07.09.2026.
CACHE_TABLES = ("history_samples", "history_minutes")

WITHOUT_KEY = """This archive has no secret.key.

The installation it came from keeps its key in the NEXDECK_SECRET_KEY
environment variable instead of in a file, so the key is in that machine's
Docker or systemd configuration and not here.

Restoring this database without that same value leaves every stored service
credential unreadable. Copy NEXDECK_SECRET_KEY across as well.
"""


class BackupError(Exception):
    """A readable failure, with a code the frontend can translate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Profile:
    """What a backup says about itself, written next to it and into the archive."""

    version: str
    schema: int
    created_at: str
    kind: str
    note: str = ""
    contains: list[str] = field(default_factory=list)
    emptied: list[str] = field(default_factory=list)

    def as_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @staticmethod
    def from_json(raw: str) -> Profile:
        data = json.loads(raw)
        return Profile(
            version=str(data.get("version") or "?"),
            schema=int(data.get("schema") or 0),
            created_at=str(data.get("created_at") or ""),
            kind=str(data.get("kind") or MANUAL),
            note=str(data.get("note") or ""),
            contains=list(data.get("contains") or []),
            emptied=list(data.get("emptied") or []),
        )


@dataclass
class Entry:
    """One backup on disk, as the list shows it."""

    name: str
    size: int
    created_at: str
    kind: str
    note: str
    version: str
    restorable: bool
    reason: str


def folder() -> Path:
    return get_settings().data_dir / FOLDER


def _profile_path(backup: Path) -> Path:
    return backup.with_suffix(".json")


def _extras_path(backup: Path) -> Path:
    return backup.with_name(backup.stem + "-files")


def _safe_note(note: str) -> str:
    """A note turned into something that can be part of a file name."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", note.strip().lower()).strip("-")
    return cleaned[:40]


def _schema_version(path: Path) -> int:
    """Which migration the copy has seen. 0 when the table is not there yet."""
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.DatabaseError:
        return 0
    finally:
        connection.close()


def latest_schema() -> int:
    """The migration number this build knows about."""
    from ..migrations import MIGRATIONS

    return max((number for number, _name, _step in MIGRATIONS), default=0)


def compatible(profile: Profile) -> tuple[bool, str]:
    """Could this archive go into the running build?

    ⚠️ Forwards only. A backup from a newer nexdeck carries tables and columns
    this build has never heard of, and there is no migration that runs
    backwards. An older one is fine: the ordinary startup path brings it up.
    """
    if profile.schema > latest_schema():
        return False, "too_new"
    return True, "ok"


def create(*, kind: str = MANUAL, note: str = "") -> Path:
    """Write a snapshot and lay its profile down beside it.

    ``VACUUM INTO`` makes a copy that holds together even while something is
    writing. Copying the file would lose whatever is still in the write-ahead
    log, which is the most recent thing anybody did.
    """
    from ..db import get_engine

    target_folder = folder()
    target_folder.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    extra = _safe_note(note)
    base = f"nexdeck-{kind}-{__version__}-{stamp}" + (f"-{extra}" if extra else "")

    target = target_folder / f"{base}.db"
    # VACUUM INTO refuses to write over a file that is already there.
    counter = 2
    while target.exists():
        target = target_folder / f"{base}-{counter}.db"
        counter += 1

    with get_engine().connect() as connection:
        # The path is ours, not something from outside. A single quote in it
        # would still take the statement apart, so they are doubled.
        connection.exec_driver_sql(f"VACUUM INTO '{str(target).replace(chr(39), chr(39) * 2)}'")

    emptied = _empty_caches(target)
    extras = _snapshot_extras(target)

    profile = Profile(
        version=__version__,
        schema=_schema_version(target),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        kind=kind,
        note=note.strip(),
        # ⚠️ What is really here, not what ought to be. ``secret.key`` stays in
        # the data directory and joins only when the archive is packed.
        contains=[DATABASE, *extras],
        emptied=emptied,
    )
    _profile_path(target).write_text(profile.as_json(), encoding="utf-8")

    logger.info("Backup written: %s (%s, %.1f MB).", target.name, kind, target.stat().st_size / 1048576)
    if kind == AUTOMATIC:
        sweep()
    return target


def _empty_caches(backup: Path) -> list[str]:
    """Throw the caches out of the fresh copy."""
    emptied: list[str] = []
    connection = sqlite3.connect(backup)
    try:
        for table in CACHE_TABLES:
            try:
                connection.execute(f"DELETE FROM {table}")  # noqa: S608 - a fixed list, not input
                emptied.append(table)
            except sqlite3.DatabaseError:
                continue
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    return emptied


def _snapshot_extras(backup: Path) -> list[str]:
    """Copy the loose files as they are now, next to the snapshot.

    ⚠️ Not read out of the live data directory when the archive is packed
    weeks later. A backup is a moment, and the pictures belong to that moment.
    """
    root = _extras_path(backup)
    taken: list[str] = []
    for name in EXTRAS:
        source = get_settings().data_dir / name
        if not source.is_dir():
            continue
        destination = root / name
        destination.mkdir(parents=True, exist_ok=True)
        for one in sorted(source.iterdir()):
            if one.is_file():
                shutil.copy2(one, destination / one.name)
                taken.append(f"{name}/{one.name}")
    return taken


def listing() -> list[Entry]:
    """Every snapshot on disk, newest first."""
    root = folder()
    if not root.is_dir():
        return []
    entries: list[Entry] = []
    # ⚠️ By time, not by name. In the file name the kind and the version come
    # before the stamp, so sorting the text backwards put every "manual" above
    # every "automatic" and 0.9.0 above 0.10.0, while the docstring above
    # promised newest first. The modification time is the one thing in this
    # that always means what it says.
    for path in sorted(root.glob("*.db"), key=lambda one: one.stat().st_mtime, reverse=True):
        profile = _read_profile(path)
        ok, reason = compatible(profile)
        entries.append(Entry(
            name=path.name, size=_size(path), created_at=profile.created_at, kind=profile.kind,
            note=profile.note, version=profile.version, restorable=ok, reason=reason,
        ))
    return entries


def _size(backup: Path) -> int:
    """The snapshot plus the files that belong to it."""
    total = backup.stat().st_size
    extras = _extras_path(backup)
    if extras.is_dir():
        total += sum(one.stat().st_size for one in extras.rglob("*") if one.is_file())
    return total


def _read_profile(backup: Path) -> Profile:
    """The profile beside the snapshot, or what can be worked out without one."""
    path = _profile_path(backup)
    if path.exists():
        try:
            return Profile.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            logger.warning("The profile of %s could not be read.", backup.name)
    stamped = datetime.fromtimestamp(backup.stat().st_mtime, UTC).isoformat(timespec="seconds")
    kind = AUTOMATIC if "-automatic-" in backup.name else MANUAL
    return Profile(version="?", schema=_schema_version(backup), created_at=stamped, kind=kind)


def file(name: str) -> Path:
    """One snapshot by name.

    ⚠️ The name comes from a URL. Anything with a path separator in it, or a
    name that is not in the folder, is refused rather than resolved.
    """
    if not name or "/" in name or "\\" in name or name != Path(name).name:
        raise BackupError("no_such_backup", "There is no such backup.")
    path = folder() / name
    if not path.is_file() or path.suffix != ".db":
        raise BackupError("no_such_backup", "There is no such backup.")
    return path


def remove(name: str) -> None:
    path = file(name)
    _profile_path(path).unlink(missing_ok=True)
    shutil.rmtree(_extras_path(path), ignore_errors=True)
    path.unlink()
    logger.info("Backup deleted: %s.", name)


def write_one_if_due() -> Path | None:
    """A snapshot by itself, if the last one is old enough.

    Called from the housekeeping tick, so the interval is kept to within five
    minutes, which is close enough for something measured in hours.
    """
    hours = get_settings().backup_every_hours
    if hours <= 0:
        return None
    newest = max(
        (path.stat().st_mtime for path in folder().glob("*.db")
         if _read_profile(path).kind == AUTOMATIC),
        default=0.0,
    )
    if newest and time.time() - newest < hours * 3600:
        return None
    written = create(kind=AUTOMATIC, note="scheduled")
    logger.info("Wrote the scheduled snapshot %s.", written.name)
    return written


def sweep(keep: int = KEEP_AUTOMATIC) -> int:
    """Drop the oldest automatic snapshots. Manual ones are never swept."""
    automatic = [entry for entry in listing() if entry.kind == AUTOMATIC]
    dropped = 0
    for entry in automatic[keep:]:
        try:
            remove(entry.name)
            dropped += 1
        except (BackupError, OSError) as failure:
            logger.warning("Could not sweep %s: %s", entry.name, failure)
    return dropped


# ---------------------------------------------------------------------------
# The archive: the only half that is actually a backup
# ---------------------------------------------------------------------------


def archive(name: str, password: str) -> bytes:
    """One snapshot as an encrypted ZIP: database, key, loose files, profile."""
    if not password:
        raise BackupError("no_password", "An archive is not built without a password.")

    source = file(name)
    profile = _read_profile(source)

    buffer = io.BytesIO()
    with pyzipper.AESZipFile(buffer, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as archive_file:
        archive_file.setpassword(password.encode("utf-8"))
        archive_file.write(source, DATABASE)
        inside = [DATABASE]

        for path, entry in _extras_to_pack(source):
            archive_file.write(path, entry)
            inside.append(entry)

        key_file = get_settings().data_dir / KEY_FILE
        if key_file.exists():
            archive_file.write(key_file, KEY_FILE)
            inside.append(KEY_FILE)
        else:
            archive_file.writestr("NO-KEY-IN-HERE.txt", WITHOUT_KEY)
            inside.append("NO-KEY-IN-HERE.txt")

        # ⚠️ Last, and with the real list. Written earlier it would be a guess:
        # it would name ``secret.key`` even where only the note about it went
        # in. Nothing in nexdeck reads this field, so the only reader it could
        # mislead is the person the open ZIP was chosen for, opening it on a
        # day when nexdeck is not running.
        profile.contains = inside
        archive_file.writestr(PROFILE, profile.as_json())

    logger.info("Archive built from %s (%.1f MB).", name, len(buffer.getvalue()) / 1048576)
    return buffer.getvalue()


def _extras_to_pack(backup: Path) -> list[tuple[Path, str]]:
    """Which loose files go in, and from where.

    Normally from the snapshot's own folder, so in the state of that moment.
    Where there is none, the snapshot predates this and only today's files are
    left. Not the same instant, but an installation that comes back without
    pictures is worse than one with slightly newer ones.
    """
    own = _extras_path(backup)
    has_own = own.is_dir()
    if not has_own:
        logger.info("Backup %s has no file snapshot of its own; packing today's files.", backup.name)
    root = own if has_own else get_settings().data_dir

    found: list[tuple[Path, str]] = []
    for name in EXTRAS:
        under = root / name
        if not under.is_dir():
            continue
        for one in sorted(under.iterdir()):
            if one.is_file():
                found.append((one, f"{name}/{one.name}"))
    return found


# ---------------------------------------------------------------------------
# Putting one back
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    """What can be said about an archive, before and after restoring it."""

    profile: Profile
    restorable: bool
    reason: str
    #: Is there a ``secret.key`` in the archive?
    #:
    #: ⚠️ Not the same question as whether the target has one, and mixing the
    #: two made the preview reassuring in exactly the worst case. An archive
    #: from an installation that keeps its key in NEXDECK_SECRET_KEY carries
    #: no file; restore it somewhere without that variable and nexdeck makes a
    #: new key. After that nothing stored can be read, and the key is the last
    #: thing anybody suspects.
    key_inside: bool


def _open(data: bytes, password: str) -> tuple[Profile, bytes, str | None, dict[str, bytes]]:
    """Unpack an archive in memory. Nothing is written here."""
    if not data:
        raise BackupError("empty_file", "That file is empty.")
    try:
        with pyzipper.AESZipFile(io.BytesIO(data)) as archive_file:
            archive_file.setpassword(password.encode("utf-8"))
            names = set(archive_file.namelist())
            if DATABASE not in names:
                raise BackupError("not_a_backup", "This file is not a nexdeck backup.")
            try:
                raw_db = archive_file.read(DATABASE)
            except RuntimeError as failure:
                # pyzipper says "Bad password" through RuntimeError.
                raise BackupError("wrong_password", "The password does not open this archive.") from failure
            profile = (
                Profile.from_json(archive_file.read(PROFILE).decode("utf-8"))
                if PROFILE in names
                else Profile(version="?", schema=0, created_at="", kind=MANUAL)
            )
            key = archive_file.read(KEY_FILE).decode("utf-8").strip() if KEY_FILE in names else None
            extras = {
                name: archive_file.read(name)
                for name in sorted(names)
                if name.split("/", 1)[0] in EXTRAS and not name.endswith("/")
            }
            for name in extras:
                # ⚠️ A nexdeck archive holds these folders flat. ``avatars/..``
                # starts with ``avatars`` all the same, and the check before
                # writing let it through after the database had already been
                # swapped, so the restore stopped halfway. Refused here, before
                # anything is touched. Found on 12.09.2026.
                filename = name.partition("/")[2]
                if filename in (".", "..") or any(mark in filename for mark in ("/", "\\", "\x00")):
                    raise BackupError("not_a_backup", "This file is not a nexdeck backup.")
    except BackupError:
        raise
    except (RuntimeError, ValueError, json.JSONDecodeError) as failure:
        raise BackupError("wrong_password", "The password does not open this archive.") from failure
    except Exception as failure:  # noqa: BLE001 - a broken ZIP arrives as anything
        raise BackupError("not_a_backup", "This file is not a nexdeck backup.") from failure

    if not raw_db.startswith(b"SQLite format 3\x00"):
        raise BackupError("not_a_backup", "This file is not a nexdeck backup.")
    if not profile.schema:
        # Older archives had no profile; ask the database itself.
        profile.schema = _schema_from_bytes(raw_db)
    return profile, raw_db, key, extras


def _schema_from_bytes(raw: bytes) -> int:
    """The migration number of a database that is still only bytes.

    ⚠️ Without touching the disk. This used to write the whole foreign database
    into the system temp directory to ask it one question. ``tempfile`` creates
    with mode 0600, so it was never readable by anyone else, but the copy still
    landed on whatever volume TMPDIR points at, outside the data directory the
    operator chose and outside anything they back up or wipe. ``deserialize``
    keeps it in this process and nowhere else.
    """
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(raw)
        row = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0] or 0) if row else 0
    except (sqlite3.DatabaseError, AttributeError):
        # AttributeError: an interpreter without deserialize. Not one we ship,
        # and a schema of 0 only means "ask the profile instead".
        return 0
    finally:
        connection.close()


def inspect(data: bytes, password: str) -> Verdict:
    """Only look: what is this, and may it be put back?

    ⚠️ Separate from restoring, and that is the point. Restoring replaces
    everything. Whoever presses the button should have seen what they are
    about to put back, rather than finding out afterwards.
    """
    profile, _raw, key, _extras = _open(data, password)
    ok, reason = compatible(profile)
    return Verdict(profile, ok, reason, key is not None)


def _stubbornly_delete(path: Path, tries: int = 20) -> None:
    """Remove a file SQLite may still be holding.

    ⚠️ It can fail. If anything still has a connection open, Windows refuses,
    and on Linux the call would go through silently while a writer keeps
    writing to a file that no longer exists. So this does not look away.
    """
    for attempt in range(tries):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(0.1)


def _hold_everything() -> None:
    """Bring the background services to a stop before the file is replaced.

    Each of them writes on its own schedule, and none of them would notice the
    database changing underneath. Without a running loop there is nothing to
    stop, which is the ordinary case in a plain unit test.
    """
    from .collector import collector
    from .hass_ws import hass_listener
    from .health import health
    from .logs import log_tailer
    from .loop import run_and_wait

    async def stop_them() -> None:
        await hass_listener.stop()
        await health.stop()
        await log_tailer.stop()
        await collector.stop()

    if run_and_wait(stop_them, timeout=20.0):
        logger.info("Background services stopped for the restore.")


def _let_everything_go() -> None:
    """And start them again, whatever happened in between."""
    from .collector import collector
    from .hass_ws import hass_listener
    from .health import health
    from .loop import run_and_wait

    async def start_them() -> None:
        await collector.start()
        await health.start()
        await hass_listener.start()

    if run_and_wait(start_them, timeout=20.0):
        logger.info("Background services running again.")


def restore(data: bytes, password: str, *, without_safety_copy: bool = False) -> Verdict:
    """Put a database and its key back.

    ⚠️ **The current state is backed up first.** Even when there is nothing
    worth keeping: if the archive turns out to be the broken one, that copy is
    the only way back. It costs seconds and megabytes.

    ⚠️ **Everyone is signed out afterwards.** This does not happen by itself.
    Session cookies are signed with the secret key, so they only fall over if
    the key changes, and restoring a backup of the same installation leaves
    the same key. Without the line below, everybody stays signed in and looks
    at a data state from two days ago without noticing.
    """
    profile, raw_db, key, extras = _open(data, password)

    ok, reason = compatible(profile)
    if not ok:
        # ⚠️ The code is written out at the raise. A lookup table or a
        # computed "restore_" + reason would hide it from the guard that
        # checks every code has a translation, and the guard would stay green
        # while the message came out in the wrong language.
        raise BackupError("too_new", "This backup comes from a newer nexdeck than this one.")

    from ..config import get_settings as read_settings
    from ..crypto import forget_key
    from ..db import get_engine, reset_engine
    from ..migrations import migrate

    settings = read_settings()
    target = settings.database_path

    try:
        create(kind=AUTOMATIC, note="before restore")
    except Exception as failure:  # noqa: BLE001
        # ⚠️ This used to be a warning and the restore went on regardless,
        # while the docstring of this very function calls the copy the only way
        # back if the archive turns out to be the broken one. A promise that
        # holds except when it matters is not one. It is still possible to go
        # ahead, because the reason for restoring may well be that the current
        # database is past saving, but somebody has to say so.
        logger.error("Could not back up before restoring: %s", failure)
        if not without_safety_copy:
            raise BackupError(
                "no_safety_copy",
                f"The safety copy of the current state failed ({failure}). Nothing was replaced. "
                "Make room, or repeat with 'restore anyway' if the current database is the problem.",
            ) from failure

    # ⚠️ Everything else has to let go of the file first. Stopping the services
    # and closing the latch are two different things and both are needed: the
    # latch holds back sessions that have not started, stopping holds back the
    # ones that are in the middle of something.
    _hold_everything()
    try:
        with paused_for_swap():
            # Close everything, or SQLite keeps the files.
            get_engine().dispose()

            # ⚠️ The companion files have to go too, and this is where it
            # hangs. Leave a ``-wal`` of the old database behind and SQLite
            # replays its changes into the new one, where they come from a
            # completely different database.
            for suffix in ("-wal", "-shm"):
                _stubbornly_delete(target.with_name(target.name + suffix))

            target.write_bytes(raw_db)
    finally:
        _let_everything_go()

    if key:
        if settings.secret_key:
            # The environment variable always wins; a file beside it changes
            # nothing. Somebody who does not know that searches for a while.
            logger.warning(
                "The restored backup carries a secret.key, but NEXDECK_SECRET_KEY is set and wins. "
                "Stored credentials stay unreadable unless the variable holds the same value."
            )
        else:
            (settings.data_dir / KEY_FILE).write_text(key, encoding="utf-8")

    for name, content in extras.items():
        # ``under`` comes from EXTRAS, not from the archive, so a name in the
        # ZIP cannot lead out of the data directory.
        under, _, filename = name.partition("/")
        if under not in EXTRAS or not filename or "/" in filename or "\\" in filename:
            continue
        destination = settings.data_dir / under
        destination.mkdir(parents=True, exist_ok=True)
        (destination / filename).write_bytes(content)
    if extras:
        logger.info("Put %d accompanying file(s) back.", len(extras))

    # ⚠️ The derived encryption key as well. A foreign ``secret.key`` may have
    # just been written; crypto remembers what it derived once per process, so
    # without this the service would keep using the key from before the
    # restore and consider every restored secret unreadable.
    forget_key()
    reset_engine()

    # An older backup is missing columns and tables; the ordinary startup path
    # brings them in.
    migrate()
    _sign_everybody_out()

    logger.info("Backup restored: version %s from %s.", profile.version, profile.created_at or "?")
    return Verdict(profile, True, "ok", key is not None)


def _sign_everybody_out() -> None:
    """After a restore nobody is signed in any more."""
    from sqlalchemy import update

    from ..db import db_session
    from ..models import Session, User
    from ..security import now_ms

    try:
        with db_session() as db:
            db.execute(update(Session).values(revoked=True))
            db.execute(update(User).values(password_changed_ms=now_ms()))
            db.commit()
    except Exception:  # noqa: BLE001 - the restore itself is done
        logger.exception("Could not end the existing sessions after the restore.")
