"""Shared shape for media servers: what is playing, and how big the library is."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Deed,
    Field,
    WidgetData,
    WidgetType,
    duration_short,
)


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


@dataclass
class Library:
    """One library of a media server, as the card and the rescan need it."""

    id: str
    name: str
    #: What kind of thing is in it, in the service's own word ("movie", "show").
    kind: str = ""
    #: How many items, when the service says so without another request per
    #: library. ``None`` means unknown, and the card says so rather than 0.
    count: int | None = None
    #: True while the service is reading the library. Jellyfin and Emby say
    #: so in the same answer that lists the libraries; Plex does not.
    scanning: bool = False
    #: How far along, when the service reports it.
    progress: float | None = None


#: The target that means "every library". A value, not an empty string: an
#: option nobody filled in must not silently become "do it to everything".
EVERYTHING = "all"


class MediaAdapter(Adapter):
    category = "media"
    #: The one thing a button may ask a media server to do. Reading is free;
    #: this is the only action, and it looks for files without touching what
    #: is already there.
    deeds = (Deed(widget_kind="libraries", id="rescan", label="Scan a library",
                  target_field="library", target_label="Library", icon="refresh-cw"),)
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
        WidgetType(
            kind="libraries",
            label="Libraries",
            description="One row per library, with a button that looks for new files.",
            renderer="list",
            default_size=(3, 2),
            refresh_seconds=120,
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
        # ⚠️ Before the streams are asked for: the library card does not need
        # them, and asking a media server what is playing costs a request that
        # this card would throw away.
        if widget_kind == "libraries":
            return self._libraries(await self.library_list(config, ctx))
        streams = await self.sessions(config, ctx)
        if widget_kind == "library":
            counts = await self.counts(config, ctx)
            return self._library(streams, counts, options)
        return self._nowplaying(streams, options)

    # -- the libraries, and looking for new files in one -----------------------

    async def library_list(self, config: dict[str, Any], ctx: Context) -> list[Library]:
        """Every library, with whatever the service says about it in one call."""
        raise NotImplementedError

    #: Whether one library alone can be told to look for new files.
    #:
    #: ⚠️ Measured, not assumed. Plex scans one section and says so in its
    #: activity list two seconds later. Jellyfin and Emby answer 204 to
    #: ``POST /Items/{id}/Refresh`` and then do nothing at all: the scan task
    #: does not run, ``RefreshStatus`` never moves, and adding
    #: ``metadataRefreshMode=ValidationOnly`` changes neither. Only
    #: ``POST /Library/Refresh``, which reads everything, actually runs.
    #: Measured on 08.09.2026 against live instances of all three.
    #:
    #: So the card offers per library only where per library works. A button
    #: labelled "Films" that quietly reads every library would be worse than
    #: no button.
    can_scan_one = True

    async def rescan(self, config: dict[str, Any], target: str, ctx: Context) -> str:
        """Ask the service to look for new files. ``target`` is a library id or
        :data:`EVERYTHING`."""
        raise NotImplementedError

    def _libraries(self, rows: list[Library]) -> WidgetData:
        items = [{
            "id": one.id,
            "title": one.name,
            "subtitle": self._scan_line(one),
            # ⚠️ A library being read is not a fault. "unknown" is the colour
            # for "something is going on", and a scan is exactly that.
            "status": "unknown" if one.scanning else "ok",
            #: Unknown, not nought: a service that does not count without a
            #: request per library would otherwise report an empty shelf.
            "value": one.count if one.count is not None else "",
            "progress": one.progress if one.scanning and one.progress is not None else None,
            "actions": ([Action(id="rescan", label="Scan", icon="refresh-cw",
                                params={"library": one.id})] if self.can_scan_one else []),
        } for one in rows]
        return WidgetData(
            items=items,
            secondary=[{"label": "Libraries", "value": len(rows)},
                       {"label": "Scanning", "value": sum(1 for one in rows if one.scanning)}],
            actions=[Action(id="rescan", label="Scan all", icon="refresh-cw",
                            params={"library": EVERYTHING})],
            metrics={"scanning": float(sum(1 for one in rows if one.scanning))},
            meta={"empty": "No libraries"},
        )

    def _scan_line(self, one: Library) -> str:
        if one.scanning:
            return "Scanning" + (f" · {one.progress:.0f}%" if one.progress is not None else "")
        return one.kind

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        if widget_kind != "libraries" or action_id != "rescan":
            return await super().action(widget_kind, action_id, params, config, options, ctx)
        target = str(params.get("library") or EVERYTHING)
        if target != EVERYTHING and not self.can_scan_one:
            raise AdapterError(
                f"{self.label} cannot read one library on its own.", code="whole_library_only",
                hint="It only offers a scan of everything, so that is what the card offers.")
        return await self.rescan(config, target, ctx)

    async def choices(self, field: str, config: dict[str, Any], ctx: Context) -> list[tuple[str, str]]:
        """The libraries, for a field that has to name one.

        ⚠️ The id, not the name. A library renamed to "4K & HDR" keeps its id,
        and a card that stored the name would quietly point at nothing; that
        shows up on the day a film is missing, not on the day of the rename.
        """
        if field != "library":
            return await super().choices(field, config, ctx)
        if not self.can_scan_one:
            # Nothing else is offered, because nothing else works. A list that
            # named four libraries and then read all of them would be a
            # button that lies about what it does.
            return [(EVERYTHING, "All libraries")]
        rows = await self.library_list(config, ctx)
        return [(one.id, one.name) for one in rows] + [(EVERYTHING, "All libraries")]

    def demo_choices(self, field: str) -> list[tuple[str, str]]:
        """Out of the demo card, so the two can never say different things."""
        if field not in ("library", "target"):
            return super().demo_choices(field)
        rows = self.demo("libraries", {}, 0).items
        pairs = [] if not self.can_scan_one else [(str(one["id"]), str(one["title"])) for one in rows]
        return pairs + [(EVERYTHING, "All libraries")]

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
        # ⚠️ Before the streams are invented. Until this line existed, the
        # libraries card fell through to "now playing" and showed two films
        # where its rows belong: believable, wrong, and invisible to a test
        # that only asks whether the demo threw.
        if widget_kind == "libraries":
            scanning = fake.flicker(f"{self.kind}-scan", tick, 0.35)
            return self._libraries([
                Library(id="7", name="4K films", kind="movie", count=214,
                        scanning=scanning, progress=fake.walk(f"{self.kind}-scanp", tick, 5, 95) if scanning else None),
                Library(id="1", name="Films", kind="movie", count=1284),
                Library(id="2", name="Series", kind="show", count=96),
                Library(id="5", name="Music", kind="artist", count=282),
            ])
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
