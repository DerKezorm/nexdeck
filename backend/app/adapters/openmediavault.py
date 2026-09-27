"""openmediavault: the NAS itself, its file systems with how full they are, and what SMART says about its disks.

Measured on 27.09.2026 against openmediavault 8.5.9-1 (Synchrony) on Debian
13, installed from openmediavault's own package source into a virtual
machine with three disks: the system disk and one data disk on a virtual
SCSI controller, one data disk on a virtual SATA controller. An ext4 file
system mounted and a third full, an XFS file system not mounted. Three
accounts: ``admin``, a user in the group ``openmediavault-admin`` and a
plain user.

⚠️ The way in is the one the web interface takes: ``POST /rpc.php`` with
``{"service", "method", "params"}``. ``Session.login`` answers with the
session in the cookie ``OPENMEDIAVAULT-SESSIONID`` (not
``X-OPENMEDIAVAULT-SESSIONID``, which older write-ups name; that one is
not looked at). The adapter sends the cookie itself on every call.

⚠️ A wrong password and an unknown user are the same answer, HTTP 400
"Incorrect username or password.". A call without a valid session is 401
"Session not authenticated.". After five idle minutes (the timeout set under
Workbench) the first call answers 401 "Session expired." and every later one
"Session not authenticated.", because the first one threw the session away.
The adapter signs in once more on any 401 and asks again.

⚠️ Three wrong passwords within five minutes lock the account for good.
openmediavault's own PAM rules say ``pam_faillock deny=3 fail_interval=300
unlock_time=0``; measured: after four refused sign-ins (a test and three
cards) the right password was refused too, with the same 400, until
``faillock --user admin --reset``. So the adapter does not try a refused
password again for 15 minutes, and a changed one at once.

⚠️ Only an administrator can read the cards: a user in the group
``openmediavault-admin`` (``admin`` is one). Every other user may sign in to
the web interface, and every call the cards make answers 403 "Invalid context
role.", except ``System.getInformation``: that one answers 200 with only the
time and the host name, and leaves out everything else without saying why.
The sign-in says which it is, ``permissions.role`` is ``admin`` or ``user``,
and the adapter goes by that.

⚠️ Each sign-in from what openmediavault takes for a new browser can send the
user a mail ("Your user account was used to log in"), when notifications are
set up. What makes a browser known is a second cookie,
``OPENMEDIAVAULT-LOGIN-<hash>``, set with the first sign-in and good for 60
days. The adapter keeps it and sends it along with every later sign-in;
measured: with it the sign-in sets no new one, without it it does.

⚠️ Sending the session of one user with the sign-in of another is refused,
400 "Another user is already authenticated.". The adapter never sends the old
session with a sign-in.

⚠️ Units differ within one answer. ``cpuUtilization`` is a number in per
cent (0.99 on an idle machine), ``memUtilization`` a string holding a
fraction ("0.16989"), and the memory sizes are strings of bytes. The card
works memory out from ``memTotal`` and ``memAvailable``. The count of
updates is what apt knew at its last refresh: 0 on the fresh machine, 32
once apt had fetched its lists.

⚠️ In the file system list ``size`` and ``available`` are strings of bytes,
and ``used`` is text for the eye ("2.54 GiB"). Size less available would
count the blocks ext4 keeps for root as used; the adapter reads the text.
A file system that is not mounted has ``-1`` for size, available and the
percentage, which means unknown and not a negative number.

⚠️ SMART comes from ``smartctl --xall`` on every disk each time the list is
asked for, and with openmediavault's default power mode "never" that wakes
sleeping disks (from the source; a virtual disk does not sleep). So the disk
card asks every half hour. A disk on the virtual
SCSI controller answered ``BAD_STATUS`` although ``smartctl -H`` said OK:
``--xall`` prints no health line for it, and openmediavault reads a missing
line as a failure. The same status is what openmediavault reports when
reading SMART failed altogether. A disk of a hypervisor (QEMU, VMware,
VirtualBox, Hyper-V) shows made-up values at best, so the card says
"not available" for it instead of good or bad. A disk without SMART does
not appear in the list at all; openmediavault leaves out VirtIO block disks
on purpose. A temperature of 0 is none.

⚠️ openmediavault 8 can ask for a second step at sign-in
(``status: challengeRequired``) when a plugin for it is installed. That is
from the source, not measured; the adapter says to use an account without
one.
"""

