"""Kavita: the reading library.

Kavita hands out a JWT for a plugin key, which is what nexdeck is here: the
key comes from the account settings, the token is fetched once and kept until
it is refused.
"""

from __future__ import annotations

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
    base_url,
)


class KavitaAdapter(Adapter):
    kind = "kavita"
    label = "Kavita"
    category = "media"
    description = "Libraries, series and what was added last."
    icon = "kavita"
    docs_url = "https://wiki.kavitareader.com/guides/settings/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://kavita:5000"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="Account settings > 3rd Party Clients > API key."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="library",
            label="Library",
            description="Series and libraries in one number.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=600,
            metrics=("series",),
        ),
        WidgetType(
            kind="latest",
            label="Recently added",
            description="The series that arrived last.",
            renderer="list",
            default_size=(3, 3),
            refresh_seconds=600,
            options=(Field("limit", "Entries", type="number", default=6),),
        ),
    )

    async def _token(self, config: dict[str, Any], ctx: Context, force: bool = False) -> str:
        cached = ctx.cache.get("kavita_token")
        if cached and not force:
            return cached
        response = await ctx.request(
            "POST",
            f"{base_url(config)}/api/Plugin/authenticate",
            params={"apiKey": str(config.get("api_key") or ""), "pluginName": "nexdeck"},
            verify=not config.get("insecure"),
        )
        if response.status_code >= 400:
            raise AuthFailed("Kavita rejected the API key.")
        token = str((response.json() or {}).get("token") or "")
        if not token:
            raise AuthFailed("Kavita did not hand out a token.")
        ctx.cache["kavita_token"] = token
        return token

    async def _call(self, config: dict[str, Any], ctx: Context, method: str, path: str, body: Any = None, retry: bool = True) -> Any:
        token = await self._token(config, ctx)
        response = await ctx.request(
            method,
            f"{base_url(config)}/api{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json_body=body,
            verify=not config.get("insecure"),
        )
        if response.status_code in (401, 403) and retry:
            await self._token(config, ctx, force=True)
            return await self._call(config, ctx, method, path, body, retry=False)
        if response.status_code >= 400:
            raise AdapterError(f"Kavita answered with HTTP {response.status_code}.", code="http_error")
        try:
            return response.json()
        except ValueError:
            return None

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        libraries = await self._call(config, ctx, "GET", "/Library/libraries")
        return f"Kavita answers with {len(libraries) if isinstance(libraries, list) else 0} libraries."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "latest":
            limit = int(options.get("limit") or 6)
            payload = await self._call(config, ctx, "POST", f"/Series/recently-added-v2?PageNumber=1&PageSize={limit}", {})
            entries = payload if isinstance(payload, list) else (payload or {}).get("result") or []
            items = [
                {"title": entry.get("name") or entry.get("seriesName") or "?", "subtitle": entry.get("libraryName") or "", "status": "ok"}
                for entry in entries[:limit]
            ]
            return WidgetData(items=items, secondary=[{"label": "Entries", "value": len(items)}])

        libraries = await self._call(config, ctx, "GET", "/Library/libraries")
        count = len(libraries) if isinstance(libraries, list) else 0
        series = await self._call(config, ctx, "POST", "/Series/all-v2?PageNumber=1&PageSize=1", {})
        total = len(series) if isinstance(series, list) else 0
        return WidgetData(
            primary={"label": "Libraries", "value": count},
            secondary=[{"label": "Series", "value": total}],
            metrics={"series": float(total)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "latest":
            rows = [("The Iron Ferry", "Comics"), ("Harbour Tales", "Comics"), ("A History of Harbours", "Books")]
            return WidgetData(
                items=[{"title": title, "subtitle": library, "status": "ok"} for title, library in rows],
                secondary=[{"label": "Entries", "value": len(rows)}],
            )
        return WidgetData(
            primary={"label": "Libraries", "value": 3},
            secondary=[{"label": "Series", "value": fake.counter("kavita-series", tick, 184, 0.002)}],
            metrics={"series": 184.0},
        )


ADAPTER = KavitaAdapter()
