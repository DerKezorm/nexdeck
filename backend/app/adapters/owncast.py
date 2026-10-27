"""Owncast: whether the stream is live, who is watching, and the way to stop it.

Measured on 27.10.2026 against owncast/owncast v0.3.0, offline and with a
test picture pushed over RTMP (ffmpeg, 640x360, H.264 and AAC), with the
default administrator and with a wrong one.

⚠️ The public ``GET /api/status`` is small: ``online``, ``streamTitle``,
``versionNumber``, ``lastConnectTime`` and ``lastDisconnectTime``, and
``serverTime`` to read them against. **There is no viewer count in it any
more**; it moved to the administrator's ``GET /api/admin/status``, which also
carries the peaks, the picture the broadcaster sends and the stream's health.

⚠️ The administrator signs in with **basic authentication, the user ``admin``
and the stream key as the password** (a new Owncast starts with ``abc123``,
which is why a wrong one must be refused and not just noticed). A wrong
password and no password answer 401 ``Unauthorized``.

⚠️ ``lastConnectTime`` is ``null`` while the stream is offline, and
``lastDisconnectTime`` is ``null`` while it is live; the other one keeps the
time of the last session. How long a stream has been live is read against
the server's own ``serverTime`` and not this machine's clock.

⚠️ ``health`` is ``null`` when Owncast has nothing to say; a value is an
object whose ``healthy`` flag is false when the stream stutters, with a
``message``. That shape is from Owncast's source and was not seen here.

⚠️ ``POST /api/admin/disconnect`` answers 200 ``{"success": true, "message":
"inbound stream disconnected"}``, and the broadcaster (ffmpeg) exited at
once. The stream key is unchanged, so the same program can start again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
    duration_short,
)


def _moment(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


class OwncastAdapter(Adapter):
    kind = "owncast"
    label = "Owncast"
    category = "media"
    description = "Whether the stream is live, how long, how many watch, and the way to disconnect the broadcaster."
    icon = "owncast"
    docs_url = "https://owncast.online/docs/api/"
    #: Measured against Owncast v0.3.0 in a container, live over RTMP for a minute; no real viewers.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://owncast:8080"),
        Field("stream_key", "Admin password (stream key)", type="password", secret=True,
              help="The stream key is the password of the user admin. Without it only the public status is shown."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="stream",
            label="Stream",
            description="Live or offline, how long it has been live, the viewers, the picture it sends and how healthy it is.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("viewers",),
        ),
        WidgetType(
            kind="viewers",
            label="Viewers",
            description="The number of people watching now, with the peak of this session and of all time. Needs the stream key.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=30,
            metrics=("viewers",),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, admin: bool = False) -> Any:
        auth = ("admin", str(config.get("stream_key"))) if admin else None
        response = await ctx.request("GET", f"{base_url(config)}{path}", auth=auth, verify=not config.get("insecure"),
                                     cache_seconds=10, auth_errors=False)
        if response.status_code in (401, 403):
            raise AuthFailed("Owncast rejected the stream key." if admin else "Owncast asks for a sign-in the public status does not need.")
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way Owncast does.", code="not_owncast",
                               hint="Use the address of Owncast itself, usually port 8080.")
        if response.status_code >= 400:
            raise AdapterError(f"Owncast answered with HTTP {response.status_code}.", code="http_error")
        try:
            answer = response.json()
        except ValueError as error:
            raise AdapterError("Owncast did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than Owncast.") from error
        if not isinstance(answer, dict) or "online" not in answer:
            raise AdapterError("This address answers, but not the way Owncast does.", code="not_owncast")
        return answer

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/api/status")
        if config.get("stream_key"):
            await self._get(config, ctx, "/api/admin/status", admin=True)
        version = str(status.get("versionNumber") or "")
        state = "live" if status.get("online") else "offline"
        return f"Owncast {version} answers, the stream is {state}." if version else f"Owncast answers, the stream is {state}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        has_key = bool(config.get("stream_key"))
        if widget_kind == "viewers":
            if not has_key:
                raise AdapterError("The viewer count needs the stream key.", code="needs_stream_key",
                                   hint="Add the stream key of Owncast, the password of the user admin, to this connection.")
            return self.viewers_card(await self._get(config, ctx, "/api/admin/status", admin=True), base_url(config))
        public = await self._get(config, ctx, "/api/status")
        admin = await self._get(config, ctx, "/api/admin/status", admin=True) if has_key else None
        followers = None
        if has_key:
            try:
                followers = (await self._get_any(config, ctx, "/api/admin/followers?limit=1")).get("total")
            except AdapterError:
                followers = None
        return self.stream_card(public, admin, followers, base_url(config))

    async def _get_any(self, config: dict[str, Any], ctx: Context, path: str) -> dict[str, Any]:
        """An administrator's address whose answer does not carry ``online``."""
        response = await ctx.request("GET", f"{base_url(config)}{path}", auth=("admin", str(config.get("stream_key"))),
                                     verify=not config.get("insecure"), cache_seconds=60, auth_errors=False)
        if response.status_code >= 400:
            raise AdapterError(f"Owncast answered with HTTP {response.status_code}.", code="http_error")
        answer = response.json()
        return answer if isinstance(answer, dict) else {}

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def stream_card(public: dict[str, Any], admin: dict[str, Any] | None, followers: Any = None, link: str | None = None) -> WidgetData:
        online = bool(public.get("online"))
        secondary: list[dict[str, Any]] = []
        metrics: dict[str, float] = {}
        status = "ok" if online else "unknown"
        title = str(public.get("streamTitle") or "").strip()
        if online:
            started, now = _moment(public.get("lastConnectTime")), _moment(public.get("serverTime"))
            if started and now and now >= started:
                secondary.append({"label": "Live for", "value": duration_short((now - started).total_seconds())})
        else:
            ended = _moment(public.get("lastDisconnectTime"))
            now = _moment(public.get("serverTime"))
            if ended and now and now >= ended:
                secondary.append({"label": "Offline for", "value": duration_short((now - ended).total_seconds())})
        if title:
            secondary.insert(0, {"label": "Title", "value": title})
        if admin is not None:
            viewers = _count(admin.get("viewerCount")) if online else 0
            metrics["viewers"] = float(viewers)
            secondary.append({"label": "Viewers", "value": viewers})
            details = ((admin.get("broadcaster") or {}).get("streamDetails") or {}) if online else {}
            if details.get("width") and details.get("height"):
                picture = f"{details['width']}x{details['height']}"
                if details.get("framerate"):
                    picture += f" at {int(details['framerate'])} fps"
                secondary.append({"label": "Picture", "value": picture})
            if details.get("videoBitrate"):
                secondary.append({"label": "Bitrate", "value": f"{int(details['videoBitrate'])} kbit/s"})
            health = admin.get("health")
            if online and isinstance(health, dict) and health.get("healthy") is False:
                status = "warn"
                secondary.append({"label": "Health", "value": str(health.get("message") or "Unhealthy")})
            if followers is not None:
                secondary.append({"label": "Followers", "value": _count(followers)})
        return WidgetData(
            status=status,
            primary={"label": "Stream", "value": "Live" if online else "Offline"},
            secondary=secondary,
            metrics=metrics,
            actions=[Action(id="disconnect", label="Disconnect the broadcaster", icon="power", confirm=True, danger=True)] if online and admin is not None else [],
            link=link,
        )

    @staticmethod
    def viewers_card(admin: dict[str, Any], link: str | None = None) -> WidgetData:
        online = bool(admin.get("online"))
        viewers = _count(admin.get("viewerCount")) if online else 0
        return WidgetData(
            status="ok" if online else "unknown",
            primary={"label": "Viewers", "value": viewers},
            secondary=[
                {"label": "Peak this session", "value": _count(admin.get("sessionPeakViewerCount"))},
                {"label": "Peak ever", "value": _count(admin.get("overallPeakViewerCount"))},
            ],
            metrics={"viewers": float(viewers)},
            link=link,
        )

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any],
                     options: dict[str, Any], ctx: Context) -> str:
        if action_id != "disconnect":
            raise AdapterError("Unknown action.", code="no_such_action")
        if not config.get("stream_key"):
            raise AuthFailed("Disconnecting needs the stream key.")
        response = await ctx.request("POST", f"{base_url(config)}/api/admin/disconnect", auth=("admin", str(config["stream_key"])),
                                     verify=not config.get("insecure"), auth_errors=False)
        ctx.forget_answers()
        if response.status_code in (401, 403):
            raise AuthFailed("Owncast rejected the stream key.")
        if response.status_code >= 400:
            raise AdapterError(f"Owncast answered with HTTP {response.status_code}.", code="http_error")
        return "The broadcaster is disconnected."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        live = not fake.flicker("owncast-offline", tick // 20, 0.3)
        viewers = round(fake.walk("owncast-viewers", tick, 3, 41)) if live else 0
        now = datetime.now(UTC)
        public = {"online": live, "streamTitle": "Friday night build", "serverTime": now.isoformat(),
                  "lastConnectTime": datetime.fromtimestamp(now.timestamp() - 1500 - tick, UTC).isoformat() if live else None,
                  "lastDisconnectTime": None if live else now.isoformat()}
        admin = {"online": live, "viewerCount": viewers, "sessionPeakViewerCount": 44, "overallPeakViewerCount": 112, "health": None,
                 "broadcaster": {"streamDetails": {"width": 1920, "height": 1080, "framerate": 30, "videoBitrate": 4300}}}
        if widget_kind == "viewers":
            return self.viewers_card(admin)
        return self.stream_card(public, admin, 281)


ADAPTER: Adapter = OwncastAdapter()
