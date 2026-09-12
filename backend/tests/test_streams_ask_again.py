"""An open stream asks again whether it may still be open, however busy it is.

⚠️ The board stream asked again only when 25 seconds had passed without a
message. Every card refresh and every reachability check sends one, so on a
living board that moment never came, and a withdrawn kiosk link or a share
taken away kept a wall display on live data until the connection broke by
itself. The log stream and the video relay never asked at all. Found on
12.09.2026.
"""

from __future__ import annotations

import asyncio
import inspect

from app.routers import logs, stream, widgets
from app.services.sse import Recheck


def test_a_busy_stream_asks_again_by_the_clock_and_not_by_the_silence() -> None:
    now = [0.0]
    asked: list[float] = []
    answers = [True, False]

    def still_allowed() -> bool:
        asked.append(now[0])
        return answers.pop(0)

    recheck = Recheck(still_allowed, every=25, clock=lambda: now[0])

    async def a_message_every_few_seconds() -> list[bool]:
        verdicts = []
        for moment in (1, 10, 24, 26, 30, 50, 52, 60):
            now[0] = moment
            verdicts.append(await recheck.denied())
        return verdicts

    verdicts = asyncio.run(a_message_every_few_seconds())
    assert asked == [26, 52], "asked on every message, or not once 25 seconds had passed"
    assert verdicts == [False, False, False, False, False, False, True, True], "a refusal has to stay a refusal"


def test_every_stream_that_follows_a_board_asks_again() -> None:
    """The three places that keep a connection open for as long as the viewer likes."""
    for route in (stream.stream, logs.log_stream, widgets.widget_stream):
        source = inspect.getsource(route)
        assert "Recheck(" in source and ".denied()" in source, f"{route.__module__}.{route.__name__} does not ask again"
