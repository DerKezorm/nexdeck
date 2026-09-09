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
from ..adapters.base import (
    AdapterError,
    Ask,
    Context,
    WidgetData,
    fill_in,
    outbound_client,
    shape_for_display,
)
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
        #: Counted up every time a widget's settings change, so an answer that
        #: was already being fetched when they changed can be recognised.
        #:
        #: ⚠️ ``schedule`` cancels the running task, but cancelling only takes
        #: effect at the next await, and between the adapter returning and the
        #: answer being published there is none: telling, storing and sending
        #: all run to the end. So a fetch made with the **old** options could
        #: still overwrite the fresh one, and the board showed the settings
        #: from before the save until something else refreshed it. On screen
        #: that is "I change something, it shows, it jumps back, and only F5
        #: gives me the result", which is what this page was reported for
        #: three times. It needs a fetch to be in flight at the moment Save is
        #: pressed, so it happened perhaps once in five tries.
        self._generation: dict[int, int] = {}
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
            self._client = outbound_client(
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
            # Anything still in the air was fetched with the settings from
            # before this call and must not be published.
            self._generation[widget_id] = self._generation.get(widget_id, 0) + 1
            if not self.running:
                return
            self._failures.pop(widget_id, None)
            self._tasks[widget_id] = asyncio.get_running_loop().create_task(self._loop(widget_id), name=f"widget-{widget_id}")

        run_on_loop(_start)

    def unschedule(self, widget_id: int) -> None:
        live.forget(widget_id)
        self._generation[widget_id] = self._generation.get(widget_id, 0) + 1
        run_on_loop(lambda: self._cancel(widget_id))

    def _cancel(self, widget_id: int) -> None:
        task = self._tasks.pop(widget_id, None)
        if task is not None:
            task.cancel()

    def _drop_cache(self, integration_id: int) -> None:
        """Throw away a connection's cache, and close what it was holding open.

        ⚠️ Four adapters keep an httpx client in there, because a Deluge or
        UniFi session is worth reusing between calls. Popping the cache left
        those clients with their connections open and nothing pointing at
        them: they were closed by the next restart and by nothing else.
        """
        cache = self._caches.pop(integration_id, None)
        for value in (cache or {}).values():
            if isinstance(value, httpx.AsyncClient) and not value.is_closed:
                spawn(value.aclose, name=f"close-client-{integration_id}")

    def forget_integration(self, integration_id: int) -> None:
        """The connection is gone. Nothing of it stays behind."""
        self._drop_cache(integration_id)

    def reschedule_integration(self, integration_id: int) -> None:
        self._drop_cache(integration_id)
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
        except Exception:  # noqa: BLE001
            # ⚠️ Anything at all. The two branches above cover what an adapter
            # is expected to raise; anything else came out of here and ended
            # the card's task, so the card froze on its last data and came back
            # only after a restart. And the text says nothing about the inside
            # of the server: it reaches every viewer of the board, guests
            # included. The reason goes to the log, where it belongs.
            logger.exception("Widget %s could not be refreshed.", widget_id)
            live.set(widget_id, WidgetData(
                status="bad",
                error="This card could not be read. The server log says why.",
                meta={"code": "unexpected"},
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
        # Which settings this answer belongs to. Read after the options, so a
        # change between the two counts as "changed" rather than being missed.
        mine = self._generation.get(widget_id, 0)
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

        if self._generation.get(widget_id, 0) != mine:
            # The settings changed while this was being fetched. The task that
            # replaced this one is already fetching with the new ones, so this
            # answer is thrown away rather than put on the board.
            logger.debug("Widget %s changed while it was being read; the older answer is dropped.", widget_id)
            return None

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

    # -- what a card may be asked to do --------------------------------------

    @staticmethod
    def _offered(data: WidgetData | None) -> list[tuple[str, dict[str, Any], Ask | None]]:
        """Every action the card last put in front of whoever is looking.

        Two places: the card's own buttons, and the buttons on each row of a
        list, which is where the container, the machine or the entity is named.

        The third part of each entry is the blank the card left for whoever
        presses it, or nothing, which is what almost every action is.
        """
        if data is None:
            return []
        offered = [(action.id, dict(action.params), action.ask) for action in data.actions]
        for item in data.items:
            for entry in (item.get("actions") or []) if isinstance(item, dict) else []:
                if isinstance(entry, dict) and entry.get("id"):
                    ask = entry.get("ask")
                    offered.append((
                        str(entry["id"]),
                        dict(entry.get("params") or {}),
                        Ask.model_validate(ask) if isinstance(ask, dict) else ask if isinstance(ask, Ask) else None,
                    ))
        return offered

    def _refuse_unless_offered(self, widget_id: int, action_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """A card may only be asked to do what it last offered to do.

        ⚠️ Until 07.09.2026 the name and the parameters of an action went
        through to the adapter as they arrived. ``action_id`` was checked
        against the adapter's own list, the parameters against nothing at all,
        and several adapters put a parameter straight into a path. Measured
        with the pinned httpx: a container id of ``../volumes/prune?x=`` turns
        ``POST /containers/{id}/start`` into ``POST /volumes/prune``, and the
        Docker socket is mounted by the compose file the README hands out.
        Home Assistant was worse: ``lock.unlock`` was never offered by any
        card and ran all the same, with a token that may do anything.

        The list of offered actions is the one the viewer just had in front of
        them, so this costs no query and refuses everything that was never on
        screen. A kiosk token counts as a viewer too, which is the point: it
        is the least trusted way in and the one that reaches this code.

        One action in three hundred leaves a blank for whoever presses it: a
        video address to fetch. That is the only parameter that may differ
        from what was offered, the adapter had to declare it as an
        :class:`Ask`, and it goes through :func:`fill_in` first. Returns the
        parameters the adapter is to be given, which is not always the ones
        that arrived.
        """
        offered = self._offered(live.get(widget_id))
        if not offered:
            raise AdapterError("This card is not offering any action right now.", code="no_such_action")
        given = dict(params or {})
        for offered_id, fixed, ask in offered:
            if offered_id != action_id:
                continue
            if ask is None:
                if given == fixed:
                    return given
                continue
            # The one blank the card declared is the only parameter that may
            # differ, and it has to survive its own declaration before the
            # adapter is handed it. Everything else still has to match.
            rest = {name: value for name, value in given.items() if name != ask.name}
            if rest != {name: value for name, value in fixed.items() if name != ask.name}:
                continue
            return {**rest, ask.name: fill_in(ask, given.get(ask.name))}
        logger.warning("Widget %s was asked for the action %r, which it did not offer.", widget_id, action_id)
        raise AdapterError("This card is not offering that action.", code="no_such_action")

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

        params = self._refuse_unless_offered(widget_id, action_id, params)
        adapter, widget_kind = split_widget_kind(kind)
        ok = True
        try:
            if demo:
                message = f"Demo mode: {action_id} would have run now."
            else:
                ctx = Context(
                    self.client, integration_id=integration_id, widget_id=widget_id,
                    cache=self._caches.setdefault(integration_id or 0, {}),
                    # ⚠️ A button card belongs to no service and acts on one.
                    # Without this it could be pressed and had nothing to press.
                    resolve_integration=self.resolve_integration,
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
