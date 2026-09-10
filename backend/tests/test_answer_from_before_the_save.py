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

⚠️ Two loops are in play, and every trap in this file comes from that. The
``client`` fixture yields inside ``with TestClient(app)``, so the app's
lifespan is running and ``loop._main`` points at the loop the TestClient runs
the app on, in another thread; the test itself runs on the pytest-asyncio
loop. What follows from that is written down at ``_the_app_loop_has_caught_up``
and at ``one_widget``.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.adapters.base import WidgetData
from app.services.collector import collector
from app.services.loop import main_loop
from app.services.state import live


class _HeldAdapter:
    """An adapter whose fetch waits until the test lets it finish."""

    def __init__(self, held_loop: asyncio.AbstractEventLoop) -> None:
        self.held_loop = held_loop
        self.reached = asyncio.Event()
        self.may_finish = asyncio.Event()
        self.saw: list[dict] = []

    def widget(self, kind: str):
        from app.adapters.base import WidgetType

        return WidgetType(kind="held", label="Held", description="", renderer="value", refresh_seconds=3600)

    async def fetch(self, widget_kind, config, options, ctx) -> WidgetData:
        self.saw.append(dict(options))
        answer = WidgetData(primary={"label": "Seconds", "value": options.get("seconds", "off")})
        if asyncio.get_running_loop() is not self.held_loop:
            # ⚠️ Only the fetch this test started is held. The patch below
            # replaces the adapter for the whole process, so the widget loops
            # the app runs on its own loop come through here too, and the two
            # events belong to the loop that first waited on them: from the
            # other loop, waiting raises "bound to a different event loop".
            # That crash was published as a card with no primary at all, and
            # the assertion below then died on ``None.get`` instead of saying
            # what was wrong. Measured once in ten runs on 09.09.2026.
            return answer
        self.reached.set()
        await self.may_finish.wait()
        return answer

    def detect(self, *args, **kwargs):
        return []

    needs_integration = False
    kind = "held"


@pytest.fixture
async def held(monkeypatch: pytest.MonkeyPatch) -> _HeldAdapter:
    adapter = _HeldAdapter(asyncio.get_running_loop())
    monkeypatch.setattr("app.services.collector.split_widget_kind", lambda kind: (adapter, "held"))
    monkeypatch.setattr("app.services.collector.shape_for_display", lambda data, *rest: data)
    return adapter


# -- waiting for the save, not for the clock ---------------------------------


def _the_app_loop_has_caught_up() -> None:
    """Return once everything already handed to the app's loop has run.

    ``collector.schedule`` does not take effect here and now: ``run_on_loop``
    sees that ``_main`` is a different loop and hands the work over with
    ``call_soon_threadsafe``. Callbacks queued on a loop run in the order they
    arrived, so once this one has come back, everything queued before it has
    run as well. That is a property of the loop, not a guess about how fast
    the machine is.

    Blocking is deliberate. The app's loop lives in its own thread, so waiting
    for it here holds up nothing that could answer it.
    """
    app_loop = main_loop()
    if app_loop is None or app_loop.is_closed():
        # No foreign loop, so ``run_on_loop`` already ran everything inline.
        return
    landed = threading.Event()
    app_loop.call_soon_threadsafe(landed.set)
    assert landed.wait(5), "the loop the app runs on did not answer within five seconds"


def _the_save_has_reached_the_collector(widget_id: int, before: int) -> None:
    """Wait until the settings change has bumped the generation counter.

    ⚠️ This used to be ``await asyncio.sleep(0.05)``, which hoped the other
    thread would get its turn within 50 ms. On a busy machine it usually did
    not: the counter was never bumped, so nothing marked the answer in flight
    as stale, it reached the board, and the test reported the guard as broken.
    Four runs out of four red on 09.09.2026 against an untouched 0.5.1.

    The assertion is the second half. Waiting for the handover proves nothing
    if the handover has stopped happening at all; the test would then pass
    with no race left in it.
    """
    _the_app_loop_has_caught_up()
    assert collector._generation.get(widget_id, 0) != before, (
        "the settings change never reached the collector, so this test proves nothing")


async def test_an_answer_from_before_the_save_is_thrown_away(held: _HeldAdapter, one_widget: int) -> None:
    """The whole point. Without the check the older answer wins, because it is
    published after the newer settings are already in the database."""
    slow = asyncio.ensure_future(collector.refresh(one_widget))
    await asyncio.wait_for(held.reached.wait(), timeout=5)

    # The save happens while the fetch is still in the air.
    before = collector._generation.get(one_widget, 0)
    _save_options(one_widget, {"seconds": "on"})
    collector.schedule(one_widget)
    _the_save_has_reached_the_collector(one_widget, before)

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
def one_widget(client, monkeypatch: pytest.MonkeyPatch) -> int:
    """One widget nothing but the test itself writes to.

    ⚠️ The collector is running, and creating a widget starts a loop for it on
    the app's loop. That loop reads the same widget through the same patched
    adapter, so it publishes as well, and it starts somewhere in the first
    1.5 seconds (``_loop`` spreads the first fetches). Whichever of the two
    published last won, which made the answer on the board a coin toss and
    would have let a broken guard pass whenever the loop happened to publish
    afterwards.

    So the collector's own loops are stopped for the length of the test.
    ``schedule`` still bumps the generation counter, which is the whole of
    what these tests need from it; it only skips starting the replacement
    task. That leaves exactly one thing that can publish this widget: the
    fetch the test started itself.
    """
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

    monkeypatch.setattr(collector, "running", False)
    # Cancels the loop this widget already has, and marks anything it may have
    # in the air as stale. Both are handed over, so wait for them to land.
    collector.unschedule(widget_id)
    _the_app_loop_has_caught_up()

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
    before = collector._generation.get(one_widget, 0)
    _save_options(one_widget, {"seconds": "on"})
    collector.schedule(one_widget)
    _the_save_has_reached_the_collector(one_widget, before)
    held.may_finish.set()

    assert await asyncio.wait_for(slow, timeout=5) is not None, (
        "the loop was told this widget no longer exists and would have stopped refreshing it")
