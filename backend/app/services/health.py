"""Reachability checks: HTTP, TCP and ping, with outages.

One loop wakes every few seconds and runs every check that is due. A failed
check marks ``down_since``; once a target has been down longer than the
threshold an outage is opened and announced, and the recovery closes it.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import db_session
from ..models import HealthCheck, Outage, Page, Widget, utcnow
from . import history, notify
from .sse import board_topic, hub

logger = logging.getLogger("nexdeck.health")

WAKE_SECONDS = 5
PARALLEL = 16


_clients: dict[bool, httpx.AsyncClient] = {}


def http_client(insecure: bool) -> httpx.AsyncClient:
    """One client per TLS mode, kept for the life of the process.

    A fresh client builds a TLS context and loads the CA bundle, which costs
    about a second on Windows. Measured as latency, that made a LAN service
    look a second away.
    """
    client = _clients.get(insecure)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(verify=not insecure, follow_redirects=True, headers={"User-Agent": "nexdeck-check"})
        _clients[insecure] = client
    return client


async def check_http(target: str, timeout: float, expect_status: int, insecure: bool) -> tuple[bool, int, str]:
    started = time.perf_counter()
    try:
        response = await http_client(insecure).get(target, timeout=timeout)
    except httpx.HTTPError as error:
        return False, int((time.perf_counter() - started) * 1000), error.__class__.__name__
    latency = int((time.perf_counter() - started) * 1000)
    if expect_status:
        return response.status_code == expect_status, latency, f"HTTP {response.status_code}"
    # Anything the server answered with, short of a server error, counts as
    # reachable: 401 from a login page still proves the service is up.
    return response.status_code < 500, latency, f"HTTP {response.status_code}"


async def check_tcp(target: str, timeout: float) -> tuple[bool, int, str]:
    host, _, port = target.rpartition(":")
    if not host or not port.isdigit():
        return False, 0, "Expected host:port"
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host.strip("[]"), int(port)), timeout)
    except (OSError, TimeoutError) as error:
        return False, int((time.perf_counter() - started) * 1000), error.__class__.__name__
    writer.close()
    return True, int((time.perf_counter() - started) * 1000), "open"


async def check_ping(target: str, timeout: float) -> tuple[bool, int, str]:
    count_flag = "-n" if platform.system() == "Windows" else "-c"
    wait_flag = "-w" if platform.system() == "Windows" else "-W"
    wait_value = str(int(timeout * 1000)) if platform.system() == "Windows" else str(int(timeout))
    started = time.perf_counter()
    try:
        process = await asyncio.create_subprocess_exec(
            "ping", count_flag, "1", wait_flag, wait_value, target,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        code = await asyncio.wait_for(process.wait(), timeout + 2)
    except NotImplementedError:
        # Windows with the selector event loop cannot spawn processes.
        return False, 0, "Ping is not available on this system; use an HTTP or TCP check."
    except (OSError, TimeoutError) as error:
        return False, int((time.perf_counter() - started) * 1000), error.__class__.__name__
    return code == 0, int((time.perf_counter() - started) * 1000), "reply" if code == 0 else "no reply"


def service_target(kind: str, widget: Widget | None) -> str:
    """The address of a widget's integration, shaped for the check: the URL, host:port, or the host."""
    if widget is None or widget.integration is None:
        return ""
    from ..adapters import get_adapter
    from .integrations import resolve_config

    try:
        url = get_adapter(widget.integration.kind).default_link(resolve_config(widget.integration))
    except Exception:
        # ⚠️ One connection whose secret cannot be read used to raise out of
        # the list comprehension that builds the whole round, and then no
        # check ran at all, for anyone, until the next restart. A target this
        # code cannot work out is one tile without a check, nothing more.
        logger.warning("The address of widget %s could not be worked out for its check.", widget.id, exc_info=True)
        return ""
    if kind == "http" or not url:
        return url
    parsed = urlsplit(url if "://" in url else f"http://{url}")
    host = parsed.hostname or ""
    if kind == "tcp":
        return f"{host}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
    return host


