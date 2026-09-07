"""Which pieces of a card are shown, and which number the needle follows.

⚠️ The tick boxes are made from what a widget declares, not written out by
hand in thirty adapters. Every test here is about the mechanism, so the
thirty-first adapter inherits it instead of forgetting it.
"""

from __future__ import annotations

from app.adapters import get_adapter
from app.adapters.base import (
    Context,
    WidgetData,
    WidgetType,
    join_parts,
    keep_parts,
    part_on,
    part_option,
    pick_gauge_row,
)

PARTS = (("cpu", "CPU"), ("memory", "Memory"), ("temp", "Temperature"))


def _rows() -> WidgetData:
    return WidgetData(
        primary={"label": "CPU", "value": 16, "unit": "%", "part": "cpu"},
        secondary=[
            {"label": "Memory", "value": 52, "unit": "%", "part": "memory"},
            {"label": "Temp", "value": None, "unit": "°C", "part": "temp"},
        ],
        metrics={"cpu": 16.0, "memory": 52.0},
    )


# ---------------------------------------------------------------------------
# The tick boxes
# ---------------------------------------------------------------------------


def test_a_widget_that_declares_parts_gets_one_box_each() -> None:
    widget = WidgetType(kind="x", label="X", description="", renderer="stats", parts=PARTS)
    made = {field.name: field for field in widget.options}
    assert set(made) == {"show_cpu", "show_memory", "show_temp"}
    assert all(field.type == "bool" for field in made.values())


def test_they_all_start_ticked() -> None:
    """⚠️ A card that arrives empty leaves people guessing what it could show."""
    widget = WidgetType(kind="x", label="X", description="", renderer="stats", parts=PARTS)
    assert all(field.default is True for field in widget.options)
    assert part_on({}, "cpu") is True


def test_the_boxes_come_after_the_options_the_adapter_wrote() -> None:
    from app.adapters.base import Field

    widget = WidgetType(kind="x", label="X", description="", renderer="stats", parts=PARTS,
                        options=(Field("filter", "Filter"),))
    assert [field.name for field in widget.options][0] == "filter"


def test_an_adapter_may_write_a_box_itself_and_is_not_overruled() -> None:
    from app.adapters.base import Field

    widget = WidgetType(kind="x", label="X", description="", renderer="stats", parts=PARTS,
                        options=(Field(part_option("cpu"), "Show the load", type="bool", default=False),))
    boxes = [field for field in widget.options if field.name == "show_cpu"]
    assert len(boxes) == 1
    assert boxes[0].label == "Show the load"


# ---------------------------------------------------------------------------
# Taking a piece out
# ---------------------------------------------------------------------------


def test_nothing_is_touched_while_everything_is_ticked() -> None:
    data = keep_parts(_rows(), PARTS, {})
    assert data.primary["label"] == "CPU"
    assert [row["label"] for row in data.secondary] == ["Memory", "Temp"]


def test_a_row_that_is_switched_off_goes() -> None:
    data = keep_parts(_rows(), PARTS, {"show_temp": False})
    assert [row["label"] for row in data.secondary] == ["Memory"]


def test_the_next_row_moves_up_when_the_first_one_goes() -> None:
    """⚠️ A stats card without a first row looks like the service stopped
    answering. It has not; somebody just hid a row."""
    data = keep_parts(_rows(), PARTS, {"show_cpu": False})
    assert data.primary["label"] == "Memory"
    assert [row["label"] for row in data.secondary] == ["Temp"]


def test_hiding_everything_leaves_a_card_without_a_number_rather_than_a_wrong_one() -> None:
    data = keep_parts(_rows(), PARTS, {"show_cpu": False, "show_memory": False, "show_temp": False})
    assert data.primary is None
    assert data.secondary == []


def test_the_recorded_numbers_are_untouched() -> None:
    """⚠️ What a card draws and what it records are different questions. A
    graph with a week-long hole because somebody hid a row is not what
    hiding a row meant."""
    data = keep_parts(_rows(), PARTS, {"show_cpu": False, "show_memory": False})
    assert data.metrics == {"cpu": 16.0, "memory": 52.0}


