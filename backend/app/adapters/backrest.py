"""Backrest: every backup plan with its last run, why it failed and how much it holds, with a button that starts a backup.

Measured against Backrest 1.14.1, restic 0.19.1 inside the image, on 12.09.2026,
with a local repository in the test stack and three plans: one over a folder of
test files, one over a folder that does not exist, and one that never ran.

⚠️ A fresh Backrest has authentication switched off: its configuration
answered without any credentials until a user was added. With a user, requests
carry basic authentication. A wrong password is answered "Unauthorized (No
Authorization Header)", the same as no header at all, because a failed basic
check falls through to the check for a bearer token.

⚠️ The API is gRPC over JSON, ``POST /v1.Backrest/GetSummaryDashboard`` with a
JSON body. Numbers come as strings, zeros are left out, and the recent backups
of a plan are listed newest first. A plan that never ran is listed with empty
``recentBackups``. ``GetOperations`` without a selector answered 500 "empty
selector".

⚠️ The dashboard knows that a backup failed, not why. The reason is the
``displayMessage`` of the backup operation ("failed to backup: path ... does
not exist"), so the card asks the operations of a failed plan, and only of
those. A backup that is still running shows in the operations as
``STATUS_INPROGRESS`` and not in the dashboard.

⚠️ ``Backup`` answers only when the backup is done: 200 ``{}`` after 1.6 seconds
for 3 MB, 500 with the reason for the folder that does not exist, 404 for a plan
Backrest does not have. A request the client stopped waiting for after 0.3
seconds still ran to a good snapshot, so the button waits a few seconds and
otherwise says the backup goes on.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    Unreachable,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    human_bytes,
)

#: How long the button waits for a backup before it says the backup goes on without it.
BACKUP_WAIT_SECONDS = 10.0
STATUS_COLOUR = {"STATUS_SUCCESS": "ok", "STATUS_WARNING": "warn", "STATUS_ERROR": "bad",
                 "STATUS_SYSTEM_CANCELLED": "unknown", "STATUS_USER_CANCELLED": "unknown"}
STATUS_WORD = {"STATUS_ERROR": "Failed", "STATUS_WARNING": "Warning", "STATUS_SYSTEM_CANCELLED": "Cancelled", "STATUS_USER_CANCELLED": "Cancelled"}
#: Only these send the card to the operations for a reason.
NEEDS_REASON = {"STATUS_ERROR", "STATUS_WARNING"}
ORDER = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _recent(summary: dict[str, Any]) -> dict[str, Any]:
    recent = summary.get("recentBackups")
    return recent if isinstance(recent, dict) else {}


def _latest(summary: dict[str, Any]) -> tuple[str, float | None]:
    """The newest finished backup of a plan: its status, and when it started in seconds."""
    recent = _recent(summary)
    statuses = recent.get("status") or []
    stamps = recent.get("timestampMs") or []
    if not statuses:
        return "", None
    return str(statuses[0]), (_number(stamps[0]) / 1000 if stamps else None) or None


def _last_good(summary: dict[str, Any]) -> float | None:
    recent = _recent(summary)
    good = [_number(stamp) / 1000 for stamp, status in zip(recent.get("timestampMs") or [], recent.get("status") or [], strict=False)
            if status == "STATUS_SUCCESS"]
    return max(good) if good else None


class BackrestAdapter(Adapter):
    kind = "backrest"
    label = "Backrest"
    category = "nas"
    description = "Every backup plan with its last run, why it failed and how much it holds, with a button that starts a backup."
    icon = "backrest"
    #: Confirmed against a live instance on 2026-09-12.
    beta = False
    docs_url = "https://garethgeorge.github.io/backrest/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://backrest:9898"),
        Field("username", "User", help="A user of Backrest's own sign-in. Leave it empty when authentication is switched off."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="plans", label="Backup plans",
                   description="Every plan with its last backup and why it failed, failed ones first, with a button that starts a backup.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("failed",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Backups", description="How many plans are fine, and when the last good backup ran.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("failed",)),
    )

    async def _call(self, config: dict[str, Any], ctx: Context, name: str, body: dict[str, Any], timeout: float = 15.0) -> Any:
        user = str(config.get("username") or "").strip()
        response = await ctx.request(
            "POST", f"{base_url(config)}/v1.Backrest/{name}", json_body=body,
            auth=(user, str(config.get("password") or "")) if user else None,
            verify=not config.get("insecure"), timeout=timeout, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Backrest rejected the user or the password.")
        return response

    async def _json(self, config: dict[str, Any], ctx: Context, name: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._call(config, ctx, name, body)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Backrest did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Backrest.") from error
        if response.status_code >= 400:
            message = str(answer.get("message") or "") if isinstance(answer, dict) else ""
            raise AdapterError(f"Backrest refused: {message}" if message else f"Backrest answered with HTTP {response.status_code}.",
                               code="http_error")
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Backrest does.", code="not_backrest")
        return answer

    async def _dashboard(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._json(config, ctx, "GetSummaryDashboard", {})
        # ⚠️ Measured: a Backrest without plans answers with its paths and nothing else.
        if "configPath" not in answer and "planSummaries" not in answer:
            raise AdapterError("This address answers, but not the way Backrest does.", code="not_backrest")
        return [one for one in answer.get("planSummaries") or [] if isinstance(one, dict)]

    async def _reason(self, config: dict[str, Any], ctx: Context, plan: str) -> str:
        """Why the newest backup of a plan went wrong, from its operations."""
        try:
            answer = await self._json(config, ctx, "GetOperations", {"selector": {"planId": plan}, "lastN": 4})
        except AuthFailed:
            raise
        except AdapterError:
            return ""
        # Oldest first, so the newest backup is found from the end.
        for operation in reversed(answer.get("operations") or []):
            if isinstance(operation, dict) and "operationBackup" in operation and operation.get("displayMessage"):
                return " ".join(str(operation["displayMessage"]).split())[:160]
        return ""

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        plans = await self._dashboard(config, ctx)
        return f"Backrest answers with {len(plans)} backup plans."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        plans = await self._dashboard(config, ctx)
        if widget_kind == "summary":
            return self._summary(plans)
        reasons: dict[str, str] = {}
        for plan in plans:
            status, _moment = _latest(plan)
            if status in NEEDS_REASON:
                identifier = str(plan.get("id") or "")
                reasons[identifier] = await self._reason(config, ctx, identifier)
        return self._plans(plans, reasons, max(1, int(options.get("limit") or 10)))

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "backup":
            raise AdapterError("Backrest has no such action.", code="no_such_action")
        plan = str(params.get("plan") or "").strip()
        if not plan or len(plan) > 128:
            raise AdapterError("That is not a plan this card offered.", code="bad_param")
        try:
            response = await self._call(config, ctx, "Backup", {"value": plan}, timeout=BACKUP_WAIT_SECONDS)
        except Unreachable as error:
            # ⚠️ Measured: a backup nobody waits for any more still runs to its end.
            if isinstance(error.__cause__, httpx.TimeoutException):
                ctx.forget_answers()
                return "Backrest is backing up; it goes on in the background."
            raise
        ctx.forget_answers()
        if response.status_code < 400:
            return "Backrest has finished the backup."
        try:
            message = str(response.json().get("message") or "")
        except (ValueError, AttributeError):
            message = ""
        raise AdapterError(f"Backrest could not back up: {message}" if message else f"Backrest answered with HTTP {response.status_code}.",
                           code="action_failed")

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _plans(plans: list[dict[str, Any]], reasons: dict[str, str], limit: int, now: float | None = None) -> WidgetData:
        rows = []
        for plan in plans:
            identifier = str(plan.get("id") or "?")
            status, moment = _latest(plan)
            colour = STATUS_COLOUR.get(status, "unknown")
            if not status:
                words: tuple[str, ...] = ("Never run",)
            elif colour == "ok":
                size = _number(plan.get("protectedBytes"))
                words = (human_bytes(size),) if size else ()
            else:
                words = (STATUS_WORD.get(status, "Unknown"), reasons.get(identifier, ""))
            row: dict[str, Any] = {
                "title": identifier,
                "subtitle": " · ".join(part for part in words if part),
                "status": colour,
                "actions": [Action(id="backup", label="Back up now", icon="play", confirm=True, params={"plan": identifier})],
            }
            when = ago(moment, now=now) if moment else ""
            if when:
                row["value"] = when
            rows.append(row)
        rows.sort(key=lambda row: (ORDER.get(row["status"], 9), row["title"].lower()))
        failed = sum(1 for row in rows if row["status"] == "bad")
        known = any(row["status"] != "unknown" for row in rows)
        return WidgetData(
            status="bad" if failed else "ok" if known else "unknown",
            items=rows[:limit],
            secondary=[{"label": "Failed", "value": failed}],
            meta={"empty": "No backup plans yet."},
            metrics={"failed": float(failed)},
        )

    @staticmethod
    def _summary(plans: list[dict[str, Any]], now: float | None = None) -> WidgetData:
        latest = [_latest(plan)[0] for plan in plans]
        failed = latest.count("STATUS_ERROR")
        fine = latest.count("STATUS_SUCCESS")
        newest = max((moment for moment in (_last_good(plan) for plan in plans) if moment), default=None)
        secondary: list[dict[str, Any]] = []
        if failed:
            secondary.append({"label": "Failed", "value": failed})
        if newest:
            secondary.append({"label": "Last backup", "value": ago(newest, now=now)})
        return WidgetData(
            status="bad" if failed else "ok" if fine else "unknown",
            primary={"label": "Plans fine", "value": fine, "unit": f"/ {len(plans)}"},
            secondary=secondary,
            metrics={"failed": float(failed)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        failing = fake.flicker("backrest-photos", tick, 0.6)
        now = time.time()

        def plan(identifier: str, hours_ago: float, status: str, size: int) -> dict[str, Any]:
            return {"id": identifier, "protectedBytes": str(size),
                    "recentBackups": {"timestampMs": [str(int((now - hours_ago * 3600) * 1000))], "status": [status]}}

        plans = [
            plan("documents", 2, "STATUS_SUCCESS", 48_200_000_000),
            plan("photos", 5, "STATUS_ERROR" if failing else "STATUS_SUCCESS", 212_000_000_000),
            plan("docker-volumes", 0.5, "STATUS_SUCCESS", 3_400_000_000),
            {"id": "offsite", "recentBackups": {}},
        ]
        if widget_kind == "summary":
            return self._summary(plans)
        return self._plans(plans, {"photos": "repository is already locked by another process"}, max(1, int(options.get("limit") or 10)))


ADAPTER = BackrestAdapter()
