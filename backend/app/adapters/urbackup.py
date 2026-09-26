"""UrBackup: which machine is backed up in time, which is not, and what the server is doing.

Measured on 26.09.2026 against UrBackup server 2.5.37 with two clients
2.5.31 in containers, reached over its internet mode: one backed up, one
without any folder chosen, and a third added on the server that never came
online. Three accounts: an administrator, one with the rights status and
progress only, and one with neither.

⚠️ The API is the one the web interface speaks: ``POST /x?a=<action>`` with
form fields, the session in the field ``ses``. Signing in goes in two steps.
``a=salt`` hands out a salt, a random value, the number of PBKDF2 rounds and
the session; the password travels as md5(rnd + PBKDF2-SHA256(md5(salt +
password), salt, rounds)), and the password itself never leaves nexdeck. The
hashing was checked against the live server with a right and a wrong one.

⚠️ A server without any account lets everybody in: ``a=login`` without a
name answers ``success: true``. With an account it answers ``success: false``
and ``admin_only``. An unknown name gets a salt answer without a salt, a
wrong password ``error: 2``.

⚠️ Once, right after a rebuilt server and a run of sign-ins with right,
wrong and unknown names, ``a=salt`` answered ``{"error": 3}`` without a salt
to this machine for between eight and fifteen minutes, while the server's own
host was let in. Eleven wrong passwords and seven unknown names in a row did
not bring it back, and UrBackup's source has no lock after failed sign-ins,
only a line in the system log. The adapter names it as a refusal of the
moment, not as a wrong name.

⚠️ A session that has gone stale is not refused with a status code: every
action answers 200 with ``{"error": 1}``. The adapter signs in again once and
asks again.

⚠️ A user without the right ``status`` is not refused either: the list of
clients comes back empty, the same as a server with no clients. The rights
are in the answer to the sign-in, so the adapter reads them there.

⚠️ ``lastacts``, the finished backups, comes only with an administrator's
rights; a user with ``progress`` sees what is running and nothing else.

⚠️ ``file_ok`` and ``image_ok`` are the server's own judgement against the
intervals set in it. Image backups do not exist for Linux clients
(``image_not_supported``) and are off for internet clients by default, so a
missing image counts only for a client that has had one, or when the card
is told to expect them.
"""

from __future__ import annotations

import hashlib
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
    ago,
    base_url,
    human_bytes,
    human_rate,
)

SESSION = "urbackup_session"
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
#: What a running process or a finished backup was, by UrBackup's numbers.
ACTION = {1: "Incremental file backup", 2: "Full file backup", 3: "Incremental image backup", 4: "Full image backup",
          5: "Resumed incremental file backup", 6: "Resumed full file backup"}
RIGHTS_HINT = "Give the user the rights status and progress in UrBackup under Settings > Users."
LOCK_HINT = "It lifted by itself after a few minutes when this was measured."


def _hashed(salt: dict[str, Any], password: str) -> str:
    """The password as the web interface sends it; see the top of the file."""
    inner = hashlib.md5((str(salt["salt"]) + password).encode()).digest()
    rounds = int(salt.get("pbkdf2_rounds") or 0)
    token = hashlib.pbkdf2_hmac("sha256", inner, str(salt["salt"]).encode(), rounds).hex() if rounds > 0 else inner.hex()
    return hashlib.md5((str(salt["rnd"]) + token).encode()).hexdigest()


def _kind(image: Any, incremental: Any, resumed: Any = 0) -> str:
    word = ("incremental " if incremental else "full ") + ("image backup" if image else "file backup")
    return f"Resumed {word}" if resumed else word.capitalize()


