"""rTorrent over XML-RPC, straight or through ruTorrent.

Measured on 27.09.2026 against crazymax/rtorrent-rutorrent (rTorrent
0.16.22, API version 26, ruTorrent 5.3.14), with a Debian 13.7 netinst
image downloading at a cap of 200 KiB/s down and 50 KiB/s up, three small
invented torrents made for the purpose (one finished and stopped, one
seeding, one whose tracker does not exist and then paused), one of them
damaged on disk and checked again, and a 400 MB one caught in its hash
check. Both doors were measured: the XML-RPC port of the image and
ruTorrent's httprpc plugin, each with a right and a wrong password.

⚠️ There are two ways in and the same calls work through both. The image
serves rTorrent's XML-RPC on its own port (8000), where nginx hands every
path to rTorrent, ``/RPC2`` as much as ``/`` or ``/RPC``. ruTorrent (port
8080) has no ``/RPC2``, it answers 404; its plugin
``plugins/httprpc/action.php`` takes the same raw XML-RPC and passes it on.
The adapter takes a full address as it is, and for a bare one tries
``/RPC2`` first and the plugin second, and remembers which answered.

⚠️ ruTorrent filters what it passes on ("sanitize", its default): a
multicall carrying ``execute.throw`` came back 403 with the fault -501 "The
command ... was rejected by this server". Everything the cards read went
through, ``d.multicall2`` and ``system.multicall`` included. Changing
something is another matter: the members of a multicall reach rTorrent
untrusted, and some calls answer 0 there and do nothing; ``pause`` below
says which.

⚠️ The XML-RPC port of the image is open to anybody until a password is set:
its switch is the file ``/passwd/rpc.htpasswd``, not ``xmlrpc.htpasswd``
next to it, and with an empty file nginx asks for nothing. Both doors answer
a wrong password with nginx's 401 page.

⚠️ With rTorrent stopped behind them the XML-RPC port answers 502 and
ruTorrent 500 "Could not complete the rTorrent XMLRPC request."; neither
means the address is wrong.

⚠️ The state is four numbers, and the obvious reading of each is wrong
somewhere. ``d.state`` is started or stopped, ``d.is_active`` is paused or
not, ``d.is_open`` stays 1 after a stopped torrent was checked, and
``d.complete`` stays 1 while a finished torrent is checked again. During
the check ``d.is_hash_checking`` is 1, ``d.hashing`` was 3, ``d.is_active``
drops to 0, and ``d.completed_chunks`` read 0 while ``d.chunks_hashed``
counted up: the progress of a check is the chunks hashed.

⚠️ ``d.message`` carries tracker complaints as much as real trouble, and a
healthy seeding torrent without a tracker read "Tracker: [No DHT nodes
available for peer search.]". ruTorrent paints every message red except
"Tracker: [Tried all trackers.]"; this adapter calls only messages that do
not start with ``Tracker: [`` an error, such as "Download registered as
completed, but hash check returned unfinished chunks." on the damaged one.

⚠️ Rates and sizes are bytes: ``d.down.rate`` and
``throttle.global_down.rate`` in bytes per second, and the cap set with
``throttle.global_down.max_rate.set_kb`` 200 read back as 204800.

The linuxserver image for ruTorrent was last updated in 2021. The image
jesec/rtorrent-flood opens SCGI on a local socket only, going by the
``rtorrent.rc`` it ships with, which no HTTP client reaches; it was not run
here.

The answers are parsed with ``xmlrpc.client``, which uses expat without
loading external entities; the expat that comes with Python refuses
entity expansion attacks of its own accord, and the size of an answer is
capped by ``Context.request``.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any
from urllib.parse import urlsplit
from xml.parsers.expat import ExpatError

from . import demo as fake
from .base import (
    AdapterError,
    AuthFailed,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    human_rate,
)
from .downloads_base import DownloadAdapter, QueueItem, Snapshot

ENDPOINT = "rtorrent_endpoint"
#: Tried in this order when the address names none.
ENDPOINTS = ("/RPC2", "/plugins/httprpc/action.php")
FIELDS = ("d.hash=", "d.name=", "d.state=", "d.is_active=", "d.is_open=", "d.complete=", "d.is_hash_checking=", "d.hashing=",
          "d.message=", "d.size_bytes=", "d.completed_bytes=", "d.left_bytes=", "d.down.rate=", "d.up.rate=",
          "d.size_chunks=", "d.chunks_hashed=")
KEYS = tuple(field[2:-1].replace(".", "_") for field in FIELDS)
#: The order the list goes in: trouble first, the finished ones last.
ORDER = {"error": 0, "downloading": 1, "checking": 2, "paused": 3, "seeding": 4, "finished": 5}
STATUS = {"error": "bad", "paused": "warn"}
URL_HINT = "Enter the XML-RPC address of rTorrent, such as http://rtorrent:8000/RPC2, or the address of ruTorrent."
DOWN_HINT = "Check that rTorrent itself is running; the web server in front of it answers."


def state_of(row: dict[str, Any]) -> str:
    """One word for the four numbers; see the top of the file."""
    if int(row.get("is_hash_checking") or 0) or int(row.get("hashing") or 0):
        return "checking"
    message = str(row.get("message") or "")
    if message and not message.startswith("Tracker: ["):
        return "error"
    running = int(row.get("state") or 0) == 1 and int(row.get("is_active") or 0) == 1
    if int(row.get("complete") or 0):
        return "seeding" if running else "finished"
    return "downloading" if running else "paused"


def progress_of(row: dict[str, Any], state: str) -> float:
    if state == "checking":
        chunks = int(row.get("size_chunks") or 0)
        return min(100.0, 100.0 * int(row.get("chunks_hashed") or 0) / chunks) if chunks else 0.0
    size = float(row.get("size_bytes") or 0)
    return min(100.0, 100.0 * float(row.get("completed_bytes") or 0) / size) if size else 0.0


class RTorrentAdapter(DownloadAdapter):
    kind = "rtorrent"
    label = "rTorrent"
    description = "Torrents, speed and pause or resume in rTorrent, straight over XML-RPC or through ruTorrent."
    icon = "rutorrent"
    keywords = ("ruTorrent",)
    beta = False
    docs_url = "https://kannibalox.github.io/rtorrent-docs/cmd-ref.html"
    has_upload = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://rutorrent:8080",
              help="The address of ruTorrent, or rTorrent's XML-RPC address such as http://rtorrent:8000/RPC2."),
        Field("username", "Username"),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        *DownloadAdapter.widgets,
        WidgetType(kind="torrents", label="Torrents",
                   description="Every torrent with its state, progress, size and speed, seeding and finished ones included.",
                   renderer="list", default_size=(4, 3), refresh_seconds=10,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="overview", label="rTorrent overview",
                   description="How many torrents there are in each state, with the speed down and up.",
                   renderer="value", default_size=(3, 2), refresh_seconds=10, metrics=("download", "upload"),
                   parts=(("download", "Download"), ("upload", "Upload"), ("downloading", "Downloading"), ("seeding", "Seeding"),
                          ("paused", "Paused"), ("finished", "Finished"), ("error", "Error"), ("checking", "Checking"))),
    )

    # -- talking to rTorrent -------------------------------------------------

    def _candidates(self, config: dict[str, Any], ctx: Context) -> list[str]:
        base = base_url(config)
        path = urlsplit(base).path.lower()
        if path.endswith(("/rpc2", ".php")):
            return [base]
        held = ctx.cache.get(ENDPOINT)
        if isinstance(held, tuple) and held[0] == base:
            return [held[1]]
        return [base + one for one in ENDPOINTS]

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, *params: Any) -> Any:
        body = xmlrpc.client.dumps(params, method).encode()
        auth = (str(config["username"]), str(config.get("password") or "")) if config.get("username") else None
        for endpoint in self._candidates(config, ctx):
            response = await ctx.request("POST", endpoint, content=body, headers={"Content-Type": "text/xml"}, auth=auth,
                                         verify=not config.get("insecure"), timeout=15.0, auth_errors=False)
            xml = "xml" in response.headers.get("content-type", "")
            if response.status_code == 401 or (response.status_code == 403 and not xml):
                raise AuthFailed("rTorrent rejected the user name or password.")
            if response.status_code == 404:
                continue
            if response.status_code >= 500:
                # ⚠️ 502 from the XML-RPC port, 500 from ruTorrent: rTorrent is down.
                raise AdapterError("The web server answers, but rTorrent behind it does not.", code="rtorrent_down", hint=DOWN_HINT)
            try:
                answer = xmlrpc.client.loads(response.content)[0]
            except xmlrpc.client.Fault as fault:
                # ⚠️ ruTorrent's refusal is a fault with 403 around it.
                raise AdapterError(f"rTorrent refused {method}: {fault.faultString}", code="rpc_error") from fault
            except (ExpatError, xmlrpc.client.ResponseError, ValueError, IndexError):
                continue
            ctx.cache[ENDPOINT] = (base_url(config), endpoint)
            return answer[0] if answer else None
        ctx.cache.pop(ENDPOINT, None)
        raise AdapterError("This address answers, but not with rTorrent's XML-RPC.", code="not_rtorrent", hint=URL_HINT)

    async def _rows(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        answer = await self._call(config, ctx, "d.multicall2", "", "main", *FIELDS)
        if not isinstance(answer, list):
            raise AdapterError("This address answers, but not with rTorrent's XML-RPC.", code="not_rtorrent", hint=URL_HINT)
        return [dict(zip(KEYS, row, strict=False)) for row in answer if isinstance(row, list)]

    async def _rates(self, config: dict[str, Any], ctx: Context) -> tuple[float, float]:
        answer = await self._call(config, ctx, "system.multicall", [
            {"methodName": "throttle.global_down.rate", "params": []},
            {"methodName": "throttle.global_up.rate", "params": []},
        ])
        # Each member comes back as a list of one, or as a fault struct.
        values = [float(one[0]) if isinstance(one, list) and one else 0.0 for one in answer or []]
        return (values + [0.0, 0.0])[0], (values + [0.0, 0.0])[1]

    # -- the hooks -----------------------------------------------------------

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._call(config, ctx, "system.client_version")
        rows = await self._rows(config, ctx)
        return f"rTorrent {version} answers with {len(rows)} torrents."

    async def snapshot(self, config: dict[str, Any], ctx: Context) -> Snapshot:
        rows = await self._rows(config, ctx)
        down, up = await self._rates(config, ctx)
        return self._snapshot(rows, down, up)

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind in ("torrents", "overview"):
            rows = await self._rows(config, ctx)
            down, up = await self._rates(config, ctx)
            return self._torrents(rows, options) if widget_kind == "torrents" else self._overview(rows, down, up)
        return await super().fetch(widget_kind, config, options, ctx)

    async def pause(self, config: dict[str, Any], ctx: Context) -> None:
        """Stop what is downloading, the way ruTorrent's own pause does.

        ⚠️ One call per torrent and never ``system.multicall``: through
        ruTorrent the members of a multicall go to rTorrent untrusted, where
        ``d.stop`` came back as a fault and ``d.start`` answered 0 and did
        nothing. Sent alone, ruTorrent passes both on as trusted. ``d.stop``
        and not ``d.pause``, because the answer to ``d.pause`` is
        ``d.resume``, and ``d.resume`` through ruTorrent answered 0 and left
        the torrent paused.
        """
        for row in await self._rows(config, ctx):
            if state_of(row) == "downloading":
                await self._call(config, ctx, "d.stop", str(row.get("hash") or ""))

    async def resume(self, config: dict[str, Any], ctx: Context) -> None:
        for row in await self._rows(config, ctx):
            if state_of(row) not in ("paused", "error") or int(row.get("complete") or 0):
                continue
            target = str(row.get("hash") or "")
            if int(row.get("state") or 0) == 1:
                # ⚠️ Paused elsewhere with d.pause: d.start alone leaves it paused.
                await self._call(config, ctx, "d.stop", target)
            await self._call(config, ctx, "d.start", target)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _snapshot(rows: list[dict[str, Any]], down: float, up: float) -> Snapshot:
        items = []
        remaining = 0.0
        for row in rows:
            state = state_of(row)
            # Done is done: a finished torrent checked again is no download.
            if int(row.get("complete") or 0):
                continue
            left = float(row.get("left_bytes") or 0)
            rate = float(row.get("down_rate") or 0)
            remaining += left
            items.append(QueueItem(
                name=str(row.get("name") or row.get("hash") or "?"), progress=progress_of(row, state),
                size_bytes=float(row.get("size_bytes") or 0), eta_seconds=left / rate if rate > 0 and left > 0 else None,
                state=state, identifier=str(row.get("hash") or ""),
            ))
        items.sort(key=lambda item: (ORDER.get(item.state, 9), item.name.lower()))
        paused = bool(items) and all(item.state == "paused" for item in items)
        return Snapshot(download_bps=down, upload_bps=up, paused=paused, remaining_bytes=remaining, items=items, total=len(items))

    @staticmethod
    def _torrents(rows: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        entries = []
        for row in rows:
            state = state_of(row)
            progress = progress_of(row, state)
            parts = [human_bytes(float(row.get("size_bytes") or 0)), state]
            down, up = float(row.get("down_rate") or 0), float(row.get("up_rate") or 0)
            if down > 0:
                parts.append(f"↓ {human_rate(down)}")
            if up > 0:
                parts.append(f"↑ {human_rate(up)}")
            if state == "error":
                parts.append(str(row.get("message") or ""))
            entries.append((ORDER.get(state, 9), str(row.get("name") or "?").lower(), {
                "id": str(row.get("hash") or row.get("name") or ""),
                "title": str(row.get("name") or row.get("hash") or "?"),
                "subtitle": " · ".join(part for part in parts if part),
                "progress": round(progress, 1),
                "value": f"{progress:.0f}%",
                "status": STATUS.get(state, "ok"),
            }))
        entries.sort(key=lambda entry: (entry[0], entry[1]))
        items = [entry[2] for entry in entries]
        return WidgetData(
            status="bad" if any(item["status"] == "bad" for item in items) else "ok",
            items=items[: int(options.get("limit") or 8)],
            meta={"empty": "rTorrent has no torrents."},
        )

    @staticmethod
    def _overview(rows: list[dict[str, Any]], down: float, up: float) -> WidgetData:
        counts = dict.fromkeys(ORDER, 0)
        for row in rows:
            counts[state_of(row)] += 1
        return WidgetData(
            status="bad" if counts["error"] else "ok",
            primary={"label": "Torrents", "value": len(rows)},
            secondary=[
                {"label": "Download", "value": human_rate(down), "part": "download"},
                {"label": "Upload", "value": human_rate(up), "part": "upload"},
                {"label": "Downloading", "value": counts["downloading"], "part": "downloading"},
                {"label": "Seeding", "value": counts["seeding"], "part": "seeding"},
                {"label": "Paused", "value": counts["paused"], "part": "paused"},
                {"label": "Finished", "value": counts["finished"], "part": "finished"},
                {"label": "Error", "value": counts["error"], "part": "error"},
                {"label": "Checking", "value": counts["checking"], "part": "checking"},
            ],
            metrics={"download": round(down / 1024 / 1024, 2), "upload": round(up / 1024 / 1024, 2)},
        )

    # -- demo ----------------------------------------------------------------

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind in ("queue", "speed"):
            return super().demo(widget_kind, options, tick)
        paused = fake.flicker("rtorrent-paused", tick, 0.1)
        down = 0.0 if paused else fake.walk("rtorrent-down", tick, 2, 18) * 1024 * 1024
        up = fake.walk("rtorrent-up", tick, 0.2, 3) * 1024 * 1024
        gib = 1024 ** 3
        done = (35 + tick * 0.4) % 100
        rows = [
            {"hash": "demo-one", "name": "Copper.Sky.2025.2160p", "state": 1, "is_active": 0 if paused else 1, "complete": 0,
             "size_bytes": 18 * gib, "completed_bytes": 18 * gib * done / 100, "left_bytes": 18 * gib * (1 - done / 100),
             "down_rate": down, "up_rate": up / 3},
            {"hash": "demo-two", "name": "Harbour.Lights.S03E04", "state": 1, "is_active": 1, "complete": 1,
             "size_bytes": 2.4 * gib, "completed_bytes": 2.4 * gib, "up_rate": up * 2 / 3},
            {"hash": "demo-three", "name": "debian-13.7.0-amd64-netinst.iso", "state": 0, "is_active": 0, "complete": 1,
             "size_bytes": 756 * 1024 ** 2, "completed_bytes": 756 * 1024 ** 2},
            {"hash": "demo-four", "name": "Orbital.2025.REMUX", "state": 1, "is_active": 0, "complete": 0,
             "size_bytes": 41 * gib, "completed_bytes": 9 * gib, "left_bytes": 32 * gib},
        ]
        if fake.flicker("rtorrent-broken", tick, 0.2):
            rows.append({"hash": "demo-five", "name": "Nightshift.2026.1080p", "state": 0, "is_active": 0, "complete": 0,
                         "size_bytes": 6 * gib, "completed_bytes": 2 * gib,
                         "message": "Download registered as completed, but hash check returned unfinished chunks."})
        if widget_kind == "overview":
            return self._overview(rows, down, up)
        return self._torrents(rows, options)


ADAPTER = RTorrentAdapter()
