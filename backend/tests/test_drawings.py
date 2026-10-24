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
    NUMBER_RENDERERS,
    WidgetData,
    WidgetType,
    apply_level,
    as_bars,
    as_chart,
    as_gauge,
    as_inout,
    as_ring,
    as_segments,
    inout_pair,
    offer_views,
    ring_of,
    shape_for_display,
)

# ---------------------------------------------------------------------------
# Which cards offer which drawing
# ---------------------------------------------------------------------------


def test_only_list_cards_that_declared_bars_offer_them() -> None:
    """Declared, like the ring. It used to be every list card, and on 143 of
    157 the switch did nothing (22.09.2026); whether a declaration is right is
    held by ``test_bars_are_offered_where_they_can_be_drawn``."""
    offered = {
        f"{adapter.kind}.{widget.kind}"
        for adapter in all_adapters()
        for widget in adapter.widgets
        if any(one.name == "view" and "bars" in {value for value, _ in one.options}
               for one in widget.options)
    }
    declared = {
        f"{adapter.kind}.{widget.kind}"
        for adapter in all_adapters()
        for widget in adapter.widgets
        if widget.bars and widget.renderer == "list"
    }
    assert offered == declared
    assert len(declared) >= 10, "hardly any card declares bars, so this test proves little"


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
    # Pi-hole's card is a dial already, so "A dial" is its own drawing, not an extra.
    assert [value for value, _ in view.options] == ["value", "number", "ring", "meter", "segments", "chart"]


def test_a_number_card_with_one_metric_is_offered_every_drawing_of_a_number() -> None:
    """Issue #39: the same choices on every number. One metric used to get no
    chart, as "the sparkline the card already draws, minus its number"; the
    chart draws the reading, the lowest and the highest above the line."""
    widget = WidgetType(kind="x", label="X", description="", renderer="value", metrics=("only",))
    view = next(one for one in widget.options if one.name == "view")
    assert [value for value, _ in view.options] == ["value", "gauge", "meter", "segments", "chart"]
    names = {one.name: one for one in widget.options}
    assert names["gauge_max"].only_when == ("view", "gauge|meter")
    assert names["meter_direction"].only_when == ("view", "meter")
    assert names["level_warn"].only_when == names["level_bad"].only_when == ("view", "gauge|meter|segments")


def test_a_card_without_a_number_is_offered_none_of_them() -> None:
    """A card that records nothing has no measured number to draw, and a
    clock or an app tile draws itself in the browser."""
    for widget in (
        WidgetType(kind="x", label="X", description="", renderer="value"),
        WidgetType(kind="x", label="X", description="", renderer="value", metrics=("n",), client_only=True),
        WidgetType(kind="x", label="X", description="", renderer="list", metrics=("n",)),
    ):
        view = next((one for one in widget.options if one.name == "view"), None)
        offered = {value for value, _ in view.options} if view else set()
        assert not offered & {"gauge", "meter", "segments"}, widget
        assert not {"gauge_max", "meter_direction", "level_warn", "level_bad"} & {one.name for one in widget.options}


def test_an_adapter_that_knew_its_dial_keeps_its_own_words_for_full() -> None:
    """⚠️ No second "Full at" under the download speed, whose own field says
    what full means on a line; and none on a card that measures a share."""
    for kind, widget_kind in (("sabnzbd", "speed"), ("opnsense", "system")):
        options = get_adapter(kind).widget(widget_kind).options
        assert sum(1 for one in options if one.name == "gauge_max") <= 1
    assert "gauge_max" not in {one.name for one in get_adapter("opnsense").widget("system").options}


def test_every_number_card_offers_every_drawing_of_a_number() -> None:
    """Held for all of them, not for a sample: the issue was that the choice
    depended on which adapter a number came from."""
    cards = [
        (adapter.kind, widget)
        for adapter in all_adapters()
        for widget in adapter.widgets
        if widget.renderer in NUMBER_RENDERERS and widget.metrics and not widget.client_only
    ]
    assert len(cards) > 150, f"only {len(cards)} number cards; the walk is broken"
    for kind, widget in cards:
        view = next(one for one in widget.options if one.name == "view")
        offered = {value for value, _ in view.options}
        wanted = {"meter", "segments", "chart"} | ({"gauge"} if widget.renderer != "gauge" else {"number"})
        assert wanted <= offered, f"{kind}.{widget.kind} misses {wanted - offered}"


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


