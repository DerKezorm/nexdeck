"""UrBackup, against the answers of a live UrBackup server 2.5.37 with clients 2.5.31 (26.09.2026)."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context

UB = "http://urbackup.example.com:55414"
X = f"{UB}/x"
CONFIG = {"url": UB, "username": "watcher", "password": "a-password-for-the-cards"}
ADAPTER = get_adapter("urbackup")
NOW = 1790456601.0

SALT = {"pbkdf2_rounds": 10000, "rnd": "Lqv91RlgRT", "salt": "abcdefghij0123456789", "ses": "session-from-the-salt"}
ADMIN_RIGHTS = {"api_version": 2, "browse_backups": "all", "graph": "all", "logs": "all", "progress": "all", "settings": "all",
                "status": "all", "success": True}
WATCHER_RIGHTS = {**ADMIN_RIGHTS, "browse_backups": "none", "graph": "none", "logs": "none", "settings": "none"}
NOBODY_RIGHTS = {**WATCHER_RIGHTS, "logs": "all", "progress": "none", "status": "none"}


def client(identifier: int, name: str, **fields: Any) -> dict[str, Any]:
    entry = {"client_version_string": "2.5.31", "delete_pending": "", "file_ok": False, "groupname": "", "id": identifier,
             "image_not_supported": True, "image_ok": False, "ip": f"172.17.0.{14 + identifier}", "last_filebackup_issues": 0,
             "lastbackup": 0, "lastbackup_image": 0, "lastseen": NOW, "name": name, "online": True, "os_simple": "linux",
             "os_version_string": "Debian GNU/Linux 12 (bookworm)", "processes": [], "status": 0, "uid": "mnP0eP96vTF7rwiP"}
    entry.update(fields)
    return entry


CLIENTS = [
    client(1, "laptop-office", file_ok=True, lastbackup=NOW - 58),
    # ⚠️ The key is only there while it is true.
    client(2, "nas-box", no_backup_paths=True),
    client(3, "never-seen", online=False, client_version_string="", ip="-", image_not_supported=None, lastseen=NOW - 84),
]
STATUS = {"admin": True, "curr_version_str": "2.5.37", "curr_version_num": 2005003700, "has_status_check": True, "status": CLIENTS}


def form(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


def server(*, rights: dict[str, Any] = WATCHER_RIGHTS, status: dict[str, Any] = STATUS, progress: dict[str, Any] | None = None) -> dict[str, list[dict[str, str]]]:
    """A fake UrBackup: answers each action and writes down what it was sent."""
    seen: dict[str, list[dict[str, str]]] = {}

    def answer(request: httpx.Request) -> httpx.Response:
        action = request.url.params["a"]
        sent = form(request)
        seen.setdefault(action, []).append(sent)
        if action == "salt":
            return httpx.Response(200, json=SALT)
        if action == "login":
            return httpx.Response(200, json=rights if sent.get("password") == expected else {"api_version": 2, "error": 2})
        if sent.get("ses") != SALT["ses"]:
            return httpx.Response(200, json={"error": 1})
        return httpx.Response(200, json=status if action == "status" else progress or {"lastacts": [], "progress": []})

    expected = _independent_hash(CONFIG["password"])
    respx.post(X).mock(side_effect=answer)
    return seen


def _independent_hash(password: str) -> str:
    """The exchange worked out once more, apart from the adapter, the way the live server took it."""
    first = hashlib.new("md5", (SALT["salt"] + password).encode("utf-8")).digest()
    stretched = hashlib.pbkdf2_hmac("sha256", first, SALT["salt"].encode("utf-8"), SALT["pbkdf2_rounds"])
    return hashlib.new("md5", (SALT["rnd"] + stretched.hex()).encode("utf-8")).hexdigest()


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_sign_in_sends_the_hash_and_never_the_password(ctx: Context) -> None:
    seen = server(rights=ADMIN_RIGHTS)
    assert await ADAPTER.test(CONFIG, ctx) == "UrBackup 2.5.37 answers; it knows 3 machine(s)."
    assert seen["salt"] == [{"username": "watcher"}]
    assert seen["login"][0]["password"] == _independent_hash(CONFIG["password"])
    assert all(CONFIG["password"] not in str(sent) for sent in seen["login"])
    assert seen["status"][0]["ses"] == SALT["ses"]


@respx.mock
async def test_the_session_is_kept_and_a_stale_one_renewed(ctx: Context) -> None:
    seen = server()
    await ADAPTER.fetch("clients", CONFIG, {}, ctx)
    await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert len(seen["login"]) == 1, "one sign-in for both cards"
    # ⚠️ Stale: 200 with error 1, and one more sign-in puts it right.
    held = ctx.cache["urbackup_session"]
    ctx.cache["urbackup_session"] = (held[0], "gone-stale", held[2])
    card = await ADAPTER.fetch("clients", CONFIG, {}, ctx)
    assert len(card.items) == 3 and len(seen["login"]) == 2


@respx.mock
async def test_refusals_at_the_door(ctx: Context) -> None:
    server()
    with pytest.raises(AuthFailed, match="rejected the password"):
        await ADAPTER.test({**CONFIG, "password": "wrong"}, ctx)


@respx.mock
async def test_an_unknown_name_and_a_locked_address_are_told_apart(ctx: Context) -> None:
    route = respx.post(X)
    route.mock(return_value=httpx.Response(200, json={"error": 0, "ses": "ZMblnC0nGp1UVu6clQbsLxvwJ6u0Re"}))
    with pytest.raises(AuthFailed, match="no user of that name"):
        await ADAPTER.test(CONFIG, ctx)
    # ⚠️ No salt either, but error 3: seen once, for some minutes, cause unknown.
    route.mock(return_value=httpx.Response(200, json={"error": 3, "ses": "tQ6qFSTRQneVWk3p8R7JWeFjIdoyaa"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "locked"


@respx.mock
async def test_without_accounts_the_door_is_open_and_with_one_it_is_shut(ctx: Context) -> None:
    route = respx.post(X)
    route.mock(side_effect=lambda request: httpx.Response(200, json={
        "login": {"api_version": 2, "lang": "en", "session": "open-door", "success": True}}.get(request.url.params["a"], STATUS)))
    assert (await ADAPTER.test({"url": UB}, ctx)).startswith("UrBackup 2.5.37")
    route.mock(return_value=httpx.Response(200, json={"admin_only": "admin", "api_version": 2, "lang": "en", "success": False}))
    with pytest.raises(AuthFailed, match="asks for sign-in"):
        await ADAPTER.test({"url": UB}, Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={}))


@respx.mock
async def test_a_user_without_the_status_right_is_not_an_empty_server(ctx: Context) -> None:
    # ⚠️ UrBackup answers such a user with an empty list.
    server(rights=NOBODY_RIGHTS, status={"status": []})
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("clients", CONFIG, {}, ctx)
    assert caught.value.code == "forbidden"
    with pytest.raises(AdapterError):
        await ADAPTER.fetch("activity", CONFIG, {}, ctx)


@respx.mock
async def test_machines_worst_first_and_images_only_where_they_count(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.urbackup.time.time", lambda: NOW)
    server(status={**STATUS, "status": [
        *CLIENTS,
        client(4, "old-desktop", file_ok=False, lastbackup=NOW - 86400 * 3, image_not_supported=False, lastbackup_image=NOW - 86400 * 9),
        client(5, "windows-pc", file_ok=True, lastbackup=NOW - 7200, image_not_supported=False),
    ]})
    card = await ADAPTER.fetch("clients", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row["status"]) for row in card.items] == [
        ("old-desktop", "File backup overdue · File backup 3 d ago · Image backup 9 d ago · Image backup overdue", "bad"),
        ("nas-box", "No folders chosen", "warn"),
        ("never-seen", "Never backed up · Offline", "warn"),
        ("laptop-office", "File backup 0 min ago", "ok"),
        # Never had an image, so a missing one is not held against it.
        ("windows-pc", "File backup 2 h ago", "ok"),
    ]
    expecting = await ADAPTER.fetch("clients", CONFIG, {"expect_images": True}, ctx)
    assert [row for row in expecting.items if row["title"] == "windows-pc"][0] == {
        "title": "windows-pc", "subtitle": "File backup 2 h ago · No image backup yet", "status": "warn"}


@respx.mock
async def test_the_overview_counts(ctx: Context) -> None:
    server()
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Backed up in time", "value": 1, "unit": "/ 3"}
    assert {row["part"]: row["value"] for row in card.secondary} == {"overdue": 0, "never": 2, "online": 2, "running": 0}
    assert card.status == "warn"


@respx.mock
async def test_backups_running_and_finished(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.urbackup.time.time", lambda: NOW)
    server(rights=ADMIN_RIGHTS, progress={
        "progress": [{"action": 2, "clientid": 1, "detail_pc": -1, "done_bytes": 0, "eta_ms": -44505, "name": "laptop-office", "pcdone": 0,
                      "speed_bpms": 0, "total_bytes": 20},
                     {"action": 1, "clientid": 2, "eta_ms": 300000, "name": "nas-box", "pcdone": 42, "speed_bpms": 2048}],
        "lastacts": [{"backuptime": NOW - 58, "clientid": 1, "del": False, "details": "", "duration": 1, "id": 1, "image": 0, "incremental": 0,
                      "name": "laptop-office", "restore": 0, "resumed": 0, "size_bytes": 20},
                     {"backuptime": NOW - 86400 * 40, "clientid": 2, "del": True, "image": 1, "incremental": 1, "name": "nas-box",
                      "restore": 0, "resumed": 0, "size_bytes": 3_000_000_000}]})
    card = await ADAPTER.fetch("activity", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"], row.get("value", "")) for row in card.items] == [
        # ⚠️ A negative time left means UrBackup cannot tell yet.
        ("laptop-office", "Full file backup · 0 %", ""),
        ("nas-box", "Incremental file backup · 42 % · 2.0 MB/s · 5 min left", ""),
        ("laptop-office", "Full file backup · 20 B", "0 min ago"),
        ("nas-box", "Incremental image backup · Deleted · 2.8 GB", "40 d ago"),
    ]
    assert card.items[1]["progress"] == 42.0 and card.items[3]["status"] == "unknown"


@respx.mock
async def test_a_user_who_sees_only_what_runs_is_told(ctx: Context) -> None:
    # ⚠️ No lastacts without an administrator's rights.
    server(progress={"progress": []})
    card = await ADAPTER.fetch("activity", CONFIG, {}, ctx)
    assert card.items == [] and card.meta["empty"] == "Nothing is running."
    assert card.meta["notice"] == "Finished backups are shown to an administrator only."


@respx.mock
async def test_a_web_page_is_not_urbackup(ctx: Context) -> None:
    respx.post(X).mock(return_value=httpx.Response(200, text="<html>router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_urbackup"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(4):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary
