"""Boards: serialisation, layout placement, slugs, export and import."""

from __future__ import annotations

import re
from typing import Any

import yaml
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..adapters import get_adapter, split_widget_kind
from ..adapters.base import DEFAULT_MIN, RENDERER_MIN
from ..cards import store as card_store
from ..deps import error, require_integration
from ..models import Board, Integration, Page, Role, User, Widget
from . import app_keys, grid, holders
from . import health as health_service
from .integrations import export_config, store_config
from .state import live

#: The screens a page keeps a layout for. Only ``lg`` is drawn; its columns
#: are the board's own (``grid.columns``), and twelve is what this says for
#: code that has no board at hand.
COLUMNS = {"lg": 12, "md": 8, "sm": 4}


def slugify(text: str) -> str:
    """A name turned into something that can stand in an address.

    ⚠️ Never all digits. A board addressed by its number and a board whose
    slug is that number would be the same address, and the code that looks a
    board up by number would find the wrong one.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        return "board"
    return f"b-{slug}" if slug.isdigit() else slug


def unique_slug(db: Session, wanted: str, ignore_id: int | None = None) -> str:
    base = slugify(wanted)
    slug = base
    counter = 2
    while True:
        existing = db.scalar(select(Board).where(Board.slug == slug))
        if existing is None or existing.id == ignore_id:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def unique_page_slug(db: Session, board_id: int, wanted: str, ignore_id: int | None = None) -> str:
    """A page address no other page of the board has.

    ⚠️ Two pages called "Network" used to share one address, and the page
    looked up by it was always the first: the second could not be opened at
    all, not even right after it was made (measured 19.10.2026 on the demo
    board, which has a "Network" page of its own).
    """
    base = slugify(wanted)
    taken = {row[0] for row in db.execute(select(Page.slug).where(Page.board_id == board_id, Page.id != (ignore_id or 0)))}
    slug, counter = base, 2
    while slug in taken:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


class Placer:
    """Bottom-left placement for one page, measured once instead of per card.

    ⚠️ This used to be a single function that copied the whole layout
    dictionary, scanned every card of every breakpoint twice and reassigned
    ``page.layouts`` for each card placed. Reassigning marks the JSON column
    dirty, so the next flush rewrote the page's whole layout again. The work
    grew with the square of the number of cards: measured on 07.09.2026, an
    import of 12 kB of YAML held the only worker for 55 seconds, and 2 MB were
    allowed. The placement itself is unchanged, down to the last edge case;
    only the bookkeeping moved out of the loop.
    """

    def __init__(self, page: Page, columns: int = grid.BASE) -> None:
        self.page = page
        self.cols = {**COLUMNS, "lg": columns}
        self.layouts: dict[str, list[dict]] = {key: list(value or []) for key, value in (page.layouts or {}).items()}
        self._edge: dict[str, tuple[int, int, int]] = {}
        for key in COLUMNS:
            self.layouts.setdefault(key, [])
            self._edge[key] = self._measure(self.layouts[key])

    @staticmethod
    def _measure(items: list[dict]) -> tuple[int, int, int]:
        """How far down the page reaches, and where its lowest row ends."""
        bottom = max((item["y"] + item["h"] for item in items), default=0)
        row = [item for item in items if item["y"] + item["h"] == bottom]
        if not row:
            return bottom, 0, 0
        return bottom, max(item["x"] + item["w"] for item in row), min(item["y"] for item in row)

    @staticmethod
    def _grown(edge: tuple[int, int, int], x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
        """The same three numbers after one card was added, without re-measuring.

        A card that ends above the current bottom belongs to no lowest row and
        changes nothing, which is exactly what ``_measure`` would say.
        """
        bottom, right, top = edge
        if y + h > bottom:
            return y + h, x + w, y
        if y + h == bottom:
            return bottom, max(right, x + w), min(top, y)
        return bottom, right, top

    def add(self, widget_id: int, size: tuple[int, int], min_size: tuple[int, int]) -> None:
        """Give a card a spot at the bottom of every breakpoint.

        ``size`` and ``min_size`` are in twelfths, as adapters declare them.
        """
        for key, cols in self.cols.items():
            items = self.layouts[key]
            w = min(cols, max(1, grid.widen(size[0], cols) if key == "lg" else max(1, round(size[0] * cols / 12)) or 1))
            min_w = grid.widen(min_size[0], cols) if key == "lg" else min_size[0]
            h = size[1]
            if key == "sm":
                w = min(cols, max(2, w))
            bottom, right, top = self._edge[key]
            x, y = 0, bottom
            # Fill the last row before opening a new one.
            if items and right + w <= cols:
                x, y = right, top
            items.append({"i": str(widget_id), "x": x, "y": y, "w": w, "h": h, "minW": min_w, "minH": min_size[1]})
            self._edge[key] = self._grown(self._edge[key], x, y, w, h)

    def add_at(self, widget_id: int, spots: dict[str, dict]) -> None:
        """Put a card where the file says, and keep the edge up to date."""
        for key, spot in spots.items():
            self.layouts[key].append({"i": str(widget_id), **spot})
            self._edge[key] = self._grown(self._edge[key], spot["x"], spot["y"], spot["w"], spot["h"])

    def finish(self) -> None:
        """Write the page's layout once, at the end."""
        self.page.layouts = self.layouts


def place_widget(page: Page, widget_id: int, size: tuple[int, int], min_size: tuple[int, int], columns: int = grid.BASE) -> None:
    """Give a single new widget a spot at the bottom of every breakpoint."""
    placer = Placer(page, columns)
    placer.add(widget_id, size, min_size)
    placer.finish()