def test_a_card_measuring_one_thing_is_drawn_as_a_chart_of_one_line() -> None:
    data = as_chart(WidgetData(metrics={"wan_down": 40.0}), {"view": "chart"})
    assert data.meta["renderer"] == "chart"


def test_a_card_that_measured_nothing_right_now_stays_what_it_is() -> None:
    """A chart of no line is an empty box; the card keeps its number."""
    data = as_chart(WidgetData(primary={"label": "Load", "value": None}), {"view": "chart"})
    assert data.meta.get("renderer") is None


def test_the_chart_is_offered_wherever_two_metrics_or_a_number_are_declared() -> None:
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
        if widget.renderer != "chart" and not widget.client_only
        and (len(widget.metrics) >= 2 or (widget.renderer in NUMBER_RENDERERS and widget.metrics))
    )
    assert offered == declared
    assert declared > 20, f"only {declared} cards measure two things; the walk is broken"


# ---------------------------------------------------------------------------
# The Plex load card, which can be four dials
# ---------------------------------------------------------------------------


def test_the_plex_load_card_can_be_a_dial_for_any_of_its_four_values() -> None:
    widget = get_adapter("plex").widget("load")
    view = next(one for one in widget.options if one.name == "view")
    assert [value for value, _ in view.options] == ["value", "gauge", "meter", "segments", "chart"]
    picker = next(one for one in widget.options if one.name == "gauge_part")
    assert [value for value, _ in picker.options] == ["plex_cpu", "plex_memory", "host_cpu", "host_memory"]
    # ⚠️ The picker is meaningless outside the views of one number, and an
    # option that does nothing must not be on screen.
    assert picker.only_when == ("view", "gauge|meter|segments")


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


# ---------------------------------------------------------------------------
# In and out, mirrored, for a card that measures a line each way
# ---------------------------------------------------------------------------


def test_in_and_out_are_drawn_mirrored_when_both_are_measured() -> None:
    data = as_inout(WidgetData(metrics={"clients": 12.0, "wan_down": 40.0, "wan_up": 8.0}), {"view": "inout"})
    assert data.meta["renderer"] == "inout"
    assert data.meta["inout"] == ["wan_down", "wan_up"]


def test_in_without_out_stays_what_it_is() -> None:
    assert as_inout(WidgetData(metrics={"wan_down": 40.0}), {"view": "inout"}).meta.get("renderer") is None
    assert as_inout(WidgetData(metrics={"wan_down": 40.0, "wan_up": 8.0}), {"view": "value"}).meta.get("renderer") is None


def test_in_and_out_are_offered_where_a_pair_is_declared_and_nowhere_else() -> None:
    offered = {
        f"{adapter.kind}.{widget.kind}"
        for adapter in all_adapters()
        for widget in adapter.widgets
        if any(one.name == "view" and "inout" in {value for value, _ in one.options} for one in widget.options)
    }
    assert {"unifi.summary", "unifi.console", "fritzbox.connection", "speedtest.latest", "nexpulse.latest"} <= offered
    assert "glances.system" not in offered, "cpu and memory are not a way in and a way out"
    assert "gatus.summary" not in offered, "endpoints up and down are counted, not carried"
    assert len(offered) >= 5, f"only {sorted(offered)}"


def test_every_card_offering_in_and_out_names_the_rows_its_chips_read() -> None:
    """⚠️ The chips under the drawing find their number by the row's metric.
    A FRITZ!Box, a speed test and a torrent client wrote "Download" and
    "Upload" without one, and the chips read "down –" and "up –" under a
    drawing that knew both numbers."""
    unnamed = []
    for adapter in all_adapters():
        for widget in adapter.widgets:
            pair = inout_pair(widget.metrics) if widget.inout and not widget.client_only else None
            if pair is None:
                continue
            data = adapter.demo(widget.kind, {}, 3)
            named = {row.get("metric") for row in [data.primary, *(data.secondary or [])] if row}
            unnamed += [f"{adapter.kind}.{widget.kind}:{metric}" for metric in pair if metric not in named]
    assert not unnamed, unnamed


