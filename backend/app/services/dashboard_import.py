"""Boards from other dashboards: Homepage and Homarr.

What the other dashboard's files say becomes a **plan** first, shown to the
person before anything is made: the connections it would take or create,
with what is still missing, the cards page by page, each with a tick to
leave it out, and in words what has no counterpart here. The plan comes
back, possibly with missing values filled in and cards left out, and only
then are connections created and the board made, through the ordinary
import with the rights of whoever asked.

Homepage: every group of ``services.yaml`` becomes a page. A service whose
widget nexdeck has an adapter for becomes a connection and a card; one that
is only a link becomes an app tile, with a reachability check where
Homepage had one. ``bookmarks.yaml`` becomes bookmark cards, and
``widgets.yaml`` gives the clock, the search and the weather.

Homarr (up to 0.15, the JSON config): every category becomes a page, apps
the same way as Homepage's services, and the clock, weather, bookmark,
notebook and iframe widgets come along.

⚠️ Nothing pasted is ever read as a reference to the environment, and a
Homepage placeholder such as ``{{HOMEPAGE_VAR_SONARR_KEY}}`` is not taken
for the key it stands for: the field counts as missing and says why. Taken
as it came, it filled the field with text the service rejects, and the
connection failed only when the first card asked.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters import all_adapters, get_adapter
from ..adapters.base import Adapter, WidgetType
from ..models import Board, Integration, Role, User
from .boards import ImportError_, import_board
from .integrations import resolve_config, store_config, validate_required


class DashboardImportError(ValueError):
    pass


#: Homepage's and Homarr's names for a service, where they differ from ours.
RENAMED = {
    "adguardhome": "adguard",
    "changedetectionio": "changedetection",
    "diskstation": "synology",
    "paperlessngx": "paperless",
    "proxmoxbackupserver": "pbs",
    "whatsupdocker": "wud",
    "uptimekuma": "uptimekuma",
    "customapi": "jsonapi",
    "speedtesttracker": "speedtest",
    "nginxproxymanager": "npm",
}

#: Where each of our fields may find its value among the names the other
#: dashboards use, in order. Kinds that name things differently come first.
SOURCES: dict[str, tuple[str, ...]] = {
    "url": ("url",),
    "api_key": ("key", "apikey", "apiKey", "api_key", "token"),
    "token": ("key", "token", "apikey", "apiKey"),
    "password": ("password", "key"),
    "username": ("username", "user"),
    "email": ("username", "email"),
    "client_token": ("key", "token"),
    "security_token": ("key", "token"),
    "api_token": ("key", "token"),
    "profile": ("profile",),
    "site": ("site",),
}
PER_KIND: dict[str, dict[str, tuple[str, ...]]] = {
    "opnsense": {"api_key": ("username", "key"), "api_secret": ("password", "secret")},
    "proxmox": {"token_id": ("username",), "token_secret": ("password",)},
    "pbs": {"token_id": ("username",), "secret": ("password",)},
    "portainer": {"endpoint_id": ("env",)},
    "peanut": {"device": ("key", "device")},
    "glances": {"api_version": ("version",)},
    "pihole": {"password": ("key", "password")},
}

#: Which card stands for a service when the other dashboard showed "its" widget.
PREFERRED = ("summary", "status", "counts", "overview", "system", "library", "latest", "connection", "ups", "node", "vpn", "energy", "queue", "nowplaying", "monitors")

PLACEHOLDER = re.compile(r"\{\{\s*HOMEPAGE_(VAR|FILE)_[A-Z0-9_]+\s*\}\}")
#: More would not be a board anybody reads, and a file can name the same group a thousand times over.
MAX_CARDS = 300


def _kind_of(name: str | None) -> Adapter | None:
    if not name:
        return None
    wanted = RENAMED.get(str(name).lower().replace("-", "").replace("_", ""), str(name).lower())
    try:
        adapter = get_adapter(wanted)
    except KeyError:
        return None
    return adapter if adapter.needs_integration else None


def representative(adapter: Adapter) -> WidgetType | None:
    """The card that stands for the service: the first of PREFERRED it has
    that needs no option filled in by hand, else the first such card."""
    usable = [w for w in adapter.widgets if not any(f.required and f.default is None for f in w.options)]
    for name in PREFERRED:
        for widget in usable:
            if widget.kind == name:
                return widget
    return usable[0] if usable else None


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def settings_from(adapter: Adapter, given: dict[str, Any]) -> tuple[dict[str, str], list[str], list[str]]:
    """A connection's settings out of what the other dashboard had.

    Returns the settings, the required fields still missing, and the fields
    that held a Homepage placeholder instead of a value.
    """
    config: dict[str, str] = {}
    placeholders: list[str] = []
    for field in adapter.fields:
        for source in PER_KIND.get(adapter.kind, {}).get(field.name) or SOURCES.get(field.name, (field.name,)):
            value = _text(given.get(source))
            if not value:
                continue
            if PLACEHOLDER.search(value):
                placeholders.append(field.name)
                break
            config[field.name] = value
            break
    missing = [field.name for field in adapter.fields if field.required and not config.get(field.name)]
    return config, missing, placeholders


def _icon(value: Any, fallback: str) -> str:
    """Homepage writes ``sonarr.png``, ``mdi-…`` or an address; Homarr an address
    to the dashboard-icons collection. The collection's names are ours too."""
    text = _text(value)
    if not text:
        return fallback
    if text.startswith(("http://", "https://")):
        match = re.search(r"/(?:png|svg|webp)/([a-z0-9-]+)\.(?:png|svg|webp)$", text)
        return match.group(1) if match else text
    if text.startswith(("mdi-", "si-", "sh-")):
        return fallback
    return re.sub(r"\.(png|svg|webp)$", "", text)


