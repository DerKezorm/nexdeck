"""nexdeck's own log: written to a file, readable back, and self-limiting.

Everything used to go to standard output and nowhere else, so the one thing
an administrator asks for after a bad night did not exist on a machine whose
container log had rotated away.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.services import journal

from .conftest import CSRF, create_user, login, setup_admin


@pytest.fixture(autouse=True)
def _fresh_log(data_dir, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201
    """Each test gets the data directory of its own instance, and a schema.

    ⚠️ The suite sets ``NEXDECK_LOG_LEVEL=WARNING`` so a test run stays quiet,
    which means ``setup()`` starts in the quiet level and drops every INFO line
    these tests write. The level is forced back afterwards; the environment is
    what the one test about it changes for itself.
    """
    from app import config
    from app.migrations import migrate

    # ⚠️ The suite sets the level in the environment so a run stays quiet. That
    # also freezes it: ``fixed_by_env`` would be true and the switch in the
    # interface would refuse every change. These tests model a normal install,
    # where nobody set it, and the one test about the environment sets it back.
    monkeypatch.setenv("NEXDECK_LOG_LEVEL", "")
    config.reset_settings_cache()
    migrate()
    journal.setup()
    journal.apply_mode("normal")
    yield
    # The handler has to let go of the file before Windows will remove it.
    journal.teardown()
    for path in [journal.log_file(), *journal.rotated()]:
        path.unlink(missing_ok=True)


def _write(message: str, level: int = logging.INFO, name: str = "nexdeck.test") -> None:
    logging.getLogger(name).log(level, message)
    for handler in logging.getLogger().handlers:
        handler.flush()


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def test_a_line_reaches_the_file_and_comes_back() -> None:
    _write("something happened")
    found = journal.read(limit=50)
    assert any(line.message == "something happened" for line in found), [line.message for line in found]


def test_the_newest_line_comes_first() -> None:
    """An administrator opens this to see what just happened."""
    _write("older")
    _write("newer")
    messages = [line.message for line in journal.read(limit=50)]
    assert messages.index("newer") < messages.index("older")


def test_a_level_filter_means_this_level_and_above() -> None:
    _write("a quiet note", logging.INFO)
    _write("a real problem", logging.ERROR)
    only = [line.message for line in journal.read(limit=50, level="WARNING")]
    assert "a real problem" in only
    assert "a quiet note" not in only


def test_the_search_looks_at_the_whole_line() -> None:
    _write("the collector gave up on widget 12")
    assert [line.message for line in journal.read(search="widget 12")]
    assert not journal.read(search="widget 99")


def test_a_line_from_an_older_format_stays_readable() -> None:
    """⚠️ After an update the same file holds lines the version before it
    wrote. Refusing them would blank out exactly the part somebody wants."""
    old = journal.parse("2026-09-06 04:12:33 WARNING nexdeck.collector Radarr stopped answering")
    assert old is not None
    assert old.level == "WARNING" and old.request_id is None
    assert old.message == "Radarr stopped answering"

    new = journal.parse("2026-09-06 04:12:33 WARNING  nexdeck.collector [a1b2c3 kim] Radarr stopped answering")
    assert new is not None
    assert new.request_id == "a1b2c3 kim"
    assert new.message == "Radarr stopped answering"


def test_a_line_that_is_not_one_is_skipped_rather_than_guessed_at() -> None:
    assert journal.parse("") is None
    assert journal.parse("  File \"/app/thing.py\", line 12, in fetch") is None


def test_clearing_leaves_the_file_writable() -> None:
    """⚠️ Removed rather than truncated, the handler would hold a deleted file
    open and every line for the rest of the run would go nowhere."""
    _write("before")
    journal.clear()
    _write("after")
    messages = [line.message for line in journal.read(limit=50)]
    assert "after" in messages
    assert "before" not in messages


# ---------------------------------------------------------------------------
# The request number
# ---------------------------------------------------------------------------


def test_a_line_carries_the_request_it_belongs_to() -> None:
    """A dozen background tasks write into the same file at once."""
    token = journal.bind_request("abc123")
    try:
        _write("inside a request")
    finally:
        journal.unbind_request(token)
    _write("outside one")

    lines = {line.message: line.request_id for line in journal.read(limit=50)}
    assert lines["inside a request"] == "abc123"
    assert lines["outside one"] == "-"


def test_the_actor_rides_along_when_it_is_known() -> None:
    token = journal.bind_request("abc123")
    journal.set_actor("kim")
    try:
        _write("kim did something")
    finally:
        journal.set_actor("")
        journal.unbind_request(token)
    lines = {line.message: line.request_id for line in journal.read(limit=50)}
    assert lines["kim did something"] == "abc123 kim"


# ---------------------------------------------------------------------------
# The level, and the end it carries
# ---------------------------------------------------------------------------


def test_a_deep_level_carries_an_end() -> None:
    """⚠️ This is how a data directory fills up: somebody turns tracing on for
    one problem and it is still on months later."""
    with db_session() as db:
        state = journal.set_mode(db, "trace", 30)
    assert state.mode == "trace"
    assert state.until is not None
    assert timedelta(minutes=25) < state.until - datetime.now(UTC) < timedelta(minutes=35)


def test_a_shallow_level_needs_no_end() -> None:
    with db_session() as db:
        state = journal.set_mode(db, "normal", 0)
    assert state.until is None


def test_a_deep_level_may_also_be_set_until_the_next_restart() -> None:
    with db_session() as db:
        assert journal.set_mode(db, "detailed", 0).until is None


def test_the_deep_level_is_taken_away_when_its_time_is_up() -> None:
    with db_session() as db:
        journal.set_mode(db, "trace", 30)
        # Move the end into the past rather than waiting half an hour.
        journal._store(db, "trace", datetime.now(UTC) - timedelta(minutes=1))
        db.commit()
        assert journal.enforce_expiry(db) is True
        assert journal.state(db).mode == "normal"
        assert journal.enforce_expiry(db) is False, "and it does not keep firing afterwards"


def test_a_level_that_is_still_running_is_left_alone() -> None:
    with db_session() as db:
        journal.set_mode(db, "trace", 480)
        assert journal.enforce_expiry(db) is False
        assert journal.state(db).mode == "trace"


def test_an_unknown_level_or_duration_is_refused() -> None:
    with db_session() as db:
        with pytest.raises(ValueError):
            journal.set_mode(db, "verbose", 0)
        with pytest.raises(ValueError):
            journal.set_mode(db, "trace", 7)


def test_the_level_takes_effect_at_once() -> None:
    """A restart destroys the state somebody wanted to look at."""
    journal.apply_mode("quiet")
    assert logging.getLogger("nexdeck").level == logging.WARNING
    journal.apply_mode("trace")
    assert logging.getLogger("nexdeck").level == logging.DEBUG


def test_a_level_in_the_environment_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator who sets it there means it, and the interface says so."""
    from app import config

    monkeypatch.setenv("NEXDECK_LOG_LEVEL", "debug")
    config.reset_settings_cache()
    try:
        assert journal.env_mode() == "detailed", "the technical name reaches a level, not nothing"
        assert journal.fixed_by_env() is True
        monkeypatch.setenv("NEXDECK_LOG_LEVEL", "")
        config.reset_settings_cache()
        assert journal.fixed_by_env() is False, "and an empty one leaves the choice to the interface"
    finally:
        config.reset_settings_cache()


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_only_an_administrator_reads_the_log(client: TestClient) -> None:
    """It carries every message the server has, including other people's."""
    setup_admin(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    for path in ("/api/v1/journal", "/api/v1/journal/level", "/api/v1/journal/download"):
        assert kim.get(path).status_code == 403, path
    assert kim.put("/api/v1/journal/level", json={"mode": "trace"}, headers=CSRF).status_code == 403
    assert kim.delete("/api/v1/journal", headers=CSRF).status_code == 403


def test_the_administrator_reads_filters_and_downloads_it(client: TestClient) -> None:
    setup_admin(client)
    _write("a line for the administrator", logging.ERROR)

    listed = client.get("/api/v1/journal?limit=100")
    assert listed.status_code == 200, listed.text
    assert any(row["message"] == "a line for the administrator" for row in listed.json())

    filtered = client.get("/api/v1/journal?level=ERROR&search=administrator")
    assert filtered.status_code == 200
    assert filtered.json(), "the line is an ERROR and contains the word"

    taken = client.get("/api/v1/journal/download")
    assert taken.status_code == 200
    assert "a line for the administrator" in taken.text
    assert "attachment" in taken.headers["content-disposition"]


def test_the_level_can_be_changed_and_says_what_it_is(client: TestClient) -> None:
    setup_admin(client)
    now = client.get("/api/v1/journal/level").json()
    assert now["mode"] == "normal" and now["until"] is None
    assert set(now["modes"]) == set(journal.MODES)

    changed = client.put("/api/v1/journal/level", json={"mode": "detailed", "minutes": 120}, headers=CSRF)
    assert changed.status_code == 200, changed.text
    assert changed.json()["mode"] == "detailed"
    assert changed.json()["until"] is not None
    assert client.get("/api/v1/journal/level").json()["mode"] == "detailed"


def test_a_level_the_environment_fixed_is_not_overwritten(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A switch that pretends to work is worse than one that says it cannot."""
    setup_admin(client)
    from app import config

    monkeypatch.setenv("NEXDECK_LOG_LEVEL", "trace")
    config.reset_settings_cache()
    try:
        assert client.get("/api/v1/journal/level").json()["fixed_by_env"] is True
        refused = client.put("/api/v1/journal/level", json={"mode": "quiet"}, headers=CSRF)
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "fixed_by_env"
    finally:
        config.reset_settings_cache()


def test_emptying_the_log_works_and_is_itself_recorded(client: TestClient) -> None:
    setup_admin(client)
    _write("something from before")
    assert client.delete("/api/v1/journal", headers=CSRF).status_code == 204

    left = [row["message"] for row in client.get("/api/v1/journal?limit=100").json()]
    assert "something from before" not in left
    assert any("cleared by an administrator" in message for message in left), left


def test_nobody_setting_the_level_leaves_the_switch_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ ``log_level`` carries a default of INFO. Asking the settings instead
    of the environment answered "somebody set this" on every installation, and
    the switch in the interface was greyed out for everybody with a reason that
    was not true."""
    monkeypatch.delenv("NEXDECK_LOG_LEVEL", raising=False)
    from app import config

    config.reset_settings_cache()
    try:
        assert config.get_settings().log_level, "the default is still there; that is not the question"
        assert journal.env_mode() is None
        assert journal.fixed_by_env() is False
    finally:
        config.reset_settings_cache()


def test_a_key_in_a_query_never_reaches_the_file() -> None:
    """⚠️ httpx logs the full address of every request at INFO, and the deep
    log levels turn httpx up to exactly that. Several services take their key
    in the query string: Kavita wants ``apiKey``, Technitium wants ``token``,
    Synology's ``auth.cgi`` takes the DSM password that way. The line then sat
    in ``data/logs/nexdeck.log`` and in ``docker logs``, and the deep level
    exists precisely so somebody can download that file and attach it to an
    issue.
    """
    journal.apply_mode("detailed")
    logging.getLogger("httpx").info(
        'HTTP Request: GET %s "HTTP/1.1 200 OK"',
        "http://kavita.example.com:5000/api/Series?apiKey=THE-REAL-KEY&libraryId=1",
    )
    logging.getLogger("nexdeck").info(
        "GET https://dsm.example.com:5001/webapi/auth.cgi?account=admin&passwd=THE-REAL-PASSWORD&format=sid",
    )
    for handler in logging.getLogger().handlers:
        handler.flush()
    written = journal.log_file().read_text(encoding="utf-8", errors="replace")

    assert "THE-REAL-KEY" not in written, "an API key from a query string was written to the log"
    assert "THE-REAL-PASSWORD" not in written, "a password from a query string was written to the log"
    assert "apiKey=***" in written and "passwd=***" in written, "the lines were not written at all, so this proves nothing"
    assert "libraryId=1" in written, "the rest of the address should survive; only the secret goes"
