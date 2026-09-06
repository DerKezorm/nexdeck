"""The log follower: how often it writes, and when it stops.

One commit per line on the event loop is what a chatty container turns into
without batching, and a follower nobody watches used to run until the server
was restarted.
"""

from __future__ import annotations

import time

from sqlalchemy import select

from app.db import db_session
from app.models import LogLine
from app.services.logs import BATCH_LINES, UNWATCHED_SECONDS, LogTailer, recent_lines


def _count(source: str) -> int:
    with db_session() as db:
        return len(db.execute(select(LogLine.ts).where(LogLine.source == source)).all())


def test_lines_are_written_in_batches_not_one_by_one(client) -> None:
    """The browser sees each line at once; only the archive waits."""
    tailer = LogTailer()
    sent: list[str] = []
    tailer._emit = lambda board_id, widget_id, line, source, ts=None: sent.append(line)  # type: ignore[assignment]

    for number in range(BATCH_LINES - 1):
        tailer._store(None, 1, "1:app", f"line {number}")
    assert len(sent) == BATCH_LINES - 1, "every line went out to the browser straight away"
    assert _count("1:app") == 0, "and none of them has been written yet"

    tailer._store(None, 1, "1:app", "the one that fills the batch")
    assert _count("1:app") == BATCH_LINES


def test_a_reader_sees_what_is_still_in_the_batch(client) -> None:
    from app.services import logs as logs_module

    logs_module.log_tailer._emit = lambda *args, **kwargs: None  # type: ignore[assignment]
    logs_module.log_tailer._store(None, 1, "9:app", "not yet written")
    lines = recent_lines("9:app")
    assert [entry["line"] for entry in lines] == ["not yet written"]


def test_an_empty_line_is_not_stored(client) -> None:
    tailer = LogTailer()
    tailer._emit = lambda *args, **kwargs: None  # type: ignore[assignment]
    for text in ("", "   ", "\r\n"):
        tailer._store(None, 1, "2:app", text)
    tailer.flush()
    assert _count("2:app") == 0


def test_a_follower_nobody_watches_is_stopped(client) -> None:
    tailer = LogTailer()
    stopped: list[int] = []
    tailer.stop_widget = lambda widget_id: stopped.append(widget_id)  # type: ignore[assignment]
    tailer._tasks[5] = object()  # type: ignore[assignment]
    tailer._watched[5] = time.time() - UNWATCHED_SECONDS - 1
    tailer.drop_unwatched()
    assert stopped == [5]


def test_a_follower_somebody_is_watching_stays(client) -> None:
    tailer = LogTailer()
    stopped: list[int] = []
    tailer.stop_widget = lambda widget_id: stopped.append(widget_id)  # type: ignore[assignment]
    tailer._tasks[5] = object()  # type: ignore[assignment]
    tailer.seen(5)
    tailer.drop_unwatched()
    assert stopped == []
