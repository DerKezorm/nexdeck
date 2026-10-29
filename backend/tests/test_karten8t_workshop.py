"""B6 of the second security review: comments of strangers do not push the answer of the action out of nexdeck's sight."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from app.workshop import submit

BODY = "### Type\n\nCard\n"
DIGEST = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
ISSUE = {"number": 7, "state": "closed", "body": BODY}


class Thread(submit.Context):
    """An issue with its comments, in pages of ``per_page`` as GitHub hands them out."""

    def __init__(self, comments: list[dict[str, Any]]) -> None:
        self.all = comments
        self.asked: list[int] = []

    async def api(self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        assert params is not None
        page, size = int(params["page"]), int(params["per_page"])
        self.asked.append(page)
        return self.all[(page - 1) * size : page * size]


def verdict(status: str = "accepted") -> dict[str, Any]:
    return {"user": {"login": submit.BOT}, "body": f"**{status}.**\n- a reason\n<!-- workshop:{status}:{DIGEST} -->"}


def stranger(body: str = "+1") -> dict[str, Any]:
    return {"user": {"login": "stranger"}, "body": body}


def state(comments: list[dict[str, Any]]) -> tuple[tuple[str, list[str]], list[int]]:
    thread = Thread(comments)
    seen = asyncio.run(thread.comments({**ISSUE, "comments": len(comments)}))
    return submit._state_of(ISSUE, submit.last_marker(seen)), thread.asked


def test_karten8t_b6_a_hundred_comments_after_the_verdict_do_not_hide_it() -> None:
    found, asked = state([verdict()] + [stranger()] * 100)
    assert found == ("in_shop", [])
    assert asked == [2, 1]


def test_karten8t_b6_a_rejection_keeps_its_reasons_under_three_pages_of_strangers() -> None:
    found, asked = state([stranger()] * 5 + [verdict("rejected")] + [stranger()] * 250)
    assert found == ("failed", ["a reason"])
    assert asked == [3, 2, 1]


def test_karten8t_b6_a_marker_written_by_a_stranger_counts_for_nothing() -> None:
    forged = stranger(f"<!-- workshop:accepted:{DIGEST} -->")
    found, _asked = state([verdict("rejected")] + [forged] * 120)
    assert found == ("failed", ["a reason"])


def test_karten8t_b6_the_last_page_alone_is_read_when_the_verdict_is_on_it() -> None:
    found, asked = state([stranger()] * 150 + [verdict()])
    assert found == ("in_shop", [])
    assert asked == [2]


def test_karten8t_b6_reading_back_stops_after_the_most_pages() -> None:
    _found, asked = state([stranger()] * (100 * (submit.MAX_COMMENT_PAGES + 5)))
    assert len(asked) == submit.MAX_COMMENT_PAGES and asked[0] == submit.MAX_COMMENT_PAGES + 5
