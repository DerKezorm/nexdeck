"""What the adapters notice between two fetches, and what they keep quiet about.

Of the seven events in the catalogue, three had never been emitted from
anywhere in the code. Somebody could subscribe to "a download finished" and
wait for the rest of their life.
"""

from __future__ import annotations

from typing import Any

from app.adapters import get_adapter
from app.adapters.base import WidgetData
from app.services.notify import EVENTS


def _queue(*items: tuple[str, float]) -> WidgetData:
    return WidgetData(items=[{"id": name, "title": name, "progress": progress} for name, progress in items])


def _requests(*ids: int) -> WidgetData:
    return WidgetData(items=[{"id": number, "title": f"Film {number}", "subtitle": "Kim · movie"} for number in ids])


SAB = get_adapter("sabnzbd")
SEERR = get_adapter("seerr")


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


def test_an_item_that_was_nearly_done_and_is_gone_finished() -> None:
    found = SAB.detect("queue", _queue(("Film.2026", 99.0), ("Serie.S01", 20.0)), _queue(("Serie.S01", 24.0)), {})
    assert [one.event for one in found] == ["download_done"]
    assert "Film.2026" in found[0].title


def test_an_item_removed_halfway_is_not_called_finished() -> None:
    """⚠️ The same disappearance at ten per cent means somebody removed it.
    Saying "finished" about a file that is not there is worse than silence."""
    assert SAB.detect("queue", _queue(("Film.2026", 10.0)), _queue(), {}) == []


def test_nothing_is_announced_on_the_first_successful_fetch() -> None:
    """⚠️ A card that was broken has no "before". Calling every running
    download finished at that moment is a burst of lies in one go."""
    assert SAB.detect("queue", None, _queue(("A", 99.0)), {}) == []
    assert SAB.detect("queue", WidgetData(error="unreachable"), _queue(("A", 99.0)), {}) == []


def test_an_item_still_in_the_queue_says_nothing() -> None:
    assert SAB.detect("queue", _queue(("A", 99.0)), _queue(("A", 100.0)), {}) == []


def test_the_speed_card_notices_nothing() -> None:
    """It has no items; only the queue can tell one download from another."""
    assert SAB.detect("speed", _queue(("A", 99.0)), _queue(), {}) == []


def test_two_files_finishing_are_two_messages_and_one_file_is_one() -> None:
    found = SAB.detect("queue", _queue(("A", 99.0), ("B", 100.0)), _queue(), {})
    assert len(found) == 2
    assert len({one.dedupe_key() for one in found}) == 2, "each file has its own key"


def test_a_burst_is_capped() -> None:
    """A queue emptied by hand must not send forty messages."""
    before = _queue(*[(f"F{i}", 99.0) for i in range(40)])
    assert len(SAB.detect("queue", before, _queue(), {})) == 5


def test_every_download_adapter_inherits_the_detector() -> None:
    for kind in ("sabnzbd", "nzbget", "qbittorrent", "transmission", "deluge"):
        adapter = get_adapter(kind)
        found = adapter.detect("queue", _queue(("A", 99.0)), _queue(), {})
        assert [one.event for one in found] == ["download_done"], kind


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def test_a_request_that_was_not_there_is_new() -> None:
    found = SEERR.detect("requests", _requests(1, 2), _requests(1, 2, 3), {})
    assert [one.event for one in found] == ["request_new"]
    assert "Film 3" in found[0].title
    assert "Kim" in found[0].body


def test_it_watches_the_numbers_and_not_the_count() -> None:
    """⚠️ Somebody approving one while somebody else asks for another leaves
    the count unchanged. A card watching the number would miss it."""
    found = SEERR.detect("requests", _requests(1, 2), _requests(2, 3), {})
    assert len(found) == 1 and "Film 3" in found[0].title


def test_an_approved_request_disappearing_says_nothing() -> None:
    assert SEERR.detect("requests", _requests(1, 2), _requests(1), {}) == []


def test_a_first_look_at_a_full_list_stays_quiet() -> None:
    assert SEERR.detect("requests", None, _requests(1, 2, 3), {}) == []
    assert SEERR.detect("requests", WidgetData(items=[]), _requests(1, 2, 3), {}) == []


def test_overseerr_and_jellyseerr_inherit_it() -> None:
    for kind in ("overseerr", "jellyseerr"):
        found = get_adapter(kind).detect("requests", _requests(1), _requests(1, 2), {})
        assert [one.event for one in found] == ["request_new"], kind


# ---------------------------------------------------------------------------
# The catalogue itself
# ---------------------------------------------------------------------------


def test_no_adapter_announces_an_event_the_catalogue_does_not_know() -> None:
    """A channel can only subscribe to what stands in EVENTS."""
    from app.adapters import all_adapters

    checked = 0
    for adapter in all_adapters():
        for widget in adapter.widgets:
            for before, after in (
                (_queue(("A", 99.0)), _queue()),
                (_requests(1), _requests(1, 2)),
            ):
                try:
                    found = adapter.detect(widget.kind, before, after, {})
                except Exception:  # noqa: BLE001 - a detector that throws is another test's business
                    continue
                for one in found:
                    checked += 1
                    assert one.event in EVENTS, f"{adapter.kind}.{widget.kind} announces {one.event!r}"
    assert checked > 0, "no detector fired at all; this test would pass on anything"


def test_a_detector_is_given_the_options_of_its_card() -> None:
    """The signature is part of the contract; a detector may need them."""
    import inspect

    from app.adapters.base import Adapter

    names = list(inspect.signature(Adapter.detect).parameters)
    assert names == ["self", "widget_kind", "before", "after", "options"]


def _unused(_: Any) -> None:
    return None
