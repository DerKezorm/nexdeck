"""Duplicati: whether every backup job ran lately, and why the last try failed.

Measured against Duplicati 2.4.0.0 on 11.09.2026: one job to a local folder,
one to an FTP server that does not exist, and one that failed first and ran
fine after its target was fixed.

⚠️ A good run does not clear an earlier failure. The job that failed and
then ran fine still carried ``LastErrorDate`` and ``LastErrorMessage`` next
to its new ``LastBackupFinished``. A job has failed only when its error is
newer than its last good backup. The server's ``HasError`` stays on for the
same reason until someone dismisses the notification, so the cards do not
read it.

⚠️ Times are written without separators: ``20260911T090333Z``.

⚠️ The API wants a bearer token from ``/api/v1/auth/login``, which lasted 900
seconds. Duplicati before 2.1 signed in differently and is not supported.

The backup list carries no warnings, so neither do the cards.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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
)

TOKEN = "duplicati_token"
#: Measured lifetime 900 seconds; asking again a while before it runs out.
TOKEN_SECONDS = 600


def _moment(raw: Any) -> float:
    """``20260911T090333Z`` as seconds since the epoch; 0 when missing or unreadable."""
    try:
        return datetime.strptime(str(raw or ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return 0.0


def _backup_id(pair: Any) -> str:
    """The backup of a task, from the ``{"Item1": task, "Item2": backup}`` pairs of the server state."""
    return str(pair.get("Item2") or "") if isinstance(pair, dict) else ""


class DuplicatiAdapter(Adapter):
    kind = "duplicati"
    label = "Duplicati"
    category = "nas"
    description = "Whether every backup job ran lately, and why the last try failed."
    icon = "duplicati"
    beta = False
    docs_url = "https://docs.duplicati.com/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://duplicati:8200"),
        Field("password", "Password", type="password", secret=True, required=True, help="The password of Duplicati's web interface."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="backups", label="Backup jobs", description="Every job with its last good backup, failed ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("failed",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Backups", description="How many jobs are fine, and when the last backup finished.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("failed",)),
    )

    async def _token(self, config: dict[str, Any], ctx: Context, fresh: bool = False) -> str:
        cached = ctx.cache.get(TOKEN)
        if not fresh and isinstance(cached, tuple) and cached[1] > time.monotonic():
            return str(cached[0])
        response = await ctx.request("POST", f"{base_url(config)}/api/v1/auth/login", json_body={"Password": str(config.get("password") or "")},
                                     verify=not config.get("insecure"), auth_errors=False)
        # Measured: a wrong password gets 401 {"Error": "Failed to log in"}.
        if response.status_code in (401, 403):
            raise AuthFailed("Duplicati rejected the password.")
        if response.status_code >= 400:
            raise AdapterError(f"Duplicati answered the sign-in with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL. Duplicati before 2.1 signs in differently and is not supported.")
        try:
            token = response.json().get("AccessToken")
        except (ValueError, AttributeError) as error:
            raise AdapterError("This address answers, but not the way Duplicati does.", code="not_duplicati") from error
        if not token:
            raise AdapterError("This address answers, but not the way Duplicati does.", code="not_duplicati")
        ctx.cache[TOKEN] = (str(token), time.monotonic() + TOKEN_SECONDS)
        return str(token)

    async def _json(self, config: dict[str, Any], ctx: Context, path: str) -> Any:
        for attempt in (0, 1):
            token = await self._token(config, ctx, fresh=attempt == 1)
            response = await ctx.request("GET", f"{base_url(config)}/api/v1{path}", headers={"Authorization": f"Bearer {token}"},
                                         verify=not config.get("insecure"), auth_errors=False)
            # A token from before a restart of the server is refused; one new sign-in, then give up.
            if response.status_code != 401 or attempt == 1:
                break
        if response.status_code in (401, 403):
            raise AuthFailed("Duplicati rejected the password.")
        if response.status_code >= 400:
            raise AdapterError(f"Duplicati answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Duplicati did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _state(self, config: dict[str, Any], ctx: Context) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        backups = await self._json(config, ctx, "/backups")
        if not isinstance(backups, list):
            raise AdapterError("This address answers, but not the way Duplicati does.", code="not_duplicati")
        state = await self._json(config, ctx, "/serverstate")
        return [one for one in backups if isinstance(one, dict)], state if isinstance(state, dict) else {}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        backups, _state = await self._state(config, ctx)
        info = await self._json(config, ctx, "/systeminfo")
        version = info.get("ServerVersion") if isinstance(info, dict) else None
        return f"Duplicati {version or '?'} answers with {len(backups)} backup jobs."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        backups, state = await self._state(config, ctx)
        rows = self._rows(backups, state)
        if widget_kind == "summary":
            return self._summary(rows)
        return self._backups(rows, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _rows(backups: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
        running = _backup_id(state.get("ActiveTask"))
        queued = {_backup_id(pair) for pair in state.get("SchedulerQueueIds") or []}
        rows = []
        for entry in backups:
            backup = entry.get("Backup") if isinstance(entry.get("Backup"), dict) else {}
            meta = backup.get("Metadata") if isinstance(backup.get("Metadata"), dict) else {}
            good = _moment(meta.get("LastBackupFinished")) or _moment(meta.get("LastBackupDate"))
            failed_at = _moment(meta.get("LastErrorDate"))
            identifier = str(backup.get("ID") or "")
            if identifier and identifier == running:
                state_word, word, reason = "warn", "Running", ""
            elif failed_at > good:
                state_word, word, reason = "bad", "Failed", " ".join(str(meta.get("LastErrorMessage") or "").split())
            elif identifier in queued:
                state_word, word, reason = "unknown", "Waiting", ""
            elif not good:
                state_word, word, reason = "unknown", "Never run", ""
            else:
                state_word, word, reason = "ok", "", ""
            rows.append({"state": state_word, "good": good, "row": {
                "title": str(backup.get("Name") or "?"),
                "subtitle": " · ".join(part for part in (word, reason[:120]) if part),
                "status": state_word,
                "value": ago(good) if good else "",
            }})
        return rows

    @staticmethod
    def _summary(rows: list[dict[str, Any]]) -> WidgetData:
        failed = sum(1 for one in rows if one["state"] == "bad")
        fine = sum(1 for one in rows if one["state"] == "ok")
        newest = max((one["good"] for one in rows), default=0.0)
        secondary: list[dict[str, Any]] = []
        if failed:
            secondary.append({"label": "Failed", "value": failed})
        if newest:
            secondary.append({"label": "Last backup", "value": ago(newest)})
        return WidgetData(
            status="bad" if failed else "ok" if rows else "unknown",
            primary={"label": "Jobs fine", "value": fine, "unit": f"/ {len(rows)}"},
            secondary=secondary,
            metrics={"failed": float(failed)},
        )

    @staticmethod
    def _backups(rows: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        order = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
        ranked = sorted(rows, key=lambda one: (order.get(one["state"], 9), one["row"]["title"].lower()))
        failed = sum(1 for one in rows if one["state"] == "bad")
        return WidgetData(
            status="bad" if failed else "ok",
            items=[one["row"] for one in ranked][: int(options.get("limit") or 10)],
            secondary=[{"label": "Failed", "value": failed}],
            meta={"empty": "No backup jobs yet."},
            metrics={"failed": float(failed)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        failed = fake.flicker("duplicati-offsite", tick, 0.7)

        def stamp(hours: float) -> str:
            return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(time.time() - hours * 3600))

        offsite = {"LastBackupFinished": stamp(27)}
        if failed:
            offsite |= {"LastErrorDate": stamp(3), "LastErrorMessage": "The remote server returned an error: (530) Not logged in."}
        backups = [
            {"Backup": {"ID": "1", "Name": "Documents", "Metadata": {"LastBackupFinished": stamp(2)}}},
            {"Backup": {"ID": "2", "Name": "Offsite", "Metadata": offsite}},
            {"Backup": {"ID": "3", "Name": "Docker volumes", "Metadata": {"LastBackupFinished": stamp(5)}}},
        ]
        rows = self._rows(backups, {"ActiveTask": None, "SchedulerQueueIds": []})
        if widget_kind == "summary":
            return self._summary(rows)
        return self._backups(rows, options)


ADAPTER = DuplicatiAdapter()
