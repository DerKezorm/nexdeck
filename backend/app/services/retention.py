"""Tables that had no end, and now have one.

⚠️ Five tables grew for as long as an installation ran. Only the history and
the container log lines were ever swept. On a dashboard that is up for a year
the action log holds every button anybody pressed, the notice centre every
message ever sent, and the outage table a row per service per failure, and
none of it is ever read again. SQLite does not shrink on its own either: the
file keeps the pages, and the backup archive carries them along.

``password_resets`` had a ``prune`` written for it that nothing ever called.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ActionLog, Asset, Notice, Outage, utcnow
from . import password_reset

logger = logging.getLogger("nexdeck.retention")


def prune_old_records(db: Session) -> dict[str, int]:
    """Sweep what nobody is going to look at again. Returns what went."""
    settings = get_settings()
    gone: dict[str, int] = {}

    if settings.keep_action_log_days > 0:
        cutoff = utcnow() - timedelta(days=settings.keep_action_log_days)
        gone["action_log"] = db.execute(delete(ActionLog).where(ActionLog.created_at < cutoff)).rowcount or 0

    if settings.keep_notices_days > 0:
        cutoff = utcnow() - timedelta(days=settings.keep_notices_days)
        gone["notices"] = db.execute(delete(Notice).where(Notice.created_at < cutoff)).rowcount or 0

    if settings.keep_outages_days > 0:
        cutoff = utcnow() - timedelta(days=settings.keep_outages_days)
        # ⚠️ Only outages that are over. One that is still running is the
        # reason a card is red right now, however long ago it started.
        gone["outages"] = db.execute(
            delete(Outage).where(Outage.ended_at.is_not(None), Outage.ended_at < cutoff)
        ).rowcount or 0

    if any(gone.values()):
        db.commit()

    strays = sweep_stray_uploads(db)
    if strays:
        gone["stray_uploads"] = strays

    # Its own rule, its own function, and until now no caller at all.
    reset_links = password_reset.prune(db)
    if reset_links:
        gone["password_resets"] = reset_links

    if any(gone.values()):
        logger.info("Swept old rows: %s.", ", ".join(f"{count} {name}" for name, count in gone.items() if count))
    return gone


def sweep_stray_uploads(db: Session) -> int:
    """Delete files in the uploads directory that no row knows about.

    ⚠️ Only those. A file whose ``Asset`` row exists stays, even when no board
    currently points at it: somebody uploaded it on purpose, the interface
    lists it, and a background that disappears by itself because a page was
    temporarily switched to another one would be worse than the disk space it
    costs. What is swept here is the other case, where the row is gone and the
    file was left behind, which is what a delete that failed halfway leaves.
    """
    directory = get_settings().uploads_dir
    if not directory.is_dir():
        return 0
    known = {str(row) for row in db.scalars(select(Asset.id))}
    gone = 0
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if path.stem not in known:
            try:
                path.unlink()
            except OSError as failure:
                logger.warning("Stray upload %s could not be removed: %s", path.name, failure)
                continue
            gone += 1
    if gone:
        logger.info("Removed %d upload(s) that no row pointed at.", gone)
    return gone


def counts(db: Session) -> dict[str, int]:
    """What the sweeper is looking after, for a test to weigh."""
    from sqlalchemy import func

    return {
        "action_log": int(db.scalar(select(func.count(ActionLog.id))) or 0),
        "notices": int(db.scalar(select(func.count(Notice.id))) or 0),
        "outages": int(db.scalar(select(func.count(Outage.id))) or 0),
    }