def test_covers_can_run_past_as_a_band() -> None:
    from app.adapters.base import as_band

    assert as_band(WidgetData(items=[{"title": "A"}]), {"view": "band"}).meta["band"] is True
    assert "band" not in as_band(WidgetData(items=[]), {"view": "value"}).meta
    widget = get_adapter("plex").widget("recent")
    view = next(one for one in widget.options if one.name == "view")
    assert dict(view.options)["value"] == "Covers in a grid" and "band" in dict(view.options)



# ---------------------------------------------------------------------------
# LEDs, seven segments and the lines for yellow and red (issue #39)
# ---------------------------------------------------------------------------


def _speed(value: float = 30.0, unit: str = "MB/s") -> WidgetData:
    return WidgetData(status="ok", primary={"label": "Download", "value": value, "unit": unit}, metrics={"speed": value})


def test_the_leds_share_the_dial_s_arithmetic() -> None:
    data = as_gauge(_speed(30.0), {"view": "meter", "gauge_max": 120})
    assert data.meta["renderer"] == "meter"
    assert data.meta["gauge"] == {"share": 25.0, "max": 120.0}
    assert data.meta["meter"] == {"direction": "across", "zones": {}, "low_is_bad": False}
    # A share is full at a hundred by arithmetic, as for the dial.
    share = as_gauge(_speed(64.0, "%"), {"view": "meter", "meter_direction": "upright"})
    assert share.meta["gauge"] == {"share": 64.0} and share.meta["meter"]["direction"] == "upright"


def test_the_leds_without_a_ceiling_stay_a_number() -> None:
    """⚠️ As with the dial: a row of LEDs without a ceiling claims a share of
    nothing, so the card keeps drawing the number until full is named."""
    assert as_gauge(_speed(30.0), {"view": "meter"}).meta.get("renderer") is None


def test_an_adapter_s_own_ceiling_lights_the_leds_too() -> None:
    """A line's speed or a volume's size is passed to ``as_gauge`` once, and the
    LEDs get it as the dial does."""
    data = as_gauge(_speed(50.0), {"view": "meter"}, maximum=100)
    assert data.meta["renderer"] == "meter" and data.meta["gauge"]["share"] == 50.0


def test_the_led_zones_are_shares_of_the_same_ceiling() -> None:
    data = as_gauge(_speed(30.0), {"view": "meter", "gauge_max": 200, "level_warn": 100, "level_bad": "150"})
    assert data.meta["meter"]["zones"] == {"warn": 50.0, "bad": 75.0}


def test_the_lines_colour_the_drawing_and_leave_the_status_alone() -> None:
    """⚠️ The problems card, the notices and the red glow read ``status``; a
    line drawn for the look of an LED row is not a fault of the service."""
    options = {"view": "segments", "level_warn": 25, "level_bad": 40}
    for value, level in ((10.0, "ok"), (25.0, "warn"), (39.9, "warn"), (40.0, "bad")):
        data = apply_level(_speed(value), options)
        assert data.meta["level"] == level, value
        assert data.status == "ok"


def test_the_lines_colour_the_number_in_every_view_for_a_tile_of_key_figures() -> None:
    """A tile draws the card's number whatever its view; the plain number and
    the rows never read the level, and the status stays the service's."""
    for view in ("value", "number", "chart", None):
        options = {"level_warn": 25, "level_bad": 40, **({"view": view} if view else {})}
        data = apply_level(_speed(30.0), options)
        assert data.meta["level"] == "warn", view
        assert data.status == "ok"


def test_red_below_yellow_means_low_numbers_are_the_bad_ones() -> None:
    options = {"view": "meter", "level_warn": 20, "level_bad": 10}
    assert [apply_level(_speed(v), options).meta["level"] for v in (50.0, 20.0, 10.0, 3.0)] == ["ok", "warn", "bad", "bad"]


def test_no_lines_or_no_number_leave_the_colour_to_the_card() -> None:
    assert "level" not in apply_level(_speed(99.0), {"view": "meter"}).meta
    word = WidgetData(primary={"label": "State", "value": "online"})
    assert "level" not in apply_level(word, {"view": "segments", "level_bad": 1}).meta


def test_seven_segments_draw_numbers_and_leave_words_alone() -> None:
    assert as_segments(_speed(12.5), {"view": "segments"}).meta["renderer"] == "segments"
    word = WidgetData(primary={"label": "State", "value": "online"})
    assert as_segments(word, {"view": "segments"}).meta.get("renderer") is None
    assert as_segments(_speed(12.5), {"view": "value"}).meta.get("renderer") is None


