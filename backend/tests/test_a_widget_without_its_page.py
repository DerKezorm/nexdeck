"""A widget whose page is gone answers 404, not a 500 out of an ``assert``.

⚠️ Two routes checked the page with ``assert page is not None``. An assert is
not a check: under ``python -O`` it is not there at all and the next line dies
on ``None.board_id``, and without ``-O`` it ends in an ``AssertionError``.
Either way a 500 with a traceback in the log, for a card that was simply
deleted a moment earlier. Still open in the check of 12.09.2026.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.models import Widget
from app.routers import music, widgets


class _PageGone:
    """A database that still has the widget and no longer has its page."""

    def get(self, model: Any, key: int) -> Any:
        return Widget(id=key, page_id=99, kind="core.clock") if model is Widget else None


def test_the_widget_routes_say_there_is_no_such_widget() -> None:
    with pytest.raises(HTTPException) as gone:
        widgets._widget(_PageGone(), 1)
    assert gone.value.status_code == 404


def test_the_music_routes_say_there_is_no_such_widget() -> None:
    with pytest.raises(HTTPException) as gone:
        music._player(_PageGone(), 1, None, None)
    assert gone.value.status_code == 404
