"""Boards from files: ``data/boards/*.yaml`` override the database.

A provisioned board is shown like any other but cannot be edited in the
browser; the file is its source. Files are re-read when they change, and a
board whose file disappears is removed.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from ..config import get_settings
from ..db import db_session
from ..models import Board, Page, Widget
from .boards import ImportError_, import_board

logger = logging.getLogger("nexdeck.provisioning")

_seen: dict[str, float] = {}
POLL_SECONDS = 10


def _files() -> list[Path]:
    directory = get_settings().boards_dir
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in (".yaml", ".yml") and p.is_file())


def load_all() -> None:
    """Import every file once at start, replacing boards from earlier runs."""
    for path in _files():
        _load(path)
    _remove_orphans()


def _load(path: Path) -> None:
    from .collector import collector

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        logger.warning("Cannot read %s: %s", path.name, error)
        return
    with db_session() as db:
        existing = db.scalar(select(Board).where(Board.source_file == path.name, Board.provisioned.is_(True)))
        try:
            board = import_board(db, text, owner_id=None, provisioned=True, source_file=path.name, replace=existing)
        except ImportError_ as error:
            logger.warning("Board file %s was not loaded: %s", path.name, error)
            return
        board.provisioned = True
        board.source_file = path.name
        db.flush()
        widget_ids = list(db.scalars(select(Widget.id).join(Page).where(Page.board_id == board.id)))
    _seen[path.name] = path.stat().st_mtime
    for widget_id in widget_ids:
        collector.schedule(widget_id)
    logger.info("Board file %s loaded as %r.", path.name, board.slug)


def _remove_orphans() -> None:
    from .collector import collector

    names = {p.name for p in _files()}
    with db_session() as db:
        for board in list(db.scalars(select(Board).where(Board.provisioned.is_(True)))):
            if board.source_file not in names:
                widget_ids = list(db.scalars(select(Widget.id).join(Page).where(Page.board_id == board.id)))
                db.delete(board)
                for widget_id in widget_ids:
                    collector.unschedule(widget_id)
                _seen.pop(board.source_file, None)
                logger.info("Board file %s is gone; board %r removed.", board.source_file, board.slug)


async def watch() -> None:
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            for path in _files():
                mtime = path.stat().st_mtime
                if _seen.get(path.name) != mtime:
                    _load(path)
            _remove_orphans()
        except Exception:  # noqa: BLE001
            logger.exception("Provisioning watch failed.")
