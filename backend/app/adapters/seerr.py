"""Seerr (and its ancestors Overseerr and Jellyseerr): media requests."""

from __future__ import annotations

from typing import Any

from .base import Adapter, AdapterError, Context, Detected, Field, WidgetData, WidgetType, base_url

STATUS_LABELS = {1: "pending", 2: "approved", 3: "declined"}


class SeerrAdapter(Adapter):
    kind = "seerr"
    #: Confirmed against a live instance on 2026-09-05.
    beta = False
    label = "Seerr"
    category = "media"
    description = "Open requests with approve as an action. Works with Overseerr and Jellyseerr too."
    icon = "seerr"
    docs_url = "https://docs.seerr.dev/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://seerr:5055"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Settings > General > API Key"),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="requests",
            label="Requests",
            description="Pending requests with who asked, and approve or decline.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=60,
            metrics=("pending",),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="counts",
            label="Request counts",
            description="Pending, approved and available, in one number.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=60,
            metrics=("pending",),
        ),
    )

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Api-Key": str(config.get("api_key") or "")}

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 10) -> Any:
        return await ctx.get_json(f"{base_url(config)}/api/v1{path}", headers=self._headers(config), params=params, verify=not config.get("insecure"), cache_seconds=cache)

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        status = await self._get(config, ctx, "/status", cache=0)
        return f"Seerr {status.get('version', '?')} answers."

    async def _title(self, config: dict[str, Any], ctx: Context, media: dict[str, Any]) -> str:
        tmdb = media.get("tmdbId")
        kind = media.get("mediaType", "movie")
        if not tmdb:
            return "?"
        key = f"seerr-title:{kind}:{tmdb}"
        cached = ctx.cache.get(key)
        if cached:
            return cached
        try:
            details = await self._get(config, ctx, f"/{kind}/{tmdb}", cache=3600)
        except AdapterError:
            return f"{kind} {tmdb}"
        title = details.get("title") or details.get("name") or f"{kind} {tmdb}"
        year = (details.get("releaseDate") or details.get("firstAirDate") or "")[:4]
        text = f"{title} ({year})" if year else title
        ctx.cache[key] = text
        return text

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        counts = await self._get(config, ctx, "/request/count", cache=30)
        pending = int(counts.get("pending") or 0)
        if widget_kind == "counts":
            return WidgetData(
                status="warn" if pending else "ok",
                primary={"label": "Pending", "value": pending},
                secondary=[{"label": "Approved", "value": counts.get("approved", 0)}, {"label": "Available", "value": counts.get("available", 0)}, {"label": "Total", "value": counts.get("total", 0)}],
                metrics={"pending": float(pending)},
            )
        limit = int(options.get("limit") or 8)
        payload = await self._get(config, ctx, "/request", params={"filter": "pending", "take": limit, "sort": "added"}, cache=30)
        items = []
        for request in payload.get("results") or []:
            media = request.get("media") or {}
            items.append({
                "id": request.get("id"),
                "title": await self._title(config, ctx, media),
                "subtitle": f"{(request.get('requestedBy') or {}).get('displayName', '?')} · {media.get('mediaType', '')}",
                "status": "warn",
                "actions": [
                    {"id": "approve", "label": "Approve", "icon": "check", "params": {"id": request.get("id")}},
                    {"id": "decline", "label": "Decline", "icon": "x", "confirm": True, "danger": True, "params": {"id": request.get("id")}},
                ],
            })
        return WidgetData(status="warn" if pending else "ok", items=items, secondary=[{"label": "Pending", "value": pending}], metrics={"pending": float(pending)})

    def detect(self, widget_kind: str, before: WidgetData | None, after: WidgetData,
               options: dict[str, Any]) -> list[Detected]:
        """A request that was not in the list a minute ago is a new one.

        ⚠️ By its number, not by the count. Somebody approving one while
        somebody else asks for another leaves the count unchanged, and a card
        that only watches the number would miss it entirely.

        ⚠️ And only when the list was read both times: an empty "before" is a
        card that was broken or is new, and announcing every pending request
        as fresh is a burst of noise at exactly the wrong moment.
        """
        if widget_kind != "requests" or before is None or before.error:
            return []
        seen = {str(item.get("id")) for item in before.items if item.get("id") is not None}
        if not seen:
            return []
        found = []
        for item in after.items:
            key = str(item.get("id"))
            if key in seen or item.get("id") is None:
                continue
            who = str(item.get("subtitle") or "").split(" · ")[0]
            found.append(Detected(
                event="request_new",
                title=f"{item.get('title') or 'Something'} was requested",
                body=f"Asked for by {who}." if who and who != "?" else "",
                key=f"request_new:{key}",
            ))
        return found[:5]

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any], config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if action_id not in ("approve", "decline"):
            raise AdapterError("Unknown action.", code="no_such_action")
        request_id = params.get("id")
        if not request_id:
            raise AdapterError("No request was named.", code="missing_param")
        response = await ctx.request("POST", f"{base_url(config)}/api/v1/request/{request_id}/{action_id}", headers=self._headers(config), verify=not config.get("insecure"))
        if response.status_code >= 400:
            raise AdapterError(f"Seerr answered with HTTP {response.status_code}.", code="http_error")
        return f"Request {action_id}d."

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        titles = ["The Quiet Harbour (2026)", "Northern Shore (2025)", "Copper Sky (2025)", "Signal Lost (2026)"]
        pending = 2 + (tick // 90) % 3
        if widget_kind == "counts":
            return WidgetData(status="warn", primary={"label": "Pending", "value": pending},
                              secondary=[{"label": "Approved", "value": 118}, {"label": "Available", "value": 104}, {"label": "Total", "value": 131}],
                              metrics={"pending": float(pending)})
        items = [{"id": i, "title": t, "subtitle": f"{['Alex', 'Sam', 'Kim', 'Robin'][i]} · {'tv' if i % 2 else 'movie'}", "status": "warn",
                  "actions": [{"id": "approve", "label": "Approve", "icon": "check", "params": {"id": i}}, {"id": "decline", "label": "Decline", "icon": "x", "confirm": True, "danger": True, "params": {"id": i}}]}
                 for i, t in enumerate(titles[:pending])]
        return WidgetData(status="warn", items=items, secondary=[{"label": "Pending", "value": pending}], metrics={"pending": float(pending)})


ADAPTER = SeerrAdapter()
