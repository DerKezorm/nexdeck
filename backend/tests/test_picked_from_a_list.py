"""Blanks picked from a list the card handed over, and more than one of them.

⚠️ The guard of 0.2.0 lets an action through only with exactly the parameters
the card last offered. A blank is the exception, and it is only safe as long as
the card declared it. For a pick list the declaration *is* the list: the value
pressed has to be one the card put on screen, or the adapter never sees it.

These run against the guard directly rather than through an adapter, because
the guard is what they are about. The Nexview approval card is the first real
user of two lists at once; its own tests sit beside its adapter.
"""

from __future__ import annotations

import pytest

from app.adapters.base import Action, AdapterError, Ask, Choice, WidgetData, fill_in
from app.services.collector import collector
from app.services.state import live

WIDGET = 9_001

FOLDERS = Ask(name="root_folder_path", label="Target folder", kind="choice",
              options=[Choice(value="/media/films", label="Films"), Choice(value="/media/kids", label="Kids")])
PROFILES = Ask(name="quality_profile_id", label="Quality profile", kind="choice",
               options=[Choice(value="4", label="HD-1080p"), Choice(value="7", label="Ultra-HD")])


def _offer(*actions: Action, rows: list[dict] | None = None) -> None:
    live.set(WIDGET, WidgetData(actions=list(actions), items=rows or []))


@pytest.fixture(autouse=True)
def _clean():
    live.forget(WIDGET)
    yield
    live.forget(WIDGET)


# -- one list ----------------------------------------------------------------


def test_a_value_the_card_offered_goes_through() -> None:
    _offer(Action(id="approve", label="Approve", params={"id": 12}, asks=[FOLDERS]))
    given = collector._refuse_unless_offered(WIDGET, "approve", {"id": 12, "root_folder_path": "/media/kids"})
    assert given == {"id": 12, "root_folder_path": "/media/kids"}


@pytest.mark.parametrize("value", [
    "/media/other",           # a real-looking folder the card never offered
    "/media/films/../../etc",  # one that walks out of an offered one
    "Films",                  # the label instead of the value
    "",
    None,
    4,
])
def test_a_value_the_card_did_not_offer_is_refused(value) -> None:
    _offer(Action(id="approve", label="Approve", params={"id": 12}, asks=[FOLDERS]))
    with pytest.raises(AdapterError) as refused:
        collector._refuse_unless_offered(WIDGET, "approve", {"id": 12, "root_folder_path": value})
    assert refused.value.code == "bad_value"


def test_the_fixed_parameters_still_have_to_match() -> None:
    """The list is one parameter. The request id beside it is still the card's
    own word: an offered folder is no excuse to approve a different request."""
    _offer(Action(id="approve", label="Approve", params={"id": 12}, asks=[FOLDERS]))
    with pytest.raises(AdapterError) as refused:
        collector._refuse_unless_offered(WIDGET, "approve", {"id": 13, "root_folder_path": "/media/kids"})
    assert refused.value.code == "no_such_action"


# -- two lists at once -------------------------------------------------------


def test_two_blanks_are_filled_in_together() -> None:
    _offer(Action(id="approve", label="Approve", params={"id": 12}, asks=[FOLDERS, PROFILES]))
    given = collector._refuse_unless_offered(
        WIDGET, "approve", {"id": 12, "root_folder_path": "/media/films", "quality_profile_id": "7"})
    assert given == {"id": 12, "root_folder_path": "/media/films", "quality_profile_id": "7"}


def test_one_of_two_blanks_left_empty_is_refused() -> None:
    """⚠️ A folder without a profile is not a smaller question but an
    unanswerable one. Nexview would refuse it too, but only after the adapter
    had already gone out to ask."""
    _offer(Action(id="approve", label="Approve", params={"id": 12}, asks=[FOLDERS, PROFILES]))
    with pytest.raises(AdapterError) as refused:
        collector._refuse_unless_offered(WIDGET, "approve", {"id": 12, "root_folder_path": "/media/films"})
    assert refused.value.code == "bad_value"


def test_a_value_from_the_other_list_is_refused() -> None:
    """Each blank is checked against its own list, not against all of them."""
    _offer(Action(id="approve", label="Approve", params={"id": 12}, asks=[FOLDERS, PROFILES]))
    with pytest.raises(AdapterError):
        collector._refuse_unless_offered(
            WIDGET, "approve", {"id": 12, "root_folder_path": "7", "quality_profile_id": "/media/films"})


# -- on a row, which is where approving happens ------------------------------


def test_lists_on_a_row_are_checked_against_that_row() -> None:
    """⚠️ Every request carries its own lists, because a film and a series go
    to different instances with different folders. A folder that is fine for
    one row must not pass on another."""
    film = {"title": "A film", "actions": [Action(
        id="approve", label="Approve", params={"id": 1}, asks=[FOLDERS]).model_dump()]}
    series_folders = Ask(name="root_folder_path", label="Target folder", kind="choice",
                         options=[Choice(value="/media/series", label="Series")])
    series = {"title": "A series", "actions": [Action(
        id="approve", label="Approve", params={"id": 2}, asks=[series_folders]).model_dump()]}
    _offer(rows=[film, series])

    assert collector._refuse_unless_offered(
        WIDGET, "approve", {"id": 2, "root_folder_path": "/media/series"})["root_folder_path"] == "/media/series"
    with pytest.raises(AdapterError):
        collector._refuse_unless_offered(WIDGET, "approve", {"id": 2, "root_folder_path": "/media/films"})


# -- the declaration on its own ----------------------------------------------


def test_a_list_takes_only_its_own_values() -> None:
    assert fill_in(PROFILES, " 7 ") == "7"
    with pytest.raises(AdapterError):
        fill_in(PROFILES, "8")


def test_a_list_with_nothing_in_it_takes_nothing() -> None:
    """A service that answered with no folders at all must not turn the blank
    into "anything goes"."""
    empty = Ask(name="root_folder_path", label="Target folder", kind="choice", options=[])
    with pytest.raises(AdapterError):
        fill_in(empty, "/media/films")


def test_free_text_still_works_beside_a_list() -> None:
    """MeTube's address field is the other kind and must not have changed."""
    address = Ask(name="url", label="Video address", kind="url", max_length=200)
    _offer(Action(id="add", label="Fetch", params={"format": "any"}, asks=[address]))
    given = collector._refuse_unless_offered(
        WIDGET, "add", {"format": "any", "url": "https://videos.example.com/x"})
    assert given["url"] == "https://videos.example.com/x"