def remove_from_layouts(page: Page, widget_id: int) -> None:
    layouts = dict(page.layouts or {})
    for key in list(layouts):
        layouts[key] = [item for item in layouts[key] if item.get("i") != str(widget_id)]
    page.layouts = layouts


def service_link(widget: Widget) -> str:
    """The address of the widget's integration, so a card without its own link leads there.

    Computed on every read: when the integration's address changes, every
    card that follows it changes with it.
    """
    if widget.integration is None:
        return ""
    from ..adapters import get_adapter
    from .integrations import resolve_config

    try:
        return get_adapter(widget.integration.kind).default_link(resolve_config(widget.integration))
    except (KeyError, ValueError):
        return ""


def _drawn_as(widget: Widget, declared: str) -> str:
    """Which renderer really draws this card, once its options are read.

    A card that offers the "view" option is drawn by whatever that says. Only
    the ones the frontend actually swaps for are listed; anything else is the
    declared renderer.
    """
    view = str((widget.options or {}).get("view") or "")
    if view == "number":
        return "value"
    return view if view in ("gauge", "value", "meter", "segments") else declared


def card_sizes(widget: Widget, columns: int = grid.BASE) -> tuple[list[int], list[int]]:
    """The size a card is made at and the smallest it may be, in ``columns``.

    ⚠️ The floor follows what is drawn, not what the adapter declares.
    Several cards can be switched to a dial, and a dial has no rows: a
    Synology system card set to "a dial" was still held to the three
    columns a row of statistics needs, while the volumes card beside it,
    showing the same dial, went down to two. Same picture, different
    floor, and nothing on screen said why.
    """
    try:
        adapter, kind = split_widget_kind(widget.kind)
        widget_type = adapter.widget(kind)
    except KeyError:
        return [grid.widen(3, columns), 2], [grid.widen(1, columns), 1]
    default_size, min_size = list(widget_type.default_size), list(widget_type.min_size)
    shown = _drawn_as(widget, widget_type.renderer)
    if shown != widget_type.renderer:
        floor = RENDERER_MIN.get(shown, DEFAULT_MIN)
        min_size = [min(min_size[0], floor[0]), min(min_size[1], floor[1])]
        default_size = [max(default_size[0], min_size[0]), max(default_size[1], min_size[1])]
    if adapter.kind == "custom":
        # What the card's definition asks for, never below the floor of what is drawn (KARTEN-6 AC-10).
        from ..adapters.custom import sizes_of

        asked, least = sizes_of(widget.options or {}, (default_size[0], default_size[1]), (min_size[0], min_size[1]))
        default_size, min_size = list(asked), list(least)
    return [grid.widen(default_size[0], columns), default_size[1]], [grid.widen(min_size[0], columns), min_size[1]]


def widget_view(db: Session, widget: Widget, bars: list[float | None] | None = None, columns: int = grid.BASE,
                maintenance_until: dict[int, Any] | None = None) -> dict[str, Any]:
    """A card as the browser gets it.

    ``default_size`` and ``min_size`` come out in the columns of the card's
    board, so the grid can use them as they are. ``maintenance_until`` is what
    ``maintenance.until_by_card`` says for a whole board; one card alone asks.
    """
    from . import maintenance
    try:
        adapter, kind = split_widget_kind(widget.kind)
        widget_type = adapter.widget(kind)
        renderer = widget_type.renderer
        beta = adapter.beta
        client_only = widget_type.client_only
    except KeyError:
        renderer = "value"
        beta = False
        client_only = False
    default_size, min_size = card_sizes(widget, columns)
    # A tile that follows an app (issue #37) takes its address from the app,
    # for the network this request comes from.
    from . import apps as apps_service

    app, app_link = apps_service.tile_view(db, widget)
    health = None
    if widget.health_check is not None:
        health = health_service.check_payload(widget.health_check)
        health["bars"] = (bars if bars is not None
                          else health_service.uptime_bars(db, widget.id, health_service.bars_window(widget.options)))
    # ⚠️ What the card shows, under the names every part of the page reads;
    # the tile's own values, which may be empty, only for its settings sheet.
    # Saving the shown name back would pin the app's name to the tile and stop
    # it following a rename.
    own = {"own_title": widget.title, "own_icon": widget.icon} if app is not None else {}
    # A card of blocks is a tile of key figures when its definition names a main value; the page cannot see that in the
    # renderer, so the card says so (KARTEN-7 AC-8, the same rule as ``holders.is_number_card``).
    number = {"number_card": holders.is_number_card(widget.kind, widget.options)} if widget.kind == "custom.builder" else {}
    return {
        "id": widget.id,
        "kind": widget.kind,
        "title": widget.title or (app["name"] if app is not None else ""),
        "icon": _card_icon(widget) or (app["icon"] if app is not None else ""),
        **own,
        **number,
        "link": widget.link,
        "service_link": app_link if app is not None else service_link(widget),
        "app": app,
        "renderer": renderer,
        "options": widget.options or {},
        "integration_id": widget.integration_id,
        "integration_name": widget.integration.name if widget.integration else None,
        "refresh_seconds": widget.refresh_seconds,
        "beta": beta,
        "client_only": client_only,
        "default_size": default_size,
        "min_size": min_size,
        "health": health,
        # Until when the card's connection, or the tile itself, is in maintenance.
        "maintenance": _away((maintenance_until if maintenance_until is not None
                              else maintenance.until_by_card(db, [widget])).get(widget.id)),
    }


def _card_icon(widget: Widget) -> str:
    """The icon in a card's head; a custom card without one of its own shows the logo of the service it reads.

    ⚠️ Cards placed before 27.10.2026 kept the generic icon of the custom kind; it counts as none, so they show the
    logo too, and a logo changed in an own integration reaches every card at once.
    """
    if not widget.kind.startswith("custom."):
        return widget.icon
    from ..adapters import adapter_or_missing

    generic = adapter_or_missing("custom").icon
    if widget.icon and widget.icon != generic:
        return widget.icon
    if widget.integration is None:
        return generic
    return adapter_or_missing(widget.integration.kind).icon or generic


