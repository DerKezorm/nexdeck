"""The collector: one background task per widget, polling at its own pace.

The server asks every service in the widget's interval, keeps the result in
the live state, records metrics for history and pushes the change to every
browser that shows the board. Ten open tabs cost the service one request,
not ten.

Failures back off: after repeated errors the interval doubles, up to five
minutes, and the widget shows the last error instead of stale numbers.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..adapters import split_widget_kind
from ..adapters.base import AdapterError, Context, WidgetData, shape_for_display
from ..config import get_settings
from ..crypto import SecretUnreadable
from ..db import db_session
from ..models import ActionLog, Integration, Widget, utcnow
from . import history
from .integrations import resolve_config
from .loop import run_on_loop, spawn
from .notify import emit
from .sse import board_topic, hub
from .state import live

logger = logging.getLogger("nexdeck.collector")

MAX_BACKOFF = 300
MIN_INTERVAL = 5
#: How long to wait before trying a card again that could not even be set up.
RECOVERY_INTERVAL = 60.0


class Collector:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._caches: dict[int, dict[str, Any]] = {}
        self._client: httpx.AsyncClient | None = None
        self._failures: dict[int, int] = {}
        #: What has already been told, so a card refreshing every thirty
        #: seconds does not send the same line a hundred times an hour.
        self._told: dict[str, float] = {}
        #: Cards already reported as broken; one line per breakage, not per try.
        self._broken: set[int] = set()
        self._tick_start = time.time()
        self.running = False

    # -- lifecycle -----------------------------------------------------------

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": "nexdeck"},
                timeout=15.0,
            )
        return self._client

    async def start(self) -> None:
        self.running = True
        with db_session() as db:
            widget_ids = list(db.scalars(select(Widget.id)))
        for widget_id in widget_ids:
            self.schedule(widget_id)
        logger.info("Collector started with %d widgets.", len(widget_ids))

    async def stop(self) -> None:
        self.running = False
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        await self._say_goodbye()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _say_goodbye(self) -> None:
        """Adapters holding a session at a service log out, so restarts do not pile sessions up."""
        from ..adapters import get_adapter

        for integration_id, cache in list(self._caches.items()):
            if not integration_id or not cache:
                continue
            try:
                with db_session() as db:
                    integration = db.get(Integration, integration_id)
                    if integration is None:
                        continue
                    adapter = get_adapter(integration.kind)
                    config = resolve_config(integration)
                ctx = Context(self.client, integration_id=integration_id, cache=cache)
                await asyncio.wait_for(adapter.close(config, ctx), timeout=3)
            except Exception:  # noqa: BLE001 - a goodbye that fails must not hold up the shutdown
                logger.debug("Integration %s could not say goodbye.", integration_id)

    def schedule(self, widget_id: int) -> None:
        """(Re)start the loop of one widget, e.g. after its settings changed.

        Safe to call from a worker thread: the task is created on the main loop.
        """

        def _start() -> None:
            self._cancel(widget_id)
            if not self.running:
                return
            self._failures.pop(widget_id, None)
            self._tasks[widget_id] = asyncio.get_running_loop().create_task(self._loop(widget_id), name=f"widget-{widget_id}")

        run_on_loop(_start)

    def unschedule(self, widget_id: int) -> None:
        live.forget(widget_id)
        run_on_loop(lambda: self._cancel(widget_id))

    def _cancel(self, widget_id: int) -> None:
        task = self._tasks.pop(widget_id, None)
        if task is not None:
            task.cancel()

    def reschedule_integration(self, integration_id: int) -> None:
        self._caches.pop(integration_id, None)
        with db_session() as db:
            ids = list(db.scalars(select(Widget.id).where(Widget.integration_id == integration_id)))
        for widget_id in ids:
            self.schedule(widget_id)

    @property
    def tick(self) -> int:
        return int(time.time() - self._tick_start)

    # -- the loop ------------------------------------------------------------

    async def _loop(self, widget_id: int) -> None:
        # Spread the first fetches so that a restart does not hit every
        # service at the same instant.
        await asyncio.sleep(random.uniform(0.05, 1.5))
        while self.running:
            try:
                interval = await self.refresh(widget_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # ⚠️ Anything that escapes here used to end the task for good.
                # Nothing restarts it and nothing prints it, so the card stayed
                # blank and the log stayed empty. Say it out loud, put it on
                # the card, and try again on a long interval.
                logger.exception("Widget %s could not be read.", widget_id)
                live.set(widget_id, WidgetData(
                    status="bad",
                    error="This card could not be read. The server log says why.",
                ))
                await asyncio.sleep(RECOVERY_INTERVAL)
                continue
            if interval is None:
                return
            await asyncio.sleep(interval)

    async def refresh(self, widget_id: int) -> float | None:
        """Fetch once, publish, and return the seconds until the next fetch.

        Everything that can fail before the adapter is even chosen (an
        unreadable secret, a kind this build does not have) is turned into a
        readable card here, so the caller never has to catch it.
        """
        try:
            return await self._refresh(widget_id)
        except asyncio.CancelledError:
            raise
        except AdapterError as failure:
            live.set(widget_id, WidgetData(status="bad", error=failure.message, meta={"code": failure.code, "hint": failure.hint}))
            return RECOVERY_INTERVAL
        except SecretUnreadable:
            logger.error("Widget %s has a secret this installation cannot read.", widget_id)
            live.set(widget_id, WidgetData(
                status="bad",
                error="A stored secret cannot be read with this installation's key.",
                meta={"code": "secret_unreadable", "hint": "The key changed. Enter the credentials of this connection again."},
            ))
            return RECOVERY_INTERVAL

    async def _refresh(self, widget_id: int) -> float | None:
        with db_session() as db:
            widget = db.scalar(
                select(Widget)
                .options(selectinload(Widget.integration), selectinload(Widget.page))
                .where(Widget.id == widget_id)
            )
            if widget is None:
                return None
            board_id = widget.page.board_id
            integration = widget.integration
            kind = widget.kind
            title = widget.title or widget.kind
            options = dict(widget.options or {})
            refresh_seconds = widget.refresh_seconds
            config = resolve_config(integration) if integration is not None else {}
            demo = self._demo_active(integration)
            integration_id = integration.id if integration else None
            # Demo integrations point nowhere; a card without a link is better
            # than a link to demo.invalid.
            link = widget.link or (integration and not demo and self._safe_link(kind, config)) or None

        try:
            adapter, widget_kind = split_widget_kind(kind)
        except KeyError as error:
            live.set(widget_id, WidgetData(status="unknown", error=str(error)))
            return None
        widget_type = adapter.widget(widget_kind)
        interval = max(MIN_INTERVAL, refresh_seconds or widget_type.refresh_seconds)
        # Held before the fetch overwrites it: the adapter needs both to see
        # what changed.
        previous = live.get(widget_id)

        try:
            if demo:
                data = adapter.demo(widget_kind, options, self.tick)
            else:
                if adapter.needs_integration and integration_id is None:
                    raise AdapterError(
                        "This widget needs a connection to a service.", code="no_integration",
                        hint="Open the widget settings and pick an integration.",
                    )
                ctx = Context(
                    self.client, integration_id=integration_id, widget_id=widget_id,
                    cache=self._caches.setdefault(integration_id or 0, {}),
                    resolve_integration=self.resolve_integration,
                )
                data = await asyncio.wait_for(adapter.fetch(widget_kind, config, options, ctx), timeout=60)
            self._failures.pop(widget_id, None)
            # Everything between the service and the screen, in one place the
            # preview uses too.
            data = shape_for_display(data, adapter, widget_kind, options)
            if data.link is None and link:
                data.link = link
            data.updated_at = time.time()
            self._mark_integration(integration_id, ok=True)
        except AdapterError as error:
            data = self._failure(widget_id, error.message, hint=error.hint, code=error.code)
            self._mark_integration(integration_id, ok=False, error=error.message)
        except TimeoutError:
            data = self._failure(widget_id, "The service did not answer within a minute.", code="timeout")
            self._mark_integration(integration_id, ok=False, error="timeout")
        except Exception as error:  # noqa: BLE001 - one broken adapter must not stop the others
            logger.exception("Widget %s (%s) failed.", widget_id, kind)
            data = self._failure(widget_id, f"Unexpected error: {error.__class__.__name__}.", code="crash")
            self._mark_integration(integration_id, ok=False, error=error.__class__.__name__)

        self._tell_about(widget_id, title, adapter, widget_kind, previous, data, options)
        live.set(widget_id, data)
        if data.metrics and not data.error:
            with db_session() as db:
                history.record(db, widget_id, data.metrics)
        hub.publish(board_topic(board_id), "widget", {"id": widget_id, "data": data.model_dump()})

        failures = self._failures.get(widget_id, 0)
        if failures:
            return min(MAX_BACKOFF, interval * (2 ** min(failures, 6)))
        return interval

    def _failure(self, widget_id: int, message: str, *, code: str, hint: str = "") -> WidgetData:
        self._failures[widget_id] = self._failures.get(widget_id, 0) + 1
        previous = live.get(widget_id)
        data = WidgetData(status="unknown", error=message, meta={"code": code, "hint": hint})
        if previous is not None and not previous.error:
            # Keep the last good numbers visible, greyed out by the error.
            data.primary = previous.primary
            data.secondary = previous.secondary
            data.items = previous.items
            data.link = previous.link
            data.meta["stale_since"] = previous.updated_at
        return data

    def _demo_active(self, integration: Integration | None) -> bool:
        if get_settings().demo:
            return True
        if integration is not None and integration.demo:
            return True
        return demo_flag()

    @staticmethod
    def _safe_link(kind: str, config: dict[str, Any]) -> str:
        try:
            adapter, _ = split_widget_kind(kind)
            return adapter.default_link(config)
        except Exception:  # noqa: BLE001
            return ""

    def _mark_integration(self, integration_id: int | None, *, ok: bool, error: str = "") -> None:
        if integration_id is None:
            return
        key = f"mark:{integration_id}"
        cache = self._caches.setdefault(integration_id, {})
        last = cache.get(key)
        # Throttle writes: once a minute unless the outcome changed.
        if last and last[0] == ok and last[1] > time.monotonic():
            return
        cache[key] = (ok, time.monotonic() + 60)
        with db_session() as db:
            integration = db.get(Integration, integration_id)
            if integration is None:
                return
            if ok:
                integration.last_ok_at = utcnow()
                integration.last_error = ""
            else:
                integration.last_error = error[:500]

    async def resolve_integration(self, integration_id: int) -> tuple[Any, dict[str, Any], Context]:
        """For widgets that combine several integrations, such as the calendar."""
        from ..adapters import get_adapter

        with db_session() as db:
            integration = db.get(Integration, integration_id)
            if integration is None or not integration.enabled:
                raise AdapterError(f"Integration {integration_id} is missing or disabled.", code="no_integration")
            adapter = get_adapter(integration.kind)
            config = resolve_config(integration)
        ctx = Context(self.client, integration_id=integration_id, cache=self._caches.setdefault(integration_id, {}))
        return adapter, config, ctx

    # -- on demand -----------------------------------------------------------

    async def preview(self, widget_id: int, options: dict[str, Any], integration_id: int | None) -> WidgetData:
        """Fetch once with draft options and integration. Nothing is published or recorded."""
        with db_session() as db:
            widget = db.get(Widget, widget_id)
            if widget is None:
                return WidgetData(status="unknown", error="There is no such widget.")
            kind = widget.kind
            integration = db.get(Integration, integration_id) if integration_id is not None else None
            config = resolve_config(integration) if integration is not None else {}
            demo = self._demo_active(integration)
        try:
            adapter, widget_kind = split_widget_kind(kind)
        except KeyError as error:
            return WidgetData(status="unknown", error=str(error))
        try:
            if demo:
                return shape_for_display(adapter.demo(widget_kind, options, self.tick), adapter, widget_kind, options, for_settings=True)
            if adapter.needs_integration and integration is None:
                raise AdapterError(
                    "This widget needs a connection to a service.", code="no_integration",
                    hint="Pick an integration first.",
                )
            ctx = Context(
                self.client, integration_id=integration_id, widget_id=widget_id,
                cache=self._caches.setdefault(integration_id or 0, {}),
                resolve_integration=self.resolve_integration,
            )
            fetched = await asyncio.wait_for(adapter.fetch(widget_kind, config, options, ctx), timeout=20)
            return shape_for_display(fetched, adapter, widget_kind, options, for_settings=True)
        except AdapterError as error:
            return WidgetData(status="unknown", error=error.message, meta={"code": error.code, "hint": error.hint})
        except TimeoutError:
            return WidgetData(status="unknown", error="The service did not answer within twenty seconds.", meta={"code": "timeout"})
        except Exception as error:  # noqa: BLE001 - a broken adapter must answer the preview, not crash it
            logger.exception("Preview of widget %s (%s) failed.", widget_id, kind)
            return WidgetData(status="unknown", error=f"Unexpected error: {error.__class__.__name__}.", meta={"code": "crash"})

    def _tell_about(self, widget_id: int, title: str, adapter: Any, widget_kind: str,
                    before: WidgetData | None, after: WidgetData, options: dict[str, Any]) -> None:
        """Ask the adapter what happened, and pass it on once.

        ⚠️ Once. A card refreshing every thirty seconds would otherwise send
        the same line a hundred and twenty times an hour, and the second one
        already costs more trust than the first one earns.
        """
        if after.error:
            self._tell_about_failure(widget_id, title, after)
            return
        self._broken.discard(widget_id)
        try:
            found = adapter.detect(widget_kind, before, after, options)
        except Exception:  # noqa: BLE001 - a bad detector must not stop the card
            logger.exception("The detector of widget %s failed.", widget_id)
            return
        now = time.time()
        for detected in found:
            key = f"{widget_id}:{detected.dedupe_key()}"
            if now - self._told.get(key, 0.0) < detected.quiet_seconds:
                continue
            self._told[key] = now
            self._forget_old_keys(now)
            logger.info("%s on %r: %s", detected.event, title, detected.title)
            emit(detected.event, detected.title, detected.body,
                 level="warn" if detected.level in ("warn", "bad") else "info")

    def _tell_about_failure(self, widget_id: int, title: str, data: WidgetData) -> None:
        """A card that stopped working, said once and not on every retry."""
        if widget_id in self._broken:
            return
        self._broken.add(widget_id)
        code = str((data.meta or {}).get("code") or "")
        if code == "auth_failed":
            emit("auth_rejected", f"{title}: the service rejected its credentials",
                 data.error or "", level="warn")
        else:
            emit("widget_broken", f"{title} stopped working", data.error or "", level="warn")

    def _forget_old_keys(self, now: float) -> None:
        """⚠️ Without this the note of what was already told grows for the life
        of the process, one entry per distinct thing ever seen."""
        if len(self._told) <= 500:
            return
        for key in [k for k, when in self._told.items() if now - when > 86400]:
            self._told.pop(key, None)

    async def refresh_now(self, widget_id: int) -> WidgetData | None:
        await self.refresh(widget_id)
        return live.get(widget_id)

    async def run_action(
        self, widget_id: int, action_id: str, params: dict[str, Any], *, actor: str, user_id: int | None
    ) -> str:
        with db_session() as db:
            widget = db.scalar(
                select(Widget).options(selectinload(Widget.integration)).where(Widget.id == widget_id)
            )
            if widget is None:
                raise AdapterError("This widget no longer exists.", code="not_found")
            integration = widget.integration
            config = resolve_config(integration) if integration else {}
            options = dict(widget.options or {})
            kind = widget.kind
            integration_id = integration.id if integration else None
            demo = self._demo_active(integration)

        adapter, widget_kind = split_widget_kind(kind)
        ok = True
        try:
            if demo:
                message = f"Demo mode: {action_id} would have run now."
            else:
                ctx = Context(
                    self.client, integration_id=integration_id, widget_id=widget_id,
                    cache=self._caches.setdefault(integration_id or 0, {}),
                )
                message = await adapter.action(widget_kind, action_id, params, config, options, ctx)
        except AdapterError as error:
            ok = False
            message = error.message
        with db_session() as db:
            db.add(
                ActionLog(
                    user_id=user_id, actor=actor, widget_id=widget_id, integration_id=integration_id,
                    action=action_id, params=params, ok=ok, message=message[:400],
                )
            )
        if not ok:
            raise AdapterError(message, code="action_failed")
        # Show the effect right away instead of waiting for the next interval.
        spawn(lambda: self.refresh(widget_id), name=f"refresh-{widget_id}")
        return message


_demo_flag = False


def demo_flag() -> bool:
    return _demo_flag


def set_demo_flag(value: bool) -> None:
    global _demo_flag
    _demo_flag = value


collector = Collector()
