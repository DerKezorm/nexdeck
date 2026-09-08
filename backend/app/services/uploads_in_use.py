"""Where an uploaded file is used.

⚠️ Written because there was no way to take a file off the server again. The
upload quota's own message says "delete a file you no longer need", and the
only delete button in the whole interface was the one for icons. Files piled
up, and the sweeper leaves them alone on purpose: a row that exists was
uploaded deliberately, and a background that vanished because a page was
switched away for an afternoon would be worse than the disk it costs.

Deleting one is only safe if you can see where it is still drawn, so that is
what this works out. It is one pass over the widgets and one over the boards,
not a query per file: with fifty uploads the other way is fifty scans.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, Board, Widget

#: An asset address as it appears anywhere: ``/api/v1/assets/12/rack.png``.
ADDRESS = re.compile(r"/api/v1/assets/(\d+)/")


def _mentioned(blob: Any) -> set[int]:
    """Every asset id an arbitrary options blob refers to.

    ⚠️ Over the whole value as text, not over the fields we happen to know.
    The addresses live in a widget's icon, in a picture card's list, in a
    bookmark's line and in whatever the next card invents; a list of known
    field names would be right on the day it was written and wrong after that.
    """
    if blob is None:
        return set()
    text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
    return {int(found) for found in ADDRESS.findall(text)}


def usage(db: Session) -> dict[int, list[dict[str, str]]]:
    """For every asset, the places that draw it."""
    found: dict[int, list[dict[str, str]]] = {}

    def note(asset_id: int, what: str, name: str) -> None:
        found.setdefault(asset_id, []).append({"what": what, "name": name})

    for widget in db.scalars(select(Widget)):
        for asset_id in _mentioned(widget.options) | _mentioned(widget.icon):
            note(asset_id, "widget", widget.title or widget.kind)
    for board in db.scalars(select(Board)):
        for asset_id in _mentioned(board.background):
            note(asset_id, "board", board.name)
    return found


def used_by(db: Session, asset_id: int) -> list[dict[str, str]]:
    """The places that draw one asset."""
    return usage(db).get(asset_id, [])


def same_file(db: Session, digest: str, user_id: int) -> Asset | None:
    """An upload this account already made, byte for byte.

    ⚠️ Uploading the same picture twice made two files. Nobody notices, and
    both count against the quota. Per account, not across the installation:
    the quota is per account, and handing somebody a file another person
    uploaded would leak that it exists.
    """
    return db.scalar(select(Asset).where(Asset.digest == digest, Asset.uploaded_by == user_id))
