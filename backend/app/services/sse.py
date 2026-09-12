"""Server-Sent Events hub.

One queue per connected browser, subscribed to topics: a board, a user, or
everything. Publishing never blocks a producer: a slow consumer whose queue is
full simply misses events and reloads on the next full snapshot.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

QUEUE_SIZE = 500


# eq=False keeps identity hashing: subscribers live in a set, and a dataclass
# with generated equality is not hashable.
@dataclass(eq=False)
class Subscriber:
    topics: set[str]
    queue: asyncio.Queue[str] = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE))


class Hub:
    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()

    def subscribe(self, topics: set[str]) -> Subscriber:
        subscriber = Subscriber(topics=topics)
        self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)

    @property
    def connections(self) -> int:
        return len(self._subscribers)

    def publish(self, topic: str, event: str, payload: Any) -> None:
        message = f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"
        for subscriber in list(self._subscribers):
            if topic in subscriber.topics or "*" in subscriber.topics:
                try:
                    subscriber.queue.put_nowait(message)
                except asyncio.QueueFull:
                    # The consumer is not keeping up; it will resync on reconnect.
                    pass


hub = Hub()


def board_topic(board_id: int) -> str:
    return f"board:{board_id}"


def user_topic(user_id: int) -> str:
    return f"user:{user_id}"


class Recheck:
    """Asks again, by the clock, whether an open stream may stay open.

    ⚠️ The board stream used to ask only after 25 seconds without a message.
    Every card refresh and every reachability check is a message, so on a
    living board that moment never came, and a withdrawn kiosk link or a share
    taken away kept a wall display on live data until the connection broke by
    itself. The log stream and the video relay never asked at all. Found on
    12.09.2026. Whatever is flowing, the question now comes at least every
    ``every`` seconds, and a refusal stays a refusal.
    """

    def __init__(self, still_allowed: Callable[[], bool], *, every: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._still_allowed = still_allowed
        self._every = every
        self._clock = clock
        self._asked_at = clock()
        self._refused = False

    async def denied(self) -> bool:
        """True once the answer was no. Asked in a thread, because the question reads the database."""
        if self._refused:
            return True
        now = self._clock()
        if now - self._asked_at < self._every:
            return False
        self._asked_at = now
        self._refused = not await asyncio.to_thread(self._still_allowed)
        return self._refused
