"""Frigate: the cameras, what they detected and how the machine copes.

nexdeck has the deeper camera path with Reolink, but Frigate is the standard
answer to video surveillance in a homelab. The pictures of a detection come
through the server like every other service image, so no address of a camera
ever reaches the browser.

Frigate answers on two ports, and which one the address names decides whether
an account is needed: 5000 is the internal API without a sign-in, 8971 the
authenticated one, and that is the port a reverse proxy in front of Frigate
uses. The sign-in is ``POST /api/login`` with a user and a password; the
answer carries the JWT in a cookie, and Frigate takes that token in an
``Authorization: Bearer`` header as well. Up to and including 0.13.0 this
adapter had no field for either, so a card on the authenticated port said
"the service rejected the credentials" and offered nowhere to put any.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    AuthFailed,
    Context,
    Field,
    MediaSource,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    measured,
    path_segment,
    percent,
    percent_text,
    status_from_percent,
)

#: What Frigate calls its JWT cookie unless the installation renamed it
#: (``auth.cookie_name``).
JWT_COOKIE = "frigate_token"
#: How long a token is used before signing in again. A Frigate session lasts a
#: day by default, and an installation may set it shorter; an hour is well
#: inside both, and a token the server refuses is replaced at once anyway.
TOKEN_SECONDS = 3600
#: How long a refused sign-in is remembered.
#:
#: ⚠️ Frigate rate-limits failed sign-ins, by default once a second and five
#: times a minute, counted per address. A board with three Frigate cards and a
#: wrong password would spend that budget on its first refresh and lock the
#: operator out of Frigate's own login page with it.
REFUSAL_SECONDS = 60
#: A detector slower than this per picture falls behind a camera at 10 fps.
SLOW_DETECTOR_MS = 100
#: Frames a second a camera may drop for want of detection before it is a finding.
SKIPPED_FPS = 1.0
#: The cameras of the demo cards.
DEMO_CAMERAS = ("driveway", "front_door", "garden", "garage")


class FrigateAdapter(Adapter):
    kind = "frigate"
    label = "Frigate"
    category = "monitoring"
    description = "Cameras with their frame rates, the latest detections and the load they cause."
    icon = "frigate"
    docs_url = "https://docs.frigate.video/integrations/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://frigate:5000",
              help="Port 5000 is Frigate's internal API and needs no account; port 8971 is the authenticated one, and so is a reverse proxy in front of it."),
        Field("username", "User", help="A user from Frigate's Settings > Users. Leave it empty on port 5000, where nothing signs in. A viewer is enough; the cards only read."),
        Field("password", "Password", type="password", secret=True),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="cameras",
            label="Cameras",
            description="One line per camera with its frame rates.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=30,
            metrics=("cameras",),
        ),
        WidgetType(
            kind="events",
            label="Detections",
            description="What was seen last, with its picture, camera and time.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="camera",
            label="Camera",
            description="One camera large: its latest picture, fetched again every few seconds.",
            renderer="camera",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=60,
            options=(
                Field("camera", "Camera", type="choices", required=True),
                Field("interval", "Picture every (seconds)", type="number", default=10),
            ),
        ),
        WidgetType(
            kind="today",
            label="Today",
            description="What was detected since midnight, counted by kind.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("detections_today",),
            options=(Field("camera", "Camera", type="choices", help="Empty for every camera."),),
        ),
        WidgetType(
            kind="health",
            label="Health",
            description="Quiet while everything runs: a camera without frames, dropped frames, a slow detector, storage running out.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=60,
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="Cameras, detection load and what the recordings occupy.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("cameras", "storage_percent"),
        ),
    )

    # -- signing in ----------------------------------------------------------

    @staticmethod
    def _signs_in(config: dict[str, Any]) -> bool:
        return bool(str(config.get("username") or "").strip())

    @staticmethod
    def _token_in(response: httpx.Response) -> str:
        """The JWT out of the sign-in's answer.

        ⚠️ Only the cookie carries it: a sign-in Frigate accepts answers 200
        with an empty body. The cookie's name is a Frigate setting, so the
        usual name is read first and then any cookie whose value is shaped
        like a JWT.
        """
        for answer in (*response.history, response):
            token = answer.cookies.get(JWT_COOKIE)
            if token:
                return str(token)
        for answer in (*response.history, response):
            for raw in answer.headers.get_list("set-cookie"):
                value = raw.split(";", 1)[0].partition("=")[2].strip()
                pieces = value.split(".")
                if len(pieces) == 3 and pieces[0] and pieces[1]:
                    return value
        return ""

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        """The bearer token, or an empty string where nothing signs in.

        Empty means one of two things, and both go on to ask without a token:
        no user is configured, or Frigate answered the sign-in with
        "authentication is disabled", which is what the internal port and an
        installation that leaves the sign-in to its proxy both do.

        ⚠️ One sign-in at a time per connection. Every card of a connection
        refreshes within the same second, and each finding no token and
        signing in on its own is what the rate limit above is there to stop.
        """
        if not self._signs_in(config):
            return ""
        kept = ctx.cache.get("frigate_jwt")
        if kept and not force and kept[0] > time.monotonic():
            return str(kept[1])
        lock = ctx.cache.setdefault("frigate_login_lock", asyncio.Lock())
        async with lock:
            kept = ctx.cache.get("frigate_jwt")
            if kept and not force and kept[0] > time.monotonic():
                return str(kept[1])
            refused = ctx.cache.get("frigate_login_refused")
            if refused and refused[0] > time.monotonic():
                raise AuthFailed(str(refused[1]))
            response = await ctx.request(
                "POST",
                f"{base_url(config)}/api/login",
                json_body={"user": str(config.get("username") or "").strip(), "password": str(config.get("password") or "")},
                verify=not config.get("insecure"),
                auth_errors=False,
            )
            if response.status_code in (401, 403):
                message = "Frigate turned the user or the password down."
                ctx.cache["frigate_login_refused"] = (time.monotonic() + REFUSAL_SECONDS, message)
                raise AuthFailed(message)
            if response.status_code == 404:
                # Frigate's own answer when authentication is switched off. The
                # cards ask without a token from here on; if something in front
                # of Frigate then refuses them, ``_refusal`` says so instead of
                # blaming the password.
                ctx.cache["frigate_signin"] = "off"
                ctx.cache["frigate_jwt"] = (time.monotonic() + TOKEN_SECONDS, "")
                return ""
            if response.status_code >= 400:
                raise AdapterError(f"Frigate answered the sign-in with HTTP {response.status_code}.", code="http_error",
                                   hint="Check the URL; it is the address of Frigate itself, without /api.")
            token = self._token_in(response)
            if not token:
                raise AdapterError("Frigate accepted the sign-in but handed out no token.", code="not_frigate",
                                   hint="Check the URL; something in front of Frigate may be answering the sign-in.")
            ctx.cache["frigate_signin"] = "on"
            ctx.cache["frigate_jwt"] = (time.monotonic() + TOKEN_SECONDS, token)
            return token

    def _refusal(self, config: dict[str, Any], ctx: Context) -> str:
        """Why a card was turned down, in the words of the case it is in."""
        if not self._signs_in(config):
            return ("Frigate wants an account for this address. Port 8971 is the authenticated API and needs a user and a password; "
                    "port 5000 is the internal one and needs none.")
        if ctx.cache.get("frigate_signin") == "off":
            return ("Frigate's own authentication is switched off, so the user and the password have nowhere to go, "
                    "and whatever stands in front of Frigate turned the card down.")
        return "Frigate turned the account down for this address."

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 15, retry: bool = True) -> Any:
        token = await self._token(config, ctx)
        response = await ctx.request(
            "GET",
            f"{base_url(config)}/api{path}",
            headers={"Authorization": f"Bearer {token}"} if token else None,
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
            auth_errors=False,
        )
        if response.status_code in (401, 403) and retry and self._signs_in(config):
            # A token signed with an older secret is turned down like a
            # made-up one, and Frigate makes a new secret whenever it cannot
            # keep the old one. Sign in once more before giving up.
            ctx.forget_answers()
            await self._token(config, ctx, force=True)
            return await self._get(config, ctx, path, params, cache=0, retry=False)
        if response.status_code in (401, 403):
            raise AuthFailed(self._refusal(config, ctx))
        if response.status_code >= 400:
            raise AdapterError(f"Frigate answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of Frigate itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("Frigate did not answer with data.", code="not_json",
                               hint="The URL probably points at a login page or at something else than Frigate.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        """What answered, and whether the account was used to get there.

        ⚠️ The count comes from ``_cameras``, the same reading the cards use.
        Its own shorter list of names to skip counted ``detection_fps``, a
        number, as a camera, so the test promised one camera more than the
        cards then showed.
        """
        stats = await self._get(config, ctx, "/stats", cache=0)
        cameras = self._cameras(stats)
        answer = f"Frigate answers with {len(cameras)} cameras."
        if not self._signs_in(config):
            return answer
        if ctx.cache.get("frigate_signin") == "off":
            return f"{answer} Its own authentication is switched off, so the user and the password are not used."
        return f"{answer} Signed in as {str(config.get('username') or '').strip()}."

    @staticmethod
    def _cameras(stats: dict[str, Any]) -> dict[str, Any]:
        """The cameras in ``/api/stats``, in either of its two layouts.

        ⚠️ Newer Frigate keeps them under ``cameras``; older versions put each
        camera beside ``detectors`` and ``service`` at the top. Only the old
        layout was read, so on a current Frigate the card listed "cameras" and
        "embeddings", two keys of the answer, as two cameras at 0 fps, and the
        real one was missing. Issue #1, from a screenshot on 18.09.2026.
        """
        stats = stats or {}
        nested = stats.get("cameras")
        if isinstance(nested, dict):
            return {name: values for name, values in nested.items() if isinstance(values, dict)}
        skip = {"detectors", "service", "cpu_usages", "gpu_usages", "processes", "detection_fps", "bandwidth", "embeddings"}
        return {name: values for name, values in stats.items() if name not in skip and isinstance(values, dict)}

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "events":
            limit = int(options.get("limit") or 8)
            # Without include_thumbnails=0 older versions put every thumbnail
            # into the list as base64; the card fetches them one by one
            # through the server instead.
            events = await self._get(config, ctx, "/events", params={"limit": limit, "include_thumbnails": 0}, cache=15)
            items = []
            for event in events if isinstance(events, list) else []:
                when = event.get("start_time")
                moment = datetime.fromtimestamp(float(when), UTC).strftime("%H:%M") if when else ""
                items.append({
                    "title": str(event.get("label") or "?").capitalize(),
                    "subtitle": f"{event.get('camera', '?')} · {moment}",
                    "value": self._score(event),
                    "status": "warn" if event.get("has_clip") else "ok",
                    "art": self._thumbnail(event),
                    "art_shape": "square",
                })
            return WidgetData(items=items, secondary=[{"label": "Detections", "value": len(items)}])

        if widget_kind == "today":
            return await self._today(config, options, ctx)

        stats = await self._get(config, ctx, "/stats", cache=15)
        cameras = self._cameras(stats)

        if widget_kind == "camera":
            return self._camera(cameras, options)
        if widget_kind == "health":
            return self._health(stats, cameras)

        if widget_kind == "cameras":
            items = []
            for name, values in cameras.items():
                camera_fps = float(values.get("camera_fps") or 0)
                detection_fps = float(values.get("detection_fps") or 0)
                items.append({
                    "title": name.replace("_", " "),
                    "subtitle": f"{camera_fps:.0f} fps · {detection_fps:.1f} detections/s",
                    "value": f"{int(float(values.get('process_fps') or 0))} fps",
                    "status": "bad" if camera_fps <= 0 else "ok",
                })
            items.sort(key=lambda item: 0 if item["status"] == "bad" else 1)
            return WidgetData(
                status="bad" if any(item["status"] == "bad" for item in items) else "ok",
                items=items,
                secondary=[{"label": "Cameras", "value": len(items)}],
                metrics={"cameras": float(len(items))},
            )

        service = (stats or {}).get("service") or {}
        storage = service.get("storage") or {}
        recordings = storage.get("/media/frigate/recordings") or {}
        used = float(recordings.get("used") or 0) * 1024 * 1024
        total = float(recordings.get("total") or 0) * 1024 * 1024
        # ⚠️ This used to fall back to 0.0, which colours the card green for a
        # recordings folder whose size Frigate did not report.
        share = percent(used, total)
        return WidgetData(
            status=status_from_percent(share),
            primary={"label": "Cameras", "value": len(cameras)},
            secondary=[
                {"label": "Detections per second", "value": round(float((stats or {}).get("detection_fps") or 0), 1)},
                {"label": "Recordings", "value": human_bytes(used)},
                {"label": "Used", "value": percent_text(share, 1)},
            ],
            metrics=measured({"cameras": float(len(cameras)), "storage_percent": share}),
        )

    # -- pictures, today and health ------------------------------------------

    @staticmethod
    def _score(event: dict[str, Any]) -> str:
        """How sure Frigate was, from wherever this version keeps it.

        ⚠️ Newer Frigate leaves ``top_score`` at the top ``null`` and keeps the
        number in ``data``: the reporter's car read 0% while ``data.top_score``
        said 0.917 (issue #1, measured 18.09.2026). No number is no number,
        not 0%.
        """
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        for value in (data.get("top_score"), data.get("score"), event.get("top_score"), event.get("score")):
            if isinstance(value, (int, float)) and value > 0:
                return f"{round(float(value) * 100)}%"
        return ""

    @staticmethod
    def _thumbnail(event: dict[str, Any]) -> str:
        identifier = str(event.get("id") or "")
        try:
            return f"proxy:/thumb/{path_segment(identifier, 'The detection')}"
        except AdapterError:
            return ""

    async def image_source(self, config: dict[str, Any], path: str, ctx: Context) -> MediaSource:
        """``/latest/<camera>`` and ``/thumb/<detection>``, fetched with the account's token.

        ⚠️ Only these two. The default would fetch any path of Frigate's
        address, and on port 5000 that is every endpoint without a sign-in.
        The latest picture is never kept; a detection's thumbnail does not
        change and is kept.
        """
        parts = path.strip("/").split("/")
        if len(parts) != 2 or parts[0] not in ("latest", "thumb"):
            raise AdapterError("Frigate pictures are /latest/<camera> or /thumb/<detection>.", code="bad_path")
        name = path_segment(parts[1], "The camera" if parts[0] == "latest" else "The detection")
        token = await self._token(config, ctx)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if parts[0] == "latest":
            return MediaSource(url=f"{base_url(config)}/api/{name}/latest.jpg", headers=headers,
                               params={"h": 720}, cache_seconds=0, media_type="image/jpeg")
        return MediaSource(url=f"{base_url(config)}/api/events/{name}/thumbnail.jpg", headers=headers,
                           media_type="image/jpeg")

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        if field != "camera":
            return await super().choices(field, config, ctx)
        cameras = self._cameras(await self._get(config, ctx, "/stats", cache=60))
        return [(name, name.replace("_", " ")) for name in sorted(cameras)]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        if field != "camera":
            return []
        return [(name, name.replace("_", " ")) for name in DEMO_CAMERAS]

    @staticmethod
    def _camera(cameras: dict[str, Any], options: dict[str, Any]) -> WidgetData:
        wanted = str(options.get("camera") or "").strip()
        if not wanted:
            raise AdapterError("Pick a camera in the card's settings.", code="bad_param")
        values = cameras.get(wanted)
        if values is None:
            raise AdapterError(f"Frigate has no camera {wanted}.", code="no_camera",
                               hint=f"It has {', '.join(sorted(cameras)) or 'none'}.")
        receiving = float(values.get("camera_fps") or 0) > 0
        return WidgetData(
            status="ok" if receiving else "bad",
            items=[{
                "title": wanted.replace("_", " "),
                "subtitle": "" if receiving else "no frames",
                "status": "ok" if receiving else "bad",
                "art": f"proxy:/latest/{path_segment(wanted, 'The camera')}",
            }],
            meta={"mode": "snapshot", "live": False, "interval": max(5, int(options.get("interval") or 10)), "empty": "No cameras"},
        )

    async def _today(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        """Detections since midnight on nexdeck's clock, by label.

        Counted from ``/api/events`` rather than ``/api/events/summary``: the
        list is what the Detections card already reads.
        """
        midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        params: dict[str, Any] = {"after": int(midnight.timestamp()), "limit": 1000, "include_thumbnails": 0}
        camera = str(options.get("camera") or "").strip()
        if camera:
            params["cameras"] = path_segment(camera, "The camera")
        events = await self._get(config, ctx, "/events", params=params, cache=60)
        return self._count(events if isinstance(events, list) else [])

    @staticmethod
    def _count(events: list[dict[str, Any]]) -> WidgetData:
        labels = Counter(str(event.get("label") or "?") for event in events if isinstance(event, dict))
        total = sum(labels.values())
        return WidgetData(
            status="ok",
            primary={"label": "Detections today", "value": total},
            secondary=[{"label": label.capitalize(), "value": count} for label, count in labels.most_common(6)],
            metrics={"detections_today": float(total)},
        )

    @staticmethod
    def _health(stats: dict[str, Any], cameras: dict[str, Any]) -> WidgetData:
        """Only what is wrong; an empty card is the good news.

        ⚠️ The thresholds come from Frigate's documentation, not from a
        measured installation: a camera at 0 fps delivers nothing, skipped
        frames mean detection cannot keep up, and a detector slower than
        about 100 ms a picture falls behind a camera at 10 fps.
        """
        items: list[dict[str, Any]] = []
        for name, values in sorted(cameras.items()):
            title = name.replace("_", " ")
            if float(values.get("camera_fps") or 0) <= 0:
                items.append({"title": title, "subtitle": "no frames from the camera", "status": "bad"})
                continue
            skipped = float(values.get("skipped_fps") or 0)
            if skipped >= SKIPPED_FPS:
                items.append({"title": title, "subtitle": f"skips {skipped:.1f} frames/s, detection cannot keep up", "status": "warn"})
        for name, detector in sorted(((stats or {}).get("detectors") or {}).items()):
            speed = float(detector.get("inference_speed") or 0) if isinstance(detector, dict) else 0.0
            if speed > SLOW_DETECTOR_MS:
                items.append({"title": f"Detector {name}", "subtitle": f"{speed:.0f} ms per picture", "status": "warn"})
        recordings = (((stats or {}).get("service") or {}).get("storage") or {}).get("/media/frigate/recordings") or {}
        share = percent(float(recordings.get("used") or 0), float(recordings.get("total") or 0))
        if share is not None and share >= 90:
            items.append({"title": "Recordings", "subtitle": f"{percent_text(share)} of the disk used",
                          "status": "bad" if share >= 97 else "warn"})
        order = {"bad": 0, "warn": 1}
        items.sort(key=lambda item: order.get(str(item["status"]), 2))
        bad = sum(1 for item in items if item["status"] == "bad")
        warn = len(items) - bad
        meta: dict[str, Any] = {"empty": f"Frigate answers · {len(cameras)} cameras, nothing to report"}
        if items:
            meta["status_reason"] = f"{bad} error finding(s), {warn} warning(s)"
        return WidgetData(status="bad" if bad else ("warn" if warn else "ok"), items=items, meta=meta)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cameras = list(DEMO_CAMERAS)
        if widget_kind == "camera":
            return WidgetData(
                items=[{"title": "driveway", "subtitle": "", "status": "ok", "art": ""}],
                meta={"mode": "snapshot", "live": False, "interval": 30, "empty": "No cameras"},
            )
        if widget_kind == "today":
            return self._count([{"label": label} for label in ["person"] * 7 + ["car"] * 4 + ["cat"] * 2 + ["package"]])
        if widget_kind == "health":
            if fake.flicker("frigate-health", tick, 0.1):
                return self._health({}, {"garden": {"camera_fps": 0}})
            return self._health({}, {name: {"camera_fps": 10} for name in cameras})
        if widget_kind == "events":
            rows = [("Person", "front_door", 91), ("Car", "driveway", 88), ("Cat", "garden", 74), ("Person", "garage", 69)]
            return WidgetData(
                items=[
                    {"title": label, "subtitle": f"{camera} · {(7 + index * 3) % 24:02d}:{(tick * 7 + index * 11) % 60:02d}", "value": f"{score}%", "status": "warn" if index == 0 else "ok"}
                    for index, (label, camera, score) in enumerate(rows[: int(options.get("limit") or 8)])
                ],
                secondary=[{"label": "Detections", "value": 4}],
            )
        if widget_kind == "cameras":
            broken = fake.flicker("frigate-camera", tick, 0.08)
            items = []
            for index, name in enumerate(cameras):
                down = broken and index == 2
                items.append({
                    "title": name.replace("_", " "),
                    "subtitle": f"{0 if down else 10} fps · {0 if down else round(fake.walk(f'frigate-d{index}', tick, 0.2, 4.0), 1)} detections/s",
                    "value": f"{0 if down else 10} fps",
                    "status": "bad" if down else "ok",
                })
            items.sort(key=lambda item: 0 if item["status"] == "bad" else 1)
            return WidgetData(
                status="bad" if broken else "ok",
                items=items,
                secondary=[{"label": "Cameras", "value": len(items)}],
                metrics={"cameras": float(len(items))},
            )
        share = fake.walk("frigate-storage", tick, 46, 78)
        return WidgetData(
            status=status_from_percent(share),
            primary={"label": "Cameras", "value": len(cameras)},
            secondary=[
                {"label": "Detections per second", "value": round(fake.walk("frigate-fps", tick, 1.2, 9.4), 1)},
                {"label": "Recordings", "value": human_bytes(share / 100 * 2.0e12)},
                {"label": "Used", "value": percent_text(share, 1)},
            ],
            metrics={"cameras": float(len(cameras)), "storage_percent": share},
        )


ADAPTER = FrigateAdapter()
