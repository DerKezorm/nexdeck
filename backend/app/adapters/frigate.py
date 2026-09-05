"""Frigate: the cameras, what they detected and how the machine copes.

nexdeck has the deeper camera path with Reolink, but Frigate is the standard
answer to video surveillance in a homelab. The pictures of a detection come
through the server like every other service image, so no address of a camera
ever reaches the browser.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import demo as fake
from .base import (
    Adapter,
    Context,
    Field,
    WidgetData,
    WidgetType,
    base_url,
    human_bytes,
    status_from_percent,
)


class FrigateAdapter(Adapter):
    kind = "frigate"
    label = "Frigate"
    category = "monitoring"
    description = "Cameras with their frame rates, the latest detections and the load they cause."
    icon = "frigate"
    docs_url = "https://docs.frigate.video/integrations/api/"
    fields = (
        Field("url", "URL", type="url", required=True, placeholder="http://frigate:5000"),
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

    async def _get(self, config: dict[str, Any], ctx: Context, path: str, params: dict[str, Any] | None = None, cache: float = 15) -> Any:
        return await ctx.get_json(
            f"{base_url(config)}/api{path}",
            params=params,
            verify=not config.get("insecure"),
            cache_seconds=cache,
        )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        stats = await self._get(config, ctx, "/stats", cache=0)
        cameras = [name for name in (stats or {}) if name not in ("detectors", "service", "cpu_usages", "gpu_usages", "processes")]
        return f"Frigate answers with {len(cameras)} cameras."

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
        share = round(100.0 * used / total, 1) if total else 0.0
        return WidgetData(
            status=status_from_percent(share),
            primary={"label": "Cameras", "value": len(cameras)},
            secondary=[
                {"label": "Detections per second", "value": round(float((stats or {}).get("detection_fps") or 0), 1)},
                {"label": "Recordings", "value": human_bytes(used)},
                {"label": "Used", "value": f"{share} %"},
            ],
            metrics={"cameras": float(len(cameras)), "storage_percent": share},
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
                {"label": "Used", "value": f"{share} %"},
            ],
            metrics={"cameras": float(len(cameras)), "storage_percent": share},
        )


ADAPTER = FrigateAdapter()
