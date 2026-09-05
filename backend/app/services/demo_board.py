"""The starter board of a fresh installation, and the demo board.

The demo creates one integration per adapter in demo mode and a board that
shows every kind of widget with moving, invented data. It is what the
screenshots on the project page show and what a first visitor sees when
they choose "start with a demo".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..adapters import get_adapter, split_widget_kind
from ..models import Board, Integration, Page, Widget
from . import health as health_service
from .boards import COLUMNS, place_widget, unique_slug

Spec = tuple[str, str, str | None, dict[str, Any], tuple[int, int, int, int]]
"""(widget kind, title, integration kind or None, options, (x, y, w, h) on the large layout)"""

DEMO_PAGES: list[tuple[str, list[Spec]]] = [
    ("Overview", [
        ("core.clock", "Clock", None, {"label": "Home", "date": True}, (0, 0, 3, 2)),
        ("weather.current", "Weather", None, {"place": "Springfield", "latitude": 52.52, "longitude": 13.41}, (3, 0, 3, 2)),
        ("docker.load", "Docker load", "docker", {}, (6, 0, 3, 2)),
        ("nexview.requests", "Nexview requests", "nexview", {}, (9, 0, 3, 2)),
        ("docker.containers", "Containers", "docker", {}, (0, 2, 4, 4)),
        ("jellyfin.nowplaying", "Now playing", "jellyfin", {}, (4, 2, 4, 3)),
        ("radarr.queue", "Radarr queue", "radarr", {}, (8, 2, 4, 3)),
        ("core.app", "Radarr", None, {"description": "Movies"}, (4, 5, 2, 1)),
        ("core.app", "Sonarr", None, {"description": "Series"}, (6, 5, 2, 1)),
        ("core.app", "Jellyfin", None, {"description": "Media server"}, (8, 5, 2, 1)),
        ("core.app", "Pi-hole", None, {"description": "DNS filter"}, (10, 5, 2, 1)),
        ("proxmox.node", "Proxmox · pve", "proxmox", {}, (0, 6, 4, 2)),
        ("pihole.summary", "Pi-hole", "pihole", {}, (4, 6, 2, 2)),
        ("uptimekuma.monitors", "Uptime Kuma", "uptimekuma", {}, (6, 6, 3, 3)),
        ("calendar.upcoming", "Upcoming", None, {"sources": []}, (9, 6, 3, 3)),
        ("rss.headlines", "Homelab news", None, {"urls": "https://example.com/feed.xml", "limit": 6}, (0, 8, 4, 3)),
        ("speedtest.latest", "Speedtest", "speedtest", {}, (4, 8, 2, 2)),
        ("synology.system", "NAS · storage", "synology", {}, (6, 9, 4, 2)),
        ("homeassistant.entity", "Living room", "homeassistant", {"label": "Living room"}, (10, 9, 2, 2)),
    ]),
    ("Media", [
        ("plex.nowplaying", "Plex", "plex", {}, (0, 0, 4, 3)),
        ("jellyfin.library", "Jellyfin library", "jellyfin", {}, (4, 0, 2, 2)),
        ("seerr.requests", "Seerr requests", "seerr", {}, (6, 0, 3, 3)),
        ("sonarr.calendar", "Sonarr calendar", "sonarr", {}, (9, 0, 3, 3)),
        ("sonarr.queue", "Sonarr queue", "sonarr", {}, (0, 3, 4, 3)),
        ("sabnzbd.queue", "SABnzbd", "sabnzbd", {}, (4, 3, 4, 3)),
        ("qbittorrent.speed", "qBittorrent", "qbittorrent", {}, (8, 3, 2, 2)),
        ("lidarr.status", "Lidarr", "lidarr", {}, (10, 3, 2, 2)),
        ("prowlarr.indexers", "Prowlarr", "prowlarr", {}, (8, 5, 4, 3)),
        ("emby.nowplaying", "Emby", "emby", {}, (0, 6, 4, 2)),
        ("readarr.calendar", "Readarr", "readarr", {}, (4, 6, 4, 2)),
    ]),
    ("Network", [
        ("unifi.summary", "UniFi", "unifi", {}, (0, 0, 3, 2)),
        ("adguard.summary", "AdGuard Home", "adguard", {}, (3, 0, 2, 2)),
        ("unifi.devices", "UniFi devices", "unifi", {}, (5, 0, 3, 3)),
        ("uptimekuma.summary", "Monitors", "uptimekuma", {}, (8, 0, 2, 1)),
        ("prometheus.query", "Prometheus", "prometheus", {"label": "CPU", "unit": "%"}, (8, 1, 4, 2)),
        ("proxmox.guests", "Proxmox guests", "proxmox", {}, (0, 2, 5, 4)),
        ("truenas.pools", "TrueNAS pools", "truenas", {}, (5, 3, 3, 2)),
        ("unraid.system", "Unraid", "unraid", {}, (8, 3, 4, 2)),
        ("beszel.systems", "Beszel hosts", "beszel", {}, (5, 5, 3, 3)),
        ("glances.system", "Glances", "glances", {}, (8, 5, 4, 2)),
        ("portainer.summary", "Portainer", "portainer", {}, (8, 7, 2, 1)),
        ("core.markdown", "Notes", None, {"content": "**Rack notes**\n\n- UPS battery replaced 2026-08\n- Switch firmware due"}, (0, 6, 3, 2)),
        ("core.bookmarks", "Links", None, {}, (3, 6, 2, 2)),
        ("docker.logs", "Traefik log", "docker", {"container": "traefik"}, (0, 8, 8, 3)),
        ("jsonapi.value", "Server room", "jsonapi", {"label": "Server room", "unit": "°C", "value_path": "temperature"}, (8, 8, 2, 2)),
        ("homeassistant.entities", "House", "homeassistant", {"entity_ids": "light.kitchen\nswitch.garden_pump"}, (10, 8, 2, 3)),
    ]),
]

DEMO_ICONS = {"Radarr": "radarr", "Sonarr": "sonarr", "Jellyfin": "jellyfin", "Pi-hole": "pi-hole"}


def _integration(db: Session, cache: dict[str, Integration], kind: str, owner_id: int | None) -> Integration:
    if kind not in cache:
        adapter = get_adapter(kind)
        integration = Integration(kind=kind, name=f"{adapter.label} (demo)", config={"url": "http://demo.invalid"}, demo=True, created_by=owner_id)
        db.add(integration)
        db.flush()
        cache[kind] = integration
    return cache[kind]


def _layout_all(page: Page, widget_id: int, lg: tuple[int, int, int, int]) -> None:
    x, y, w, h = lg
    layouts = dict(page.layouts or {})
    layouts.setdefault("lg", []).append({"i": str(widget_id), "x": x, "y": y, "w": w, "h": h})
    # Medium and small screens reflow below one another; the grid packs them.
    layouts.setdefault("md", []).append({"i": str(widget_id), "x": (x * 8 // 12) % 8, "y": y, "w": max(2, min(8, round(w * 8 / 12))), "h": h})
    layouts.setdefault("sm", []).append({"i": str(widget_id), "x": 0 if w > 2 else (x % 2) * 2, "y": y * 2, "w": 4 if w > 2 else 2, "h": h})
    page.layouts = layouts


def create_demo(db: Session, owner_id: int | None) -> Board:
    cache: dict[str, Integration] = {}
    board = Board(slug=unique_slug(db, "home"), name="Home", icon="layout-dashboard", owner_id=owner_id, background={"kind": "bundled", "value": "aurora"})
    db.add(board)
    db.flush()
    for position, (page_name, specs) in enumerate(DEMO_PAGES):
        page = Page(board_id=board.id, name=page_name, slug=page_name.lower(), position=position, layouts={key: [] for key in COLUMNS})
        db.add(page)
        db.flush()
        for kind, title, integration_kind, options, lg in specs:
            adapter, _ = split_widget_kind(kind)
            integration = _integration(db, cache, integration_kind, owner_id) if integration_kind else None
            link = f"https://{title.lower().replace(' ', '-')}.example.com" if kind == "core.app" else ""
            widget = Widget(page_id=page.id, kind=kind, title=title, icon=DEMO_ICONS.get(title, adapter.icon if adapter.kind != "core" else ""), link=link,
                            integration_id=integration.id if integration else None, options=options)
            db.add(widget)
            db.flush()
            _layout_all(page, widget.id, lg)
            check = health_service.ensure_check_for_widget(db, widget)
            if check is not None:
                # Demo tiles point at example.com addresses; they are never probed.
                check.enabled = False
    db.flush()
    return board


def create_starter(db: Session, owner_id: int | None, docker_host: str = "") -> Board:
    board = Board(slug=unique_slug(db, "home"), name="Home", icon="layout-dashboard", owner_id=owner_id, background={"kind": "bundled", "value": "aurora"})
    db.add(board)
    db.flush()
    page = Page(board_id=board.id, name="Overview", slug="overview", position=0, layouts={key: [] for key in COLUMNS})
    db.add(page)
    db.flush()
    widgets: list[tuple[str, str, dict[str, Any], int | None]] = [
        ("core.clock", "Clock", {"date": True}, None),
        ("core.markdown", "Welcome", {"content": "**Welcome to nexdeck.**\n\nSwitch to edit mode with the pencil, add integrations under Settings, and drag widgets where you want them."}, None),
    ]
    if docker_host:
        integration = Integration(kind="docker", name="Docker", config={"host": docker_host, "insecure": False}, created_by=owner_id)
        db.add(integration)
        db.flush()
        widgets.append(("docker.containers", "Containers", {}, integration.id))
        widgets.append(("docker.load", "Docker load", {}, integration.id))
    for kind, title, options, integration_id in widgets:
        adapter, widget_kind = split_widget_kind(kind)
        widget_type = adapter.widget(widget_kind)
        widget = Widget(page_id=page.id, kind=kind, title=title, icon=adapter.icon if adapter.kind != "core" else "", options=options, integration_id=integration_id)
        db.add(widget)
        db.flush()
        place_widget(page, widget.id, widget_type.default_size, widget_type.min_size)
    db.flush()
    return board
