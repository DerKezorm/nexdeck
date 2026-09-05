"""Shared shape for media servers: what is playing, and how big the library is."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import demo as fake
from .base import Adapter, Context, Field, WidgetData, WidgetType, duration_short


@dataclass
class Stream:
    title: str
    subtitle: str
    user: str = ""
    progress: float = 0.0
    remaining_seconds: float | None = None
    paused: bool = False
    transcoding: bool = False
    art: str = ""


@dataclass
class MediaSnapshot:
    streams: list[Stream] = field(default_factory=list)
    bandwidth_kbps: float | None = None
    counts: dict[str, int] = field(default_factory=dict)


class MediaAdapter(Adapter):
    category = "media"
    widgets = (
        WidgetType(
            kind="nowplaying",
            label="Now playing",
            description="Current streams with user, device, quality and progress.",
            renderer="nowplaying",
            default_size=(4, 3),
            refresh_seconds=15,
            metrics=("streams",),
            options=(Field("limit", "Streams", type="number", default=6),),
        ),
        WidgetType(
            kind="library",
            label="Library",
            description="Movies, series and episodes in the library, plus active streams.",
            renderer="value",
            default_size=(2, 2),
            min_size=(1, 1),
            refresh_seconds=300,
            options=(
                Field("show", "Show", type="select", default="all", options=(("all", "Everything"), ("movies", "Movies"), ("series", "Series"), ("music", "Music"))),
                Field("style", "Style", type="select", default="number", options=(("number", "Big number with chips"), ("icons", "Icons with numbers")), help="The style applies when everything is shown."),
            ),
        ),
    )

    #: Which library counts a single-type view keeps, and the icon of each count.
    SHOW = {"movies": ("Movies",), "series": ("Series", "Episodes"), "music": ("Artists", "Albums", "Music", "Tracks")}
    ICONS = {"Movies": "lucide:film", "Series": "lucide:tv", "Episodes": "lucide:tv", "Artists": "lucide:speaker", "Albums": "lucide:speaker", "Music": "lucide:speaker", "Tracks": "lucide:speaker", "Photos": "lucide:image", "Playing": "lucide:play"}

    async def sessions(self, config: dict[str, Any], ctx: Context) -> list[Stream]:
        raise NotImplementedError

    async def counts(self, config: dict[str, Any], ctx: Context) -> dict[str, int]:
        raise NotImplementedError

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        streams = await self.sessions(config, ctx)
        if widget_kind == "library":
            counts = await self.counts(config, ctx)
            return self._library(streams, counts, options)
        return self._nowplaying(streams, options)

    def _nowplaying(self, streams: list[Stream], options: dict[str, Any]) -> WidgetData:
        limit = int(options.get("limit") or 6)
        transcoding = sum(1 for s in streams if s.transcoding)
        return WidgetData(
            status="ok",
            items=[{
                "title": s.title, "subtitle": s.subtitle, "progress": round(s.progress, 1),
                "remaining": duration_short(s.remaining_seconds) if s.remaining_seconds else "",
                "state": "paused" if s.paused else "playing", "art": s.art,
            } for s in streams[:limit]],
            secondary=[{"label": "Streams", "value": len(streams)}, {"label": "Transcoding", "value": transcoding}],
            metrics={"streams": float(len(streams))},
        )

    def _library(self, streams: list[Stream], counts: dict[str, int], options: dict[str, Any] | None = None) -> WidgetData:
        """The library card in one of three forms: one type big, everything as number and chips, or a row of icons."""
        options = options or {}
        show = str(options.get("show") or "all")
        if show in self.SHOW:
            kept = [(label, value) for label, value in counts.items() if label in self.SHOW[show]] or [(self.SHOW[show][0], 0)]
            first_label, first_value = kept[0]
            return WidgetData(
                primary={"label": first_label, "value": first_value},
                secondary=[{"label": label, "value": value} for label, value in kept[1:3]] + [{"label": "Playing", "value": len(streams)}],
            )
        if str(options.get("style") or "number") == "icons":
            items = [{"label": label, "value": value, "icon": self.ICONS.get(label, "lucide:box")} for label, value in list(counts.items())[:3]]
            items.append({"label": "Playing", "value": len(streams), "icon": self.ICONS["Playing"]})
            return WidgetData(items=items, meta={"renderer": "counters"})
        first_label, first_value = next(iter(counts.items()), ("Items", 0))
        secondary = [{"label": k, "value": v} for k, v in list(counts.items())[1:4]]
        secondary.append({"label": "Playing", "value": len(streams)})
        return WidgetData(primary={"label": first_label, "value": first_value}, secondary=secondary)

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        titles = [("The Quiet Harbour", "Living room · 4K · Direct play", "Alex"), ("Harbour Lights S03E04", "Bedroom TV · 1080p · Transcode", "Sam"), ("Orbital", "Phone · 720p", "Kim")]
        streams = []
        for index, (title, subtitle, user) in enumerate(titles):
            if index == 2 and fake.flicker(f"{self.kind}-third", tick, 0.5):
                continue
            progress = (fake.walk(f"{self.kind}-prog{index}", tick, 0, 100, period=500) + tick * 0.1) % 100
            streams.append(Stream(title=title, subtitle=subtitle, user=user, progress=progress,
                                  remaining_seconds=(100 - progress) * 60, paused=index == 2, transcoding=index == 1))
        if widget_kind == "library":
            return self._library(streams, {"Movies": 1284, "Series": 96, "Artists": 282}, options)
        return self._nowplaying(streams, options)