def _away(row: Any) -> dict[str, Any] | None:
    return {"id": row.id, "until": row.ends_at.isoformat()} if row is not None else None


def board_view(db: Session, board: Board, permission: str, *, include_live: bool = True) -> dict[str, Any]:
    pages = db.scalars(
        select(Page).options(selectinload(Page.widgets).selectinload(Widget.integration), selectinload(Page.widgets).selectinload(Widget.health_check))
        .where(Page.board_id == board.id).order_by(Page.position, Page.id)
    ).all()
    page_views = []
    widget_ids: list[int] = []
    # ⚠️ The bars of every checked card in one go. Drawn per card this was two
    # queries each, so a board with thirty of them made sixty round trips
    # before the first byte went out.
    checked = {w.id: health_service.bars_window(w.options)
               for page in pages for w in page.widgets if w.health_check is not None}
    all_bars = health_service.bars_for(db, checked)
    from . import maintenance

    away = maintenance.until_by_card(db, [w for page in pages for w in page.widgets])
    cols = grid.columns(board.settings)
    for page in pages:
        widgets = [widget_view(db, w, all_bars.get(w.id), cols, away) for w in page.widgets]
        widget_ids.extend(w.id for w in page.widgets)
        page_views.append({
            "id": page.id, "name": page.name, "slug": page.slug, "icon": page.icon, "position": page.position,
            "layouts": {key: page.layouts.get(key, []) for key in COLUMNS} if page.layouts else {key: [] for key in COLUMNS},
            "sections": page.sections or [], "widgets": widgets,
            # What the browser has to send back when it saves an arrangement.
            "layout_version": page.layout_version or 0,
            "kind": page.kind or "cards",
            "topology": {"integration_id": (page.topology or {}).get("integration_id")} if page.kind == "topology" else None,
            "home": {"integration_id": (page.home or {}).get("integration_id")} if page.kind == "home" else None,
            "side": holders.side_of(page, {w.id for w in page.widgets}),
        })
    view = {
        "id": board.id, "slug": board.slug, "name": board.name, "icon": board.icon, "owner_id": board.owner_id,
        "background": board.background or {"kind": "bundled", "value": "aurora"}, "settings": board.settings or {},
        "provisioned": board.provisioned, "permission": permission, "in_menu": board.in_menu, "pages": page_views,
    }
    if include_live:
        view["live"] = {str(k): v.model_dump() for k, v in live.snapshot(widget_ids).items()}
    return view


def board_summary(db: Session, board: Board, permission: str) -> dict[str, Any]:
    # One query with the count per page: the settings list asks what a page
    # would take with it before it offers to delete one.
    pages = db.execute(
        select(Page.id, Page.name, Page.slug, func.count(Widget.id), Page.kind)
        .outerjoin(Widget, Widget.page_id == Page.id)
        .where(Page.board_id == board.id)
        .group_by(Page.id)
        .order_by(Page.position)
    ).all()
    # Who owns it, by name. An administrator holds every board at the "owner"
    # level, so the level alone would tell everyone their own board is theirs
    # and everybody else's too.
    owner = db.get(User, board.owner_id) if board.owner_id else None
    return {
        "id": board.id, "slug": board.slug, "name": board.name, "icon": board.icon, "owner_id": board.owner_id,
        "owner_name": (owner.display_name or owner.username) if owner else "",
        "permission": permission, "provisioned": board.provisioned, "position": board.position, "in_menu": board.in_menu,
        "pages": [{"id": p[0], "name": p[1], "slug": p[2], "widget_count": int(p[3]), "kind": p[4]} for p in pages],
        "widget_count": sum(int(p[3]) for p in pages),
    }


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------


