"""TrueNAS: the current API over a WebSocket, the REST API behind it.

The answers are the shapes TrueNAS 25.10.7 gave on 18.09.2026. What matters
most here is where the key goes: a key that reaches the current API over
plain http is revoked by TrueNAS for good (issue #4).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, WidgetData, ago
from app.adapters.truenas import _smb_machine, _smb_opened, _version, _web_ui

KEY = "1-readonlykey"
INFO = {"version": "25.10.7", "hostname": "truenas", "uptime_seconds": 3600.5, "loadavg": [0.5, 0.3, 0.1], "physmem": 8_333_570_048, "cores": 4}
POOLS = [{"name": "tank", "status": "ONLINE", "healthy": True, "size": 16_642_998_272, "allocated": 2_711_552}]
ALERTS = [
    {"level": "WARNING", "dismissed": False, "datetime": {"$date": 1_789_712_345_000}, "formatted": "Pool tank is 91% full."},
    {"level": "CRITICAL", "dismissed": True, "datetime": {"$date": 1_789_700_000_000}, "formatted": "Dismissed, not shown."},
]
#: The same from before 25.04, where the REST API is the only one there is.
OLD_INFO = {**INFO, "version": "TrueNAS-SCALE-24.10.2"}
#: What a plain GET of /api/current, without a key, said on 25.10.7 on 21.09.2026.
NEEDS_UPGRADE = 'No WebSocket UPGRADE hdr: None\n Can "Upgrade" only to "WebSocket".'
#: The answers of the cards added for issue #49. Their shapes are read from the
#: middleware's source (release/25.10.0, api/v25_10_0), not measured: there
#: was no TrueNAS to ask when they were written.
UPDATE = {"code": "NORMAL", "status": {"current_version": {"train": "TrueNAS-SCALE-Goldeye", "profile": "GENERAL", "matches_profile": True},
                                       "new_version": {"version": "25.10.8", "manifest": {}, "release_notes": None, "release_notes_url": ""}},
          "error": None, "update_download_progress": None}
SUMMARY = {"ips": {"enp1s0": {"IPV4": ["192.168.1.20/24"], "IPV6": ["fe80::1/64"]}}, "default_routes": ["192.168.1.1"], "nameservers": ["192.168.1.1"]}
APPS = [
    {"name": "syncthing", "id": "syncthing", "state": "STOPPED", "upgrade_available": False, "latest_version": None, "image_updates_available": False,
     "human_version": "1.29.6_1.1.9", "version": "1.1.9", "portals": {}},
    {"name": "jellyfin", "id": "jellyfin", "state": "RUNNING", "upgrade_available": True, "latest_version": "1.2.4", "image_updates_available": False,
     "human_version": "10.10.7_1.2.3", "version": "1.2.3", "portals": {"Web UI": "http://192.168.1.20:30013/"}},
    {"name": "immich", "id": "immich", "state": "CRASHED", "upgrade_available": False, "latest_version": None, "image_updates_available": False,
     "human_version": "v1.132.3_1.6.1", "version": "1.6.1", "portals": {}},
    {"name": "custom-web", "id": "custom-web", "state": "RUNNING", "upgrade_available": False, "latest_version": None, "image_updates_available": True,
     "human_version": "1.0.0", "version": "1.0.0", "portals": {}},
]
DISKS = [
    {"name": "sdb", "model": "WDC WD140EFGX", "pool": "tank", "size": 14_000_519_643_136, "type": "HDD"},
    {"name": "nvme0n1", "model": "Samsung SSD 990 PRO 2TB", "pool": None, "size": 2_000_398_934_016, "type": "SSD"},
    {"name": "sda", "model": "WDC WD140EFGX", "pool": "tank", "size": 14_000_519_643_136, "type": "HDD"},
    {"name": "sdc", "model": "ST14000NM001G", "pool": "tank", "size": 14_000_519_643_136, "type": "HDD"},
]
#: 25.10 with thresholds: [temperature, critical]. sdc's own limit is 55.
TEMPERATURES = {"sda": [38.0, 65.0], "sdb": [52.0, None], "sdc": [56.0, 55.0], "nvme0n1": [71.0, 84.85]}
HOUR_AGO = {"$date": int((time.time() - 3600) * 1000)}
SNAPSHOT_TASKS = [{"id": 1, "dataset": "tank/photos", "enabled": True, "state": {"state": "FINISHED", "datetime": HOUR_AGO}},
                  {"id": 2, "dataset": "tank/old", "enabled": False, "state": {"state": "PENDING"}}]
REPLICATIONS = [{"id": 1, "name": "tank to backup-nas", "enabled": True, "state": {"state": "ERROR", "datetime": HOUR_AGO, "error": "No route to host."}, "job": None}]
CLOUD_SYNCS = [{"id": 1, "description": "Photos to B2", "path": "/mnt/tank/photos", "enabled": True, "locked": False,
                "job": {"state": "SUCCESS", "time_started": HOUR_AGO, "time_finished": HOUR_AGO, "error": None}}]
RSYNC_TASKS = [{"id": 1, "desc": "", "path": "/mnt/tank/documents", "enabled": True, "locked": False, "job": None}]
CLOUD_BACKUPS = [{"id": 1, "description": "Everything to Storj", "path": "/mnt/tank", "enabled": True, "locked": False,
                  "job": {"state": "FAILED", "time_finished": HOUR_AGO, "error": "Repository is locked."}}]
SERVICES = [
    {"id": 1, "service": "cifs", "enable": True, "state": "RUNNING", "pids": [100]},
    {"id": 2, "service": "nfs", "enable": True, "state": "STOPPED", "pids": []},
    {"id": 3, "service": "ssh", "enable": False, "state": "RUNNING", "pids": [200]},
    {"id": 4, "service": "ups", "enable": False, "state": "STOPPED", "pids": []},
]
VMS = [{"id": 1, "name": "homeassistant", "vcpus": 1, "cores": 2, "threads": 1, "memory": 4096, "status": {"state": "RUNNING", "pid": 42, "domain_state": "RUNNING"}},
       {"id": 2, "name": "windows", "vcpus": 4, "cores": 1, "threads": 1, "memory": 8192, "status": {"state": "STOPPED", "pid": None, "domain_state": "SHUTOFF"}}]
INSTANCES = [{"id": "pihole", "name": "pihole", "type": "CONTAINER", "status": "RUNNING", "cpu": "1", "memory": 536_870_912},
             {"id": "homeassistant", "name": "homeassistant", "type": "VM", "status": "RUNNING", "cpu": "2", "memory": 4_294_967_296}]


def smb_session(user: str, machine: str, socket: str, opened: str, session_id: str) -> dict[str, Any]:
    """One entry of ``smbstatus -jp`` as Samba writes it (``status_json.c``), not measured."""
    return {"session_id": session_id, "server_id": {"pid": "4242", "task_id": "0", "vnn": "4294967295", "unique_id": "8461929128395432"},
            "uid": 3000, "gid": 3000, "username": user, "groupname": "builtin_users", "creation_time": opened,
            "expiration_time": "30828-09-14T03:30:07.999999+01:00", "auth_time": opened, "remote_machine": machine,
            "hostname": socket, "session_dialect": "SMB3_11", "client_guid": "4ac46e2c-7c55-11ef-a6b3-0242ac120002",
            "encryption": {"cipher": "-", "degree": "none"}, "signing": {"cipher": "AES-128-GMAC", "degree": "partial"}, "channels": {}}


#: Two sessions from one Mac, one from a TV that gave no name, written with the
#: offset Samba gives Berlin in winter.
SMB_SESSIONS = [
    smb_session("alex", "alex-macbook", "ipv4:192.168.1.31:51547", "2026-11-17T14:55:00.123456+01:00", "11"),
    smb_session("media", "", "ipv4:192.168.1.40:40112", "2026-11-15T09:00:00.000000+01:00", "12"),
    smb_session("alex", "alex-macbook", "ipv4:192.168.1.31:51544", "2026-11-17T13:30:00.654321+01:00", "10"),
]


def smb_status(params: list[Any]) -> Any:
    """``smb.status`` answers the count with a number, the list with the sessions."""
    return len(SMB_SESSIONS) - 1 if params[2].get("count") else SMB_SESSIONS
ANSWERS = {
    "system.info": INFO, "pool.query": POOLS, "alert.list": ALERTS, "update.status": UPDATE, "network.general.summary": SUMMARY,
    "app.query": APPS, "disk.query": DISKS, "disk.temperatures": TEMPERATURES, "pool.snapshottask.query": SNAPSHOT_TASKS,
    "replication.query": REPLICATIONS, "cloudsync.query": CLOUD_SYNCS, "rsynctask.query": RSYNC_TASKS,
    "cloud_backup.query": CLOUD_BACKUPS, "service.query": SERVICES, "vm.query": VMS, "virt.instance.query": INSTANCES,
    # With {"count": True} TrueNAS' filter_list answers with the number alone.
    "smb.status": smb_status,
}
#: The first reporting.realtime event, as TrueNAS 25.10.7 sent it on 22.09.2026
#: 0.01 s after core.subscribe, to a read-only administrator's key. Idle, 8 GB,
#: no pool: 1.3 GB for the services, 3.8 GB of ZFS cache, 3.3 GB free.
REALTIME = {
    "cpu": {"cpu": {"usage": 3.0, "temp": None}, "cpu0": {"usage": 2.0}, "cpu1": {"usage": 5.0}},
    "memory": {"arc_size": 3_763_465_808, "arc_free_memory": 3_100_352_512, "arc_available_memory": 2_752_291_328,
               "physical_memory_total": 8_333_590_528, "physical_memory_available": 3_274_661_888},
    "disks": {}, "interfaces": {}, "pools": {}, "zfs": {},
}


class FakeTruenas:
    """A WebSocket that speaks JSON-RPC like TrueNAS, one per connection."""

    def __init__(self, key: str = KEY, refuse: dict[str, str] | None = None, realtime: dict[str, Any] | None = REALTIME,
                 unsubscribe: str | None = None, silent: set[str] | None = None) -> None:
        self.key = key
        self.refuse = refuse or {}
        #: None: the subscription is taken and no event ever comes.
        self.realtime = realtime
        #: An errname: the subscription is taken and then ended with it, as in TrueNAS' jsonrpc.rst.
        self.unsubscribe = unsubscribe
        #: Methods that are taken and never answered, like a NAS waiting on its update server.
        self.silent = silent or set()
        self.sent: list[dict[str, Any]] = []
        self.opened: list[str] = []
        self.closed = 0
        self._pending: list[str] = []
        self._authenticated = False

    async def open(self, url: str, config: dict[str, Any]) -> FakeTruenas:
        self.opened.append(url)
        self._authenticated = False
        return self

    async def send(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        method, number = message["method"], message["id"]
        # An event in between, as TrueNAS sends them, must not be taken for the answer.
        self._pending.append(json.dumps({"jsonrpc": "2.0", "method": "collection_update", "params": {}}))
        if method == "auth.login_with_api_key":
            self._authenticated = message["params"] == [self.key]
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "result": self._authenticated}))
        elif not self._authenticated:
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "error": {"code": -32001, "message": "Method call error", "data": {"errname": "ENOTAUTHENTICATED", "reason": "[ENOTAUTHENTICATED] Not authenticated"}}}))
        elif method == "core.subscribe" and "core.subscribe" not in self.refuse:
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "result": "e88dddb2-aea8-4e41-ba87-08323ffb8b29"}))
            # Another collection first: only the one asked for counts.
            self._pending.append(json.dumps({"jsonrpc": "2.0", "method": "collection_update", "params": {"msg": "changed", "collection": "alert.list", "fields": {}}}))
            if self.unsubscribe is not None:
                self._pending.append(json.dumps({"jsonrpc": "2.0", "method": "notify_unsubscribed", "params": {
                    "collection": message["params"][0],
                    "error": {"error": 13, "errname": self.unsubscribe, "reason": "Not authorized", "trace": None, "extra": []},
                }}))
            elif self.realtime is not None:
                self._pending.append(json.dumps({"jsonrpc": "2.0", "method": "collection_update",
                                                 "params": {"msg": "added", "collection": message["params"][0], "fields": self.realtime}}))
        elif method in self.silent:
            pass
        elif method in self.refuse:
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "error": {"code": -32001, "message": "Method call error", "data": {"errname": self.refuse[method], "reason": "Not permitted"}}}))
        else:
            answer = ANSWERS[method]
            self._pending.append(json.dumps({"jsonrpc": "2.0", "id": number, "result": answer(message["params"]) if callable(answer) else answer}))

    async def recv(self) -> str:
        if not self._pending:
            # A subscription that never sends: wait like a quiet socket.
            await asyncio.sleep(3600)
        return self._pending.pop(0)

    async def close(self) -> None:
        self.closed += 1

    def methods(self) -> list[str]:
        return [message["method"] for message in self.sent]


def turned_down(status: int):
    async def open_socket(url: str, config: dict[str, Any]) -> Any:
        raise InvalidStatus(Response(status, "Not Found", Headers()))

    return open_socket


def current_api(address: str, status: int) -> respx.Route:
    """The keyless look at /api/current: 400 on a TrueNAS that has it, 404 on one that has not."""
    return respx.get(f"{address}/api/current").mock(return_value=httpx.Response(status, text=NEEDS_UPGRADE if status == 400 else "404 page not found"))


async def no_socket(url: str, config: dict[str, Any]) -> Any:
    raise AssertionError(f"a WebSocket was opened to {url}; over http that revokes the key")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def truenas(monkeypatch: pytest.MonkeyPatch):
    # ⚠️ Set when the test runs, not when the module is collected: a full run
    # can reach this file more than an hour after collecting it.
    HOUR_AGO["$date"] = int((time.time() - 3600) * 1000)
    adapter = get_adapter("truenas")
    fake = FakeTruenas()
    monkeypatch.setattr(adapter, "_open_socket", fake.open)
    return adapter, fake


async def test_https_reads_everything_through_the_current_api(ctx: Context, truenas) -> None:
    """A read-only administrator's key gets 403 from the REST API on 25.10 and
    everything from the current API."""
    adapter, fake = truenas
    config = {"url": "https://truenas.example.com/", "api_key": KEY}

    assert await adapter.test(config, ctx) == "TrueNAS 25.10.7 on truenas answers."
    assert fake.opened == ["wss://truenas.example.com/api/current"]

    fake.sent.clear()
    system = await adapter.fetch("system", config, {}, ctx)
    # One connection for what the card shows each time, a second one for the
    # waiting update, which is asked every six hours only.
    assert fake.methods() == ["auth.login_with_api_key", "system.info", "alert.list", "core.subscribe", "auth.login_with_api_key", "update.status"]
    assert fake.sent[3]["params"] == ["reporting.realtime"]
    assert system.primary == {"label": "CPU", "value": 3.0, "unit": "%"}
    assert [entry["value"] for entry in system.secondary if entry["label"] == "Alerts"] == [1]
    assert system.status == "warn"

    pools = await adapter.fetch("pools", config, {}, ctx)
    assert [(item["title"], item["status"]) for item in pools.items] == [("tank", "ok")]

    alerts = await adapter.fetch("alerts", config, {}, ctx)
    assert [(item["title"], item["subtitle"]) for item in alerts.items] == [("Pool tank is 91% full.", "2026-09-18")], "a day, not the first ten digits of a timestamp"
    assert fake.closed == len(fake.opened), "every connection is closed again"


async def test_cards_share_what_was_just_read(ctx: Context, truenas) -> None:
    adapter, fake = truenas
    config = {"url": "https://truenas.example.com", "api_key": KEY}
    await adapter.fetch("system", config, {}, ctx)
    opened = len(fake.opened)
    await adapter.fetch("alerts", config, {}, ctx)
    assert len(fake.opened) == opened, "the alerts were read a moment ago by the system card"


async def test_a_refused_key_says_so_and_does_not_try_the_rest_api(ctx: Context, truenas) -> None:
    adapter, fake = truenas
    config = {"url": "https://truenas.example.com", "api_key": "1-wrong"}
    with respx.mock(assert_all_called=False) as router:
        rest = router.get(url__regex=r".*/api/v2\.0/.*").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(AdapterError) as refused:
            await adapter.test(config, ctx)
    assert refused.value.code == "auth_failed"
    assert "revokes" in refused.value.hint
    assert fake.methods() == ["auth.login_with_api_key"]
    assert not rest.called


async def test_a_method_the_role_may_not_call_names_the_role(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("truenas")
    fake = FakeTruenas(refuse={"pool.query": "EACCES"})
    monkeypatch.setattr(adapter, "_open_socket", fake.open)
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("pools", {"url": "https://truenas.example.com", "api_key": KEY}, {}, ctx)
    assert refused.value.code == "auth_failed"
    assert "Read-Only Administrator" in refused.value.hint


@respx.mock
async def test_http_never_opens_the_websocket_and_says_why_it_is_refused(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """TrueNAS revoked a key for good after one login over ws:// (measured).
    Over http the REST API is the only safe way, and on 25.10 it refuses a
    read-only key; the message has to say what to change."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    current_api("http://truenas.example.com", 404)
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(403))
    with pytest.raises(AdapterError) as refused:
        await adapter.test({"url": "http://truenas.example.com", "api_key": KEY}, ctx)
    assert refused.value.code == "auth_failed"
    assert "https://" in refused.value.hint