def _link(value: Any) -> str:
    text = _text(value)
    return text if text.startswith(("http://", "https://")) else ""


def _same_address(one: str, other: str) -> bool:
    a, b = urlsplit(one.rstrip("/")), urlsplit(other.rstrip("/"))
    return (a.hostname or "", a.port, a.path.rstrip("/")) == (b.hostname or "", b.port, b.path.rstrip("/")) and bool(a.hostname)


class _Plan:
    """Collects connections, pages and notes while a file is read."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.connections: list[dict[str, Any]] = []
        self.pages: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.cards = 0

    def page(self, name: str) -> dict[str, Any]:
        for page in self.pages:
            if page["name"] == name:
                return page
        page = {"name": name[:80] or "Overview", "cards": []}
        self.pages.append(page)
        return page

    def card(self, page: dict[str, Any], **card: Any) -> None:
        if self.cards >= MAX_CARDS:
            if self.cards == MAX_CARDS:
                self.notes.append(f"Only the first {MAX_CARDS} cards are taken.")
                self.cards += 1
            return
        self.cards += 1
        page["cards"].append({"key": f"c{self.cards}", "include": True, "icon": "", "link": "", "options": {}, "connection": None, **card})

    def connection(self, adapter: Adapter, name: str, given: dict[str, Any], where: str) -> str:
        config, missing, placeholders = settings_from(adapter, given)
        key = f"n{len(self.connections) + 1}"
        for field in placeholders:
            self.notes.append(f"{where}: {field} is a Homepage placeholder, not a value. Fill it in below.")
        self.connections.append({
            "key": key, "kind": adapter.kind, "label": adapter.label, "icon": adapter.icon, "name": name[:80] or adapter.label,
            "config": config, "missing": missing,
            "secret": [field.name for field in adapter.fields if field.secret],
            "fields": [{"name": f.name, "label": f.label, "secret": f.secret, "required": f.required} for f in adapter.fields if f.type != "bool"],
            "use": "create", "existing": [],
        })
        return key

    def service(self, page: dict[str, Any], name: str, *, kind: str | None, given: dict[str, Any], link: str, icon: Any,
                description: str, check: bool, where: str) -> None:
        """One service: a connection and its card when there is an adapter, else a tile."""
        adapter = _kind_of(kind)
        if kind and adapter is None:
            self.notes.append(f"{where}: nexdeck has no counterpart for the {kind} widget; it becomes a tile.")
        options: dict[str, Any] = {}
        if adapter and adapter.kind == "jsonapi":
            # Its one card needs the path to the value, which the mapping gives.
            options = _custom_api(given)
            widget = adapter.widget("value") if options else None
        else:
            widget = representative(adapter) if adapter else None
        if adapter and widget:
            key = self.connection(adapter, name, given, where)
            self.card(page, kind=f"{adapter.kind}.{widget.kind}", title=name, icon=_icon(icon, adapter.icon), link=link,
                      connection=key, options=options)
            return
        self.card(page, kind="core.app", title=name, icon=_icon(icon, "lucide:link"), link=link,
                  options={"description": description[:200], "check": bool(check and link)})

    def finish(self) -> dict[str, Any]:
        self.pages = [page for page in self.pages if page["cards"]]
        if not self.pages:
            raise DashboardImportError("Nothing in these files becomes a card.")
        return {"source": self.source, "connections": self.connections, "pages": self.pages, "notes": self.notes}


def _custom_api(given: dict[str, Any]) -> dict[str, Any]:
    """Homepage's customapi: the first mapping becomes the value card."""
    mappings = given.get("mappings")
    first = mappings[0] if isinstance(mappings, list) and mappings and isinstance(mappings[0], dict) else None
    if not first:
        return {}
    field = first.get("field")
    if isinstance(field, dict):
        # {"a": {"b": "c"}} means a.b.c.
        parts: list[str] = []
        while isinstance(field, dict) and len(field) == 1:
            (name, field), = field.items()
            parts.append(str(name))
        if isinstance(field, str):
            parts.append(field)
        field = ".".join(parts)
    return {"value_path": _text(field), "label": _text(first.get("label")), "unit": _text(first.get("suffix"))} if _text(field) else {}