def test_a_field_inside_a_list_row_can_be_switched_off_too() -> None:
    """Both shapes occur: a row of its own, and a field inside a row."""
    data = WidgetData(items=[
        {"title": "authentik-server-1", "subtitle": "ghcr.io/x", "cpu": 3.0, "value": "744 MB", "memory_percent": 12.0},
    ])
    parts = (("cpu", "CPU"), ("value", "Memory in use"))
    kept = keep_parts(data, parts, {"show_cpu": False})
    assert "cpu" not in kept.items[0]
    assert kept.items[0]["value"] == "744 MB"
    assert kept.items[0]["title"] == "authentik-server-1", "the name is never a part"


def test_a_line_made_of_several_facts_keeps_the_separator_right() -> None:
    assert join_parts({}, ("image", "nginx:1"), ("uptime", "up 4 days")) == "nginx:1 · up 4 days"
    assert join_parts({"show_image": False}, ("image", "nginx:1"), ("uptime", "up 4 days")) == "up 4 days"
    assert join_parts({"show_uptime": False}, ("image", "nginx:1"), ("uptime", "up 4 days")) == "nginx:1"
    assert join_parts({"show_image": False, "show_uptime": False}, ("image", "n"), ("uptime", "u")) == ""
    assert join_parts({}, ("image", ""), ("uptime", "up 4 days")) == "up 4 days", "no stray separator"


# ---------------------------------------------------------------------------
# Which row the needle follows
# ---------------------------------------------------------------------------


def test_the_needle_follows_the_chosen_row() -> None:
    data = pick_gauge_row(_rows(), {"view": "gauge", "gauge_part": "memory"})
    assert data.primary["label"] == "Memory"
    assert [row["label"] for row in data.secondary] == ["CPU", "Temp"], "and CPU is still there"


def test_the_choice_does_nothing_outside_the_dial_view() -> None:
    """⚠️ Otherwise the plain card would silently reorder its rows."""
    data = pick_gauge_row(_rows(), {"gauge_part": "memory"})
    assert data.primary["label"] == "CPU"


def test_a_choice_that_names_nothing_leaves_the_card_alone() -> None:
    data = pick_gauge_row(_rows(), {"view": "gauge", "gauge_part": "does-not-exist"})
    assert data.primary["label"] == "CPU"


# ---------------------------------------------------------------------------
# The three cards he asked for
# ---------------------------------------------------------------------------


def test_the_synology_system_card_offers_a_box_per_row_and_a_dial() -> None:
    widget = get_adapter("synology").widget("system")
    names = [field.name for field in widget.options]
    assert names == ["view", "gauge_part", "show_cpu", "show_memory", "show_volume", "show_temp"]
    picker = next(field for field in widget.options if field.name == "gauge_part")
    assert [value for value, _label in picker.options] == ["cpu", "memory", "volume", "temp"]


def test_the_synology_container_card_offers_a_box_per_detail() -> None:
    names = [field.name for field in get_adapter("synology").widget("containers").options]
    assert names == ["filter", "show_stopped", "only_items", "show_image", "show_uptime",
                     "show_cpu", "show_memory_percent", "show_value"]


def test_the_synology_volume_card_offers_a_dial() -> None:
    names = [field.name for field in get_adapter("synology").widget("volumes").options]
    assert "view" in names


def test_every_row_of_the_system_card_says_which_part_it_is() -> None:
    """⚠️ Without a key the tick boxes would have to recognise a row by its
    label, and a label is translated."""
    widget = get_adapter("synology").widget("system")
    keys = {key for key, _label in widget.parts}
    assert keys == {"cpu", "memory", "volume", "temp"}


def test_a_widget_with_parts_declares_them_in_the_order_it_draws_them() -> None:
    """The boxes read top to bottom like the card does."""
    assert [key for key, _label in get_adapter("synology").widget("system").parts] == [
        "cpu", "memory", "volume", "temp",
    ]


# ---------------------------------------------------------------------------
# The data really carries the keys, against a recorded DSM
# ---------------------------------------------------------------------------

NAS = "https://nas.example.com:5001"
SYSTEM_ANSWERS = {
    ("SYNO.Core.System.Utilization", "get"): {"cpu": {"user_load": 11, "system_load": 5, "other_load": 0}, "memory": {"real_usage": 52}},
    ("SYNO.Core.System", "info"): {"model": "DS1825+", "firmware_ver": "7.2", "temperature": 42},
    ("SYNO.Storage.CGI.Storage", "load_info"): {"volumes": [
        {"id": "volume_1", "display_name": "volume_1", "status": "normal", "size": {"used": "43500000000000", "total": "125700000000000"}},
    ]},
}
CONFIG = {"url": NAS, "username": "nexdeck", "password": "a-password", "insecure": True}


