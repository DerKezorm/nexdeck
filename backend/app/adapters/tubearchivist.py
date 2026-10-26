"""Tube Archivist: what waits in the download queue, which videos came in last, and how big the archive is.

Measured against Tube Archivist v0.5.12 on 11.09.2026, with Elasticsearch
and Redis beside it, and one public-domain video of 14 seconds queued,
downloaded, deleted, queued again and downloaded again.

⚠️ The token goes as ``Authorization: Token <token>``. As ``Bearer`` it is
ignored: 403 "Authentication credentials were not provided.", the same as no
token at all. A made-up token gets 403 "Invalid token.".

⚠️ ``/api/stats/download/`` answers ``null`` for every count while the queue
is empty, not 0.

⚠️ Starting downloads answers 200 with a task id whether or not anything is
waiting: on an empty queue the task ran and did nothing, with one video it
reported "downloaded 1 video(s).". The card offers the button only while the
queue holds something and no download runs.

⚠️ A running download shows in ``/api/notification/?filter=download`` as an
entry of the group "download:run" with ``progress`` between 0 and 1. Once it
is done the entry stays for a while with the message "Task completed" and no
``progress`` at all.

⚠️ The API schema at ``/api/schema/`` wants a signed-in session; with the
token it answers 403.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

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

START = Action(id="start_downloads", label="Start downloads", icon="download", confirm=True)


def _count(value: Any) -> int:
    """A count Tube Archivist may hand out as null."""
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    return str(payload.get("detail") or "") if isinstance(payload, dict) else ""


def _not_tubearchivist() -> AdapterError:
    return AdapterError("This address answers, but not the way Tube Archivist does.", code="not_tubearchivist",
                        hint="Check the URL; it is the address of Tube Archivist itself, port 8000 unless told otherwise.")


def _page(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise _not_tubearchivist()
    rows = [one for one in payload["data"] if isinstance(one, dict)]
    paginate = payload.get("paginate") if isinstance(payload.get("paginate"), dict) else {}
    return rows, _count(paginate.get("total_hits")) or len(rows)


def _running(notes: Any) -> int | None:
    """How far a running download is, in per cent, or None when none runs."""
    for note in notes if isinstance(notes, list) else []:
        if isinstance(note, dict) and note.get("group") == "download:run":
            progress = note.get("progress")
            if isinstance(progress, (int, float)) and not isinstance(progress, bool):
                return round(float(progress) * 100)
    return None


class TubeArchivistAdapter(Adapter):
    kind = "tubearchivist"
    label = "Tube Archivist"
    category = "media"
    description = "What waits in the download queue, which videos came in last, and how big the archive is."
    icon = "lucide:archive"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://docs.tubearchivist.com/api/introduction/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://tubearchivist:8000"),
        Field("token", "API token", type="password", secret=True, required=True,
              help="Settings > Application, under API token."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="queue", label="Download queue",
                   description="The videos waiting to be downloaded, with a button that starts the downloads.",
                   renderer="list", default_size=(3, 3), refresh_seconds=60, metrics=("queued",),
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="videos", label="Latest videos", description="The videos downloaded last, with their channel.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="summary", label="Video archive",
                   description="How many videos and channels the archive holds, and how many videos wait in the queue.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("videos", "queued")),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Token {config.get('token') or ''}"}

    def _refused(self, response: httpx.Response) -> AuthFailed:
        if "Invalid token" in _detail(response):
            return AuthFailed("Tube Archivist rejected the API token.")
        return AuthFailed("Tube Archivist saw no API token.")

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 30) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers=self._headers(config),
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise self._refused(response)
        if response.status_code >= 400:
            raise AdapterError(f"Tube Archivist answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Tube Archivist itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Tube Archivist did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Tube Archivist.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        ping = await self._json(config, ctx, "/ping/", cache=0)
        if not isinstance(ping, dict) or ping.get("response") != "pong":
            raise _not_tubearchivist()
        return f"Tube Archivist {ping.get('version') or '?'} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "queue":
            queue = await self._json(config, ctx, "/download/", {"filter": "pending"}, cache=15)
            notes = await self._json(config, ctx, "/notification/", {"filter": "download"}, cache=5)
            return self._queue(queue, notes, options)
        if widget_kind == "videos":
            page = await self._json(config, ctx, "/video/", {"sort": "downloaded", "order": "desc"}, cache=60)
            return self._videos(page, options, time.time())
        videos = await self._json(config, ctx, "/stats/video/", cache=120)
        channels = await self._json(config, ctx, "/stats/channel/", cache=300)
        downloads = await self._json(config, ctx, "/stats/download/", cache=30)
        return self._summary(videos, channels, downloads)

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "start_downloads":
            raise AdapterError("Unknown download action.", code="no_such_action")
        response = await ctx.request("POST", f"{base_url(config)}/api/task/by-name/download_pending/", headers=self._headers(config),
                                     json_body={}, verify=not config.get("insecure"), auth_errors=False)
        if response.status_code in (401, 403):
            raise self._refused(response)
        if response.status_code >= 400:
            raise AdapterError(f"Tube Archivist answered with HTTP {response.status_code}.", code="action_failed")
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if not isinstance(answer, dict) or not answer.get("task_id"):
            raise AdapterError("Tube Archivist answered, but started no download task.", code="action_failed")
        ctx.forget_answers()
        return "Downloads started."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _queue(queue: Any, notes: Any, options: dict[str, Any]) -> WidgetData:
        rows, total = _page(queue)
        items = [{
            "title": str(one.get("title") or one.get("youtube_id") or "?"),
            "subtitle": str(one.get("channel_name") or ""),
            "status": "ok",
            "value": str(one.get("duration") or ""),
        } for one in rows[: max(1, int(options.get("limit") or 8))]]
        progress = _running(notes)
        secondary: list[dict[str, Any]] = [{"label": "Queue", "value": total}]
        if progress is not None:
            secondary.append({"label": "Downloading", "value": f"{progress}%"})
        return WidgetData(
            status="ok",
            items=items,
            secondary=secondary,
            # Only while something waits and nothing runs: the task starts and answers 200 either way.
            actions=[START] if total and progress is None else [],
            metrics={"queued": float(total)},
            meta={"empty": "Nothing waits to be downloaded."},
        )

    @staticmethod
    def _videos(page: Any, options: dict[str, Any], now: float) -> WidgetData:
        rows, total = _page(page)
        items = []
        for one in rows[: max(1, int(options.get("limit") or 8))]:
            channel = one.get("channel") if isinstance(one.get("channel"), dict) else {}
            items.append({
                "title": str(one.get("title") or one.get("youtube_id") or "?"),
                "subtitle": str(channel.get("channel_name") or ""),
                "status": "ok",
                "value": ago(one.get("date_downloaded"), now=now),
            })
        return WidgetData(status="ok", items=items, secondary=[{"label": "Videos", "value": total}],
                          meta={"empty": "No videos downloaded yet."})

    @staticmethod
    def _summary(videos: Any, channels: Any, downloads: Any) -> WidgetData:
        if not isinstance(videos, dict) or "doc_count" not in videos or not isinstance(channels, dict) or not isinstance(downloads, dict):
            raise _not_tubearchivist()
        count = _count(videos.get("doc_count"))
        queued = _count(downloads.get("pending"))
        return WidgetData(
            status="ok",
            primary={"label": "Videos", "value": count},
            secondary=[{"label": "Channels", "value": _count(channels.get("doc_count"))}, {"label": "Queue", "value": queued}],
            metrics={"videos": float(count), "queued": float(queued)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()
        waiting = [
            {"youtube_id": "demo00000001", "title": "How a rocket engine works", "channel_name": "Example Science", "duration": "12m 4s"},
            {"youtube_id": "demo00000002", "title": "Building a bookshelf in a weekend", "channel_name": "Example Workshop", "duration": "21m 37s"},
            {"youtube_id": "demo00000003", "title": "The history of the printing press", "channel_name": "Example History", "duration": "8m 52s"},
        ]
        running = [{"group": "download:run", "title": "Downloading", "progress": (tick % 10) / 10}] if tick % 20 < 10 else []
        if widget_kind == "queue":
            return self._queue({"data": waiting, "paginate": {"total_hits": 3}}, running, options)
        if widget_kind == "videos":
            done = [
                {"youtube_id": "demo00000004", "title": "A tour of a radio telescope", "channel": {"channel_name": "Example Science"}, "date_downloaded": now - 1_800},
                {"youtube_id": "demo00000005", "title": "Sharpening a chisel", "channel": {"channel_name": "Example Workshop"}, "date_downloaded": now - 26_000},
                {"youtube_id": "demo00000006", "title": "Maps of the old world", "channel": {"channel_name": "Example History"}, "date_downloaded": now - 190_000},
            ]
            return self._videos({"data": done, "paginate": {"total_hits": 412}}, options, now)
        return self._summary({"doc_count": 412 + tick % 3}, {"doc_count": 17}, {"pending": 3})


ADAPTER = TubeArchivistAdapter()
