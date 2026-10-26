"""PhotoPrism: how many photos and videos the library holds, what came in last, and a button that indexes.

Measured against PhotoPrism 260728-bbde8f452 on 11.09.2026, with SQLite,
thirteen self-made test files (twelve generated patterns and a two-second
clip), an app password of the administrator and a client access token.

⚠️ A wrong credential is not refused everywhere: ``/api/v1/config`` answers
200 without one, with a made-up token and with a made-up app password alike,
in ``"mode": "public"`` and with every count at 0. A card that trusted it
would show an empty library. The adapter wants ``"mode": "user"``.

⚠️ A client access token from ``photoprism auth add`` (without a user name)
reads the counts and may index, but every photo search answers 400 "Unable
to do that". An app password, which belongs to an account, lists them.

⚠️ Indexing answers when it is done, not when it starts: "Indexing completed
in 1 s" after a second for thirteen files. A second start while one runs gets
500 ``{"error": "Already running"}``.

⚠️ Nothing in the REST API says that an index is running; PhotoPrism tells
its own interface over the websocket. There is no card for it.

⚠️ The twelve generated patterns all went into review (``count.review``):
they carry no camera data and got the lowest quality score.
"""

from __future__ import annotations

import time
from typing import Any

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

INDEX = Action(id="index", label="Start indexing", icon="refresh-cw", confirm=True)
TYPES = {"image": "Photo", "video": "Video"}


def _not_photoprism() -> AdapterError:
    return AdapterError("This address answers, but not the way PhotoPrism does.", code="not_photoprism",
                        hint="Check the URL; PhotoPrism listens on port 2342 unless told otherwise.")


def _count(counts: dict[str, Any], key: str) -> int:
    value = counts.get(key)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


class PhotoPrismAdapter(Adapter):
    kind = "photoprism"
    label = "PhotoPrism"
    category = "media"
    description = "How many photos and videos the library holds, what came in last, and a button that indexes the originals."
    icon = "photoprism"
    #: Confirmed against a live instance on 2026-09-11.
    beta = False
    docs_url = "https://docs.photoprism.app/developer-guide/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://photoprism:2342"),
        Field("token", "App password", type="password", secret=True, required=True,
              help="An app password from Settings > Account > Apps and Devices. A client access token from the command line cannot list photos."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="library", label="Photo library",
                   description="Photos, videos and the ones in review, with a button that indexes the originals.",
                   renderer="value", default_size=(3, 2), refresh_seconds=300, metrics=("photos", "videos")),
        WidgetType(kind="recent", label="Recently added", description="The photos and videos that came into the library last.",
                   renderer="list", default_size=(3, 3), refresh_seconds=300,
                   options=(Field("limit", "Entries", type="number", default=8),)),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('token') or ''}"}

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 60) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/v1{path}", headers=self._headers(config),
            params=params, verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False,
        )
        if response.status_code in (401, 403):
            raise AuthFailed("PhotoPrism rejected the app password.")
        if response.status_code == 400 and path == "/photos":
            raise AuthFailed("PhotoPrism refused to list photos. A client access token cannot; an app password can.")
        if response.status_code >= 400:
            raise AdapterError(f"PhotoPrism answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of PhotoPrism itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("PhotoPrism did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than PhotoPrism.") from error

    async def _config(self, config: dict[str, Any], ctx: Context, cache: float = 60) -> dict[str, Any]:
        answer = await self._json(config, ctx, "/config", cache=cache)
        if not isinstance(answer, dict) or not isinstance(answer.get("count"), dict):
            raise _not_photoprism()
        if answer.get("mode") != "user":
            # ⚠️ Measured: a made-up password gets this same 200, as a visitor with nothing in the library.
            raise AuthFailed("PhotoPrism answered as for a visitor, so the app password was not accepted.")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        answer = await self._config(config, ctx, cache=0)
        counts = answer["count"]
        await self._json(config, ctx, "/photos", {"count": 1}, cache=0)
        return f"PhotoPrism {answer.get('version') or '?'} answers with {_count(counts, 'photos')} photos and {_count(counts, 'videos')} videos."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "recent":
            limit = max(1, int(options.get("limit") or 8))
            photos = await self._json(config, ctx, "/photos", {"count": limit, "offset": 0, "order": "added", "merged": "true"})
            if not isinstance(photos, list):
                raise _not_photoprism()
            return self._recent(photos, time.time())
        return self._library((await self._config(config, ctx))["count"])

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id != "index":
            raise AdapterError("Unknown library action.", code="no_such_action")
        # ⚠️ The answer comes when the run is over, so the wait is long.
        response = await ctx.request("POST", f"{base_url(config)}/api/v1/index", headers=self._headers(config),
                                     json_body={"path": "/", "rescan": False, "cleanup": False},
                                     verify=not config.get("insecure"), timeout=120, auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("PhotoPrism rejected the app password.")
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if response.status_code == 500 and isinstance(answer, dict) and "already running" in str(answer.get("error") or "").lower():
            raise AdapterError("PhotoPrism is indexing already.", code="action_failed")
        if response.status_code >= 400:
            raise AdapterError(f"PhotoPrism answered with HTTP {response.status_code}.", code="action_failed")
        if not isinstance(answer, dict) or not str(answer.get("message") or "").startswith("Indexing completed"):
            raise AdapterError("PhotoPrism answered, but did not say that indexing completed.", code="action_failed")
        ctx.forget_answers()
        return "Indexing completed."

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _library(counts: dict[str, Any]) -> WidgetData:
        photos, videos = _count(counts, "photos"), _count(counts, "videos")
        return WidgetData(
            status="ok",
            primary={"label": "Photos", "value": photos},
            secondary=[{"label": "Videos", "value": videos}, {"label": "In review", "value": _count(counts, "review")}],
            actions=[INDEX],
            metrics={"photos": float(photos), "videos": float(videos)},
        )

    @staticmethod
    def _recent(photos: list[Any], now: float) -> WidgetData:
        items = []
        for one in photos:
            if not isinstance(one, dict):
                continue
            kind = str(one.get("Type") or "")
            items.append({
                "title": str(one.get("Title") or one.get("Name") or one.get("FileName") or "?"),
                "subtitle": TYPES.get(kind, kind),
                "status": "ok",
                "value": ago(one.get("CreatedAt"), now=now),
            })
        return WidgetData(status="ok", items=items, meta={"empty": "Nothing indexed yet."})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = time.time()

        def added(seconds: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds))

        if widget_kind == "recent":
            return self._recent([
                {"Type": "image", "Title": "Lake at dawn", "CreatedAt": added(900)},
                {"Type": "video", "Title": "Birthday candles", "CreatedAt": added(7_200)},
                {"Type": "image", "Title": "Harbour walk", "CreatedAt": added(90_000)},
            ], now)
        return self._library({"photos": 18_342 + tick % 4, "videos": 611, "review": 23})


ADAPTER = PhotoPrismAdapter()