# -- Homepage ------------------------------------------------------------------


def _yaml(text: str, name: str) -> Any:
    if not text.strip():
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as failure:
        raise DashboardImportError(f"{name} is not valid YAML: {failure}") from failure


def _entries(block: Any) -> list[tuple[str, Any]]:
    """Homepage's lists of one-key mappings, as (name, value) pairs."""
    pairs: list[tuple[str, Any]] = []
    if isinstance(block, dict):
        return [(str(k), v) for k, v in block.items()]
    for item in block or []:
        if isinstance(item, dict):
            pairs += [(str(k), v) for k, v in item.items()]
    return pairs


def from_homepage(services: str, bookmarks: str = "", widgets: str = "") -> dict[str, Any]:
    plan = _Plan("homepage")
    found_services = _yaml(services, "services.yaml")
    found_bookmarks = _yaml(bookmarks, "bookmarks.yaml")
    found_widgets = _yaml(widgets, "widgets.yaml")
    if found_services is None and found_bookmarks is None and found_widgets is None:
        raise DashboardImportError("Paste at least one of the three files.")

    first = None
    for kind, options in _entries(found_widgets):
        options = options if isinstance(options, dict) else {}
        first = first or plan.page("Overview")
        if kind == "datetime":
            plan.card(first, kind="core.clock", title="Clock", options={"date": True})
        elif kind == "search":
            plan.card(first, kind="core.search", title="Search")
        elif kind in ("openmeteo", "openweathermap", "weatherapi"):
            weather = {key: options[key] for key in ("latitude", "longitude") if isinstance(options.get(key), (int, float))}
            if _text(options.get("label")):
                weather["place"] = _text(options.get("label"))
            plan.card(first, kind="weather.current", title="Weather", options=weather)
        else:
            plan.notes.append(f"widgets.yaml: the {kind} widget has no counterpart and is left out.")

    def group(name: str, items: Any, page: dict[str, Any]) -> None:
        for service, body in _entries(items):
            if not isinstance(body, (dict, list)):
                continue
            if isinstance(body, list):
                # A group inside a group: its services join the page they are on.
                group(service, body, page)
                continue
            widget = body.get("widget") if isinstance(body.get("widget"), dict) else None
            if isinstance(body.get("widgets"), list) and body["widgets"] and isinstance(body["widgets"][0], dict):
                widget = body["widgets"][0]
            link = _link(body.get("href")) or _link((widget or {}).get("url"))
            plan.service(page, service, kind=(widget or {}).get("type"), given={**(widget or {})}, link=link, icon=body.get("icon"),
                         description=_text(body.get("description")), check=bool(body.get("siteMonitor") or body.get("ping")),
                         where=f"{name} > {service}")

    for name, items in _entries(found_services):
        group(name, items, plan.page(name))

    for name, links in _entries(found_bookmarks):
        lines = []
        for title, body in _entries(links):
            entry = body[0] if isinstance(body, list) and body and isinstance(body[0], dict) else body if isinstance(body, dict) else {}
            href = _link(entry.get("href"))
            if href:
                icon = _icon(entry.get("icon"), "")
                lines.append(" | ".join(part for part in (title.replace("|", "/"), href, icon) if part))
        if lines:
            plan.card(first or plan.page("Bookmarks"), kind="core.bookmarks", title=name, options={"links": "\n".join(lines)})
    return plan.finish()


