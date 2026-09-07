"""nexdeck's own log: a file an administrator can read, filter and download.

Until now everything went to standard output and nowhere else. That is fine
on a laptop and useless on a NAS: the one question a self-hosted dashboard
gets asked is "why did this card stop working at four in the morning", and the
answer was in a container log nobody had kept.

Four levels, and the deep ones switch themselves off again. Somebody turns
tracing on to catch a problem, the problem happens, and the setting stays on
for three months writing gigabytes. The level carries an end from the moment
it is set.

⚠️ Named ``journal`` because ``services/logs.py`` was already taken by the
container log tailer, which follows *other people's* logs. These two have
nothing to do with each other and the names must not suggest they do.

Three traps, all of them learned in Nexview and all of them still true here:

* **uvicorn keeps its own logger on** ``propagate = False``. Without adding the
  handler to ``uvicorn.error`` by hand, no start-up failure and no crash from
  the server itself reaches the file. Exactly the lines somebody asks for are
  the ones that would be missing.
* **A reload adds a second handler** unless the old one is taken away first,
  and then every line appears twice.
* **The format has to survive its own change.** After an update the same file
  holds lines written by the version before it, so the parser reads the newer
  part as optional instead of refusing the line.
"""

from __future__ import annotations

import contextvars
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DbSessionType

from ..config import get_settings
from ..models import Setting

#: What each level means for our own messages, for everything else, and for
#: the libraries, which are chatty enough to bury the interesting lines.
MODES: dict[str, dict[str, int]] = {
    "quiet": {"app": logging.WARNING, "root": logging.WARNING, "libs": logging.WARNING},
    "normal": {"app": logging.INFO, "root": logging.INFO, "libs": logging.WARNING},
    "detailed": {"app": logging.DEBUG, "root": logging.INFO, "libs": logging.INFO},
    "trace": {"app": logging.DEBUG, "root": logging.DEBUG, "libs": logging.DEBUG},
}
#: The levels that switch themselves off again.
DEEP_MODES = ("detailed", "trace")
DEFAULT_MODE = "normal"
#: How long a deep level may stay on. ``0`` means until the next restart.
ALLOWED_MINUTES = (30, 120, 480, 0)

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
KEY = "log_mode"

#: Libraries that would otherwise fill the file with one line per request.
NOISY = ("httpx", "httpcore", "uvicorn.access", "watchfiles", "PIL", "urllib3", "asyncio")

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
#: A deep level writes far more, so it gets a bigger file before it rotates.
MAX_BYTES_NORMAL = 4 * 1024 * 1024
MAX_BYTES_DEEP = 16 * 1024 * 1024
BACKUP_COUNT = 3
#: Nobody downloads more than this, and no mail carries it.
DOWNLOAD_LIMIT = 20 * 1024 * 1024

#: ⚠️ The bracket is optional on purpose. After an update the same file still
#: holds lines from the version before it, and those stay readable.
LINE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<logger>\S+)\s*"
    r"(?:\[(?P<request>[^\]]*)\]\s*)?"
    r"(?P<message>.*)$"
)

logger = logging.getLogger("nexdeck.journal")

#: The number of the request being served, so the lines of one call belong
#: together in a file that a dozen background tasks write to at the same time.
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
#: Who is doing it, when that is known.
_actor: contextvars.ContextVar[str] = contextvars.ContextVar("actor", default="")

_handler: RotatingFileHandler | None = None
_mode = DEFAULT_MODE
_until: datetime | None = None


# ---------------------------------------------------------------------------
# The request a line belongs to
# ---------------------------------------------------------------------------


def bind_request(number: str) -> contextvars.Token[str]:
    return _request_id.set(number)


def unbind_request(token: contextvars.Token[str]) -> None:
    _request_id.reset(token)


def set_actor(name: str) -> None:
    _actor.set(name or "")


def current_request_id() -> str:
    return _request_id.get()


