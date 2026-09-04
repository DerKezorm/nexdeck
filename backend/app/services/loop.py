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