# -- Homarr --------------------------------------------------------------------


def from_homarr(text: str) -> dict[str, Any]:
    try:
        config = json.loads(text)
    except json.JSONDecodeError as failure:
        raise DashboardImportError(f"This is not Homarr's config JSON: {failure.msg}.") from failure
    if not isinstance(config, dict) or not isinstance(config.get("apps"), list):
        raise DashboardImportError("This is not Homarr's config: it has no list of apps. Homarr 1.0 and later keep boards in a database, not in this file.")
    plan = _Plan("homarr")
    categories = {str(c.get("id")): _text(c.get("name")) for c in config.get("categories") or [] if isinstance(c, dict)}

    def page_for(item: dict[str, Any]) -> dict[str, Any]:
        area = item.get("area") if isinstance(item.get("area"), dict) else {}
        category = categories.get(str((area.get("properties") or {}).get("id"))) if area.get("type") == "category" else None
        return plan.page(category or "Overview")

    for app in config["apps"]:
        if not isinstance(app, dict):
            continue
        integration = app.get("integration") if isinstance(app.get("integration"), dict) else {}
        given = {"url": app.get("url")}
        for prop in integration.get("properties") or []:
            if isinstance(prop, dict) and prop.get("field"):
                given[str(prop["field"])] = prop.get("value")
        behaviour = app.get("behaviour") if isinstance(app.get("behaviour"), dict) else {}
        appearance = app.get("appearance") if isinstance(app.get("appearance"), dict) else {}
        network = app.get("network") if isinstance(app.get("network"), dict) else {}
        name = _text(app.get("name")) or "App"
        plan.service(page_for(app), name, kind=integration.get("type") or None, given=given,
                     link=_link(behaviour.get("externalUrl")) or _link(app.get("url")), icon=appearance.get("iconUrl"),
                     description="", check=bool(network.get("enabledStatusChecker")), where=name)

    for widget in config.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        kind, props = str(widget.get("type") or ""), widget.get("properties") if isinstance(widget.get("properties"), dict) else {}
        page = page_for(widget)
        if kind == "date":
            plan.card(page, kind="core.clock", title="Clock", options={"date": bool(props.get("showDate", True))})
        elif kind == "weather":
            location = props.get("location") if isinstance(props.get("location"), dict) else {}
            weather = {key: location[key] for key in ("latitude", "longitude") if isinstance(location.get(key), (int, float))}
            if _text(location.get("name")):
                weather["place"] = _text(location.get("name"))
            plan.card(page, kind="weather.current", title="Weather", options=weather)
        elif kind == "bookmark":
            lines = [f"{_text(i.get('name')).replace('|', '/')} | {_link(i.get('href'))}" for i in props.get("items") or [] if isinstance(i, dict) and _link(i.get("href"))]
            if lines:
                plan.card(page, kind="core.bookmarks", title="Bookmarks", options={"links": "\n".join(lines)})
        elif kind == "notebook":
            plan.card(page, kind="core.markdown", title="Notes", options={"content": _text(props.get("content"))[:20000]})
        elif kind == "iframe" and _link(props.get("embedUrl")):
            plan.card(page, kind="core.iframe", title="Frame", options={"url": _link(props.get("embedUrl"))})
        else:
            plan.notes.append(f"The {kind or 'unnamed'} widget has no counterpart and is left out.")
    return plan.finish()


# -- both ------------------------------------------------------------------------


def detect(files: dict[str, str]) -> str:
    joined = "\n".join(files.values()).lstrip()
    return "homarr" if joined.startswith("{") else "homepage"


def preview(db: Session, user: User, source: str, files: dict[str, str]) -> dict[str, Any]:
    """The plan, with each connection matched against those this installation has."""
    source = detect(files) if source == "auto" else source
    if source == "homarr":
        plan = from_homarr(next((text for text in files.values() if text.strip()), ""))
    else:
        plan = from_homepage(files.get("services", ""), files.get("bookmarks", ""), files.get("widgets", ""))
    admin = user.role == Role.admin.value
    for connection in plan["connections"]:
        rows = db.scalars(select(Integration).where(Integration.kind == connection["kind"]).order_by(Integration.name)).all()
        usable = [row for row in rows if admin or not row.admin_only]
        connection["existing"] = [{"id": row.id, "name": row.name} for row in usable]
        # The same address is the same service: take it rather than make a twin.
        address = connection["config"].get("url", "")
        same = next((row for row in usable if address and _same_address(address, str(resolve_config(row).get("url", "")))), None)
        if same is not None:
            connection["use"] = same.id
        elif not admin:
            connection["use"] = usable[0].id if usable else None
    return plan