@respx.mock
async def test_http_with_a_full_key_keeps_working_over_rest(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a TrueNAS from before 25.04, which has no other API."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    current_api("http://truenas.example.com", 404)
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=OLD_INFO))
    respx.get("http://truenas.example.com/api/v2.0/pool").mock(return_value=httpx.Response(200, json=POOLS))
    pools = await adapter.fetch("pools", {"url": "http://truenas.example.com", "api_key": "2-full"}, {}, ctx)
    assert [item["title"] for item in pools.items] == ["tank"]
    assert respx.calls.last.request.headers["Authorization"] == "Bearer 2-full"


@respx.mock
async def test_rest_is_refused_where_truenas_has_deprecated_it(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ A full administrator's key over http reaches the REST API on 25.10 and
    gets its answers. That it works is the trouble. Measured on 25.10.7: every
    call that signs in is counted, and one alert on the NAS names the count of
    the last 24 hours. It only goes away at no call at all, so not even the
    version may be asked over REST. A plain GET of /api/current, without the
    key, tells a TrueNAS that has the current API, once an hour."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    look = current_api("http://truenas.example.com", 400)
    rest = respx.get(url__startswith="http://truenas.example.com/api/v2.0/").mock(return_value=httpx.Response(200, json=INFO))
    config = {"url": "http://truenas.example.com", "api_key": "2-full"}
    started = time.monotonic()
    for minutes, kind in enumerate(("pools", "system", "alerts")):
        # Five minutes apart: past every short cache, well inside the hour.
        # Asked in the same second, the second call never leaves the request
        # cache, and this passed with nothing remembered at all.
        monkeypatch.setattr(time, "monotonic", lambda minutes=minutes: started + 300 * minutes)
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch(kind, config, {}, ctx)
        assert refused.value.code == "deprecated_api"
        assert "Change the URL to https://" in refused.value.hint
    assert not rest.called, "one call over REST is one too many: it keeps the alert alive"
    assert look.call_count == 1, "asked once an hour, not once a card"
    assert "authorization" not in look.calls.last.request.headers, "the key stays at home for this"


@respx.mock
async def test_a_proxy_that_says_404_is_caught_by_the_version(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second line. Something in front says 404 for /api/current, so the
    REST API is asked, and what it says its version is settles it: once an
    hour, and nothing else goes there."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    current_api("http://truenas.example.com", 404)
    info = respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json={**INFO, "version": "25.10.1"}))
    pools = respx.get("http://truenas.example.com/api/v2.0/pool").mock(return_value=httpx.Response(200, json=POOLS))
    alerts = respx.get("http://truenas.example.com/api/v2.0/alert/list").mock(return_value=httpx.Response(200, json=ALERTS))
    config = {"url": "http://truenas.example.com", "api_key": "2-full"}
    started = time.monotonic()
    for minutes, kind in enumerate(("pools", "system", "alerts")):
        monkeypatch.setattr(time, "monotonic", lambda minutes=minutes: started + 300 * minutes)
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch(kind, config, {}, ctx)
        assert refused.value.code == "deprecated_api"
        assert "25.10.1" in refused.value.message
    assert info.call_count == 1, "the version is asked once an hour, not once a card"
    assert not pools.called and not alerts.called


