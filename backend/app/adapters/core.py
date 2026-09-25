"""Widgets that need no service: clock, notes, bookmarks, search, iframe."""

from __future__ import annotations

import math
from typing import Any

from .base import Action, Adapter, AdapterError, Context, Field, WidgetData, WidgetType


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
                          ("24h", "Last 24 hours, one bar per 30 minutes"),
                          ("6h", "Last 6 hours, one bar per 7.5 minutes"),
                          ("1h", "Last hour, one bar per minute"),
                          ("live", "Last 48 checks, one bar each"),
                          ("none", "No bars"),
                      )),
                Field("only_down", "Only what is down", type="bool", default=False),
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
            return self._problems(ctx)
        if widget_kind == "status":
            return self._status(ctx, options)
        if widget_kind == "notices":
            return self._notices(ctx, options)
        return self.demo(widget_kind, options, 0)

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
            meta={"empty": "Everything answers.", "bars": drawn or ""},
        )

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

    @staticmethod
    def _problems(ctx: Context) -> WidgetData:
        """Every other card of the same board that is yellow, red or failing, with its reason.

        A yellow dot says that something is wrong; this card says what. It reads
        the live state the collector already holds, so it costs no request.
        """
        from sqlalchemy import select

        from ..db import db_session
        from ..models import HealthCheck, Page, Widget
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
            # ⚠️ The checks of the cards on this board count as well. An app tile
            # draws itself in the browser and has no live state, so a failing
            # check turned it red and this card beside it said everything was
            # fine. Found on 07.09.2026.
            failing = {
                check.widget_id: check.last_error
                for check in db.scalars(select(HealthCheck).where(
                    HealthCheck.widget_id.in_([widget_id for _page, widget_id, _title in rows]),
                    HealthCheck.enabled.is_(True),
                    HealthCheck.last_ok.is_(False),
                ))
            }
        items: list[dict[str, Any]] = []
        for page_name, widget_id, title in rows:
            data = live.get(widget_id)
            where = page_name if several_pages else ""
            if data is not None and data.error:
                items.append({"title": title, "subtitle": data.error, "error_code": str(data.meta.get("code") or ""), "status": "bad", "value": where})
            elif widget_id in failing:
                items.append({"title": title, "subtitle": failing[widget_id] or "Error", "status": "bad", "value": where})
            elif data is None:
                continue
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
            return WidgetData(
                status="bad",
                items=[
                    {"title": "Radarr", "subtitle": "The service could not be reached.", "error_code": "unreachable", "status": "bad", "value": ""},
                    {"title": "UniFi Network", "subtitle": "1 device(s) offline", "status": "warn", "value": ""},
                ],
                meta={"empty": "Everything is fine"},
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
            return WidgetData(status="bad", items=rows, primary={"label": "Down", "value": 1}, meta={"empty": "Everything answers.", "bars": "24h"})
        if widget_kind == "notices":
            import time

            now = time.time()
            return WidgetData(status="warn", items=[
                {"title": "Nextcloud is down", "subtitle": "Nextcloud has not answered for 3 minutes (ConnectError).", "status": "bad", "emphasis": True, "when": now - 240},
                {"title": "nexdeck 0.20.0 is out", "subtitle": "", "status": "ok", "emphasis": True, "when": now - 3 * 3600},
                {"title": "Backup written", "subtitle": "", "status": "ok", "emphasis": False, "when": now - 26 * 3600},
            ], primary={"label": "Unread", "value": 2}, meta={"empty": "No notices.", "headline": True})
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
