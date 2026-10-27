"""slskd: the Soulseek client of a home server, its connection and its transfers.

Measured on 27.10.2026 against slskd/slskd 0.26.2 (a fresh container with a
web user, an API key and no Soulseek account): the sign-in with name and
password, the API key, a wrong key, ``/application`` in full, the empty
transfer lists, ``DELETE .../completed``. **The transfers themselves are not
measured**: they need a connection to the Soulseek network, which needs an
account, so the rows follow slskd's OpenAPI file and its source (a list of
users, each with directories, each with files), and the card says so below.

⚠️ ``GET /api/v0/application`` is the one address that tells most: the version
(with whether a newer one exists), ``server.state`` and its flags
(``isConnected``, ``isLoggedIn``), the shares (files, folders, whether a scan
runs or the index is faulted) and the relay agents. A fresh slskd without a
Soulseek account answers ``"state": "None"`` and ``isConnected: false``, and
every other address still works.

⚠️ Two ways in. An **API key** in ``X-API-Key`` (set in the configuration
under ``web.authentication.api_keys``) and a **sign-in**, ``POST /api/v0/session``
with ``{"username", "password"}``, which answers ``{"token", "expires"}`` (the
time in seconds) and then goes in ``Authorization: Bearer``. A wrong key and a
wrong password answer 401 with no body, and so does any address without
either.

⚠️ A transfer's ``state`` is a text of flags joined by a comma, such as
``Queued, Remotely`` (the other side holds it in its queue), ``InProgress``,
``Completed, Succeeded`` or ``Completed, TimedOut``. Remote queues, refusals
and time-outs are everyday on Soulseek, so a failed row is yellow and an
error red, and the card itself stays green while the connection is up.

⚠️ ``DELETE /api/v0/transfers/downloads/all/completed`` answers 204 and takes
the finished records off the list; the files stay where they are.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

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
    base_url,
    duration_short,
    human_bytes,
    human_rate,
)

#: Everything under one segment of the transfers address.
DIRECTIONS = ("downloads", "uploads")
#: How far along a download has to have been for its disappearance to mean "finished".
NEARLY_DONE = 95.0
STATE_WORD = {
    "inprogress": "Transferring",
    "requested": "Requested",
    "initializing": "Starting",
    "queued": "Queued",
    "queued, locally": "Queued here",
    "queued, remotely": "Queued by the other side",
    "completed, succeeded": "Done",
    "completed, timedout": "Timed out",
    "completed, errored": "Failed",
    "completed, rejected": "Refused",
    "completed, cancelled": "Cancelled",
    "completed, aborted": "Aborted",
}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _files(users: Any) -> Iterator[dict[str, Any]]:
    """Every transfer in slskd's list: users, each with directories, each with files."""
    for user in users if isinstance(users, list) else []:
        if not isinstance(user, dict):
            continue
        if "filename" in user:
            yield user
            continue
        for directory in user.get("directories") or []:
            for file in (directory or {}).get("files") or []:
                if isinstance(file, dict):
                    yield {"username": user.get("username"), **file}


def _kind(file: dict[str, Any]) -> str:
    """``active``, ``queued``, ``done`` or ``failed`` from the text of flags."""
    state = str(file.get("state") or "").lower().replace(" ", "")
    if state.startswith("completed"):
        return "done" if "succeeded" in state else "failed"
    if "inprogress" in state:
        return "active"
    return "queued"


def _name(file: dict[str, Any]) -> str:
    return str(file.get("filename") or "?").replace("\\", "/").rsplit("/", 1)[-1] or "?"


