"""When a backup is too old: one rule for Backrest, Kopia and Duplicati.

A backup tool says when a run failed. It does not say when no run happened:
a schedule that was switched off, a container that stopped, a disk that was
not mounted. The plan then shows its last good backup from a week ago, in
green. Here a plan, source or job whose last good backup is older than the
connection allows turns yellow, says so, and is told once.

The limit belongs to the connection, 26 hours by default: a nightly backup
with a little room for one that runs late. A weekly one wants about 8 days.

UrBackup is left out: its server knows the intervals it was given and says
"overdue" itself. Proxmox Backup Server is left out because its card has no
last good backup per guest to hold against a limit.
"""

from __future__ import annotations

import time
from typing import Any

from .base import Detected, Field, WidgetData

#: Added to the fields of each connection that knows its last good backups.
STALE_FIELD = Field(
    "stale_hours", "Too old after (hours)", type="number", default=26,
    help="A plan, source or job whose last good backup is older than this turns the card yellow. 26 suits a nightly backup, about 200 a weekly one; 0 switches it off.",
)
WORD = "Too old"


def limit_of(config: dict[str, Any]) -> float:
    """The limit in seconds; 0 is off."""
    try:
        hours = float(config.get("stale_hours", 26))
    except (TypeError, ValueError):
        hours = 26.0
    return max(0.0, hours) * 3600


def too_old(good: float | None, limit: float, now: float | None = None) -> bool:
    """A last good backup older than the limit. None (never ran) is another matter, not this one."""
    return bool(limit) and bool(good) and (now if now is not None else time.time()) - float(good) > limit


def age(rows: list[dict[str, Any]], limit: float, now: float | None = None) -> list[dict[str, Any]]:
    """Kopia's and Duplicati's rows (``{"state", "good", "row"}``): the green ones that are too old turn yellow."""
    for one in rows:
        if one["state"] == "ok" and too_old(one["good"], limit, now):
            one["state"] = "warn"
            one["row"]["status"] = "warn"
            one["row"]["subtitle"] = WORD
            one["row"]["stale"] = True
    return rows


def news(before: WidgetData | None, after: WidgetData) -> list[Detected]:
    """Rows that became too old between two fetches; never on the first, never twice a day."""
    if before is None or before.error or after.error:
        return []
    was = {str(row.get("title")) for row in before.items if row.get("stale")}
    return [
        Detected(event="backup_stale", title=f"{row.get('title')}: the last good backup is too old",
                 body=str(row.get("value") or ""), level="warn", key=f"backup_stale:{row.get('title')}", quiet_seconds=86400)
        for row in after.items if row.get("stale") and str(row.get("title")) not in was
    ][:5]