def test_a_dial_card_can_be_drawn_as_its_plain_number() -> None:
    """Issue #44: NextDNS and Technitium are dials by birth, and asking for the
    number left the dial standing. "value" stays the dial on these cards, or
    every board saved before would change its drawing."""
    for kind in ("nextdns", "technitium"):
        adapter = get_adapter(kind)
        view = next(one for one in adapter.widget("summary").options if one.name == "view")
        assert ("number", "The number") in view.options, kind
        plain = shape_for_display(adapter.demo("summary", {}, tick=3), adapter, "summary", {"view": "number"})
        assert plain.meta["renderer"] == "value", kind
        assert plain.secondary, kind
        dial = shape_for_display(adapter.demo("summary", {}, tick=3), adapter, "summary", {"view": "value"})
        assert (dial.meta or {}).get("renderer") is None, kind


def test_the_row_picked_for_the_dial_is_the_one_the_leds_and_digits_show() -> None:
    adapter = get_adapter("plex")
    for view in ("meter", "segments"):
        data = shape_for_display(adapter.demo("load", {}, tick=9), adapter, "load",
                                 {"view": view, "gauge_part": "host_memory", "gauge_max": 100})
        assert data.primary["part"] == "host_memory", view



def test_a_floor_moves_where_the_dial_and_the_leds_start() -> None:
    """A room is never colder than 15 °C: 22 of 15 to 29 is half, not three quarters."""
    room = WidgetData(status="ok", primary={"label": "Living room", "value": 22.0, "unit": "°C"}, metrics={"temp": 22.0})
    dial = as_gauge(room, {"view": "gauge", "gauge_min": 15, "gauge_max": 29})
    assert dial.meta["gauge"] == {"share": 50.0, "max": 29.0, "min": 15.0}
    leds = as_gauge(WidgetData(primary={"label": "Living room", "value": 22.0, "unit": "°C"}),
                    {"view": "meter", "gauge_min": "15", "gauge_max": 29, "level_warn": 22, "level_bad": 25.5})
    assert leds.meta["gauge"]["share"] == 50.0
    assert leds.meta["meter"]["zones"] == {"warn": 50.0, "bad": 75.0}
    # Below the floor is empty, not less than empty.
    assert as_gauge(WidgetData(primary={"label": "x", "value": 9.0}), {"view": "gauge", "gauge_min": 15, "gauge_max": 29}).meta["gauge"]["share"] == 0.0


def test_a_floor_at_or_above_the_ceiling_leaves_the_number() -> None:
    data = as_gauge(WidgetData(primary={"label": "x", "value": 20.0}), {"view": "gauge", "gauge_min": 30, "gauge_max": 30})
    assert data.meta.get("renderer") is None


def test_a_percentage_with_a_floor_still_needs_no_ceiling() -> None:
    data = as_gauge(WidgetData(primary={"label": "CPU", "value": 60.0, "unit": "%"}), {"view": "meter", "gauge_min": 20})
    assert data.meta["gauge"] == {"share": 50.0, "min": 20.0, "max": 100.0}


def test_the_chart_says_how_far_back_it_reaches() -> None:
    """nexdeck keeps a day of minute rows, so a day is the longest offered."""
    widget = WidgetType(kind="x", label="X", description="", renderer="value", metrics=("only",))
    field = next(one for one in widget.options if one.name == "chart_hours")
    assert [value for value, _ in field.options] == ["1", "6", "24"] and field.only_when == ("view", "chart")
    two = WidgetData(metrics={"a": 1.0, "b": 2.0})
    assert as_chart(two, {"view": "chart", "chart_hours": "6"}).meta["chart_hours"] == 6
    assert as_chart(WidgetData(metrics={"a": 1.0}), {"view": "chart"}).meta["chart_hours"] == 24
    assert as_chart(WidgetData(metrics={"a": 1.0}), {"view": "chart", "chart_hours": "720"}).meta["chart_hours"] == 24


def test_every_card_offering_a_chart_offers_its_hours() -> None:
    for adapter in all_adapters():
        for widget in adapter.widgets:
            view = next((one for one in widget.options if one.name == "view"), None)
            if view is not None and "chart" in {value for value, _ in view.options}:
                assert any(one.name == "chart_hours" for one in widget.options), f"{adapter.kind}.{widget.kind}"
