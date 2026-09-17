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
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    measured,
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
            description="What was seen last, with camera and time.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=30,
            options=(Field("limit", "Entries", type="number", default=8),),
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
        skip = {"detectors", "service", "cpu_usages", "gpu_usages", "processes", "detection_fps", "bandwidth"}
        return {name: values for name, values in (stats or {}).items() if name not in skip and isinstance(values, dict)}

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "events":
            limit = int(options.get("limit") or 8)
            events = await self._get(config, ctx, "/events", params={"limit": limit}, cache=15)
            items = []
            for event in events if isinstance(events, list) else []:
                when = event.get("start_time")
                moment = datetime.fromtimestamp(float(when), UTC).strftime("%H:%M") if when else ""
                items.append({
                    "title": str(event.get("label") or "?").capitalize(),
                    "subtitle": f"{event.get('camera', '?')} · {moment}",
                    "value": f"{int(float(event.get('top_score') or event.get('score') or 0) * 100)}%",
                    "status": "warn" if event.get("has_clip") else "ok",
                })
            return WidgetData(items=items, secondary=[{"label": "Detections", "value": len(items)}])

        stats = await self._get(config, ctx, "/stats", cache=15)
        cameras = self._cameras(stats)

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

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        cameras = ["driveway", "front_door", "garden", "garage"]
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
