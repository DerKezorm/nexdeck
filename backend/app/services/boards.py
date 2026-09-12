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
from ..deps import error, require_integration
from ..models import Board, Integration, Page, User, Widget
from . import health as health_service
from .integrations import export_config, store_config
from .state import live

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

    def __init__(self, page: Page) -> None:
        self.page = page
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
        """Give a card a spot at the bottom of every breakpoint."""
        for key, cols in COLUMNS.items():
            items = self.layouts[key]
            w = min(cols, max(1, size[0] if key == "lg" else max(1, round(size[0] * cols / 12)) or 1))
            h = size[1]
            if key == "sm":
                w = min(cols, max(2, w))
            bottom, right, top = self._edge[key]
            x, y = 0, bottom
            # Fill the last row before opening a new one.
            if items and right + w <= cols:
                x, y = right, top
            items.append({"i": str(widget_id), "x": x, "y": y, "w": w, "h": h, "minW": min_size[0], "minH": min_size[1]})
            self._edge[key] = self._grown(self._edge[key], x, y, w, h)

    def add_at(self, widget_id: int, spots: dict[str, dict]) -> None:
        """Put a card where the file says, and keep the edge up to date."""
        for key, spot in spots.items():
            self.layouts[key].append({"i": str(widget_id), **spot})
            self._edge[key] = self._grown(self._edge[key], spot["x"], spot["y"], spot["w"], spot["h"])

    def finish(self) -> None:
        """Write the page's layout once, at the end."""
        self.page.layouts = self.layouts


def place_widget(page: Page, widget_id: int, size: tuple[int, int], min_size: tuple[int, int]) -> None:
    """Give a single new widget a spot at the bottom of every breakpoint."""
    placer = Placer(page)
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
    return view if view in ("gauge", "value") else declared


