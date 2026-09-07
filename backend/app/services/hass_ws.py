"""Home Assistant WebSocket listener: state changes arrive instead of being polled.

One task per Home Assistant integration. It authenticates, loads all states
once, subscribes to ``state_changed`` and keeps ``ctx.cache["hass_states"]``
current. Whenever an entity that a widget shows changes, the widget is
refreshed right away.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from typing import Any

from sqlalchemy import select

from ..adapters.base import base_url
from ..db import db_session
from ..models import Integration, Widget
from .integrations import resolve_config
from .loop import run_on_loop, spawn

logger = logging.getLogger("nexdeck.hass")

RECONNECT_SECONDS = 15
#: The floor between two refreshes of one card, whatever the house does.
TOUCH_INTERVAL = 1.0


def ssl_options(url: str, config: dict[str, Any]) -> dict[str, Any]:
    """What to hand ``websockets.connect`` about certificates.

    ⚠️ The "Ignore TLS errors" box counts here too. Everything the adapter
    fetches over HTTP honoured it and this connection did not, so a Home
    Assistant behind a self-signed certificate showed its cards and never
    received a state change: the socket failed to open every twenty seconds,
    which reads as "reconnecting", not as "the certificate".
    """
    if not url.startswith("wss://") or not config.get("insecure"):
        return {}
    relaxed = ssl.create_default_context()
    relaxed.check_hostname = False
    relaxed.verify_mode = ssl.CERT_NONE
    return {"ssl": relaxed}


class HassListener:
    def __init__(self) -> None:
        #: entity -> widgets, per integration, so a state change is no query.
        self._watch_map: dict[int, dict[str, list[int]]] = {}
        #: When each widget was last refreshed by a state change.
        self._last_touch: dict[int, float] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self.running = False

    async def start(self) -> None:
        self.running = True
        with db_session() as db:
            ids = list(db.scalars(select(Integration.id).where(Integration.kind == "homeassistant", Integration.enabled.is_(True), Integration.demo.is_(False))))
        for integration_id in ids:
            self.watch(integration_id)

    async def stop(self) -> None:
        self.running = False
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    def watch(self, integration_id: int) -> None:
        def _start() -> None:
            self._cancel(integration_id)
            if self.running:
                self._tasks[integration_id] = asyncio.get_running_loop().create_task(self._run(integration_id), name=f"hass-{integration_id}")

        run_on_loop(_start)

    def unwatch(self, integration_id: int) -> None:
        run_on_loop(lambda: self._cancel(integration_id))

    def _cancel(self, integration_id: int) -> None:
        task = self._tasks.pop(integration_id, None)
        if task:
            task.cancel()

    async def _run(self, integration_id: int) -> None:
        import websockets

        from .collector import collector

        while self.running:
            with db_session() as db:
                integration = db.get(Integration, integration_id)
                if integration is None or not integration.enabled or integration.demo or integration.kind != "homeassistant":
                    return
                config = resolve_config(integration)
            cache = collector._caches.setdefault(integration_id, {})
            url = base_url(config).replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/api/websocket"
            try:
                async with websockets.connect(url, max_size=16 * 1024 * 1024, open_timeout=15,
                                              **ssl_options(url, config)) as socket:
                    await socket.recv()  # auth_required
                    await socket.send(json.dumps({"type": "auth", "access_token": config.get("token", "")}))
                    reply = json.loads(await socket.recv())
                    if reply.get("type") != "auth_ok":
                        logger.warning("Home Assistant %s rejected the token over WebSocket.", integration_id)
                        cache.pop("hass_states", None)
                        await asyncio.sleep(RECONNECT_SECONDS * 4)
                        continue
                    await socket.send(json.dumps({"id": 1, "type": "get_states"}))
                    await socket.send(json.dumps({"id": 2, "type": "subscribe_events", "event_type": "state_changed"}))
                    states: dict[str, Any] = cache.setdefault("hass_states", {})
                    async for raw in socket:
                        message = json.loads(raw)
                        if message.get("id") == 1 and message.get("type") == "result":
                            for entity in message.get("result") or []:
                                states[entity["entity_id"]] = entity
                            logger.info("Home Assistant %s: %d states loaded.", integration_id, len(states))
                        elif message.get("type") == "event":
                            data = (message.get("event") or {}).get("data") or {}
                            entity_id = data.get("entity_id")
                            new_state = data.get("new_state")
                            if entity_id and new_state:
                                states[entity_id] = new_state
                                self._touch(integration_id, entity_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                logger.info("Home Assistant %s WebSocket closed (%s); reconnecting.", integration_id, error.__class__.__name__)
                cache.pop("hass_states", None)
            await asyncio.sleep(RECONNECT_SECONDS)

    def _watchers(self, integration_id: int) -> dict[str, list[int]]:
        """Which widgets watch which entity, read once and kept.

        ⚠️ This used to be a database round trip per state change. A house
        with a few hundred entities sends dozens a second, and each one opened
        a session on the event loop and loaded every widget of the
        integration. The map only changes when a widget does, and
        ``forget_widgets`` is called then.
        """
        cached = self._watch_map.get(integration_id)
        if cached is not None:
            return cached
        found: dict[str, list[int]] = {}
        with db_session() as db:
            for widget in db.scalars(select(Widget).where(Widget.integration_id == integration_id)):
                options = widget.options or {}
                shown = [str(options.get("entity_id") or "")] + str(options.get("entity_ids") or "").splitlines()
                for entity in {name.strip() for name in shown if name.strip()}:
                    found.setdefault(entity, []).append(widget.id)
        self._watch_map[integration_id] = found
        return found

    def forget_widgets(self, integration_id: int | None) -> None:
        """Say that the widgets of this integration changed."""
        if integration_id is not None:
            self._watch_map.pop(integration_id, None)

    def _touch(self, integration_id: int, entity_id: str) -> None:
        """Refresh the widgets that show this entity, at most once per second each."""
        from .collector import collector

        now = time.monotonic()
        for widget_id in self._watchers(integration_id).get(entity_id, ()):
            # The promise in this docstring is kept here. A flapping sensor
            # used to refresh its card many times a second, whatever the
            # card's own interval said.
            if now - self._last_touch.get(widget_id, 0.0) < TOUCH_INTERVAL:
                continue
            self._last_touch[widget_id] = now
            spawn(lambda widget_id=widget_id: collector.refresh(widget_id))


hass_listener = HassListener()
