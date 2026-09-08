"""The drawings a card can be asked for beyond its own: bars and a ring.

⚠️ Both refuse rather than draw nothing, and that is what most of this file
is about. A bar chart of rows that carry "2.5 s" is a column of empty tracks,
and a ring whose slices do not add up to anything is a picture of a whole
that does not exist. Both cases look like the service stopped answering, so
the card stays what it was and the operator still sees their rows.
"""

from __future__ import annotations

from app.adapters import all_adapters, get_adapter
from app.adapters.base import (
    WidgetData,
    WidgetType,
    as_bars,
    as_chart,
    as_ring,
    offer_views,
    ring_of,
    shape_for_display,
)

# ---------------------------------------------------------------------------
# Which cards offer which drawing
# ---------------------------------------------------------------------------


def test_every_list_card_offers_bars() -> None:
    """One rule in WidgetType, not a field written into ninety adapters."""
    seen = 0
    for adapter in all_adapters():
        for widget in adapter.widgets:
            if widget.renderer != "list":
                continue
            seen += 1
            view = next((one for one in widget.options if one.name == "view"), None)
            assert view is not None, f"{adapter.kind}.{widget.kind} has no view field"
            assert "bars" in {value for value, _ in view.options}, f"{adapter.kind}.{widget.kind}"
    # ⚠️ A floor, or this test passes on an empty list. The guard that had no
    # floor is why every test in this repo that walks a set has one.
    assert seen > 50, f"only {seen} list cards found; the walk is broken"


def test_only_cards_that_declared_a_ring_offer_one() -> None:
    offered = {
        f"{adapter.kind}.{widget.kind}"
        for adapter in all_adapters()
        for widget in adapter.widgets
        if any(one.name == "view" and "ring" in {value for value, _ in one.options}
               for one in widget.options)
    }
    declared = {
        f"{adapter.kind}.{widget.kind}"
        for adapter in all_adapters()
        for widget in adapter.widgets
        if widget.ring
    }
    assert offered == declared
    assert declared, "no card declares a ring, so this test proves nothing"


def test_the_cards_own_drawing_is_named_after_what_it_draws() -> None:
    """"The number" under a card that draws a dial is a third thing on a list
    of two."""
    assert dict(offer_views((), "list", (("bars", "Bars"),))[0].options)["value"] == "Rows"
    assert dict(offer_views((), "gauge", (("ring", "A ring"),))[0].options)["value"] == "A dial"
    assert dict(offer_views((), "value", (("ring", "A ring"),))[0].options)["value"] == "The number"


def test_a_card_gathers_every_drawing_it_qualifies_for_in_one_field() -> None:
    """⚠️ Pi-hole's card is a dial, declares slices and records two metrics.
    Three separate fields would be three questions about the same thing, and
    the settings sheet would show all three."""
    options = get_adapter("pihole").widget("summary").options
    assert sum(1 for one in options if one.name == "view") == 1
    view = next(one for one in options if one.name == "view")
    assert [value for value, _ in view.options] == ["value", "ring", "chart"]


def test_a_card_with_one_metric_is_not_offered_a_chart() -> None:
    """One line is the sparkline the card already draws, minus its number."""
    widget = WidgetType(kind="x", label="X", description="", renderer="value", metrics=("only",))
    assert not [one for one in widget.options if one.name == "view"]


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------


def _rows(*values: object) -> WidgetData:
    return WidgetData(items=[{"title": f"row {i}", "value": v} for i, v in enumerate(values)])


def test_bars_are_drawn_when_the_rows_carry_numbers() -> None:
    data = as_bars(_rows(40, 12, 3), {"view": "bars"})
    assert data.meta["renderer"] == "bars"


def test_the_drawing_is_left_alone_when_nobody_asked() -> None:
    assert as_bars(_rows(40, 12), {}).meta.get("renderer") is None
    assert as_bars(_rows(40, 12), {"view": "value"}).meta.get("renderer") is None


def test_rows_whose_value_is_text_stay_a_list() -> None:
    """n8n's run card puts "2.5 s" where the number would be, and a bar chart
    of those is a column of empty tracks."""
    assert as_bars(_rows("2.5 s", "120 ms", ""), {"view": "bars"}).meta.get("renderer") is None