def apply(db: Session, user: User, plan: dict[str, Any], name: str) -> Board:
    """Create what the plan says and make the board.

    The plan came back from the browser, so it is read like any other input:
    kinds and fields are checked here, the board goes through the untrusted
    import, and only an administrator creates connections.
    """
    admin = user.role == Role.admin.value
    names: dict[str, tuple[str, str] | None] = {}
    made: list[Integration] = []
    for connection in plan.get("connections") or []:
        if not isinstance(connection, dict):
            continue
        key, use = str(connection.get("key")), connection.get("use")
        try:
            adapter = get_adapter(str(connection.get("kind")))
        except KeyError as failure:
            raise DashboardImportError(f"There is no adapter {connection.get('kind')!r}.") from failure
        if use is None:
            names[key] = None
        elif use == "create":
            if not admin:
                raise DashboardImportError("Only an administrator creates connections. Pick one that exists, or leave the cards out.")
            given = {field.name: _text((connection.get("config") or {}).get(field.name)) for field in adapter.fields if field.type != "bool"}
            config = store_config(adapter.kind, {k: v for k, v in given.items() if v})
            missing = validate_required(adapter.kind, config)
            label = _text(connection.get("name")) or adapter.label
            if missing:
                raise DashboardImportError(f"{label} still lacks {', '.join(missing)}. Fill it in or leave its cards out.")
            integration = Integration(kind=adapter.kind, name=_free_name(db, label, made), config=config, created_by=user.id)
            db.add(integration)
            db.flush()
            made.append(integration)
            names[key] = (integration.name, adapter.kind)
        else:
            existing = db.get(Integration, int(use))
            if existing is None or existing.kind != adapter.kind:
                raise DashboardImportError(f"Connection {use} is not a {adapter.label} connection.")
            names[key] = (existing.name, existing.kind)

    # ⚠️ The import finds a card's connection by name alone. Two connections of
    # one name, of two kinds, would put the cards of one on the other.
    chosen = {v for v in names.values() if v}
    if len({n for n, _k in chosen}) != len(chosen):
        raise DashboardImportError("Two of the connections chosen have the same name. Rename one first.")

    pages = []
    for page in plan.get("pages") or []:
        widgets = []
        for card in (page.get("cards") or []) if isinstance(page, dict) else []:
            if not isinstance(card, dict) or not card.get("include", True):
                continue
            target = names.get(str(card.get("connection"))) if card.get("connection") else None
            if card.get("connection") and target is None:
                continue
            widgets.append({
                "kind": str(card.get("kind")), "title": _text(card.get("title"))[:120], "icon": _text(card.get("icon"))[:200],
                "link": _link(card.get("link")), "integration": target[0] if target else None,
                "options": card.get("options") if isinstance(card.get("options"), dict) else {},
            })
        if widgets:
            pages.append({"name": _text(page.get("name"))[:80] or "Overview", "widgets": widgets})
    if not pages:
        raise DashboardImportError("Every card was left out, so there is no board to make.")
    document = {
        "nexdeck": 1,
        "board": {"name": name.strip()[:80] or "Imported", "icon": "layout-dashboard", "settings": {"columns": 24}},
        "integrations": [{"name": n, "kind": k} for n, k in chosen],
        "pages": pages,
    }
    try:
        return import_board(db, yaml.safe_dump(document, sort_keys=False, allow_unicode=True), owner_id=user.id, trusted=False, allow_locked=admin)
    except ImportError_ as failure:
        raise DashboardImportError(str(failure)) from failure


def _free_name(db: Session, wanted: str, made: list[Integration]) -> str:
    """A connection name nobody has yet: the import finds connections by name."""
    taken = {row for row in db.scalars(select(Integration.name))} | {row.name for row in made}
    name, number = wanted[:80], 2
    while name in taken:
        name = f"{wanted[:74]} ({number})"
        number += 1
    return name


def known_kinds() -> list[str]:
    """Every service kind the import can make a connection for, for the guards."""
    return sorted(adapter.kind for adapter in all_adapters() if adapter.needs_integration)
