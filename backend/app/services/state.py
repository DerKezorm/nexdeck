"""The live state: the latest data of every widget, in memory.

The collector writes here, the API reads here, the SSE hub announces changes.
Nothing in this module touches the database.
"""

from __future__ import annotations

from ..adapters.base import WidgetData


class LiveState:
    def __init__(self) -> None:
        self._data: dict[int, WidgetData] = {}

    def get(self, widget_id: int) -> WidgetData | None:
        return self._data.get(widget_id)

    def set(self, widget_id: int, data: WidgetData) -> None:
        self._data[widget_id] = data

    def forget(self, widget_id: int) -> None:
        self._data.pop(widget_id, None)

    def snapshot(self, widget_ids: list[int]) -> dict[int, WidgetData]:
        return {i: self._data[i] for i in widget_ids if i in self._data}

    def clear(self) -> None:
        self._data.clear()


live = LiveState()
