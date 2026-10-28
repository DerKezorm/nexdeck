"""Zerobyte: every backup schedule with its last run, where it reads from and writes to, and a button that runs it now.

Measured against Zerobyte 0.43.2 (restic inside), on 27.10.2026, with a fresh
container, a directory volume, a local repository and four schedules: one that
ran, one whose folder does not exist, one paused and one with a path that is
not in the volume.

⚠️ The key goes in the header ``X-Api-Key`` and works under ``/api/v1`` only
(Zerobyte 0.40.0 and newer). A wrong key and no key get the same answer, 401
``{"message": "Invalid or expired session"}``. The key is made through the
API itself (``POST /api/v1/auth/api-keys`` with the password of the account),
or under Settings in the interface.

⚠️ A schedule is addressed by its ``shortId`` ("jMGTmi_j", underscores and
dashes happen), never by the number ``id``. ``POST /backups/{shortId}/run``
answers 202 ``{"taskId", "status": "started"}`` at once and the backup runs on
in the background; a second call while it runs is 409 "Backup is already
running for this schedule". A paused schedule can be run by hand.

⚠️ ``lastBackupStatus`` is ``success``, ``error``, ``warning``, ``in_progress``
or null. While a backup runs the status is ``in_progress`` and ``lastBackupAt``
still holds the finished one before it. A schedule on a folder that is gone
never gets a status of its own: the run is refused with 400 and the reason,
the schedule stays null, and the reason sits on the volume (``status`` error,
``lastError``). A schedule that ran into a missing path has ``error`` and a
``lastBackupError`` of several lines, the last one a JSON line of restic.

⚠️ A repository carries ``config`` with its endpoint and bucket, the keys
hidden. The cards read none of it.
"""

from __future__ import annotations

import time
from typing import Any

from . import backup_age
from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    human_bytes,
    path_segment,
)

STATUS_COLOUR = {"success": "ok", "warning": "warn", "error": "bad", "in_progress": "unknown"}
STATUS_WORD = {"error": "Failed", "warning": "Warning", "in_progress": "Running"}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
REPOSITORY_COLOUR = {"healthy": "ok", "error": "bad", "unknown": "unknown", "doctor": "warn", "cancelled": "warn"}
REPOSITORY_WORD = {"error": "Error", "unknown": "Not checked yet", "doctor": "Being repaired", "cancelled": "Check cancelled"}


def _seconds(value: Any) -> float | None:
    """A time Zerobyte writes in milliseconds, in seconds; None when it is missing."""
    try:
        return float(value) / 1000 or None
    except (TypeError, ValueError):
        return None


