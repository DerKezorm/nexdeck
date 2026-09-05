"""Boards: serialisation, layout placement, slugs, export and import."""

from __future__ import annotations

import re
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..adapters import get_adapter, split_widget_kind
from ..models import Board, Integration, Page, Widget
from . import health as health_service
from .integrations import export_config, store_config
from .state import live

COLUMNS = {"lg": 12, "md": 8, "sm": 4}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "board"


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


def place_widget(page: Page, widget_id: int, size: tuple[int, int], min_size: tuple[int, int]) -> None:
    """Give a new widget a spot at the bottom of every breakpoint."""
    layouts = dict(page.layouts or {})
    for key, cols in COLUMNS.items():
        items = list(layouts.get(key) or [])
        w = min(cols, max(1, size[0] if key == "lg" else max(1, round(size[0] * cols / 12)) or 1))
        h = size[1]
        if key == "sm":
            w = min(cols, max(2, w))
        bottom = max((item["y"] + item["h"] for item in items), default=0)
        x = 0
        # Try to fill the last row before opening a new one.
        row_items = [item for item in items if item["y"] + item["h"] == bottom]
        if row_items:
            right = max(item["x"] + item["w"] for item in row_items)
            top = min(item["y"] for item in row_items)
            if right + w <= cols:
                x, bottom = right, top
        items.append({"i": str(widget_id), "x": x, "y": bottom, "w": w, "h": h, "minW": min_size[0], "minH": min_size[1]})
        layouts[key] = items
    page.layouts = layouts


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


def widget_view(db: Session, widget: Widget) -> dict[str, Any]:
    try:
        adapter, kind = split_widget_kind(widget.kind)
        widget_type = adapter.widget(kind)
        renderer = widget_type.renderer
        beta = adapter.beta
        client_only = widget_type.client_only
        default_size, min_size = list(widget_type.default_size), list(widget_type.min_size)
    except KeyError:
        renderer = "value"
        beta = False
        client_only = False
        default_size, min_size = [3, 2], [1, 1]
    health = None
    if widget.health_check is not None:
        health = health_service.check_payload(widget.health_check)
        health["bars"] = health_service.uptime_bars(db, widget.id, health_service.bars_window(widget.options))
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
    for page in pages:
        widgets = [widget_view(db, w) for w in page.widgets]
        widget_ids.extend(w.id for w in page.widgets)
        page_views.append({
            "id": page.id, "name": page.name, "slug": page.slug, "icon": page.icon, "position": page.position,
            "layouts": {key: page.layouts.get(key, []) for key in COLUMNS} if page.layouts else {key: [] for key in COLUMNS},
            "sections": page.sections or [], "widgets": widgets,
        })
    view = {
        "id": board.id, "slug": board.slug, "name": board.name, "icon": board.icon, "owner_id": board.owner_id,
        "background": board.background or {"kind": "bundled", "value": "aurora"}, "settings": board.settings or {},
        "provisioned": board.provisioned, "permission": permission, "pages": page_views,
    }
    if include_live:
        view["live"] = {str(k): v.model_dump() for k, v in live.snapshot(widget_ids).items()}
    return view


def board_summary(db: Session, board: Board, permission: str) -> dict[str, Any]:
    pages = db.execute(select(Page.id, Page.name, Page.slug).where(Page.board_id == board.id).order_by(Page.position)).all()
    widgets = db.scalar(select(func.count(Widget.id)).join(Page).where(Page.board_id == board.id)) or 0
    return {
        "id": board.id, "slug": board.slug, "name": board.name, "icon": board.icon, "owner_id": board.owner_id,
        "permission": permission, "provisioned": board.provisioned, "position": board.position,
        "pages": [{"id": p.id, "name": p.name, "slug": p.slug} for p in pages], "widget_count": int(widgets),
    }


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------


def export_board(db: Session, board: Board) -> str:
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
        {"name": i.name, "kind": i.kind, "config": export_config(i), "demo": i.demo} for i in integrations.values()
    ]
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


class ImportError_(ValueError):
    pass


def import_board(db: Session, text: str, *, owner_id: int | None, slug: str | None = None, provisioned: bool = False, source_file: str = "", replace: Board | None = None) -> Board:
    """Create (or replace) a board from a YAML document."""
    import os

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ImportError_(f"The file is not valid YAML: {error}") from error
    if not isinstance(document, dict) or "board" not in document:
        raise ImportError_("The file has no 'board' section.")
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
            config = {}
            for key, value in (entry.get("config") or {}).items():
                if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                    value = os.environ.get(value[2:-1], "")
                config[key] = value
            existing = Integration(kind=entry["kind"], name=str(entry.get("name") or entry["kind"]), config=store_config(entry["kind"], config), demo=bool(entry.get("demo")), created_by=owner_id)
            db.add(existing)
            db.flush()
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
                layouts = dict(page.layouts or {})
                for key in COLUMNS:
                    item = layout.get(key) or layout.get("lg") or {}
                    entries = list(layouts.get(key) or [])
                    entries.append({"i": str(widget.id), "x": int(item.get("x", 0)), "y": int(item.get("y", 0)), "w": min(COLUMNS[key], int(item.get("w", widget_type.default_size[0]))), "h": int(item.get("h", widget_type.default_size[1]))})
                    layouts[key] = entries
                page.layouts = layouts
            else:
                place_widget(page, widget.id, widget_type.default_size, widget_type.min_size)
            health_service.ensure_check_for_widget(db, widget)
    if not document.get("pages"):
        db.add(Page(board_id=board.id, name="Overview", slug="overview", position=0, layouts={key: [] for key in COLUMNS}))
    db.flush()
    return board