from __future__ import annotations

import re
import time
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    percent,
    percent_text,
    status_from_percent,
    worst,
)

SESSION = "openmediavault_session"
MARKERS = "openmediavault_login_markers"
SESSION_COOKIE = "OPENMEDIAVAULT-SESSIONID"
MARKER_PREFIX = "OPENMEDIAVAULT-LOGIN-"
REFUSED = "openmediavault_refused"
#: How long a refused password is not tried again. openmediavault locks an
#: account for good after three failures within five minutes; one attempt in
#: this long can never be three of them.
REFUSED_SECONDS = 900.0
LOCK_HINT = ("Check the password. After three wrong ones within five minutes openmediavault locks the account until "
             "an administrator runs faillock --user <name> --reset on it, and while it is locked the right password is "
             "refused as well. nexdeck tries a refused password again only every 15 minutes.")
ADMIN_HINT = "Use admin, or add the user to the group openmediavault-admin under Users > Users."
URL_HINT = "Check the URL; it is the address of openmediavault's web interface."
#: Above this a file system is filling up, as on the other NAS cards.
FULL_PERCENT = 90.0
#: Optical media are file systems to openmediavault too; nobody wants them on a card.
SKIPPED_TYPES = {"iso9660", "udf"}
#: What openmediavault's SMART verdicts mean, and the colour of each.
VERDICT = {
    "GOOD": ("Good", "ok"),
    "BAD_ATTRIBUTE_IN_THE_PAST": ("Attribute failed in the past", "warn"),
    "BAD_SECTOR": ("Bad sectors", "warn"),
    "BAD_ATTRIBUTE_NOW": ("Attribute failing now", "bad"),
    "BAD_SECTOR_MANY": ("Many bad sectors", "bad"),
    "BAD_STATUS": ("Failed or unreadable", "bad"),
}
#: How a hypervisor names the disks it makes up.
VIRTUAL = re.compile(r"\b(qemu|vmware|vbox|virtualbox|virtual disk|msft virtual)\b", re.IGNORECASE)
UNITS = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4, "PIB": 1024**5, "EIB": 1024**6}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
SYSTEM_PARTS = (("cpu", "CPU"), ("memory", "Memory"), ("load", "Load"), ("uptime", "Uptime"),
                ("updates", "Updates"), ("version", "Version"))


class Expired(Exception):
    """A 401: no session, or one that ran out."""


def _refused() -> AuthFailed:
    error = AuthFailed("openmediavault rejected the user or the password.")
    error.hint = LOCK_HINT
    return error


