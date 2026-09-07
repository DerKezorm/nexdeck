"""The ring view, and the cards that are not allowed to have one.

A ring claims a share of something. On a card with no ceiling it claims one
that does not exist, and the eye believes the drawing before it reads the
number underneath.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters import all_adapters, get_adapter
from app.adapters.base import RENDERER_MIN, WidgetData, as_gauge, gauge_view_field

from .conftest import CSRF, setup_admin


def _card(value: float, unit: str = "Mbps", label: str = "Download") -> WidgetData:
    return WidgetData(primary={"label": label, "value": value, "unit": unit})


def test_a_number_stays_a_number_until_it_is_asked() -> None:
    card = as_gauge(_card(900), {})
    assert card.meta.get("renderer") is None
    assert card.primary["value"] == 900


def test_a_ceiling_turns_it_into_a_share() -> None:
    card = as_gauge(_card(900), {"view": "gauge", "gauge_max": 1000})
    assert card.meta["renderer"] == "gauge"
    assert card.meta["gauge"] == {"share": 90.0, "max": 1000.0}


def test_asking_for_a_dial_without_a_ceiling_leaves_the_number() -> None:
    """⚠️ The whole point. Drawing an empty dial, or a full one, would be a
    claim about a proportion nobody gave."""
    card = as_gauge(_card(900), {"view": "gauge"})
    assert card.meta.get("renderer") is None
    assert card.primary["value"] == 900


def test_a_nonsense_ceiling_leaves_the_number() -> None:
    for bad in ("", "abc", 0, -5, None):
        card = as_gauge(_card(900), {"view": "gauge", "gauge_max": bad})
        assert card.meta.get("renderer") is None, bad


def test_a_card_already_in_percent_needs_no_ceiling() -> None:
    """It said so with its unit."""
    card = as_gauge(_card(37, unit="%", label="CPU"), {"view": "gauge"})
    assert card.meta["renderer"] == "gauge"
    assert card.primary["value"] == 37.0


def test_more_than_full_is_full_and_not_more() -> None:
    """The needle stops at the end of the dial; the number does not."""
    card = as_gauge(_card(1400), {"view": "gauge", "gauge_max": 1000})
    assert card.meta["gauge"]["share"] == 100.0
    assert card.primary["value"] == 1400


def test_below_nothing_is_nothing() -> None:
    card = as_gauge(_card(-20), {"view": "gauge", "gauge_max": 1000})
    assert card.meta["gauge"]["share"] == 0.0


def test_a_card_without_a_number_is_left_alone() -> None:
    text = WidgetData(primary={"label": "State", "value": "running", "unit": ""})
    assert as_gauge(text, {"view": "gauge", "gauge_max": 100}).meta.get("renderer") is None


def test_applying_it_twice_changes_nothing() -> None:
    """⚠️ The collector applies it centrally. An adapter that also calls it
    must not turn its own percentage into a percentage of a percentage."""
    once = as_gauge(_card(900), {"view": "gauge", "gauge_max": 1000})
    twice = as_gauge(once, {"view": "gauge", "gauge_max": 1000})
    assert twice.primary == once.primary


def test_the_measured_value_is_what_the_card_still_shows() -> None:
    """⚠️ A dial that replaces "43.3 MB/s" with "90%" answers a question
    nobody asked. The share moves the needle; the number stays the number."""
    card = as_gauge(_card(43.3, unit="MB/s"), {"view": "gauge", "gauge_max": 12.5})
    assert card.primary["value"] == 43.3
    assert card.primary["unit"] == "MB/s"
    assert card.primary["label"] == "Download"
    assert card.meta["gauge"]["max"] == 12.5, "and the dial knows what full means"


# ---------------------------------------------------------------------------
# Which cards offer it
# ---------------------------------------------------------------------------


def test_the_cards_he_asked_for_offer_it() -> None:
    for kind, widget in (("speedtest", "latest"), ("sabnzbd", "speed"), ("nzbget", "speed"),
                         ("qbittorrent", "speed"), ("transmission", "speed"), ("deluge", "speed")):
        options = {field.name for field in get_adapter(kind).widget(widget).options}
        assert "view" in options, f"{kind}.{widget}"
        assert "gauge_max" in options, f"{kind}.{widget} needs a ceiling to be a share of"


def test_a_card_already_in_percent_offers_the_view_without_a_ceiling() -> None:
    for kind in ("mikrotik", "opnsense", "pfsense"):
        options = {field.name for field in get_adapter(kind).widget("system").options}
        assert options == {"view"}, kind


def test_no_card_offers_a_ceiling_without_the_view_to_use_it() -> None:
    """A setting that changes nothing is a setting somebody fills in and then
    wonders about."""
    for adapter in all_adapters():
        for widget in adapter.widgets:
            names = {field.name for field in widget.options}
            if "gauge_max" in names:
                assert "view" in names, f"{adapter.kind}.{widget.kind}"


def test_every_card_offering_the_view_is_big_enough_to_be_one() -> None:
    """A card that can turn into a dial has to have room for one.

    ⚠️ This used to demand that such a card be drawn by the value renderer,
    on the reasoning that a list cannot become a dial. It can: the data names
    the drawing (``meta.renderer``), which is how a stats card and a list card
    both offer the view now. What actually has to hold is the size: a card
    that shrinks to one cell and then turns into a dial is a clipped dial.
    """
    floor = RENDERER_MIN["gauge"]
    checked = 0
    for adapter in all_adapters():
        for widget in adapter.widgets:
            if not any(field.name == "view" and any(v == "gauge" for v, _ in field.options) for field in widget.options):
                continue
            checked += 1
            assert widget.min_size[0] >= floor[0] and widget.min_size[1] >= floor[1], (
                f"{adapter.kind}.{widget.kind} may become a dial but shrinks to {widget.min_size}"
            )
    assert checked >= 8, "no card offers it; this test would pass on anything"

    # ⚠️ And the check above can actually fail. Sizes are raised to the
    # floor of their own renderer, and most floors already clear the dial's,
    # so a test that only walks the real widgets would pass whatever happened.
    # A clock is the counter-example: two cells wide, one high.
    from app.adapters.base import WidgetType

    too_small = WidgetType(kind="x", label="X", description="", renderer="clock",
                           options=(gauge_view_field(),))
    assert too_small.min_size[1] < floor[1], "the rule has no teeth if nothing can break it"


def test_a_card_that_already_measures_a_percentage_names_no_ceiling() -> None:
    """⚠️ "35% of 100%" is a sentence about nothing.

    The share is arithmetic when the unit is already a percentage, so no
    ceiling was named and none is written down. The card said it anyway, and
    the dial dutifully printed it under the number.
    """
    card = WidgetData(primary={"label": "volume_1", "value": 35, "unit": "%"})
    dialled = as_gauge(card, {"view": "gauge"})
    assert dialled.meta["gauge"]["share"] == 35.0
    assert "max" not in dialled.meta["gauge"], "nobody named a ceiling"


def test_a_ceiling_somebody_named_is_kept() -> None:
    """The other half: 38 of 48 MB/s is worth saying."""
    card = WidgetData(primary={"label": "Download", "value": 38, "unit": "MB/s"})
    dialled = as_gauge(card, {"view": "gauge", "gauge_max": 48})
    assert dialled.meta["gauge"]["max"] == 48.0


def test_a_ceiling_the_adapter_named_is_kept() -> None:
    card = WidgetData(primary={"label": "Queue", "value": 3, "unit": ""})
    dialled = as_gauge(card, {"view": "gauge"}, maximum=10)
    assert dialled.meta["gauge"] == {"share": 30.0, "max": 10}


def test_a_card_shown_as_a_dial_may_be_made_as_small_as_a_dial(client: TestClient) -> None:
    """⚠️ The floor followed the renderer the adapter declares, not the one
    that draws the card. Two Synology cards side by side, both showing the
    same dial: the volumes card went down to two columns and the system card
    stopped at three, because "stats" needs room for a row of statistics that
    a dial does not have. Nothing on screen said why.
    """
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    page = board["pages"][0]["id"]

    made = client.post(f"/api/v1/pages/{page}/widgets", json={
        "kind": "synology.system", "title": "Synology",
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    widget_id = made.json()["widget"]["id"]

    def floor_of(widget_id: int) -> list[int]:
        seen = client.get(f"/api/v1/boards/{board['slug']}").json()
        card = next(w for w in seen["pages"][0]["widgets"] if w["id"] == widget_id)
        return card["min_size"]

    # As statistics: three columns, because that is what the rows need.
    assert floor_of(widget_id) == [3, 2]

    switched = client.patch(f"/api/v1/widgets/{widget_id}", json={"options": {"view": "gauge"}}, headers=CSRF)
    assert switched.status_code == 200, switched.text
    assert floor_of(widget_id) == [2, 2], "a dial is still held to the width of a table"

    # And back again.
    client.patch(f"/api/v1/widgets/{widget_id}", json={"options": {"view": "value"}}, headers=CSRF)
    assert floor_of(widget_id)[0] >= 2
