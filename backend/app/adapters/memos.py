"""Memos: how many memos there are, the ones written last, and the open tasks in them.

Measured on 28.10.2026 against Memos 0.31.0 (neosmemo/memos:stable) with a
personal access token and four invented memos, two of them with task lists.

⚠️ Memos has no API key as such. The sign-in answers an access token that
lasts fifteen minutes; what a dashboard needs is a personal access token
(Settings > My account > Access tokens, ``memos_pat_...``), sent as a Bearer
token. A wrong or missing one gets 401 ``{"code": 16, "message":
"authentication required"}``, and so does a list without any token: nothing
is public on a private instance.

⚠️ The user is named ``users/<username>`` (``/api/v1/auth/me``), and the
statistics live at ``/api/v1/users/<username>:getStats`` with a colon:
``totalMemoCount``, ``tagCount`` and ``memoTypeStats``. ``undoCount`` there
is the number of *memos* with an open task, not of tasks (one memo with three
open boxes counted 1 beside another with one), and it matched the filter
``has_incomplete_tasks``. ``todoCount`` was equal to it in both
measurements, so which of the two means open is only settled by that match
with the filter; the card says "Memos with open tasks".

⚠️ ``GET /api/v1/memos`` answers ``memos`` and ``nextPageToken``, newest
first, and takes ``pageSize`` and ``filter``. The memo's ``name`` is
``memos/<id>``, which is also its address in the interface. ``snippet`` has
the line breaks eaten ("dentist #todobook a slot"), so the title is the
first line of ``content``. ``property.title`` is empty unless the memo begins
with a heading.
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
    ago,
    base_url,
)

URL_HINT = "Check the URL; it is the address of Memos itself, without /api."
OPEN_TASK = re.compile(r"^\s*[-*+] \[ \] (.+?)\s*$", re.M)


def _title(memo: dict[str, Any]) -> str:
    """The first line with the markdown of a heading or a list taken off."""
    property_title = str((memo.get("property") or {}).get("title") or "").strip()
    if property_title:
        return property_title
    for line in str(memo.get("content") or "").splitlines():
        text = re.sub(r"^\s*(#{1,6}\s+|[-*+]\s+(\[[ xX]\]\s+)?)", "", line).strip()
        if text:
            return text
    return "?"


class MemosAdapter(Adapter):
    kind = "memos"
    label = "Memos"
    category = "other"
    description = "How many memos Memos holds, the memos written last, and the open tasks in them."
    icon = "memos"
    beta = True
    docs_url = "https://usememos.com/docs/api"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://memos:5230"),
        Field("token", "Access token", type="password", secret=True, required=True,
              help="Settings > My account > Access tokens (it starts with memos_pat_). The one from signing in lasts fifteen minutes."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="summary", label="Memos", description="How many memos there are, with those holding open tasks and the tags.",
                   renderer="value", default_size=(3, 2), refresh_seconds=600, metrics=("memos",),
                   parts=(("open", "Memos with open tasks"), ("tags", "Tags"))),
        WidgetType(kind="recent", label="Recent memos", description="The memos written last, with their tags.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="tasks", label="Open tasks", description="The unticked boxes of your task lists, with the memo they stand in.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300, metrics=("open_tasks",),
                   options=(Field("limit", "Entries", type="number", default=12),)),
    )

    # -- talking to Memos ----------------------------------------------------

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None,
                   cache: float = 10) -> dict[str, Any]:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("Memos rejected the access token.")
        if response.status_code >= 400:
            raise AdapterError(f"Memos answered with HTTP {response.status_code}.", code="http_error", hint=URL_HINT)
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Memos did not answer with JSON.", code="not_json",
                               hint="The URL probably points at a login page or a reverse proxy.") from error
        if not isinstance(answer, dict):
            raise AdapterError("This address answers, but not the way Memos does.", code="not_memos", hint=URL_HINT)
        return answer

    async def _memos(self, config: dict[str, Any], ctx: Context, **params: Any) -> list[dict[str, Any]]:
        answer = await self._get(config, ctx, "/memos", params)
        if not isinstance(answer.get("memos"), list):
            raise AdapterError("This address answers, but not the way Memos does.", code="not_memos", hint=URL_HINT)
        return [memo for memo in answer["memos"] if isinstance(memo, dict)]

    async def _user(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._get(config, ctx, "/auth/me", cache=3600)
        name = str((me.get("user") or {}).get("name") or "")
        if not name.startswith("users/"):
            raise AdapterError("This address answers, but not the way Memos does.", code="not_memos", hint=URL_HINT)
        return name

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        profile = await self._get(config, ctx, "/instance/profile", cache=0)
        stats = await self._get(config, ctx, f"/{await self._user(config, ctx)}:getStats", cache=0)
        return f"Memos {profile.get('version') or '?'} answers with {int(stats.get('totalMemoCount') or 0)} memos."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        base = base_url(config)
        if widget_kind == "recent":
            limit = max(1, min(50, int(options.get("limit") or 8)))
            return self._recent(await self._memos(config, ctx, pageSize=limit), base)
        if widget_kind == "tasks":
            limit = max(1, min(50, int(options.get("limit") or 12)))
            memos = await self._memos(config, ctx, pageSize=200, filter="has_incomplete_tasks")
            return self._tasks(memos, limit, base)
        stats = await self._get(config, ctx, f"/{await self._user(config, ctx)}:getStats")
        return self._summary(stats, base)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _summary(stats: dict[str, Any], base: str) -> WidgetData:
        total = int(stats.get("totalMemoCount") or 0)
        # ⚠️ Memos with an open task, not tasks; see the top of the file.
        open_memos = int((stats.get("memoTypeStats") or {}).get("undoCount") or 0)
        return WidgetData(
            status="ok",
            primary={"label": "Memos", "value": total},
            secondary=[
                {"label": "Memos with open tasks", "value": open_memos, "part": "open"},
                {"label": "Tags", "value": len(stats.get("tagCount") or {}), "part": "tags"},
            ],
            link=base,
            metrics={"memos": float(total)},
        )

    @staticmethod
    def _recent(memos: list[dict[str, Any]], base: str) -> WidgetData:
        items = []
        for memo in memos:
            row: dict[str, Any] = {
                "title": _title(memo),
                "subtitle": " ".join(f"#{tag}" for tag in (memo.get("tags") or [])[:3] if tag),
                "value": ago(memo.get("updateTime") or memo.get("createTime")),
            }
            if memo.get("name"):
                row["url"] = f"{base}/{memo['name']}"
            items.append(row)
        return WidgetData(status="ok", items=items, link=base, meta={"empty": "No memos yet."})

    @staticmethod
    def _tasks(memos: list[dict[str, Any]], limit: int, base: str) -> WidgetData:
        rows = []
        for memo in memos:
            for task in OPEN_TASK.findall(str(memo.get("content") or "")):
                row: dict[str, Any] = {"title": task, "subtitle": _title(memo)}
                if memo.get("name"):
                    row["url"] = f"{base}/{memo['name']}"
                rows.append(row)
        return WidgetData(
            status="ok",
            items=rows[:limit],
            secondary=[{"label": "Open", "value": len(rows)}],
            link=base,
            meta={"empty": "No open tasks."},
            metrics={"open_tasks": float(len(rows))},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        base = "https://memos.example.com"
        now = time.time()
        stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))  # noqa: E731
        memos = [
            {"name": "memos/a1", "content": "Call the dentist\n\n- [ ] book a slot\n- [x] find the number", "tags": ["todo"], "updateTime": stamp(1200)},
            {"name": "memos/a2", "content": "# Backup plan\n\nNightly to the NAS", "tags": ["lab", "backup"], "updateTime": stamp(5 * 3600)},
            {"name": "memos/a3", "content": "Shopping\n\n- [ ] milk\n- [ ] bread", "tags": ["home"], "updateTime": stamp(2 * 86400)},
        ]
        if widget_kind == "summary":
            fresh = 1 if fake.flicker("memos-new", tick, 0.3) else 0
            stats = {"totalMemoCount": 212 + tick % 3 + fresh, "memoTypeStats": {"undoCount": 6}, "tagCount": {f"tag{n}": 1 for n in range(18)}}
            return self._summary(stats, base)
        if widget_kind == "tasks":
            return self._tasks(memos, 12, base)
        return self._recent(memos, base)


ADAPTER = MemosAdapter()
