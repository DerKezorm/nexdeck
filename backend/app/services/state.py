"""The live state: the latest data of every widget, in memory.

The collector writes here, the API reads here, the SSE hub announces changes.
Nothing in this module touches the database.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ..adapters.base import WidgetData


def level_of(data: WidgetData) -> str:
    """Red, yellow or neither, the way a card shows it: a failed fetch is red."""
    if data.error:
        return "bad"
    return data.status if data.status in ("warn", "bad") else "ok"


class LiveState:
    def __init__(self) -> None:
        self._data: dict[int, WidgetData] = {}
        self._since: dict[int, float | None] = {}
        self._recalled: set[int] = set()

    def get(self, widget_id: int) -> WidgetData | None:
        return self._data.get(widget_id)

    def set(self, widget_id: int, data: WidgetData) -> None:
        before = self._data.get(widget_id)
        level = level_of(data)
        if before is None:
            # ⚠️ A card that is already yellow or red the first time it is seen
            # turned so before anybody looked, after a restart for one. Its
            # "since" is unknown, not now: the attention card would otherwise
            # call a disk that filled up last week new after every update.
            self._since[widget_id] = time.time() if level == "ok" else None
        elif level_of(before) != level:
            self._since[widget_id] = time.time()
        self._data[widget_id] = data

    def since(self, widget_id: int) -> float | None:
        """When the card last changed between green, yellow and red, if that was seen."""
        return self._since.get(widget_id)

    def recall(self, widget_id: int, lookup: Callable[[], float | None]) -> float | None:
        """``since``, or once per card what ``lookup`` remembers of a time before this process.

        Asked once: a card whose past nobody wrote down would otherwise ask
        the database on every fetch.
        """
        known = self._since.get(widget_id)
        if known is not None or widget_id in self._recalled:
            return known
        self._recalled.add(widget_id)
        found = lookup()
        if found is not None and widget_id in self._data:
            self._since[widget_id] = found
        return found

    def forget(self, widget_id: int) -> None:
        self._data.pop(widget_id, None)
        self._since.pop(widget_id, None)
        self._recalled.discard(widget_id)

    def snapshot(self, widget_ids: list[int]) -> dict[int, WidgetData]:
        return {i: self._data[i] for i in widget_ids if i in self._data}

    def clear(self) -> None:
        self._data.clear()
        self._since.clear()
        self._recalled.clear()


live = LiveState()
