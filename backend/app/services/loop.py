"""The main event loop, reachable from worker threads.

FastAPI runs synchronous route handlers in a thread pool. A handler that
creates or cancels a background task must hand that over to the loop the
collector runs on; ``asyncio.create_task`` from a worker thread has no loop
and raises. Everything that starts background work goes through here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger("nexdeck.loop")

_main: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _main
    _main = loop


def main_loop() -> asyncio.AbstractEventLoop | None:
    return _main


def _running() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def run_on_loop(function: Callable[[], None]) -> None:
    """Run ``function`` on the main loop: now when already there, soon otherwise."""
    running = _running()
    target = _main or running
    if target is None:
        # No loop at all: nothing background can run (e.g. plain unit tests).
        return
    if running is target:
        function()
    elif target.is_closed():
        return
    else:
        target.call_soon_threadsafe(function)


def spawn(factory: Callable[[], Coroutine[Any, Any, Any]], name: str = "") -> None:
    """Start a coroutine as a task on the main loop, from any thread."""

    def _start() -> None:
        loop = asyncio.get_running_loop()
        loop.create_task(factory(), name=name or None)

    run_on_loop(_start)


def run_and_wait(factory: Callable[[], Coroutine[Any, Any, Any]], timeout: float = 30.0) -> bool:
    """Run a coroutine on the main loop from a worker thread and wait for it.

    ⚠️ Only from a worker thread. Called on the loop itself this would wait for
    something that cannot start until the waiting stops, so it refuses that
    case rather than hanging. Restoring a backup needs it: it runs in a worker
    thread and has to bring the collector and the reachability loop to a stop
    before it replaces the database under them.

    Returns whether it actually ran. Without a loop there is nothing to stop,
    which is the ordinary case in a plain unit test.
    """
    target = _main
    if target is None or target.is_closed() or _running() is target:
        return False
    try:
        asyncio.run_coroutine_threadsafe(factory(), target).result(timeout)
    except Exception:  # noqa: BLE001 - a service that will not stop must not stop the rescue
        logger.exception("A background service did not come to a stop in time.")
        return False
    return True