def export_board(db: Session, board: Board, *, reveal_locked: bool = False, with_ids: bool = False) -> str:
    """The board as YAML.

    ⚠️ ``reveal_locked`` is not a nicety. Exporting needs only "view", and a
    board is shared at that level all the time, while ``export_config`` masks
    the fields marked secret and writes out everything else: addresses, user
    names, ports, paths. For a connection the administrator reserved for
    himself that is exactly the part he reserved. A viewer gets the name and
    the kind, which is all an import needs to match it up again.

    ``with_ids`` is for editing the board in place (``edit_board``): every page
    and card carries its number, so what stays in the text keeps its row, and
    with it its check and the history of its uptime bars.
    """
    pages = db.scalars(select(Page).options(selectinload(Page.widgets).selectinload(Widget.integration)).where(Page.board_id == board.id).order_by(Page.position)).all()
    from . import apps as apps_service

    integrations: dict[int, Integration] = {}
    followed_apps: dict[int, Any] = {}
    document: dict[str, Any] = {
        "nexdeck": 1,
        "board": {"name": board.name, "slug": board.slug, "icon": board.icon, "background": board.background or {}, "settings": board.settings or {}},
        "pages": [],
    }
    for page in pages:
        page_doc: dict[str, Any] = {**({"id": page.id} if with_ids else {}), "name": page.name, "slug": page.slug, "icon": page.icon, "widgets": []}
        if page.kind == "topology":
            # The connection by name, like a card's; the arrangement as it stands.
            stored = page.topology or {}
            connection = db.get(Integration, stored["integration_id"]) if stored.get("integration_id") else None
            if connection is not None:
                integrations[connection.id] = connection
            page_doc["kind"] = "topology"
            page_doc["topology"] = {
                "integration": connection.name if connection is not None else None,
                **{key: stored.get(key) for key in ("start", "seeded", "placed", "clients", "hidden", "positions") if key in stored},
            }
        elif page.kind == "home":
            # The same for a home page: its connection by name, what stands where as it stands.
            stored = page.home or {}
            connection = db.get(Integration, stored["integration_id"]) if stored.get("integration_id") else None
            if connection is not None:
                integrations[connection.id] = connection
            page_doc["kind"] = "home"
            page_doc["home"] = {"integration": connection.name if connection is not None else None, "elements": stored.get("elements") or []}
        # A holding card names its cards by place on the page, "#2" for the
        # third: the numbers of the cards are new after every import.
        place = {widget.id: index for index, widget in enumerate(page.widgets)}
        # The side bar the same way.
        side = holders.side_of(page, set(place))
        if side["place"] != "off" or side["cards"]:
            page_doc["side"] = {"place": side["place"], "width": side["width"], "cards": [f"#{place[number]}" for number in side["cards"]]}
        for widget in page.widgets:
            if widget.integration is not None:
                integrations[widget.integration.id] = widget.integration
            layout = {}
            for key in COLUMNS:
                for item in (page.layouts or {}).get(key, []):
                    if item.get("i") == str(widget.id):
                        layout[key] = {"x": item["x"], "y": item["y"], "w": item["w"], "h": item["h"]}
            options = _by_place(widget, place)
            app = apps_service.followed(db, widget)
            if app is not None:
                # By name, not by number: the number means nothing on another
                # installation, and the app travels along below.
                followed_apps[app.id] = app
                options = {key: value for key, value in (options or {}).items() if key != "app_id"}
                options["app"] = app.name
            page_doc["widgets"].append({
                **({"id": widget.id} if with_ids else {}),
                "kind": widget.kind, "title": widget.title, "icon": widget.icon, "link": widget.link,
                "integration": widget.integration.name if widget.integration else None,
                "options": options, "refresh_seconds": widget.refresh_seconds, "layout": layout,
            })
        document["pages"].append(page_doc)
    document["integrations"] = [
        {"name": i.name, "kind": i.kind, "demo": i.demo,
         "config": export_config(i) if (reveal_locked or not i.admin_only) else {}}
        for i in integrations.values()
    ]
    if followed_apps:
        document["apps"] = [
            {key: value for key, value in apps_service.app_view(app).items() if key != "id"}
            for app in followed_apps.values()
        ]
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def _apps_of(db: Session, document: dict[str, Any], trusted: bool) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The apps a file names: the ones found here by name, and what the file says of each.

    Only a file the operator put on the server creates a missing app, as with
    connections. Over HTTP a tile whose app is missing becomes a tile of its
    own, with the name, icon and address the file gives it (``_follow_app``).
    """
    from ..models import App
    from . import apps as apps_service

    found: dict[str, Any] = {}
    written: dict[str, dict[str, Any]] = {}
    for entry in document.get("apps") or []:
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            continue
        name = str(entry["name"]).strip()[:120]
        written[name] = entry
        app = apps_service.by_name(db, name)
        if app is None and trusted:
            try:
                addresses = apps_service.clean_addresses(entry.get("addresses"))
                app = App(name=name, icon=str(entry.get("icon") or "")[:200], description=str(entry.get("description") or "")[:300],
                          addresses=addresses, home=apps_service.clean_choice(addresses, str(entry.get("home") or "")),
                          away=apps_service.clean_choice(addresses, str(entry.get("away") or "")))
            except apps_service.AppRefused as error:
                raise ImportError_(f"The app {name!r}: {error}") from error
            db.add(app)
            db.flush()
        if app is not None:
            found[name] = app
    return found, written


def _follow_app(fields: dict[str, Any], widget_doc: dict[str, Any], found: dict[str, Any], written: dict[str, dict[str, Any]], label: str) -> None:
    """Tie an imported tile to its app by name, or make it a tile of its own."""
    from types import SimpleNamespace

    from . import apps as apps_service

    options = fields["options"]
    options.pop("app_id", None)
    name = str(options.pop("app", "") or "")
    if not name:
        options.pop("address", None)
        return
    if name in found:
        options["app_id"] = found[name].id
        # No name of its own means the app's name, not "App tile".
        if not str(widget_doc.get("title") or "").strip():
            fields["title"] = ""
        return
    choice = str(options.pop("address", "") or "")
    entry = written.get(name) or {}
    try:
        addresses = apps_service.clean_addresses(entry.get("addresses"))
    except apps_service.AppRefused:
        addresses = []
    stand_in = SimpleNamespace(addresses=addresses, home=str(entry.get("home") or ""), away=str(entry.get("away") or ""))
    if not str(widget_doc.get("title") or "").strip():
        fields["title"] = name or label
    fields["icon"] = fields["icon"] or str(entry.get("icon") or "")
    fields["link"] = fields["link"] or apps_service.resolve(stand_in, choice, None)  # type: ignore[arg-type]


#: Cards that hold other cards of their page, by number in ``options["cards"]``.
GROUP_KINDS = holders.HOLDER_KINDS
#: More than this in one card is a page, not a group.
MOST_TUCKED = 12


def clean_cards(db: Session, page_id: int, own_id: int | None, kind: str, options: dict | None) -> dict | None:
    """The cards a holding card may keep: cards of its own page, no holder
    among them and not itself, each once, at most twelve. Anything else is
    left out rather than refused: a card that was deleted or moved meanwhile
    is simply no longer in it.
    """
    if kind not in GROUP_KINDS or not options or "cards" not in options:
        return options
    wanted: list[int] = []
    for entry in options.get("cards") or []:
        try:
            number = int(entry)
        except (TypeError, ValueError):
            continue
        if number != own_id and number not in wanted:
            wanted.append(number)
    found = {row.id: row for row in db.scalars(select(Widget).where(Widget.page_id == page_id, Widget.id.in_(wanted or [-1])))}
    present = {number: row.kind for number, row in found.items()}
    kept = [number for number in wanted if number in present and present[number] not in GROUP_KINDS][:MOST_TUCKED]
    # Key figures hold numbers: a list or a clock picked for them is left where it is.
    if kind == "core.figures":
        kept = [number for number in kept if holders.is_number_card(present[number], found[number].options)]
    # ⚠️ A card stands in one place. Picked here, it leaves the other holders of
    # the page and its side bar; it used to be drawn twice, in both.
    page = db.get(Page, page_id)
    if page is not None and kept:
        for holder in page.widgets:
            cards = (holder.options or {}).get("cards")
            if holder.id != own_id and holder.kind in GROUP_KINDS and isinstance(cards, list) and any(number in cards for number in kept):
                holder.options = {**holder.options, "cards": [one for one in cards if one not in kept]}
        side = holders.side_of(page)
        if any(number in side["cards"] for number in kept):
            page.side = {**side, "cards": [one for one in side["cards"] if one not in kept]}
    return {**options, "cards": kept}


#: The colours every card can wear: the first four follow the theme (accent, bad,
#: warn, ok), the rest are nexdeck's own. ``icon`` takes the main colour of the
#: card's logo, a ``#rrggbb`` is a colour of one's own.
CARD_COLOURS = frozenset({"accent", "blue", "violet", "pink", "red", "orange", "yellow", "green", "icon"})
#: How the colour shows: a frame, a tint over the glass, or the whole card.
CARD_EFFECTS = frozenset({"frame", "tint", "fill"})
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _check_held(options: dict) -> None:
    """A size inside a group or a side bar: columns of twelve and rows, each from 1 to 12."""
    if "held_size" in options and options["held_size"] is not None and holders.held_size(options["held_size"]) is None:
        raise error("bad_held_size", "A size inside a group goes from 1 to 12 columns and 1 to 12 rows.")


def _check_look(options: dict) -> None:
    """The colour of a card and how it shows, checked before it is stored.

    ⚠️ The colour goes into the card's style. Anything but a name from the list
    or ``#rrggbb`` is refused here, so nothing else ever reaches a style sheet.
    """
    colour = options.get("card_colour")
    if colour not in (None, "") and not (isinstance(colour, str) and (colour in CARD_COLOURS or _HEX.match(colour))):
        raise error("bad_card_colour", "A card's colour is one from the list or reads like #3b82f6.")
    effect = options.get("card_effect")
    if effect not in (None, "") and effect not in CARD_EFFECTS:
        raise error("bad_card_effect", "A card's colour shows as a frame, a tint or a fill.")
    # A card without its head or without its frame: yes or no, nothing that could reach a class name.
    for name in ("hide_head", "frameless"):
        if options.get(name) is not None and not isinstance(options[name], bool):
            raise error(f"bad_{name}", f"Whether a card goes {'without its head' if name == 'hide_head' else 'without its frame'} is yes or no.")


#: Whether a card is left out of the phone's stack, and whether it comes back when it turns red.
PHONE_SWITCHES = ("phone_hide", "phone_show_red")


def _check_phone(options: dict) -> None:
    """The two switches for the phone are switches: on, off or not set."""
    for name in PHONE_SWITCHES:
        if options.get(name) is not None and not isinstance(options[name], bool):
            raise error("bad_phone", "Hiding a card on the phone is switched on or off, nothing else.")


def refuse_unshared_card(db: Session, kind: str, options: dict | None, user: User | None) -> None:
    """Only an administrator puts a custom card on a board, unless he released that card for users (KARTEN-11 AC-3, AC-4).

    ⚠️ Asked where a card is **placed**, never where an already placed one is changed or moved: taking the release back
    leaves the cards that stand on boards where they are (EC-1). A card that is not released answers like one that does
    not exist, so nobody learns the short names of the cards he cannot see.
    """
    if not kind.startswith("custom.") or user is None or user.role == Role.admin.value:
        return
    slug = str((options or {}).get("card") or "").strip()
    entry = card_store.get(db, slug) if slug else None
    if entry is None or not entry.users_may_place:
        raise error("unknown_card", "There is no card with that short name.")


def _validate_options(db: Session, kind: str, options: dict | None, user: User | None) -> None:
    """Check every option that names a connection.

    ⚠️ ``integration_id`` was checked from the start and the options were not.
    The merged calendar keeps its sources in one, so a member could write the
    number of a connection reserved for administrators into it and read its
    release calendar. The same check now covers both.
    """
    if not options:
        return
    _check_look(options)
    _check_held(options)
    _check_phone(options)
    if kind == "core.app" and options.get("app_id") not in (None, ""):
        from ..models import App

        try:
            known = db.get(App, int(options["app_id"])) is not None
        except (TypeError, ValueError):
            known = False
        if not known:
            raise error("unknown_app", "There is no such app in the catalog.")
    if kind == "core.app":
        from . import aliases

        try:
            aliases.check(options.get("alias"))
        except aliases.AliasRefused as refused:
            raise error(refused.code, str(refused)) from None
    adapter, widget_kind = split_widget_kind(kind)
    for field in adapter.widget(widget_kind).options:
        if field.type != "integrations":
            continue
        allowed = {value for value, _label in field.options}
        for entry in options.get(field.name) or []:
            try:
                integration_id = int(entry)
            except (TypeError, ValueError):
                raise error("bad_source", f"{entry!r} is not a connection.") from None
            integration = require_integration(db, integration_id, user)
            if allowed and integration.kind not in allowed:
                raise error("bad_source", f"A {integration.kind} connection cannot be a source here.")


def _by_place(widget: Widget, place: dict[int, int]) -> dict:
    options = dict(widget.options or {})
    if widget.kind in GROUP_KINDS and isinstance(options.get("cards"), list):
        options["cards"] = [f"#{place[number]}" for number in options["cards"] if isinstance(number, int) and number in place]
    return options


def _by_number(made: list[Widget]) -> None:
    """The places a holding card names in a file, turned back into the numbers of the cards just made."""
    for widget in made:
        cards = (widget.options or {}).get("cards")
        if widget.kind not in GROUP_KINDS or not isinstance(cards, list):
            continue
        numbers = []
        for entry in cards:
            if isinstance(entry, str) and entry.startswith("#") and entry[1:].isdigit() and int(entry[1:]) < len(made):
                target = made[int(entry[1:])]
                if target.kind not in GROUP_KINDS and target.id != widget.id:
                    numbers.append(target.id)
        widget.options = {**widget.options, "cards": numbers[:MOST_TUCKED]}


def _side_by_number(side: Any, made: list[Widget]) -> dict:
    """The side bar of a page in a file, its places turned back into the numbers of the cards just made."""
    if not isinstance(side, dict):
        return {}
    numbers: list[int] = []
    for entry in side.get("cards") or []:
        if isinstance(entry, str) and entry.startswith("#") and entry[1:].isdigit() and int(entry[1:]) < len(made):
            target = made[int(entry[1:])]
            if target.kind not in GROUP_KINDS and target.id not in numbers:
                numbers.append(target.id)
    return {
        "place": side.get("place") if side.get("place") in holders.PLACES else "off",
        "width": side.get("width") if side.get("width") in holders.WIDTHS else "narrow",
        "cards": numbers[: holders.MOST_SIDE],
    }


def _user_of(db: Session, owner_id: int | None) -> User | None:
    """Whose rights the import runs with. A file on the server has none."""
    return db.get(User, owner_id) if owner_id else None


class ImportError_(ValueError):
    pass


#: What one import may bring in. A board nobody can read is not a board, and
#: without a ceiling the only limit was the 2 MB request body.
#:
#: ⚠️ YAML anchors make the input tiny and the result enormous: a few hundred
#: bytes can name the same card a thousand times over. The count has to happen
#: on the parsed document, not on the length of the text.
MAX_PAGES = 50
MAX_WIDGETS = 300


def _read_the_whole_thing_first(db: Session, document: dict, user: User | None, allow_locked: bool, standing: frozenset[str] = frozenset()) -> None:
    """Every objection raised before anything is touched.

    ⚠️ The order used to be the other way round. Replacing a board deleted all
    its pages and only then looked at the widget kinds, so a file with one
    unknown kind emptied the board and wrote that down. Under provisioning it
    did so every ten seconds.

    ⚠️ And it is where the checks the API has always made finally reach the
    import. Naming a connection reserved for administrators is refused when a
    card is created, changed or previewed, and three tests say so, but
    ``import_board`` never called any of it: the same options went through as
    YAML. An interval was taken as it came, so a card could arrive with the
    text "abc" in a column SQLite is happy to keep and no way to fix it in the
    interface.
    """
    meta = document.get("board")
    if meta is not None and not isinstance(meta, dict):
        raise ImportError_("The 'board' section has to be a mapping of name, icon and settings.")
    pages = document.get("pages")
    if pages is not None and not isinstance(pages, list):
        raise ImportError_("'pages' has to be a list.")
    for position, page_doc in enumerate(pages or [], start=1):
        if not isinstance(page_doc, dict):
            raise ImportError_(f"Page {position} has to be a mapping.")
        widgets = page_doc.get("widgets")
        if widgets is not None and not isinstance(widgets, list):
            raise ImportError_(f"The widgets of page {position} have to be a list.")
        for number, widget_doc in enumerate(widgets or [], start=1):
            where = f"card {number} on page {position}"
            if not isinstance(widget_doc, dict):
                raise ImportError_(f"{where.capitalize()} has to be a mapping.")
            kind = str(widget_doc.get("kind") or "")
            try:
                adapter, widget_kind = split_widget_kind(kind)
                adapter.widget(widget_kind)
            except KeyError as unknown:
                raise ImportError_(f"Unknown widget kind {kind!r} in {where}.") from unknown
            options = widget_doc.get("options")
            if options is not None and not isinstance(options, dict):
                raise ImportError_(f"The options of {where} have to be a mapping.")
            every = widget_doc.get("refresh_seconds")
            if every is not None and (not isinstance(every, int) or isinstance(every, bool) or not 5 <= every <= 86400):
                raise ImportError_(f"The refresh interval of {where} has to be a whole number of seconds between 5 and 86400.")
            # ⚠️ The layout is read after the old cards of a replaced board are
            # gone, and it was not looked at here until 12.09.2026: a card with
            # ``layout: nope`` got past every other check and came apart in the
            # middle of writing.
            layout = widget_doc.get("layout")
            if layout not in (None, {}):
                spots = [layout.get(key) for key in (*COLUMNS, "lg")] if isinstance(layout, dict) else None
                if spots is None or any(
                    spot not in (None, {}) and (
                        not isinstance(spot, dict)
                        or any(
                            isinstance(spot.get(side, 0), bool) or not isinstance(spot.get(side, 0), int) or spot.get(side, 0) < 0
                            for side in ("x", "y", "w", "h")
                        )
                    )
                    for spot in spots
                ):
                    raise ImportError_(f"The layout of {where} has to give lg an x, y, w and h as whole numbers.")
            if not allow_locked:
                try:
                    # A card that stands on the board being edited keeps its place whether or not users may still place it (KARTEN-11 EC-1).
                    if str((options or {}).get("card") or "").strip() not in standing:
                        refuse_unshared_card(db, kind, options, user)
                    _validate_options(db, kind, options, user)
                except HTTPException as refused:
                    detail = refused.detail if isinstance(refused.detail, dict) else {}
                    raise ImportError_(f"{where.capitalize()}: {detail.get('message', 'this option is not allowed')}") from refused
            try:
                app_keys.check_value(kind, options)
            except HTTPException as refused:
                detail = refused.detail if isinstance(refused.detail, dict) else {}
                raise ImportError_(f"{where.capitalize()}: {detail.get('message', 'this key is not allowed')}") from refused
    # A file is one board, and a key opens one tile of a board.
    twice = app_keys.twice_in_file(pages or [])
    if twice:
        raise ImportError_(f"Key {twice} is given to two app tiles. Each key opens one tile of a board.")


def _refuse_if_oversized(document: dict) -> None:
    pages = document.get("pages")
    if not isinstance(pages, list):
        return
    if len(pages) > MAX_PAGES:
        raise ImportError_(f"This file has {len(pages)} pages; at most {MAX_PAGES} are imported at once.")
    cards = sum(len(page.get("widgets") or []) for page in pages if isinstance(page, dict) and isinstance(page.get("widgets"), list))
    if cards > MAX_WIDGETS:
        raise ImportError_(f"This file has {cards} cards; at most {MAX_WIDGETS} are imported at once.")


def import_board(
    db: Session,
    text: str,
    *,
    owner_id: int | None,
    slug: str | None = None,
    provisioned: bool = False,
    source_file: str = "",
    replace: Board | None = None,
    trusted: bool = False,
    allow_locked: bool = False,
    keep_ids: bool = False,
) -> Board:
    """Create (or replace) a board from a YAML document.

    ⚠️ Two callers, two levels of trust. Provisioning reads files the operator
    put into ``data/boards/`` on the server, so it may do everything: expand
    ``${VAR}`` from the environment and create the connections the file names.
    ``POST /api/v1/boards/import`` is open to every member, and gets neither.

    Without those two rights the import was a way to read any environment
    variable of the server: a member imported a board whose connection had
    ``api_key: "${NEXDECK_SECRET_KEY}"``, and read the value straight back out
    of the connection list. That key signs every session and unlocks every
    stored secret.

    ``allow_locked`` says whether a widget may be tied to a connection the
    administrator reserved. It follows the caller, not the file.

    ``keep_ids`` (with ``replace``) edits the board instead of rebuilding it: a
    page or card whose ``id`` belongs to this board keeps its row and is changed
    where it stands, anything else is new, and whatever the text no longer names
    goes. A number from another board is not looked at, it only makes a new card.
    """
    import os

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ImportError_(f"The file is not valid YAML: {error}") from error
    if not isinstance(document, dict) or "board" not in document:
        raise ImportError_("The file has no 'board' section.")
    _refuse_if_oversized(document)
    standing = frozenset(
        str((one.options or {}).get("card") or "").strip()
        for one in (db.scalars(select(Widget).join(Page).where(Page.board_id == replace.id, Widget.kind.like("custom.%"))) if replace is not None else [])
    )
    _read_the_whole_thing_first(db, document, _user_of(db, owner_id), allow_locked, standing)
    meta = document.get("board") or {}
    name = str(meta.get("name") or "Imported board")
    # Integrations: matched by name, created when missing.
    by_name: dict[str, Integration] = {}
    for entry in document.get("integrations") or []:
        if not isinstance(entry, dict) or not entry.get("kind"):
            continue
        try:
            get_adapter(entry["kind"])
        except KeyError as error:
            raise ImportError_(f"Unknown integration kind {entry['kind']!r}.") from error
        existing = db.scalar(select(Integration).where(Integration.name == str(entry.get("name")), Integration.kind == entry["kind"]))
        if existing is None:
            if not trusted:
                raise ImportError_(
                    f"This file wants a connection called {str(entry.get('name'))!r}, and there is none. "
                    "An administrator has to set it up first; an import does not create connections.",
                )
            config = {}
            for key, value in (entry.get("config") or {}).items():
                # Only a file the operator put on the server may read the
                # environment. Over HTTP this would hand out the secret key.
                if trusted and isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                    value = os.environ.get(value[2:-1], "")
                config[key] = value
            existing = Integration(kind=entry["kind"], name=str(entry.get("name") or entry["kind"]), config=store_config(entry["kind"], config), demo=bool(entry.get("demo")), created_by=owner_id)
            db.add(existing)
            db.flush()
        if existing.admin_only and not allow_locked:
            raise ImportError_(f"The connection {existing.name!r} is reserved for administrators.")
        by_name[existing.name] = existing
    apps_found, apps_written = _apps_of(db, document, trusted)

    # A file is taken at its word about its columns, as long as they are ones
    # nexdeck draws; a file from before 0.17.0 has none and gets twelve.
    raw_settings = meta.get("settings") if isinstance(meta.get("settings"), dict) else {}
    settings = grid.clean(raw_settings, grid.columns(raw_settings))
    old_pages: dict[int, Page] = {}
    old_widgets: dict[int, Widget] = {}
    if replace is not None:
        board = replace
        for page in list(db.scalars(select(Page).options(selectinload(Page.widgets)).where(Page.board_id == board.id))):
            if keep_ids:
                old_pages[page.id] = page
                old_widgets.update({widget.id: widget for widget in page.widgets})
            else:
                db.delete(page)
        db.flush()
        board.name = name
        board.icon = str(meta.get("icon") or board.icon)
        board.background = dict(meta.get("background") or {})
        board.settings = settings
    else:
        board = Board(
            slug=unique_slug(db, slug or str(meta.get("slug") or name)), name=name, icon=str(meta.get("icon") or "layout-dashboard"),
            owner_id=owner_id, background=dict(meta.get("background") or {}), settings=settings,
            provisioned=provisioned, source_file=source_file,
        )
        db.add(board)
        db.flush()

    for position, page_doc in enumerate(document.get("pages") or []):
        page_name = str(page_doc.get("name") or f"Page {position + 1}")
        page_slug = slugify(str(page_doc.get("slug") or page_doc.get("name") or f"page-{position + 1}"))
        page = old_pages.pop(_number(page_doc.get("id")), None)
        page_kind, page_topology = _topology_of(page_doc, by_name)
        page_home: dict[str, Any] = {}
        if page_kind == "cards":
            page_kind, page_home = _home_of(page_doc, by_name)
        if page is not None:
            page.name, page.slug, page.icon, page.position = page_name, page_slug, str(page_doc.get("icon") or ""), position
            page.kind, page.topology, page.home = page_kind, page_topology, page_home
            page.layouts = {key: [] for key in COLUMNS}
            # An open browser arranging this page is told it moved on (``put_layouts``).
            page.layout_version = (page.layout_version or 0) + 1
        else:
            page = Page(board_id=board.id, name=page_name, slug=page_slug, icon=str(page_doc.get("icon") or ""), position=position,
                        layouts={key: [] for key in COLUMNS}, kind=page_kind, topology=page_topology, home=page_home)
            db.add(page)
        db.flush()
        placer = Placer(page, grid.columns(board.settings))
        made: list[Widget] = []
        for widget_doc in page_doc.get("widgets") or []:
            kind = str(widget_doc.get("kind") or "")
            try:
                adapter, widget_kind = split_widget_kind(kind)
            except KeyError as error:
                raise ImportError_(f"Unknown widget kind {kind!r}.") from error
            widget_type = adapter.widget(widget_kind)
            integration = by_name.get(str(widget_doc.get("integration"))) if widget_doc.get("integration") else None
            fields = {
                "kind": kind, "title": str(widget_doc.get("title") or widget_type.label), "icon": str(widget_doc.get("icon") or (adapter.icon if adapter.kind != "core" else "")),
                "link": str(widget_doc.get("link") or ""), "integration_id": integration.id if integration else None,
                "options": dict(widget_doc.get("options") or {}), "refresh_seconds": widget_doc.get("refresh_seconds"),
            }
            if kind == "core.app":
                _follow_app(fields, widget_doc, apps_found, apps_written, widget_type.label)
            widget = old_widgets.pop(_number(widget_doc.get("id")), None)
            if widget is not None:
                for key, value in fields.items():
                    setattr(widget, key, value)
                widget.page = page
            else:
                widget = Widget(page_id=page.id, **fields)
                db.add(widget)
            db.flush()
            made.append(widget)
            layout = widget_doc.get("layout") or {}
            if layout:
                spots = {}
                for key in COLUMNS:
                    item = layout.get(key) or layout.get("lg") or {}
                    cols = placer.cols[key]
                    w = min(cols, max(1, int(item.get("w", grid.widen(widget_type.default_size[0], cols)))))
                    # ⚠️ Inside the grid, not only narrower than it: a card at
                    # x 20 on a file that says twelve columns would be drawn
                    # off the edge, and the grid pulls it back onto whatever
                    # stands there.
                    x = min(int(item.get("x", 0)), cols - w)
                    spots[key] = {"x": x, "y": int(item.get("y", 0)), "w": w, "h": int(item.get("h", widget_type.default_size[1]))}
                placer.add_at(widget.id, spots)
            else:
                placer.add(widget.id, widget_type.default_size, widget_type.min_size)
            health_service.ensure_check_for_widget(db, widget)
        _by_number(made)
        page.side = _side_by_number(page_doc.get("side"), made)
        placer.finish()
    # What the text no longer names. The cards first: one that moved to another page is no longer in its old
    # page's list, so deleting that page cannot take it along.
    for widget in old_widgets.values():
        db.delete(widget)
    db.flush()
    for page in old_pages.values():
        db.delete(page)
    if not document.get("pages"):
        db.add(Page(board_id=board.id, name="Overview", slug="overview", position=0, layouts={key: [] for key in COLUMNS}))
    db.flush()
    return board


def _topology_of(page_doc: dict, by_name: dict[str, Integration]) -> tuple[str, dict[str, Any]]:
    """A page's kind and, for a network plan, its arrangement and connection.

    A connection the file names but this installation lacks leaves the page
    without one; it says so when opened instead of refusing the whole file.
    """
    if page_doc.get("kind") != "topology":
        return "cards", {}
    from . import topology as topology_service

    raw = page_doc.get("topology") if isinstance(page_doc.get("topology"), dict) else {}
    connection = by_name.get(str(raw.get("integration"))) if raw.get("integration") else None
    connection_id = connection.id if connection is not None and connection.kind == "unifi" else None
    return "topology", topology_service.clean_layout(raw, connection_id)


def _home_of(page_doc: dict, by_name: dict[str, Integration]) -> tuple[str, dict[str, Any]]:
    """A page's kind and, for a home page, what stands on it and its connection.

    As with a network plan, a connection the file names but this installation
    lacks leaves the page without one, and the page says so when opened.
    """
    if page_doc.get("kind") != "home":
        return "cards", {}
    from . import home as home_service

    raw = page_doc.get("home") if isinstance(page_doc.get("home"), dict) else {}
    connection = by_name.get(str(raw.get("integration"))) if raw.get("integration") else None
    connection_id = connection.id if connection is not None and connection.kind == "homeassistant" else None
    return "home", home_service.clean_layout(raw, connection_id)


def _number(value: Any) -> int | None:
    """A row number from a file, or nothing: ``true`` is not 1."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None