def _dsm() -> None:
    import httpx
    import respx

    respx.post(f"{NAS}/webapi/auth.cgi").mock(return_value=httpx.Response(200, json={"success": True, "data": {"sid": "sid-1"}}))

    def route(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        data = SYSTEM_ANSWERS.get((params.get("api"), params.get("method")))
        if data is None:
            return httpx.Response(200, json={"success": False, "error": {"code": 101}})
        return httpx.Response(200, json={"success": True, "data": data})

    respx.get(f"{NAS}/webapi/entry.cgi").mock(side_effect=route)


async def test_every_row_the_system_card_returns_carries_its_key() -> None:
    """⚠️ Declaring parts and then not tagging the rows leaves tick boxes that
    do nothing. The box would be there, the row would stay, and nobody would
    know which half was broken."""
    import httpx
    import respx

    with respx.mock:
        _dsm()
        ctx = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
        data = await get_adapter("synology").fetch("system", CONFIG, {}, ctx)

    declared = {key for key, _label in get_adapter("synology").widget("system").parts}
    rows = [data.primary, *data.secondary]
    assert all(row.get("part") for row in rows), f"a row without a key: {rows}"
    assert {row["part"] for row in rows} == declared


async def test_a_row_the_operator_switched_off_really_disappears() -> None:
    """End to end: the box, the key and the filter, together."""
    import httpx
    import respx

    with respx.mock:
        _dsm()
        ctx = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
        data = await get_adapter("synology").fetch("system", CONFIG, {}, ctx)

    widget = get_adapter("synology").widget("system")
    kept = keep_parts(data, widget.parts, {"show_temp": False, "show_volume": False})
    assert [row["part"] for row in [kept.primary, *kept.secondary]] == ["cpu", "memory"]


# ---------------------------------------------------------------------------
# The two ways to a card must end in the same card
# ---------------------------------------------------------------------------


async def test_the_preview_shows_what_the_board_will_show() -> None:
    """⚠️ There are two ways to a card: the collector that refreshes it, and
    the preview the settings sheet asks for. The passes hung on the collector
    alone, so switching a piece off changed nothing in the sheet until the
    page was reloaded, and building a card meant guessing and pressing F5.
    """
    import httpx
    import respx

    from app.adapters.base import shape_for_display

    adapter = get_adapter("synology")
    options = {"show_temp": False, "show_volume": False}
    with respx.mock:
        _dsm()
        ctx = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
        raw = await adapter.fetch("system", CONFIG, options, ctx)

    shaped = shape_for_display(raw, adapter, "system", options)
    assert [row["part"] for row in [shaped.primary, *shaped.secondary]] == ["cpu", "memory"]


def test_both_ways_run_the_same_passes() -> None:
    """Written down, because the next pass will be added to one of them."""
    import inspect

    from app.services import collector as module

    source = inspect.getsource(module.Collector)
    live = source.count("shape_for_display(")
    assert live >= 3, "the refresh, the preview and the demo all go through it"
    for forgotten in ("keep_parts(", "pick_gauge_row(", "as_gauge("):
        assert forgotten not in source, f"{forgotten} is called past shape_for_display; that is how they drift apart"


# ---------------------------------------------------------------------------
# Which rows of a list are shown
# ---------------------------------------------------------------------------


def _disks() -> WidgetData:
    from app.adapters.base import WidgetData as Data

    return Data(items=[{"title": f"Drive {n}", "value": f"3{n} °C"} for n in range(1, 6)])


def test_every_list_card_offers_the_picker() -> None:
    """⚠️ One rule, not a field written into thirty adapters."""
    from app.adapters import all_adapters
    from app.adapters.base import ITEM_PICKER

    lists = offered = 0
    for adapter in all_adapters():
        for widget in adapter.widgets:
            if widget.renderer != "list":
                continue
            lists += 1
            offered += any(field.name == ITEM_PICKER for field in widget.options)
    assert lists > 40, "no list cards found; this test would pass on anything"
    assert offered == lists


def test_nothing_picked_means_all_of_them() -> None:
    """⚠️ Not laziness. The rows come from the service, so a new disk turns up
    on its own; storing "these five" would hide the sixth."""
    from app.adapters.base import keep_items

    assert len(keep_items(_disks(), {}).items) == 5
    assert len(keep_items(_disks(), {"only_items": []}).items) == 5


def test_only_the_picked_rows_stay() -> None:
    from app.adapters.base import keep_items

    kept = keep_items(_disks(), {"only_items": ["Drive 1", "Drive 5"]})
    assert [item["title"] for item in kept.items] == ["Drive 1", "Drive 5"]


def test_a_row_that_went_away_is_simply_gone() -> None:
    """A disk that was pulled must not leave a hole or an error."""
    from app.adapters.base import keep_items

    kept = keep_items(_disks(), {"only_items": ["Drive 2", "Drive 99"]})
    assert [item["title"] for item in kept.items] == ["Drive 2"]


def test_nonsense_in_the_option_is_ignored_rather_than_hiding_everything() -> None:
    from app.adapters.base import keep_items

    for rubbish in ("Drive 1", 7, None, {}):
        assert len(keep_items(_disks(), {"only_items": rubbish}).items) == 5


def test_the_picker_reaches_a_card_through_the_ordinary_way() -> None:
    from app.adapters.base import shape_for_display

    adapter = get_adapter("synology")
    shaped = shape_for_display(_disks(), adapter, "disks", {"only_items": ["Drive 3"]})
    assert [item["title"] for item in shaped.items] == ["Drive 3"]


# ---------------------------------------------------------------------------
# Options that would do nothing are not on screen
# ---------------------------------------------------------------------------


def test_the_dial_picker_only_appears_in_the_dial_view() -> None:
    picker = next(field for field in get_adapter("synology").widget("system").options if field.name == "gauge_part")
    assert picker.only_when == ("view", "gauge")


def test_the_row_details_of_the_volume_card_only_appear_in_the_list_view() -> None:
    """⚠️ They describe a row of a list, and a dial has no rows: three
    switches that moved and changed nothing."""
    widget = get_adapter("synology").widget("volumes")
    for name in ("show_subtitle", "show_progress", "show_value"):
        field = next(one for one in widget.options if one.name == name)
        assert field.only_when == ("view", "value"), name


def test_the_condition_reaches_the_frontend() -> None:
    """⚠️ It is the frontend that hides the field. A condition the payload
    drops is a condition nobody acts on."""
    payload = get_adapter("synology").widget("system").to_dict("synology")
    picker = next(field for field in payload["options"] if field["name"] == "gauge_part")
    assert picker["only_when"] == ["view", "gauge"]
    plain = next(field for field in payload["options"] if field["name"] == "view")
    assert plain["only_when"] is None


async def test_the_volume_dial_follows_the_rows_that_were_picked() -> None:
    """⚠️ This card trades its rows for a dial before the central picker runs,
    so "only volume_2" would silently take the fullest of all of them."""
    import httpx
    import respx

    two_volumes = dict(SYSTEM_ANSWERS)
    two_volumes[("SYNO.Storage.CGI.Storage", "load_info")] = {"volumes": [
        {"id": "volume_1", "display_name": "volume_1", "status": "normal", "size": {"used": "90", "total": "100"}},
        {"id": "volume_2", "display_name": "volume_2", "status": "normal", "size": {"used": "10", "total": "100"}},
    ]}
    original = dict(SYSTEM_ANSWERS)
    SYSTEM_ANSWERS.update(two_volumes)
    try:
        with respx.mock:
            _dsm()
            ctx = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
            data = await get_adapter("synology").fetch(
                "volumes", CONFIG, {"view": "gauge", "only_items": ["volume_2"]}, ctx,
            )
    finally:
        SYSTEM_ANSWERS.clear()
        SYSTEM_ANSWERS.update(original)
    assert data.primary["label"] == "volume_2", "the fullest of the picked ones, not of all"
    assert data.primary["value"] == 10.0


def test_the_settings_sheet_is_told_about_the_rows_it_would_hide() -> None:
    """⚠️ The tick boxes are made from the rows the card shows. Switching one
    off took its own box away with it, and there was no way back short of
    clearing the whole option."""
    from app.adapters.base import ALL_ITEMS, keep_items

    picked = {"only_items": ["Drive 1"]}
    for_sheet = keep_items(_disks(), picked, remember_all=True)
    assert [item["title"] for item in for_sheet.items] == ["Drive 1"]
    assert for_sheet.meta[ALL_ITEMS] == ["Drive 1", "Drive 2", "Drive 3", "Drive 4", "Drive 5"]


def test_the_boards_are_not_told_about_them() -> None:
    """A second copy of every title on every refresh, for a question only the
    settings sheet asks."""
    from app.adapters.base import ALL_ITEMS, keep_items

    on_a_board = keep_items(_disks(), {"only_items": ["Drive 1"]})
    assert ALL_ITEMS not in (on_a_board.meta or {})


def test_the_full_list_is_there_even_when_nothing_is_hidden() -> None:
    """Otherwise the picker is empty on a card nobody has touched yet."""
    from app.adapters.base import ALL_ITEMS, keep_items

    fresh = keep_items(_disks(), {}, remember_all=True)
    assert len(fresh.meta[ALL_ITEMS]) == 5
    assert len(fresh.items) == 5


async def test_the_preview_carries_the_full_list_and_the_refresh_does_not() -> None:
    """The two ways to a card differ in exactly this one thing."""
    from app.adapters.base import ALL_ITEMS, shape_for_display

    adapter = get_adapter("synology")
    options = {"only_items": ["Drive 2"]}
    for_sheet = shape_for_display(_disks(), adapter, "disks", options, for_settings=True)
    for_board = shape_for_display(_disks(), adapter, "disks", options)
    assert ALL_ITEMS in for_sheet.meta and ALL_ITEMS not in (for_board.meta or {})
    assert [item["title"] for item in for_board.items] == ["Drive 2"]


# ---------------------------------------------------------------------------
# The volume card filters twice, and the sheet has to survive both
# ---------------------------------------------------------------------------

TWO_VOLUMES = {
    ("SYNO.Storage.CGI.Storage", "load_info"): {"volumes": [
        {"id": "volume_1", "display_name": "volume_1", "status": "normal", "size": {"used": "43500000000000", "total": "125700000000000"}},
        {"id": "volume_2", "display_name": "volume_2", "status": "normal", "size": {"used": "900000000000", "total": "1000000000000"}},
    ]},
}


async def _volumes(options: dict) -> object:
    import httpx
    import respx

    with respx.mock:
        respx.post(f"{NAS}/webapi/auth.cgi").mock(return_value=httpx.Response(200, json={"success": True, "data": {"sid": "sid-1"}}))

        def route(request: httpx.Request) -> httpx.Response:
            params = request.url.params
            data = TWO_VOLUMES.get((params.get("api"), params.get("method")))
            if data is None:
                return httpx.Response(200, json={"success": False, "error": {"code": 101}})
            return httpx.Response(200, json={"success": True, "data": data})

        respx.get(f"{NAS}/webapi/entry.cgi").mock(side_effect=route)
        ctx = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
        return await get_adapter("synology").fetch("volumes", CONFIG, options, ctx)


async def test_the_dial_view_of_the_volume_card_still_offers_its_volumes() -> None:
    """The card the operator asked about.

    In the dial view this card trades its rows for one needle, and the tick
    boxes are built from the rows a card sends back. So the settings sheet
    said the card had nothing to pick from, while the same card in the list
    view offered every volume. The choice matters in both: it decides which
    volumes the fullest is picked from.
    """
    from app.adapters.base import ALL_ITEMS

    data = await _volumes({"view": "gauge"})
    assert data.items == [], "the dial view is supposed to have traded its rows"
    assert data.meta[ALL_ITEMS] == ["volume_1", "volume_2"]


async def test_a_volume_switched_off_keeps_its_own_box() -> None:
    """⚠️ This card applies the picker itself and is then filtered again
    centrally, so the full list was written down after the first pass. A
    volume switched off lost the box that would switch it back on.
    """
    from app.adapters.base import ALL_ITEMS, shape_for_display

    picked = {"only_items": ["volume_1"]}
    for view in ("value", "gauge"):
        data = await _volumes({**picked, "view": view})
        for_sheet = shape_for_display(data, get_adapter("synology"), "volumes", {**picked, "view": view}, for_settings=True)
        assert for_sheet.meta[ALL_ITEMS] == ["volume_1", "volume_2"], f"in the {view} view"


async def test_the_needle_follows_the_volumes_that_were_picked() -> None:
    """volume_2 is the fuller one; asking for volume_1 alone must not hand the
    needle to volume_2 anyway."""
    everything = await _volumes({"view": "gauge"})
    assert everything.primary["label"] == "volume_2"

    only_one = await _volumes({"view": "gauge", "only_items": ["volume_1"]})
    assert only_one.primary["label"] == "volume_1"
