"""Pressing "refresh" again and again reaches the service once, not once per press.

⚠️ Every press was a fetch. Whoever may act on a board could hold the button,
or call the address in a loop, and send the server at the service behind the
card as fast as it answers: a login that locks after a few tries, a rate limit
at a cloud API, a NAS that wakes its disks. Still open in the check of
12.09.2026.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.adapters.base import WidgetData, WidgetType
from app.db import db_session
from app.migrations import migrate
from app.models import Board, Page, Widget
from app.services import collector as collector_module
from app.services.state import live


class _Counting:
    """An adapter that counts how often the service would have been asked."""

    needs_integration = False
    kind = "counting"

    def __init__(self) -> None:
        self.fetches = 0

    def widget(self, kind: str) -> WidgetType:
        return WidgetType(kind="counting", label="Counting", description="", renderer="value", refresh_seconds=3600)

    async def fetch(self, widget_kind, config, options, ctx) -> WidgetData:
        self.fetches += 1
        # A service takes a moment to answer; presses arriving meanwhile must not start their own fetch.
        await asyncio.sleep(0.01)
        return WidgetData(primary={"label": "Fetches", "value": self.fetches})

    def detect(self, *args, **kwargs):
        return []


@pytest.fixture
def counting(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> _Counting:
    migrate()
    live.clear()
    adapter = _Counting()
    monkeypatch.setattr(collector_module, "split_widget_kind", lambda kind: (adapter, "counting"))
    monkeypatch.setattr(collector_module, "shape_for_display", lambda data, *rest: data)
    return adapter


def _one_widget() -> int:
    with db_session() as db:
        board = Board(slug="wall", name="Wall")
        db.add(board)
        db.flush()
        page = Page(board_id=board.id, name="Main", slug="main")
        db.add(page)
        db.flush()
        widget = Widget(page_id=page.id, kind="counting.counting")
        db.add(widget)
        db.flush()
        return widget.id


async def test_presses_at_the_same_moment_share_one_fetch(counting: _Counting) -> None:
    service = collector_module.Collector()
    widget_id = _one_widget()
    try:
        answers = await asyncio.gather(*(service.refresh_now(widget_id) for _ in range(5)))
    finally:
        await service.stop()
    assert counting.fetches == 1
    assert [answer.primary if answer else None for answer in answers] == [{"label": "Fetches", "value": 1}] * 5


async def test_a_press_right_after_the_last_one_answers_from_it(counting: _Counting) -> None:
    service = collector_module.Collector()
    widget_id = _one_widget()
    try:
        await service.refresh_now(widget_id)
        again = await service.refresh_now(widget_id)
    finally:
        await service.stop()
    assert counting.fetches == 1
    assert again is not None and again.primary == {"label": "Fetches", "value": 1}


async def test_once_the_gap_has_passed_a_press_fetches_again(counting: _Counting, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other side: a minimum gap, not a button that works once."""
    monkeypatch.setattr(collector_module, "REFRESH_NOW_GAP", 0.0)
    service = collector_module.Collector()
    widget_id = _one_widget()
    try:
        await service.refresh_now(widget_id)
        again = await service.refresh_now(widget_id)
    finally:
        await service.stop()
    assert counting.fetches == 2
    assert again is not None and again.primary == {"label": "Fetches", "value": 2}


async def test_settings_saved_in_between_are_fetched_at_once(counting: _Counting) -> None:
    """A save right after a press must not be answered with what the old settings fetched."""
    service = collector_module.Collector()
    widget_id = _one_widget()
    try:
        await service.refresh_now(widget_id)
        service._generation[widget_id] = service._generation.get(widget_id, 0) + 1
        await service.refresh_now(widget_id)
    finally:
        await service.stop()
    assert counting.fetches == 2
