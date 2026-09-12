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
from types import SimpleNamespace

import httpx
import pytest
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


def test_the_icon_proxy_builds_one_client_and_not_one_per_icon(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ Building an :class:`httpx.AsyncClient` loads the CA bundle and builds
    a TLS context, and it does that on the event loop: measured on Windows on
    09.09.2026, 1.0 s each, 11.35 s for eleven in a row. This proxy built one
    per icon. On the first load of a fresh installation nothing is cached and
    the demo board asks for eleven logos at once, so the server had no turn
    for anything else for about eleven seconds: the live stream took 5.4 s to
    open and the board answer that carries the cards' first data came back
    after 14.3 s, against an end-to-end test that waits 15 s.
    """
    import asyncio

    from app.services import icons

    built = 0
    real = icons.outbound_client

    def counted(**kwargs: object):  # noqa: ANN202
        nonlocal built
        built += 1
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(icons, "outbound_client", counted)
    monkeypatch.setattr(icons, "_client", None)
    monkeypatch.setattr(icons, "_negative", {})

    async def answer(_self: object, url: str, **_kwargs: object) -> object:
        return SimpleNamespace(status_code=200, content=b"<svg/>")

    monkeypatch.setattr(httpx.AsyncClient, "get", answer)

    async def five_icons() -> None:
        try:
            for name in ("sonarr", "radarr", "plex", "emby", "kavita"):
                assert await icons.fetch_icon(name, "svg") is not None
        finally:
            await icons.close_client()

    asyncio.run(five_icons())
    assert built == 1, f"five icons cost {built} clients, which is {built} TLS contexts on the event loop"


class Clients:
    """Counts the clients one module builds while a block of code runs.

    ⚠️ The reason is the same everywhere and it is measured: a fresh
    :class:`httpx.AsyncClient` builds a TLS context and loads the CA bundle,
    on the event loop, and on Windows on 09.09.2026 that cost 1.0 s each and
    11.35 s for eleven in a row. Four places built one per call. While one is
    being built nothing else in the server gets a turn, not the live stream,
    not a board answer, not another notification.

    Setting ``_client`` is also the trip wire: a module that goes back to
    ``async with outbound_client(...)`` per call has no such attribute, and
    this stops there.
    """

    def __init__(self, module: object, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        real = module.outbound_client  # type: ignore[attr-defined]

        def counted(**kwargs: object):  # noqa: ANN202
            self.count += 1
            return real(**kwargs)

        monkeypatch.setattr(module, "outbound_client", counted)
        monkeypatch.setattr(module, "_client", None)


def test_a_notification_channel_builds_one_client_and_not_one_per_message(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An outage reaches every channel that subscribed to it, one after the
    other. At one client each, the server stood still for a second per
    channel at the moment it has the most to say.
    """
    import asyncio

    from app.services import channels
    from app.services.notify import Message

    built = Clients(channels, monkeypatch)

    async def answer(_self: object, _url: str, **_kwargs: object) -> object:
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, "post", answer)
    message = Message(event="outage", title="Sonarr is down", body="No answer for 90 s.", level="error")

    async def four_channels() -> None:
        try:
            for topic in ("deck", "house", "arr", "spare"):
                await channels.send("ntfy", {"url": "https://ntfy.example.com", "topic": topic}, message)
        finally:
            await channels.close_client()

    asyncio.run(four_channels())
    assert built.count == 1, f"four notifications cost {built.count} clients, one TLS context each"


def test_web_push_builds_one_client_and_not_one_per_subscription(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One account is a phone, a tablet and two browsers. Each of them is its
    own POST to its own push service, and each one used to build a client.
    """
    import asyncio
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.migrations import migrate
    from app.services.channels import webpush
    from app.services.notify import Message

    # The signature names the public address, and that is read from the
    # settings table the way every running installation has it.
    migrate()
    vapid = ec.generate_private_key(ec.SECP256R1())
    pem = vapid.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    monkeypatch.setattr(webpush, "ensure_keys", lambda: (pem, "public"))

    browser = ec.generate_private_key(ec.SECP256R1())
    p256dh = webpush._b64url(
        browser.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    auth = webpush._b64url(os.urandom(16))

    built = Clients(webpush, monkeypatch)

    async def answer(_self: object, _url: str, **_kwargs: object) -> object:
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr(httpx.AsyncClient, "post", answer)
    message = Message(event="outage", title="Sonarr is down", body="No answer for 90 s.", level="error")

    async def four_devices() -> None:
        try:
            for device in ("phone", "tablet", "laptop", "desktop"):
                assert await webpush.send_one(f"https://push.example.com/send/{device}", p256dh, auth, message)
        finally:
            await webpush.close_client()

    asyncio.run(four_devices())
    assert built.count == 1, f"four devices cost {built.count} clients, one TLS context each"


def test_a_sign_in_builds_one_client_and_not_one_per_leg(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One sign-in walks discovery, the code exchange and userinfo. Three
    legs, three clients, three seconds of a stopped server, while the person
    signing in sits on a redirect and waits.

    The legs differ in timeout and headers; httpx takes both per request, so
    sharing the client costs them nothing.
    """
    import asyncio

    from app.services import oidc

    monkeypatch.setattr(oidc, "_discovery", {})
    built = Clients(oidc, monkeypatch)
    document = {
        "issuer": "https://id.example.com",
        "authorization_endpoint": "https://id.example.com/auth",
        "token_endpoint": "https://id.example.com/token",
        "jwks_uri": "https://id.example.com/certs",
        "userinfo_endpoint": "https://id.example.com/userinfo",
    }

    async def get(_self: object, _url: str, **_kwargs: object) -> object:
        return SimpleNamespace(status_code=200, json=lambda: document)

    async def post(_self: object, _url: str, **_kwargs: object) -> object:
        return SimpleNamespace(status_code=200, json=lambda: {"id_token": "pretend", "access_token": "pretend"})

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    async def one_sign_in() -> None:
        try:
            assert await oidc.discovery("https://id.example.com")
            assert await oidc.exchange(document, "nexdeck", "secret", "https://deck.example.com/cb", "code", "verifier")
            assert await oidc.userinfo(document, "pretend")
            # A second provider, so the discovery cache does not hide a build.
            assert await oidc.discovery("https://other.example.com")
        finally:
            await oidc.close_client()

    asyncio.run(one_sign_in())
    assert built.count == 1, f"one sign-in cost {built.count} clients, one TLS context each"


def test_the_update_check_builds_one_client_and_not_one_per_look(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The answer is cached for six hours, so this is the cheapest of the
    four. It is also the only one somebody presses a button for and then
    watches, and the second it cost was a second of nothing else moving.
    """
    import asyncio

    from app import __version__
    from app.routers import system

    monkeypatch.setattr(system, "_update_cache", {})
    built = Clients(system, monkeypatch)

    async def answer(_self: object, _url: str, **_kwargs: object) -> object:
        # The version this installation already runs, so the check has
        # nothing to announce and stays out of the database.
        return SimpleNamespace(status_code=200, json=lambda: {"tag_name": f"v{__version__}"})

    monkeypatch.setattr(httpx.AsyncClient, "get", answer)

    async def four_looks() -> None:
        try:
            for _ in range(4):
                assert await system.latest_version(force=True) == __version__
        finally:
            await system.close_client()

    asyncio.run(four_looks())
    assert built.count == 1, f"four looks cost {built.count} clients, one TLS context each"

