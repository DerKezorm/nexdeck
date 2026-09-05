"""Syncthing: are the folders in sync, and who is connected.

The API key is in Syncthing under Actions > Settings. Folder states are read
as they come: the documentation names four, the program emits more, so an
unknown one is shown rather than swallowed.

⚠️ ``/rest/db/status`` is expensive on the Syncthing side; the folder card
therefore asks slowly and the answers are cached.
"""

from __future__ import annotations

from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    duration_short,
    human_bytes,
    percent,
)

#: What a folder state means for the dot. Anything else stays unknown.
STATES = {"idle": "ok", "scanning": "warn", "syncing": "warn", "sync-preparing": "warn", "cleaning": "warn", "error": "bad"}


class SyncthingAdapter(Adapter):
    kind = "syncthing"
    label = "Syncthing"
    category = "nas"
    description = "Folders with their state, and the devices that are connected."
    icon = "syncthing"
    docs_url = "https://docs.syncthing.net/dev/rest.html"
    #: Seen against a live Syncthing 2.1.3 (05.09.2026).
    beta = False
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://syncthing:8384"),
        Field("api_key", "API key", type="password", secret=True, required=True, help="In Syncthing under Actions > Settings > General."),
        Field("insecure", "Ignore TLS errors", type="bool", default=False),
    )
    widgets = (
        WidgetType(
            kind="folders",
            label="Folders",
            description="One line per folder with its state and how much of it is there.",
            renderer="list",
            default_size=(4, 3),
            refresh_seconds=300,
            metrics=("folders", "errors"),
            options=(Field("limit", "Entries", type="number", default=8),),
        ),
        WidgetType(
            kind="status",
            label="Status",
            description="Connected devices, folders, uptime and the version.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=120,
            metrics=("connected", "folders"),
        ),
    )

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 60) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/rest{path}",
            headers={"X-API-Key": str(config.get("api_key") or "")},
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        version = await self._get(config, ctx, "/system/version", cache=0)
        return f"Syncthing {version.get('version', '?')} answers on {version.get('os', '?')}."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        folders = await self._get(config, ctx, "/config/folders", cache=600)
        folders = folders if isinstance(folders, list) else []

        if widget_kind == "status":
            status = await self._get(config, ctx, "/system/status", cache=120)
            connections = await self._get(config, ctx, "/system/connections", cache=120)
            version = await self._get(config, ctx, "/system/version", cache=3600)
            devices = (connections or {}).get("connections") or {}
            # The own device is in the list too, and it is always connected.
            mine = str((status or {}).get("myID") or "")
            others = {key: value for key, value in devices.items() if key != mine}
            connected = sum(1 for entry in others.values() if entry.get("connected"))
            return WidgetData(
                status="warn" if connected < len(others) else "ok",
                primary={"label": "Connected", "value": connected},
                secondary=[
                    {"label": "Devices", "value": len(others)},
                    {"label": "Folders", "value": len(folders)},
                    {"label": "Uptime", "value": duration_short(float((status or {}).get("uptime") or 0))},
                    {"label": "Version", "value": str((version or {}).get("version") or "?")},
                ],
                metrics={"connected": float(connected), "folders": float(len(folders))},
            )

        items = []
        errors = 0
        for folder in folders[: int(options.get("limit") or 8)]:
            folder_id = str(folder.get("id") or "")
            if not folder_id:
                continue
            state = await self._get(config, ctx, "/db/status", {"folder": folder_id}, cache=300)
            global_bytes = float((state or {}).get("globalBytes") or 0)
            local_bytes = float((state or {}).get("localBytes") or 0)
            share = percent(local_bytes, global_bytes) if global_bytes else 100.0
            word = str((state or {}).get("state") or "")
            pull_errors = int((state or {}).get("pullErrors") or 0)
            paused = bool(folder.get("paused"))
            if pull_errors or word == "error":
                errors += 1
            items.append({
                "title": str(folder.get("label") or folder_id),
                # The bare state word, so the interface can put it in German.
                "subtitle": word,
                "value": human_bytes(global_bytes),
                "progress": share,
                "status": "unknown" if paused else ("bad" if pull_errors or word == "error" else STATES.get(word, "unknown")),
            })
        return WidgetData(
            status="bad" if errors else "ok",
            items=items,
            secondary=[{"label": "Folders", "value": len(folders)}, {"label": "Errors", "value": errors}],
            metrics={"folders": float(len(folders)), "errors": float(errors)},
        )

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        broken = fake.flicker("syncthing-error", tick, 0.12)
        rows = [
            ("Documents", "idle", 41_000_000_000, 100.0),
            ("Photos", "syncing", 812_000_000_000, fake.walk("syncthing-photos", tick, 82, 100, period=400)),
            ("Backups", "error" if broken else "idle", 2_400_000_000_000, 96.0 if broken else 100.0),
            ("Music", "scanning", 128_000_000_000, 100.0),
        ]
        if widget_kind == "status":
            return WidgetData(
                status="ok",
                primary={"label": "Connected", "value": 3},
                secondary=[
                    {"label": "Devices", "value": 4},
                    {"label": "Folders", "value": len(rows)},
                    {"label": "Uptime", "value": "12d 6h"},
                    {"label": "Version", "value": "v2.1.0"},
                ],
                metrics={"connected": 3.0, "folders": float(len(rows))},
            )
        items = [
            {
                "title": name,
                "subtitle": state,
                "value": human_bytes(size),
                "progress": share,
                "status": "bad" if state == "error" else STATES.get(state, "unknown"),
            }
            for name, state, size, share in rows[: int(options.get("limit") or 8)]
        ]
        return WidgetData(
            status="bad" if broken else "ok",
            items=items,
            secondary=[{"label": "Folders", "value": len(rows)}, {"label": "Errors", "value": 1 if broken else 0}],
            metrics={"folders": float(len(rows)), "errors": 1.0 if broken else 0.0},
        )


ADAPTER = SyncthingAdapter()
