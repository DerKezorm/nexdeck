"""What the server does per request, and how often it does it.

⚠️ None of this is about a benchmark. Each one is a count that used to grow
with the size of the board or the length of a log file, on a machine that is
often a Raspberry Pi:

* opening a board asked SQLite two questions per checked card
* every single request read the key file off the disk and made a directory
* asking for the last 200 log lines read the whole log file into memory
* the compose file this project ships puts uvicorn straight in front of the
  browser, and nothing compressed anything
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import get_engine

from .conftest import CSRF, setup_admin


class Counter:
    """Counts the statements a block of code sends to SQLite."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> Counter:
        self._engine = get_engine()
        event.listen(self._engine, "before_cursor_execute", self._note)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(self._engine, "before_cursor_execute", self._note)

    def _note(self, _conn, _cursor, statement, *_rest) -> None:  # noqa: ANN001
        self.statements.append(statement)

    def against(self, table: str) -> int:
        return sum(1 for s in self.statements if table in s)


def _board_with_checked_cards(client: TestClient, how_many: int) -> str:
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    for number in range(how_many):
        made = client.post(f"/api/v1/pages/{page}/widgets", json={
            "kind": "core.app", "title": f"App {number}", "link": f"https://a{number}.example.com",
        }, headers=CSRF)
        assert made.status_code == 201, made.text
        widget_id = made.json()["widget"]["id"]
        check = client.put(f"/api/v1/widgets/{widget_id}/health", json={
            "kind": "http", "target": f"https://a{number}.example.com",
        }, headers=CSRF)
        assert check.status_code == 200, check.text
    return board["slug"]


def test_opening_a_board_does_not_ask_twice_per_card(client: TestClient) -> None:
    """⚠️ Two queries per checked card, so thirty cards meant sixty round
    trips before the first byte went out. Now: one pair per bar window.
    """
    setup_admin(client)
    slug = _board_with_checked_cards(client, 8)

    with Counter() as counted:
        seen = client.get(f"/api/v1/boards/{slug}")
    assert seen.status_code == 200, seen.text
    assert len(seen.json()["pages"][0]["widgets"]) == 8, "the board came back without its cards"

    history = counted.against("history_minutes") + counted.against("history_samples")
    assert history <= 4, f"{history} history queries for eight cards"


def test_the_key_file_is_read_once_and_not_per_request(data_dir: Path, monkeypatch) -> None:
    """⚠️ Every signed cookie and every session check goes through here, so a
    ``mkdir`` and a read from disk happened on every single request.

    ⚠️ Without an empty ``NEXDECK_SECRET_KEY`` this test proves nothing: the
    configured secret is returned before the file is ever looked at, and the
    fixtures set one. It caught nothing at first for exactly that reason.
    """
    monkeypatch.setenv("NEXDECK_SECRET_KEY", "")
    from app import config

    config.reset_settings_cache()
    settings = config.get_settings()
    first = settings.resolved_secret_key()
    key_file = data_dir / "secret.key"
    assert key_file.exists(), "no key file was written, so this test proves nothing"
    key_file.unlink()
    # Gone from the disk, still known: it was remembered.
    assert settings.resolved_secret_key() == first
    assert not key_file.exists(), "it went back to the disk instead of remembering"


def test_the_log_view_does_not_read_the_whole_file(client: TestClient, data_dir: Path) -> None:
    """⚠️ At trace level a log file grows to hundreds of megabytes, and the
    answer to "show me the last page" was the server reading all of it.
    """
    from app.services import journal

    setup_admin(client)
    path = journal.log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "2026-09-07 12:00:00 INFO     nexdeck [-] line number {number}\n"
    with path.open("w", encoding="utf-8") as handle:
        for number in range(20_000):
            handle.write(line.format(number=number))

    # ⚠️ Counted around ``read``, the way the log view calls it, and not
    # around the block reader underneath. Counting the inner one leaves the
    # call site free to go back to reading the file whole, and the answer is
    # the same either way; only the memory is not.
    lines: list[journal.Line] = []
    size = path.stat().st_size
    assert size > 500_000, f"the file is only {size} bytes, so reading it whole would prove nothing"
    read_bytes = _bytes_read_by(lambda: lines.extend(journal.read(limit=5)))

    assert len(lines) == 5
    assert "19999" in lines[0].message, "the newest line is not the first one"
    assert "19995" in lines[4].message
    assert read_bytes < size / 4, f"{read_bytes} of {size} bytes read for five lines"


class _Counted:
    """A file handle that remembers how much was read through it."""

    total = 0

    def __init__(self, handle) -> None:  # noqa: ANN001
        self._handle = handle

    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size)
        _Counted.total += len(chunk)
        return chunk

    def seek(self, *where: int) -> int:
        return self._handle.seek(*where)

    def __enter__(self) -> _Counted:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._handle.close()


def _bytes_read_by(work) -> int:  # noqa: ANN001
    """How many bytes ``work`` reads through ``Path.open``."""
    import pathlib as _pathlib

    real_open = _pathlib.Path.open
    _Counted.total = 0

    def counted(self, *args: object, **kwargs: object):  # noqa: ANN001, ANN202
        return _Counted(real_open(self, *args, **kwargs))

    _pathlib.Path.open = counted  # type: ignore[method-assign]
    try:
        work()
    finally:
        _pathlib.Path.open = real_open  # type: ignore[method-assign]
    return _Counted.total


def test_the_frontend_is_not_sent_uncompressed(client: TestClient) -> None:
    """⚠️ First load was 713 kB where it is 222 kB compressed, over whatever
    line the operator has, because the shipped compose file puts uvicorn
    straight in front of the browser.
    """
    setup_admin(client)
    plain = client.get("/api/v1/adapters", headers={"Accept-Encoding": "identity"})
    zipped = client.get("/api/v1/adapters", headers={"Accept-Encoding": "gzip"})
    assert plain.status_code == 200 and zipped.status_code == 200
    assert zipped.headers.get("content-encoding") == "gzip"
    sent = int(zipped.headers["content-length"])
    assert sent * 3 < len(plain.content), f"{sent} of {len(plain.content)} bytes is not worth calling compression"


def test_a_short_answer_is_left_alone(client: TestClient) -> None:
    """Below the floor, compressing costs more than it saves."""
    setup_admin(client)
    small = client.get("/api/v1/auth/me", headers={"Accept-Encoding": "gzip"})
    assert small.status_code == 200
    assert small.headers.get("content-encoding") is None
