"""Kopia: whether every snapshot source was backed up lately, and whether the last try failed.

Measured against Kopia 0.23.1 in server mode on 11.09.2026: one source that
snapshotted, one whose folder vanished before the next snapshot.

⚠️ A failed snapshot does not show in ``/api/v1/sources``. The source stays
``IDLE`` with the previous good snapshot as its last one; the failure lives
only in ``/api/v1/tasks``, as ``FAILED`` with the reason. The call that
starts a snapshot answered ``success: true`` for the one that then failed.
So the cards read the tasks as well and put a newer failed task above an
older good snapshot.

⚠️ The task list is kept in memory. After the server restarts, earlier
failures are gone and the source looks fine again.

⚠️ With the server's CSRF check on, which is the default, basic
authentication alone gets 401 "Invalid or missing CSRF token". The token is
in a meta tag of the start page and only counts together with the session
cookies that page sets. Measured: token without the cookies, 401; both, 200.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
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

CSRF_META = re.compile(r'name="kopia-csrf-token" content="([^"]+)"')
#: How a snapshot task names its source: ``root@host:/path at 2026-09-11T08:58:35Z``.
TASK_SOURCE = re.compile(r"^(?P<user>[^@]+)@(?P<host>[^:]+):(?P<path>.+) at \S+$")
SESSION = "kopia_session"


def _moment(raw: Any) -> float:
    """An RFC 3339 time with nanoseconds as seconds since the epoch; 0 when unreadable."""
    text = str(raw or "")
    if not text:
        return 0.0
    text = re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


class KopiaAdapter(Adapter):
    kind = "kopia"
    label = "Kopia"
    category = "nas"
    description = "Whether every snapshot source was backed up lately, and whether the last try failed."
    icon = "kopia"
    beta = False
    docs_url = "https://kopia.io/docs/repository-server/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://kopia:51515",
              help="Kopia started with server start, or KopiaUI's own server."),
        Field("username", "User", required=True, default="kopia", help="The --server-username the server was started with."),
        Field("password", "Password", type="password", secret=True, required=True, help="The --server-password."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="sources", label="Snapshots", description="Every source with its last good snapshot, failed ones first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("failed",),
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="summary", label="Backups", description="How many sources are fine, and when the last snapshot finished.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("failed",)),
    )

    def _auth(self, config: dict[str, Any]) -> tuple[str, str]:
        return str(config.get("username") or ""), str(config.get("password") or "")

    async def _session(self, config: dict[str, Any], ctx: Context, fresh: bool = False) -> dict[str, str]:
        if not fresh and isinstance(ctx.cache.get(SESSION), dict):
            return ctx.cache[SESSION]
        page = await ctx.request("GET", f"{base_url(config)}/", auth=self._auth(config), verify=not config.get("insecure"), auth_errors=False)
        if page.status_code in (401, 403):
            raise AuthFailed("Kopia rejected the user or the password.")
        headers: dict[str, str] = {}
        token = CSRF_META.search(page.text) if page.status_code < 400 else None
        if token:
            headers["X-Kopia-Csrf-Token"] = token.group(1)
            cookies = "; ".join(f"{name}={value}" for name, value in page.cookies.items())
            if cookies:
                headers["Cookie"] = cookies
        # A server without its UI has no start page to take a token from; with
        # the check switched off it needs none, and otherwise the API says so.
        ctx.cache[SESSION] = headers
        return headers

    async def _json(self, config: dict[str, Any], ctx: Context, path: str) -> Any:
        for attempt in (0, 1):
            headers = await self._session(config, ctx, fresh=attempt == 1)
            response = await ctx.request("GET", f"{base_url(config)}/api/v1{path}", auth=self._auth(config), headers=headers,
                                         verify=not config.get("insecure"), auth_errors=False)
            if response.status_code != 401 or attempt == 1:
                break
        if response.status_code == 401:
            if "CSRF" in response.text:
                raise AdapterError("Kopia refused the request without a valid CSRF token.", code="csrf",
                                   hint="Start the server with its UI, or with --disable-csrf-token-checks.")
            raise AuthFailed("Kopia rejected the user or the password.")
        if response.status_code >= 400:
            raise AdapterError(f"Kopia answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Kopia did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than the Kopia server.") from error

    async def _state(self, config: dict[str, Any], ctx: Context) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sources = await self._json(config, ctx, "/sources")
        tasks = await self._json(config, ctx, "/tasks")
        if not isinstance(sources, dict) or not isinstance(sources.get("sources"), list):
            raise AdapterError("This address answers, but not the way Kopia does.", code="not_kopia")
        return ([one for one in sources["sources"] if isinstance(one, dict)],
                [one for one in (tasks.get("tasks") if isinstance(tasks, dict) else None) or [] if isinstance(one, dict)])

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._json(config, ctx, "/repo/status")
        if not isinstance(status, dict) or "connected" not in status:
            raise AdapterError("This address answers, but not the way Kopia does.", code="not_kopia")
        if not status.get("connected"):
            return "Kopia answers, but its repository is not connected."
        sources, _tasks = await self._state(config, ctx)
        return f"Kopia answers: repository on {status.get('storage', '?')}, {len(sources)} sources."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        sources, tasks = await self._state(config, ctx)
        rows = self._rows(sources, tasks)
        if widget_kind == "summary":
            return self._summary(rows)
        return self._sources(rows, options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _rows(sources: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest_task: dict[tuple[str, str, str], dict[str, Any]] = {}
        for task in tasks:
            if task.get("kind") != "Snapshot":
                continue
            named = TASK_SOURCE.match(str(task.get("description") or ""))
            if not named:
                continue
            key = (named["user"], named["host"], named["path"])
            if _moment(task.get("endTime") or task.get("startTime")) >= _moment((latest_task.get(key) or {}).get("endTime")):
                latest_task[key] = task
        several_hosts = len({str((one.get("source") or {}).get("host")) for one in sources}) > 1
        rows = []
        for source in sources:
            where = source.get("source") if isinstance(source.get("source"), dict) else {}
            last = source.get("lastSnapshot") if isinstance(source.get("lastSnapshot"), dict) else {}
            good = _moment(last.get("endTime"))
            task = latest_task.get((str(where.get("userName")), str(where.get("host")), str(where.get("path"))), {})
            errors = int(((last.get("stats") or {}).get("errorCount")) or 0)
            if task.get("status") == "FAILED" and _moment(task.get("endTime") or task.get("startTime")) > good:
                state, word, reason = "bad", "Failed", str(task.get("errorMessage") or "")
            elif source.get("status") == "UPLOADING" or task.get("status") == "RUNNING":
                state, word, reason = "warn", "Running", ""
            elif source.get("status") in ("PENDING", "PAUSED"):
                # ⚠️ Measured: a source of another host is REMOTE, which is not
                # a state of its own but "this server does not run it".
                state, word, reason = "unknown", "Waiting" if source.get("status") == "PENDING" else "Paused", ""
            elif not last:
                state, word, reason = "unknown", "No snapshot yet", ""
            elif errors:
                state, word, reason = "warn", f"{errors} errors", ""
            else:
                state, word, reason = "ok", "", ""
            place = f"{where.get('userName')}@{where.get('host')}" if several_hosts else ""
            rows.append({"state": state, "good": good, "row": {
                "title": str(where.get("path") or "?"),
                "subtitle": " · ".join(part for part in (word, reason[:120], place) if part),
                "status": state,
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
            secondary.append({"label": "Last snapshot", "value": ago(newest)})
        return WidgetData(
            status="bad" if failed else "ok" if rows else "unknown",
            primary={"label": "Sources fine", "value": fine, "unit": f"/ {len(rows)}"},
            secondary=secondary,
            metrics={"failed": float(failed)},
        )

    @staticmethod
    def _sources(rows: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        order = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
        ranked = sorted(rows, key=lambda one: (order.get(one["state"], 9), one["row"]["title"]))
        failed = sum(1 for one in rows if one["state"] == "bad")
        return WidgetData(
            status="bad" if failed else "ok",
            items=[one["row"] for one in ranked][: int(options.get("limit") or 10)],
            secondary=[{"label": "Failed", "value": failed}],
            meta={"empty": "No snapshot sources yet."},
            metrics={"failed": float(failed)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        failed = fake.flicker("kopia-photos", tick, 0.7)

        def stamp(hours: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime(time.time() - hours * 3600))

        sources = [
            {"source": {"host": "nas", "userName": "root", "path": "/volume1/documents"}, "status": "IDLE", "lastSnapshot": {"endTime": stamp(3), "stats": {"errorCount": 0}}},
            {"source": {"host": "nas", "userName": "root", "path": "/volume1/photos"}, "status": "IDLE", "lastSnapshot": {"endTime": stamp(26), "stats": {"errorCount": 0}}},
            {"source": {"host": "nas", "userName": "root", "path": "/opt/stacks"}, "status": "IDLE", "lastSnapshot": {"endTime": stamp(1), "stats": {"errorCount": 0}}},
        ]
        tasks = [{"kind": "Snapshot", "status": "FAILED", "description": f"root@nas:/volume1/photos at {stamp(2)}", "endTime": stamp(2),
                  "errorMessage": "unable to read directory: permission denied"}] if failed else []
        rows = self._rows(sources, tasks)
        if widget_kind == "summary":
            return self._summary(rows)
        return self._sources(rows, options)


ADAPTER = KopiaAdapter()