#: Query parameters that carry a credential. Matched without case, and the
#: value is replaced before the line is ever written.
SECRET_PARAMS = ("apikey", "api_key", "apitoken", "token", "access_token", "key", "passwd", "password", "auth", "secret", "sig", "signature")
_SECRET_IN_QUERY = re.compile(
    r"([?&](?:" + "|".join(SECRET_PARAMS) + r")=)([^&\s\"']+)",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Take the credentials out of a line before it is written anywhere.

    ⚠️ httpx logs the full address of every request at INFO, and the deep log
    levels turn httpx up to exactly that. Several services take their key in
    the query string, so it is not the adapter doing anything wrong: Kavita
    wants ``apiKey``, Technitium wants ``token``, Synology's ``auth.cgi``
    takes the DSM password that way. The line then sits in
    ``data/logs/nexdeck.log`` and in ``docker logs``, and the deep level exists
    precisely so somebody can download that file and attach it to an issue.
    """
    return _SECRET_IN_QUERY.sub(lambda hit: hit.group(1) + "***", text)


class _Context(logging.Filter):
    """Puts the request number on every line, and takes the secrets out."""

    def filter(self, record: logging.LogRecord) -> bool:
        number = _request_id.get()
        who = _actor.get()
        record.request_id = f"{number} {who}".strip() if who else number
        if record.args:
            record.msg = record.getMessage()
            record.args = ()
        if isinstance(record.msg, str) and "=" in record.msg:
            record.msg = redact(record.msg)
        return True


# ---------------------------------------------------------------------------
# Where it lives
# ---------------------------------------------------------------------------


def log_dir() -> Path:
    directory = get_settings().data_dir / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def log_file() -> Path:
    return log_dir() / "nexdeck.log"


def rotated() -> list[Path]:
    """The kept older files. ``nexdeck.log.1`` is the most recent of them."""
    return sorted(p for p in log_dir().glob("nexdeck.log.*") if p.is_file())


# ---------------------------------------------------------------------------
# Setting up and switching
# ---------------------------------------------------------------------------


def env_mode() -> str | None:
    """The level from ``NEXDECK_LOG_LEVEL``, if somebody actually set it.

    ⚠️ Read from the environment, not from the settings. ``log_level`` carries
    a default of ``INFO``, so asking the settings said "somebody set this" on
    every installation, and the switch in the interface was greyed out with
    the wrong reason for everybody.
    """
    value = (os.environ.get("NEXDECK_LOG_LEVEL") or "").strip().lower()
    if not value:
        return None
    if value in MODES:
        return value
    # Somebody who writes the technical name should not reach into nothing.
    return {"warning": "quiet", "warn": "quiet", "error": "quiet",
            "info": "normal", "debug": "detailed"}.get(value)


def setup() -> None:
    """Set logging up, once at start.

    The stored level is deliberately not read here: on the very first start
    there is no database yet. ``apply_stored()`` catches up once there is.
    """
    global _handler

    root = logging.getLogger()
    uvicorn_error = logging.getLogger("uvicorn.error")

    # ⚠️ Take our own handlers away first. A reload would otherwise add a
    # second one and every line would appear twice.
    for target in (root, uvicorn_error):
        for existing in list(target.handlers):
            if getattr(existing, "_nexdeck", False):
                target.removeHandler(existing)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    handler = RotatingFileHandler(log_file(), maxBytes=MAX_BYTES_NORMAL, backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(formatter)
    handler.addFilter(_Context())
    handler._nexdeck = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    _handler = handler

    # Also to the container output, so `docker logs` does not go quiet.
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(_Context())
    console._nexdeck = True  # type: ignore[attr-defined]
    root.addHandler(console)

    # ⚠️ uvicorn keeps its logger on ``propagate = False``. Without this line no
    # start-up failure and no crash from the server itself reaches the file,
    # which is exactly what somebody asks for when they ask for the log.
    uvicorn_error.addHandler(handler)

    apply_mode(env_mode() or DEFAULT_MODE)


def teardown() -> None:
    """Take our handlers off again and close the file.

    ⚠️ Windows refuses to remove a file another handle still holds open, so a
    test that cleans up after itself has to come through here first. The same
    applies to a shutdown that wants to leave nothing behind.
    """
    global _handler
    for target in (logging.getLogger(), logging.getLogger("uvicorn.error")):
        for existing in list(target.handlers):
            if getattr(existing, "_nexdeck", False):
                target.removeHandler(existing)
                try:
                    existing.close()
                except Exception:  # noqa: BLE001
                    pass
    _handler = None


def apply_mode(mode: str) -> None:
    """Make a level take effect, without a restart.

    A restart usually destroys the state somebody wanted to look at.
    """
    global _mode
    levels = MODES.get(mode)
    if levels is None:
        mode, levels = DEFAULT_MODE, MODES[DEFAULT_MODE]
    _mode = mode

    logging.getLogger().setLevel(levels["root"])
    logging.getLogger("nexdeck").setLevel(levels["app"])
    for name in NOISY:
        logging.getLogger(name).setLevel(levels["libs"])
    if _handler is not None:
        _handler.maxBytes = MAX_BYTES_DEEP if mode in DEEP_MODES else MAX_BYTES_NORMAL


def current_mode() -> str:
    return _mode


def fixed_by_env() -> bool:
    """An operator who sets the level in the environment means it."""
    return env_mode() is not None


# ---------------------------------------------------------------------------
# The level, and the end it carries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeState:
    mode: str
    until: datetime | None
    fixed_by_env: bool


def stored(db: DbSessionType) -> tuple[str, datetime | None]:
    row = db.get(Setting, KEY)
    data: dict[str, Any] = dict(row.value or {}) if row else {}
    mode = str(data.get("mode") or DEFAULT_MODE)
    raw = data.get("until")
    if mode not in MODES:
        mode = DEFAULT_MODE
    end: datetime | None = None
    if raw:
        try:
            end = datetime.fromisoformat(str(raw))
        except ValueError:
            end = None
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
    return mode, end


def _store(db: DbSessionType, mode: str, until: datetime | None) -> None:
    row = db.get(Setting, KEY)
    value = {"mode": mode, "until": until.isoformat() if until else None}
    if row is None:
        db.add(Setting(key=KEY, value=value))
    else:
        row.value = value


def set_mode(db: DbSessionType, mode: str, minutes: int = 0) -> ModeState:
    """Switch the level, and give a deep one an end.

    ⚠️ A deep level without an end is how a data directory fills up. Somebody
    turns tracing on for one problem and the setting is still there months
    later, writing every request to disk.
    """
    if mode not in MODES:
        raise ValueError(mode)
    if minutes not in ALLOWED_MINUTES:
        raise ValueError(minutes)
    until = datetime.now(UTC) + timedelta(minutes=minutes) if (mode in DEEP_MODES and minutes) else None
    _store(db, mode, until)
    db.commit()
    if not fixed_by_env():
        apply_mode(mode)
        global _until
        _until = until
        logger.info("The log level is now %s%s.", mode, f" until {until:%Y-%m-%d %H:%M} UTC" if until else "")
    return ModeState(mode=mode, until=until, fixed_by_env=fixed_by_env())


def apply_stored(db: DbSessionType) -> None:
    """Take the stored level over, once the database is there."""
    global _until
    mode, until = stored(db)
    if until is not None and until <= datetime.now(UTC):
        mode, until = DEFAULT_MODE, None
        _store(db, mode, until)
        db.commit()
    _until = until
    if not fixed_by_env():
        apply_mode(mode)


def enforce_expiry(db: DbSessionType) -> bool:
    """Turn a deep level off once its time is up. Called by the loop."""
    mode, until = stored(db)
    if mode not in DEEP_MODES or until is None or until > datetime.now(UTC):
        return False
    _store(db, DEFAULT_MODE, None)
    db.commit()
    global _until
    _until = None
    if not fixed_by_env():
        apply_mode(DEFAULT_MODE)
    logger.info("The log level went back to %s: the time it was set for is up.", DEFAULT_MODE)
    return True


def state(db: DbSessionType) -> ModeState:
    mode, until = stored(db)
    return ModeState(mode=mode, until=until, fixed_by_env=fixed_by_env())


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    time: str
    level: str
    logger: str
    message: str
    request_id: str | None = None


def parse(raw: str) -> Line | None:
    found = LINE.match(raw)
    if found is None:
        return None
    request = (found.group("request") or "").strip()
    return Line(
        time=found.group("time"),
        level=found.group("level"),
        logger=found.group("logger"),
        message=found.group("message").rstrip(),
        request_id=request or None,
    )


def read(limit: int = 200, level: str | None = None, search: str | None = None) -> list[Line]:
    """The newest lines first. ``level`` means "this one and above".

    Reads the rotated files too, newest first, and stops as soon as it has
    enough: on a trace-level file that is the difference between an answer and
    a timeout.
    """
    wanted = LEVELS.index(level) if level in LEVELS else 0
    needle = (search or "").lower().strip()
    found: list[Line] = []
    for path in [log_file(), *rotated()]:
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for text in reversed(raw.splitlines()):
            line = parse(text)
            if line is None:
                continue
            if LEVELS.index(line.level) < wanted:
                continue
            if needle and needle not in text.lower():
                continue
            found.append(line)
            if len(found) >= limit:
                return found
    return found


def download() -> tuple[str, bool]:
    """The whole log as text, and whether it had to be cut.

    Oldest first here, unlike the view: a file somebody reads from the top
    should read forwards.
    """
    parts: list[str] = []
    total = 0
    cut = False
    for path in [*reversed(rotated()), log_file()]:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if total + len(text) > DOWNLOAD_LIMIT:
            text = text[: max(0, DOWNLOAD_LIMIT - total)]
            cut = True
        parts.append(text)
        total += len(text)
        if cut:
            break
    return "".join(parts), cut


def clear() -> int:
    """Empty the log. Returns how many files were touched."""
    touched = 0
    for path in rotated():
        try:
            path.unlink()
            touched += 1
        except OSError:
            pass
    current = log_file()
    if current.exists():
        # Truncated rather than removed: the handler holds it open, and on
        # Windows a removed file would take the rest of the run's lines with it.
        try:
            with current.open("w", encoding="utf-8"):
                pass
            touched += 1
        except OSError:
            pass
    logger.info("The log was cleared by an administrator.")
    return touched
