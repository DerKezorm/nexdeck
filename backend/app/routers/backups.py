"""Backups: list, make, download, put back. Administrators only.

⚠️ **Restoring is a one-way door and is treated like one.** The upload is
looked at first and described back to the operator, and only a second call
with the name of this installation typed out actually replaces anything.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Form, Response, UploadFile, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import AdminUser, DbSession, error
from ..services import backup

router = APIRouter(prefix="/api/v1/backups", tags=["admin"])

logger = logging.getLogger("nexdeck.backups")

#: Bigger than any plausible dashboard, small enough that a wrong file does
#: not eat the machine's memory before it is refused.
MAX_UPLOAD = 512 * 1024 * 1024


class MakeBody(BaseModel):
    note: str = Field(default="", max_length=200)


class ArchiveBody(BaseModel):
    #: ⚠️ No minimum out of politeness: ``secret.key`` is in that file, so it
    #: hands over every service credential of the installation.
    password: str = Field(min_length=8, max_length=200)


class RestoreConfirmation(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirm: str = Field(default="", max_length=120)


def _entry(entry: backup.Entry) -> dict:
    return {
        "name": entry.name, "size": entry.size, "created_at": entry.created_at, "kind": entry.kind,
        "note": entry.note, "version": entry.version, "restorable": entry.restorable, "reason": entry.reason,
    }


@router.get("", summary="List the backups on this machine")
def list_backups(admin: AdminUser) -> dict:
    return {
        "entries": [_entry(entry) for entry in backup.listing()],
        "folder": str(backup.folder()),
        "keep_automatic": backup.KEEP_AUTOMATIC,
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Write a backup now")
async def make_backup(body: MakeBody, admin: AdminUser) -> dict:
    """⚠️ In a worker thread. ``VACUUM INTO`` on a grown database blocks for
    seconds, and the event loop serves every other card while it does."""
    try:
        path = await asyncio.to_thread(backup.create, kind=backup.MANUAL, note=body.note)
    except backup.BackupError as failure:
        raise error(failure.code, failure.message) from failure
    logger.info("%s wrote a backup: %s.", admin.username, path.name)
    return _entry(next(entry for entry in backup.listing() if entry.name == path.name))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a backup")
def delete_backup(name: str, admin: AdminUser) -> None:
    try:
        backup.remove(name)
    except backup.BackupError as failure:
        raise error(failure.code, failure.message, status.HTTP_404_NOT_FOUND) from failure
    logger.info("%s deleted the backup %s.", admin.username, name)


@router.post("/{name}/archive", summary="Download a backup as an encrypted archive")
async def download_archive(name: str, body: ArchiveBody, admin: AdminUser) -> Response:
    """⚠️ A POST, not a GET, because the password is in the body. In a query
    string it would sit in every reverse proxy log on the way."""
    try:
        blob = await asyncio.to_thread(backup.archive, name, body.password)
    except backup.BackupError as failure:
        raise error(failure.code, failure.message, status.HTTP_404_NOT_FOUND) from failure
    logger.info("%s downloaded the backup %s.", admin.username, name)
    return Response(
        content=blob, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name.removesuffix(".db")}.zip"'},
    )


def _verdict(verdict: backup.Verdict) -> dict:
    return {
        "version": verdict.profile.version,
        "created_at": verdict.profile.created_at,
        "kind": verdict.profile.kind,
        "note": verdict.profile.note,
        "contains": verdict.profile.contains,
        "restorable": verdict.restorable,
        "reason": verdict.reason,
        "key_inside": verdict.key_inside,
        # ⚠️ Two questions, not one. Whether the archive brings a key, and
        # whether this installation would ignore it because NEXDECK_SECRET_KEY
        # is set. The worst combination is "no key in the archive, no variable
        # here": nexdeck then makes a new one and nothing stored can be read.
        # Asking only the first made the preview look reassuring exactly then.
        "key_from_env": bool(get_settings().secret_key),
    }


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise error("too_large", "That file is larger than half a gigabyte.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    return data


@router.post("/inspect", summary="Look inside an uploaded archive without changing anything")
async def inspect_archive(admin: AdminUser, file: UploadFile, password: Annotated[str, Form()]) -> dict:
    """⚠️ Nothing is written here. This is the screen somebody reads before
    they decide, and a restore that starts by surprising them has already
    gone wrong."""
    data = await _read(file)
    try:
        verdict = await asyncio.to_thread(backup.inspect, data, password)
    except backup.BackupError as failure:
        raise error(failure.code, failure.message) from failure
    return _verdict(verdict)


@router.post("/restore", summary="Put an uploaded archive back")
async def restore_archive(
    admin: AdminUser,
    db: DbSession,
    file: UploadFile,
    password: Annotated[str, Form()],
    confirm: Annotated[str, Form()] = "",
    without_safety_copy: Annotated[bool, Form()] = False,
) -> dict:
    """Replaces the database, the key and the loose files.

    ⚠️ The administrator types their own user name to get here. Not a
    checkbox: a checkbox is one careless click, and this is the one action in
    nexdeck that cannot be undone from inside nexdeck.

    ⚠️ ``without_safety_copy`` goes ahead even when the copy of the current
    state cannot be written. It exists because the reason for restoring may be
    that the current database is past saving, and then the copy is the thing
    that fails. Off unless somebody says otherwise.

    ⚠️ Everybody, including whoever pressed the button, is signed out
    afterwards. The accounts in the backup are not the accounts of a moment
    ago, and staying signed in would mean looking at somebody else's session.
    """
    if confirm.strip() != admin.username:
        raise error(
            "confirm_mismatch",
            "Type your own user name to confirm the restore.",
            status.HTTP_400_BAD_REQUEST,
        )
    data = await _read(file)
    # Written before, not after: if the process dies mid-restore, this line is
    # the only thing that says what was attempted.
    logger.warning("%s is restoring a backup. Everything on this installation is about to be replaced.", admin.username)
    # ⚠️ This request's own session has to let go first. It stays open until
    # the response is written, and while it does SQLite holds the write-ahead
    # log, which the restore has to delete. Windows refuses and the restore
    # dies half done; on Linux the delete would go through silently and leave
    # a writer attached to a file that no longer exists, which is worse.
    db.close()
    try:
        verdict = await asyncio.to_thread(backup.restore, data, password, without_safety_copy=without_safety_copy)
    except backup.BackupError as failure:
        logger.warning("The restore by %s did not happen: %s", admin.username, failure.message)
        raise error(failure.code, failure.message) from failure
    logger.warning("Restore finished. Every session on this installation has ended.")
    return _verdict(verdict)