def test_one_number_among_words_is_not_a_bar_chart() -> None:
    assert as_bars(_rows(40, "down", ""), {"view": "bars"}).meta.get("renderer") is None


def test_rows_that_are_all_nought_stay_a_list() -> None:
    """Every bar empty says "measured and nothing", which reads as broken."""
    assert as_bars(_rows(0, 0, 0), {"view": "bars"}).meta.get("renderer") is None


def test_a_boolean_is_not_a_number() -> None:
    """⚠️ ``isinstance(True, int)`` is true in Python, and a row that carries
    a flag would otherwise be drawn as a bar of length one."""
    assert as_bars(_rows(True, False, True), {"view": "bars"}).meta.get("renderer") is None


# ---------------------------------------------------------------------------
# The ring
# ---------------------------------------------------------------------------


def test_the_ring_draws_the_slices_the_fetch_worked_out() -> None:
    data = WidgetData(meta={"ring": ring_of(("Blocked", 400), ("Allowed", 600))})
    drawn = as_ring(data, {"view": "ring"})
    assert drawn.meta["renderer"] == "ring"
    assert [piece["label"] for piece in drawn.meta["ring"]] == ["Blocked", "Allowed"]
    assert [piece["value"] for piece in drawn.meta["ring"]] == [400.0, 600.0]


def test_a_card_that_wrote_no_slices_stays_what_it_was() -> None:
    """The flag only puts the choice on the screen; the fetch does the sum."""
    assert as_ring(WidgetData(secondary=[{"label": "Queries", "value": 1000}]),
                   {"view": "ring"}).meta.get("renderer") is None


def test_slices_are_never_taken_from_the_rows() -> None:
    """⚠️ The trap this whole design avoids. Pi-hole's rows are queries,
    blocked and clients; blocked is already inside queries, so adding the
    three up draws a whole that is nowhere in the world."""
    data = WidgetData(secondary=[{"label": "Queries", "value": 1000},
                                 {"label": "Blocked", "value": 400},
                                 {"label": "Clients", "value": 12}])
    assert as_ring(data, {"view": "ring"}).meta.get("renderer") is None


def test_one_slice_is_not_a_ring() -> None:
    data = WidgetData(meta={"ring": ring_of(("Everything", 5))})
    assert as_ring(data, {"view": "ring"}).meta.get("renderer") is None


def test_a_whole_of_nothing_is_not_drawn() -> None:
    """Nought of nought is not "all of it": it is a service with nothing yet."""
    data = WidgetData(meta={"ring": ring_of(("Up", 0), ("Down", 0))})
    assert as_ring(data, {"view": "ring"}).meta.get("renderer") is None


def test_an_unknown_slice_is_left_out_rather_than_counted_as_nought() -> None:
    """⚠️ The same rule as ``percent`` and ``measured``: a missing number
    makes every other slice bigger, so the drawing would be wrong rather than
    incomplete."""
    assert ring_of(("Up", 3), ("Down", None), ("Away", 1)) == [
        {"label": "Up", "value": 3.0},
        {"label": "Away", "value": 1.0},
    ]


def test_a_negative_slice_is_left_out() -> None:
    """A ring cannot draw less than nothing, and a service that reports -1 for
    "unknown" would otherwise turn the drawing inside out."""
    assert ring_of(("Up", 3), ("Down", -1)) == [{"label": "Up", "value": 3.0}]


# ---------------------------------------------------------------------------
# The five cards that declared one, against their own arithmetic
# ---------------------------------------------------------------------------


def test_the_declared_rings_add_up_to_the_whole_the_card_names() -> None:
    """⚠️ Measured against the card's own demo, because that is the one place
    every adapter has to produce a believable answer. A ring whose slices do
    not add up to the "/ 12" the card prints beside them is two claims about
    the same thing on one card.
    """
    checked = 0
    for kind in ("pihole", "adguard", "uptimekuma", "docker", "n8n"):
        adapter = get_adapter(kind)
        data = adapter.demo("summary", {}, tick=7)
        slices = (data.meta or {}).get("ring") or []
        assert len(slices) >= 2, f"{kind}: the demo wrote no slices"
        whole = sum(float(piece["value"]) for piece in slices)
        unit = str((data.primary or {}).get("unit") or "")
        if unit.startswith("/"):
            named = float(unit.lstrip("/ ").strip())
            assert whole == named, f"{kind}: slices add to {whole}, the card says {named}"
            checked += 1
    assert checked >= 3, f"only {checked} cards printed a whole to check against"


