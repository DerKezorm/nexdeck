"""Widgets that need no service: clock, notes, bookmarks, search, iframe."""

from __future__ import annotations

from typing import Any

from .base import Adapter, Context, Field, WidgetData, WidgetType


class CoreAdapter(Adapter):
    kind = "core"
    label = "Basics"
    category = "basics"
    description = "Clock, notes, bookmarks and embedded pages. No connection needed."
    icon = "lucide:layout-dashboard"
    beta = False
    needs_integration = False
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
                      options=(("board", "Open a board"), ("link", "Open an address"))),
                Field("board", "Which board", type="board", only_when=("kind", "board"),
                      help="A board, or one page of it."),
                Field("url", "Address", type="url", only_when=("kind", "link"),
                      placeholder="https://nas.example.com"),
                Field("new_tab", "Open in a new tab", type="bool", default=True, only_when=("kind", "link")),
                Field("look", "Look", type="select", default="label",
                      options=(("label", "Symbol and name"), ("icon", "Symbol only, large"), ("text", "Name only"))),
                Field("colour", "Colour", type="colour", default="",
                      help="Empty keeps the look of every other card."),
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
            label="Problems",
            description="Every card on this board that is yellow or red, with its reason.",
            renderer="list",
            default_size=(3, 2),
            min_size=(2, 1),
            refresh_seconds=15,
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
                Field("check", "Check reachability", type="bool", default=True),
                Field(
                    "bars",
                    "Availability bars",
                    type="select",
                    default="24h",
                    help="What the row of bars at the bottom of the tile shows.",
                    options=(
                        ("24h", "Last 24 hours, one bar per 30 minutes"),
                        ("6h", "Last 6 hours, one bar per 7.5 minutes"),
                        ("1h", "Last hour, one bar per minute"),
                        ("live", "Last 48 checks, one bar each"),
                    ),
                ),
                Field("open_new_tab", "Open in a new tab", type="bool", default=True),
            ),
        ),
    )

    async def test(self, config: dict[str, Any], ctx: Context) -> str:
        return "Nothing to test."

    async def fetch(self, widget_kind: str, config: dict[str, Any], options: dict[str, Any], ctx: Context) -> WidgetData:
        if widget_kind == "problems":
            return self._problems(ctx)
        return self.demo(widget_kind, options, 0)

    @staticmethod
    def _problems(ctx: Context) -> WidgetData:
        """Every other card of the same board that is yellow, red or failing, with its reason.

        A yellow dot says that something is wrong; this card says what. It reads
        the live state the collector already holds, so it costs no request.
        """
        from sqlalchemy import select

        from ..db import db_session
        from ..models import Page, Widget
        from ..services.state import live

        fine = WidgetData(status="ok", items=[], meta={"empty": "Everything is fine"})
        if ctx.widget_id is None:
            return fine
        with db_session() as db:
            me = db.get(Widget, ctx.widget_id)
            page = db.get(Page, me.page_id) if me is not None else None
            if me is None or page is None:
                return fine
            pages = list(db.scalars(select(Page).where(Page.board_id == page.board_id).order_by(Page.position)))
            rows = [
                (other.name, widget.id, widget.title or widget.kind)
                for other in pages
                for widget in db.scalars(select(Widget).where(Widget.page_id == other.id))
                if widget.id != me.id
            ]
            several_pages = len(pages) > 1
        items: list[dict[str, Any]] = []
        for page_name, widget_id, title in rows:
            data = live.get(widget_id)
            if data is None:
                continue
            where = page_name if several_pages else ""
            if data.error:
                items.append({"title": title, "subtitle": data.error, "error_code": str(data.meta.get("code") or ""), "status": "bad", "value": where})
            elif data.status in ("warn", "bad"):
                reasons = [str(data.meta.get("status_reason") or ""), *(str(u) for u in (data.meta.get("urgent") or []))]
                subtitle = " · ".join(r for r in reasons if r) or ("Error" if data.status == "bad" else "Warning")
                items.append({"title": title, "subtitle": subtitle, "status": data.status, "value": where})
        items.sort(key=lambda item: (item["status"] != "bad", item["title"].lower()))
        status = "bad" if any(item["status"] == "bad" for item in items) else ("warn" if items else "ok")
        return WidgetData(status=status, items=items, meta={"empty": "Everything is fine"})

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
        if widget_kind == "markdown":
            return WidgetData(meta={"markdown": options.get("content") or ""})
        if widget_kind == "image":
            return WidgetData(items=parse_pictures(options.get("pictures")), meta={
                "every": max(0, int(options.get("every") or 0)),
                "fit": "contain" if options.get("fit") == "contain" else "cover",
                "captions": options.get("captions", True),
            })
        if widget_kind == "button":
            kind = "link" if options.get("kind") == "link" else "board"
            where = str((options.get("url") if kind == "link" else options.get("board")) or "").strip()
            return WidgetData(meta={
                "kind": kind,
                "where": where,
                "new_tab": options.get("new_tab", True),
                "look": str(options.get("look") or "label"),
                "colour": str(options.get("colour") or ""),
            })
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
            return WidgetData(
                status="bad",
                items=[
                    {"title": "Radarr", "subtitle": "The service could not be reached.", "error_code": "unreachable", "status": "bad", "value": ""},
                    {"title": "UniFi Network", "subtitle": "1 device(s) offline", "status": "warn", "value": ""},
                ],
                meta={"empty": "Everything is fine"},
            )
        if widget_kind == "app":
            return WidgetData(meta={
                "description": options.get("description") or "",
                "check": options.get("check", True),
                "open_new_tab": options.get("open_new_tab", True),
            })
        raise KeyError(widget_kind)


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