async def run_check(check: HealthCheck) -> tuple[bool, int, str]:
    timeout = float(check.timeout_seconds or 5)
    if check.kind == "tcp":
        return await check_tcp(check.target, timeout)
    if check.kind == "ping":
        return await check_ping(check.target, timeout)
    return await check_http(check.target, timeout, check.expect_status or 0, check.insecure)


class HealthService:
    def __init__(self) -> None:
        self.running = False
        self._task: asyncio.Task[None] | None = None
        self._next_due: dict[int, float] = {}

    async def start(self) -> None:
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="health")

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def reset(self, check_id: int) -> None:
        self._next_due.pop(check_id, None)

    async def _loop(self) -> None:
        while self.running:
            try:
                await self.run_due()
            except Exception:  # noqa: BLE001
                logger.exception("Health loop failed.")
            await asyncio.sleep(WAKE_SECONDS)

    async def run_due(self, force: bool = False) -> None:
        now = time.monotonic()
        with db_session() as db:
            checks = list(db.scalars(
                select(HealthCheck).options(selectinload(HealthCheck.widget).selectinload(Widget.integration)).where(HealthCheck.enabled.is_(True))
            ))
            due = [c for c in checks if force or self._next_due.get(c.id, 0) <= now]
            # A check without a target follows its widget's integration, read afresh every time.
            snapshot = [(c.id, c.kind, c.target or service_target(c.kind, c.widget), c.timeout_seconds, c.expect_status, c.insecure, c.interval_seconds) for c in due]
        if not snapshot:
            return
        semaphore = asyncio.Semaphore(PARALLEL)

        async def one(row: tuple) -> None:
            check_id, kind, target, timeout, expect, insecure, interval = row
            async with semaphore:
                probe = HealthCheck(id=check_id, kind=kind, target=target, timeout_seconds=timeout,
                                    expect_status=expect, insecure=insecure)
                try:
                    ok, latency, detail = await run_check(probe)
                except Exception as error:  # noqa: BLE001 - one broken check must not stop the others
                    logger.warning("Check %s (%s %s) failed: %s", check_id, kind, target, error.__class__.__name__)
                    ok, latency, detail = False, 0, f"Check failed: {error.__class__.__name__}"
            self._next_due[check_id] = time.monotonic() + max(5, interval or get_settings().health_interval_seconds)
            self._record(check_id, ok, latency, detail)

        await asyncio.gather(*(one(row) for row in snapshot))

    def _record(self, check_id: int, ok: bool, latency: int, detail: str) -> None:
        settings = get_settings()
        now = utcnow()
        with db_session() as db:
            check = db.scalar(
                select(HealthCheck).options(selectinload(HealthCheck.widget)).where(HealthCheck.id == check_id)
            )
            if check is None:
                return
            was_ok = check.last_ok
            check.last_ok = ok
            check.last_latency_ms = latency
            check.last_checked_at = now
            check.last_error = "" if ok else detail[:300]
            name = (check.widget.title if check.widget else "") or check.target
            board_id = None
            if check.widget is not None:
                page = db.get(Page, check.widget.page_id)
                board_id = page.board_id if page else None
                history.record(db, check.widget.id, {"latency": float(latency), "up": 1.0 if ok else 0.0})
            announce: tuple[str, str, str, str] | None = None
            if ok:
                if check.down_since is not None:
                    open_outage = db.scalar(
                        select(Outage).where(Outage.check_id == check.id, Outage.ended_at.is_(None))
                    )
                    if open_outage is not None:
                        open_outage.ended_at = now
                        if open_outage.announced:
                            length = int((now - open_outage.started_at).total_seconds())
                            announce = ("recovery", f"{name} is back", f"{name} answers again after {length // 60} minutes.", "info")
                check.down_since = None
            else:
                if check.down_since is None:
                    check.down_since = now
                    db.add(Outage(check_id=check.id, started_at=now))
                else:
                    down_for = (now - check.down_since).total_seconds()
                    if down_for >= settings.outage_threshold_seconds:
                        open_outage = db.scalar(
                            select(Outage).where(Outage.check_id == check.id, Outage.ended_at.is_(None))
                        )
                        if open_outage is not None and not open_outage.announced:
                            open_outage.announced = True
                            announce = ("outage", f"{name} is down", f"{name} has not answered for {int(down_for // 60)} minutes ({detail}).", "error")
            payload = {
                "check_id": check.id, "widget_id": check.widget_id, "ok": ok, "latency_ms": latency,
                "detail": detail, "down_since": check.down_since.isoformat() if check.down_since else None,
                "changed": was_ok is not None and was_ok != ok,
                # The tile's bars travel with every result; otherwise they only
                # moved when the whole board was loaded again.
                "bars": uptime_bars(db, check.widget.id, bars_window(check.widget.options)) if check.widget is not None else None,
            }
        if board_id is not None:
            hub.publish(board_topic(board_id), "health", payload)
        if announce is not None:
            event, title, body, level = announce
            notify.emit(event, title, body, level=level)


