"""An answer fetched with the old settings must never reach the board.

⚠️ This is the last corner of the fault reported three times as "I change
something in a card, it shows, then it jumps back, and only F5 gives me the
result".

``schedule`` cancels the running task when settings change, but cancelling
only takes effect at the next await, and between the adapter returning and the
answer being published there is none: telling, storing and sending all run
straight to the end. So a fetch that started before the save could still
overwrite the fresh answer with the settings from before it. It needs a fetch
to be in flight at the exact moment Save is pressed, which is why it turned up
in about one try in five and never in a unit test.

Here the race is not waited for. The adapter is held open until the settings
have been changed, and only then allowed to answer.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.base import WidgetData
from app.services.collector import collector
from app.services.state import live


class _HeldAdapter:
    """An adapter whose fetch waits until the test lets it finish."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.may_finish = asyncio.Event()
        self.saw: list[dict] = []

    def widget(self, kind: str):
        from app.adapters.base import WidgetType

        return WidgetType(kind="held", label="Held", description="", renderer="value", refresh_seconds=3600)

    async def fetch(self, widget_kind, config, options, ctx) -> WidgetData:
        self.saw.append(dict(options))
        self.reached.set()
        await self.may_finish.wait()
        return WidgetData(primary={"label": "Seconds", "value": options.get("seconds", "off")})

    def detect(self, *args, **kwargs):
        return []

    needs_integration = False
    kind = "held"


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> _HeldAdapter:
    adapter = _HeldAdapter()
    monkeypatch.setattr("app.services.collector.split_widget_kind", lambda kind: (adapter, "held"))
    monkeypatch.setattr("app.services.collector.shape_for_display", lambda data, *rest: data)
    return adapter


async def test_an_answer_from_before_the_save_is_thrown_away(held: _HeldAdapter, one_widget: int) -> None:
    """The whole point. Without the check the older answer wins, because it is
    published after the newer settings are already in the database."""
    slow = asyncio.ensure_future(collector.refresh(one_widget))
    await asyncio.wait_for(held.reached.wait(), timeout=5)

    # The save happens while the fetch is still in the air.
    _save_options(one_widget, {"seconds": "on"})
    collector.schedule(one_widget)
    await asyncio.sleep(0.05)

    held.may_finish.set()
    await asyncio.wait_for(slow, timeout=5)

    on_screen = live.get(one_widget)
    assert on_screen is None or on_screen.primary.get("value") != "off", (
        "the answer fetched with the settings from before the save reached the board")


async def test_an_answer_nobody_overtook_is_published(held: _HeldAdapter, one_widget: int) -> None:
    """⚠️ The other half, or the guard would be "publish nothing", which passes
    the test above and shows an empty board."""
    fetching = asyncio.ensure_future(collector.refresh(one_widget))
    await asyncio.wait_for(held.reached.wait(), timeout=5)
    held.may_finish.set()
    await asyncio.wait_for(fetching, timeout=5)

    on_screen = live.get(one_widget)
    assert on_screen is not None and on_screen.primary["value"] == "off"


# -- the widget these two act on ---------------------------------------------


def _save_options(widget_id: int, options: dict) -> None:
    from app.db import db_session
    from app.models import Widget

    with db_session() as db:
        widget = db.get(Widget, widget_id)
        widget.options = options
        db.commit()


@pytest.fixture
def one_widget(client) -> int:
    from tests.conftest import CSRF, setup_admin

    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    made = client.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "core.clock", "title": "Clock"},
        headers=CSRF,
    )
    assert made.status_code == 201, made.text
    widget_id = int(made.json()["widget"]["id"])
    _save_options(widget_id, {"seconds": "off"})
    live.forget(widget_id)
    yield widget_id
    live.forget(widget_id)


async def test_a_card_whose_settings_changed_keeps_refreshing(held: _HeldAdapter, one_widget: int) -> None:
    """⚠️ The dropped answer must not read as "this widget is gone".

    The loop ends when a refresh returns nothing, which is how a deleted
    widget stops its task. A dropped answer returning the same thing would
    have stopped the card for good: it would sit there until the next restart,
    and the only clue would be a card that never changes again.
    """
    slow = asyncio.ensure_future(collector.refresh(one_widget))
    await asyncio.wait_for(held.reached.wait(), timeout=5)
    _save_options(one_widget, {"seconds": "on"})
    collector.schedule(one_widget)
    await asyncio.sleep(0.05)
    held.may_finish.set()

    assert await asyncio.wait_for(slow, timeout=5) is not None, (
        "the loop was told this widget no longer exists and would have stopped refreshing it")
