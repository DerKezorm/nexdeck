"""PeerTube: the instance in numbers, the newest videos, the queue of jobs and what moderators have to look at.

Measured on 27.10.2026 against chocobozzz/peertube:production-bookworm
(PeerTube 7.3.0) with PostgreSQL 17 and Redis 7, one administrator, one video
uploaded and transcoded, one report filed. No federation, no registrations.

⚠️ **The public numbers need no sign-in** (``GET /api/v1/server/stats``,
``GET /api/v1/videos``, ``GET /api/v1/config``), the queue and the reports do.

⚠️ ``server/stats`` is a cached answer: a video uploaded and published was
already in ``GET /api/v1/videos`` (``total: 1``) while ``totalVideos`` and
``totalLocalVideos`` still said 0 several minutes later. A card built on it
lags behind what the instance shows; the newest-videos card reads the live list.

⚠️ **Signing in is OAuth with the instance's own client**, and it is picky
about the name it is addressed by: ``GET /api/v1/oauth-clients/local`` answers
**403 "Getting client tokens for host 127.0.0.1:9100 is forbidden"** when the
``Host`` header is not the hostname PeerTube was installed with. That is the
usual state of a connection by an internal address, so the connection has a
field for the host name PeerTube knows itself by, sent as ``Host``. Then
``POST /api/v1/users/token`` (a form: ``client_id``, ``client_secret``,
``grant_type=password``, ``response_type=code``, ``username``, ``password``)
answers ``access_token`` and ``expires_in`` (86399 seconds). A wrong password
is HTTP 400 ``invalid_grant``; a token PeerTube does not know, on a later
call, is 401 ``invalid_token``.

⚠️ Queue sizes are read as ``total`` of ``GET /api/v1/jobs/<state>?count=0``,
which returns an empty list and the number. ``delayed`` always holds the
instance's own repeating jobs (two on a quiet instance) and says nothing, so
it is not shown. ``waiting`` and ``active`` are the transcoding and the
federation work; ``failed`` stays until somebody looks.

⚠️ A report carries the video it is about, or the comment, or the account;
the card names whichever is there.
"""

from __future__ import annotations

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
    duration_short,
    human_bytes,
)


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clip(text: Any, size: int = 110) -> str:
    one = " ".join(str(text or "").split())
    return one if len(one) <= size else one[: size - 1].rstrip() + "…"


