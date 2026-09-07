"""SQLite engine and session factory.

One file, WAL mode, a generous busy timeout: the collector writes history
samples in the background while requests read boards, and SQLite must not
answer either of them with "database is locked".
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None

#: Set in normal operation, cleared while the database file is being replaced.
_open_for_business = threading.Event()
_open_for_business.set()
#: How long a caller waits for the swap before giving up on it.
SWAP_WAIT_SECONDS = 30.0


def _configure(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _pragmas(connection, _record) -> None:  # noqa: ANN001
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # ⚠️ Spelled out on purpose. Left to SQLAlchemy the pool is 5 plus 10,
        # and that number appeared nowhere. Synchronous routes hold a
        # connection for the length of the request, so this ceiling decides
        # when the sixteenth caller starts waiting, and after thirty seconds
        # gets a 500 with nothing in it that says why.
        _engine = create_engine(
            f"sqlite:///{settings.database_path}",
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        _configure(_engine)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def paused_for_swap() -> Iterator[None]:
    """Hold every new session back while the database file is replaced.

    ⚠️ Restoring a backup empties the pool, deletes the write-ahead log and
    writes a different file over the database. Nothing used to stop the rest of
    the house carrying on through all of that: the collector records a
    measurement, the reachability loop writes a result, another request opens a
    session, and each of them reattaches to a file that is being replaced under
    them. On Linux that goes through quietly and leaves a writer holding a file
    that no longer exists, which is the worse of the two outcomes.

    This is one half. A session that was already open when the latch closed is
    not held by it, so the caller stops the background services as well.
    """
    _open_for_business.clear()
    try:
        yield
    finally:
        _open_for_business.set()


def _wait_for_the_swap() -> None:
    if _open_for_business.is_set():
        return
    if not _open_for_business.wait(timeout=SWAP_WAIT_SECONDS):
        raise RuntimeError("The database is being replaced and did not come back in time.")


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    _wait_for_the_swap()
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Iterator[Session]:
    """For background services that live outside a request."""
    _wait_for_the_swap()
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reset_engine() -> None:
    """Tests point the settings at a fresh directory and call this."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
