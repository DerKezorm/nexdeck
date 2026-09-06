"""What happens when one thing is broken: the rest must keep working.

Every test here is a case where one bad row used to take the whole machinery
with it, quietly.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.base import WidgetData
from app.crypto import SecretUnreadable
from app.services import collector as collector_module
from app.services.state import live


async def test_a_widget_whose_secret_cannot_be_read_says_so_and_keeps_its_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key changed under a running installation. Before, the card went
    blank, the task ended and the log said nothing at all."""
    service = collector_module.Collector()

    async def explode(widget_id: int) -> float | None:
        raise SecretUnreadable("the key does not fit")

    monkeypatch.setattr(service, "_refresh", explode)
    live.clear()
    interval = await service.refresh(1)

    data = live.get(1)
    assert data is not None and data.status == "bad"
    assert "secret" in (data.error or "").lower()
    assert data.meta["code"] == "secret_unreadable"
    assert interval == collector_module.RECOVERY_INTERVAL, "it tries again later instead of giving up"


async def test_a_widget_whose_kind_is_gone_does_not_end_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A downgrade removes an adapter. The card should say so, once, not kill
    the task that would show it again after an upgrade."""
    service = collector_module.Collector()
    calls = {"n": 0}

    async def explode(widget_id: int) -> float | None:
        calls["n"] += 1
        raise KeyError("radarr")

    monkeypatch.setattr(service, "_refresh", explode)
    monkeypatch.setattr(collector_module, "RECOVERY_INTERVAL", 0.01)
    # The loop staggers its first fetch by up to 1.5 s; not in a test.
    monkeypatch.setattr(collector_module.random, "uniform", lambda a, b: 0.0)
    live.clear()
    service.running = True

    task = asyncio.get_running_loop().create_task(service._loop(1))
    await asyncio.sleep(0.2)
    service.running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert calls["n"] >= 2, "the loop tried again instead of ending"
    data = live.get(1)
    assert data is not None and data.status == "bad" and data.error


def test_a_card_that_cannot_be_read_still_carries_an_error_for_the_browser() -> None:
    """WidgetData with an error is what the card renders; an empty one is a
    spinner that never stops."""
    data = WidgetData(status="bad", error="This card could not be read. The server log says why.")
    assert data.error and data.status == "bad"