def _reason(text: Any) -> str:
    """The first line of an error: restic's report ends in a JSON line, and the first says what happened."""
    for line in str(text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("{"):
            return line[:160]
    return ""


def _until(moment: float | None, now: float) -> str:
    if moment is None:
        return ""
    seconds = moment - now
    if seconds <= 0:
        return ""
    if seconds < 3600:
        return f"next in {max(1, round(seconds / 60))} min"
    if seconds < 48 * 3600:
        return f"next in {round(seconds / 3600)} h"
    return f"next in {round(seconds / 86400)} d"


def _named(value: Any) -> str:
    return str(value.get("name") or "") if isinstance(value, dict) else ""


class ZerobyteAdapter(Adapter):
    kind = "zerobyte"
    label = "Zerobyte"
    category = "nas"
    description = "Every backup schedule with its last run, source and destination, and a button that runs it now."
    icon = "zerobyte"
    #: Measured on 2026-10-27 against Zerobyte 0.43.2, not yet an instance in use.
    beta = True
    docs_url = "https://api-docs.zerobyte.app"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://zerobyte:4096"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="From Settings > Personal > API keys in Zerobyte 0.40 or newer. The key may do what its user may, and the cards only read."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
        backup_age.STALE_FIELD,
    )
    widgets = (
        WidgetType(kind="backups", label="Backups",
                   description="Every schedule with its last run, source and destination and when it runs next, failed ones first, with a button that runs it now.",
                   renderer="list", default_size=(4, 3), refresh_seconds=120, metrics=("failed",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Backup summary",
                   description="How many schedules there are, how many are fine, failed, running or paused, and when the last good backup ran.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("failed",)),
        WidgetType(kind="repositories", label="Repositories",
                   description="Every repository with its state, size and snapshots, worst first.",
                   renderer="list", default_size=(3, 2), refresh_seconds=300, metrics=("broken",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, timeout: float = 15.0) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"X-Api-Key": str(config.get("api_key") or "")},
            verify=not config.get("insecure"), timeout=timeout, auth_errors=False, cache_seconds=10,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Zerobyte rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"Zerobyte answered with HTTP {response.status_code}.", code="http_error",
                               hint="Zerobyte 0.40.0 or newer is needed for API keys. Check the URL, it is the address of Zerobyte's web page.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Zerobyte did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Zerobyte.") from error

    async def _list(self, config: dict[str, Any], ctx: Context, path: str) -> list[dict[str, Any]]:
        answer = await self._json(config, ctx, path)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not the way Zerobyte does.", code="not_zerobyte")
        return [one for one in answer if isinstance(one, dict)]

    async def running_version(self, config: dict[str, Any], ctx: Context) -> str | None:
        """Zerobyte names its version on the update check, not on the backups."""
        from ..services.versions import version_in

        try:
            answer = await self._json(config, ctx, "/system/updates", timeout=8.0)
        except AdapterError:
            return None
        return version_in(str(answer.get("currentVersion") or "")) if isinstance(answer, dict) else None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        backups = await self._list(config, ctx, "/backups")
        version = await self.running_version(config, ctx)
        return f"Zerobyte {version} answers with {len(backups)} backups." if version else f"Zerobyte answers with {len(backups)} backups."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "repositories":
            return self._repositories(await self._list(config, ctx, "/repositories"), max(1, int(options.get("limit") or 10)))
        rows = self._rows(await self._list(config, ctx, "/backups"), backup_age.limit_of(config))
        if widget_kind == "summary":
            return self._summary(rows)
        return self._backups(rows, max(1, int(options.get("limit") or 10)))

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData, options: dict[str, Any]) -> list[Detected]:
        """A schedule whose last good backup became too old (``backup_age``)."""
        return backup_age.news(before, after) if widget_kind == "backups" else []

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "run":
            raise AdapterError("Zerobyte has no such action.", code="no_such_action")
        schedule = path_segment(params.get("backup"), "That schedule")
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/v1/backups/{schedule}/run", headers={"X-Api-Key": str(config.get("api_key") or "")},
            verify=not config.get("insecure"), auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Zerobyte rejected the API key.")
        ctx.forget_answers()
        # ⚠️ Measured: 202 means started, not finished. The backup runs on in the background.
        if response.status_code < 300:
            return "Zerobyte has started the backup."
        try:
            message = str(response.json().get("message") or "")
        except (ValueError, AttributeError):
            message = ""
        if response.status_code == 404:
            raise AdapterError("Zerobyte does not know that schedule any more.", code="not_found")
        raise AdapterError(f"Zerobyte could not run the backup: {message}" if message else f"Zerobyte answered with HTTP {response.status_code}.",
                           code="action_failed")

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _rows(backups: list[dict[str, Any]], stale_after: float, now: float | None = None) -> list[dict[str, Any]]:
        """One entry per schedule: its state, when it last went well, and the row the list shows."""
        now = time.time() if now is None else now
        rows = []
        for backup in backups:
            identifier = str(backup.get("shortId") or "")
            status = str(backup.get("lastBackupStatus") or "")
            enabled = backup.get("enabled") is not False
            volume = backup.get("volume") if isinstance(backup.get("volume"), dict) else {}
            repository = backup.get("repository") if isinstance(backup.get("repository"), dict) else {}
            moment = _seconds(backup.get("lastBackupAt"))
            # While a backup runs, lastBackupAt is still the one before it, which went well or not.
            good = moment if status == "success" or (status == "in_progress" and moment) else None
            state = STATUS_COLOUR.get(status, "unknown")
            words: list[str] = []
            if volume.get("status") == "error":
                # ⚠️ Measured: a folder that is gone gives the schedule no status at all, only the volume says why.
                state, words = "bad", ["Source unavailable", _reason(volume.get("lastError"))]
            elif repository.get("status") == "error":
                state, words = "bad", ["Repository error", _reason(repository.get("lastError"))]
            elif status in STATUS_WORD:
                words = [STATUS_WORD[status]]
                if status in ("error", "warning"):
                    words.append(_reason(backup.get("lastBackupError")))
            elif not status:
                words = ["Never run"]
            stale = status == "success" and backup_age.too_old(good, stale_after, now)
            if stale:
                state, words = "warn", [backup_age.WORD]
            elif not enabled and status != "in_progress":
                # A paused schedule is nobody's failure: grey, until it is too old to ignore.
                words = ["Paused", *words]
                state = "unknown" if state == "ok" else state
            next_run = _until(_seconds(backup.get("nextBackupAt")), now) if enabled else ""
            places = " → ".join(part for part in (_named(volume), _named(repository)) if part)
            row: dict[str, Any] = {
                "title": str(backup.get("name") or identifier or "?"),
                "subtitle": " · ".join(part for part in (*words, places, next_run) if part),
                "status": state,
            }
            if moment:
                row["value"] = ago(moment, now=now)
            if stale:
                row["stale"] = True
            if status != "in_progress":
                row["actions"] = [Action(id="run", label="Run now", icon="play", confirm=True, params={"backup": identifier})]
            rows.append({"state": state, "status": status, "enabled": enabled, "good": good, "row": row})
        return rows

    @staticmethod
    def _backups(rows: list[dict[str, Any]], limit: int) -> WidgetData:
        ranked = sorted(rows, key=lambda one: (ORDER.get(one["state"], 9), str(one["row"]["title"]).lower()))
        failed = sum(1 for one in rows if one["state"] == "bad")
        stale = any(one["row"].get("stale") for one in rows)
        known = any(one["state"] != "unknown" for one in rows)
        return WidgetData(
            status="bad" if failed else "warn" if stale else "ok" if known else "unknown",
            items=[one["row"] for one in ranked][:limit],
            secondary=[{"label": "Failed", "value": failed}],
            meta={"empty": "No backup schedules yet."},
            metrics={"failed": float(failed)},
        )

    @staticmethod
    def _summary(rows: list[dict[str, Any]], now: float | None = None) -> WidgetData:
        failed = sum(1 for one in rows if one["state"] == "bad")
        stale = sum(1 for one in rows if one["row"].get("stale"))
        fine = sum(1 for one in rows if one["state"] == "ok")
        running = sum(1 for one in rows if one["status"] == "in_progress")
        paused = sum(1 for one in rows if not one["enabled"])
        newest = max((one["good"] for one in rows if one["good"]), default=None)
        secondary: list[dict[str, Any]] = [{"label": "Failed", "value": failed}, {"label": "Running", "value": running}, {"label": "Paused", "value": paused}]
        if stale:
            secondary.append({"label": backup_age.WORD, "value": stale})
        if newest:
            secondary.append({"label": "Last backup", "value": ago(newest, now=now)})
        return WidgetData(
            status="bad" if failed else "warn" if stale else "ok" if fine else "unknown",
            primary={"label": "Backups fine", "value": fine, "unit": f"/ {len(rows)}"},
            secondary=secondary,
            metrics={"failed": float(failed)},
        )

    @staticmethod
    def _repositories(repositories: list[dict[str, Any]], limit: int, now: float | None = None) -> WidgetData:
        rows = []
        for repository in repositories:
            status = str(repository.get("status") or "unknown")
            stats = repository.get("stats") if isinstance(repository.get("stats"), dict) else {}
            size = stats.get("total_size")
            checked = ago(_seconds(repository.get("lastChecked")), now=now)
            words = [REPOSITORY_WORD[status]] if status in REPOSITORY_WORD else []
            if status == "error":
                words.append(_reason(repository.get("lastError")))
            snapshots = stats.get("snapshots_count")
            pieces = [*words, str(repository.get("type") or ""), f"{snapshots} snapshot{'' if snapshots == 1 else 's'}" if snapshots is not None else "",
                      f"checked {checked} ago" if checked else ""]
            rows.append({
                "title": str(repository.get("name") or "?"),
                "subtitle": " · ".join(piece for piece in pieces if piece),
                "status": REPOSITORY_COLOUR.get(status, "unknown"),
                **({"value": human_bytes(size)} if isinstance(size, int | float) else {}),
            })
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"].lower()))
        broken = sum(1 for row in rows if row["status"] == "bad")
        return WidgetData(
            status="bad" if broken else "warn" if any(row["status"] == "warn" for row in rows) else "ok" if rows else "unknown",
            items=rows[:limit],
            secondary=[{"label": "In error", "value": broken}],
            meta={"empty": "No repositories yet."},
            metrics={"broken": float(broken)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        failing = fake.flicker("zerobyte-photos", tick, 0.6)

        def backup(identifier: str, name: str, hours_ago: float | None, status: str | None, volume: str, repository: str, enabled: bool = True, error: str = "") -> dict[str, Any]:
            return {"shortId": identifier, "name": name, "enabled": enabled, "lastBackupStatus": status, "lastBackupError": error or None,
                    "lastBackupAt": int((now - hours_ago * 3600) * 1000) if hours_ago is not None else None,
                    "nextBackupAt": int((now + 7 * 3600) * 1000),
                    "volume": {"name": volume, "status": "mounted"}, "repository": {"name": repository, "status": "healthy"}}

        backups = [
            backup("a1", "Documents", 2, "success", "documents", "Offsite storage"),
            backup("a2", "Photos", 5, "error" if failing else "success", "photos", "Offsite storage",
                   error="repository is already locked by another process" if failing else ""),
            backup("a3", "Docker volumes", 0.5, "in_progress" if fake.flicker("zerobyte-run", tick, 0.3) else "success", "docker", "Local disk"),
            backup("a4", "Old laptop", 90, "success", "laptop", "Local disk", enabled=False),
        ]
        repositories = [
            {"name": "Offsite storage", "type": "s3", "status": "healthy", "lastChecked": int((now - 3 * 3600) * 1000),
             "stats": {"total_size": 412_000_000_000, "snapshots_count": 38}},
            {"name": "Local disk", "type": "local", "status": "healthy", "lastChecked": int((now - 5 * 3600) * 1000),
             "stats": {"total_size": 96_000_000_000, "snapshots_count": 21}},
        ]
        if widget_kind == "repositories":
            return self._repositories(repositories, max(1, int(options.get("limit") or 10)), now=now)
        rows = self._rows(backups, backup_age.limit_of({}), now=now)
        if widget_kind == "summary":
            return self._summary(rows, now=now)
        return self._backups(rows, max(1, int(options.get("limit") or 10)))


ADAPTER = ZerobyteAdapter()