class SlskdAdapter(Adapter):
    kind = "slskd"
    label = "slskd"
    category = "media"
    description = "The Soulseek connection, shared files, and what is downloading and uploading."
    icon = "slskd"
    docs_url = "https://github.com/slskd/slskd/blob/master/docs/api.md"
    #: Measured against slskd 0.26.2 without a Soulseek account; the transfer rows follow the OpenAPI file.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://slskd:5030"),
        Field("api_key", "API key", type="password", secret=True,
              help="From the slskd configuration under web, authentication, api_keys. Leave empty to sign in with a name and password."),
        Field("username", "User name", help="The web user of slskd. Only without an API key."),
        Field("password", "Password", type="password", secret=True, help="Only without an API key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="status",
            label="Soulseek status",
            description="Whether slskd is connected to Soulseek, what it shares and what is on the move.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("download", "upload"),
        ),
        WidgetType(
            kind="downloads",
            label="Downloads",
            description="What is downloading, queued or failed, with progress.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=15,
            metrics=("download",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="uploads",
            label="Uploads",
            description="What others are taking from you or waiting for.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=15,
            metrics=("upload",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    # -- the wire ------------------------------------------------------------

    async def _headers(self, config: dict[str, Any], ctx: Context, fresh: bool = False) -> dict[str, str]:
        if config.get("api_key"):
            return {"X-API-Key": str(config["api_key"])}
        if not (config.get("username") and config.get("password")):
            raise AuthFailed("slskd needs an API key, or a user name and a password.")
        token = ctx.cache.get("slskd_token")
        if fresh or not token or token[1] <= time.time() + 60:
            response = await ctx.request(
                "POST", f"{base_url(config)}/api/v0/session",
                json_body={"username": str(config["username"]), "password": str(config["password"])},
                verify=not config.get("insecure"), auth_errors=False,
            )
            if response.status_code in (400, 401, 403):
                raise AuthFailed("slskd rejected the user name or the password.")
            answer = self._json(response)
            if not isinstance(answer, dict) or not answer.get("token"):
                raise AdapterError("slskd did not hand out a token.", code="no_token")
            token = (str(answer["token"]), _number(answer.get("expires")) or time.time() + 3600)
            ctx.cache["slskd_token"] = token
        return {"Authorization": f"Bearer {token[0]}"}

    # -- custom cards -------------------------------------------------------------

    #: A kind that signs in by a name and password holds a token that a card renews the way the built-in cards do.
    raw_session = True

    async def raw_signed(self, config: dict[str, Any], ctx: Context) -> tuple[dict[str, str], dict[str, Any], None]:
        # ⚠️ Not ``raw_headers``: ``_headers`` here signs in and so takes the context, which the helper of that name does not.
        return await self._headers(config, ctx), {}, None

    async def raw_renew(self, config: dict[str, Any], ctx: Context, refused: Any, *, again: bool) -> tuple[dict[str, str], dict[str, Any], None] | None:
        """A token slskd turned down: one new sign-in. A key that is turned down stays turned down."""
        if config.get("api_key") or again:
            return None
        ctx.cache.pop("slskd_token", None)
        return await self._headers(config, ctx, fresh=True), {}, None

    @staticmethod
    def _json(response: Any) -> Any:
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way slskd does.", code="not_slskd",
                               hint="Use the address of the slskd web interface, usually port 5030.")
        if response.status_code >= 400:
            raise AdapterError(f"slskd answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("slskd did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than slskd.") from error

    async def _request(self, config: dict[str, Any], ctx: Context, method: str, path: str, cache: float = 0) -> Any:
        for attempt in (0, 1):
            response = await ctx.request(
                method, f"{base_url(config)}/api/v0{path}", headers=await self._headers(config, ctx, fresh=bool(attempt)),
                verify=not config.get("insecure"), cache_seconds=cache if method == "GET" else 0, auth_errors=False,
            )
            # A token that ran out early, or was revoked: one new sign-in, then the answer stands.
            if response.status_code == 401 and not config.get("api_key") and not attempt:
                ctx.cache.pop("slskd_token", None)
                continue
            if response.status_code == 401:
                raise AuthFailed("slskd rejected the API key." if config.get("api_key") else "slskd rejected the sign-in.")
            if response.status_code == 204:
                return None
            return self._json(response)
        raise AuthFailed("slskd rejected the sign-in.")  # pragma: no cover

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        application = await self._request(config, ctx, "GET", "/application")
        if not isinstance(application, dict) or "server" not in application:
            raise AdapterError("This address answers, but not the way slskd does.", code="not_slskd")
        version = str((application.get("version") or {}).get("current") or "")
        server = application["server"] or {}
        where = "connected to Soulseek" if server.get("isLoggedIn") else "not connected to Soulseek"
        return f"slskd {version} answers, {where}." if version else f"slskd answers, {where}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind in DIRECTIONS:
            users = await self._request(config, ctx, "GET", f"/transfers/{widget_kind}", cache=5)
            return self.transfers_card(widget_kind, users, options, link)
        application = await self._request(config, ctx, "GET", "/application", cache=10)
        downloads = await self._request(config, ctx, "GET", "/transfers/downloads", cache=5)
        uploads = await self._request(config, ctx, "GET", "/transfers/uploads", cache=5)
        return self.status_card(application or {}, downloads, uploads, link)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def status_card(application: dict[str, Any], downloads: Any, uploads: Any, link: str | None = None) -> WidgetData:
        server = application.get("server") if isinstance(application.get("server"), dict) else {}
        shares = application.get("shares") if isinstance(application.get("shares"), dict) else {}
        version = application.get("version") if isinstance(application.get("version"), dict) else {}
        if server.get("isLoggedIn"):
            word, status = "Connected", "ok"
        elif server.get("isConnecting") or server.get("isLoggingIn") or server.get("isTransitioning"):
            word, status = "Connecting", "warn"
        else:
            word, status = "Offline", "bad"
        if status == "ok" and (shares.get("faulted") or application.get("pendingRestart")):
            status = "warn"
        down = [file for file in _files(downloads) if _kind(file) == "active"]
        up = [file for file in _files(uploads) if _kind(file) == "active"]
        down_speed = sum(_number(file.get("averageSpeed")) for file in down)
        up_speed = sum(_number(file.get("averageSpeed")) for file in up)
        down_rate, up_rate = round(down_speed / 1024 / 1024, 2), round(up_speed / 1024 / 1024, 2)
        # The chips under a drawing of in and out find their numbers by these metrics.
        secondary = [
            {"label": "Download", "metric": "download", "value": down_rate, "unit": "MB/s"},
            {"label": "Upload", "metric": "upload", "value": up_rate, "unit": "MB/s"},
            {"label": "Downloading", "value": len(down)},
            {"label": "Uploading", "value": len(up)},
            {"label": "Shared files", "value": int(_number(shares.get("files")))},
            {"label": "Shared folders", "value": int(_number(shares.get("directories")))},
        ]
        if shares.get("faulted"):
            secondary.append({"label": "Share index", "value": "Faulted"})
        elif shares.get("scanning"):
            secondary.append({"label": "Share index", "value": "Scanning"})
        if version.get("isUpdateAvailable"):
            secondary.append({"label": "Update", "value": str(version.get("latest") or "available")})
        return WidgetData(
            status=status,
            primary={"label": "Soulseek", "value": word},
            secondary=secondary,
            metrics={"download": down_rate, "upload": up_rate},
            link=link,
        )

    @staticmethod
    def transfers_card(direction: str, users: Any, options: dict[str, Any], link: str | None = None) -> WidgetData:
        files = list(_files(users))
        order = {"active": 0, "queued": 1, "failed": 2, "done": 3}
        count = {kind: sum(1 for file in files if _kind(file) == kind) for kind in order}
        shown = sorted((file for file in files if _kind(file) != "done"), key=lambda file: (order[_kind(file)], -_number(file.get("percentComplete"))))
        items = []
        for file in shown[: max(1, min(50, int(options.get("limit") or 8)))]:
            kind = _kind(file)
            state = str(file.get("state") or "").strip()
            percent = _number(file.get("percentComplete"))
            parts = [str(file.get("username") or "?"), STATE_WORD.get(state.lower(), state or "Queued")]
            if kind == "active":
                if file.get("averageSpeed"):
                    parts.append(human_rate(_number(file["averageSpeed"])))
                remaining = str(file.get("remainingTime") or "")
                if remaining:
                    parts.append(f"{duration_short(_seconds(remaining))} left")
            elif file.get("size"):
                parts.append(human_bytes(_number(file["size"])))
            items.append({
                "id": str(file.get("id") or f"{file.get('username')}:{file.get('filename')}"),
                "title": _name(file),
                "subtitle": " · ".join(parts),
                "progress": round(percent, 1) if kind == "active" else None,
                "value": f"{percent:.0f}%" if kind == "active" else "",
                "status": "ok" if kind == "active" else "bad" if "errored" in state.lower() else "warn" if kind == "failed" else "unknown",
            })
        speed = sum(_number(file.get("averageSpeed")) for file in files if _kind(file) == "active")
        key = "download" if direction == "downloads" else "upload"
        return WidgetData(
            status="ok",
            items=items,
            secondary=[
                {"label": "Transferring", "value": count["active"]},
                {"label": "Queued", "value": count["queued"]},
                {"label": "Failed", "value": count["failed"]},
                {"label": "Finished", "value": count["done"]},
            ],
            metrics={key: round(speed / 1024 / 1024, 2)},
            actions=[Action(id="clear", label="Clear finished", icon="trash-2", confirm=True)] if count["done"] or count["failed"] else [],
            link=link,
            meta={"empty": "Nothing is on the move."},
        )

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A download that was nearly done and is gone from the list finished.

        ⚠️ Only nearly done: the same disappearance at ten per cent is a record
        somebody cleared, and calling it finished would be a claim about a
        file that is not there. And only when the list was read both times.
        """
        if widget_kind != "downloads" or before is None or before.error or not before.items:
            return []
        still_here = {str(item.get("id")) for item in after.items}
        gone = [item for item in before.items if str(item.get("id")) not in still_here and _number(item.get("progress")) >= NEARLY_DONE]

        return [
            Detected(event="download_done", title=f"{item.get('title') or 'A file'} finished", body="slskd has nothing left to do on it.",
                     key=f"download_done:{item.get('id')}")
            for item in gone[:5]
        ]

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "clear" or widget_kind not in DIRECTIONS:
            raise AdapterError("Unknown action.", code="no_such_action")
        await self._request(config, ctx, "DELETE", f"/transfers/{widget_kind}/all/completed")
        ctx.forget_answers()
        return "The finished transfers are cleared from the list."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        up = widget_kind == "uploads"
        names = ["Harbour Lights - 01 Departure.flac", "Harbour Lights - 02 Tide.flac", "Copper Sky - 05 Signal.mp3", "Orbital - Remote.flac"]
        users = ["alex_example", "sam_example", "kim_example", "robin_example"]
        files = []
        for index, name in enumerate(names):
            percent = (fake.walk(f"slskd-{widget_kind}-{index}", tick, 0, 100, period=240) + tick * 0.3 + index * 31) % 100
            state = "InProgress" if index < 2 else ("Queued, Remotely" if index == 2 else "Completed, TimedOut")
            files.append({"id": f"d{index}", "username": users[index], "filename": f"@@share\\Music\\{name}", "state": state, "size": (24 + index * 9) * 1024 ** 2,
                          "percentComplete": percent if index < 2 else 0, "averageSpeed": fake.walk(f"slskd-speed-{index}", tick, 0.2, 2.4) * 1024 ** 2,
                          "remainingTime": f"00:0{index + 1}:20"})
        users_list = [{"username": file["username"], "directories": [{"directory": "Music", "fileCount": 1, "files": [file]}]} for file in files]
        if widget_kind == "status":
            application = {"version": {"current": "0.26.2.0", "latest": "0.26.2.0", "isUpdateAvailable": False},
                           "server": {"state": "Connected, LoggedIn", "isConnected": True, "isLoggedIn": True},
                           "shares": {"files": 14230 + tick // 40, "directories": 1480, "faulted": False, "scanning": False}}
            return self.status_card(application, users_list, users_list[:1], None)
        return self.transfers_card("uploads" if up else "downloads", users_list, options)


def _seconds(span: str) -> float:
    """slskd writes a remaining time as ``00:03:20`` or ``1.02:03:04``."""
    days, _, clock = span.rpartition(".") if "." in span.split(":")[0] else ("0", "", span)
    try:
        hours, minutes, seconds = (float(part) for part in clock.split(":"))
        return float(days or 0) * 86400 + hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return 0.0


ADAPTER: Adapter = SlskdAdapter()
