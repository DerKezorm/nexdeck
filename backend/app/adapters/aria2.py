"""aria2 over its JSON-RPC.

Measured on 27.10.2026 against p3terx/aria2-pro (aria2 1.36.0) with an RPC
secret, one capped download running, one waiting, one that failed on a name
that does not resolve and a small one that finished.

⚠️ A wrong secret answers **HTTP 400** with ``{"error": {"code": 1,
"message": "Unauthorized"}}``, not 401, and a call without any secret the
same. Reading the status code alone calls that "aria2 answered with an
error"; the code inside the body says it is the credentials.

⚠️ In a ``system.multicall`` the same refusal comes back as **HTTP 200**, with
the fault standing in the place of the result (``[{"code": 1, ...}]`` where
an answer would be ``[result]``). The secret goes into every call inside it,
the outer call carries none. All numbers come as strings, also the counts.

⚠️ ``tellActive`` and its kin hand over every mirror of a file under
``files[].uris``, one entry per connection a download may open, up to a
hundred of them for an ordinary link. Asking for ``keys`` does not leave
``files`` out, so the rows are kept small by asking for what is needed and
nothing is done with the lists.

⚠️ A finished BitTorrent download goes on seeding as ``active`` with the whole
size completed; it is not part of the queue here, the way Deluge's seeding
torrents are not. A magnet link first runs as a download named
``[METADATA]...`` before the real one takes its place.

⚠️ ``tellStopped`` with a negative offset reads from the newest result
backwards, which is what a card wants; ``purgeDownloadResult`` forgets the
records only, never a file.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse

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
    base_url,
    human_bytes,
)
from .downloads_base import DownloadAdapter, QueueItem, Snapshot

ACTIVE_KEYS = ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "uploadSpeed", "files", "bittorrent"]
STOPPED_KEYS = ["gid", "status", "totalLength", "errorCode", "errorMessage", "files", "bittorrent"]
#: How many waiting downloads one read asks for.
WAITING_WINDOW = 100


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _name(entry: dict[str, Any]) -> str:
    """What a person calls this download: the torrent's name, else the file's."""
    torrent = ((entry.get("bittorrent") or {}).get("info") or {}).get("name")
    if torrent:
        return str(torrent)
    for file in entry.get("files") or []:
        path = str(file.get("path") or "")
        if path:
            return path.replace("\\", "/").rsplit("/", 1)[-1]
        # Not started yet, so there is no file on disk: the name is the end of the address.
        for uri in file.get("uris") or []:
            last = unquote(urlparse(str(uri.get("uri") or "")).path).rsplit("/", 1)[-1]
            if last:
                return last
    return str(entry.get("gid") or "?")


def _seeding(entry: dict[str, Any]) -> bool:
    total = _number(entry.get("totalLength"))
    return bool(entry.get("bittorrent")) and total > 0 and _number(entry.get("completedLength")) >= total


class Aria2Adapter(DownloadAdapter):
    kind = "aria2"
    label = "aria2"
    description = "Queue, speed, finished and failed downloads, pause or resume over JSON-RPC."
    icon = "aria2"
    docs_url = "https://aria2.github.io/manual/en/html/aria2c.html#rpc-interface"
    #: Measured against aria2 1.36.0 in a container; not yet on a long-lived instance.
    beta = True
    has_upload = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://aria2:6800",
              help="The RPC address of aria2, usually port 6800. The /jsonrpc at the end is added when it is missing."),
        Field("secret", "RPC secret", type="password", secret=True,
              help="The value of rpc-secret. Leave it empty when aria2 runs without one."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        *DownloadAdapter.widgets,
        WidgetType(
            kind="stopped",
            label="Finished and failed",
            description="The latest downloads aria2 has stopped with, failed ones in red and the reason under them.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            metrics=("failed",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    # -- the wire ------------------------------------------------------------

    def _address(self, config: dict[str, Any]) -> str:
        address = base_url(config)
        return address if address.endswith("/jsonrpc") else f"{address}/jsonrpc"

    def _token(self, config: dict[str, Any]) -> list[str]:
        secret = str(config.get("secret") or "")
        return [f"token:{secret}"] if secret else []

    def _refused(self, fault: dict[str, Any], secret_set: bool) -> AdapterError:
        message = str(fault.get("message") or "aria2 refused the request.")
        if message == "Unauthorized":
            return AuthFailed("aria2 rejected the RPC secret." if secret_set else "aria2 wants an RPC secret.")
        return AdapterError(message, code="rpc_error")

    async def _post(self, config: dict[str, Any], ctx: Context, payload: dict[str, Any]) -> Any:
        response = await ctx.request("POST", self._address(config), json_body=payload,
                                     verify=not config.get("insecure"), auth_errors=False)
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or "jsonrpc" not in body:
            if response.status_code in (401, 403):
                raise AuthFailed("aria2 asked for a sign-in the adapter cannot give.")
            raise AdapterError("This address answers, but not the way aria2 does.", code="not_aria2",
                               hint="Use the RPC address of aria2, usually port 6800, and not a web interface in front of it.")
        if body.get("error"):
            raise self._refused(body["error"], bool(config.get("secret")))
        return body.get("result")

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, *params: Any) -> Any:
        return await self._post(config, ctx, {"jsonrpc": "2.0", "id": "nexdeck", "method": f"aria2.{method}",
                                              "params": [*self._token(config), *params]})

    async def _many(self, config: dict[str, Any], ctx: Context, *calls: tuple[str, ...]) -> list[Any]:
        """Several calls in one request. Each answer is checked for the fault standing in its place."""
        token = self._token(config)
        result = await self._post(config, ctx, {
            "jsonrpc": "2.0", "id": "nexdeck", "method": "system.multicall",
            "params": [[{"methodName": f"aria2.{name}", "params": [*token, *rest]} for name, *rest in calls]],
        })
        answers = []
        for one in result or []:
            if isinstance(one, dict):
                raise self._refused(one, bool(config.get("secret")))
            answers.append(one[0] if isinstance(one, list) and one else None)
        return answers

    # -- the download client ---------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version, stat = await self._many(config, ctx, ("getVersion",), ("getGlobalStat",))
        waiting = int(_number((stat or {}).get("numActive")) + _number((stat or {}).get("numWaiting")))
        return f"aria2 {(version or {}).get('version', '')} answers, {waiting} items in the queue."

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        stat, active, waiting = await self._many(
            config, ctx, ("getGlobalStat",), ("tellActive", ACTIVE_KEYS),
            ("tellWaiting", 0, WAITING_WINDOW, ACTIVE_KEYS),
        )
        return self._snapshot(stat or {}, active or [], waiting or [])

    @staticmethod
    def _snapshot(stat: dict[str, Any], active: list[dict[str, Any]], waiting: list[dict[str, Any]]) -> Snapshot:
        items = []
        remaining = 0.0
        for entry in [*active, *waiting]:
            if _seeding(entry):
                continue
            state = str(entry.get("status") or "")
            total, done, speed = _number(entry.get("totalLength")), _number(entry.get("completedLength")), _number(entry.get("downloadSpeed"))
            remaining += max(0.0, total - done)
            items.append(QueueItem(
                name=_name(entry), progress=100.0 * done / total if total else 0.0, size_bytes=total or None,
                eta_seconds=(total - done) / speed if speed and total else None,
                state={"active": "downloading", "waiting": "queued", "paused": "paused"}.get(state, state or "downloading"),
                identifier=str(entry.get("gid") or ""),
            ))
        # ``numWaiting`` counts the paused ones too, and can be more than the window read.
        beyond = max(0, int(_number(stat.get("numWaiting"))) - len(waiting))
        return Snapshot(
            download_bps=_number(stat.get("downloadSpeed")),
            upload_bps=_number(stat.get("uploadSpeed")),
            # Paused means nothing runs and everything that waits was paused: a queue of only waiting ones is just busy elsewhere.
            paused=bool(items) and all(item.state == "paused" for item in items),
            remaining_bytes=remaining,
            items=items,
            total=len(items) + beyond,
        )

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        await self._call(config, ctx, "pauseAll")

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        await self._call(config, ctx, "unpauseAll")

    # -- the card of what has stopped -------------------------------------------

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind != "stopped":
            return await super().fetch(widget_kind, config, options, ctx)
        limit = max(1, min(50, int(options.get("limit") or 8)))
        stat, stopped = await self._many(config, ctx, ("getGlobalStat",), ("tellStopped", -1, limit, STOPPED_KEYS))
        return self.stopped_card(stat or {}, stopped or [], limit)

    @staticmethod
    def stopped_card(stat: dict[str, Any], stopped: list[dict[str, Any]], limit: int = 8) -> WidgetData:
        items = []
        failed = 0
        for entry in stopped[:limit]:
            state = str(entry.get("status") or "")
            size = _number(entry.get("totalLength"))
            if state == "error":
                failed += 1
                subtitle = str(entry.get("errorMessage") or "Failed.").strip().splitlines()[0][:160]
            else:
                subtitle = human_bytes(size) if size else ""
            items.append({
                "id": str(entry.get("gid") or ""),
                "title": _name(entry),
                "subtitle": subtitle,
                "value": {"error": "Failed", "removed": "Removed"}.get(state, "Done"),
                "status": "bad" if state == "error" else "ok",
            })
        kept = int(_number(stat.get("numStopped")))
        return WidgetData(
            status="bad" if failed else "ok",
            items=items,
            secondary=[{"label": "Kept", "value": kept}, {"label": "Since start", "value": int(_number(stat.get("numStoppedTotal")))}],
            metrics={"failed": float(failed)},
            actions=[Action(id="purge", label="Clear the list", icon="trash-2", confirm=True)] if kept else [],
            meta={"empty": "Nothing has stopped yet."},
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "purge":
            await self._call(config, ctx, "purgeDownloadResult")
            return "The list of stopped downloads is cleared."
        return await super().action(widget_kind, action_id, params, config, options, ctx)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind != "stopped":
            return super().demo(widget_kind, options, tick)
        broke = fake.flicker("aria2-failed", tick, 0.3)
        stopped = [
            {"gid": "a1", "status": "complete", "totalLength": str(3 * 1024 ** 3), "files": [{"path": "/downloads/Copper.Sky.2025.2160p.mkv"}]},
            {"gid": "a2", "status": "complete", "totalLength": str(700 * 1024 ** 2), "files": [{"path": "/downloads/Harbour.Lights.S03E03.mkv"}]},
        ]
        if broke:
            stopped.insert(0, {"gid": "a3", "status": "error", "errorMessage": "The response status is not successful. status=404",
                               "files": [{"path": "", "uris": [{"uri": "https://example.com/files/Orbital.2025.REMUX.mkv"}]}]})
        return self.stopped_card({"numStopped": str(len(stopped)), "numStoppedTotal": str(40 + tick // 20)}, stopped, int(options.get("limit") or 8))


ADAPTER: Adapter = Aria2Adapter()