health = HealthService()


def check_payload(check: HealthCheck) -> dict:
    return {
        "id": check.id,
        "kind": check.kind,
        "target": check.target,
        "follows_integration": not check.target,
        "interval_seconds": check.interval_seconds,
        "timeout_seconds": check.timeout_seconds,
        "expect_status": check.expect_status,
        "insecure": check.insecure,
        "enabled": check.enabled,
        "last_ok": check.last_ok,
        "last_latency_ms": check.last_latency_ms,
        "last_checked_at": check.last_checked_at.isoformat() if check.last_checked_at else None,
        "last_error": check.last_error,
        "down_since": check.down_since.isoformat() if check.down_since else None,
    }


def widget_target(widget: Widget) -> str:
    return widget.link or ""


def ensure_check_for_widget(db, widget: Widget) -> HealthCheck | None:  # noqa: ANN001
    """App tiles get a check on their link automatically."""
    wants = widget.kind == "core.app" and bool(widget.link) and widget.options.get("check", True)
    existing = widget.health_check
    if wants and existing is None:
        existing = HealthCheck(widget_id=widget.id, target=widget.link, kind="http",
                               interval_seconds=get_settings().health_interval_seconds)
        db.add(existing)
    elif wants and existing is not None and existing.target != widget.link and existing.kind == "http":
        existing.target = widget.link
    elif not wants and existing is not None and widget.kind == "core.app":
        db.delete(existing)
        return None
    return existing


#: The windows an app tile can show: hours covered and number of bars.
BAR_WINDOWS: dict[str, tuple[int, int]] = {"24h": (24, 48), "6h": (6, 48), "1h": (1, 60)}
LIVE_BARS = 48


def bars_window(options: dict | None) -> str:
    window = str((options or {}).get("bars") or "24h")
    return window if window in BAR_WINDOWS or window == "live" else "24h"


def uptime_bars(db, widget_id: int, window: str = "24h") -> list[float | None]:  # noqa: ANN001
    """Availability as a row of bars: 1.0 up, 0.0 down, None unknown.

    ``24h``, ``6h`` and ``1h`` slice the window evenly; ``live`` takes the
    last checks as they were recorded, one bar each. Raw checks are kept for
    a few hours and then folded into minute averages, so an old "check" in
    the live row is really a minute.
    """
    if window == "live":
        points = history.series(db, widget_id, "up", hours=24)[-LIVE_BARS:]
        values: list[float | None] = [round(value, 2) for _ts, value in points]
        return [None] * (LIVE_BARS - len(values)) + values
    hours, bars = BAR_WINDOWS.get(window, BAR_WINDOWS["24h"])
    points = history.series(db, widget_id, "up", hours=hours)
    if not points:
        return [None] * bars
    now = int(time.time())
    slice_seconds = hours * 3600 / bars
    buckets: list[list[float]] = [[] for _ in range(bars)]
    for ts, value in points:
        index = min(bars - 1, int((ts - (now - hours * 3600)) / slice_seconds))
        if 0 <= index < bars:
            buckets[index].append(value)
    return [round(sum(b) / len(b), 2) if b else None for b in buckets]


def is_datetime(value) -> bool:  # noqa: ANN001
    return isinstance(value, datetime)