@respx.mock
async def test_the_system_card_of_an_older_truenas_keeps_moving(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ The version comes from ``system/info``, and so do load and uptime. A
    first take kept that whole answer for the hour and handed it to the card:
    two minutes later the load had quadrupled and the card still said 12.5 %,
    on exactly the versions that were to notice nothing."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    current_api("http://truenas.example.com", 404)
    respx.get("http://truenas.example.com/api/v2.0/alert/list").mock(return_value=httpx.Response(200, json=[]))
    info = respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=OLD_INFO))
    config = {"url": "http://truenas.example.com", "api_key": "2-full"}
    assert (await adapter.fetch("system", config, {}, ctx)).primary["value"] == 12.5
    started = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: started + 120)
    info.mock(return_value=httpx.Response(200, json={**OLD_INFO, "loadavg": [2.0, 1.0, 0.5]}))
    assert (await adapter.fetch("system", config, {}, ctx)).primary["value"] == 50.0


@respx.mock
async def test_behind_a_proxy_the_refusal_names_the_proxy_not_the_address(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """The address is https:// already. What has to change is the proxy that
    does not pass the WebSocket on, and the handshake's status says so."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", turned_down(502))
    current_api("https://truenas.example.com", 400)
    rest = respx.get(url__startswith="https://truenas.example.com/api/v2.0/").mock(return_value=httpx.Response(200, json=INFO))
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("pools", {"url": "https://truenas.example.com", "api_key": "2-full"}, {}, ctx)
    assert not rest.called, "the look without the key was enough; nothing went over REST"
    assert refused.value.code == "deprecated_api"
    assert "HTTP 502" in refused.value.message
    assert "reverse proxy" in refused.value.hint
    assert "https://" not in refused.value.hint


@respx.mock
async def test_a_404_in_front_of_a_current_truenas_is_not_remembered_as_an_old_one(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """404 stands for a TrueNAS without the current API, for an hour. A proxy
    can say 404 as well; the version then shows it is no old TrueNAS, and the
    WebSocket has to be tried again once the proxy is mended."""
    adapter = get_adapter("truenas")
    attempts: list[str] = []

    async def gone(url: str, config: dict[str, Any]) -> Any:
        attempts.append(url)
        return await turned_down(404)(url, config)

    monkeypatch.setattr(adapter, "_open_socket", gone)
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=INFO))
    config = {"url": "https://truenas.example.com", "api_key": "2-full"}
    for _ in range(2):
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch("pools", config, {}, ctx)
        assert "reverse proxy" in refused.value.hint
    assert len(attempts) == 2


# -- TrueNAS 24.10 (issue #75) ---------------------------------------------------------------------------------------
# Its nginx has no location for /api/current, and `location /` answers every unknown path with a 302 to /ui/
# (nginx.conf.mako of TS-24.10.2.4). That is its 404.

INFO_2410 = {**INFO, "version": "TrueNAS-SCALE-24.10.2.4"}


def to_the_web_ui(status: int = 302):
    async def open_socket(url: str, config: dict[str, Any]) -> Any:
        raise InvalidStatus(Response(status, "Moved Temporarily", Headers({"Location": "https://truenas.example.com/ui/"})))

    return open_socket


@respx.mock
async def test_truenas_2410_over_https_is_read_over_rest(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """The handshake is sent to the login page; that says "no current API" as a 404 would, for the hour."""
    adapter = get_adapter("truenas")
    attempts: list[str] = []

    async def gone(url: str, config: dict[str, Any]) -> Any:
        attempts.append(url)
        return await to_the_web_ui()(url, config)

    monkeypatch.setattr(adapter, "_open_socket", gone)
    look = respx.get("https://truenas.example.com/api/current").mock(
        return_value=httpx.Response(302, headers={"Location": "https://truenas.example.com/ui/"}))
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=INFO_2410))
    respx.get("https://truenas.example.com/api/v2.0/pool").mock(return_value=httpx.Response(200, json=[]))
    config = {"url": "https://truenas.example.com", "api_key": "2-full"}
    assert await adapter.test(config, ctx) == "TrueNAS TrueNAS-SCALE-24.10.2.4 on truenas answers."
    await adapter.fetch("pools", config, {}, ctx)
    assert len(attempts) == 1, "remembered as a TrueNAS without the current API for the hour"
    assert not look.called, "the refused handshake said it already"


async def _redirecting_server(location: str):
    """A plain HTTP server that answers every request, the WebSocket handshake too, as TrueNAS 24.10's nginx does."""

    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(f"HTTP/1.1 302 Moved Temporarily\r\nServer: nginx\r\nLocation: {location}\r\n"
                     "Content-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        writer.close()

    return await asyncio.start_server(answer, "127.0.0.1", 0)


@respx.mock
async def test_truenas_2410_is_read_over_rest_through_the_real_websocket_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """websockets follows a redirect itself and cannot follow one to https://: that read as "could not be reached".

    The handshake goes to a real server here; only TLS is left out. What the reporter of #75 measured on 24.10.2.4
    behind 1.9.1: 302 with ``Location: https://<address>/ui/``.
    """
    adapter = get_adapter("truenas")
    server = await _redirecting_server("https://truenas.example.com:444/ui/")
    port = server.sockets[0].getsockname()[1]
    real_open = type(adapter)._open_socket
    opened: list[str] = []

    async def without_tls(url: str, config: dict[str, Any]) -> Any:
        opened.append(url)
        assert url == "wss://truenas.example.com:444/api/current"
        return await real_open(adapter, f"ws://127.0.0.1:{port}/api/current", {**config, "insecure": False})

    monkeypatch.setattr(adapter, "_open_socket", without_tls)
    respx.get("https://truenas.example.com:444/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=INFO_2410))
    look = respx.get("https://truenas.example.com:444/api/current")
    async with server:
        assert await adapter.test({"url": "https://truenas.example.com:444", "api_key": "2-full"}, ctx) == \
            "TrueNAS TrueNAS-SCALE-24.10.2.4 on truenas answers."
    assert opened == ["wss://truenas.example.com:444/api/current"]
    assert not look.called, "the refused handshake said it already"


async def test_the_websocket_client_hands_a_redirect_back_instead_of_following_it() -> None:
    server = await _redirecting_server("/ui/")
    port = server.sockets[0].getsockname()[1]
    async with server:
        with pytest.raises(InvalidStatus) as refused:
            await get_adapter("truenas")._open_socket(f"ws://127.0.0.1:{port}/api/current", {"insecure": False})
    assert refused.value.response.status_code == 302
    assert refused.value.response.headers["Location"] == "/ui/"


@respx.mock
async def test_truenas_2410_over_http_is_read_over_rest_when_the_client_follows_the_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """nexdeck's own client follows redirects, so the keyless look ends on the login page with 200."""
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", no_socket)
    respx.get("http://truenas.example.com/api/current").mock(
        return_value=httpx.Response(302, headers={"Location": "http://truenas.example.com/ui/"}))
    respx.get("http://truenas.example.com/ui/").mock(return_value=httpx.Response(200, text="<!doctype html><title>TrueNAS</title>"))
    respx.get("http://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=INFO_2410))
    following = Context(httpx.AsyncClient(follow_redirects=True), integration_id=1, widget_id=1, cache={})
    assert await adapter.test({"url": "http://truenas.example.com", "api_key": "2-full"}, following) ==         "TrueNAS TrueNAS-SCALE-24.10.2.4 on truenas answers."


@respx.mock
async def test_a_redirect_somewhere_else_is_no_sign_of_an_old_truenas(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sign-in page in front of TrueNAS also redirects. Only TrueNAS' own web interface stands for a 404."""
    adapter = get_adapter("truenas")

    async def to_sign_in(url: str, config: dict[str, Any]) -> Any:
        raise InvalidStatus(Response(302, "Found", Headers({"Location": "https://auth.example.com/login?next=/api/current"})))

    monkeypatch.setattr(adapter, "_open_socket", to_sign_in)
    respx.get("https://truenas.example.com/api/current").mock(
        return_value=httpx.Response(302, headers={"Location": "https://auth.example.com/login"}))
    respx.get("https://auth.example.com/login").mock(return_value=httpx.Response(200, text="<!doctype html><title>Sign in</title>"))
    rest = respx.get(url__startswith="https://truenas.example.com/api/v2.0/").mock(return_value=httpx.Response(200, json=INFO_2410))
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("pools", {"url": "https://truenas.example.com", "api_key": "2-full"}, {}, ctx)
    assert refused.value.code == "deprecated_api"
    assert not rest.called


@pytest.mark.parametrize(("location", "expected"), [
    ("/ui/", True),
    ("/ui", True),
    ("https://truenas.example.com/ui/", True),
    ("http://10.0.0.20:81/ui/dashboard", True),
    ("/uix/", False),
    ("/api/current", False),
    ("https://auth.example.com/login?next=/ui/", False),
    ("", False),
])
def test_the_web_ui_is_told_from_other_redirects(location: str, expected: bool) -> None:
    assert _web_ui(location) is expected


@pytest.mark.parametrize(("label", "expected"), [
    ("25.10.1", (25, 10)),
    ("25.04.0", (25, 4)),
    ("TrueNAS-SCALE-24.10.2", (24, 10)),
    ("TrueNAS-13.0-U6.1", (13, 0)),
    ("", (0, 0)),
    ("MASTER", (0, 0)),
])
def test_the_version_is_read_from_every_way_truenas_writes_it(label: str, expected: tuple[int, int]) -> None:
    assert _version(label) == expected


async def test_the_websocket_path_refuses_http_on_its_own(truenas) -> None:
    """The last line in front of a revoked key does not rely on the caller."""
    adapter, fake = truenas
    with pytest.raises(AdapterError):
        await adapter._rpc({"url": "http://truenas.example.com", "api_key": KEY}, ["system.info"])
    assert fake.opened == []


@respx.mock
async def test_an_older_truenas_without_the_current_api_falls_back_to_rest(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("truenas")
    attempts: list[str] = []

    async def gone(url: str, config: dict[str, Any]) -> Any:
        attempts.append(url)
        return await turned_down(404)(url, config)

    monkeypatch.setattr(adapter, "_open_socket", gone)
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json={**INFO, "version": "TrueNAS-SCALE-24.10.2"}))
    config = {"url": "https://truenas.example.com", "api_key": KEY}
    assert await adapter.test(config, ctx) == "TrueNAS TrueNAS-SCALE-24.10.2 on truenas answers."
    assert await adapter.test(config, ctx) == "TrueNAS TrueNAS-SCALE-24.10.2 on truenas answers."
    assert len(attempts) == 1, "a TrueNAS without the current API is not asked again within the hour"


@respx.mock
async def test_a_proxy_without_websockets_is_named_when_rest_refuses_too(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", turned_down(400))
    current_api("https://truenas.example.com", 404)
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(403))
    with pytest.raises(AdapterError) as refused:
        await adapter.test({"url": "https://truenas.example.com", "api_key": KEY}, ctx)
    assert "HTTP 400" in refused.value.message
    assert "reverse proxy" in refused.value.hint


async def test_the_system_card_shows_what_the_services_use_not_the_zfs_cache(ctx: Context, truenas) -> None:
    """Measured on 25.10.7: 8.3 GB, 3.3 GB free, 3.8 GB ZFS cache. Taken and
    free alone would read 61 per cent on an idle NAS; the cache is handed back
    when asked, so TrueNAS' own dashboard counts it apart, and so does the card."""
    adapter, _fake = truenas
    system = await adapter.fetch("system", {"url": "https://truenas.example.com", "api_key": KEY}, {}, ctx)
    chips = {entry["label"]: entry["value"] for entry in system.secondary}
    assert chips["Memory"] == "1.2 GB of 7.8 GB"
    assert chips["ZFS cache"] == "3.5 GB"
    assert system.metrics == {"cpu": 3.0, "memory": 15.5}
    # The rows view draws a line beside a row only when the row names its metric.
    assert next(entry for entry in system.secondary if entry["label"] == "Memory")["metric"] == "memory"


async def test_without_a_realtime_event_the_load_average_stands_in(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """A subscription refused, or one that stays silent, costs the card its
    CPU figure and nothing else."""
    import app.adapters.truenas as module

    adapter = get_adapter("truenas")
    config = {"url": "https://truenas.example.com", "api_key": KEY}
    cases = (
        (FakeTruenas(refuse={"core.subscribe": "EACCES"}), module.REALTIME_WAIT),
        # Taken, then ended: as much an answer as a refusal.
        (FakeTruenas(unsubscribe="EACCES"), module.REALTIME_WAIT),
        (FakeTruenas(realtime=None), 0.05),
    )
    for fake, wait in cases:
        monkeypatch.setattr(module, "REALTIME_WAIT", wait)
        monkeypatch.setattr(adapter, "_open_socket", fake.open)
        quiet = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
        started = time.monotonic()
        system = await adapter.fetch("system", config, {}, quiet)
        # A refusal is an answer: no waiting out the full five seconds for an event.
        assert time.monotonic() - started < 1.0
        assert system.primary == {"label": "Load", "value": 12.5, "unit": "%"}
        assert system.metrics == {"load": 12.5}
        assert fake.closed == len(fake.opened)


# -- the cards added for issue #49 -------------------------------------------

HTTPS = {"url": "https://truenas.example.com", "api_key": KEY}


def fake_on(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> tuple[Any, FakeTruenas]:
    adapter = get_adapter("truenas")
    fake = FakeTruenas(**kwargs)
    monkeypatch.setattr(adapter, "_open_socket", fake.open)
    return adapter, fake


def fresh() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def later(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Move the adapter's clock on, so a kept answer has to earn being kept."""
    import types

    import app.adapters.truenas as module

    monkeypatch.setattr(module, "time", types.SimpleNamespace(monotonic=lambda: time.monotonic() + seconds, time=time.time))


def params_of(fake: FakeTruenas, method: str) -> list[Any]:
    return next(message["params"] for message in fake.sent if message["method"] == method)


async def test_the_system_card_names_a_waiting_update_and_asks_for_it_rarely(ctx: Context, truenas, monkeypatch: pytest.MonkeyPatch) -> None:
    """update.status sends TrueNAS to its update server on every call (its source, 25.10)."""
    adapter, fake = truenas
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert {"label": "Update available", "value": "25.10.8", "part": "update"} in system.secondary
    fake.sent.clear()
    later(monkeypatch, 3 * 3600)
    await adapter.fetch("system", HTTPS, {}, ctx)
    assert "system.info" in fake.methods() and "update.status" not in fake.methods(), "kept for hours, not asked on every refresh"
    fake.sent.clear()
    hidden = await adapter.fetch("system", HTTPS, {"show_update": False}, fresh())
    assert "update.status" not in fake.methods(), "a hidden chip costs TrueNAS nothing"
    assert all(entry["label"] != "Update available" for entry in hidden.secondary)


async def test_a_failed_update_check_leaves_the_card_alone_and_is_not_repeated(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = fake_on(monkeypatch, refuse={"update.status": "ENETUNREACH"})
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert system.primary == {"label": "CPU", "value": 3.0, "unit": "%"}
    assert all(entry["label"] != "Update available" for entry in system.secondary)
    fake.sent.clear()
    later(monkeypatch, 3600)
    await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.status" not in fake.methods(), "a NAS without internet is not sent to its update server every 30 seconds"


async def test_truenas_25_04_is_asked_with_its_own_update_method(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "25.04.2.4"})
    monkeypatch.setitem(ANSWERS, "update.check_available", {"status": "REBOOT_REQUIRED"})
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.check_available" in fake.methods() and "update.status" not in fake.methods()
    assert {"label": "Update available", "value": "Reboot required", "part": "update"} in system.secondary


@pytest.mark.parametrize(("answer", "expected"), [
    (UPDATE, "25.10.8"),
    ({**UPDATE, "status": {**UPDATE["status"], "new_version": None}}, ""),
    ({"code": "ERROR", "status": None, "error": {"errname": "EREBOOTREQUIRED", "reason": "Reboot"}}, "Reboot required"),
    ({"code": "ERROR", "status": None, "error": {"errname": "ENETUNREACH", "reason": "No network"}}, ""),
    ({"status": "AVAILABLE", "version": "25.04.2.5"}, "25.04.2.5"),
    ({"status": "UNAVAILABLE"}, ""),
    (None, ""),
])
def test_both_update_answers_are_read(answer: Any, expected: str) -> None:
    from app.adapters.truenas import _waiting_update

    assert _waiting_update(answer) == expected


async def test_the_pool_card_shows_the_last_scrub_and_its_errors(ctx: Context, truenas, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, _fake = truenas
    two_days = {"$date": int((time.time() - 2 * 86400 - 60) * 1000)}
    monkeypatch.setitem(ANSWERS, "pool.query", [
        {**POOLS[0], "scan": {"function": "SCRUB", "state": "FINISHED", "end_time": two_days, "errors": 0}},
        {**POOLS[0], "name": "fast", "scan": {"function": "SCRUB", "state": "FINISHED", "end_time": two_days, "errors": 3}},
        {**POOLS[0], "name": "slow", "scan": {"function": "RESILVER", "state": "SCANNING", "percentage": 41.7, "errors": 0}},
        {**POOLS[0], "name": "new", "scan": None},
    ])
    pools = {item["title"]: item for item in (await adapter.fetch("pools", HTTPS, {}, ctx)).items}
    assert pools["tank"]["subtitle"].endswith("ONLINE · Scrub 2 d ago")
    assert (pools["tank"]["status"], pools["fast"]["status"]) == ("ok", "warn"), "a scrub that repaired something is worth a look"
    assert pools["fast"]["subtitle"].endswith("Scrub 2 d ago, 3 errors")
    assert pools["slow"]["subtitle"].endswith("Resilver 42%")
    assert pools["new"]["subtitle"].endswith("ONLINE")


async def test_the_interfaces_come_from_the_event_the_system_card_reads_anyway(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    live = {**REALTIME, "interfaces": {
        "enp1s0": {"link_state": "LINK_STATE_UP", "speed": 1000, "received_bytes_rate": 1_250_000.0, "sent_bytes_rate": 250_000.0},
        "enp2s0": {"link_state": "LINK_STATE_DOWN", "speed": 0, "received_bytes": 0, "sent_bytes": 0, "received_bytes_rate": 0, "sent_bytes_rate": 0},
    }}
    adapter, fake = fake_on(monkeypatch, realtime=live)
    card = await adapter.fetch("interfaces", HTTPS, {}, ctx)
    assert fake.methods() == ["auth.login_with_api_key", "core.subscribe", "network.general.summary"]
    up, down = card.items
    assert up == {"title": "enp1s0", "subtitle": "192.168.1.20/24 · 1000 Mbit/s", "value": "↓ 1.2 MB/s ↑ 244.1 KB/s", "status": "ok"}
    assert (down["status"], down["subtitle"], down["value"]) == ("unknown", "No link", ""), "a port without a cable is grey, not red"
    assert card.metrics == {"down": 1_250_000.0, "up": 250_000.0}
    assert [(row["metric"], row["value"]) for row in card.secondary] == [("down", "1.2 MB/s"), ("up", "244.1 KB/s")]

    fake.sent.clear()
    later(monkeypatch, 60)
    await adapter.fetch("interfaces", HTTPS, {}, ctx)
    assert "network.general.summary" not in fake.methods(), "the addresses are kept for five minutes"
    assert "core.subscribe" in fake.methods(), "the traffic is not"


async def test_an_interface_card_without_live_figures_says_so(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, _fake = fake_on(monkeypatch, unsubscribe="EACCES")
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("interfaces", HTTPS, {}, ctx)
    assert refused.value.code == "no_realtime"
    adapter, _fake = fake_on(monkeypatch)
    with pytest.raises(AdapterError) as empty:
        await adapter.fetch("interfaces", HTTPS, {}, fresh())
    assert empty.value.code == "no_interfaces", "an empty card would hide that TrueNAS sent none"


async def test_the_apps_that_need_somebody_come_first(ctx: Context, truenas) -> None:
    adapter, _fake = truenas
    card = await adapter.fetch("apps", HTTPS, {}, ctx)
    assert [(item["title"], item["status"], item["value"]) for item in card.items] == [
        ("immich", "bad", ""), ("custom-web", "warn", "Update available"), ("jellyfin", "warn", "Update available"), ("syncthing", "unknown", ""),
    ]
    jellyfin = card.items[2]
    assert jellyfin["subtitle"] == "10.10.7_1.2.3 · Running"
    assert jellyfin["url"] == "http://192.168.1.20:30013/"
    assert (jellyfin["update"], card.items[1]["update"]) == ("1.2.4", "image")
    assert "url" not in card.items[0], "no link where the app offers none"
    assert card.status == "bad"
    assert card.secondary == [{"label": "Running", "value": 2}, {"label": "Updates", "value": 2}]


async def test_the_disk_temperatures_are_asked_the_way_each_version_takes_them(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = fake_on(monkeypatch)
    card = await adapter.fetch("disks", HTTPS, {}, ctx)
    assert params_of(fake, "disk.temperatures") == [[], True]
    assert params_of(fake, "disk.query") == [[], {"extra": {"pools": True}}], "without it disk.query leaves the pool out"
    assert [(item["title"], item["value"], item["status"]) for item in card.items] == [
        ("sda", "38 °C", "ok"), ("sdb", "52 °C", "warn"), ("sdc", "56 °C", "bad"), ("nvme0n1", "71 °C", "warn"),
    ], "sdc's own limit of 55 counts; flash may run warmer than a spinning disk"
    assert card.items[0]["subtitle"] == "WDC WD140EFGX · tank · 12.7 TB"
    assert card.status == "bad"
    assert card.metrics == {"temperature": 71.0}

    fake.sent.clear()
    later(monkeypatch, 240)
    await adapter.fetch("disks", HTTPS, {}, ctx)
    assert "disk.query" not in fake.methods() and "system.info" in fake.methods()
    assert "disk.temperatures" not in fake.methods(), "every reading sends a command to the disk; five minutes apart at most"

    monkeypatch.undo()
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "25.04.2.4"})
    monkeypatch.setitem(ANSWERS, "disk.temperatures", {"sda": 38, "sdb": None, "sdc": None, "nvme0n1": 40})
    card = await adapter.fetch("disks", HTTPS, {}, fresh())
    assert params_of(fake, "disk.temperatures") == [[], {"powermode": "STANDBY"}], "25.04 leaves a sleeping disk alone only when told"
    assert [(item["title"], item["value"], item["status"]) for item in card.items][:2] == [("sda", "38 °C", "ok"), ("sdb", "", "unknown")]


async def test_data_protection_shows_every_kind_of_task_and_why_one_failed(ctx: Context, truenas) -> None:
    adapter, _fake = truenas
    card = await adapter.fetch("protection", HTTPS, {}, ctx)
    rows = {item["title"]: item for item in card.items}
    assert [item["status"] for item in card.items][:2] == ["bad", "bad"], "failed ones first"
    assert rows["tank to backup-nas"]["subtitle"] == "Replication · No route to host."
    assert rows["Everything to Storj"]["subtitle"] == "Cloud backup · Repository is locked."
    assert (rows["tank/photos"]["subtitle"], rows["tank/photos"]["value"], rows["tank/photos"]["status"]) == ("Snapshots · Finished", "1 h", "ok")
    assert (rows["tank/old"]["subtitle"], rows["tank/old"]["status"]) == ("Snapshots · Off", "unknown")
    assert rows["Photos to B2"]["subtitle"] == "Cloud sync · Finished"
    assert (rows["/mnt/tank/documents"]["subtitle"], rows["/mnt/tank/documents"]["value"]) == ("Rsync · Never ran", ""), "an rsync task without a description goes by its path"
    assert card.secondary == [{"label": "Tasks", "value": 6}, {"label": "Failed", "value": 2}]


async def test_data_protection_reads_only_the_kinds_that_are_shown(ctx: Context, truenas) -> None:
    adapter, fake = truenas
    card = await adapter.fetch("protection", HTTPS, {"show_cloud_backup": False, "show_rsync": False}, ctx)
    assert "cloud_backup.query" not in fake.methods() and "rsynctask.query" not in fake.methods()
    assert all(not item["id"].startswith(("cloud_backup", "rsynctask")) for item in card.items)


async def test_a_task_kind_this_truenas_lacks_leaves_the_others(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, _fake = fake_on(monkeypatch, refuse={"cloud_backup.query": "ENOMETHOD"})
    card = await adapter.fetch("protection", HTTPS, {}, ctx)
    assert len(card.items) == 5
    for method in ("replication.query", "cloud_backup.query"):
        adapter, _fake = fake_on(monkeypatch, refuse={method: "EACCES"})
        with pytest.raises(AdapterError) as refused:
            await adapter.fetch("protection", HTTPS, {}, fresh())
        assert refused.value.code == "auth_failed", f"a missing role for {method} is said, not hidden as an empty kind"


async def test_the_services_card_shows_what_is_meant_to_run(ctx: Context, truenas) -> None:
    adapter, _fake = truenas
    card = await adapter.fetch("services", HTTPS, {}, ctx)
    assert [(item["title"], item["value"], item["status"]) for item in card.items] == [
        ("NFS", "Stopped", "bad"), ("SMB", "Running", "ok"), ("SSH", "Running", "ok"),
    ], "set to start and stopped is red; running without being set to start still shows"
    every = await adapter.fetch("services", HTTPS, {"all_services": True}, ctx)
    assert ("UPS", "Stopped", "unknown") in [(item["title"], item["value"], item["status"]) for item in every.items]


def sessions_of(card: WidgetData) -> Any:
    return next((entry["value"] for entry in card.secondary if entry.get("part") == "smb_sessions"), None)


@pytest.mark.parametrize("version", ["25.04.2.4", "26.0.0", "TrueNAS-27.0.0"])
async def test_the_services_card_counts_the_open_smb_sessions(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #73: whether anybody is connected, counted as TrueNAS counts its own clients."""
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": version})
    card = await adapter.fetch("services", HTTPS, {}, fresh())
    assert params_of(fake, "smb.status") == ["SESSIONS", [], {"count": True}, {"fast": True}]
    assert card.secondary == [{"label": "SMB sessions", "value": 2, "part": "smb_sessions"}]
    assert card.status == "bad", "the stopped NFS still colours the card; the count does not"
    monkeypatch.setitem(ANSWERS, "smb.status", 0)
    assert sessions_of(await adapter.fetch("services", HTTPS, {}, fresh())) == 0, "nobody connected is said, not left out"


@pytest.mark.parametrize("version", ["25.10.7", "25.10.2.1", "", "TrueNAS-SCALE-24.10.2"])
async def test_smb_sessions_are_not_asked_where_the_method_is_private(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """25.10 refuses a read-only key, and logs every call from a full key; an unknown version may be 25.10."""
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": version})
    card = await adapter.fetch("services", HTTPS, {}, fresh())
    assert "smb.status" not in fake.methods()
    assert card.secondary == []
    assert [item["title"] for item in card.items] == ["NFS", "SMB", "SSH"]


@pytest.mark.parametrize("errname", ["EACCES", "ENOMETHOD"])
async def test_a_refused_session_count_leaves_the_services_card_as_it_was(errname: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A key whose role lacks SHARING_SMB_READ: the services still show, without the count."""
    adapter, _fake = fake_on(monkeypatch, refuse={"smb.status": errname})
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "26.0.0"})
    card = await adapter.fetch("services", HTTPS, {}, fresh())
    assert card.error is None
    assert card.secondary == []
    assert [item["title"] for item in card.items] == ["NFS", "SMB", "SSH"]


async def test_smb_sessions_are_shown_only_while_smb_runs_and_only_when_wanted(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "26.0.0"})
    monkeypatch.setitem(ANSWERS, "service.query", [{**SERVICES[0], "state": "STOPPED", "pids": []}, *SERVICES[1:]])
    card = await adapter.fetch("services", HTTPS, {}, fresh())
    assert card.secondary == [], "a stopped SMB has nothing to count; 0 would read as nobody connected"
    monkeypatch.setitem(ANSWERS, "service.query", [{**SERVICES[0], "enable": False}, *SERVICES[1:]])
    card = await adapter.fetch("services", HTTPS, {}, fresh())
    assert sessions_of(card) == 2, "a running SMB not set to start is counted too"
    monkeypatch.setitem(ANSWERS, "smb.status", [{"session_id": "3", "username": "alex"}])
    card = await adapter.fetch("services", HTTPS, {}, fresh())
    assert card.secondary == [], "a list where the count belongs is not a count"
    fake.sent.clear()
    card = await adapter.fetch("services", HTTPS, {"show_smb_sessions": False}, fresh())
    assert "smb.status" not in fake.methods() and "system.info" not in fake.methods(), "switched off is not asked at all"
    assert card.secondary == []


async def test_the_version_for_the_session_count_is_read_once_an_hour(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "26.0.0"})
    await adapter.fetch("services", HTTPS, {}, ctx)
    assert fake.methods().count("system.info") == 1
    fake.sent.clear()
    later(monkeypatch, 1800)
    await adapter.fetch("services", HTTPS, {}, ctx)
    assert "system.info" not in fake.methods() and "smb.status" in fake.methods()
    fake.sent.clear()
    later(monkeypatch, 3700)
    await adapter.fetch("services", HTTPS, {}, ctx)
    assert "system.info" in fake.methods(), "an update to 25.10 or 26 is noticed within the hour"


#: 15:00 UTC on 17.11.2026, 16:00 in Berlin, the moment the session ages are read at.
SESSIONS_READ_AT = datetime(2026, 11, 17, 15, 0, tzinfo=UTC).timestamp()


def sessions_read_at(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.adapters.truenas as module

    monkeypatch.setattr(module, "ago", lambda moment: ago(moment, now=SESSIONS_READ_AT))


def rows_of(card: WidgetData) -> list[tuple[Any, ...]]:
    return [(item["title"], item["subtitle"], item["value"], item["status"]) for item in card.items]


@pytest.mark.parametrize("version", ["25.04.2.4", "26.0.0", "TrueNAS-27.0.0"])
async def test_the_smb_sessions_card_lists_who_is_connected_from_where_and_since_when(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #73, round two: who to warn before a restart. A Mac's two sessions are one row."""
    adapter, fake = fake_on(monkeypatch)
    sessions_read_at(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": version})
    card = await adapter.fetch("smb_sessions", HTTPS, {}, fresh())
    assert params_of(fake, "smb.status") == ["SESSIONS", [], {}, {}], "the list, without fast: no client whose process is gone"
    assert rows_of(card) == [
        ("alex", "alex-macbook · SMB 3.1.1", "2 h", "ok"),
        ("media", "192.168.1.40 · SMB 3.1.1", "2 d", "ok"),
    ], "connected since the older of the Mac's sessions; the address where the TV gave no name"
    assert card.secondary == [{"label": "Sessions", "value": 3}, {"label": "Users", "value": 2}]
    assert card.status == "ok"


async def test_nobody_connected_is_an_empty_list_that_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, _fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "26.0.0"})
    monkeypatch.setitem(ANSWERS, "smb.status", [])
    card = await adapter.fetch("smb_sessions", HTTPS, {}, fresh())
    assert (card.items, card.status) == ([], "ok")
    assert card.secondary == [{"label": "Sessions", "value": 0}, {"label": "Users", "value": 0}]


async def test_the_count_and_the_list_of_sessions_are_kept_apart(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both read smb.status. Kept under the method's name alone, each card got the other's answer."""
    adapter, _fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "26.0.0"})
    assert sessions_of(await adapter.fetch("services", HTTPS, {}, ctx)) == 2
    listed = await adapter.fetch("smb_sessions", HTTPS, {}, ctx)
    assert [item["title"] for item in listed.items] == ["alex", "media"]
    assert sessions_of(await adapter.fetch("services", HTTPS, {}, ctx)) == 2


@pytest.mark.parametrize(("version", "code"), [
    ("", "smb_sessions_private"), ("TrueNAS-SCALE-24.10.2", "needs_current_api"),
])
async def test_the_smb_sessions_card_says_why_a_version_does_not_tell_them(version: str, code: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": version})
    with pytest.raises(AdapterError) as closed:
        await adapter.fetch("smb_sessions", HTTPS, {}, fresh())
    assert closed.value.code == code
    assert "smb.status" not in fake.methods()


@pytest.mark.parametrize("version", ["25.10.8", "25.10.2.1", "TrueNAS-SCALE-25.10.0"])
async def test_on_25_10_the_smb_sessions_card_is_grey_and_says_why(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #76: 25.10 keeps the sessions private. Nothing is wrong, so no red card and no question asked."""
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": version})
    card = await adapter.fetch("smb_sessions", HTTPS, {}, fresh())
    assert (card.status, card.error, card.items) == ("unknown", None, [])
    assert card.meta == {"empty": "TrueNAS 25.10 keeps the SMB sessions to itself. They show from TrueNAS 26 on."}
    assert "smb.status" not in fake.methods(), "a full key would write a warning into TrueNAS' log on every call"


async def test_a_stopped_smb_is_said_and_not_shown_as_nobody_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, _fake = fake_on(monkeypatch, refuse={"smb.status": "EFAULT"})
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "26.0.0"})
    monkeypatch.setitem(ANSWERS, "service.query", [{**SERVICES[0], "state": "STOPPED", "pids": []}, *SERVICES[1:]])
    card = await adapter.fetch("smb_sessions", HTTPS, {}, fresh())
    assert [(item["title"], item["value"], item["status"]) for item in card.items] == [("SMB", "Stopped", "unknown")]
    assert (card.secondary, card.status, card.error) == ([], "unknown", None)


@pytest.mark.parametrize("errname", ["EACCES", "ENOMETHOD"])
async def test_refused_sessions_are_an_error_on_their_own_card(errname: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The services card goes on without the count; this card has nothing else, so it says why."""
    adapter, _fake = fake_on(monkeypatch, refuse={"smb.status": errname})
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "26.0.0"})
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("smb_sessions", HTTPS, {}, fresh())
    assert refused.value.code == "smb_sessions_refused"


@pytest.mark.parametrize(("written", "meant"), [
    ("2026-11-17T14:55:00.123456+01:00", datetime(2026, 11, 17, 13, 55, 0, 123456, tzinfo=UTC)),
    # 00:30 in Berlin is 23:30 UTC the day before; Samba writes -23:00.
    ("2026-11-18T00:30:00.000000-23:00", datetime(2026, 11, 17, 23, 30, tzinfo=UTC)),
    # 20:00 in New York is 01:00 UTC the day after; Samba writes +19:00.
    ("2026-11-17T20:00:00.000000+19:00", datetime(2026, 11, 18, 1, 0, tzinfo=UTC)),
    ("2026-11-17T08:00:00.000000-10:00", datetime(2026, 11, 17, 18, 0, tzinfo=UTC)),
    ("2026-11-17T08:00:00.000000+14:00", datetime(2026, 11, 16, 18, 0, tzinfo=UTC)),
])
def test_a_session_s_start_is_read_with_samba_s_offset_put_right(written: str, meant: datetime) -> None:
    assert _smb_opened(written) == meant.timestamp()


@pytest.mark.parametrize("written", [None, "", "yesterday", 1_789_712_345])
def test_a_start_that_cannot_be_read_is_none(written: Any) -> None:
    assert _smb_opened(written) is None


@pytest.mark.parametrize(("session", "machine"), [
    ({"remote_machine": "alex-macbook", "hostname": "ipv4:192.168.1.31:51547"}, "alex-macbook"),
    ({"remote_machine": "", "hostname": "ipv4:192.168.1.40:40112"}, "192.168.1.40"),
    ({"remote_machine": " ", "hostname": "ipv6:fd00::40:40112"}, "fd00::40"),
    ({}, "?"),
])
def test_the_machine_is_its_name_else_its_address_without_the_port(session: dict[str, Any], machine: str) -> None:
    assert _smb_machine(session) == machine


async def test_vms_and_containers_are_counted_once(ctx: Context, truenas) -> None:
    adapter, _fake = truenas
    card = await adapter.fetch("vms", HTTPS, {}, ctx)
    assert [(item["title"], item["subtitle"], item["value"], item["status"]) for item in card.items] == [
        ("homeassistant", "VM · 2 vCPU · 4.0 GB", "Running", "ok"),
        ("pihole", "Container · 1 vCPU · 512.0 MB", "Running", "ok"),
        ("windows", "VM · 4 vCPU · 8.0 GB", "Stopped", "unknown"),
    ]
    assert card.secondary == [{"label": "Running", "value": 2}]


async def test_without_either_list_of_machines_the_card_says_so(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, _fake = fake_on(monkeypatch, refuse={"vm.query": "ENOMETHOD", "virt.instance.query": "ENOMETHOD"})
    with pytest.raises(AdapterError) as missing:
        await adapter.fetch("vms", HTTPS, {}, ctx)
    assert "neither" in missing.value.message


@respx.mock
async def test_a_new_card_on_an_old_truenas_says_what_it_needs(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("truenas")
    monkeypatch.setattr(adapter, "_open_socket", turned_down(404))
    respx.get("https://truenas.example.com/api/v2.0/system/info").mock(return_value=httpx.Response(200, json=OLD_INFO))
    respx.get("https://truenas.example.com/api/v2.0/alert/list").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(AdapterError) as refused:
        await adapter.fetch("apps", HTTPS, {}, ctx)
    assert refused.value.code == "needs_current_api"
    assert "25.04" in refused.value.hint
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert all(entry["label"] != "Update available" for entry in system.secondary), "the system card of an old TrueNAS keeps working"


def _data(*items: dict[str, Any], **kwargs: Any) -> WidgetData:
    return WidgetData(items=list(items), **kwargs)


def test_a_disk_is_told_once_when_it_gets_hot() -> None:
    adapter = get_adapter("truenas")
    cool, hot = {"title": "sda", "value": "40 °C", "status": "ok"}, {"title": "sda", "value": "56 °C", "status": "warn", "subtitle": "WDC · tank"}
    told = adapter.detect("disks", _data(cool), _data(hot), {})
    assert [(found.event, found.title, found.key) for found in told] == [("disk_hot", "sda is at 56 °C", "disk_hot:sda:warn")]
    assert adapter.detect("disks", _data(hot), _data({**hot, "value": "57 °C"}), {}) == [], "only on the crossing"
    assert len(adapter.detect("disks", None, _data(hot), {})) == 1, "hot when the card first looks, like a full pool"


def test_a_failed_task_is_told_when_it_fails_not_when_the_card_first_sees_it() -> None:
    adapter = get_adapter("truenas")
    good = {"id": "cloudsync.query:1", "title": "Photos to B2", "status": "ok", "subtitle": "Cloud sync · Finished"}
    failed = {**good, "status": "bad", "subtitle": "Cloud sync · Upload quota exceeded."}
    told = adapter.detect("protection", _data(good), _data(failed), {})
    assert [(found.event, found.title, found.body, found.level) for found in told] == [("backup_failed", "Photos to B2 failed", "Cloud sync · Upload quota exceeded.", "bad")]
    assert adapter.detect("protection", None, _data(failed), {}) == []
    assert adapter.detect("protection", _data(failed), _data(failed), {}) == []


def test_an_update_is_told_once_per_version() -> None:
    adapter = get_adapter("truenas")
    current = {"title": "jellyfin", "update": ""}
    waiting = {"title": "jellyfin", "update": "1.2.4"}
    told = adapter.detect("apps", _data(current), _data(waiting), {})
    assert [(found.event, found.title) for found in told] == [("software_update", "jellyfin: update to 1.2.4")]
    assert adapter.detect("apps", _data(waiting), _data(waiting), {}) == []
    assert len(adapter.detect("apps", _data(waiting), _data({**waiting, "update": "1.2.5"}), {})) == 1, "a newer one is news again"
    assert adapter.detect("apps", None, _data(waiting), {}) == [], "twenty old updates are no news when the card is added"

    before = WidgetData(secondary=[{"label": "Alerts", "value": 0}])
    after = WidgetData(secondary=[{"label": "Alerts", "value": 0}, {"label": "Update", "value": "25.10.8", "part": "update"}])
    assert [found.title for found in adapter.detect("system", before, after, {})] == ["TrueNAS 25.10.8 is available"]
    assert adapter.detect("system", after, after, {}) == []
    assert adapter.detect("system", None, after, {}) == []


@pytest.mark.parametrize("kind", ["interfaces", "apps", "disks", "protection", "services", "smb_sessions", "vms"])
def test_every_new_card_has_a_demo(kind: str) -> None:
    data = get_adapter("truenas").demo(kind, {}, 3)
    assert data.items, kind


async def test_the_update_is_asked_again_after_six_hours(ctx: Context, truenas, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = truenas
    await adapter.fetch("system", HTTPS, {}, ctx)
    fake.sent.clear()
    later(monkeypatch, 6 * 3600 + 60)
    await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.status" in fake.methods()


async def test_an_offline_truenas_answers_the_update_check_with_an_error_and_is_left_alone(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """How 25.10 says it: an answer with code ERROR, not a refused call."""
    adapter, fake = fake_on(monkeypatch)
    monkeypatch.setitem(ANSWERS, "update.status", {"code": "ERROR", "status": None, "error": {"errname": "ENETUNREACH", "reason": "Network is unreachable"},
                                                   "update_download_progress": None})
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert all(entry["label"] != "Update available" for entry in system.secondary)
    fake.sent.clear()
    later(monkeypatch, 3600)
    await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.status" not in fake.methods()


async def test_a_slow_update_check_does_not_hold_the_system_card(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    """TrueNAS waits 15 s for its update server when the traffic is dropped;
    the settings preview gives up after 20."""
    import app.adapters.truenas as module

    monkeypatch.setattr(module, "UPDATE_WAIT", 0.2)
    adapter, fake = fake_on(monkeypatch, silent={"update.status"})
    started = time.monotonic()
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert time.monotonic() - started < 2.0
    assert system.primary == {"label": "CPU", "value": 3.0, "unit": "%"}
    assert fake.closed == len(fake.opened), "the abandoned connection is closed too"
    fake.sent.clear()
    await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.status" not in fake.methods()


async def test_a_check_cut_short_from_outside_is_not_repeated_at_once(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = fake_on(monkeypatch, silent={"update.status"})
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.5):
            await adapter.fetch("system", HTTPS, {}, ctx)
    fake.sent.clear()
    await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.status" not in fake.methods(), "a cancelled preview must not send TrueNAS to its update server again"


async def test_a_failed_check_keeps_the_update_it_knew(ctx: Context, truenas, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = truenas
    await adapter.fetch("system", HTTPS, {}, ctx)
    fake.refuse["update.status"] = "ENETUNREACH"
    later(monkeypatch, 6 * 3600 + 60)
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.status" in fake.methods()
    assert {"label": "Update available", "value": "25.10.8", "part": "update"} in system.secondary, "a chip that blinks out comes back as news"


async def test_after_the_reboot_the_update_is_neither_waiting_nor_pending(ctx: Context, truenas, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, fake = truenas
    monkeypatch.setitem(ANSWERS, "update.status", {"code": "ERROR", "status": None, "error": {"errname": "EREBOOTREQUIRED", "reason": "Reboot"}})
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert {"label": "Update available", "value": "Reboot required", "part": "update"} in system.secondary
    # The reboot: uptime starts again, the new release runs, and nothing waits.
    monkeypatch.setitem(ANSWERS, "system.info", {**INFO, "version": "25.10.8", "uptime_seconds": 120.0})
    monkeypatch.setitem(ANSWERS, "update.status", {**UPDATE, "status": {**UPDATE["status"], "new_version": None}})
    later(monkeypatch, 3600)
    fake.sent.clear()
    system = await adapter.fetch("system", HTTPS, {}, ctx)
    assert "update.status" in fake.methods(), "a new boot is a new question"
    assert all(entry["label"] != "Update available" for entry in system.secondary)


def test_a_release_that_runs_already_is_not_waiting() -> None:
    from app.adapters.truenas import _unless_installed

    assert _unless_installed("25.10.8", {"version": "TrueNAS-25.10.8"}) == ""
    assert _unless_installed("25.10.8", {"version": "25.10.7"}) == "25.10.8"
    assert _unless_installed("Reboot required", {"version": "25.10.8"}) == "Reboot required"


def test_a_disk_going_from_yellow_to_red_is_told_again() -> None:
    adapter = get_adapter("truenas")
    warm, hot = {"title": "sda", "value": "52 °C", "status": "warn"}, {"title": "sda", "value": "61 °C", "status": "bad"}
    assert [found.level for found in adapter.detect("disks", _data(warm), _data(hot), {})] == ["bad"]
    assert adapter.detect("disks", _data(hot), _data(warm), {}) == [], "cooling down is no news"


def test_a_task_that_failed_while_the_card_was_in_error_is_still_told() -> None:
    """The collector keeps the last good rows on a card in error; a backup that
    failed while TrueNAS rebooted is news after it."""
    adapter = get_adapter("truenas")
    good = {"id": "cloudsync.query:1", "title": "Photos to B2", "status": "ok"}
    broken = WidgetData(items=[good], error="TrueNAS could not be reached.")
    assert len(adapter.detect("protection", broken, _data({**good, "status": "bad"}), {})) == 1
