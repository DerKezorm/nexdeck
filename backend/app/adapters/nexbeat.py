"""nexbeat: music requests of the nexapps family, read and decided through its API tokens.

Built against nexbeat's ``/api/v1``, which nexbeat promises to keep: ``me`` says
who a token is and what it may do, ``dashboard`` carries the numbers in one
call, and the waiting requests are approved or turned down through the same
handlers nexbeat's own interface uses.

Three things from that contract shape the cards:

- ``may`` in ``/api/v1/me`` folds the account and the token together:
  ``decide`` is there only for an administrator's token that may write. The
  approval card builds its buttons on that, not on the role, the same way the
  Nexview card builds on ``darf``.
- ``dashboard`` counts the whole installation for an administrator
  (``scope: all``) and only the own requests for everybody else. The card says
  which, so a user's own three requests do not pass for the house total.
- ``cover_url`` is either a whole address (Cover Art Archive) or, for a whole
  artist, a path on nexbeat itself. The path is made whole here; nexbeat serves
  it without a sign-in because an ``<img>`` sends no token.
"""

from __future__ import annotations

from typing import Any

from .base import (
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
)

#: What a token has to be allowed in ``/api/v1/me`` to approve or turn down.
MAY_DECIDE = "decide"
#: What a token has to be allowed to read the list of waiting requests at all.
MAY_SEE_ALL = "see_all"

#: nexbeat's refusals by code, in the words this card uses. Anything else is
#: passed through as nexbeat wrote it.
REFUSALS = {
    "request_not_pending": "This request is no longer waiting for approval.",
    "api_key_read_only": "This token may only read.",
    "admins_only": "This token belongs to an account that is not an administrator.",
    "request_not_found": "nexbeat no longer knows this request.",
}

#: Where requests go, by the name nexbeat gives it.
TARGETS = {"lidarr": "Lidarr", "nexcrate": "nexcrate"}


