"""ReadMeABook: audiobook requests and their downloads, read through its API tokens.

Built from ReadMeABook's own source (1.2.3) and its token documentation:
an ``rmab_`` token rides as a bearer and may call a fixed list of endpoints,
nothing else. The three the cards read are the administrator's figures:
``/api/admin/metrics``, ``/api/admin/downloads/active`` and
``/api/admin/requests/recent``. They are on that list since 1.2.0.

Three things ReadMeABook does that shape the cards:
- A token carries the role its owner had when it was made. A user's token is
  let in and then turned away from every admin figure with 403 "Admin access
  required", so the test asks ``/api/auth/me`` first and says which token it
  takes, instead of a bare refusal on every card.
- The health it reports is its own judgement: the database, and downloads
  that have sat for more than a day. "degraded" comes with the reasons.
- Speed and time left of a download come from the download client at the
  moment of asking; ReadMeABook answers 0 and no time when it cannot reach it.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    AdapterError,
    Context,
    Detected,
    Field,
    WidgetData,
    WidgetType,
    ago,
    base_url,
    duration_short,
    human_rate,
)

#: A request's state as the row shows it: colour, and the word on the right.
#: The states are ReadMeABook's, from its database schema.
STATES: dict[str, tuple[str, str]] = {
    "pending": ("unknown", "Pending"),
    "awaiting_approval": ("warn", "Awaiting approval"),
    "denied": ("unknown", "Denied"),
    "searching": ("ok", "Searching"),
    "awaiting_search": ("warn", "Nothing found yet"),
    "downloading": ("ok", "Download running"),
    "processing": ("ok", "Processing"),
    "awaiting_import": ("warn", "Awaiting import"),
    "downloaded": ("ok", "Downloaded"),
    "available": ("ok", "Available"),
    "awaiting_release": ("unknown", "Not released yet"),
    "failed": ("bad", "Failed"),
    "warn": ("warn", "Needs attention"),
    "cancelled": ("unknown", "Cancelled"),
}

#: Where a request has arrived: nothing more will happen to it.
SETTLED = frozenset({"downloaded", "available", "denied", "cancelled"})

#: What a finished download ends in. An ebook stops at "downloaded", an
#: audiobook goes on to "available" once the library has it.
DONE = frozenset({"downloaded", "available"})

HEALTH = {"healthy": "ok", "degraded": "warn", "unhealthy": "bad"}


def _limit(options: dict[str, Any]) -> int:
    try:
        wanted = int(options.get("limit") or 8)
    except (TypeError, ValueError):
        wanted = 8
    # ReadMeABook hands over the fifty newest and no more.
    return max(1, min(50, wanted))


def _count(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _state(status: str) -> tuple[str, str]:
    return STATES.get(status, ("unknown", status.replace("_", " ").capitalize() or "?"))


class ReadMeABookAdapter(Adapter):
    kind = "readmeabook"
    label = "ReadMeABook"
    category = "media"
    description = "Audiobook requests, what is downloading and how ReadMeABook is doing, through an administrator's API token."
    icon = "readmeabook"
    docs_url = "https://github.com/kikootwo/ReadMeABook"
    keywords = ("audiobooks", "ebooks", "RMAB", "requests")
    #: Seen against a live ReadMeABook 1.2.3 on 26.09.2026, set up with made-up
    #: services behind it: the test, the overview, a request moving from
    #: "searching" to "awaiting_search", an administrator's and a user's token
    #: and a wrong one. A running download was never seen, so it stays beta.
    beta = True
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://readmeabook:3030"),
        Field("api_key", "API token", type="password", secret=True, required=True,
              help="An rmab_ token of an administrator, from Profile > API Tokens. "
                   "A user's token is not let near the figures the cards read. Needs ReadMeABook 1.2.0 or newer."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="overview",
            label="ReadMeABook overview",
            description="What is downloading, all requests, what finished and failed in the last 30 days, the users, and ReadMeABook's own health.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("downloading",),
        ),
        WidgetType(
            kind="downloads",
            # Not "Downloading": a new card is named "ReadMeABook" plus this,
            # translated, and the German verb after the name reads as no name.
            # The same word stands as the big number's label and on a row,
            # where its German reads as a card that is still loading.
            label="Downloads",
            description="Books downloading right now, with how far they are, the speed and the time left.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=20,
            metrics=("downloading",),
        ),
        WidgetType(
            kind="requests",
            label="Latest requests",
            description="The newest requests with who asked and where each one stands; failed ones turn red.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            options=(
                Field("limit", "Entries", type="number", default=8, help="Between 1 and 50."),
                Field("open_only", "Only open requests", type="bool", default=False,
                      help="Leaves out what is downloaded, available, denied or cancelled."),
            ),
        ),
    )

    def default_link(self, config: dict[str, Any]) -> str:
        return base_url(config)

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float = 20) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}{path}",
            headers={"Authorization": f"Bearer {config.get('api_key', '')}"},
            verify=not config.get("insecure"), cache_seconds=cache,
            # ⚠️ Not all refusals are the same: a wrong token is fixed in this
            # connection, a user's token by making one as an administrator.
            auth_errors=False,
        )
        if response.status_code == 401:
            raise AdapterError(
                "ReadMeABook does not know this token, or it has expired or been revoked.",
                code="auth_failed", hint="Create a new one under Profile > API Tokens.",
            )
        if response.status_code == 403:
            message = ""
            try:
                message = str(response.json().get("message") or "")
            except (ValueError, AttributeError):
                pass
            if "not available via API token" in message:
                raise AdapterError(
                    "This ReadMeABook does not let API tokens read its figures. It needs version 1.2.0 or newer.",
                    code="readmeabook_too_old",
                )
            raise AdapterError(
                "This token belongs to a user, not an administrator, and ReadMeABook shows its figures only to administrators.",
                code="readmeabook_not_admin",
                hint="Create a token while signed in as an administrator, or under Admin > Users for an administrator.",
            )
        if response.status_code == 404:
            raise AdapterError(
                "ReadMeABook does not know this address. It needs version 1.2.0 or newer.",
                code="readmeabook_too_old",
            )
        if response.status_code >= 400:
            raise AdapterError(f"ReadMeABook answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("ReadMeABook did not answer with JSON.", code="bad_answer",
                               hint="The URL probably points at a sign-in page or a reverse proxy.") from error

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        me = await self._get(config, ctx, "/api/auth/me", cache=0)
        user = me.get("user") if isinstance(me, dict) else None
        user = user if isinstance(user, dict) else {}
        if user.get("role") != "admin":
            raise AdapterError(
                f"The token belongs to {user.get('username') or 'a user'}, who is no administrator. "
                "ReadMeABook shows the figures the cards read only to administrators.",
                code="readmeabook_not_admin",
                hint="Create a token while signed in as an administrator.",
            )
        metrics = await self._get(config, ctx, "/api/admin/metrics", cache=0)
        total = _count(metrics, "totalRequests")
        return f"ReadMeABook answers to {user.get('username') or 'the administrator'}; {total} request{'' if total == 1 else 's'}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "overview":
            return self._overview(await self._get(config, ctx, "/api/admin/metrics", cache=30))
        if widget_kind == "downloads":
            return self._downloads(await self._get(config, ctx, "/api/admin/downloads/active", cache=10))
        if widget_kind == "requests":
            payload = await self._get(config, ctx, "/api/admin/requests/recent", cache=30)
            return self._requests(payload, _limit(options), bool(options.get("open_only")))
        raise KeyError(widget_kind)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _overview(metrics: dict[str, Any]) -> WidgetData:
        metrics = metrics if isinstance(metrics, dict) else {}
        health = metrics.get("systemHealth") if isinstance(metrics.get("systemHealth"), dict) else {}
        issues = [str(issue) for issue in health.get("issues") or [] if issue]
        downloading = _count(metrics, "activeDownloads")
        return WidgetData(
            status=HEALTH.get(str(health.get("status") or ""), "unknown"),
            primary={"label": "Downloads", "value": downloading},
            secondary=[
                {"label": "Requests", "value": _count(metrics, "totalRequests")},
                {"label": "Done in 30 days", "value": _count(metrics, "completedLast30Days")},
                {"label": "Failed in 30 days", "value": _count(metrics, "failedLast30Days")},
                {"label": "Users", "value": _count(metrics, "totalUsers")},
            ],
            metrics={"downloading": float(downloading)},
            # ReadMeABook's own words: "3 stale downloads (>24h)".
            meta={"status_reason": "; ".join(issues)},
        )

    @staticmethod
    def _downloads(payload: dict[str, Any]) -> WidgetData:
        downloads = payload.get("downloads") if isinstance(payload, dict) else None
        rows = []
        for download in downloads if isinstance(downloads, list) else []:
            speed = float(download.get("speed") or 0)
            eta = download.get("eta")
            parts = [human_rate(speed)] if speed > 0 else []
            if isinstance(eta, int | float) and eta > 0:
                parts.append(duration_short(eta))
            subtitle = [str(part) for part in (download.get("author"), download.get("user")) if part]
            if download.get("type") == "ebook":
                subtitle.append("ebook")
            try:
                progress = max(0.0, min(100.0, float(download.get("progress") or 0)))
            except (TypeError, ValueError):
                progress = 0.0
            rows.append({
                "id": download.get("requestId"),
                "title": str(download.get("title") or "?"),
                "subtitle": " · ".join(subtitle),
                "progress": progress,
                "value": " · ".join(parts),
                "status": "ok",
            })
        return WidgetData(
            status="ok",
            items=rows,
            secondary=[{"label": "Downloads", "value": len(rows)}],
            metrics={"downloading": float(len(rows))},
            meta={"empty": "Nothing is downloading."},
        )

    @staticmethod
    def _requests(payload: dict[str, Any], limit: int, open_only: bool) -> WidgetData:
        requests = payload.get("requests") if isinstance(payload, dict) else None
        rows = []
        for request in requests if isinstance(requests, list) else []:
            status = str(request.get("status") or "")
            if open_only and status in SETTLED:
                continue
            colour, word = _state(status)
            subtitle = [str(part) for part in (request.get("author"), request.get("user")) if part]
            when = ago(request.get("createdAt"))
            if when:
                subtitle.append(when)
            row = {
                "id": request.get("requestId"),
                "title": str(request.get("title") or "?"),
                "subtitle": " · ".join(subtitle),
                "value": word,
                "status": colour,
                # For the detector: where the request stood when it was read,
                # and who asked. Not ``state``, which a list renderer reads.
                "stage": status,
                "requested_by": str(request.get("user") or ""),
            }
            if colour == "bad" and request.get("errorMessage"):
                row["subtitle"] = str(request["errorMessage"])[:200]
            rows.append(row)
            if len(rows) >= limit:
                break
        # ⚠️ The row turns red, the card does not: a failed request stays
        # failed until somebody deals with it in ReadMeABook, and a card that
        # is red for weeks is a card nobody looks at any more.
        return WidgetData(
            status="ok",
            items=rows,
            meta={"empty": "No open request." if open_only else "No request yet."},
        )

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A request that was not there is new; one that reached its end finished.

        ⚠️ By its number, and only when the list was read both times, as the
        Seerr card does: an empty "before" is a card that was broken or is
        new, and every request in the list is not news.

        ⚠️ Finished is a state ReadMeABook reports, never a guess from a
        disappearance: a request leaving the fifty newest has not finished.
        """
        if widget_kind != "requests" or before is None or before.error or not before.items:
            return []
        was = {str(item.get("id")): str(item.get("stage") or "") for item in before.items if item.get("id") is not None}
        found: list[Detected] = []
        for item in after.items:
            if item.get("id") is None:
                continue
            key = str(item.get("id"))
            title = str(item.get("title") or "A book")
            state = str(item.get("stage") or "")
            if key not in was:
                who = str(item.get("requested_by") or "")
                found.append(Detected(
                    event="request_new",
                    title=f"{title} was requested",
                    body=f"Asked for by {who} in ReadMeABook." if who else "In ReadMeABook.",
                    key=f"request_new:rmab:{key}",
                ))
            elif state in DONE and was[key] not in DONE:
                found.append(Detected(
                    event="download_done",
                    title=f"{title} finished",
                    body="ReadMeABook has it in the library." if state == "available" else "ReadMeABook has downloaded it.",
                    key=f"download_done:rmab:{key}",
                ))
        return found[:5]

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "overview":
            downloading = max(1, int(fake.walk("rmab-downloading", tick, 1, 3)))
            return self._overview({
                "totalRequests": fake.counter("rmab-requests", tick, 184, 0.002), "activeDownloads": downloading,
                "completedLast30Days": 23, "failedLast30Days": 1, "totalUsers": 6,
                "systemHealth": {"status": "healthy", "issues": []},
            })
        if widget_kind == "downloads":
            books = [("The Long Way Home", "Mara Ellis", "Alex", 0.34, 2_400_000), ("A History of Harbours", "Tom Reyes", "Sam", 0.71, 5_100_000)]
            return self._downloads({"downloads": [
                {"requestId": f"demo-{index}", "title": title, "author": author, "user": who, "type": "audiobook",
                 "progress": round(100 * ((share + tick / 600) % 1)), "speed": speed, "eta": int(900 * (1 - share))}
                for index, (title, author, who, share, speed) in enumerate(books)
            ]})
        requests = [
            ("The Long Way Home", "Mara Ellis", "Alex", "downloading"),
            ("Northern Shore", "Ines Laurent", "Kim", "awaiting_approval"),
            ("Copper Sky", "Jon Park", "Sam", "available"),
            ("Signal Lost", "Ruth Adler", "Robin", "failed"),
            ("A History of Harbours", "Tom Reyes", "Sam", "available"),
        ]
        return self._requests({"requests": [
            {"requestId": f"demo-{index}", "title": title, "author": author, "user": who, "status": status,
             "errorMessage": "No release matched the book." if status == "failed" else None}
            for index, (title, author, who, status) in enumerate(requests)
        ]}, _limit(options), bool(options.get("open_only")))


ADAPTER = ReadMeABookAdapter()
