"""Places that had no ceiling, and tables that had no end.

⚠️ All three upload endpoints read the whole body and checked the size
afterwards. Two things were wrong with that. The memory: ``file.read()`` with
no argument loads everything. And the disk, without an account at all, because
FastAPI reads the form before it resolves the dependencies: a 30 GB multipart
part sent to ``POST /auth/me/avatar`` landed in the temp directory in full, and
only then came the 401. The comment on the limit in ``backups.py`` claimed in so
many words that this could not happen.

Five tables grew for as long as an installation ran, and ``password_reset``
had a ``prune`` that nothing ever called.

And a connection number is a bare integer inside ``Widget.options``, while
SQLite hands out the number of a deleted row again: a card kept the 7 of a
connection that was gone, and the next connection an administrator created
became connection 7.
"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import ActionLog, Asset, Notice, Outage, Widget, utcnow
from app.services import retention

from .conftest import CSRF, create_user, login, setup_admin


def _picture() -> bytes:
    """A one-pixel PNG, so the avatar reader sees a real signature."""
    return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


# -- the body is weighed before it is read -------------------------------------


def test_a_body_too_big_is_refused_before_anybody_signs_in(client: TestClient) -> None:
    """⚠️ No account needed for the old version of this: the form was read
    first, so the file was on disk before the 401.
    """
    setup_admin(client)
    client.post("/api/v1/auth/logout", headers=CSRF)
    huge = client.post(
        "/api/v1/auth/me/avatar",
        files={"file": ("big.png", b"x", "image/png")},
        headers={**CSRF, "Content-Length": str(40 * 1024 * 1024)},
    )
    assert huge.status_code == 413, huge.text
    assert huge.json()["detail"]["code"] == "too_large"


def test_the_archive_address_may_receive_a_large_file(client: TestClient) -> None:
    """One address legitimately takes half a gigabyte, and only that one."""
    from app.main import MAX_BIG_BODY, MAX_BODY, body_limit

    assert body_limit("/api/v1/backups/restore") == MAX_BIG_BODY
    assert body_limit("/api/v1/assets") == MAX_BODY
    assert MAX_BODY < MAX_BIG_BODY


async def test_a_body_without_a_length_is_counted_as_it_arrives() -> None:
    """Chunked transfer declares no length, so the handler has to count."""
    import pytest
    from fastapi import HTTPException, UploadFile

    from app.uploads import read_at_most

    small = UploadFile(filename="small.bin", file=io.BytesIO(b"a" * 500))
    assert await read_at_most(small, 1000) == b"a" * 500

    big = UploadFile(filename="big.bin", file=io.BytesIO(b"a" * 4_000_000))
    with pytest.raises(HTTPException) as refused:
        await read_at_most(big, 1_000_000, "picture")
    assert refused.value.status_code == 413
    assert refused.value.detail["code"] == "too_large"


# -- what one account may leave lying about ------------------------------------


def test_an_account_cannot_fill_the_disk(client: TestClient, monkeypatch) -> None:
    setup_admin(client)
    monkeypatch.setenv("NEXDECK_UPLOAD_QUOTA_MB", "1")
    from app import config

    config.reset_settings_cache()

    first = client.post("/api/v1/assets", files={"file": ("a.png", _picture(), "image/png")}, headers=CSRF)
    assert first.status_code == 201, first.text

    with db_session() as db:
        asset = db.scalar(select(Asset))
        assert asset is not None
        asset.size = 1024 * 1024  # It has now used its megabyte.

    refused = client.post("/api/v1/assets", files={"file": ("b.png", _picture(), "image/png")}, headers=CSRF)
    assert refused.status_code == 413, refused.text
    assert refused.json()["detail"]["code"] == "quota_full"


def test_no_ceiling_means_no_ceiling(client: TestClient, monkeypatch) -> None:
    setup_admin(client)
    monkeypatch.setenv("NEXDECK_UPLOAD_QUOTA_MB", "0")
    from app import config

    config.reset_settings_cache()
    for number in range(3):
        made = client.post("/api/v1/assets", files={"file": (f"{number}.png", _picture(), "image/png")}, headers=CSRF)
        assert made.status_code == 201, made.text


# -- tables that had no end ----------------------------------------------------


def test_the_rows_nobody_reads_again_are_swept(client: TestClient) -> None:
    setup_admin(client)
    old = utcnow() - timedelta(days=200)
    with db_session() as db:
        db.add(ActionLog(actor="someone", action="restart", created_at=old))
        db.add(ActionLog(actor="someone", action="restart", created_at=utcnow()))
        db.add(Notice(event="outage", title="long ago", created_at=old))
        db.add(Notice(event="outage", title="today", created_at=utcnow()))

    with db_session() as db:
        before = retention.counts(db)
        gone = retention.prune_old_records(db)
        after = retention.counts(db)

    assert gone["action_log"] == 1 and gone["notices"] == 1
    assert after["action_log"] == before["action_log"] - 1
    assert after["notices"] == before["notices"] - 1


def test_an_outage_that_is_still_running_is_never_swept(client: TestClient) -> None:
    """It is the reason a card is red, however long ago it started."""
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    widget = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.app", "title": "App", "link": "https://a.example.com"}, headers=CSRF).json()["widget"]
    made = client.put(f"/api/v1/widgets/{widget['id']}/health", json={"kind": "http", "target": "https://a.example.com"}, headers=CSRF)
    assert made.status_code == 200, made.text
    check_id = made.json()["id"]

    long_ago = utcnow() - timedelta(days=900)
    with db_session() as db:
        db.add(Outage(check_id=check_id, started_at=long_ago, ended_at=long_ago + timedelta(hours=1)))
        db.add(Outage(check_id=check_id, started_at=long_ago, ended_at=None))

    with db_session() as db:
        gone = retention.prune_old_records(db)
        left = list(db.scalars(select(Outage)))

    assert gone["outages"] == 1
    assert len(left) == 1 and left[0].ended_at is None


def test_a_switched_off_sweep_keeps_everything(client: TestClient, monkeypatch) -> None:
    setup_admin(client)
    monkeypatch.setenv("NEXDECK_KEEP_ACTION_LOG_DAYS", "0")
    from app import config

    config.reset_settings_cache()
    with db_session() as db:
        db.add(ActionLog(actor="someone", action="restart", created_at=utcnow() - timedelta(days=900)))
    with db_session() as db:
        gone = retention.prune_old_records(db)
        assert gone.get("action_log", 0) == 0
        assert retention.counts(db)["action_log"] == 1


def test_a_file_no_row_points_at_is_removed_and_a_listed_one_is_not(client: TestClient, data_dir) -> None:
    """⚠️ Only the strays. A file whose row exists stays even when no board
    currently shows it: somebody uploaded it on purpose and the interface
    lists it.
    """
    setup_admin(client)
    made = client.post("/api/v1/assets", files={"file": ("keep.png", _picture(), "image/png")}, headers=CSRF)
    assert made.status_code == 201, made.text
    uploads = data_dir / "uploads"
    (uploads / "9999.png").write_bytes(b"left over")

    with db_session() as db:
        gone = retention.sweep_stray_uploads(db)

    assert gone == 1
    assert not (uploads / "9999.png").exists()
    assert len(list(uploads.iterdir())) == 1, "the file that has a row was removed too"


# -- a connection number that outlived its connection --------------------------


def test_deleting_a_connection_takes_its_number_out_of_every_card(client: TestClient) -> None:
    """⚠️ SQLite hands out the number of a deleted row again, so the next
    connection an administrator makes inherits it, and a card that kept the
    number silently starts reading a different service.
    """
    setup_admin(client)
    made = client.post("/api/v1/integrations", json={
        "kind": "radarr", "name": "Films", "config": {"base_url": "http://films.example.com", "api_key": "x" * 32},
        "enabled": True, "demo": True,
    }, headers=CSRF)
    assert made.status_code in (200, 201), made.text
    number = made.json()["id"]

    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    card = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Coming up", "options": {"sources": [number]},
    }, headers=CSRF)
    assert card.status_code == 201, card.text
    widget_id = card.json()["widget"]["id"]

    assert client.delete(f"/api/v1/integrations/{number}", headers=CSRF).status_code == 204
    with db_session() as db:
        widget = db.get(Widget, widget_id)
        assert widget is not None
        assert widget.options.get("sources") == [], f"the card still names connection {number}"


def test_another_connection_on_the_card_stays(client: TestClient) -> None:
    setup_admin(client)
    numbers = []
    for name in ("Films", "Series"):
        made = client.post("/api/v1/integrations", json={
            "kind": "radarr", "name": name, "config": {"base_url": f"http://{name.lower()}.example.com", "api_key": "x" * 32},
            "enabled": True, "demo": True,
        }, headers=CSRF)
        assert made.status_code in (200, 201), made.text
        numbers.append(made.json()["id"])

    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    page = board["pages"][0]["id"]
    card = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "calendar.upcoming", "title": "Coming up", "options": {"sources": numbers},
    }, headers=CSRF)
    widget_id = card.json()["widget"]["id"]

    assert client.delete(f"/api/v1/integrations/{numbers[0]}", headers=CSRF).status_code == 204
    with db_session() as db:
        widget = db.get(Widget, widget_id)
        assert widget is not None
        assert widget.options.get("sources") == [numbers[1]]


# -- caches with a lid ---------------------------------------------------------


def test_the_image_cache_is_bounded_by_bytes_and_not_only_by_count() -> None:
    """⚠️ Three hundred entries at five megabytes each is a gigabyte and a
    half held in a process that often runs on a Raspberry Pi.
    """
    import time

    from app.routers import widgets

    widgets._images.clear()
    try:
        blob = b"x" * (4 * 1024 * 1024)
        for number in range(40):
            widgets._images[(number, "/poster")] = (time.monotonic() + 3600, blob, "image/jpeg")
        widgets._make_room()
        assert widgets._cached_bytes() <= widgets.IMAGE_MAX_TOTAL
        assert widgets._images, "everything was thrown out"
    finally:
        widgets._images.clear()


def test_the_list_of_icons_that_do_not_exist_has_a_lid() -> None:
    """⚠️ It can be filled without signing in: the icon proxy answers before
    any session is required, and every made-up name left an entry behind.
    """
    from app.services import icons

    icons._negative.clear()
    try:
        for number in range(icons.NEGATIVE_LIMIT + 200):
            icons._remember_miss(f"made-up-{number}.svg")
        assert len(icons._negative) <= icons.NEGATIVE_LIMIT
    finally:
        icons._negative.clear()


def test_the_login_brake_does_not_grow_with_the_attempts() -> None:
    """⚠️ A bucket was only dropped when that exact key was looked at again,
    and a guesser sends a different address and name every time.
    """
    import time

    from app.services import login_guard

    login_guard.reset()
    try:
        # What a guesser leaves behind: one bucket per made-up name, all of
        # them long past the window and none of them ever asked about again.
        stale = time.monotonic() - login_guard.WINDOW_SECONDS - 60
        for number in range(login_guard.SWEEP_ABOVE + 200):
            login_guard._failures[f"u:ghost-{number}"] = [stale]
        assert len(login_guard._failures) > login_guard.SWEEP_ABOVE

        login_guard.failed("203.0.113.7", "someone")

        left = len(login_guard._failures)
        assert left < 10, f"{left} buckets survived, and all but two had aged out"
        # What is inside the window stays: the brake still brakes.
        assert login_guard._failures.get("u:someone")
        for _number in range(login_guard.MAX_PER_ACCOUNT):
            login_guard.failed("203.0.113.7", "someone")
        with pytest.raises(login_guard.TooManyAttempts):
            login_guard.check("203.0.113.7", "someone")
    finally:
        login_guard.reset()


def test_a_deleted_connection_leaves_no_cache_and_no_open_client(client: TestClient) -> None:
    """⚠️ The cache and the httpx client inside it used to sit in memory until
    the next restart, with their connections open to a service nobody asks
    about any more.
    """
    import httpx

    from app.services.collector import collector

    setup_admin(client)
    made = client.post("/api/v1/integrations", json={
        "kind": "radarr", "name": "Films", "config": {"base_url": "http://films.example.com", "api_key": "x" * 32},
        "enabled": True, "demo": True,
    }, headers=CSRF)
    number = made.json()["id"]
    kept = httpx.AsyncClient()
    collector._caches[number] = {"radarr_client": kept, "something": 1}

    assert client.delete(f"/api/v1/integrations/{number}", headers=CSRF).status_code == 204
    assert number not in collector._caches


def test_an_answer_far_too_large_for_a_card_is_refused() -> None:
    """An address that turns out to be a file server is read into memory and
    parsed like any other answer.
    """
    import httpx
    import pytest

    from app.adapters.base import MAX_ANSWER_BYTES, AdapterError, _refuse_a_giant_answer

    small = httpx.Response(200, content=b"{}")
    _refuse_a_giant_answer("http://a.example.com", small)

    giant = httpx.Response(200, content=b"x" * (MAX_ANSWER_BYTES + 1))
    with pytest.raises(AdapterError) as refused:
        _refuse_a_giant_answer("http://a.example.com", giant)
    assert refused.value.code == "answer_too_large"


def test_a_guest_may_not_upload_at_all(client: TestClient) -> None:
    """The quota is about members; a guest has no business writing to the disk."""
    setup_admin(client)
    create_user(client, "sam", role="guest")
    guest = TestClient(client.app)
    login(guest, "sam", "another-long-password")
    refused = guest.post("/api/v1/assets", files={"file": ("a.png", _picture(), "image/png")}, headers=CSRF)
    assert refused.status_code == 403, refused.text
