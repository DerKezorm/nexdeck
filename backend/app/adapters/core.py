"""Widgets that need no service: clock, notes, bookmarks, iframe."""

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
                Field("timezone", "Time zone", type="timezone", placeholder="Europe/Berlin", help="Empty means the browser's zone."),
                Field("format", "Format", type="select", default="24h", options=(("24h", "24-hour"), ("12h", "12-hour"))),
                Field("seconds", "Show seconds", type="bool", default=False),
                Field("date", "Show date", type="bool", default=True),
                Field("label", "Subtitle", placeholder="Home", help="A small line under the date, such as the place."),
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
                    help="One per line: Title | URL | icon (optional, a dashboard-icons name).",
                    default="Documentation | https://example.com/docs | book\nStatus page | https://example.com/status | activity",
                ),
                Field("layout", "Layout", type="select", default="list", options=(("list", "List"), ("grid", "Icon grid"))),
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
                "timezone": options.get("timezone") or "",
                "format": options.get("format") or "24h",
                "seconds": bool(options.get("seconds")),
                "date": options.get("date", True),
                "label": options.get("label") or "",
            })
        if widget_kind == "markdown":
            return WidgetData(meta={"markdown": options.get("content") or ""})
        if widget_kind == "bookmarks":
            return WidgetData(items=parse_links(options.get("links") or ""), meta={"layout": options.get("layout") or "list"})
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