# ---------------------------------------------------------------------------
# The chart, for a card that measures more than one thing
# ---------------------------------------------------------------------------


def test_a_card_measuring_two_things_can_be_drawn_as_one_chart() -> None:
    data = as_chart(WidgetData(metrics={"wan_down": 40.0, "wan_up": 8.0}), {"view": "chart"})
    assert data.meta["renderer"] == "chart"


def test_a_card_measuring_one_thing_right_now_stays_what_it_is() -> None:
    """⚠️ The choice is offered because the widget declares two metrics, but
    an adapter reports what it found: a Docker host with nothing running
    reports one, and a chart of a single line is the sparkline the card
    already had, minus the number it sat under."""
    data = as_chart(WidgetData(metrics={"wan_down": 40.0}), {"view": "chart"})
    assert data.meta.get("renderer") is None


def test_the_chart_is_offered_wherever_two_metrics_are_declared() -> None:
    offered = sum(
        1
        for adapter in all_adapters()
        for widget in adapter.widgets
        if any(one.name == "view" and "chart" in {value for value, _ in one.options}
               for one in widget.options)
    )
    declared = sum(
        1
        for adapter in all_adapters()
        for widget in adapter.widgets
        if len(widget.metrics) >= 2 and widget.renderer != "chart" and not widget.client_only
    )
    assert offered == declared
    assert declared > 20, f"only {declared} cards measure two things; the walk is broken"


# ---------------------------------------------------------------------------
# The Plex load card, which can be four dials
# ---------------------------------------------------------------------------


def test_the_plex_load_card_can_be_a_dial_for_any_of_its_four_values() -> None:
    widget = get_adapter("plex").widget("load")
    view = next(one for one in widget.options if one.name == "view")
    assert [value for value, _ in view.options] == ["value", "gauge", "chart"]
    picker = next(one for one in widget.options if one.name == "gauge_part")
    assert [value for value, _ in picker.options] == ["plex_cpu", "plex_memory", "host_cpu", "host_memory"]
    # ⚠️ The picker is meaningless outside the dial, and an option that does
    # nothing must not be on screen.
    assert picker.only_when == ("view", "gauge")


def test_the_needle_follows_the_row_that_was_picked() -> None:
    """⚠️ Not the first row. Taking that silently would mean the dial changes
    meaning the day somebody hides a row, and nobody would connect the two."""
    adapter = get_adapter("plex")
    for part, label in (("host_memory", "Host RAM"), ("plex_memory", "Plex RAM")):
        data = shape_for_display(adapter.demo("load", {}, tick=9), adapter, "load",
                                 {"view": "gauge", "gauge_part": part})
        assert data.primary["label"] == label
        assert data.meta["renderer"] == "gauge"
        # The share is the number itself: these rows are already percentages.
        assert data.meta["gauge"]["share"] == data.primary["value"]
        # ⚠️ No ceiling is named. "62% of 100%" is a sentence about nothing.
        assert "max" not in data.meta["gauge"]


def test_the_four_values_are_named_once_and_used_three_times() -> None:
    """The metrics, the tick boxes and the dial's list have to agree. Three
    hand-written lists would be three chances to let them drift, and it would
    show first as a dial pointing at the wrong row."""
    from app.adapters.plex import LOAD_PARTS

    widget = get_adapter("plex").widget("load")
    keys = [key for key, _label in LOAD_PARTS]
    assert list(widget.metrics) == keys
    assert [key for key, _label in widget.parts] == keys
    data = get_adapter("plex").demo("load", {}, tick=3)
    rows = [data.primary, *data.secondary]
    assert [row["part"] for row in rows] == keys
    assert sorted(data.metrics) == sorted(keys)