class UrBackupAdapter(Adapter):
    kind = "urbackup"
    label = "UrBackup"
    category = "hosts"
    description = "Which machines UrBackup has backed up in time and which it has not, and the backups running and finished."
    icon = "urbackup"
    beta = False
    docs_url = "https://www.urbackup.org/administration_manual.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://urbackup:55414"),
        Field("username", "Username", help="An account of UrBackup's web interface with the rights status and progress. "
                                            "Empty when UrBackup has no account at all."),
        Field("password", "Password", type="password", secret=True),
    )
    widgets = (
        WidgetType(kind="summary", label="UrBackup overview",
                   description="How many machines are backed up in time, with those overdue, never backed up, online and running now.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("clients_overdue",),
                   parts=(("overdue", "Overdue"), ("never", "Never backed up"), ("online", "Online"), ("running", "Running now")),
                   options=(Field("expect_images", "Expect image backups", type="bool", default=False,
                                  help="Count a missing image backup even for a machine that never had one."),)),
        WidgetType(kind="clients", label="Machines",
                   description="Every machine with its last file and image backup, the overdue ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120,
                   options=(Field("expect_images", "Expect image backups", type="bool", default=False,
                                  help="Count a missing image backup even for a machine that never had one."),)),
        WidgetType(kind="activity", label="Backups",
                   description="What is being backed up right now, with how far it is, and the backups that finished last.",
                   renderer="list", default_size=(3, 3), refresh_seconds=30,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    # -- talking to UrBackup -------------------------------------------------

    async def _post(self, config: dict[str, Any], ctx: Context, action: str, form: dict[str, Any]) -> Any:
        response = await ctx.request("POST", f"{base_url(config)}/x", params={"a": action}, data=form, timeout=15.0, auth_errors=False)
        if response.status_code >= 400:
            raise AdapterError(f"UrBackup answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of UrBackup's web interface, port 55414 by default.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("This address answers with something other than UrBackup.", code="not_urbackup",
                               hint="Check the URL; it is the address of UrBackup's web interface, port 55414 by default.") from error

    async def _sign_in(self, config: dict[str, Any], ctx: Context) -> tuple[str, dict[str, Any]]:
        user = str(config.get("username") or "").strip()
        if not user:
            answer = await self._post(config, ctx, "login", {})
            if not isinstance(answer, dict) or not answer.get("success"):
                raise AuthFailed("UrBackup asks for sign-in. Add a user and its password.")
            return str(answer.get("session") or ""), answer
        salt = await self._post(config, ctx, "salt", {"username": user})
        if not isinstance(salt, dict) or not salt.get("ses"):
            raise AdapterError("This address answers, but not the way UrBackup does.", code="not_urbackup")
        if salt.get("error") == 3:
            # ⚠️ Not an unknown name; see the top of the file.
            raise AdapterError("UrBackup turns sign-ins from here away for the moment.", code="locked", hint=LOCK_HINT)
        if "salt" not in salt:
            raise AuthFailed("UrBackup knows no user of that name.")
        answer = await self._post(config, ctx, "login", {"username": user, "password": _hashed(salt, str(config.get("password") or "")),
                                                         "ses": salt["ses"]})
        if not isinstance(answer, dict) or not answer.get("success"):
            raise AuthFailed("UrBackup rejected the password.")
        return str(salt["ses"]), answer

    async def _session(self, config: dict[str, Any], ctx: Context, *, fresh: bool = False) -> tuple[str, dict[str, Any]]:
        who = (base_url(config), str(config.get("username") or ""), str(config.get("password") or ""))
        held = ctx.cache.get(SESSION)
        if not fresh and isinstance(held, tuple) and held[0] == who:
            return held[1], held[2]
        session, answer = await self._sign_in(config, ctx)
        ctx.cache[SESSION] = (who, session, answer)
        return session, answer

    async def _ask(self, config: dict[str, Any], ctx: Context, action: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """An action's answer and the rights of the session that asked."""
        session, rights = await self._session(config, ctx)
        answer = await self._post(config, ctx, action, {"ses": session})
        if isinstance(answer, dict) and answer.get("error") == 1:
            # ⚠️ A stale session: 200 and error 1, nothing else.
            session, rights = await self._session(config, ctx, fresh=True)
            answer = await self._post(config, ctx, action, {"ses": session})
        if not isinstance(answer, dict) or answer.get("error") == 1:
            raise AdapterError("UrBackup does not accept the session.", code="session_refused")
        return answer, rights

    async def _clients(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer, rights = await self._ask(config, ctx, "status")
        # ⚠️ Without the right the list is simply empty.
        if rights.get("status") == "none":
            raise AdapterError("The user may not see the status of the machines.", code="forbidden", hint=RIGHTS_HINT)
        return [one for one in answer.get("status") or [] if isinstance(one, dict)]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        answer, rights = await self._ask(config, ctx, "status")
        if rights.get("status") == "none":
            raise AdapterError("The user may not see the status of the machines.", code="forbidden", hint=RIGHTS_HINT)
        version = str(answer.get("curr_version_str") or "")
        return f"UrBackup {version or 'answers'}{' answers' if version else ''}; it knows {len(answer.get('status') or [])} machine(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "activity":
            answer, rights = await self._ask(config, ctx, "progress")
            if rights.get("progress") == "none":
                raise AdapterError("The user may not see the backups.", code="forbidden", hint=RIGHTS_HINT)
            return self._activity(answer, int(options.get("limit") or 8), time.time())
        clients = await self._clients(config, ctx)
        rows = self._client_rows(clients, expect_images=options.get("expect_images") is True, now=time.time())
        if widget_kind == "clients":
            return rows
        return self._summary(clients, rows)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _client_rows(clients: list[dict[str, Any]], *, expect_images: bool, now: float) -> WidgetData:
        rows = []
        for client in clients:
            file_last = int(client.get("lastbackup") or 0)
            image_last = int(client.get("lastbackup_image") or 0)
            images_count = not client.get("image_not_supported") and (expect_images or image_last > 0)
            running = [one for one in client.get("processes") or [] if isinstance(one, dict)]
            parts: list[str] = []
            if running:
                done = int(running[0].get("pcdone") or 0)
                parts += [ACTION.get(int(running[0].get("action") or 0), "Backup"), f"{max(0, done)} %"]
                status = "ok"
            elif client.get("no_backup_paths"):
                parts.append("No folders chosen")
                status = "warn"
            elif not file_last:
                parts.append("Never backed up")
                status = "warn"
            elif not client.get("file_ok"):
                parts.append("File backup overdue")
                status = "bad"
            else:
                status = "ok"
            if file_last:
                parts.append(f"File backup {ago(file_last, now)} ago")
            if images_count:
                if image_last:
                    parts.append(f"Image backup {ago(image_last, now)} ago")
                if not client.get("image_ok"):
                    parts.append("Image backup overdue" if image_last else "No image backup yet")
                    if status == "ok" and not running:
                        status = "bad" if image_last else "warn"
            if not client.get("online"):
                seen = ago(client.get("lastseen"), now) if client.get("lastseen") else ""
                parts.append(f"Offline, last seen {seen} ago" if seen and client.get("client_version_string") else "Offline")
            rows.append({"title": str(client.get("name") or "?"), "subtitle": " · ".join(parts), "status": status})
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"].lower()))
        return WidgetData(
            status="bad" if any(row["status"] == "bad" for row in rows) else "warn" if any(row["status"] == "warn" for row in rows)
            else "ok" if rows else "unknown",
            items=rows,
            meta={"empty": "UrBackup knows no machine yet."},
        )

    @staticmethod
    def _summary(clients: list[dict[str, Any]], rows: WidgetData) -> WidgetData:
        overdue = sum(1 for row in rows.items if row["status"] == "bad")
        never = sum(1 for client in clients if not int(client.get("lastbackup") or 0))
        fine = sum(1 for row in rows.items if row["status"] == "ok")
        return WidgetData(
            status=rows.status,
            primary={"label": "Backed up in time", "value": fine, "unit": f"/ {len(clients)}"},
            secondary=[
                {"label": "Overdue", "value": overdue, "part": "overdue"},
                {"label": "Never backed up", "value": never, "part": "never"},
                {"label": "Online", "value": sum(1 for client in clients if client.get("online")), "part": "online"},
                {"label": "Running now", "value": sum(1 for client in clients if client.get("processes")), "part": "running"},
            ],
            metrics={"clients_overdue": float(overdue)},
        )

    @staticmethod
    def _activity(answer: dict[str, Any], limit: int, now: float) -> WidgetData:
        rows = []
        for process in answer.get("progress") or []:
            if not isinstance(process, dict):
                continue
            parts = [ACTION.get(int(process.get("action") or 0), "Backup"), f"{max(0, int(process.get('pcdone') or 0))} %"]
            speed = float(process.get("speed_bpms") or 0) * 1000
            if speed > 0:
                parts.append(human_rate(speed))
            eta = int(process.get("eta_ms") or 0)
            # ⚠️ Negative while UrBackup cannot tell yet.
            if eta > 0:
                parts.append(f"{max(1, round(eta / 60000))} min left")
            rows.append({"title": str(process.get("name") or "?"), "subtitle": " · ".join(parts), "status": "ok",
                         "progress": float(max(0, int(process.get("pcdone") or 0)))})
        finished = answer.get("lastacts")
        for act in finished if isinstance(finished, list) else []:
            if not isinstance(act, dict):
                continue
            if act.get("restore"):
                what = "Restore"
            else:
                what = _kind(act.get("image"), act.get("incremental"), act.get("resumed"))
            parts = [what, "Deleted"] if act.get("del") else [what]
            parts.append(human_bytes(int(act.get("size_bytes") or 0)))
            rows.append({"title": str(act.get("name") or "?"), "subtitle": " · ".join(parts),
                         "value": f"{ago(act.get('backuptime'), now)} ago" if act.get("backuptime") else "",
                         "status": "unknown" if act.get("del") else "ok"})
        # ⚠️ Only an administrator is given the finished ones.
        notice = "" if isinstance(finished, list) else "Finished backups are shown to an administrator only."
        return WidgetData(
            status="ok",
            items=rows[:max(1, limit)],
            meta={"empty": "Nothing is running." if not isinstance(finished, list) else "No backup yet.", "notice": notice},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        late = fake.flicker("urbackup-late", tick, 0.25)
        running = tick % 4 != 3
        clients = [
            {"name": "workstation", "online": True, "file_ok": True, "image_ok": True, "lastbackup": now - 5400, "lastbackup_image": now - 86400 * 2,
             "client_version_string": "2.5.31", "processes": [{"action": 1, "pcdone": 20 + tick % 70}] if running else []},
            {"name": "laptop", "online": False, "file_ok": not late, "image_ok": False, "lastbackup": now - (86400 * 3 if late else 20000),
             "lastbackup_image": 0, "lastseen": now - 86400, "client_version_string": "2.5.31"},
            {"name": "nas", "online": True, "file_ok": True, "image_ok": False, "image_not_supported": True, "lastbackup": now - 3000,
             "lastbackup_image": 0, "client_version_string": "2.5.31"},
            {"name": "raspberry", "online": True, "file_ok": False, "lastbackup": 0, "no_backup_paths": True, "client_version_string": "2.5.31"},
        ]
        if widget_kind == "activity":
            return self._activity({
                "progress": [{"name": "workstation", "action": 1, "pcdone": 20 + tick % 70, "speed_bpms": 4200, "eta_ms": 540000}] if running else [],
                "lastacts": [
                    {"name": "nas", "image": 0, "incremental": 1, "size_bytes": 380_000_000, "backuptime": now - 3000},
                    {"name": "workstation", "image": 1, "incremental": 1, "size_bytes": 4_100_000_000, "backuptime": now - 86400 * 2},
                    {"name": "laptop", "image": 0, "incremental": 0, "size_bytes": 12_600_000_000, "backuptime": now - 86400 * 4},
                ]}, int(options.get("limit") or 8), now)
        rows = self._client_rows(clients, expect_images=options.get("expect_images") is True, now=now)
        return rows if widget_kind == "clients" else self._summary(clients, rows)


ADAPTER = UrBackupAdapter()