def widget_view(db: Session, widget: Widget, bars: list[float | None] | None = None) -> dict[str, Any]:
    try:
        adapter, kind = split_widget_kind(widget.kind)
        widget_type = adapter.widget(kind)
        renderer = widget_type.renderer
        beta = adapter.beta
        client_only = widget_type.client_only
        default_size, min_size = list(widget_type.default_size), list(widget_type.min_size)
        # ⚠️ The floor follows what is drawn, not what the adapter declares.
        # Several cards can be switched to a dial, and a dial has no rows: a
        # Synology system card set to "a dial" was still held to the three
        # columns a row of statistics needs, while the volumes card beside it,
        # showing the same dial, went down to two. Same picture, different
        # floor, and nothing on screen said why.
        shown = _drawn_as(widget, renderer)
        if shown != renderer:
            floor = RENDERER_MIN.get(shown, DEFAULT_MIN)
            min_size = [min(min_size[0], floor[0]), min(min_size[1], floor[1])]
            default_size = [max(default_size[0], min_size[0]), max(default_size[1], min_size[1])]
    except KeyError:
        renderer = "value"
        beta = False
        client_only = False
        default_size, min_size = [3, 2], [1, 1]
    health = None
    if widget.health_check is not None:
        health = health_service.check_payload(widget.health_check)
        health["bars"] = (bars if bars is not None
                          else health_service.uptime_bars(db, widget.id, health_service.bars_window(widget.options)))
    return {
        "id": widget.id,
        "kind": widget.kind,
        "title": widget.title,
        "icon": widget.icon,
        "link": widget.link,
        "service_link": service_link(widget),
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
    }


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
    for page in pages:
        widgets = [widget_view(db, w, all_bars.get(w.id)) for w in page.widgets]
        widget_ids.extend(w.id for w in page.widgets)
        page_views.append({
            "id": page.id, "name": page.name, "slug": page.slug, "icon": page.icon, "position": page.position,
            "layouts": {key: page.layouts.get(key, []) for key in COLUMNS} if page.layouts else {key: [] for key in COLUMNS},
            "sections": page.sections or [], "widgets": widgets,
            # What the browser has to send back when it saves an arrangement.
            "layout_version": page.layout_version or 0,
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
        select(Page.id, Page.name, Page.slug, func.count(Widget.id))
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
        "pages": [{"id": p[0], "name": p[1], "slug": p[2], "widget_count": int(p[3])} for p in pages],
        "widget_count": sum(int(p[3]) for p in pages),
    }


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------


def export_board(db: Session, board: Board, *, reveal_locked: bool = False) -> str:
    """The board as YAML.

    ⚠️ ``reveal_locked`` is not a nicety. Exporting needs only "view", and a
    board is shared at that level all the time, while ``export_config`` masks
    the fields marked secret and writes out everything else: addresses, user
    names, ports, paths. For a connection the administrator reserved for
    himself that is exactly the part he reserved. A viewer gets the name and
    the kind, which is all an import needs to match it up again.
    """
    pages = db.scalars(select(Page).options(selectinload(Page.widgets).selectinload(Widget.integration)).where(Page.board_id == board.id).order_by(Page.position)).all()
    integrations: dict[int, Integration] = {}
    document: dict[str, Any] = {
        "nexdeck": 1,
        "board": {"name": board.name, "slug": board.slug, "icon": board.icon, "background": board.background or {}, "settings": board.settings or {}},
        "pages": [],
    }
    for page in pages:
        page_doc: dict[str, Any] = {"name": page.name, "slug": page.slug, "icon": page.icon, "widgets": []}
        for widget in page.widgets:
            if widget.integration is not None:
                integrations[widget.integration.id] = widget.integration
            layout = {}
            for key in COLUMNS:
                for item in (page.layouts or {}).get(key, []):
                    if item.get("i") == str(widget.id):
                        layout[key] = {"x": item["x"], "y": item["y"], "w": item["w"], "h": item["h"]}
            page_doc["widgets"].append({
                "kind": widget.kind, "title": widget.title, "icon": widget.icon, "link": widget.link,
                "integration": widget.integration.name if widget.integration else None,
                "options": widget.options or {}, "refresh_seconds": widget.refresh_seconds, "layout": layout,
            })
        document["pages"].append(page_doc)
    document["integrations"] = [
        {"name": i.name, "kind": i.kind, "demo": i.demo,
         "config": export_config(i) if (reveal_locked or not i.admin_only) else {}}
        for i in integrations.values()
    ]
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def _validate_options(db: Session, kind: str, options: dict | None, user: User | None) -> None:
    """Check every option that names a connection.

    ⚠️ ``integration_id`` was checked from the start and the options were not.
    The merged calendar keeps its sources in one, so a member could write the
    number of a connection reserved for administrators into it and read its
    release calendar. The same check now covers both.
    """
    if not options:
        return
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


def _read_the_whole_thing_first(db: Session, document: dict, user: User | None, allow_locked: bool) -> None:
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
                    _validate_options(db, kind, options, user)
                except HTTPException as refused:
                    detail = refused.detail if isinstance(refused.detail, dict) else {}
                    raise ImportError_(f"{where.capitalize()}: {detail.get('message', 'this option is not allowed')}") from refused


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
    """
    import os

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ImportError_(f"The file is not valid YAML: {error}") from error
    if not isinstance(document, dict) or "board" not in document:
        raise ImportError_("The file has no 'board' section.")
    _refuse_if_oversized(document)
    _read_the_whole_thing_first(db, document, _user_of(db, owner_id), allow_locked)
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

    if replace is not None:
        board = replace
        for page in list(db.scalars(select(Page).where(Page.board_id == board.id))):
            db.delete(page)
        db.flush()
        board.name = name
        board.icon = str(meta.get("icon") or board.icon)
        board.background = dict(meta.get("background") or {})
        board.settings = dict(meta.get("settings") or {})
    else:
        board = Board(
            slug=unique_slug(db, slug or str(meta.get("slug") or name)), name=name, icon=str(meta.get("icon") or "layout-dashboard"),
            owner_id=owner_id, background=dict(meta.get("background") or {}), settings=dict(meta.get("settings") or {}),
            provisioned=provisioned, source_file=source_file,
        )
        db.add(board)
        db.flush()

    for position, page_doc in enumerate(document.get("pages") or []):
        page = Page(board_id=board.id, name=str(page_doc.get("name") or f"Page {position + 1}"), slug=slugify(str(page_doc.get("slug") or page_doc.get("name") or f"page-{position + 1}")), icon=str(page_doc.get("icon") or ""), position=position, layouts={key: [] for key in COLUMNS})
        db.add(page)
        db.flush()
        placer = Placer(page)
        for widget_doc in page_doc.get("widgets") or []:
            kind = str(widget_doc.get("kind") or "")
            try:
                adapter, widget_kind = split_widget_kind(kind)
            except KeyError as error:
                raise ImportError_(f"Unknown widget kind {kind!r}.") from error
            widget_type = adapter.widget(widget_kind)
            integration = by_name.get(str(widget_doc.get("integration"))) if widget_doc.get("integration") else None
            widget = Widget(page_id=page.id, kind=kind, title=str(widget_doc.get("title") or widget_type.label), icon=str(widget_doc.get("icon") or adapter.icon),
                            link=str(widget_doc.get("link") or ""), integration_id=integration.id if integration else None,
                            options=dict(widget_doc.get("options") or {}), refresh_seconds=widget_doc.get("refresh_seconds"))
            db.add(widget)
            db.flush()
            layout = widget_doc.get("layout") or {}
            if layout:
                spots = {}
                for key in COLUMNS:
                    item = layout.get(key) or layout.get("lg") or {}
                    spots[key] = {"x": int(item.get("x", 0)), "y": int(item.get("y", 0)), "w": min(COLUMNS[key], int(item.get("w", widget_type.default_size[0]))), "h": int(item.get("h", widget_type.default_size[1]))}
                placer.add_at(widget.id, spots)
            else:
                placer.add(widget.id, widget_type.default_size, widget_type.min_size)
            health_service.ensure_check_for_widget(db, widget)
        placer.finish()
    if not document.get("pages"):
        db.add(Page(board_id=board.id, name="Overview", slug="overview", position=0, layouts={key: [] for key in COLUMNS}))
    db.flush()
    return board
