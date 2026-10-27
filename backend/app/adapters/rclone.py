"""rclone through its remote control (``rclone rcd``).

Measured on 27.10.2026 against rclone/rclone v1.75.2 started as ``rclone rcd``
with a user and a password: a copy of two files at a limit of 4 MiB/s, a copy
from a folder that is not there, the limit switched off, the counters reset,
a wrong password.

⚠️ **Everything is POST, and an empty body is an error**: ``POST /core/stats``
without a body answers **HTTP 400** ``failed to read input JSON: EOF``. The
body is ``{}`` for a call with nothing to say. Errors come as ``{"error",
"input", "path", "status"}`` with the status also as the HTTP code (400 for a
bad request, 500 for a failure such as ``job not found`` or ``bad bwlimit:
bad suffix 'c'``).

⚠️ A wrong password, and no password, answer **401** with the plain text
``401 Unauthorized``.

⚠️ ``core/stats`` counts since the start or since ``core/stats-reset``, and
**its ``speed`` does not fall to zero when the work is over**: after the copy
ended it still said 4198953 bytes per second, the average of the transfer,
beside ``"eta": 0``. The list ``transferring`` is there only while a file
moves, and that is what says whether something runs. ``eta`` is ``null``
after a reset. ``lastError`` appears with ``errors``; a copy from a folder
that does not exist counted one error, ``"lastError": "directory not found"``
and ``retryError: true``, and still answered 200 to the call that started it.

⚠️ **Every rc call is itself a job**: ``job/list`` named the running copy and
the very call asking, and the finished calls before it. It says nothing about
the work, so the cards read ``core/stats`` and ``core/transferred``.

⚠️ ``core/transferred`` lists what was done since the reset, each with
``name``, ``size``, ``bytes``, ``error`` (empty when it went well),
``completed_at``, ``group`` and the two file systems. ``core/bwlimit`` answers
``rate`` as rclone writes it (``4Mi``), ``bytesPerSecond`` (-1 for none) and
accepts ``{"rate": "off"}``.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Ask,
    AuthFailed,
    Choice,
    Context,
    Field,
    WidgetData,
    WidgetType,
    ago,
    as_gauge,
    base_url,
    duration_short,
    gauge_fields,
    human_bytes,
    human_rate,
)

#: What the button that sets the limit offers; rclone takes anything it can parse, the card only offers these.
LIMITS = (("off", "No limit"), ("1M", "1 MiB/s"), ("5M", "5 MiB/s"), ("10M", "10 MiB/s"), ("50M", "50 MiB/s"))


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _name(path: Any) -> str:
    return str(path or "?").replace("\\", "/").rsplit("/", 1)[-1] or str(path)


class RcloneAdapter(Adapter):
    kind = "rclone"
    label = "rclone"
    category = "downloads"
    description = "What rclone moves right now, the files it moved, errors, the bandwidth limit and a way to change it."
    icon = "rclone"
    docs_url = "https://rclone.org/rc/"
    #: Measured against rclone v1.75.2 in a container, with local folders as the two ends; no cloud remote was involved.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://rclone:5572",
              help="The address of rclone rcd, port 5572 unless you set --rc-addr."),
        Field("username", "User name", help="The --rc-user of rclone. Leave empty when it runs with --rc-no-auth."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="speed",
            label="Transfer speed",
            description="How fast rclone moves data now, how much is done, the time left and errors, with the bandwidth limit as the full dial.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=10,
            metrics=("speed",),
            options=gauge_fields("Used when rclone has no bandwidth limit, in MB/s.", "12.5"),
        ),
        WidgetType(
            kind="transfers",
            label="Transfers",
            description="The files moving now with progress, then the latest finished ones, failed ones in red with the reason.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=10,
            metrics=("speed", "errors"),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="overview",
            label="rclone overview",
            description="The bandwidth limit, the remotes that are set up and the version, with a button for the limit.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
        ),
    )

    # -- the wire ------------------------------------------------------------

    async def _call(self, config: dict[str, Any], ctx: Context, path: str, body: dict[str, Any] | None = None) -> Any:
        auth = (str(config["username"]), str(config.get("password") or "")) if config.get("username") else None
        response = await ctx.request("POST", f"{base_url(config)}/{path}", json_body=body or {}, auth=auth,
                                     verify=not config.get("insecure"), auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("rclone rejected the user name or the password." if auth else "rclone wants a user name and a password.")
        try:
            answer = response.json()
        except ValueError as error:
            if response.status_code == 404:
                raise AdapterError("This address answers, but not the way rclone does.", code="not_rclone",
                                   hint="Use the address of rclone rcd, usually port 5572.") from error
            raise AdapterError("rclone did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than rclone.") from error
        if response.status_code >= 400:
            message = str(answer.get("error") or "") if isinstance(answer, dict) else ""
            raise AdapterError(f"rclone refused {path}: {message}" if message else f"rclone answered with HTTP {response.status_code}.",
                               code="rclone_error" if message else "http_error")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        answer = await self._call(config, ctx, "core/version")
        if not isinstance(answer, dict) or "version" not in answer:
            raise AdapterError("This address answers, but not the way rclone does.", code="not_rclone")
        return f"rclone {str(answer['version']).lstrip('v')} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "overview":
            limit = await self._call(config, ctx, "core/bwlimit")
            remotes = await self._call(config, ctx, "config/listremotes")
            version = await self._call(config, ctx, "core/version")
            return self.overview_card(limit, remotes, version, link)
        stats = await self._call(config, ctx, "core/stats")
        if widget_kind == "transfers":
            done = await self._call(config, ctx, "core/transferred")
            return self.transfers_card(stats, done, options, link)
        limit = await self._call(config, ctx, "core/bwlimit")
        return self.speed_card(stats, limit, options, link)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _running(stats: dict[str, Any]) -> list[dict[str, Any]]:
        return [one for one in stats.get("transferring") or [] if isinstance(one, dict)]

    @classmethod
    def speed_card(cls, stats: dict[str, Any], limit: dict[str, Any], options: dict[str, Any], link: str | None = None) -> WidgetData:
        running = cls._running(stats)
        # ⚠️ The speed stays at the average of the last run once the work is over; only a file in flight makes it current.
        speed = _number(stats.get("speed")) if running else 0.0
        errors = int(_number(stats.get("errors")))
        total, done = _number(stats.get("totalBytes")), _number(stats.get("bytes"))
        secondary: list[dict[str, Any]] = [{"label": "Transferred", "value": f"{human_bytes(done)} of {human_bytes(total)}" if total else human_bytes(done)}]
        if running and stats.get("eta") is not None:
            secondary.append({"label": "Left", "value": duration_short(_number(stats["eta"]))})
        secondary.append({"label": "Files", "value": f"{int(_number(stats.get('transfers')))} of {int(_number(stats.get('totalTransfers')))}"})
        if errors:
            secondary.append({"label": "Errors", "value": errors})
        status = "bad" if stats.get("fatalError") or errors else "warn" if stats.get("retryError") else "ok"
        card = WidgetData(
            status=status,
            primary={"label": "Speed" if running else "Idle", "value": round(speed / 1024 / 1024, 1), "unit": "MB/s"},
            secondary=secondary,
            metrics={"speed": round(speed / 1024 / 1024, 2)},
            actions=[Action(id="reset", label="Reset the counters", icon="rotate-cw", confirm=True)] if done or errors else [],
            link=link,
        )
        ceiling = _number(limit.get("bytesPerSecond"))
        return as_gauge(card, options, maximum=ceiling / 1024 / 1024 if ceiling > 0 else None)

    @classmethod
    def transfers_card(cls, stats: dict[str, Any], done: dict[str, Any], options: dict[str, Any], link: str | None = None) -> WidgetData:
        items = []
        for one in cls._running(stats):
            parts = [human_rate(_number(one.get("speed"))), f"{duration_short(_number(one['eta']))} left" if one.get("eta") is not None else ""]
            items.append({
                "id": f"{one.get('group')}:{one.get('name')}",
                "title": _name(one.get("name")),
                "subtitle": " · ".join(piece for piece in (human_bytes(_number(one.get("size"))), *parts) if piece),
                "progress": float(_number(one.get("percentage"))),
                "value": f"{int(_number(one.get('percentage')))}%",
                "status": "ok",
            })
        finished = [one for one in (done or {}).get("transferred") or [] if isinstance(one, dict)]
        for one in sorted(finished, key=lambda one: str(one.get("completed_at") or ""), reverse=True):
            failed = bool(one.get("error"))
            items.append({
                "id": f"{one.get('group')}:{one.get('name')}:{one.get('completed_at')}",
                "title": _name(one.get("name")),
                "subtitle": str(one["error"]).strip().splitlines()[0][:160] if failed else
                " · ".join(piece for piece in (human_bytes(_number(one.get("size"))), ago(one.get("completed_at"))) if piece),
                "value": "Failed" if failed else "Done",
                "status": "bad" if failed else "ok",
            })
        errors = int(_number(stats.get("errors")))
        speed = _number(stats.get("speed")) if cls._running(stats) else 0.0
        secondary = [{"label": "Moving", "value": len(cls._running(stats))}, {"label": "Errors", "value": errors}]
        if stats.get("lastError"):
            secondary.append({"label": "Last error", "value": str(stats["lastError"])[:80]})
        return WidgetData(
            status="bad" if stats.get("fatalError") or errors else "ok",
            items=items[: max(1, min(50, int(options.get("limit") or 8)))],
            secondary=secondary,
            metrics={"speed": round(speed / 1024 / 1024, 2), "errors": float(errors)},
            link=link,
            meta={"empty": "Nothing has been moved."},
        )

    @staticmethod
    def overview_card(limit: dict[str, Any], remotes: dict[str, Any], version: dict[str, Any], link: str | None = None) -> WidgetData:
        ceiling = _number(limit.get("bytesPerSecond"))
        names = [str(one) for one in (remotes or {}).get("remotes") or []]
        return WidgetData(
            primary={"label": "Bandwidth limit", "value": human_rate(ceiling) if ceiling > 0 else "No limit"},
            secondary=[{"label": "Remotes", "value": len(names)}, {"label": "Version", "value": str((version or {}).get("version") or "?").lstrip("v")}],
            actions=[Action(id="limit", label="Set the limit", icon="gauge",
                            asks=[Ask(name="rate", label="Limit", kind="choice", options=[Choice(value=value, label=label) for value, label in LIMITS])])],
            link=link,
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id == "reset":
            await self._call(config, ctx, "core/stats-reset")
            ctx.forget_answers()
            return "The counters are reset."
        if action_id == "limit":
            rate = str(params.get("rate") or "")
            if rate not in {value for value, _label in LIMITS}:
                raise AdapterError("That is not one of the limits offered.", code="bad_value")
            await self._call(config, ctx, "core/bwlimit", {"rate": rate})
            ctx.forget_answers()
            return f"The limit is {rate}."

        raise AdapterError("Unknown action.", code="no_such_action")

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "overview":
            return self.overview_card({"bytesPerSecond": 10 * 1024 * 1024}, {"remotes": ["backup-crypt", "cloud-drive", "offsite"]}, {"version": "v1.75.2"})
        busy = not fake.flicker("rclone-idle", tick // 20, 0.3)
        speed = fake.walk("rclone-speed", tick, 2, 9.5) * 1024 * 1024
        running = [
            {"group": "job/4", "name": "photos/2026/IMG_4021.raw", "size": 52428800, "percentage": int(fake.walk("rclone-p1", tick, 5, 95)), "speed": speed * 0.7, "eta": 20},
            {"group": "job/4", "name": "photos/2026/IMG_4022.raw", "size": 48234496, "percentage": int(fake.walk("rclone-p2", tick, 1, 60)), "speed": speed * 0.3, "eta": 55},
        ] if busy else []
        stats = {"speed": speed if busy else 4198953.0, "bytes": 8 * 1024 ** 3 + tick * 1024 ** 2, "totalBytes": 12 * 1024 ** 3, "eta": 440 if busy else None,
                 "transfers": 310, "totalTransfers": 402, "errors": 1 if fake.flicker("rclone-error", tick // 40, 0.25) else 0, "lastError": "directory not found",
                 "transferring": running}
        if widget_kind == "speed":
            return self.speed_card(stats, {"bytesPerSecond": 10 * 1024 * 1024}, options)
        done = {"transferred": [
            {"name": "photos/2026/IMG_4019.raw", "size": 49283072, "error": "", "completed_at": "2026-10-27T12:00:00Z", "group": "job/4"},
            {"name": "photos/2026/IMG_4020.raw", "size": 51380224, "error": "", "completed_at": "2026-10-27T11:58:00Z", "group": "job/4"},
            {"name": "documents/scan.pdf", "size": 1048576, "error": "failed to open source object: permission denied", "completed_at": "2026-10-27T11:50:00Z", "group": "job/3"},
        ]}
        return self.transfers_card(stats, done, options)


ADAPTER: Adapter = RcloneAdapter()