class NexbeatAdapter(Adapter):
    kind = "nexbeat"
    label = "nexbeat"
    category = "media"
    description = "Waiting and running music requests, the library and requests to approve from nexbeat."
    icon = "nexbeat"
    # All three cards and both buttons ran against a released nexbeat 1.2.0 on 2026-09-28.
    beta = False
    docs_url = "https://github.com/DerKezorm/nexbeat"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://nexbeat:8030"),
        Field(
            "api_key", "API token", type="password", secret=True, required=True,
            help="A token from nexbeat under Profile > API tokens. Read-only is enough for the numbers; "
                 "approving requests needs an administrator's token that may write.",
        ),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="requests", label="Requests", description="Waiting, running and failed requests, and what arrived this week.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=60, metrics=("waiting", "running")),
        WidgetType(kind="library", label="Library", description="Artists and albums in Lidarr or nexcrate, as nexbeat knows them.", renderer="value", default_size=(2, 2), min_size=(1, 1), refresh_seconds=300),
        WidgetType(
            kind="approvals",
            label="Requests to approve",
            description="What waits for approval, with its cover, to approve or turn down from the board.",
            renderer="list",
            default_size=(4, 4),
            refresh_seconds=60,
            metrics=("waiting",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {config.get('api_key', '')}"}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, cache: float) -> dict[str, Any]:
        answer = await ctx.get_json(f"{base_url(config)}{path}", headers=self._headers(config),
                                    verify=not config.get("insecure"), cache_seconds=cache)
        return answer if isinstance(answer, dict) else {}

    async def _me(self, config: dict[str, Any], ctx: Context, cache: float = 300) -> dict[str, Any]:
        return await self._get(config, ctx, "/api/v1/me", cache)

    async def _dashboard(self, config: dict[str, Any], ctx: Context, cache: float = 30) -> dict[str, Any]:
        return await self._get(config, ctx, "/api/v1/dashboard", cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        tile = await self._dashboard(config, ctx, cache=0)
        me = await self._me(config, ctx, cache=0)
        version = tile.get("version", "?")
        # ⚠️ Said at setup, not discovered on the board: a read-only token is a
        # good token for the numbers, and an approval card without buttons
        # would otherwise look like one that forgot them.
        if MAY_DECIDE in (me.get("may") or []):
            return f"nexbeat {version} answers. This token may approve requests."
        if MAY_SEE_ALL in (me.get("may") or []):
            return (f"nexbeat {version} answers. This token may not approve, "
                    "so the approval card shows requests without buttons.")
        return (f"nexbeat {version} answers. This token belongs to an account that is not an administrator, "
                "so the cards count its own requests only.")

    @staticmethod
    def _scope_meta(tile: dict[str, Any]) -> dict[str, Any]:
        if tile.get("scope") == "mine":
            return {"notice": "This token belongs to an account that is not an administrator, so only its own requests are counted."}
        return {}

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "approvals":
            return await self._approvals(config, options, ctx)
        tile = await self._dashboard(config, ctx)
        if widget_kind == "requests":
            return self._requests_card(tile)
        return self._library_card(tile)

    @staticmethod
    def _requests_card(tile: dict[str, Any]) -> WidgetData:
        counts = tile.get("requests") or {}
        waiting = int(counts.get("waiting") or 0)
        running = int(counts.get("running") or 0)
        failed = int(counts.get("failed") or 0)
        meta = NexbeatAdapter._scope_meta(tile)
        status = "ok"
        if failed:
            status = "warn"
            meta["status_reason"] = f"{failed} request(s) failed"
        elif tile.get("requests_enabled") is False:
            # Nothing can reach Lidarr or nexcrate, so every request just waits.
            status = "warn"
            meta["status_reason"] = "nexbeat has no target for requests"
        return WidgetData(
            status=status,
            primary={"label": "Waiting", "value": waiting},
            secondary=[
                {"label": "Running", "value": running},
                {"label": "Failed", "value": failed},
                {"label": "This week", "value": int(counts.get("done_last_7_days") or 0)},
            ],
            metrics={"waiting": float(waiting), "running": float(running)},
            meta=meta,
        )

    @staticmethod
    def _library_card(tile: dict[str, Any]) -> WidgetData:
        library = tile.get("library") or {}
        target = TARGETS.get(str(tile.get("target") or ""), "")
        secondary: list[dict[str, Any]] = [
            {"label": "Albums", "value": int(library.get("albums") or 0)},
            {"label": "With music", "value": int(library.get("artists_with_music") or 0)},
        ]
        if target:
            secondary.append({"label": "Source", "value": target})
        return WidgetData(
            status="ok" if target else "warn",
            primary={"label": "Artists", "value": int(library.get("artists") or 0)},
            secondary=secondary,
            meta={} if target else {"status_reason": "nexbeat has no target for requests"},
        )

    async def _approvals(self, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        me = await self._me(config, ctx)
        may = me.get("may") or []
        if MAY_SEE_ALL not in may:
            return WidgetData(status="unknown", meta={
                "notice": "This token belongs to an account that is not an administrator, so there is nothing to list.",
                "empty": "Nothing to show",
            })
        may_decide = MAY_DECIDE in may

        response = await ctx.request("GET", f"{base_url(config)}/api/v1/admin/requests",
                                     params={"status": "pending_approval"}, headers=self._headers(config),
                                     verify=not config.get("insecure"), cache_seconds=30, auth_errors=False)
        if response.status_code >= 400:
            raise AdapterError(self._refusal(response), code="http_error")
        try:
            rows = response.json()
        except ValueError as error:
            raise AdapterError("nexbeat did not answer with its list of requests.", code="not_json") from error
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        shown = rows[: max(1, int(options.get("limit") or 8))]
        items = [self._approval_row(row, base_url(config), may_decide) for row in shown]
        items = [item for item in items if item is not None]
        # The rows exist to be pressed, so their buttons show without a hover:
        # a wall display with a touchscreen has none.
        meta: dict[str, Any] = {"empty": "Nothing is waiting for approval.", "actions_visible": True}
        if not may_decide:
            meta["notice"] = "This token may only read. Approving needs an administrator's token that may write."
        return WidgetData(
            status="warn" if rows else "ok",
            items=items,
            secondary=[{"label": "Waiting", "value": len(rows)}],
            metrics={"waiting": float(len(rows))},
            meta=meta,
        )

    @staticmethod
    def _approval_row(row: dict[str, Any], base: str, may_decide: bool) -> dict[str, Any] | None:
        request_id = row.get("id")
        if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 1:
            return None
        whole_artist = row.get("kind") == "artist"
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        who = str(user.get("display_name") or user.get("username") or "")
        cover = str(row.get("cover_url") or "")
        # A whole artist's picture is a path on nexbeat itself; the albums'
        # covers are whole addresses already.
        if cover.startswith("/") and not cover.startswith("//"):
            cover = base + cover
        elif not cover.startswith(("https://", "http://")):
            cover = ""
        item: dict[str, Any] = {
            "id": request_id,
            "title": str(row.get("title") or "?"),
            "subtitle": who if whole_artist else " · ".join(part for part in (str(row.get("artist_name") or ""), who) if part),
            "value": "Whole artist" if whole_artist else str(row.get("album_type") or ""),
            "art": cover,
            "art_shape": "square",
            "status": "warn",
        }
        if may_decide:
            item["actions"] = [
                {"id": "approve", "label": "Approve", "icon": "check", "params": {"id": request_id}},
                {"id": "reject", "label": "Turn down", "icon": "x", "danger": True, "confirm": True, "params": {"id": request_id}},
            ]
        return item

    @staticmethod
    def _refusal(response: Any) -> str:
        """nexbeat's own reason, which is the one that says what to do.

        nexbeat answers ``{"detail": {"code", "message"}}`` with an English
        message; a known code is put in this card's words, anything else is
        passed through rather than replaced by a status code.
        """
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, dict):
            code = str(detail.get("code") or "")
            if code in REFUSALS:
                return REFUSALS[code]
            if detail.get("message"):
                return str(detail["message"])[:200]
        if isinstance(detail, str) and detail:
            return detail[:200]
        return f"nexbeat refused with HTTP {response.status_code}."

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if widget_kind != "approvals" or action_id not in ("approve", "reject"):
            raise AdapterError("This widget has no such action.", code="no_such_action")
        request_id = params.get("id")
        if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 1:
            raise AdapterError("That is not a request nexbeat could know.", code="bad_param")
        response = await ctx.request(
            "POST", f"{base_url(config)}/api/v1/admin/requests/{request_id}/{action_id}",
            json_body={}, headers=self._headers(config), verify=not config.get("insecure"),
            # ⚠️ Not turned into "the credentials were rejected". nexbeat answers
            # 403 for a read-only token and for an account that is no
            # administrator, and both say precisely that in their own words.
            auth_errors=False,
        )
        if response.status_code >= 400:
            raise AdapterError(self._refusal(response), code="rejected")
        if action_id == "reject":
            return "Turned down."
        # Approving hands the request on at once. When Lidarr or nexcrate
        # refuses it, nexbeat still answers 200, with the request failed.
        try:
            answer = response.json()
        except ValueError:
            answer = {}
        if isinstance(answer, dict) and answer.get("status") == "failed":
            return "Approved, but nexbeat could not hand it on. It is under Requests in nexbeat."
        return "Approved."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "approvals":
            rows = [
                {"id": 201, "kind": "album", "title": "Northern Lights", "artist_name": "The Quiet Harbour",
                 "album_type": "Album", "user": {"display_name": "Anna"}, "cover_url": ""},
                {"id": 202, "kind": "artist", "title": "Copper Sky", "user": {"display_name": "Ben"}, "cover_url": ""},
                {"id": 203, "kind": "album", "title": "Lanterns", "artist_name": "Harbour Lights",
                 "album_type": "EP", "user": {"display_name": "Anna"}, "cover_url": ""},
            ]
            waiting = len(rows) + (tick // 300) % 2
            items = [self._approval_row(row, "", True) for row in rows][: int(options.get("limit") or 8)]
            return WidgetData(
                status="warn",
                items=[item for item in items if item],
                secondary=[{"label": "Waiting", "value": waiting}],
                metrics={"waiting": float(waiting)},
                meta={"empty": "Nothing is waiting for approval.", "actions_visible": True},
            )
        if widget_kind == "requests":
            waiting = 2 + (tick // 120) % 4
            return self._requests_card({"requests": {"waiting": waiting, "running": 3, "failed": 0, "done_last_7_days": 11},
                                        "requests_enabled": True, "scope": "all"})
        return self._library_card({"library": {"artists": 412, "artists_with_music": 388, "albums": 2961}, "target": "lidarr"})


ADAPTER = NexbeatAdapter()
