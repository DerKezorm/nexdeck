"""ChangeDetection.io: watched web pages, and which of them changed.

Measured against ChangeDetection.io 0.60.4 on 11.09.2026.

⚠️ The watch list is not what the API documentation describes. It names
``paused`` and ``notification_muted`` for every watch; the list of 0.60.4
carries neither, only the single watch does. A paused watch in the list
looks exactly like one that was never checked: ``last_checked`` 0. Asking
every watch on its own would cost a request per page on every refresh, so
the cards say "not checked yet" and leave it there.

⚠️ ``viewed`` is false for a watch that never changed at all. On its own it
means nothing; only together with ``last_changed`` it says "a change nobody
has looked at".
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlsplit

from . import demo as fake
from .base import (
    Action,
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

CHECK_ALL = Action(id="recheck_all", label="Check all now", icon="refresh-cw")


def _host(url: Any) -> str:
    return urlsplit(str(url or "")).hostname or ""


class ChangeDetectionAdapter(Adapter):
    kind = "changedetection"
    label = "ChangeDetection.io"
    category = "monitoring"
    description = "Watched web pages, and which of them changed."
    icon = "changedetection"
    beta = False
    docs_url = "https://changedetection.io/docs/api_v1/index.html"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://changedetection:5000"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Settings > API. The key is shown there, and the API has to be switched on."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="changes", label="Recent changes", description="Watched pages, failing ones first, then the latest change.",
                   renderer="list", default_size=(3, 3), refresh_seconds=120, metrics=("errors",),
                   options=(Field("limit", "Entries", type="number", default=10),
                            Field("tag", "Tag", help="Only watches with this tag. Empty shows all."),
                            Field("changed_only", "Only pages that changed", type="bool", default=False))),
        WidgetType(kind="summary", label="Watches", description="Changes nobody has looked at yet, errors and the queue.",
                   renderer="value", default_size=(3, 2), refresh_seconds=120, metrics=("unviewed", "errors")),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"x-api-key": str(config.get("api_key") or "")},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        # ⚠️ Measured: a missing and a wrong key both get 403 with a JSON string.
        if response.status_code in (401, 403):
            raise AuthFailed("ChangeDetection.io rejected the API key.")
        if response.status_code >= 400:
            raise AdapterError(f"ChangeDetection.io answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of ChangeDetection.io itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("ChangeDetection.io did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error

    async def _watches(self, config: dict[str, Any], ctx: Context, tag: str = "") -> dict[str, dict[str, Any]]:
        answer = await self._get(config, ctx, "/watch", params={"tag": tag} if tag else None)
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way ChangeDetection.io does.", code="not_changedetection")
        return {uuid: watch for uuid, watch in answer.items() if isinstance(watch, dict)}

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        info = await self._get(config, ctx, "/systeminfo", cache=0)
        if not isinstance(info, dict) or "watch_count" not in info:
            raise AdapterError("This address answers, but not the way ChangeDetection.io does.", code="not_changedetection")
        return f"ChangeDetection.io {info.get('version', '?')} answers with {info.get('watch_count', 0)} watches."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            info = await self._get(config, ctx, "/systeminfo")
            return self._summary(await self._watches(config, ctx), info if isinstance(info, dict) else {})
        watches = await self._watches(config, ctx, tag=str(options.get("tag") or "").strip())
        return self._changes(watches, options, base_url(config))

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "recheck_all":
            raise AdapterError("ChangeDetection.io has no such action.", code="unknown_action")
        answer = await self._get(config, ctx, "/watch", params={"recheck_all": "1"}, cache=0)
        # Measured: {"status": "OK, queued 5 watches for rechecking"}.
        queued = re.search(r"(\d+)", str(answer.get("status", "") if isinstance(answer, dict) else ""))
        if queued:
            return f"ChangeDetection.io is checking {queued.group(1)} watches again."
        return "ChangeDetection.io is checking every watch again."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _unviewed(watch: dict[str, Any]) -> bool:
        return bool(watch.get("last_changed")) and not watch.get("viewed")

    @classmethod
    def _summary(cls, watches: dict[str, dict[str, Any]], info: dict[str, Any]) -> WidgetData:
        unviewed = sum(1 for watch in watches.values() if cls._unviewed(watch))
        errors = sum(1 for watch in watches.values() if watch.get("last_error"))
        # ⚠️ Seen on a real board: five chips and a button on a card two columns
        # wide ran off its edge. A chip at zero only where the zero says something.
        overdue = info.get("overdue_watches")
        extra = (("Errors", errors), ("In queue", int(info.get("queue_size") or 0)),
                 ("Overdue", len(overdue) if isinstance(overdue, list) else 0))
        secondary: list[dict[str, Any]] = [{"label": "Watches", "value": len(watches)}]
        secondary += [{"label": label, "value": value} for label, value in extra if value]
        return WidgetData(
            status="bad" if errors else "ok",
            primary={"label": "Unviewed changes", "value": unviewed},
            secondary=secondary,
            actions=[CHECK_ALL],
            metrics={"unviewed": float(unviewed), "errors": float(errors)},
        )

    @classmethod
    def _changes(cls, watches: dict[str, dict[str, Any]], options: dict[str, Any], base: str,
                 now: float | None = None) -> WidgetData:
        changed_only = bool(options.get("changed_only"))
        # One moment for every row, which a test can fix; see ``ago``.
        moment = time.time() if now is None else now
        rows: list[tuple[int, float, str, dict[str, Any]]] = []
        for uuid, watch in watches.items():
            changed = float(watch.get("last_changed") or 0)
            if changed_only and not changed:
                continue
            title = str(watch.get("title") or watch.get("page_title") or watch.get("url") or "?")
            failed = bool(watch.get("last_error"))
            if failed:
                word = "Error"
            elif not watch.get("last_checked"):
                word = "Not checked yet"
            elif cls._unviewed(watch):
                word = "Unviewed"
            else:
                word = ""
            row: dict[str, Any] = {
                "title": title,
                "subtitle": " · ".join(part for part in (word, _host(watch.get("url"))) if part),
                "status": "bad" if failed else "unknown" if not watch.get("last_checked") else "ok",
                "value": ago(changed, moment) if changed else "",
                # The change itself where there is one, the page as last seen otherwise.
                "url": f"{base}/diff/{uuid}" if changed else f"{base}/preview/{uuid}",
            }
            rows.append((0 if failed else 1, -changed, title.lower(), row))
        rows.sort(key=lambda entry: entry[:3])
        errors = sum(1 for watch in watches.values() if watch.get("last_error"))
        unviewed = sum(1 for watch in watches.values() if cls._unviewed(watch))
        return WidgetData(
            status="bad" if errors else "ok",
            items=[entry[3] for entry in rows][: int(options.get("limit") or 10)],
            secondary=[{"label": "Unviewed", "value": unviewed}, {"label": "Errors", "value": errors}],
            actions=[CHECK_ALL],
            meta={"empty": "Nothing has changed yet." if changed_only else "No watches yet."},
            metrics={"errors": float(errors)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        broken = fake.flicker("cd-shop", tick, 0.8)
        watches = {
            "a1": {"title": "Graphics card price", "url": "https://shop.example.com/gpu", "last_changed": now - 2 * 3600, "last_checked": now - 600, "viewed": False, "last_error": False},
            "b2": {"title": "Proxmox release notes", "url": "https://pve.example.com/roadmap", "last_changed": now - 3 * 86400, "last_checked": now - 900, "viewed": True, "last_error": False},
            "c3": {"title": "Council bin dates", "url": "https://council.example.com/bins", "last_changed": now - 9 * 86400, "last_checked": now - 1200, "viewed": True, "last_error": False},
            "d4": {"title": "Concert tickets", "url": "https://tickets.example.com/tour", "last_changed": 0, "last_checked": now - 300, "viewed": False,
                   "last_error": "Exception: 403 Forbidden" if broken else False},
        }
        if widget_kind == "summary":
            return self._summary(watches, {"queue_size": 0, "overdue_watches": [], "watch_count": len(watches)})
        return self._changes(watches, options, "https://changedetection.example.com")


ADAPTER = ChangeDetectionAdapter()
