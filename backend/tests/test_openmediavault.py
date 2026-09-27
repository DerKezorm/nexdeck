"""openmediavault, against the answers of a live openmediavault 8.5.9-1 (Synchrony) on Debian 13 (27.09.2026).

Every answer below is one the live machine gave; host names, device ids,
file system ids and sessions are replaced with made-up ones.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client
from app.adapters.openmediavault import _bytes_of

OMV = "http://omv.example.com"
RPC = f"{OMV}/rpc.php"
CONFIG = {"url": OMV, "username": "admin", "password": "omv-test-password-for-the-cards"}
ADAPTER = get_adapter("openmediavault")
SESSION = "session-of-the-test-nas"
MARKER = "OPENMEDIAVAULT-LOGIN-made-up-marker-for-the-test"

WRONG = {"response": None, "error": {"code": 0, "message": "Incorrect username or password."}}
NOT_AUTHENTICATED = {"response": None, "error": {"code": 0, "message": "Session not authenticated."}}
EXPIRED = {"response": None, "error": {"code": 0, "message": "Session expired."}}
ROLE = {"response": None, "error": {"code": 0, "message": "Invalid context role."}}
ANOTHER = {"response": None, "error": {"code": 0, "message": "Another user is already authenticated."}}

INFO = {"ts": 1790498784, "time": "Sun Sep 27 08:46:24 2026", "hostname": "omv-test", "version": "8.5.9-1 (Synchrony)",
        "cpuModelName": "AMD Ryzen 7 5700U with Radeon Graphics", "cpuUtilization": 0.9950248756218906, "cpuCores": "2", "cpuMhz": "3992.456",
        "memTotal": "2070056960", "memFree": "587169792", "memUsed": "374411264", "memAvailable": "1695645696", "memUtilization": "0.18087",
        "kernel": "Linux 6.12.107+deb13-cloud-amd64", "uptime": 517.22, "loadAverage": {"1min": 0.55, "5min": 0.41, "15min": 0.17},
        "configDirty": False, "dirtyModules": [], "rebootRequired": False, "availablePkgUpdates": 0, "displayWelcomeMessage": True}
#: ⚠️ What a plain user is given, with 200.
INFO_FOR_A_USER = {"ts": 1790499085, "time": "Sun Sep 27 08:51:25 2026", "hostname": "omv-test"}


def filesystem(name: str, **fields: Any) -> dict[str, Any]:
    entry = {"devicename": name, "devicefile": f"/dev/disk/by-uuid/{name}-id", "predictabledevicefile": f"/dev/disk/by-uuid/{name}-id",
             "canonicaldevicefile": f"/dev/{name}", "parentdevicefile": f"/dev/{name[:3]}", "devlinks": [], "uuid": f"{name}-id",
             "label": "", "type": "ext4", "blocks": "-1", "mounted": False, "mountpoint": "", "used": "-1", "available": "-1", "size": "-1",
             "percentage": -1, "description": "", "propposixacl": True, "propquota": True, "propresize": True, "propfstab": True,
             "propcompress": False, "propautodefrag": False, "hasmultipledevices": False, "devicefiles": [f"/dev/{name}"], "comment": "",
             "_readonly": False, "_used": False, "propreadonly": False}
    entry.update(fields)
    return entry


FILESYSTEMS = [
    filesystem("sda1", mounted=True, mountpoint="/", used="1.46 GiB", available="14388461568", size="16694517760", percentage=10,
               blocks="16303240", _used=True, _readonly=True),
    filesystem("sdc1", label="media", mounted=True, mountpoint="/srv/dev-disk-by-uuid-sdc1-id", used="2.54 GiB",
               available="5604016128", size="8349229056", percentage=33, blocks="8153544"),
    filesystem("sr0", label="cidata", type="iso9660", parentdevicefile="/dev/sr0"),
    filesystem("sda15", type="vfat", mounted=True, mountpoint="/boot/efi", used="8.89 MiB", available="120395776", size="129718272",
               percentage=8),
    # ⚠️ Not mounted: -1 for size, available and the percentage.
    filesystem("sdb1", label="archive", type="xfs"),
]


def disk(name: str, **fields: Any) -> dict[str, Any]:
    entry = {"devicename": name, "canonicaldevicefile": f"/dev/{name}", "devicefile": f"/dev/disk/by-id/made-up-{name}",
             "devicelinks": [f"/dev/disk/by-id/made-up-{name}"], "model": "QEMU HARDDISK", "size": "8589934592", "temperature": "0",
             "description": f"QEMU HARDDISK [/dev/{name}, 8.00 GiB]", "vendor": "QEMU", "serialnumber": f"made-up-serial-{name}",
             "wwn": "", "overallstatus": "BAD_STATUS", "uuid": "made-up-uuid", "monitor": False, "_used": False}
    entry.update(fields)
    return entry


#: ⚠️ As measured: the virtual SCSI disks say BAD_STATUS, the virtual SATA disk GOOD with 31 °C.
SMART = {"total": 3, "data": [
    disk("sda", size="17179869184"),
    disk("sdb"),
    disk("sdc", vendor="ATA", temperature="31", overallstatus="GOOD"),
]}

ANSWERS: dict[tuple[str, str], Any] = {("System", "getInformation"): INFO, ("FileSystemMgmt", "enumerateFilesystems"): FILESYSTEMS,
                                        ("Smart", "getList"): SMART}


class Nas:
    """A fake openmediavault: signs in, answers the calls it knows, writes down what it was sent."""

    def __init__(self, *, role: str = "admin", answers: dict[tuple[str, str], Any] | None = None) -> None:
        self.role = role
        self.answers = {**ANSWERS, **(answers or {})}
        self.logins: list[dict[str, str]] = []
        self.calls: list[tuple[str, str, Any, dict[str, str]]] = []
        self.sessions = 0
        self.valid: set[str] = set()
        self.refuse: set[tuple[str, str]] = set()
        respx.post(RPC).mock(side_effect=self.answer)

    def answer(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        cookies = dict(part.strip().split("=", 1) for part in request.headers.get("cookie", "").split(";") if "=" in part)
        if (body["service"], body["method"]) == ("Session", "login"):
            self.logins.append(cookies)
            if cookies.get("OPENMEDIAVAULT-SESSIONID"):
                return httpx.Response(400, json=ANOTHER)
            if body["params"] != {"username": CONFIG["username"], "password": CONFIG["password"]}:
                return httpx.Response(400, json=WRONG, headers={"set-cookie": "OPENMEDIAVAULT-SESSIONID=unauthenticated; path=/; HttpOnly"})
            self.sessions += 1
            session = f"{SESSION}-{self.sessions}"
            self.valid.add(session)
            headers = [("set-cookie", f"OPENMEDIAVAULT-SESSIONID={session}; path=/; HttpOnly; SameSite=Strict")]
            if MARKER not in cookies:
                headers.append(("set-cookie", f"{MARKER}=A%20quote; Max-Age=5184000; HttpOnly; SameSite=Strict"))
            return httpx.Response(200, headers=headers, json={"response": {"username": CONFIG["username"], "status": "authenticated",
                                                                           "permissions": {"role": self.role}, "sessionid": session},
                                                              "error": None})
        self.calls.append((body["service"], body["method"], body["params"], cookies))
        if cookies.get("OPENMEDIAVAULT-SESSIONID") not in self.valid:
            return httpx.Response(401, json=NOT_AUTHENTICATED)
        if (body["service"], body["method"]) in self.refuse or self.role != "admin":
            if (body["service"], body["method"]) == ("System", "getInformation"):
                return httpx.Response(200, json={"response": INFO_FOR_A_USER, "error": None})
            return httpx.Response(403, json=ROLE)
        return httpx.Response(200, json={"response": self.answers[(body["service"], body["method"])], "error": None})


@pytest.fixture
def ctx() -> Context:
    # The client the app uses: no cookie jar, so only what the adapter sends goes out.
    return Context(outbound_client(), integration_id=1, widget_id=1, cache={})


# -- signing in ---------------------------------------------------------------


@respx.mock
async def test_the_sign_in_hands_the_session_to_every_call(ctx: Context) -> None:
    nas = Nas()
    assert await ADAPTER.test(CONFIG, ctx) == "openmediavault 8.5.9-1 (Synchrony) answers on omv-test."
    await ADAPTER.fetch("filesystems", CONFIG, {}, ctx)
    assert len(nas.logins) == 1, "one sign-in for both"
    assert [cookies.get("OPENMEDIAVAULT-SESSIONID") for *_, cookies in nas.calls] == [f"{SESSION}-1", f"{SESSION}-1"]


@respx.mock
async def test_a_wrong_password_is_a_refusal(ctx: Context) -> None:
    Nas()
    with pytest.raises(AuthFailed, match="rejected the user or the password"):
        await ADAPTER.test({**CONFIG, "password": "a-wrong-password"}, ctx)


@respx.mock
async def test_a_refused_password_is_not_tried_again_soon(ctx: Context) -> None:
    nas = Nas()
    wrong = {**CONFIG, "password": "a-wrong-password"}
    for kind in ("system", "filesystems", "disks", "system"):
        with pytest.raises(AuthFailed) as caught:
            await ADAPTER.fetch(kind, wrong, {}, ctx)
    # ⚠️ Three failures in five minutes lock the account for good, so one try and no more.
    assert len(nas.logins) == 1
    assert "faillock --user <name> --reset" in caught.value.hint
    # A changed password is tried at once.
    await ADAPTER.fetch("system", CONFIG, {}, ctx)
    assert len(nas.logins) == 2
    # And the wrong one again only when its time is up.
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("system", wrong, {}, ctx)
    assert len(nas.logins) == 2
    tried, _until = ctx.cache["openmediavault_refused"]
    ctx.cache["openmediavault_refused"] = (tried, 0.0)
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("system", wrong, {}, ctx)
    assert len(nas.logins) == 3


def test_the_hold_is_longer_than_the_lock_window() -> None:
    from app.adapters import openmediavault

    # pam_faillock fail_interval=300: one try per hold can never be three in a window.
    assert openmediavault.REFUSED_SECONDS >= 300 * 2


@respx.mock
async def test_a_session_that_ran_out_is_renewed_once(ctx: Context) -> None:
    nas = Nas()
    await ADAPTER.fetch("system", CONFIG, {}, ctx)
    # ⚠️ Five idle minutes: 401 "Session expired.", then one more sign-in.
    nas.valid.clear()
    route = respx.post(RPC)
    first = {"done": False}

    def expired_once(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["method"] != "login" and not first["done"]:
            first["done"] = True
            return httpx.Response(401, json=EXPIRED)
        return nas.answer(request)

    route.mock(side_effect=expired_once)
    card = await ADAPTER.fetch("system", CONFIG, {}, ctx)
    assert card.primary["value"] == 1.0
    assert len(nas.logins) == 2


@respx.mock
async def test_a_session_refused_right_after_the_sign_in_is_not_asked_forever(ctx: Context) -> None:
    nas = Nas()
    route = respx.post(RPC)
    route.mock(side_effect=lambda request: nas.answer(request) if json.loads(request.content)["method"] == "login"
               else httpx.Response(401, json=NOT_AUTHENTICATED))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("system", CONFIG, {}, ctx)
    assert caught.value.code == "session_refused"
    assert len(nas.logins) == 2


@respx.mock
async def test_the_login_marker_is_kept_and_the_old_session_never_sent(ctx: Context) -> None:
    nas = Nas()
    await ADAPTER.fetch("system", CONFIG, {}, ctx)
    nas.valid.clear()
    await ADAPTER.fetch("system", CONFIG, {}, ctx)
    assert len(nas.logins) == 2
    # ⚠️ Without the marker every sign-in counts as a new browser, which can mail the user.
    assert nas.logins[0] == {}
    assert nas.logins[1] == {MARKER: "A%20quote"}
    # ⚠️ With the old session in it, a sign-in of another user would be refused.
    assert all("OPENMEDIAVAULT-SESSIONID" not in cookies for cookies in nas.logins)


@respx.mock
async def test_a_different_user_signs_in_afresh(ctx: Context) -> None:
    nas = Nas()
    await ADAPTER.fetch("system", CONFIG, {}, ctx)
    other = {**CONFIG, "username": "deputy"}
    with pytest.raises(AuthFailed):
        await ADAPTER.fetch("system", other, {}, ctx)
    # The marker belongs to the user it was set for.
    assert nas.logins[1] == {}


@respx.mock
async def test_a_second_step_and_a_lock_are_named(ctx: Context) -> None:
    route = respx.post(RPC)
    route.mock(return_value=httpx.Response(200, json={"response": {"username": "admin", "status": "challengeRequired",
                                                                   "challenge": {"kind": "totp"}}, "error": None}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "second_factor"
    route.mock(return_value=httpx.Response(429, json={"response": None, "error": {
        "code": 0, "message": "Too many failed verification attempts. Please try again later."}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "locked"


# -- rights -------------------------------------------------------------------


@respx.mock
async def test_a_plain_user_is_told_so_and_not_shown_an_empty_nas(ctx: Context) -> None:
    nas = Nas(role="user")
    for kind in ("system", "filesystems", "disks"):
        with pytest.raises(AdapterError) as caught:
            await ADAPTER.fetch(kind, CONFIG, {}, ctx)
        assert caught.value.code == "forbidden"
        assert "openmediavault-admin" in caught.value.hint
    with pytest.raises(AdapterError, match="not an administrator"):
        await ADAPTER.test(CONFIG, ctx)
    assert nas.calls == [], "nothing is asked that is known to be refused"


@respx.mock
async def test_the_narrowed_information_is_not_taken_for_a_whole_one(ctx: Context) -> None:
    nas = Nas()
    # ⚠️ 200 with time and host name only, as a plain user gets it.
    nas.refuse.add(("System", "getInformation"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("system", CONFIG, {}, ctx)
    assert caught.value.code == "forbidden"


@respx.mock
async def test_a_refused_call_says_which(ctx: Context) -> None:
    nas = Nas()
    nas.refuse.add(("Smart", "getList"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("disks", CONFIG, {}, ctx)
    assert caught.value.code == "forbidden"
    assert "Smart.getList" in caught.value.message and "Invalid context role." in caught.value.message


# -- when the address is wrong ----------------------------------------------


@respx.mock
async def test_nothing_listening_is_unreachable(ctx: Context) -> None:
    respx.post(RPC).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.test(CONFIG, ctx)


@respx.mock
async def test_something_else_at_the_address(ctx: Context) -> None:
    respx.post(RPC).mock(return_value=httpx.Response(404, text="<html>Not found</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_openmediavault"
    respx.post(RPC).mock(return_value=httpx.Response(200, json={"status": "ok"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_openmediavault"


@respx.mock
async def test_an_error_of_the_call_itself(ctx: Context) -> None:
    nas = Nas()
    nas.answers[("Smart", "getList")] = None
    route = respx.post(RPC)
    route.mock(side_effect=lambda request: nas.answer(request) if json.loads(request.content)["method"] == "login"
               else httpx.Response(500, json={"response": None, "error": {"code": 0, "message": "Failed to get list of storage devices"}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("disks", CONFIG, {}, ctx)
    assert caught.value.code == "rpc_error"
    assert "Failed to get list of storage devices" in caught.value.message


# -- the cards ----------------------------------------------------------------


@respx.mock
async def test_the_system_card(ctx: Context) -> None:
    Nas()
    card = await ADAPTER.fetch("system", CONFIG, {}, ctx)
    chips = {chip["label"]: chip["value"] for chip in card.secondary}
    # ⚠️ CPU in per cent, memory worked out from the byte strings: (total - available) / total.
    assert card.primary == {"label": "CPU", "value": 1.0, "unit": "%", "part": "cpu"}
    assert chips == {"Memory": 18.1, "Load": "0.55 / 0.41 / 0.17", "Uptime": "8m 37s", "Updates": 0, "Version": "8.5.9-1"}
    assert card.metrics == {"cpu": 1.0, "memory": 18.1}
    assert card.status == "ok"


def test_memory_falls_back_to_the_fraction() -> None:
    info = {**INFO, "memAvailable": None}
    card = ADAPTER._system(info)
    # ⚠️ "0.18087" is a fraction: 18.1 per cent, not 0.2.
    assert next(chip for chip in card.secondary if chip["label"] == "Memory")["value"] == 18.1


def test_the_system_card_colours() -> None:
    assert ADAPTER._system({**INFO, "rebootRequired": True}).status == "warn"
    assert any(chip["label"] == "Reboot" for chip in ADAPTER._system({**INFO, "rebootRequired": True}).secondary)
    assert ADAPTER._system({**INFO, "cpuUtilization": 96.0}).status == "bad"
    assert ADAPTER._system({**INFO, "cpuUtilization": 81.0}).status == "warn"
    busy = ADAPTER._system({**INFO, "memAvailable": str(int(2070056960 * 0.04))})
    assert busy.status == "bad"
    assert next(chip for chip in ADAPTER._system({**INFO, "availablePkgUpdates": 7}).secondary if chip["label"] == "Updates")["value"] == 7


@respx.mock
async def test_the_file_system_card(ctx: Context) -> None:
    Nas()
    card = await ADAPTER.fetch("filesystems", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in card.items}
    # ⚠️ The CD of cloud-init is a file system too; it is left out.
    assert set(rows) == {"sda1", "media", "sda15", "archive"}
    assert rows["media"] == {"title": "media", "subtitle": "EXT4 · 2.5 GB of 7.8 GB · /dev/sdc1", "progress": 33.0, "value": "33%", "status": "ok"}
    assert rows["sda1"]["subtitle"] == "EXT4 · 1.5 GB of 15.5 GB · System"
    assert rows["sda15"]["subtitle"] == "VFAT · 8.9 MB of 123.7 MB"
    # ⚠️ Not mounted: nothing measured, not a negative share.
    assert rows["archive"] == {"title": "archive", "subtitle": "XFS · /dev/sdb1", "value": "Not mounted", "status": "unknown"}
    assert card.status == "ok"
    assert [row["title"] for row in card.items][-1] == "sda15", "the unmounted one before the healthy ones"


def test_a_full_file_system_warns() -> None:
    card = ADAPTER._filesystems([FILESYSTEMS[1] | {"percentage": 90}, FILESYSTEMS[0]])
    assert card.items[0]["title"] == "media" and card.items[0]["status"] == "warn"
    assert card.status == "warn"
    assert ADAPTER._filesystems([FILESYSTEMS[1] | {"percentage": 89}]).status == "ok"
    assert ADAPTER._filesystems([]).status == "unknown"


def test_the_share_is_worked_out_when_missing() -> None:
    row = ADAPTER._filesystems([FILESYSTEMS[1] | {"percentage": -1}]).items[0]
    # 2.54 GiB of 8349229056 bytes.
    assert row["progress"] == 32.7


def test_used_is_read_from_its_text() -> None:
    assert _bytes_of("2.54 GiB") == pytest.approx(2.54 * 1024**3)
    assert _bytes_of("8.89 MiB") == pytest.approx(8.89 * 1024**2)
    assert _bytes_of("512 B") == 512
    assert _bytes_of("1.2 TiB") == pytest.approx(1.2 * 1024**4)
    assert _bytes_of("3.5 KB") == pytest.approx(3.5 * 1024)
    assert _bytes_of("2745212928") == 2745212928
    assert _bytes_of("-1") is None
    assert _bytes_of("n/a") is None


@respx.mock
async def test_virtual_disks_are_not_graded(ctx: Context) -> None:
    Nas()
    card = await ADAPTER.fetch("disks", CONFIG, {}, ctx)
    # ⚠️ Measured BAD_STATUS on the virtual SCSI disks, GOOD on the SATA one: all made up.
    assert [row["title"] for row in card.items] == ["sda", "sdb", "sdc"]
    assert all(row["status"] == "unknown" and row["value"] == "" for row in card.items)
    assert card.items[0]["subtitle"] == "QEMU HARDDISK · 16.0 GB · Virtual disk, SMART not available"
    assert card.status == "unknown"


def test_real_disks_by_their_verdict() -> None:
    real = {"vendor": "ATA", "model": "WDC WD40EFRX-68N32N0", "size": "4000787030016"}
    card = ADAPTER._disks([
        disk("sda", **real, temperature="34", overallstatus="GOOD"),
        disk("sdb", **real, temperature="0", overallstatus="GOOD"),
        disk("sdc", **real, temperature="41", overallstatus="BAD_SECTOR"),
        disk("sdd", **real, temperature="", overallstatus="BAD_STATUS"),
        disk("sde", **real, temperature="38", overallstatus="BAD_ATTRIBUTE_IN_THE_PAST"),
        disk("sdf", **real, temperature="38", overallstatus="SOMETHING_NEW"),
    ])
    rows = {row["title"]: row for row in card.items}
    assert rows["sda"] == {"title": "sda", "subtitle": "WDC WD40EFRX-68N32N0 · 3.6 TB · Good", "value": "34 °C", "status": "ok"}
    # ⚠️ 0 is no temperature.
    assert rows["sdb"]["value"] == ""
    assert rows["sdc"]["status"] == "warn" and rows["sdc"]["subtitle"].endswith("Bad sectors")
    assert rows["sdd"]["status"] == "bad" and rows["sdd"]["subtitle"].endswith("Failed or unreadable")
    assert rows["sde"]["status"] == "warn"
    assert rows["sdf"]["status"] == "unknown" and rows["sdf"]["subtitle"].endswith("Something new")
    assert card.status == "bad"
    assert [row["title"] for row in card.items][0] == "sdd", "the failing disk first"
    assert ADAPTER._disks([disk("sda", **real, temperature="35", overallstatus="BAD_SECTOR_MANY")]).status == "bad"
    assert ADAPTER._disks([disk("sda", **real, temperature="35", overallstatus="BAD_ATTRIBUTE_NOW")]).status == "bad"
    assert ADAPTER._disks([disk("sda", **real, temperature="35", overallstatus="GOOD")]).status == "ok"


def test_other_hypervisors_are_known_too() -> None:
    for vendor, model in (("VMware", "Virtual disk"), ("ATA", "VBOX HARDDISK"), ("Msft", "Virtual Disk")):
        row = ADAPTER._disks([disk("sda", vendor=vendor, model=model, overallstatus="GOOD", temperature="30")]).items[0]
        assert row["status"] == "unknown", (vendor, model)


@respx.mock
async def test_the_disk_list_is_asked_for_everything(ctx: Context) -> None:
    nas = Nas()
    await ADAPTER.fetch("disks", CONFIG, {}, ctx)
    assert nas.calls[0][:3] == ("Smart", "getList", {"start": 0, "limit": -1})


def test_the_disk_card_is_asked_rarely() -> None:
    # ⚠️ Reading SMART can wake sleeping disks.
    assert ADAPTER.widget("disks").refresh_seconds >= 1800


def test_the_demo_fills_every_card() -> None:
    for widget in ADAPTER.widgets:
        for tick in (0, 7, 31):
            data = ADAPTER.demo(widget.kind, {}, tick)
            assert data.items or data.primary, widget.kind
    assert ADAPTER.demo("system", {}, 3).primary["value"] is not None
    assert any(row["value"] == "Not mounted" for row in ADAPTER.demo("filesystems", {}, 0).items)
