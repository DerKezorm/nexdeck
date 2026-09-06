"""The ring view, and the cards that are not allowed to have one.

A ring claims a share of something. On a card with no ceiling it claims one
that does not exist, and the eye believes the drawing before it reads the
number underneath.
"""

from __future__ import annotations

from app.adapters import all_adapters, get_adapter
from app.adapters.base import WidgetData, as_gauge


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


def test_every_card_offering_the_view_draws_with_a_renderer_that_can() -> None:
    """The ring is drawn by the gauge renderer; a list cannot become one."""
    checked = 0
    for adapter in all_adapters():
        for widget in adapter.widgets:
            if not any(field.name == "view" and any(v == "gauge" for v, _ in field.options) for field in widget.options):
                continue
            checked += 1
            assert widget.renderer in ("value", "gauge"), f"{adapter.kind}.{widget.kind} draws as {widget.renderer}"
    assert checked >= 8, "no card offers it; this test would pass on anything"
