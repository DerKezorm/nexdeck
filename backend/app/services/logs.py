"""Container log tailing: one follower per log widget, lines kept for a few hours."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select

from ..adapters.docker import container_name, docker_client
from ..config import get_settings
from ..db import db_session
from ..models import LogLine, Page, Widget
from .integrations import resolve_config
from .sse import board_topic, hub

logger = logging.getLogger("nexdeck.logs")

MAX_LINE = 2000


class LogTailer:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def ensure(self, widget_id: int) -> None:
        task = self._tasks.get(widget_id)
        if task is None or task.done():
            self._tasks[widget_id] = asyncio.create_task(self._follow(widget_id), name=f"logs-{widget_id}")

    def stop_widget(self, widget_id: int) -> None:
        task = self._tasks.pop(widget_id, None)
        if task:
            task.cancel()

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        for task in self._tasks.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    def prune(self) -> None:
        cutoff = time.time() - get_settings().log_history_hours * 3600
        with db_session() as db:
            db.execute(delete(LogLine).where(LogLine.ts < cutoff))

    async def _follow(self, widget_id: int) -> None:
        while True:
            with db_session() as db:
                widget = db.get(Widget, widget_id)
                if widget is None or widget.kind != "docker.logs" or widget.integration is None:
                    return
                page = db.get(Page, widget.page_id)
                board_id = page.board_id if page else None
                config = resolve_config(widget.integration)
                demo = widget.integration.demo or get_settings().demo
                wanted = str((widget.options or {}).get("container") or "")
                integration_id = widget.integration.id
            source = f"{integration_id}:{wanted}"
            try:
                if demo:
                    await self._demo_lines(widget_id, source, board_id)
                else:
                    await self._docker_lines(config, wanted, widget_id, source, board_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                logger.info("Log follower for widget %s stopped (%s); retrying.", widget_id, error.__class__.__name__)
                self._emit(board_id, widget_id, f"[nexdeck] log stream interrupted: {error.__class__.__name__}, retrying", source)
            await asyncio.sleep(10)

    async def _docker_lines(self, config: dict, wanted: str, widget_id: int, source: str, board_id: int | None) -> None:
        async with docker_client(config) as client:
            containers = (await client.get("/containers/json", params={"all": 1})).json()
            match = next((c for c in containers if container_name(c) == wanted or c.get("Id", "").startswith(wanted)), None)
            if match is None:
                self._emit(board_id, widget_id, f"[nexdeck] no container named {wanted!r}", source)
                await asyncio.sleep(50)
                return
            inspect = (await client.get(f"/containers/{match['Id']}/json")).json()
            tty = bool((inspect.get("Config") or {}).get("Tty"))
            since = self._last_ts(source)
            params = {"follow": 1, "stdout": 1, "stderr": 1, "timestamps": 1, "tail": 200 if since == 0 else 0, "since": int(since)}
            async with client.stream("GET", f"/containers/{match['Id']}/logs", params=params, timeout=httpx.Timeout(None, connect=15)) as response:
                buffer = b""
                async for chunk in response.aiter_bytes():
                    buffer += chunk
                    if tty:
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            self._store(board_id, widget_id, source, line.decode("utf-8", "replace"))
                    else:
                        while len(buffer) >= 8:
                            size = int.from_bytes(buffer[4:8], "big")
                            if len(buffer) < 8 + size:
                                break
                            payload, buffer = buffer[8:8 + size], buffer[8 + size:]
                            for line in payload.decode("utf-8", "replace").splitlines():
                                self._store(board_id, widget_id, source, line)

    async def _demo_lines(self, widget_id: int, source: str, board_id: int | None) -> None:
        samples = [
            "INFO  request handled GET /api/health 200 in 2ms",
            "INFO  scheduler: refresh job finished (12 items)",
            "WARN  upstream responded slowly (1240ms)",
            "INFO  request handled GET /assets/app.js 304 in 1ms",
            "ERROR connection reset by peer while proxying /stream",
            "INFO  cache warmed: 214 entries",
        ]
        index = 0
        while True:
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            self._store(board_id, widget_id, source, f"{stamp} {samples[index % len(samples)]}")
            index += 1
            await asyncio.sleep(2 + (index % 3))

    def _last_ts(self, source: str) -> float:
        with db_session() as db:
            row = db.scalar(select(LogLine.ts).where(LogLine.source == source).order_by(LogLine.ts.desc()).limit(1))
        return float(row or 0)

    def _store(self, board_id: int | None, widget_id: int, source: str, line: str) -> None:
        line = line.rstrip("\r")[:MAX_LINE]
        if not line.strip():
            return
        ts = time.time()
        with db_session() as db:
            db.add(LogLine(source=source, ts=ts, line=line))
        self._emit(board_id, widget_id, line, source, ts)

    @staticmethod
    def _emit(board_id: int | None, widget_id: int, line: str, source: str, ts: float | None = None) -> None:
        if board_id is not None:
            hub.publish(board_topic(board_id), "log", {"widget_id": widget_id, "line": line, "ts": ts or time.time(), "source": source})


log_tailer = LogTailer()


def recent_lines(source: str, limit: int = 200) -> list[dict]:
    with db_session() as db:
        rows = db.execute(select(LogLine.ts, LogLine.line).where(LogLine.source == source).order_by(LogLine.ts.desc()).limit(limit)).all()
    return [{"ts": ts, "line": line} for ts, line in reversed(rows)]
