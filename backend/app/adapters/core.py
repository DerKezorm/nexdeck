"""Widgets that need no service: clock, countdown, timer, notes, bookmarks, search, iframe."""

from __future__ import annotations

import datetime
import math
import re
from typing import Any

from ..services.upstream import UPSTREAM
from . import demo as fake
from .base import (
    Action,
    Adapter,
    AdapterError,
    Context,
    Field,
    WidgetData,
    WidgetType,
    duration_short,
    human_bytes,
    status_from_percent,
    worst,
)


class CoreAdapter(Adapter):
    kind = "core"
    label = "Basics"
    category = "basics"
    description = "Clock, notes, bookmarks and embedded pages. No connection needed."
    icon = "lucide:layout-dashboard"
    beta = False
    needs_integration = False

    def to_dict(self) -> dict[str, Any]:
        """The picker of the updates card also offers the own kinds whose description names a project on GitHub."""
        from . import REGISTRY

        found = super().to_dict()
        own = sorted(kind for kind, one in REGISTRY.items() if kind.startswith("custom:") and getattr(one, "upstream", ""))
        for widget in found["widgets"]:
            for option in widget["options"]:
                if widget["kind"] == "core.updates" and option["name"] == "picked":
                    option["options"] = [*option["options"], *({"value": kind, "label": ""} for kind in own)]
        return found

    widgets = (
        WidgetType(
            kind="clock",
            label="Clock",
            description="Time and date, optionally for another time zone.",
            renderer="clock",
            default_size=(3, 2),
            min_size=(2, 1),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("face", "Face", type="select", default="digits",
                      options=(("digits", "Digits"), ("hands", "Hands"))),
                Field("timezone", "Time zone", type="timezone", placeholder="Europe/Berlin", help="Empty means the browser's zone."),
                Field("format", "Format", type="select", default="24h", options=(("24h", "24-hour"), ("12h", "12-hour")),
                      only_when=("face", "digits")),
                Field("seconds", "Show seconds", type="bool", default=False),
                Field("date", "Show date", type="bool", default=True),
                Field("label", "Subtitle", placeholder="Home", help="A small line under the date, such as the place."),
                Field("colour", "Colour", type="colour", default="",
                      help="Empty takes the board's own. It applies to the digits and to the hands."),
            ),
        ),
        WidgetType(
            kind="countdown",
            label="Countdown",
            description="The days until a date, such as a holiday or a birthday, and the hours and minutes once it is close.",
            renderer="countdown",
            default_size=(3, 2),
            min_size=(2, 1),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("event", "What it counts to", placeholder="Holiday", help="Stands under the number: 12 days until Holiday."),
                Field("date", "Date", type="date", required=True),
                Field("time", "Time", type="time", help="Empty counts to the start of the day, and the card counts in days."),
                Field("yearly", "Every year", type="bool", default=False, help="For a birthday: once the day is past, it counts to the next one."),
                Field("show", "Shows", type="select", default="auto",
                      options=(("auto", "Days, and hours and minutes in the last two days"), ("days", "Days only"), ("all", "Days, hours and minutes"))),
                Field("after", "Once it is past", type="select", default="since",
                      options=(("since", "Count the days since"), ("here", "Say that it is here"))),
            ),
        ),
        WidgetType(
            kind="timer",
            label="Timer",
            description="A timer to start, pause and reset, such as a kitchen timer on a wall tablet. Each browser runs its own, and it rings or flashes when it is done.",
            renderer="timer",
            default_size=(3, 3),
            min_size=(2, 2),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("minutes", "Starts at (minutes)", type="number", default=10),
                Field("presets", "Quick picks (minutes)", default="3, 5, 10, 15, 30",
                      help="A button each, separated by commas. Empty leaves the row out."),
                Field("end", "When it is done", type="select", default="sound",
                      options=(("sound", "Ring and flash"), ("flash", "Flash only"))),
            ),
        ),
        WidgetType(
            kind="markdown",
            label="Notes",
            description="A card of text with Markdown formatting.",
            renderer="text",
            default_size=(3, 2),
            refresh_seconds=3600,
            client_only=True,
            options=(Field("content", "Text", type="textarea", default="Write something here.\n\n- lists\n- **bold**\n- [links](https://example.com)"),),
        ),
        WidgetType(
            kind="bookmarks",
            label="Bookmarks",
            description="A list of links with icons.",
            renderer="bookmarks",
            default_size=(3, 2),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field(
                    "links",
                    "Links",
                    type="textarea",
                    help="One per line: Title | URL | icon (optional, a service name like plex, or lucide:book for a drawn symbol).",
                    # ⚠️ book and activity are drawn symbols, not service
                    # logos. Written without the prefix they were looked up
                    # as logos, and every board answered two 404s per load.
                    default="Documentation | https://example.com/docs | lucide:book\nStatus page | https://example.com/status | lucide:activity",
                ),
                Field("layout", "Layout", type="select", default="list", options=(("list", "List"), ("grid", "Icon grid"))),
            ),
        ),
        WidgetType(
            kind="search",
            label="Search",
            description="A search field on the board, for the engines and services set up under Search.",
            renderer="search",
            # Two rows: the field, and the row of targets under it. With the
            # row switched off one row is enough, and two columns is still a
            # usable bar: a search field in a corner is a reasonable want.
            default_size=(4, 2),
            min_size=(2, 1),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("placeholder", "Placeholder", placeholder="Search", help="The grey text in the empty field."),
                Field("target", "Default target", placeholder="g", help="The shortcut of the target that Enter uses. Empty means the first one in the list."),
                Field("show_targets", "Show the other targets", type="bool", default=True, help="A row of buttons under the field, one per target. With a dozen targets a card two rows high is mostly buttons."),
                Field("show_shortcuts", "Show the shortcuts on the buttons", type="bool", default=True, help="The !x behind each name. Off makes the row narrower."),
                Field("new_tab", "Open in a new tab", type="bool", default=True),
                Field("autofocus", "Put the cursor in the field", type="bool", default=False, help="Only sensible once on a board, and it takes the keyboard from everything else."),
            ),
        ),
        WidgetType(
            kind="iframe",
            label="Embedded page",
            description="Shows another page inside the card. Many services forbid embedding.",
            renderer="iframe",
            default_size=(6, 4),
            min_size=(2, 2),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("url", "URL", type="url", required=True, placeholder="https://example.com"),
                Field("refresh", "Reload every (seconds)", type="number", default=0, help="0 means never."),
            ),
        ),
        WidgetType(
            kind="button",
            label="Button card",
            description="One button that leads to a board or an address. Its name and symbol are the card's own.",
            renderer="button",
            default_size=(2, 1),
            min_size=(1, 1),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("kind", "What it does", type="select", default="board",
                      options=(("board", "Open a board"), ("link", "Open an address"),
                               ("action", "Trigger an action"))),
                Field("board", "Which board", type="board", only_when=("kind", "board"),
                      help="A board, or one page of it."),
                Field("url", "Address", type="url", only_when=("kind", "link"),
                      placeholder="https://nas.example.com"),
                Field("new_tab", "Open in a new tab", type="bool", default=True, only_when=("kind", "link")),
                # ⚠️ Three lists, nothing typed. A library is "section 7" on
                # one server and an item id on the next, and a name written by
                # hand points at nothing the day it is renamed.
                Field("service", "Connection", type="integrations", default="",
                      only_when=("kind", "action"),
                      help="Only connections that offer something a button may trigger."),
                Field("deed", "Action", type="choices", from_field="service",
                      only_when=("kind", "action"),
                      help="Pick the connection first; what it offers appears here."),
                Field("target", "What it acts on", type="choices", from_field="service",
                      only_when=("kind", "action")),
                Field("confirm", "Ask before it runs", type="bool", default=False,
                      only_when=("kind", "action")),
                Field("look", "Look", type="select", default="label",
                      options=(("label", "Symbol and name"), ("icon", "Symbol only, large"), ("text", "Name only"))),
                Field("colour", "Colour", type="colour", default="",
                      help="Empty keeps the look of every other card."),
            ),
        ),
        WidgetType(
            kind="heading",
            label="Heading",
            description="A title across the page with an optional line, to split the cards into sections. With the line alone it is a divider.",
            renderer="heading",
            # The whole row and one row high: a heading stands above its group.
            # Narrower is allowed, for a heading over one column of cards.
            default_size=(12, 1),
            min_size=(1, 1),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("style", "What it shows", type="select", default="both",
                      options=(("both", "Title and line"), ("title", "Title only"), ("line", "Line only"))),
                Field("align", "Alignment", type="select", default="left",
                      options=(("left", "Left"), ("center", "Centred"))),
                Field("size", "Text size", type="select", default="normal",
                      options=(("small", "Small"), ("normal", "Normal"), ("large", "Large"))),
                Field("colour", "Colour", type="colour", default="",
                      help="Empty keeps the look of every other card."),
            ),
        ),
        WidgetType(
            kind="tabs",
            label="Tabs",
            description="Several cards in one, a tab each: more on a small screen, and a wall that turns the pages itself.",
            renderer="tabs",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("cards", "Cards in it", type="cards", default=[],
                      help="Cards of this page. They leave the board and live in this card until it is removed."),
                Field("turn", "Turn the tabs", type="select", default="0",
                      options=(("0", "By hand"), ("10", "Every 10 seconds"), ("20", "Every 20 seconds"), ("60", "Every minute"))),
            ),
        ),
        WidgetType(
            kind="group",
            label="Group",
            description="A titled box that holds cards side by side, folds away and moves as one.",
            renderer="group",
            default_size=(12, 3),
            min_size=(3, 2),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("cards", "Cards in it", type="cards", default=[],
                      help="Cards of this page. They leave the board and live in this box until it is removed."),
                Field("columns", "Cards side by side", type="select", default="auto",
                      options=(("auto", "As many as fit"), ("2", "Two"), ("3", "Three"), ("4", "Four"), ("6", "Six"))),
            ),
        ),
        WidgetType(
            kind="figures",
            label="Key figures",
            description="Numbers from several connections in one grid, each a tile with its value, unit and colour: the processor of the NAS beside the downloads and the blocked queries. Made for wall displays.",
            renderer="figures",
            default_size=(6, 3),
            min_size=(2, 2),
            refresh_seconds=3600,
            client_only=True,
            options=(
                # The picker offers the number cards of the page only.
                Field("cards", "Tiles", type="cards", default=[], helper="numbers",
                      help="Cards of this page that show a number. They leave the board and show here as tiles, each with its own settings, until they are dragged out or this card is removed."),
                Field("columns", "Grid", type="select", default="auto",
                      options=(("auto", "Automatic, as large as possible"), ("1", "One across"), ("2", "Two across"),
                               ("3", "Three across"), ("4", "Four across"), ("6", "Six across")),
                      help="Automatic works out the rows from the number of tiles and the shape of the card: a row on a wide card, a column on a tall one."),
                Field("tone", "Shows yellow and red as", type="select", default="fill",
                      options=(("fill", "A tinted tile"), ("border", "A coloured edge"), ("dot", "A dot in the corner"))),
                Field("history", "History behind the number", type="bool", default=False,
                      help="The last hours as a faint line, as the card itself records them."),
            ),
        ),
        WidgetType(
            kind="image",
            label="Picture",
            description="One picture, or a list of them as a slideshow.",
            renderer="image",
            default_size=(3, 2),
            min_size=(1, 1),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("pictures", "Pictures", type="pictures",
                      help="Upload files, or name an address. Both go in the same list."),
                Field("every", "Move on every (seconds)", type="number", default=8,
                      help="0 keeps the first picture. On a wall display, slower is better."),
                Field("fit", "Crop", type="select", default="cover",
                      options=(("cover", "Fill the card, edges cropped"), ("contain", "Whole picture, edges left free"))),
                Field("captions", "Show the captions", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="problems",
            label="Needs attention",
            description="What needs a look, from every board of this board's owner: cards that are yellow or red, services that do not answer and unread warnings from the bell. Otherwise it says that everything is fine.",
            renderer="attention",
            default_size=(4, 4),
            min_size=(2, 1),
            refresh_seconds=15,
            options=(
                # ⚠️ The boards of the owner, not of whoever looks. The card is
                # read once for everyone who sees it, like the status page.
                Field("scope", "From where", type="select", default="all",
                      options=(("all", "Every board of this board's owner"), ("board", "Only this board")),
                      help="The card is read once for everyone who sees it, so it shows what the owner of the board sees."),
                Field("bell", "Unread warnings from the bell", type="bool", default=True,
                      help="Warnings and errors the owner has not read yet. Plain news like a finished download is left out."),
                Field("updates", "Waiting updates as a quiet line", type="bool", default=True,
                      help="Updates never colour the card. They need Check for updates under System, About."),
                Field("opens", "Tapping a row opens", type="select", default="card",
                      options=(("card", "The card, on its board"), ("service", "The service"))),
            ),
        ),
        WidgetType(
            kind="status",
            label="Status page",
            description="Every card with a reachability check: how it answers, its bars and how much of the time it was up.",
            renderer="list",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=30,
            # The availability of each service side by side, for whoever wants the chart.
            bars=True,
            options=(
                Field("scope", "Which cards", type="select", default="board",
                      options=(("board", "The cards on this board"), ("owner", "Every board of this board's owner")),
                      help="Boards that belong to somebody else never show up here."),
                Field("bars", "Availability bars", type="select", default="24h",
                      options=(
                          ("30d", "Last 30 days, one bar per day"),
                          ("7d", "Last 7 days, one bar per 6 hours"),
                          ("24h", "Last 24 hours, one bar per 30 minutes"),
                          ("6h", "Last 6 hours, one bar per 7.5 minutes"),
                          ("1h", "Last hour, one bar per minute"),
                          ("live", "Last 48 checks, one bar each"),
                          ("none", "No bars"),
                      )),
                Field("only_down", "Only what is down", type="bool", default=False),
                # The same rows drawn as wide strips of bars, one service each: the look
                # of a public status page, and what reads from across a room.
                Field("look", "Look", type="select", default="rows",
                      options=(("rows", "Rows with small bars"), ("strips", "A wide strip of bars per service"))),
            ),
        ),
        WidgetType(
            kind="chronicle",
            label="What happened",
            description="The latest lines of the chronicle from every board of this board's owner: cards that turned yellow, red or green, outages, maintenance, new versions and containers that restarted.",
            renderer="chronicle",
            default_size=(4, 4),
            min_size=(2, 2),
            refresh_seconds=30,
            options=(
                Field("scope", "From where", type="select", default="all",
                      options=(("all", "Every board of this board's owner"), ("board", "Only this board")),
                      help="The card is read once for everyone who sees it, so it shows what the owner of the board sees."),
                Field("group", "Which lines", type="select", default="services",
                      options=(("services", "Cards, services and versions"), ("cards", "Cards and services"),
                               ("versions", "Versions and containers"), ("all", "Everything, changes in nexdeck too"))),
                Field("limit", "Entries", type="number", default=12),
            ),
        ),
        WidgetType(
            kind="report",
            label="Daily report",
            description="What happened in the last 24 hours and what is still red, from every board of this board's owner.",
            renderer="report",
            default_size=(4, 4),
            min_size=(3, 2),
            refresh_seconds=300,
            options=(
                Field("scope", "From where", type="select", default="all",
                      options=(("all", "Every board of this board's owner"), ("board", "Only this board")),
                      help="The card is read once for everyone who sees it, so it shows what the owner of the board sees."),
            ),
        ),
        WidgetType(
            kind="notices",
            label="Notices",
            description="The notices of this board's owner, for a wall where nobody opens the bell. Everyone who can see the board sees them.",
            renderer="list",
            default_size=(3, 3),
            min_size=(2, 2),
            refresh_seconds=30,
            options=(
                Field("level", "Which notices", type="select", default="all",
                      options=(("all", "All of them"), ("warn", "Warnings and errors"), ("error", "Errors only"))),
                Field("unread_only", "Only unread ones", type="bool", default=False),
                Field("limit", "Entries", type="number", default=8),
            ),
        ),
        WidgetType(
            kind="updates",
            label="Updates",
            description="One list of what has a newer version: your connected services, containers from What's Up Docker and Cup, a Watchtower run that failed, the projects you follow on GitHub, and nexdeck itself.",
            renderer="list",
            default_size=(4, 3),
            min_size=(2, 2),
            refresh_seconds=900,
            options=(
                Field("services", "Connected services", type="select", default="all",
                      help="The version each service says it runs, held against the newest release of its project on GitHub, looked at every six hours while Check for updates is on under System, About. A service that does not name its version, or whose project is not on GitHub, is left out here and listed under System, Integrations.",
                      options=(("all", "Every connection that names its version"), ("pick", "Only the ones picked"), ("none", "None"))),
                Field("picked", "Services", type="integrations", default=[], only_when=("services", "pick"),
                      # Kinds only, to narrow the picker; it shows the connections' own names.
                      options=tuple((kind, "") for kind in sorted(UPSTREAM))),
                Field("sources", "Container sources", type="integrations", default=[],
                      options=(("wud", "What's Up Docker"), ("cup", "Cup"), ("arcane", "Arcane"), ("dockhand", "Dockhand"), ("watchtower", "Watchtower")),
                      help="Watchtower updates by itself; it shows up only when its last run could not update everything."),
                Field("repos", "GitHub projects", type="textarea", placeholder="owner/name",
                      help="One per line, as owner/name, up to ten. Each shows its newest release; one from the last seven days stands out."),
                Field("nexdeck", "nexdeck itself", type="bool", default=True,
                      help="Through the update check in System. With that switched off, the card shows what a check by hand found and asks nothing itself."),
                Field("show_current", "Also show what is up to date", type="bool", default=False),
                Field("limit", "Entries", type="number", default=12),
            ),
        ),
        WidgetType(
            kind="host",
            label="This machine",
            description="Processor, memory, load, temperature and a disk of the machine nexdeck runs on, read from the kernel. No agent needed.",
            renderer="stats",
            default_size=(3, 3),
            min_size=(2, 2),
            refresh_seconds=15,
            metrics=("cpu", "memory"),
            options=(
                Field("disk", "File system", placeholder="/data",
                      help="A path whose file system the card shows. Empty means the one nexdeck keeps its data on, which in Docker is a volume of the host."),
                Field("temperature", "Show the temperature", type="bool", default=True),
            ),
        ),
        WidgetType(
            kind="app",
            label="App tile",
            description="A launcher tile: icon, name, link and an optional reachability check.",
            renderer="app",
            default_size=(2, 1),
            min_size=(1, 1),
            refresh_seconds=3600,
            client_only=True,
            options=(
                Field("description", "Description", placeholder="What this service does"),
                Field("look", "Display", type="select", default="row",
                      help="A big icon looks best on a square tile, two by two; a row on a wide one, three by one.",
                      options=(("row", "A row: icon, name and bars"), ("icon", "A big icon under the name"))),
                Field("corner", "Reachability shown as", type="select", default="dot", only_when=("look", "icon"),
                      options=(("dot", "A dot in the corner"), ("bars", "Availability bars along the bottom"))),
                Field("check", "Check reachability", type="bool", default=True),
                Field(
                    "bars",
                    "Availability bars",
                    type="select",
                    default="24h",
                    help="What the row of bars at the bottom of the tile shows.",
                    options=(
                        ("30d", "Last 30 days, one bar per day"),
                        ("7d", "Last 7 days, one bar per 6 hours"),
                        ("24h", "Last 24 hours, one bar per 30 minutes"),
                        ("6h", "Last 6 hours, one bar per 7.5 minutes"),
                        ("1h", "Last hour, one bar per minute"),
                        ("live", "Last 48 checks, one bar each"),
                    ),
                ),
                Field("open_new_tab", "Open in a new tab", type="bool", default=True),
                # One digit per board opens the tile from the keyboard (services/app_keys.py).
                Field("key", "Key", type="select", default="",
                      options=(("", "None"), *((digit, digit) for digit in "123456789")),
                      help="Pressing this digit on the board opens the tile, as a click would. Each key opens one tile of the board; ? shows the keys on the tiles."),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return "Nothing to test."

    async def action(self, widget_kind: str, action_id: str, params: dict[str, Any],
                     config: dict[str, Any], options: dict[str, Any], ctx: Context) -> str:
        """A button, pressed.

        ⚠️ Everything a card offers is checked against its last answer before
        this is reached, and for every other card that is enough: the answer
        came from the service. A button's answer comes from its own options,
        and those are written by whoever may edit the board. So the deed and
        its target are checked again here, against the target adapter's own
        declaration and its own list, which nobody editing a board can write.
        """
        if widget_kind != "button":
            return await super().action(widget_kind, action_id, params, config, options, ctx)
        if str(options.get("kind") or "") != "action":
            raise AdapterError("This button does not trigger anything.", code="no_such_action")
        if ctx.resolve_integration is None:
            raise AdapterError("The connection cannot be resolved here.", code="no_resolver")
        try:
            service = int(str(options.get("service") or "").strip())
        except ValueError:
            raise AdapterError(
                "This button has no connection picked.", code="no_integration",
                hint="Open the button settings and pick one.") from None

        adapter, service_config, service_ctx = await ctx.resolve_integration(service)
        deed = adapter.deed(action_id)
        if deed is None:
            raise AdapterError(f"{adapter.label} does not offer that.", code="no_such_action")

        call: dict[str, Any] = {}
        if deed.target_field:
            target = str(params.get("target") or options.get("target") or "")
            offered = {value for value, _label in await adapter.choices(deed.target_field, service_config, service_ctx)}
            # ⚠️ Against the service's own list, not against a pattern. A
            # target that is not on it either never existed or is gone, and
            # both are a reason to stop rather than to send it anyway.
            if target not in offered:
                raise AdapterError(
                    "That is not one of the things this connection offers.", code="no_such_target",
                    hint="Open the button settings and pick it again.")
            call[deed.target_field] = target
        return await adapter.action(deed.widget_kind, deed.id, call, service_config, {}, service_ctx)

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "problems":
            return await self._problems(ctx, options)
        if widget_kind == "status":
            return self._status(ctx, options)
        if widget_kind == "notices":
            return self._notices(ctx, options)
        if widget_kind == "chronicle":
            return self._chronicle(ctx, options)
        if widget_kind == "report":
            return self._report(ctx, options)
        if widget_kind == "updates":
            return await self._updates(ctx, options)
        if widget_kind == "host":
            return self._host(ctx, options)
        return self.demo(widget_kind, options, 0)

    @staticmethod
    def _host(ctx: Context, options: dict[str, Any]) -> WidgetData:
        """The machine nexdeck runs on, one look per refresh; the processor share is between two looks."""
        from ..config import get_settings
        from ..services import hoststats

        key = f"host:cpu:{ctx.widget_id}"
        disk = str(options.get("disk") or "").strip() or str(get_settings().data_dir.resolve())
        try:
            machine = hoststats.read(disk, ctx.cache.get(key))
        except hoststats.NoProc:
            raise AdapterError(
                "This machine has no /proc to read; the card reads Linux directly.", code="no_proc",
                hint="nexdeck in Docker runs on Linux. On Windows or macOS without Docker, Glances, Netdata or Beszel can read the machine.",
            ) from None
        ctx.cache[key] = machine.sample
        return host_card(machine, show_temperature=options.get("temperature", True))

    async def _updates(self, ctx: Context, options: dict[str, Any]) -> WidgetData:
        """What has a newer version, gathered from every source the card names.

        Each source is asked on its own: one that fails becomes a line above
        the rows, and the others still speak.
        """
        rows: list[dict[str, Any]] = []
        failures: list[str] = []
        sources = options.get("sources") or []
        if isinstance(sources, str):
            sources = [one for one in sources.split(",") if one.strip()]
        repos = [line.strip().strip("/") for line in str(options.get("repos") or "").splitlines() if line.strip()][:10]
        ask_nexdeck = options.get("nexdeck", True)
        services = str(options.get("services") or "all")
        show_current = bool(options.get("show_current"))
        if not sources and not repos and not ask_nexdeck and services == "none":
            raise AdapterError("Nothing is chosen to look at.", code="missing_sources",
                               hint="Open the card's settings and pick a source, a project or nexdeck itself.")
        if services != "none":
            rows.extend(await self._services(ctx, services, options.get("picked") or [], show_current))
        for source in sources:
            try:
                if ctx.resolve_integration is None:
                    raise AdapterError("Sources cannot be resolved here.", code="no_resolver")
                adapter, config, source_ctx = await ctx.resolve_integration(int(source))
                rows.extend(await waiting_at(adapter, config, source_ctx))
            except (AdapterError, ValueError, KeyError) as error:
                failures.append(str(getattr(error, "message", error)))
        if repos:
            rows.extend(await self._releases(repos, ctx, failures))
        if ask_nexdeck:
            mine = await nexdeck_row()
            if mine is not None:
                rows.append(mine)
        weight = {"bad": 0, "warn": 1}
        rows.sort(key=lambda row: (weight.get(str(row.get("status")), 2), str(row.get("title") or "").lower()))
        try:
            limit = max(1, min(50, int(options.get("limit") or 12)))
        except (TypeError, ValueError):
            limit = 12
        statuses = {row.get("status") for row in rows}
        return WidgetData(
            status="bad" if "bad" in statuses else "warn" if "warn" in statuses or failures else "ok",
            items=rows[:limit],
            error="; ".join(failures) if failures and not rows else None,
            meta={"empty": "Everything is up to date.", "notice": "; ".join(failures) if rows else ""},
        )

    @classmethod
    async def _services(cls, ctx: Context, services: str, picked: Any, show_current: bool) -> list[dict[str, Any]]:
        """A row for each connected service behind its project's newest release, or every one with ``show_current``.

        ⚠️ Never a connection reserved for administrators. The card is read once
        for everyone who sees it, and on a board an administrator shares with
        edit rights anybody may add one, so neither the viewer nor the owner
        decides this. Its version stands under System, Integrations.
        """
        import time

        from sqlalchemy import select

        from ..db import db_session
        from ..models import Integration
        from ..services import versions

        if ctx.resolve_integration is None:
            return []
        from ..routers import system

        wanted = {int(one) for one in picked if str(one).isdigit()} if services == "pick" else None
        with db_session() as db:
            # Without the operator's switch nothing newer is known, and so nothing is asked at all.
            if not system.update_check_on(db):
                return []
            found = [
                (one.id, one.kind, one.name)
                for one in db.scalars(select(Integration).where(Integration.enabled.is_(True), Integration.demo.is_(False)))
                if versions.repo_of(one.kind) and not one.admin_only and (wanted is None or one.id in wanted)
            ]
        readings = await versions.read_many([(number, kind) for number, kind, _name in found], ctx.resolve_integration, ctx)
        rows: list[dict[str, Any]] = []
        for number, _kind, name in found:
            reading = readings[number]
            if reading.state == "behind":
                fresh = bool(reading.published) and time.time() - reading.published < 7 * 86400
                rows.append({
                    "title": name,
                    "subtitle": " · ".join(part for part in (f"Runs {reading.running}", "major version" if versions.major_jump(reading.running, reading.newest) else "") if part),
                    "status": "warn",
                    "value": reading.newest,
                    "url": reading.url,
                    "emphasis": fresh,
                    # When the newer release came out: a day old is something else than a year.
                    **({"released": reading.published} if reading.published else {}),
                })
            elif reading.state == "current" and show_current:
                rows.append({"title": name, "subtitle": "Up to date", "status": "ok", "value": reading.running})
        return rows

    @staticmethod
    async def _releases(repos: list[str], ctx: Context, failures: list[str]) -> list[dict[str, Any]]:
        """The newest release of each project, one that came this week stands out."""
        import time

        from . import get_adapter

        github = get_adapter("github")
        rows: list[dict[str, Any]] = []
        for repo in repos:
            if repo.count("/") != 1:
                failures.append(f"{repo} is not owner/name.")
                continue
            try:
                release = await github.newest_release({}, ctx, repo)
            except AdapterError as error:
                failures.append(f"{repo}: {error.message}")
                continue
            if release is None:
                continue
            fresh = bool(release["published"]) and time.time() - release["published"] < 7 * 86400
            rows.append({
                "title": repo,
                "subtitle": " · ".join(("Newest release", "pre-release")) if release["prerelease"] else "Newest release",
                "status": "ok",
                "value": release["tag"],
                "url": release["url"],
                "emphasis": fresh,
            })
        return rows

    @staticmethod
    def _board_of(db, widget_id: int | None):  # noqa: ANN001, ANN205
        """The board a card stands on, or None for a card that is gone."""
        from ..models import Board, Page, Widget

        me = db.get(Widget, widget_id) if widget_id is not None else None
        page = db.get(Page, me.page_id) if me is not None else None
        return db.get(Board, page.board_id) if page is not None else None

    @classmethod
    def _status(cls, ctx: Context, options: dict[str, Any]) -> WidgetData:
        """The reachability checks of this board, or of every board its owner has.

        ⚠️ The owner's boards and no others. The card is read once for all
        who see it, a guest on a shared board included, so "every board"
        cannot mean the boards of the viewer; it means the boards of whoever
        put the card there, who chose to show them.
        """
        from sqlalchemy import select

        from ..db import db_session
        from ..models import Board, HealthCheck, Page, Widget
        from ..services import health

        window = str(options.get("bars") or "24h")
        drawn = window if window in health.BAR_WINDOWS or window == "live" else None
        nothing = WidgetData(status="unknown", items=[], meta={"empty": "No card here has a reachability check."})
        with db_session() as db:
            board = cls._board_of(db, ctx.widget_id)
            if board is None:
                return nothing
            boards = [board]
            if options.get("scope") == "owner" and board.owner_id is not None:
                boards = list(db.scalars(select(Board).where(Board.owner_id == board.owner_id).order_by(Board.name)))
            names = {one.id: one.name for one in boards}
            rows = db.execute(
                select(Widget.id, Widget.title, Page.board_id, HealthCheck.last_ok, HealthCheck.last_error, HealthCheck.last_latency_ms)
                .join(Page, Widget.page_id == Page.id)
                .join(HealthCheck, HealthCheck.widget_id == Widget.id)
                .where(Page.board_id.in_(list(names)), HealthCheck.enabled.is_(True))
            ).all()
            # The availability needs the bars even when none are drawn.
            bars = health.bars_for(db, {row.id: drawn or "24h" for row in rows})
        if not rows:
            return nothing
        items: list[dict[str, Any]] = []
        for row in rows:
            known = [bar for bar in bars.get(row.id, []) if bar is not None]
            if row.last_ok is False:
                status, said = "bad", row.last_error or "Down"
            elif row.last_ok is None:
                status, said = "unknown", row.last_error or "Not checked yet."
            else:
                status, said = "ok", f"{row.last_latency_ms} ms" if row.last_latency_ms is not None else ""
            title = row.title or "App tile"
            item: dict[str, Any] = {"title": f"{title} · {names[row.board_id]}" if len(names) > 1 else title, "subtitle": said, "status": status}
            if known:
                # ⚠️ Down to the whole per cent, never up: a card rounds anything
                # from 10 on to whole numbers, and 99.96 would have read 100
                # for a service that was gone for a while.
                item.update(value=math.floor(100 * sum(known) / len(known) + 1e-9), unit="%")
            if drawn:
                item["bars"] = bars.get(row.id, [])
            items.append(item)
        order = {"bad": 0, "unknown": 1, "ok": 2}
        items.sort(key=lambda item: (order[item["status"]], item["title"].lower()))
        down = sum(1 for item in items if item["status"] == "bad")
        if options.get("only_down"):
            items = [item for item in items if item["status"] == "bad"]
        return WidgetData(
            status="bad" if down else "ok",
            items=items,
            primary={"label": "Down", "value": down},
            meta={"empty": "Everything answers.", "bars": drawn or "", **cls._look(options, drawn)},
        )

    @staticmethod
    def _look(options: dict[str, Any], drawn: str | None) -> dict[str, Any]:
        """Strips, when asked for and when there are bars to draw them with."""
        return {"renderer": "strips"} if options.get("look") == "strips" and drawn else {}

    @classmethod
    def _notices(cls, ctx: Context, options: dict[str, Any]) -> WidgetData:
        """The notice centre of the board's owner, newest first.

        Notices belong to one account each. The card is read once for
        everyone who sees it, so it shows those of whoever owns the board,
        and it never marks one as read.
        """
        from sqlalchemy import func, select

        from ..db import db_session
        from ..models import Notice

        levels = {"warn": ("warn", "error", "bad"), "error": ("error", "bad")}.get(str(options.get("level") or "all"))
        try:
            limit = max(1, min(50, int(options.get("limit") or 8)))
        except (TypeError, ValueError):
            limit = 8
        with db_session() as db:
            board = cls._board_of(db, ctx.widget_id)
            if board is None or board.owner_id is None:
                return WidgetData(status="unknown", items=[], meta={"empty": "This board has no owner whose notices it could show."})
            query = select(Notice).where(Notice.user_id == board.owner_id)
            if levels:
                query = query.where(Notice.level.in_(levels))
            if options.get("unread_only"):
                query = query.where(Notice.read_at.is_(None))
            notices = list(db.scalars(query.order_by(Notice.created_at.desc(), Notice.id.desc()).limit(limit)))
            unread = db.scalar(select(func.count()).select_from(Notice).where(Notice.user_id == board.owner_id, Notice.read_at.is_(None))) or 0
            rows = [(n.title, n.body, n.level, n.link, n.created_at, n.read_at is None) for n in notices]
        weight = {"error": "bad", "bad": "bad", "warn": "warn"}
        items: list[dict[str, Any]] = []
        for title, body, level, link, created_at, is_unread in rows:
            item: dict[str, Any] = {"title": title, "subtitle": body, "status": weight.get(level, "ok"), "emphasis": is_unread}
            if created_at is not None:
                item["when"] = created_at.timestamp()
            if link:
                item["url"] = link
            items.append(item)
        loud = {item["status"] for item in items if item["emphasis"]}
        return WidgetData(
            status="bad" if "bad" in loud else "warn" if "warn" in loud else "ok",
            items=items,
            primary={"label": "Unread", "value": unread},
            meta={"empty": "No notices.", "headline": bool(unread)},
        )

    @classmethod
    async def _problems(cls, ctx: Context, options: dict[str, Any]) -> WidgetData:
        """What needs a look: yellow and red cards, failing checks, unread warnings.

        A yellow dot says that something is wrong; this card says what, where
        and since when. It reads the live state the collector already holds,
        the checks and the bell, so it costs no request of any service.

        ⚠️ From the boards of the board's owner, never of whoever looks: the
        card is read once for everyone who sees it (see ``_status``). A card
        in maintenance is left out and named on a quiet line instead, and so
        is another card of this kind, or two of them would list each other.
        """
        from sqlalchemy import select

        from ..db import db_session
        from ..models import Board, HealthCheck, Notice, Page, Widget
        from ..services import maintenance
        from ..services.boards import service_link
        from ..services.state import live

        fine = WidgetData(status="ok", items=[], meta={"empty": "Everything is fine"})
        if ctx.widget_id is None:
            return fine
        whole = options.get("scope", "all") != "board"
        with db_session() as db:
            board = cls._board_of(db, ctx.widget_id)
            if board is None:
                return fine
            boards = [board]
            if whole and board.owner_id is not None:
                boards = list(db.scalars(select(Board).where(Board.owner_id == board.owner_id).order_by(Board.position, Board.id)))
            board_of = {one.id: one for one in boards}
            pages = list(db.scalars(select(Page).where(Page.board_id.in_(list(board_of))).order_by(Page.position, Page.id)))
            page_of = {page.id: page for page in pages}
            widgets = [
                widget for widget in db.scalars(select(Widget).where(Widget.page_id.in_(list(page_of))))
                if widget.id != ctx.widget_id and widget.kind != "core.problems"
            ]
            away = maintenance.until_by_card(db, widgets)
            # ⚠️ The checks of the cards count as well. An app tile draws itself
            # in the browser and has no live state, so a failing check turned it
            # red and this card beside it said everything was fine (07.09.2026).
            checks = {
                check.widget_id: (check.last_ok, check.last_error, check.down_since)
                for check in db.scalars(select(HealthCheck).where(
                    HealthCheck.widget_id.in_([widget.id for widget in widgets]), HealthCheck.enabled.is_(True)))
            }
            several_pages = len(pages) > 1
            several_boards = len(boards) > 1
            # The row leads where the card itself leads: its own link, then the
            # one in its live state, then the service's (WidgetCard's order).
            rows = []
            quiet: dict[str, Any] = {}
            for widget in widgets:
                page = page_of[widget.page_id]
                home = board_of[page.board_id]
                if widget.id in away:
                    name = widget.integration.name if widget.integration is not None else (widget.title or "App tile")
                    quiet[name] = max(away[widget.id].ends_at, quiet.get(name, away[widget.id].ends_at))
                    continue
                where = home.name if several_boards else page.name if several_pages else ""
                # Whom "Why?" asks about (roadmap M6): the connection, or an app tile itself.
                # A card of nexdeck's own, such as a calendar, has no service to look into.
                subject = (f"integration:{widget.integration_id}" if widget.integration_id
                           else f"tile:{widget.id}" if widget.kind == "core.app" else "")
                rows.append((widget.id, widget.title or widget.kind, widget.icon, widget.link, service_link(widget), home, page, where, subject))
            notices = []
            if options.get("bell", True) and board.owner_id is not None:
                notices = [
                    (notice.id, notice.title, notice.body, notice.level, notice.link, notice.created_at)
                    for notice in db.scalars(
                        select(Notice).where(Notice.user_id == board.owner_id, Notice.read_at.is_(None),
                                             Notice.level.in_(("warn", "error", "bad")))
                        .order_by(Notice.created_at.desc(), Notice.id.desc()).limit(50))
                ]
            counted = {"cards": len(widgets), "checks": len(checks), "boards": len(boards)}
            owner = board.owner_id
        updates = await cls._services(ctx, "all", [], False) if options.get("updates", True) else []

        items: list[dict[str, Any]] = []
        for widget_id, title, icon, own, service, home, page, where, subject in rows:
            data = live.get(widget_id)
            last_ok, last_error, down_since = checks.get(widget_id, (None, "", None))
            item: dict[str, Any]
            since: float | None = live.since(widget_id)
            if data is not None and data.error:
                item = {"title": title, "subtitle": data.error, "error_code": str(data.meta.get("code") or ""), "status": "bad", "source": "card"}
            elif last_ok is False:
                item = {"title": title, "subtitle": last_error or "Error", "status": "bad", "source": "check"}
                since = down_since.timestamp() if down_since is not None else None
            elif data is None or data.status not in ("warn", "bad"):
                continue
            else:
                item = {"title": title, "status": data.status, "source": "card", **CoreAdapter._findings_of(data)}
            item.update(value=where, board=home.name, page=page.name, icon=icon,
                        target={"board": home.slug, "page": page.slug, "widget": widget_id})
            if subject:
                item["subject"] = subject
            if since is not None:
                item["since"] = since
            link = own or (data.link if data is not None else "") or service
            if link:
                item["url"] = link
            items.append(item)
        for number, title, body, level, link, created_at in notices:
            item = {"title": title, "subtitle": body, "status": "bad" if level in ("error", "bad") else "warn",
                    "source": "bell", "notice": number, "value": ""}
            if created_at is not None:
                item["since"] = created_at.timestamp()
            if link:
                item["url"] = link
            items.append(item)
        # Red before yellow, the newest first; what turned before anybody looked comes last.
        items.sort(key=lambda item: (item["status"] != "bad", -float(item.get("since") or 0), str(item["title"]).lower()))
        status = "bad" if any(item["status"] == "bad" for item in items) else ("warn" if items else "ok")
        return WidgetData(status=status, items=items, meta={
            "empty": "Everything is fine",
            "counted": counted,
            "owner": owner,
            "opens": "service" if options.get("opens") == "service" else "card",
            "updates": [{"title": row["title"], "value": row["value"]} for row in updates],
            "maintenance": [{"title": name, "until": until.isoformat()} for name, until in sorted(quiet.items())],
        })

    #: What each choice of the chronicle card shows.
    CHRONICLE_GROUPS = {
        "services": ("card", "outage", "recovery", "maintenance", "maintenance_end", "version", "container_restarted", "container_recreated"),
        "cards": ("card", "outage", "recovery", "maintenance", "maintenance_end"),
        "versions": ("version", "container_restarted", "container_recreated"),
    }

    @classmethod
    def _chronicle(cls, ctx: Context, options: dict[str, Any]) -> WidgetData:
        """The latest lines of the chronicle, as the board's owner sees them."""
        from ..db import db_session
        from ..services import chronicle

        group = str(options.get("group") or "services")
        kinds = cls.CHRONICLE_GROUPS.get(group) or tuple(chronicle.KINDS)
        try:
            limit = max(1, min(50, int(options.get("limit") or 12)))
        except (TypeError, ValueError):
            limit = 12
        if ctx.widget_id is None:
            return WidgetData(items=[], meta={"empty": "Nothing happened yet."})
        with db_session() as db:
            lines = chronicle.card_lines(db, ctx.widget_id, kinds=kinds, whole=options.get("scope", "all") != "board", limit=limit)
        return WidgetData(items=lines, meta={"empty": "Nothing happened yet."})

    @classmethod
    def _report(cls, ctx: Context, options: dict[str, Any]) -> WidgetData:
        """The last 24 hours and what is red now, for the boards of the owner (``report.summary``)."""
        from sqlalchemy import select

        from ..db import db_session
        from ..models import Board
        from ..services import report

        with db_session() as db:
            board = cls._board_of(db, ctx.widget_id)
            if board is None:
                return WidgetData(meta={"report": None})
            boards = {board.id}
            if options.get("scope", "all") != "board" and board.owner_id is not None:
                boards = set(db.scalars(select(Board.id).where(Board.owner_id == board.owner_id)))
            found = report.summary(db, boards=boards, owner_id=board.owner_id)
        return WidgetData(status="ok", meta={"report": found})

    #: How many of a card's own yellow or red rows the problems card names.
    FINDINGS_SHOWN = 2

    @staticmethod
    def _findings_of(data: WidgetData) -> dict[str, Any]:
        """The subtitle of a yellow or red card: its first red and yellow rows, else its reason.

        "Jellyfin findings: 0 error finding(s), 1 warning(s)" said that there
        was something, not what (issue #35). A card whose rows carry no status
        of their own keeps saying it the old way, by its reason.

        ``findings`` and ``more`` let the browser translate each part on its
        own; ``subtitle`` is the same in English, for anything that reads the
        API.
        """
        loud = [row for row in data.items if isinstance(row, dict) and row.get("status") in ("bad", "warn")]
        if not loud:
            reasons = [str(data.meta.get("status_reason") or ""), *(str(u) for u in (data.meta.get("urgent") or []))]
            return {"subtitle": " · ".join(r for r in reasons if r) or ("Error" if data.status == "bad" else "Warning")}
        # Red before yellow, each in the order the card has them.
        loud.sort(key=lambda row: row.get("status") != "bad")
        shown = loud[: CoreAdapter.FINDINGS_SHOWN]
        findings = [
            {"title": str(row.get("title") or ""), "subtitle": str(row.get("subtitle") or ""), "worded": bool(row.get("worded"))}
            for row in shown
        ]
        more = len(loud) - len(shown)
        parts = [f"{f['title']}: {f['subtitle']}" if f["title"] and f["subtitle"] else f["title"] or f["subtitle"] for f in findings]
        if more:
            parts.append(f"+{more} more")
        return {"subtitle": " · ".join(p for p in parts if p), "findings": findings, "more": more}

    def demo(self, widget_kind: str, options: dict[str, Any], tick: int) -> WidgetData:
        if widget_kind == "clock":
            return WidgetData(meta={
                "face": "hands" if options.get("face") == "hands" else "digits",
                "timezone": options.get("timezone") or "",
                "format": options.get("format") or "24h",
                "seconds": bool(options.get("seconds")),
                "date": options.get("date", True),
                "label": options.get("label") or "",
                "colour": str(options.get("colour") or ""),
            })
        if widget_kind == "countdown":
            return WidgetData(meta=countdown_meta(options))
        if widget_kind == "timer":
            return WidgetData(meta=timer_meta(options))
        if widget_kind == "markdown":
            return WidgetData(meta={"markdown": options.get("content") or ""})
        if widget_kind == "heading":
            # Drawn from the card's own options, so a change shows while the sheet is open.
            return WidgetData()
        if widget_kind in ("tabs", "group"):
            # A holder draws the data its cards already have; its own answer only
            # says what it is and how many it holds, which keeps it apart from a
            # heading that answers nothing.
            cards = options.get("cards") if isinstance(options.get("cards"), list) else []
            own = {"turn": str(options.get("turn") or "0")} if widget_kind == "tabs" else {"columns": str(options.get("columns") or "auto")}
            return WidgetData(meta={"holder": widget_kind, "holds": len(cards), **own})
        if widget_kind == "figures":
            cards = options.get("cards") if isinstance(options.get("cards"), list) else []
            columns = str(options.get("columns") or "auto")
            tone = str(options.get("tone") or "fill")
            return WidgetData(meta={
                "holder": "figures",
                "holds": len(cards),
                "columns": columns if columns in ("auto", "1", "2", "3", "4", "6") else "auto",
                "tone": tone if tone in ("fill", "border", "dot") else "fill",
                "history": bool(options.get("history")),
            })
        if widget_kind == "image":
            return WidgetData(items=parse_pictures(options.get("pictures")), meta={
                "every": max(0, int(options.get("every") or 0)),
                "fit": "contain" if options.get("fit") == "contain" else "cover",
                "captions": options.get("captions", True),
            })
        if widget_kind == "button":
            asked = str(options.get("kind") or "board")
            kind = asked if asked in ("link", "action") else "board"
            where = str((options.get("url") if kind == "link" else options.get("board")) or "").strip()
            data = WidgetData(meta={
                "kind": kind,
                "where": where,
                "new_tab": options.get("new_tab", True),
                "look": str(options.get("look") or "label"),
                "colour": str(options.get("colour") or ""),
            })
            if kind == "action":
                # ⚠️ The action goes into the card's own answer, which is what
                # the guard in the collector checks a press against. A button
                # that only knew its action from its options would be the one
                # card in nexdeck that can be asked for anything.
                deed_id = str(options.get("deed") or "")
                target = str(options.get("target") or "")
                if deed_id:
                    params = {"target": target} if target else {}
                    data.actions = [Action(id=deed_id, label=deed_id, icon="zap",
                                           confirm=bool(options.get("confirm")), params=params)]
                else:
                    data.status = "warn"
                    data.error = "This button has no action picked yet."
                data.meta["deed"] = deed_id
                data.meta["target"] = target
            return data
        if widget_kind == "bookmarks":
            return WidgetData(items=parse_links(options.get("links") or ""), meta={"layout": options.get("layout") or "list"})
        if widget_kind == "search":
            return WidgetData(meta={
                "placeholder": options.get("placeholder") or "",
                "target": options.get("target") or "",
                "show_targets": options.get("show_targets", True),
                "show_shortcuts": options.get("show_shortcuts", True),
                "new_tab": options.get("new_tab", True),
                "autofocus": bool(options.get("autofocus")),
            })
        if widget_kind == "iframe":
            return WidgetData(meta={"url": options.get("url") or "", "refresh": int(options.get("refresh") or 0)})
        if widget_kind == "problems":
            import time

            now = time.time()
            return WidgetData(
                status="bad",
                items=[
                    {"title": "Paperless", "subtitle": "The service could not be reached.", "error_code": "unreachable", "status": "bad",
                     "source": "check", "value": "Infrastructure", "board": "Infrastructure", "since": now - 12 * 60},
                    {"title": "Jellyfin", "status": "warn", "source": "card", "value": "Media", "board": "Media", "since": now - 40 * 60,
                     **self._findings_of(WidgetData(status="warn", items=[
                         {"title": "Jellyfin", "subtitle": "A restart is pending", "status": "warn"},
                         {"title": "Sign-in", "subtitle": "6 failed sign-ins in 24 h", "status": "warn"},
                         {"title": "Activity log", "subtitle": "2 error(s) in 24 h", "status": "warn"},
                     ]))},
                    {"title": "Backup failed", "subtitle": "Task Photos", "status": "warn", "source": "bell", "value": "", "since": now - 2 * 3600},
                    {"title": "Synology", "subtitle": "Volume 1 is 91 % full", "status": "warn", "source": "card", "value": "Infrastructure", "board": "Infrastructure"},
                ],
                meta={
                    "empty": "Everything is fine", "counted": {"cards": 31, "checks": 12, "boards": 3}, "owner": None,
                    "opens": "service" if options.get("opens") == "service" else "card",
                    "updates": [{"title": "Sonarr", "value": "4.0.16"}, {"title": "Immich", "value": "2.2.0"}] if options.get("updates", True) else [],
                    "maintenance": [],
                },
            )
        if widget_kind == "status":
            day = [1.0] * 40 + [0.5, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
            rows = [
                {"title": "Nextcloud", "subtitle": "The service could not be reached.", "error_code": "unreachable", "status": "bad", "value": 97, "unit": "%", "bars": day[:-1] + [0.0]},
                {"title": "Jellyfin", "subtitle": "41 ms", "status": "ok", "value": 100, "unit": "%", "bars": [1.0] * 48},
                {"title": "Radarr", "subtitle": "12 ms", "status": "ok", "value": 98, "unit": "%", "bars": day},
            ]
            if options.get("only_down"):
                rows = rows[:1]
            return WidgetData(status="bad", items=rows, primary={"label": "Down", "value": 1}, meta={"empty": "Everything answers.", "bars": "24h", **self._look(options, "24h")})
        if widget_kind == "chronicle":
            import time

            now = time.time()
            lines = [
                {"kind": "card", "level": "bad", "name": "Paperless", "before": "ok", "after": "bad", "detail": "The service could not be reached.", "board": "Infrastructure", "when": now - 14 * 60},
                {"kind": "version", "level": "info", "name": "Sonarr", "before": "4.0.15", "after": "4.0.16", "detail": "", "board": "", "when": now - 18 * 60},
                {"kind": "container_recreated", "level": "info", "name": "sonarr", "before": "lscr.io/linuxserver/sonarr:4.0.15", "after": "lscr.io/linuxserver/sonarr:4.0.16", "detail": "", "board": "Infrastructure", "when": now - 19 * 60},
                {"kind": "maintenance", "level": "info", "name": "Synology", "before": "", "after": "", "detail": "", "board": "", "when": now - 3 * 3600},
                {"kind": "outage", "level": "bad", "name": "Nextcloud", "before": "", "after": "", "detail": "ConnectError", "board": "Infrastructure", "when": now - 9 * 3600},
                {"kind": "recovery", "level": "ok", "name": "Nextcloud", "before": "", "after": "", "detail": "12 min", "board": "Infrastructure", "when": now - 9 * 3600 + 720},
            ]
            return WidgetData(items=lines[: int(options.get("limit") or 12)], meta={"empty": "Nothing happened yet."})
        if widget_kind == "report":
            return WidgetData(meta={"report": {
                "since": "", "outages": ["Nextcloud"], "red": ["Paperless"], "now_red": ["Paperless"],
                "versions": [{"name": "Sonarr", "before": "4.0.15", "after": "4.0.16"}], "containers": ["sonarr"], "restarted": [],
                "backups": ["Photos: the last good backup is too old"],
            }})
        if widget_kind == "notices":
            import time

            now = time.time()
            return WidgetData(status="warn", items=[
                {"title": "Nextcloud is down", "subtitle": "Nextcloud has not answered for 3 minutes (ConnectError).", "status": "bad", "emphasis": True, "when": now - 240},
                {"title": "nexdeck 0.20.0 is out", "subtitle": "", "status": "ok", "emphasis": True, "when": now - 3 * 3600},
                {"title": "Backup written", "subtitle": "", "status": "ok", "emphasis": False, "when": now - 26 * 3600},
            ], primary={"label": "Unread", "value": 2}, meta={"empty": "No notices.", "headline": True})
        if widget_kind == "host":
            from ..services.hoststats import Machine

            gib = 1024 ** 3
            machine = Machine(
                cpu=round(fake.walk("host-cpu", tick, 4, 38), 1), cores=8,
                memory_total=32 * gib, memory_used=int(fake.walk("host-memory", tick, 11, 14) * gib),
                load=(round(fake.walk("host-load", tick, 0.3, 2.4), 2), 0.9, 0.7), uptime=13 * 86400 + 4 * 3600,
                temperature=(round(fake.walk("host-temperature", tick, 44, 58), 1), "coretemp Package id 0"),
                disk_total=2000 * gib, disk_used=1240 * gib, disk_path="/data",
            )
            return host_card(machine, show_temperature=options.get("temperature", True))
        if widget_kind == "updates":
            return WidgetData(status="bad", items=[
                {"title": "Watchtower", "subtitle": "The last run could not update everything", "status": "bad", "value": "1"},
                {"title": "immich-server", "subtitle": " · ".join(("Major", "What's Up Docker")), "status": "warn", "value": "1.140.1 → 2.0.0"},
                {"title": "nexdeck", "subtitle": "New version", "status": "warn", "value": "0.19.3 → 0.20.0"},
                {"title": "ghcr.io/home-assistant/home-assistant", "subtitle": " · ".join(("Minor", "Cup")), "status": "ok", "value": "2026.9.1 → 2026.10.0"},
                {"title": "jellyfin/jellyfin", "subtitle": "Newest release", "status": "ok", "value": "v10.11.11", "emphasis": True},
            ], meta={"empty": "Everything is up to date.", "notice": ""})
        if widget_kind == "app":
            return WidgetData(meta={
                "description": options.get("description") or "",
                "check": options.get("check", True),
                "open_new_tab": options.get("open_new_tab", True),
            })
        raise KeyError(widget_kind)


def host_card(machine: Any, show_temperature: bool = True) -> WidgetData:
    """The rows of the host card from one look at the machine."""
    def share(used: int, total: int) -> float | None:
        return round(100 * used / total, 1) if total else None

    memory = share(machine.memory_used, machine.memory_total)
    disk = share(machine.disk_used, machine.disk_total)
    rows: list[dict[str, Any]] = []
    if memory is not None:
        rows.append({"label": "Memory", "value": memory, "unit": "%", "metric": "memory",
                     "hint": f"{human_bytes(machine.memory_used)} of {human_bytes(machine.memory_total)}"})
    if machine.swap_total:
        rows.append({"label": "Swap", "value": share(machine.swap_used, machine.swap_total), "unit": "%",
                     "hint": f"{human_bytes(machine.swap_used)} of {human_bytes(machine.swap_total)}"})
    if machine.load is not None:
        rows.append({"label": "Load", "value": " ".join(f"{one:.2f}" for one in machine.load),
                     "hint": f"{machine.cores} cores" if machine.cores else ""})
    if show_temperature and machine.temperature is not None:
        rows.append({"label": "Temperature", "value": machine.temperature[0], "unit": "°C", "hint": machine.temperature[1]})
    if disk is not None:
        rows.append({"label": "Disk", "value": disk, "unit": "%",
                     "hint": f"{human_bytes(machine.disk_total - machine.disk_used)} free of {human_bytes(machine.disk_total)} · {machine.disk_path}"})
    if machine.uptime is not None:
        rows.append({"label": "Uptime", "value": duration_short(machine.uptime)})
    metrics = {name: value for name, value in (("cpu", machine.cpu), ("memory", memory)) if value is not None}
    return WidgetData(
        status=status_from_percent(worst(machine.cpu, memory, disk)),
        primary={"label": "CPU", "value": machine.cpu, "unit": "%"},
        secondary=rows,
        metrics=metrics,
    )


async def waiting_at(adapter: Adapter, config: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
    """The rows a container source has waiting, read from its own card.

    What's Up Docker and Cup already list their updates; their rows come
    along without the ones they could not check and without buttons, which
    belong to the source's own card. Watchtower keeps no list of what waits,
    it updates by itself, so it has a row only when its last run failed.

    Arcane and Dockhand (issue #51) list the containers whose image has an
    update, as each last checked. ⚠️ An empty list from either can mean that
    nothing was checked yet; their own card says so, and so does a row here,
    instead of "Everything is up to date". The same for environments that did
    not answer.
    """
    if adapter.kind in ("wud", "cup"):
        data = await adapter.fetch("updates", config, {"limit": 50}, ctx)
        rows = []
        for row in data.items:
            if row.get("status") == "unknown":
                continue
            kept = {key: row[key] for key in ("title", "status", "value", "url") if key in row}
            kept["subtitle"] = " · ".join(part for part in (str(row.get("subtitle") or ""), adapter.label) if part)
            rows.append(kept)
        return rows
    if adapter.kind in ("arcane", "dockhand"):
        data = await adapter.fetch("updates", config, {}, ctx)
        rows = []
        for row in data.items:
            kept = {key: row[key] for key in ("title", "status", "value", "url", "icon", "icon_dot") if key in row}
            kept["subtitle"] = " · ".join(part for part in (str(row.get("subtitle") or ""), adapter.label) if part)
            rows.append(kept)
        meta = data.meta or {}
        if meta.get("notice"):
            rows.append({"title": adapter.label, "subtitle": str(meta["notice"]), "status": "warn"})
        if not data.items and data.status == "unknown":
            rows.append({"title": adapter.label, "subtitle": str(meta.get("empty") or ""), "status": "unknown"})
        return rows
    if adapter.kind == "watchtower":
        data = await adapter.fetch("summary", config, {}, ctx)
        failed = int((data.metrics or {}).get("failed") or 0)
        if not failed:
            return []
        return [{"title": adapter.label, "subtitle": "The last run could not update everything", "status": "bad", "value": str(failed)}]
    return []


async def nexdeck_row() -> dict[str, Any] | None:
    """nexdeck's own row when a newer version is known, through the switch in System."""
    from .. import __version__
    from ..db import db_session
    from ..routers import system

    with db_session() as db:
        allowed = system.update_check_on(db)
    newest = await system.known_latest_version(allowed)
    if not newest or not is_newer(newest, __version__):
        return None
    return {"title": "nexdeck", "subtitle": "New version", "status": "warn", "value": f"{__version__} → {newest}",
            "url": f"{system.REPO_URL}/releases"}


def is_newer(offered: str, running: str) -> bool:
    """0.20.0 over 0.19.3; a version that is not three numbers counts when it differs."""
    def parts(version: str) -> tuple[int, ...] | None:
        try:
            return tuple(int(piece) for piece in version.strip().lstrip("v").split("."))
        except ValueError:
            return None

    left, right = parts(offered), parts(running)
    if left is None or right is None:
        return offered.strip().lstrip("v") != running.strip().lstrip("v")
    return left > right


def parse_pictures(written: Any) -> list[dict[str, str]]:
    """The pictures of a card, however they were written down.

    The list the picker builds is ``[{"url": …, "caption": …}]``. ⚠️ The old
    shape, one line per picture with the caption after a pipe, is still read:
    a card made before the picker existed must not lose its pictures because
    the field it was filled in with was replaced.
    """
    pictures: list[dict[str, str]] = []
    if isinstance(written, list):
        for one in written:
            if not isinstance(one, dict):
                continue
            url = str(one.get("url") or "").strip()
            if url:
                pictures.append({"url": url, "title": str(one.get("caption") or one.get("title") or "").strip()})
        return pictures
    for line in str(written or "").splitlines():
        line = line.strip()
        if not line:
            continue
        url, _, caption = line.partition("|")
        url = url.strip()
        if url:
            pictures.append({"url": url, "title": caption.strip()})
    return pictures


#: A time of day as the time field writes it.
CLOCK_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
#: The longest a timer may run, and the most quick picks it shows.
LONGEST_TIMER_MINUTES = 24 * 60
MOST_PRESETS = 8


def countdown_meta(options: dict[str, Any]) -> dict[str, Any]:
    """What the countdown draws, each option checked once here.

    The browser counts, in its own time zone: a date means the start of
    that day where the screen is, which is what a holiday on a wall means.
    A date that is not one comes out empty, and the card asks for one.
    """
    raw_date = str(options.get("date") or "").strip()
    try:
        date = datetime.date.fromisoformat(raw_date).isoformat() if raw_date else ""
    except ValueError:
        date = ""
    raw_time = str(options.get("time") or "").strip()
    show = str(options.get("show") or "auto")
    after = str(options.get("after") or "since")
    return {
        "event": str(options.get("event") or "").strip()[:80],
        "date": date,
        "time": raw_time if CLOCK_TIME.match(raw_time) else "",
        "yearly": bool(options.get("yearly")),
        "show": show if show in ("auto", "days", "all") else "auto",
        "after": after if after in ("since", "here") else "since",
    }


def timer_meta(options: dict[str, Any]) -> dict[str, Any]:
    """What the timer offers: where it starts, its quick picks, and how it ends.

    Minutes, and parts of one (0.5 is thirty seconds); nothing under a
    second and nothing over a day. A quick pick that is no number is left
    out rather than refused: the row is a convenience.
    """
    def minutes(raw: Any) -> float | None:
        try:
            value = float(str(raw).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value * 60 < 1 or value > LONGEST_TIMER_MINUTES:
            return None
        return round(value, 2)

    presets: list[float] = []
    for part in re.split(r"[;,\s]+", str(options.get("presets") or "")):
        value = minutes(part) if part else None
        if value is not None and value not in presets:
            presets.append(value)
    start = minutes(options.get("minutes"))
    return {
        "minutes": start if start is not None else 10,
        "presets": presets[:MOST_PRESETS],
        "end": "flash" if options.get("end") == "flash" else "sound",
    }


def parse_links(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        title = parts[0]
        url = parts[1] if len(parts) > 1 else ""
        icon = parts[2] if len(parts) > 2 else ""
        if not url and title.startswith("http"):
            url, title = title, title
        items.append({"title": title, "url": url, "icon": icon})
    return items


ADAPTER = CoreAdapter()
