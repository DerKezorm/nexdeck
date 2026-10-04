"""Real-Debrid: the premium left on the account, its torrents and its latest downloads.

Written on 04.10.2026 from the documentation of the REST API 1.0
(https://api.real-debrid.com/) for issue #29, without an account to
measure against; beta until someone with one has seen the cards.

- One address for everyone, ``https://api.real-debrid.com/rest/1.0``. The
  private API token from https://real-debrid.com/apitoken goes in
  ``Authorization: Bearer``, never in the address, although the API would
  take it there too.
- Refusals are ``{"error": …, "error_code": n}``: 401 for a bad token,
  403 for a locked account (14) or an address Real-Debrid does not serve (22).
  Real-Debrid is known to refuse addresses of VPNs and data centres, so a
  nexdeck on a rented server or behind a VPN may see 22 with a good token.
- 250 requests a minute per account; refused ones count as well, and too
  many can block the account for a while. Every card is cached for a minute
  or more and nothing is asked again on a refusal.
- Read only: nothing is added, selected, deleted or unrestricted from here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    human_bytes,
    human_rate,
)

API = "https://api.real-debrid.com/rest/1.0"
SITE = "https://real-debrid.com"
#: Real-Debrid's states of a torrent, in words, and how a card colours them.
STATES = {
    "magnet_error": ("magnet failed", "bad"),
    "magnet_conversion": ("reading the magnet", "warn"),
    "waiting_files_selection": ("waiting for a file selection", "warn"),
    "queued": ("queued", "warn"),
    "downloading": ("downloading", "ok"),
    "downloaded": ("ready", "ok"),
    "error": ("failed", "bad"),
    "virus": ("virus found", "bad"),
    "compressing": ("compressing", "ok"),
    "uploading": ("uploading", "ok"),
    "dead": ("dead", "bad"),
}
SHOW = (("active", "Active only"), ("all", "All"))


class RealDebridAdapter(Adapter):
    kind = "realdebrid"
    label = "Real-Debrid"
    category = "downloads"
    description = "The premium left on a Real-Debrid account, its torrents with their progress, and the latest downloads."
    icon = "real-debrid"
    beta = True
    docs_url = "https://api.real-debrid.com/"
    keywords = ("Debrid", "RD", "Torrent")
    fields = (
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="The private API token from real-debrid.com/apitoken. Real-Debrid refuses many addresses of VPNs and data centres."),
    )
    widgets = (
        WidgetType(
            kind="account",
            label="Real-Debrid account",
            description="The days of premium left and when it ends, the fidelity points, and the torrents running against their limit.",
            renderer="value",
            default_size=(3, 2),
            refresh_seconds=900,
            metrics=("days",),
        ),
        WidgetType(
            kind="torrents",
            label="Torrents",
            description="The torrents on the account, newest first, with their progress and what holds them up.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=120,
            options=(
                Field("show", "Show", type="select", default="active", options=SHOW),
                Field("limit", "Entries", type="number", default=8, help="Between 1 and 50."),
            ),
        ),
        WidgetType(
            kind="downloads",
            label="Latest downloads",
            description="The links unrestricted last, newest first, with their hoster and size.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            options=(Field("limit", "Entries", type="number", default=6, help="Between 1 and 50."),),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return SITE

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, *,
                   params: dict[str, Any] | None = None, cache: int = 60) -> Any:
        response = await ctx.request(
            "GET", f"{API}{path}", params=params, cache_seconds=cache, auth_errors=False,
            headers={"Authorization": f"Bearer {str(config.get('api_key') or '').strip()}", "Accept": "application/json"},
        )
        code = _code_of(response)
        if response.status_code == 401 or code == 8:
            raise AuthFailed("Real-Debrid does not know this API token; it may have been renewed.")
        if code == 14:
            raise AdapterError("Real-Debrid has locked this account.", code="auth_failed")
        if code == 22:
            raise AdapterError("Real-Debrid does not serve the address nexdeck asks from.", code="ip_refused",
                               hint="Real-Debrid refuses many addresses of VPNs and data centres. Its support can allow one.")
        if response.status_code == 429 or code == 34:
            raise AdapterError("Real-Debrid asks for fewer requests for a while.", code="rate_limited",
                               hint="It allows 250 a minute for an account, nexdeck and every other app together.")
        if response.status_code == 204:
            return []
        if response.status_code >= 400:
            raise AdapterError(f"Real-Debrid answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            raise AdapterError("Real-Debrid did not answer with JSON.", code="bad_answer") from None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        user = await self._get(config, ctx, "/user", cache=0)
        user = user if isinstance(user, dict) else {}
        if user.get("type") != "premium":
            return f"Real-Debrid answers for {user.get('username') or '?'}, an account without premium."
        return f"Real-Debrid answers for {user.get('username') or '?'}, premium for {_days(user.get('premium'))} more day(s)."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "torrents":
            show = str(options.get("show") or "active")
            params: dict[str, Any] = {"limit": _limit(options, 8)}
            if show == "active":
                params["filter"] = "active"
            rows = await self._get(config, ctx, "/torrents", params=params)
            return torrents_of(rows if isinstance(rows, list) else [], _limit(options, 8), show == "active")
        if widget_kind == "downloads":
            rows = await self._get(config, ctx, "/downloads", params={"limit": _limit(options, 6)}, cache=120)
            return downloads_of(rows if isinstance(rows, list) else [], _limit(options, 6))
        user = await self._get(config, ctx, "/user", cache=300)
        active = await self._get(config, ctx, "/torrents/activeCount")
        return account_of(user if isinstance(user, dict) else {}, active if isinstance(active, dict) else {})

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        now = datetime.now(UTC)
        if widget_kind == "torrents":
            progress = round(fake.walk("rd-progress", tick, 20, 95), 1)
            rows = [
                {"id": "D1", "filename": "Example.Linux.Distro.2026.10.iso", "bytes": 4_400_000_000, "status": "downloading",
                 "progress": progress, "speed": 38_000_000, "added": (now - timedelta(minutes=8)).isoformat()},
                {"id": "D2", "filename": "Open.Movie.Project.2160p", "bytes": 21_000_000_000, "status": "waiting_files_selection",
                 "progress": 0, "added": (now - timedelta(hours=1)).isoformat()},
                {"id": "D3", "filename": "Public.Domain.Concert.FLAC", "bytes": 1_200_000_000, "status": "downloaded",
                 "progress": 100, "added": (now - timedelta(hours=5)).isoformat()},
            ]
            show = str(options.get("show") or "active")
            if show == "active":
                rows = [row for row in rows if row["status"] != "downloaded"]
            return torrents_of(rows, _limit(options, 8), show == "active")
        if widget_kind == "downloads":
            rows = [
                {"id": "L1", "filename": "Example.Linux.Distro.2026.10.iso", "filesize": 4_400_000_000, "host": "real-debrid.com",
                 "generated": (now - timedelta(minutes=20)).isoformat()},
                {"id": "L2", "filename": "conference-talk.mp4", "filesize": 640_000_000, "host": "example.com",
                 "generated": (now - timedelta(hours=3)).isoformat()},
            ]
            return downloads_of(rows, _limit(options, 6))
        return account_of({"username": "example", "type": "premium", "points": 1240,
                           "premium": 86_400 * 41, "expiration": (now + timedelta(days=41)).isoformat()},
                          {"nb": 1 if fake.flicker("rd-active", tick, 0.5) else 2, "limit": 50})


def _code_of(response: Any) -> int | None:
    try:
        answer = response.json()
    except (ValueError, AttributeError):
        return None
    code = answer.get("error_code") if isinstance(answer, dict) else None
    return code if isinstance(code, int) else None


def _limit(options: dict[str, Any], default: int) -> int:
    try:
        return max(1, min(50, int(options.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _days(seconds: Any) -> int:
    try:
        return max(0, int(float(seconds)) // 86_400)
    except (TypeError, ValueError):
        return 0


def _date(moment: Any) -> str:
    try:
        return datetime.fromisoformat(str(moment).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def account_of(user: dict[str, Any], active: dict[str, Any]) -> WidgetData:
    premium = user.get("type") == "premium"
    days = _days(user.get("premium")) if premium else 0
    if not premium:
        status, reason = "bad", "The account has no premium."
    elif days < 7:
        status, reason = "warn", f"Premium ends in {days} day(s)."
    else:
        status, reason = "ok", ""
    secondary = [
        {"label": "Ends", "value": (_date(user.get("expiration")) if premium else "") or "?"},
        {"label": "Points", "value": int(user.get("points") or 0)},
    ]
    if active:
        secondary.append({"label": "Active torrents", "value": f"{int(active.get('nb') or 0)} / {int(active.get('limit') or 0)}"})
    return WidgetData(
        status=status,
        primary={"label": "Premium days", "value": days},
        secondary=secondary,
        metrics={"days": float(days)},
        meta={"status_reason": reason},
    )


def torrents_of(rows: list[Any], limit: int, active_only: bool) -> WidgetData:
    items = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        words, state = STATES.get(str(row.get("status") or ""), (str(row.get("status") or "?"), "unknown"))
        progress = float(row.get("progress") or 0)
        parts = [human_bytes(row.get("bytes")) if row.get("bytes") else "", words]
        if row.get("status") == "downloading" and row.get("speed"):
            parts.append(human_rate(float(row["speed"])))
        items.append({
            "id": str(row["id"]),
            "title": str(row.get("filename") or "?"),
            "subtitle": " · ".join(part for part in parts if part),
            "progress": round(progress, 1),
            "value": f"{progress:.0f}%",
            "status": state,
            "url": f"{SITE}/torrents",
        })
    items = items[:limit]
    bad = [item for item in items if item["status"] == "bad"]
    return WidgetData(
        status="bad" if bad else "ok",
        items=items,
        meta={"empty": "No torrent is running." if active_only else "No torrents on the account.",
              "status_reason": f"{len(bad)} torrent(s) failed" if bad else ""},
    )


def downloads_of(rows: list[Any], limit: int) -> WidgetData:
    items = [
        {
            "id": str(row.get("id") or row.get("download") or index),
            "title": str(row.get("filename") or "?"),
            "subtitle": " · ".join(part for part in (str(row.get("host") or ""),
                                                      human_bytes(row.get("filesize")) if row.get("filesize") else "") if part),
            "value": ago(row.get("generated")),
            "url": f"{SITE}/downloads",
        }
        for index, row in enumerate(rows) if isinstance(row, dict)
    ][:limit]
    return WidgetData(status="ok", items=items, meta={"empty": "Nothing unrestricted yet."})


ADAPTER = RealDebridAdapter()