class PeertubeAdapter(Adapter):
    kind = "peertube"
    label = "PeerTube"
    category = "media"
    description = "Videos, users and views of a PeerTube instance, the newest videos, the job queue and the reports waiting for a moderator."
    icon = "peertube"
    docs_url = "https://docs.joinpeertube.org/api-rest-reference.html"
    #: Measured against PeerTube 7.3.0 in a container; no federation, no registrations, no failed job seen.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://peertube:9000"),
        Field("host", "Host name of the instance",
              help="Only when the URL uses another name than PeerTube was installed with, such as an internal address. Sent as the Host header; the sign-in needs it."),
        Field("username", "User name", help="An administrator or moderator. Without one only the public numbers and videos are shown."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="stats",
            label="Instance",
            description="Videos, views, users and storage of the instance. PeerTube keeps these numbers for a few minutes.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            metrics=("videos", "views"),
        ),
        WidgetType(
            kind="latest",
            label="Newest videos",
            description="The videos published last, with channel, length and views.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(
                Field("limit", "Entries", type="number", default=8),
                Field("local", "Only videos of this instance", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="moderation",
            label="Moderation",
            description="Open reports, accounts waiting to be let in, and videos held back for a look. Needs a moderator.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            metrics=("reports",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="jobs",
            label="Job queue",
            description="Jobs waiting, running and failed: transcoding, federation and the rest. Needs an administrator.",
            renderer="value",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("waiting", "failed"),
        ),
    )

    # -- the wire ------------------------------------------------------------

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Host": str(config["host"]).strip()} if str(config.get("host") or "").strip() else {}

    @staticmethod
    def _json(response: Any) -> Any:
        if response.status_code == 404:
            raise AdapterError("This address answers, but not the way PeerTube does.", code="not_peertube",
                               hint="Use the address of PeerTube itself, usually port 9000 behind its proxy.")
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail") or "")
            except (ValueError, AttributeError):
                detail = ""
            raise AdapterError(detail or f"PeerTube answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("PeerTube did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than PeerTube.") from error

    async def _public(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 30) -> Any:
        response = await ctx.request("GET", f"{base_url(config)}{path}", headers=self._headers(config),
                                     verify=not config.get("insecure"), cache_seconds=cache, auth_errors=False)
        return self._json(response)

    async def _token(self, config: dict[str, Any], ctx: Context, fresh: bool = False) -> str:
        if not (config.get("username") and config.get("password")):
            raise AdapterError("This card needs a user name and a password.", code="needs_login",
                               hint="Add the sign-in of an administrator or moderator of PeerTube to this connection.")
        held = ctx.cache.get("peertube_token")
        if held and not fresh and held[1] > time.time() + 60:
            return str(held[0])
        verify = not config.get("insecure")
        client = await ctx.request("GET", f"{base_url(config)}/api/v1/oauth-clients/local", headers=self._headers(config),
                                   verify=verify, auth_errors=False)
        if client.status_code == 403:
            raise AdapterError("PeerTube refuses to hand out its sign-in for this address.", code="wrong_host",
                               hint="Fill in the host name PeerTube was installed with (its public name) in the field Host name of the instance.")
        oauth = self._json(client)
        answer = await ctx.request(
            "POST", f"{base_url(config)}/api/v1/users/token", headers=self._headers(config), verify=verify, auth_errors=False,
            data={"client_id": oauth.get("client_id"), "client_secret": oauth.get("client_secret"), "grant_type": "password",
                  "response_type": "code", "username": str(config["username"]), "password": str(config["password"])},
        )
        if answer.status_code in (400, 401) and "invalid_grant" in answer.text:
            raise AuthFailed("PeerTube rejected the user name or the password.")
        body = self._json(answer)
        if not isinstance(body, dict) or not body.get("access_token"):
            raise AdapterError("PeerTube did not hand out a token.", code="no_token")
        token = str(body["access_token"])
        ctx.cache["peertube_token"] = (token, time.time() + _count(body.get("expires_in") or 3600))
        return token

    async def _private(self, config: dict[str, Any], ctx: Context, path: str) -> Any:
        for attempt in (0, 1):
            token = await self._token(config, ctx, fresh=bool(attempt))
            response = await ctx.request(
                "GET", f"{base_url(config)}{path}", headers={**self._headers(config), "Authorization": f"Bearer {token}"},
                verify=not config.get("insecure"), cache_seconds=10, auth_errors=False,
            )
            if response.status_code == 401 and not attempt:
                ctx.cache.pop("peertube_token", None)
                continue
            if response.status_code in (401, 403):
                raise AuthFailed("PeerTube does not let this account see that." if response.status_code == 403 else "PeerTube rejected the sign-in.")
            return self._json(response)
        raise AuthFailed("PeerTube rejected the sign-in.")  # pragma: no cover

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        server = await self._public(config, ctx, "/api/v1/config", cache=0)
        if not isinstance(server, dict) or "serverVersion" not in server:
            raise AdapterError("This address answers, but not the way PeerTube does.", code="not_peertube")
        version = str(server["serverVersion"])
        if config.get("username") and config.get("password"):
            await self._token(config, ctx)
            return f"PeerTube {version} answers, signed in as {config['username']}."
        return f"PeerTube {version} answers."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        link = base_url(config)
        if widget_kind == "stats":
            return self.stats_card(await self._public(config, ctx, "/api/v1/server/stats", cache=60), link)
        if widget_kind == "latest":
            limit = max(1, min(50, int(options.get("limit") or 8)))
            local = "&isLocal=true" if options.get("local", True) else ""
            answer = await self._public(config, ctx, f"/api/v1/videos?start=0&count={limit}&sort=-publishedAt{local}")
            return self.latest_card(answer, link)
        if widget_kind == "jobs":
            counts = {}
            for state in ("waiting", "active", "failed"):
                counts[state] = _count((await self._private(config, ctx, f"/api/v1/jobs/{state}?start=0&count=0")).get("total"))
            return self.jobs_card(counts, link)
        limit = max(1, min(50, int(options.get("limit") or 8)))
        abuses = await self._private(config, ctx, f"/api/v1/abuses?start=0&count={limit}&state=1&sort=-createdAt")
        registrations = await self._private(config, ctx, "/api/v1/users/registrations?start=0&count=0&state=pending")
        held = await self._private(config, ctx, "/api/v1/videos/blacklist?start=0&count=0&type=2")
        return self.moderation_card(abuses, _count(registrations.get("total")), _count(held.get("total")), options, link)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def stats_card(stats: dict[str, Any], link: str | None = None) -> WidgetData:
        videos, views = _count(stats.get("totalLocalVideos")), _count(stats.get("totalLocalVideoViews"))
        secondary = [
            {"label": "Views", "value": views},
            {"label": "Users", "value": _count(stats.get("totalUsers"))},
            {"label": "Active this month", "value": _count(stats.get("totalMonthlyActiveUsers"))},
            {"label": "Storage", "value": human_bytes(_count(stats.get("totalLocalVideoFilesSize")))},
            {"label": "Followers", "value": _count(stats.get("totalInstanceFollowers"))},
        ]
        return WidgetData(primary={"label": "Videos", "value": videos}, secondary=secondary,
                          metrics={"videos": float(videos), "views": float(views)}, link=link)

    @staticmethod
    def latest_card(answer: dict[str, Any], link: str | None = None) -> WidgetData:
        items = []
        for video in answer.get("data") or []:
            if not isinstance(video, dict):
                continue
            channel = video.get("channel") if isinstance(video.get("channel"), dict) else {}
            seconds = _count(video.get("duration"))
            items.append({
                "id": str(video.get("uuid") or video.get("id") or ""),
                "title": str(video.get("name") or "?"),
                "subtitle": " · ".join(piece for piece in (str(channel.get("displayName") or ""), duration_short(seconds) if seconds else "",
                                                             ago(video.get("publishedAt"))) if piece),
                "value": f"{_count(video.get('views'))} views",
                "status": "ok",
            })
        return WidgetData(items=items, secondary=[{"label": "Videos", "value": _count(answer.get("total"))}], link=link,
                          meta={"empty": "No video is published."})

    @staticmethod
    def jobs_card(counts: dict[str, int], link: str | None = None) -> WidgetData:
        waiting, active, failed = counts.get("waiting", 0), counts.get("active", 0), counts.get("failed", 0)
        return WidgetData(
            status="warn" if failed else "ok",
            primary={"label": "Waiting", "value": waiting},
            secondary=[{"label": "Running", "value": active}, {"label": "Failed", "value": failed}],
            metrics={"waiting": float(waiting), "failed": float(failed)},
            link=link,
        )

    @staticmethod
    def moderation_card(abuses: dict[str, Any], registrations: int, held: int, options: dict[str, Any], link: str | None = None) -> WidgetData:
        items = []
        for abuse in abuses.get("data") or []:
            if not isinstance(abuse, dict):
                continue
            video, comment, account = abuse.get("video") or {}, abuse.get("comment") or {}, abuse.get("flaggedAccount") or {}
            if video:
                about = f"Video: {video.get('name') or '?'}"
            elif comment:
                about = f"Comment: {_clip(comment.get('text'), 60)}"
            else:
                about = f"Account: {account.get('displayName') or account.get('name') or '?'}"
            items.append({
                "id": str(abuse.get("id") or ""),
                "title": about,
                "subtitle": _clip(abuse.get("reason")),
                "value": ago(abuse.get("createdAt")),
                "status": "warn",
            })
        reports = _count(abuses.get("total"))
        secondary = [{"label": "Reports", "value": reports}, {"label": "Accounts waiting", "value": registrations},
                     {"label": "Videos held back", "value": held}]
        return WidgetData(
            status="warn" if reports or registrations or held else "ok",
            items=items,
            secondary=secondary,
            metrics={"reports": float(reports)},
            link=link,
            meta={"empty": "Nothing waits for a moderator."},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        views = fake.counter("peertube-views", tick, 48210, 0.4)
        if widget_kind == "stats":
            return self.stats_card({"totalLocalVideos": 214, "totalLocalVideoViews": views, "totalUsers": 38, "totalMonthlyActiveUsers": 21,
                                    "totalLocalVideoFilesSize": 412 * 1024 ** 3, "totalInstanceFollowers": 57})
        if widget_kind == "latest":
            now = time.time()
            videos = [
                {"uuid": f"v{index}", "name": name, "duration": length, "views": fake.counter(f"peertube-v{index}", tick, 20 * (4 - index), 0.01),
                 "publishedAt": now - 3600 * (index * 7 + 2), "channel": {"displayName": channel}}
                for index, (name, length, channel) in enumerate([("Harbour Lights: the tide", 1260, "Main channel"), ("Signal Lost, part 2", 2935, "Orbital Tide"),
                                                                 ("Copper Sky in the rain", 312, "Main channel"), ("Quiet Harbour, live", 5400, "Streams")])
            ]
            return self.latest_card({"total": 214, "data": videos})
        if widget_kind == "jobs":
            busy = fake.flicker("peertube-busy", tick, 0.4)
            return self.jobs_card({"waiting": 6 if busy else 0, "active": 2 if busy else 0, "failed": 1 if fake.flicker("peertube-failed", tick // 30, 0.3) else 0})
        now = time.time()
        abuses = {"total": 2, "data": [
            {"id": 7, "reason": "Spam in the description, links to a shop", "createdAt": now - 5400, "video": {"name": "Signal Lost, part 2"}},
            {"id": 6, "reason": "Rude remark about another user", "createdAt": now - 86400, "comment": {"text": "That was a waste of everybody's time"}},
        ]}
        return self.moderation_card(abuses, 1, 0, options)


ADAPTER: Adapter = PeertubeAdapter()
