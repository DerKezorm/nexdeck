"""Server-Sent Events hub.

One queue per connected browser, subscribed to topics: a board, a user, or
everything. Publishing never blocks a producer: a slow consumer whose queue is
full simply misses events and reloads on the next full snapshot.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

QUEUE_SIZE = 500


@dataclass
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