def _number(value: Any) -> float | None:
    """A number openmediavault may have sent as a string; None for nothing or garbage."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bytes_of(text: Any) -> float | None:
    """``"2.54 GiB"`` in bytes. A plain number is taken as it is, in case a later version sends one."""
    plain = _number(text)
    if plain is not None:
        return plain if plain >= 0 else None
    found = re.fullmatch(r"\s*([\d.]+)\s*([KMGTPE]?i?B)\s*", str(text or ""), re.IGNORECASE)
    if not found:
        return None
    unit = found.group(2).upper()
    factor = UNITS.get(unit) or UNITS.get(unit.replace("B", "IB")) or 1
    return float(found.group(1)) * factor


def _said(answer: Any) -> str:
    error = answer.get("error") if isinstance(answer, dict) else None
    return " ".join(str(error.get("message") or "").split())[:240] if isinstance(error, dict) else ""


class OpenMediaVaultAdapter(Adapter):
    kind = "openmediavault"
    label = "openmediavault"
    category = "nas"
    description = "CPU, memory, load and updates of the NAS, its file systems with how full they are, and the SMART state of its disks."
    icon = "openmediavault"
    #: Every card against openmediavault 8.5.9-1 with an administrator and a plain user, 27.09.2026.
    beta = False
    docs_url = "https://docs.openmediavault.org/en/stable/development/tools/omv_rpc.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://openmediavault.local"),
        Field("username", "Username", default="admin",
              help="admin, or a user in the group openmediavault-admin. Other users may not read the cards."),
        Field("password", "Password", type="password", secret=True, required=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False,
              help="openmediavault over HTTPS often comes with a certificate of its own making."),
    )
    widgets = (
        WidgetType(kind="system", label="System",
                   description="CPU, memory, load, uptime, waiting updates and the version.",
                   renderer="stats", default_size=(4, 2), refresh_seconds=30, metrics=("cpu", "memory"),
                   parts=SYSTEM_PARTS),
        WidgetType(kind="filesystems", label="File systems",
                   description="Every file system with how full it is, its type and whether it is mounted.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   parts=(("subtitle", "Type and size"), ("progress", "Usage bar"), ("value", "Percentage"))),
        WidgetType(kind="disks", label="Disks",
                   description="Every disk with its SMART state and temperature. Asked every half hour, "
                               "because reading SMART can wake sleeping disks.",
                   renderer="list", default_size=(3, 3), refresh_seconds=1800),
    )

    # -- talking to openmediavault -------------------------------------------

    async def _post(self, config: dict[str, Any], ctx: Context, body: dict[str, Any], cookies: dict[str, str]) -> tuple[Any, Any]:
        """The answer and the response it came in; HTTP errors other than 400, 401, 403 and 429 end here."""
        headers = {"Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())} if cookies else None
        response = await ctx.request("POST", f"{base_url(config)}/rpc.php", json_body=body, headers=headers,
                                     verify=not config.get("insecure"), timeout=30.0, auth_errors=False)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than openmediavault.", code="not_openmediavault",
                               hint=URL_HINT) from error
        if not isinstance(answer, dict) or "response" not in answer:
            raise AdapterError("This address answers, but not the way openmediavault does.", code="not_openmediavault", hint=URL_HINT)
        return answer, response

    async def _sign_in(self, config: dict[str, Any], ctx: Context) -> tuple[str, str]:
        """A fresh session and the role it has; see the top of the file for the cookies."""
        who = (base_url(config), str(config.get("username") or "admin"))
        tried = (*who, str(config.get("password") or ""))
        refused = ctx.cache.get(REFUSED)
        if isinstance(refused, tuple) and refused[0] == tried and refused[1] > time.monotonic():
            # ⚠️ Not again yet: each try counts towards the lock.
            raise _refused()
        markers = ctx.cache.get(MARKERS)
        sent = dict(markers[1]) if isinstance(markers, tuple) and markers[0] == who else {}
        # ⚠️ Never the old session: another user's is refused.
        answer, response = await self._post(config, ctx, {"service": "Session", "method": "login",
                                                          "params": {"username": who[1], "password": str(config.get("password") or "")}}, sent)
        if response.status_code == 429:
            raise AdapterError("openmediavault turns sign-ins of this user away for the moment.", code="locked",
                               hint="Too many failed attempts at the second step; it lifts by itself.")
        if response.status_code in (400, 401):
            ctx.cache[REFUSED] = (tried, time.monotonic() + REFUSED_SECONDS)
            raise _refused()
        if response.status_code >= 300:
            raise AdapterError(f"openmediavault answered the sign-in with HTTP {response.status_code}: {_said(answer)}", code="http_error")
        result = answer.get("response") if isinstance(answer.get("response"), dict) else {}
        if result.get("status") == "challengeRequired":
            raise AdapterError("openmediavault asks this user for a second step at sign-in.", code="second_factor",
                               hint="Use an administrator account without a second step for the cards.")
        session = str(response.cookies.get(SESSION_COOKIE) or result.get("sessionid") or "")
        if result.get("status") != "authenticated" or not session:
            raise AdapterError("openmediavault handed out no session.", code="not_openmediavault", hint=URL_HINT)
        fresh = {name: value for name, value in response.cookies.items() if name.startswith(MARKER_PREFIX)}
        if fresh or not sent:
            ctx.cache[MARKERS] = (who, {**sent, **fresh})
        role = str((result.get("permissions") or {}).get("role") or "user")
        return session, role

    async def _session(self, config: dict[str, Any], ctx: Context, *, fresh: bool = False) -> tuple[str, str]:
        who = (base_url(config), str(config.get("username") or "admin"), str(config.get("password") or ""))
        held = ctx.cache.get(SESSION)
        if not fresh and isinstance(held, tuple) and held[0] == who:
            return held[1], held[2]
        session, role = await self._sign_in(config, ctx)
        ctx.cache[SESSION] = (who, session, role)
        return session, role

    async def _once(self, config: dict[str, Any], ctx: Context, session: str, service: str, method: str, params: Any) -> Any:
        answer, response = await self._post(config, ctx, {"service": service, "method": method, "params": params, "options": None},
                                            {SESSION_COOKIE: session})
        if response.status_code == 401:
            raise Expired
        if response.status_code == 403:
            raise AdapterError(f"The user may not call {service}.{method}: {_said(answer) or 'refused'}", code="forbidden", hint=ADMIN_HINT)
        if response.status_code == 404:
            raise AdapterError(f"This openmediavault does not know {service}.{method}.", code="not_found")
        if response.status_code >= 300 or answer.get("error"):
            raise AdapterError(f"openmediavault answered {service}.{method} with an error: {_said(answer) or response.status_code}",
                               code="rpc_error")
        return answer.get("response")

    async def _call(self, config: dict[str, Any], ctx: Context, service: str, method: str, params: Any = None) -> Any:
        session, role = await self._session(config, ctx)
        if role != "admin":
            # ⚠️ Measured: nothing the cards read is open to a plain user.
            raise AdapterError("The user may sign in to openmediavault but is not an administrator.", code="forbidden", hint=ADMIN_HINT)
        try:
            return await self._once(config, ctx, session, service, method, params)
        except Expired:
            pass
        # ⚠️ Run out after the idle timeout: one more sign-in, then once more.
        session, role = await self._session(config, ctx, fresh=True)
        if role != "admin":
            raise AdapterError("The user may sign in to openmediavault but is not an administrator.", code="forbidden", hint=ADMIN_HINT)
        try:
            return await self._once(config, ctx, session, service, method, params)
        except Expired as error:
            raise AdapterError("openmediavault does not accept the session it just handed out.", code="session_refused") from error

    async def _information(self, config: dict[str, Any], ctx: Context) -> dict[str, Any]:
        info = await self._call(config, ctx, "System", "getInformation")
        info = info if isinstance(info, dict) else {}
        if "version" not in info:
            # ⚠️ What a plain user gets: time and host name, nothing else.
            raise AdapterError("openmediavault gave this user only the host name.", code="forbidden", hint=ADMIN_HINT)
        return info

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._information(config, ctx)
        return f"openmediavault {info.get('version') or '?'} answers on {info.get('hostname') or '?'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "filesystems":
            return self._filesystems(await self._call(config, ctx, "FileSystemMgmt", "enumerateFilesystems") or [])
        if widget_kind == "disks":
            listing = await self._call(config, ctx, "Smart", "getList", {"start": 0, "limit": -1}) or {}
            return self._disks(listing.get("data") if isinstance(listing, dict) else listing)
        return self._system(await self._information(config, ctx))

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _system(info: dict[str, Any]) -> WidgetData:
        cpu = _number(info.get("cpuUtilization"))
        cpu = round(cpu, 1) if cpu is not None else None
        total, available = _number(info.get("memTotal")), _number(info.get("memAvailable"))
        memory = percent(total - available, total) if total and available is not None else None
        if memory is None and _number(info.get("memUtilization")) is not None:
            # ⚠️ A fraction, not per cent.
            memory = round(100.0 * float(_number(info.get("memUtilization")) or 0), 1)
        load = info.get("loadAverage") if isinstance(info.get("loadAverage"), dict) else {}
        loads = [_number(load.get(key)) for key in ("1min", "5min", "15min")]
        updates = int(_number(info.get("availablePkgUpdates")) or 0)
        version = str(info.get("version") or "?").split(" (")[0]
        chips = [
            {"label": "Memory", "value": memory, "unit": "%" if memory is not None else "", "metric": "memory", "part": "memory"},
            {"label": "Load", "value": " / ".join(f"{one:.2f}" for one in loads if one is not None) or "?", "part": "load"},
            {"label": "Uptime", "value": duration_short(_number(info.get("uptime"))), "part": "uptime"},
            {"label": "Updates", "value": updates, "part": "updates"},
            {"label": "Version", "value": version, "part": "version"},
        ]
        if info.get("rebootRequired") is True:
            chips.append({"label": "Reboot", "value": "Required"})
        status = status_from_percent(worst(cpu, memory))
        if status == "ok" and info.get("rebootRequired") is True:
            status = "warn"
        return WidgetData(
            status=status,
            primary={"label": "CPU", "value": cpu, "unit": "%" if cpu is not None else "", "part": "cpu"},
            secondary=chips,
            metrics={name: value for name, value in (("cpu", cpu), ("memory", memory)) if value is not None},
        )

    @staticmethod
    def _filesystems(found: Any) -> WidgetData:
        rows = []
        for fs in found if isinstance(found, list) else []:
            if not isinstance(fs, dict) or str(fs.get("type") or "").lower() in SKIPPED_TYPES:
                continue
            kind = str(fs.get("type") or "?").upper()
            device = str(fs.get("canonicaldevicefile") or fs.get("devicefile") or "")
            title = str(fs.get("label") or fs.get("devicename") or device or "?")
            if not fs.get("mounted"):
                # ⚠️ -1 everywhere: nothing measured.
                subtitle = " · ".join(part for part in (kind, device if fs.get("label") else "") if part)
                rows.append({"title": title, "subtitle": subtitle, "value": "Not mounted", "status": "unknown"})
                continue
            size = _number(fs.get("size"))
            size = size if size is not None and size > 0 else None
            used = _bytes_of(fs.get("used"))
            share = _number(fs.get("percentage"))
            share = share if share is not None and share >= 0 else percent(used, size)
            parts = [kind]
            if used is not None and size is not None:
                parts.append(f"{human_bytes(used)} of {human_bytes(size)}")
            if fs.get("mountpoint") == "/":
                parts.append("System")
            elif device and fs.get("label"):
                parts.append(device)
            rows.append({"title": title, "subtitle": " · ".join(parts), "progress": share, "value": percent_text(share),
                         "status": "unknown" if share is None else "warn" if share >= FULL_PERCENT else "ok"})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), str(row["title"]).lower()))
        return WidgetData(
            status="warn" if any(row["status"] == "warn" for row in rows) else "ok" if rows else "unknown",
            items=rows,
            meta={"empty": "openmediavault reports no file system."},
        )

    @staticmethod
    def _disks(found: Any) -> WidgetData:
        rows = []
        for disk in found if isinstance(found, list) else []:
            if not isinstance(disk, dict):
                continue
            model = str(disk.get("model") or "").strip()
            size = _number(disk.get("size"))
            parts = [part for part in (model, human_bytes(size) if size else "") if part]
            if VIRTUAL.search(f"{disk.get('vendor') or ''} {model}"):
                # ⚠️ A hypervisor's disk: whatever SMART says is made up.
                parts.append("Virtual disk, SMART not available")
                rows.append({"title": str(disk.get("devicename") or disk.get("devicefile") or "?"), "subtitle": " · ".join(parts),
                             "value": "", "status": "unknown"})
                continue
            verdict = str(disk.get("overallstatus") or "")
            word, status = VERDICT.get(verdict, (verdict.replace("_", " ").capitalize() or "Unknown", "unknown"))
            parts.append(word)
            temperature = _number(disk.get("temperature"))
            rows.append({"title": str(disk.get("devicename") or disk.get("devicefile") or "?"), "subtitle": " · ".join(parts),
                         # ⚠️ 0 is openmediavault's word for "none".
                         "value": f"{temperature:.0f} °C" if temperature and temperature > 0 else "", "status": status})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), str(row["title"])))
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "warn" if any(row["status"] == "warn" for row in rows)
            else "ok" if any(row["status"] == "ok" for row in rows) else "unknown",
            items=rows,
            meta={"empty": "openmediavault reports no disk with SMART."},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        gib = 1024**3
        if widget_kind == "filesystems":
            media = fake.walk("omv-media", tick, 86, 93, period=900)
            return self._filesystems([
                {"devicename": "sda1", "canonicaldevicefile": "/dev/sda1", "label": "", "type": "ext4", "mounted": True, "mountpoint": "/",
                 "used": "6.12 GiB", "available": str(int(21.4 * gib)), "size": str(int(29.1 * gib)), "percentage": 22},
                {"devicename": "md0", "canonicaldevicefile": "/dev/md0", "label": "media", "type": "ext4", "mounted": True,
                 "mountpoint": "/srv/dev-disk-by-label-media", "used": f"{media / 100 * 7.2:.2f} TiB",
                 "available": str(int((100 - media) / 100 * 7.2 * 1024 * gib)), "size": str(int(7.2 * 1024 * gib)), "percentage": round(media)},
                {"devicename": "sdd1", "canonicaldevicefile": "/dev/sdd1", "label": "backup", "type": "btrfs", "mounted": True,
                 "mountpoint": "/srv/dev-disk-by-label-backup", "used": "1.31 TiB", "available": str(int(2.3 * 1024 * gib)),
                 "size": str(int(3.64 * 1024 * gib)), "percentage": 36},
                {"devicename": "sde1", "canonicaldevicefile": "/dev/sde1", "label": "spare", "type": "xfs", "mounted": False,
                 "used": "-1", "available": "-1", "size": "-1", "percentage": -1},
            ])
        if widget_kind == "disks":
            aging = fake.flicker("omv-sector", tick, 0.2)
            return self._disks([
                {"devicename": "sda", "model": "Samsung SSD 870 EVO 250GB", "vendor": "ATA", "size": str(250_059_350_016), "temperature": "31",
                 "overallstatus": "GOOD"},
                {"devicename": "sdb", "model": "WDC WD40EFRX-68N32N0", "vendor": "ATA", "size": str(4_000_787_030_016),
                 "temperature": str(int(fake.walk("omv-sdb", tick, 35, 39, period=900))), "overallstatus": "GOOD"},
                {"devicename": "sdc", "model": "WDC WD40EFRX-68N32N0", "vendor": "ATA", "size": str(4_000_787_030_016),
                 "temperature": str(int(fake.walk("omv-sdc", tick, 36, 40, period=900))), "overallstatus": "BAD_SECTOR" if aging else "GOOD"},
                {"devicename": "sdd", "model": "ST4000VN006-3CW104", "vendor": "ATA", "size": str(4_000_787_030_016), "temperature": "34",
                 "overallstatus": "GOOD"},
            ])
        return self._system({
            "hostname": "nas", "version": "8.5.9-1 (Synchrony)",
            "cpuUtilization": fake.walk("omv-cpu", tick, 3, 24), "memTotal": str(16 * gib),
            "memAvailable": str(int((100 - fake.walk("omv-memory", tick, 22, 30, period=600)) / 100 * 16 * gib)),
            "uptime": 19 * 86400 + tick * 30, "loadAverage": {"1min": 0.42, "5min": 0.38, "15min": 0.31},
            "availablePkgUpdates": 3, "rebootRequired": False,
        })


ADAPTER = OpenMediaVaultAdapter()
