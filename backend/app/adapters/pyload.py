"""pyLoad (pyload-ng 0.5) over its REST API.

Measured on 27.10.2026 against lscr.io/linuxserver/pyload-ng (pyload-ng
0.5.0b3.dev101, API 0.5.0) with a package of two links, one of them a name
that does not resolve, one of them downloading, and a wrong key.

⚠️ This pyLoad has no ``POST /api/login`` any more: it answers **404
"Obsolete API"**, as does ``/api/logout``. A program signs in with an **API key**
(``pl_...``) in the ``X-API-Key`` header. The key is made in the web interface
(Settings, API keys), and for that a person signs in with name and password.
Older pyload-ng builds that still log in over ``/api/login`` are not spoken to.

⚠️ A wrong key and no key at all answer **HTTP 401**, with
``{"error": "Invalid API key"}`` and ``{"error": "Invalid API credentials"}``.
An address the API does not know answers 404 ``{"error": "Not Found"}``.

⚠️ ``pause_server`` and ``unpause_server`` answer ``null`` and change
``status_server.pause`` at once, while ``speed`` still shows the old figure for
a moment. Pausing stops new links; the one downloading finishes its chunk.

⚠️ ``status_server.queue`` and ``total`` count links, and a link that failed
is still one of them. The queue here is counted from ``get_queue_data`` without
the failed and the finished ones, which are a card of their own.

Link status numbers (pyLoad's ``DownloadStatus``): 0 finished, 1 offline,
2 online, 3 queued, 4 skipped, 5 waiting, 6 temporarily offline, 7 starting,
8 failed, 9 aborted, 10 decrypting, 11 custom, 12 downloading, 13 processing,
14 unknown.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)
from .downloads_base import DownloadAdapter, QueueItem, Snapshot

FINISHED, OFFLINE, SKIPPED, WAITING, FAILED, ABORTED, DOWNLOADING = 0, 1, 4, 5, 8, 9, 12
#: What a link in one of these states is: not part of the queue any more, or never going to be.
OUT_OF_THE_QUEUE = {FINISHED, SKIPPED, FAILED, ABORTED, OFFLINE}
STATES = {3: "queued", 5: "queued", 6: "queued", 2: "queued"}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class PyloadAdapter(DownloadAdapter):
    kind = "pyload"
    label = "pyLoad"
    description = "Queue, speed, failed links and a waiting captcha, pause or resume, retry the failed ones."
    icon = "pyload"
    docs_url = "https://github.com/pyload/pyload/wiki"
    #: Measured against pyload-ng 0.5.0b3 in a container; no premium account or captcha plugin was set up.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://pyload:8000"),
        Field("api_key", "API key", type="password", secret=True, required=True,
              help="Made in pyLoad under Settings, API keys. It starts with pl_."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    guide = (
        "In pyLoad, sign in and open Settings, then API keys.",
        "Create a key and copy it right away: pyLoad shows it only once.",
        "The key acts as the user it was made for; a user who may add and change downloads is enough.",
    )
    widgets = (
        *DownloadAdapter.widgets,
        WidgetType(
            kind="attention",
            label="Needs a look",
            description="Links that failed or are offline, with the reason, and a captcha that waits for an answer.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            metrics=("failed",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 5) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api/{path}", headers={"X-API-Key": str(config.get("api_key") or "")},
            verify=not config.get("insecure"), cache_seconds=cache,
        )
        return self._answer(response)

    async def _post(self, config: dict[str, Any], ctx: Context, path: str) -> Any:
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/{path}", headers={"X-API-Key": str(config.get("api_key") or "")},
            verify=not config.get("insecure"),
        )
        ctx.forget_answers()
        return self._answer(response)

    @staticmethod
    def _answer(response: Any) -> Any:
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way pyLoad 0.5 does.", code="not_pyload",
                               hint="Use the address of the pyLoad web interface, usually port 8000, and pyLoad 0.5 or newer.")
        if response.status_code >= 400:
            raise AdapterError(f"pyLoad answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("pyLoad did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than pyLoad.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "get_server_version", cache=0)
        snapshot = await self.snapshot(config, ctx)
        return f"pyLoad {version} answers, {snapshot.total} items in the queue."

    # -- the download client -------------------------------------------------

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        status = await self._get(config, ctx, "status_server")
        active = await self._get(config, ctx, "status_downloads")
        packages = await self._get(config, ctx, "get_queue_data")
        free = await self._get(config, ctx, "free_space")
        return self._snapshot(status or {}, active or [], packages or [], free)

    @staticmethod
    def _snapshot(status: dict[str, Any], active: list[dict[str, Any]], packages: list[dict[str, Any]], free: Any) -> Snapshot:
        running = {link.get("fid"): link for link in active if isinstance(link, dict)}
        items = []
        remaining = 0.0
        for package in packages:
            for link in package.get("links") or []:
                state = int(_number(link.get("status")))
                if state in OUT_OF_THE_QUEUE:
                    continue
                size = _number(link.get("size"))
                now = running.get(link.get("fid"))
                progress = _number(now.get("percent")) if now else 0.0
                speed = _number(now.get("speed")) if now else 0.0
                remaining += _number(now.get("bleft")) if now else size
                items.append(QueueItem(
                    name=str(link.get("name") or link.get("url") or "?"), progress=progress, size_bytes=size or None,
                    eta_seconds=_number(now.get("eta")) if now and speed else None,
                    state=STATES.get(state, "downloading"), identifier=str(link.get("fid") or ""),
                ))
        free_bytes = _number(free)
        return Snapshot(
            download_bps=_number(status.get("speed")),
            paused=bool(status.get("pause")),
            remaining_bytes=remaining,
            items=items,
            total=len(items),
            free_bytes=free_bytes or None,
        )

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        await self._post(config, ctx, "pause_server")

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        await self._post(config, ctx, "unpause_server")

    # -- the card of what needs a look -----------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind != "attention":
            return await super().fetch(widget_kind, config, options, ctx)
        status = await self._get(config, ctx, "status_server")
        packages = await self._get(config, ctx, "get_queue_data")
        return self.attention_card(status or {}, packages or [], options)

    @staticmethod
    def attention_card(status: dict[str, Any], packages: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        items = []
        if status.get("captcha"):
            items.append({"title": "A captcha waits for an answer", "subtitle": "Downloads of that host stand still until it is solved.",
                          "value": "Captcha", "status": "warn"})
        failed = 0
        for package in packages:
            for link in package.get("links") or []:
                state = int(_number(link.get("status")))
                if state not in (FAILED, ABORTED, OFFLINE):
                    continue
                failed += 1
                reason = str(link.get("error") or link.get("statusmsg") or "").strip()
                items.append({
                    "id": str(link.get("fid") or ""),
                    "title": str(link.get("name") or link.get("url") or "?"),
                    "subtitle": " · ".join(piece for piece in (str(package.get("name") or ""), reason[:140]) if piece),
                    "value": {OFFLINE: "Offline", ABORTED: "Aborted"}.get(state, "Failed"),
                    "status": "bad" if state != OFFLINE else "warn",
                })
        limit = max(1, min(50, int(options.get("limit") or 8)))
        waiting = bool(status.get("captcha"))
        return WidgetData(
            status="bad" if failed else "warn" if waiting else "ok",
            items=items[:limit],
            secondary=[{"label": "Failed", "value": failed}],
            metrics={"failed": float(failed)},
            actions=[Action(id="retry", label="Try the failed ones again", icon="refresh-cw", confirm=True)] if failed else [],
            meta={"empty": "Nothing needs a look."},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "retry":
            await self._post(config, ctx, "restart_failed")
            return "The failed links are queued again."
        return await super().action(widget_kind, action_id, params, config, options, ctx)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind != "attention":
            return super().demo(widget_kind, options, tick)
        broke = fake.flicker("pyload-failed", tick, 0.35)
        packages = [{"name": "Harbour Lights S03", "links": [
            {"fid": 1, "name": "Harbour.Lights.S03E01.mkv", "status": FINISHED},
            {"fid": 2, "name": "Harbour.Lights.S03E02.mkv", "status": FAILED, "error": "Parse error: Empty file | Plugin may be out of date"},
        ]}]
        if broke:
            packages.append({"name": "Orbital 2025", "links": [{"fid": 3, "name": "Orbital.2025.part1.rar", "status": OFFLINE, "statusmsg": "offline"}]})
        return self.attention_card({"captcha": fake.flicker("pyload-captcha", tick, 0.15)}, packages, options)


ADAPTER: Adapter = PyloadAdapter()
