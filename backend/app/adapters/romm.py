"""RomM: how many games each platform holds, and what came in last.

Measured against RomM 5.2.0 on 11.09.2026, with four ROM files on three
platforms, a client token with ``roms.read`` and ``platforms.read``, and a
library scan.

⚠️ A token RomM does not know gets 500 Internal Server Error, not 401. Only a
wrong password over basic authentication gets 401, and a known token without
the scope 403.

⚠️ ``/api/stats`` answers without any token.

⚠️ A scan cannot be started over the REST API: ``/api/tasks/run/scan_library``
answered "Task 'scan_library' cannot be run". The web interface starts it over
its socket, and a scheduled rescan runs it too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

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
    human_bytes,
)


class RommAdapter(Adapter):
    kind = "romm"
    label = "RomM"
    category = "media"
    description = "How many games each platform holds, and what came in last."
    icon = "romm"
    beta = False
    docs_url = "https://docs.romm.app/latest/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://romm:8080"),
        Field("token", "Client API token", type="password", secret=True, required=True,
              help="A client API token with the scopes roms.read and platforms.read."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(kind="platforms", label="Platforms", description="Every platform with its number of games, the biggest first.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("limit", "Entries", type="number", default=10),)),
        WidgetType(kind="recent", label="Recently added games", description="The games that came into the library last.",
                   renderer="list", default_size=(3, 3), refresh_seconds=900,
                   options=(Field("limit", "Entries", type="number", default=8),)),
        WidgetType(kind="summary", label="Game library", description="Games, platforms and the size of the library.",
                   renderer="value", default_size=(3, 2), refresh_seconds=900, metrics=("games",)),
    )

    async def _json(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.request(
            "GET", f"{base_url(config)}/api{path}", headers={"Authorization": f"Bearer {config.get('token') or ''}"},
            params=params, verify=not config.get("insecure"), cache_seconds=30, auth_errors=False,
        )
        if response.status_code == 401:
            raise AuthFailed("RomM wants a client API token.")
        if response.status_code == 403:
            raise AuthFailed("RomM refused the token. It needs the scopes roms.read and platforms.read.")
        if response.status_code == 500:
            raise AdapterError("RomM answered with HTTP 500, which is also its answer to a token it does not know.", code="http_error",
                               hint="Check the token first.")
        if response.status_code >= 400:
            raise AdapterError(f"RomM answered with HTTP {response.status_code}.", code="http_error",
                               hint="Check the URL; it is the address of RomM itself, without /api.")
        try:
            return response.json()
        except ValueError as error:
            raise AdapterError("RomM did not answer with JSON.", code="not_json",
                               hint="The URL probably points at something else than RomM.") from error

    async def _platforms(self, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
        platforms = await self._json(config, ctx, "/platforms")
        if not isinstance(platforms, list):
            raise AdapterError("This address answers, but not the way RomM does.", code="not_romm")
        return [one for one in platforms if isinstance(one, dict)]

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        heartbeat = await self._json(config, ctx, "/heartbeat")
        version = ((heartbeat.get("SYSTEM") or {}).get("VERSION") if isinstance(heartbeat, dict) else None) or "?"
        platforms = await self._platforms(config, ctx)
        return f"RomM {version} answers with {len(platforms)} platforms."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "summary":
            stats = await self._json(config, ctx, "/stats")
            if not isinstance(stats, dict) or "ROMS" not in stats:
                raise AdapterError("This address answers, but not the way RomM does.", code="not_romm")
            return self._summary(stats)
        if widget_kind == "recent":
            limit = max(1, int(options.get("limit") or 8))
            page = await self._json(config, ctx, "/roms", {"order_by": "created_at", "order_dir": "desc", "limit": limit})
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise AdapterError("This address answers, but not the way RomM does.", code="not_romm")
            return self._recent(page["items"])
        return self._platform_list(await self._platforms(config, ctx), options)

    # -- the cards -----------------------------------------------------------

    @staticmethod
    def _platform_list(platforms: list[dict[str, Any]], options: dict[str, Any]) -> WidgetData:
        ranked = sorted(platforms, key=lambda one: (-int(one.get("rom_count") or 0), str(one.get("display_name") or one.get("name") or "")))
        items = [{
            "title": str(one.get("custom_name") or one.get("display_name") or one.get("name") or one.get("fs_slug") or "?"),
            "subtitle": human_bytes(one.get("fs_size_bytes")) if one.get("fs_size_bytes") else "",
            "status": "ok",
            "value": str(int(one.get("rom_count") or 0)),
        } for one in ranked[: int(options.get("limit") or 10)]]
        return WidgetData(
            status="ok",
            items=items,
            secondary=[{"label": "Games", "value": sum(int(one.get("rom_count") or 0) for one in platforms)}],
            meta={"empty": "No platforms yet. RomM finds them in the library folder when it scans."},
        )

    @staticmethod
    def _recent(roms: list[Any]) -> WidgetData:
        items = [{
            "title": str(rom.get("name") or rom.get("fs_name") or "?"),
            "subtitle": str(rom.get("platform_custom_name") or rom.get("platform_display_name") or ""),
            "value": ago(rom.get("created_at")),
        } for rom in roms if isinstance(rom, dict)]
        return WidgetData(status="ok", items=items, meta={"empty": "No games yet."})

    @staticmethod
    def _summary(stats: dict[str, Any]) -> WidgetData:
        games = int(stats.get("ROMS") or 0)
        secondary: list[dict[str, Any]] = [{"label": "Platforms", "value": int(stats.get("PLATFORMS") or 0)}]
        if stats.get("TOTAL_FILESIZE_BYTES"):
            secondary.append({"label": "Size", "value": human_bytes(stats.get("TOTAL_FILESIZE_BYTES"))})
        if stats.get("SAVES"):
            secondary.append({"label": "Saves", "value": int(stats["SAVES"])})
        return WidgetData(
            status="ok",
            primary={"label": "Games", "value": games},
            secondary=secondary,
            metrics={"games": float(games)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "summary":
            return self._summary({"ROMS": 1_284 + tick % 3, "PLATFORMS": 14, "SAVES": 37, "TOTAL_FILESIZE_BYTES": 412_000_000_000})
        if widget_kind == "recent":
            def added(hours: float) -> str:
                return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

            return self._recent([
                {"name": "Castle Quest", "platform_display_name": "Super Nintendo Entertainment System", "created_at": added(3)},
                {"name": "Kart Rally", "platform_display_name": "Nintendo 64", "created_at": added(26)},
                {"name": "Pocket Racer", "platform_display_name": "Game Boy Advance", "created_at": added(50)},
            ])
        return self._platform_list([
            {"display_name": "Super Nintendo Entertainment System", "rom_count": 412, "fs_size_bytes": 1_900_000_000},
            {"display_name": "Game Boy Advance", "rom_count": 388, "fs_size_bytes": 5_800_000_000},
            {"display_name": "PlayStation", "rom_count": 96, "fs_size_bytes": 71_000_000_000},
        ], options)


ADAPTER = RommAdapter()
