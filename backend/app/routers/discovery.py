"""Service discovery: containers as tile suggestions, labels as configuration.

Labels ``nexdeck.name``, ``nexdeck.url``, ``nexdeck.icon``, ``nexdeck.group``
and ``nexdeck.description`` describe a tile; Homepage's ``homepage.*`` labels
are understood as well, so a migration keeps its tiles.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..adapters.base import AdapterError, Context
from ..adapters.docker import ADAPTER as DOCKER
from ..adapters.docker import container_name
from ..deps import CurrentUser, DbSession, error, require_board
from ..models import Integration, Page, Widget
from ..services import health as health_service
from ..services.boards import place_widget, widget_view
from ..services.collector import collector
from ..services.icons import guess_from_image
from ..services.integrations import resolve_config
from ..services.sse import board_topic, hub

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


def suggestion(entry: dict[str, Any], host_hint: str) -> dict[str, Any]:
    labels = entry.get("Labels") or {}
    name = container_name(entry)

    def label(key: str) -> str:
        return str(labels.get(f"nexdeck.{key}") or labels.get(f"homepage.{key}") or "")

    url = label("url") or label("href")
    if not url:
        for port in entry.get("Ports") or []:
            public = port.get("PublicPort")
            if public:
                scheme = "https" if public in (443, 8443, 9443) else "http"
                url = f"{scheme}://{host_hint}:{public}"
                break
    icon = label("icon") or guess_from_image(entry.get("Image", ""))
    return {
        "container": name,
        "id": entry.get("Id", "")[:12],
        "image": entry.get("Image", ""),
        "running": entry.get("State") == "running",
        "name": label("name") or name.replace("-", " ").replace("_", " ").title(),
        "url": url,
        "icon": icon,
        "group": label("group"),
        "description": label("description"),
        "labelled": any(k.startswith(("nexdeck.", "homepage.")) for k in labels),
    }


@router.get("/docker", summary="Suggest tiles from running containers")
async def docker_suggestions(integration_id: int, user: CurrentUser, db: DbSession, host: str = "") -> list[dict]:
    """``host`` is used for links to published ports; it defaults to the engine's host name."""
    integration = db.get(Integration, integration_id)
    if integration is None or integration.kind != "docker":
        raise error("not_found", "There is no such Docker integration.", status.HTTP_404_NOT_FOUND)
    if integration.demo:
        return [suggestion(c, host or "docker.local") for c in _demo_containers()]
    config = resolve_config(integration)
    ctx = Context(collector.client, integration_id=integration.id, cache=collector._caches.setdefault(integration.id, {}))
    try:
        containers = await DOCKER.list_containers(config, ctx)
    except AdapterError as failure:
        raise error(failure.code, failure.message) from failure
    hint = host or _host_from(config.get("host", ""))
    return [suggestion(c, hint) for c in sorted(containers, key=container_name)]


class ApplyBody(BaseModel):
    page_id: int
    integration_id: int
    containers: list[str] = Field(default_factory=list)
    host: str = ""


@router.post("/docker/apply", summary="Create app tiles for chosen containers")
async def apply_suggestions(body: ApplyBody, user: CurrentUser, db: DbSession) -> dict:
    page = db.get(Page, body.page_id)
    if page is None:
        raise error("not_found", "There is no such page.", status.HTTP_404_NOT_FOUND)
    board, _ = require_board(db, str(page.board_id), user, "edit")
    suggestions = await docker_suggestions(body.integration_id, user, db, body.host)
    wanted = set(body.containers)
    created = []
    for entry in suggestions:
        if entry["container"] not in wanted:
            continue
        widget = Widget(page_id=page.id, kind="core.app", title=entry["name"], icon=entry["icon"], link=entry["url"],
                        options={"description": entry["description"], "check": bool(entry["url"])})
        db.add(widget)
        db.flush()
        place_widget(page, widget.id, (2, 1), (1, 1))
        health_service.ensure_check_for_widget(db, widget)
        created.append(widget)
    db.commit()
    for widget in created:
        db.refresh(widget)
        collector.schedule(widget.id)
    hub.publish(board_topic(board.id), "board", {"id": board.id, "changed": True})
    return {"created": [widget_view(db, w) for w in created], "layouts": page.layouts}


def _host_from(engine_host: str) -> str:
    if engine_host.startswith(("tcp://", "http://", "https://")):
        rest = engine_host.split("://", 1)[1]
        return rest.split("/")[0].split(":")[0]
    return "localhost"


def _demo_containers() -> list[dict[str, Any]]:
    return [
        {"Id": "a" * 12, "Names": ["/radarr"], "Image": "lscr.io/linuxserver/radarr:latest", "State": "running", "Labels": {"nexdeck.group": "Media"}, "Ports": [{"PublicPort": 7878}]},
        {"Id": "b" * 12, "Names": ["/sonarr"], "Image": "lscr.io/linuxserver/sonarr:latest", "State": "running", "Labels": {}, "Ports": [{"PublicPort": 8989}]},
        {"Id": "c" * 12, "Names": ["/jellyfin"], "Image": "jellyfin/jellyfin:latest", "State": "running", "Labels": {"homepage.name": "Jellyfin", "homepage.href": "https://jellyfin.example.com", "homepage.icon": "jellyfin"}, "Ports": [{"PublicPort": 8096}]},
        {"Id": "d" * 12, "Names": ["/pihole"], "Image": "pihole/pihole:latest", "State": "running", "Labels": {}, "Ports": [{"PublicPort": 80}]},
    ]


def _unused(select_=select) -> None:
    return None
