"""The four forms of a custom card: what the finished values become, and how they are drawn like any other card (KARTEN-6)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import Context, WidgetData, shape_for_display
from app.adapters.custom import present
from app.cards import images, load, pipeline, store
from app.db import db_session
from app.services import holders
from app.services.collector import collector
from app.services.state import live

from .cards_sample import VALUE_CARD
from .conftest import CSRF, setup_admin
from .test_cards_placing import BASE, connection, page_of, place

HEAD = """\
nexdeck-card: 1
slug: {slug}
name: Sample
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
"""

STATS = HEAD.format(slug="disk") + """\
form: stats
stats:
  - {path: used, label: {en: Used, de: Belegt}, unit: "%", format: percent, rules: [{op: ">=", than: 90, then: bad}]}
  - {path: free, label: Free, format: bytes}
  - {path: name, label: Name}
demo:
  queue: {used: 71, free: 5368709120, name: nas}
"""

LIST = HEAD.format(slug="waiting") + """\
form: list
rows: {select: records, sort: {field: size, desc: true}, limit: 3}
empty: {en: Nothing waiting, de: Nichts wartet}
item:
  title: title
  subtitle: {template: "{series} S{season}"}
  value: {path: size, format: bytes}
  status: [{op: ">", than: 1000, then: warn}]
  link: url
  image: poster
demo:
  queue: {records: [{title: A, series: X, season: 1, size: 5000, url: "https://example.com/a", poster: /poster/a.jpg}]}
"""

POSTERS = HEAD.format(slug="covers") + """\
form: posters
rows: {select: records}
item:
  image: poster
  title: title
  subtitle: series
  link: url
demo:
  queue: {records: [{title: A, series: X, poster: "https://img.example.com/a.jpg", url: "https://example.com/a"}]}
"""


def made(text: str, answers: dict[str, Any], **keywords: Any) -> WidgetData:
    definition = load.load_definition(text).definition
    return present(definition, pipeline.run(definition, {"queue": answers}), **keywords)


RECORDS = {"records": [
    {"title": "Small", "series": "X", "season": 1, "size": 10, "url": "https://example.com/s", "poster": "/p/small.jpg"},
    {"title": "Big", "series": "Y", "season": 2, "size": 5000, "url": "javascript:alert(1)", "poster": "https://img.example.com/b.jpg"},
    {"title": "Odd", "series": "Z", "season": 3, "size": 2000, "url": "/relative", "poster": "data:image/png;base64,AAAA"},
    {"title": "Odder", "series": "W", "season": 4, "size": 1, "url": "ftp://example.com/x", "poster": "javascript:alert(1)"},
]}


# -- AC-1, AC-2: one number ---------------------------------------------------------------


def test_karten6_ac1_a_number_card_has_a_value_a_unit_a_colour_and_a_history() -> None:
    data = made(VALUE_CARD, {"totalRecords": 12})
    assert data.primary == {"label": {"en": "Waiting", "de": "Wartend"}, "value": 12, "unit": "items", "format": "number", "digits": None, "text": "12"}
    assert (data.status, data.metrics, data.meta["custom"]) == ("warn", {"value": 12.0}, True)
    assert made(VALUE_CARD, {"totalRecords": 3}).status == "ok"


def test_karten6_ac1_a_number_card_offers_the_dial_the_leds_the_digits_and_the_chart() -> None:
    widget = get_adapter("custom").widget("value")
    view = next(field for field in widget.options if field.name == "view")
    assert {"value", "gauge", "meter", "segments", "chart"} <= {value for value, _label in view.options}
    names = {field.name for field in widget.options}
    assert {"gauge_max", "gauge_min", "level_warn", "level_bad", "meter_direction", "chart_hours"} <= names


@pytest.mark.parametrize("view", ["gauge", "meter", "segments"])
def test_karten6_ac1_the_views_of_a_number_card_follow_yellow_from_and_red_from(view: str) -> None:
    adapter = get_adapter("custom")
    data = made(VALUE_CARD.replace("rules:\n  - {value: totalRecords, op: \">=\", than: 10, then: warn}\n", ""), {"totalRecords": 70})
    assert data.status == "ok"
    options = {"view": view, "gauge_max": 100, "level_warn": 60, "level_bad": 90}
    shaped = shape_for_display(data, adapter, "value", options)
    assert shaped.meta["level"] == "warn" and shaped.meta["renderer"] == view
    assert view == "segments" or shaped.meta["gauge"]["share"] == 70
    shaped_bad = shape_for_display(made(VALUE_CARD, {"totalRecords": 95}), adapter, "value", options)
    assert shaped_bad.meta["level"] == "bad"


def test_karten6_ac1_a_percentage_is_a_dial_without_being_told_what_full_is() -> None:
    definition = VALUE_CARD.replace("unit: items", "unit: x\n  format: percent")
    data = shape_for_display(made(definition, {"totalRecords": 40}), get_adapter("custom"), "value", {"view": "gauge"})
    assert data.primary["unit"] == "%" and data.meta["gauge"]["share"] == 40


def test_karten6_ac2_a_number_card_is_a_tile_of_key_figures_and_a_list_is_not() -> None:
    assert holders.is_number_card("custom.value") and holders.is_number_card("custom.stats")
    assert not holders.is_number_card("custom.list") and not holders.is_number_card("custom.posters")


@pytest.fixture
def stand(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, int, int]:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    # Keyed by card number, which every fresh database starts counting at 1 again.
    from app.routers import widgets as widget_routes

    widget_routes._images.clear()
    with db_session() as db:
        for text in (VALUE_CARD, STATS, LIST, POSTERS):
            store.create(db, text.replace("requires: [sonarr, radarr]", "requires: [sonarr]"))
    return client, page_of(client), connection(client, "sonarr")


def test_karten6_ac2_the_api_takes_a_custom_number_into_key_figures_and_refuses_a_list(stand: tuple[TestClient, int, int]) -> None:
    client, page, sonarr = stand
    figures = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.figures", "title": "Figures"}, headers=CSRF).json()["widget"]
    number = place(client, page, sonarr).json()["widget"]
    rows = place(client, page, sonarr, kind="custom.list", card="waiting").json()["widget"]
    taken = client.post(f"/api/v1/pages/{page}/place", json={"widget_id": number["id"], "into": "group", "group_id": figures["id"]}, headers=CSRF)
    assert taken.status_code == 200, taken.text
    refused = client.post(f"/api/v1/pages/{page}/place", json={"widget_id": rows["id"], "into": "group", "group_id": figures["id"]}, headers=CSRF)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "not_a_number"


# -- AC-3: several numbers ----------------------------------------------------------------


def test_karten6_ac3_several_numbers_come_side_by_side_with_their_labels() -> None:
    data = made(STATS, {"used": 95, "free": 5368709120, "name": "nas"})
    labels = [data.primary["label"], *(row["label"] for row in data.secondary)]
    assert labels == [{"en": "Used", "de": "Belegt"}, "Free", "Name"]
    assert (data.primary["value"], data.primary["unit"]) == (95, "%")
    assert data.secondary[0]["text"] == "5.0 GB" and data.secondary[1]["value"] == "nas"
    assert data.status == "bad", "the rule on the first value colours the card"
    assert [data.primary["metric"], *(row["metric"] for row in data.secondary)] == ["stat1", "stat2", "stat3"]
    assert set(data.metrics) == {"stat1", "stat2"}


def test_karten6_ac3_two_to_six_values_and_no_other_number() -> None:
    from pydantic import ValidationError

    from app.cards.schema import ADAPTER

    base = {"nexdeck-card": 1, "slug": "x", "name": "X", "version": "1.0.0", "requires": ["sonarr"], "requests": [{"id": "q", "path": "/a"}], "form": "stats"}
    ADAPTER.validate_python({**base, "stats": ["a", "b"]})
    ADAPTER.validate_python({**base, "stats": list("abcdef")})
    for wrong in (["a"], list("abcdefg")):
        with pytest.raises(ValidationError):
            ADAPTER.validate_python({**base, "stats": wrong})
    assert len(get_adapter("custom").widget("stats").metrics) == 6


# -- AC-4, EC-1, EC-4, EC-5, EC-8: a list ----------------------------------------------------


def test_karten6_ac4_every_row_has_a_title_a_subtitle_a_value_a_status_and_a_link() -> None:
    data = made(LIST, RECORDS, base=BASE)
    big = data.items[0]
    assert (big["title"], big["subtitle"], big["value"], big["status"]) == ("Big", "Y S2", "4.9 KB", "warn")
    assert data.items[-1]["status"] == "ok"
    assert data.items[1]["title"] == "Odd" and len(data.items) == 3, "sorted by size, three of four"


def test_karten6_ac4_a_list_shows_fifty_rows_at_most() -> None:
    rows = {"records": [{"title": f"T{number}", "series": "S", "season": 1, "size": number} for number in range(120)]}
    unlimited = made(LIST.replace(", limit: 3", ""), rows)
    assert len(unlimited.items) == 10, "ten is the default"
    fifty = made(LIST.replace("limit: 3", "limit: 50"), rows)
    assert len(fifty.items) == 50
    with pytest.raises(load.CardInvalid):
        load.load_definition(LIST.replace("limit: 3", "limit: 51"))


def test_karten6_ec1_an_empty_list_has_the_text_of_the_definition_or_none() -> None:
    data = made(LIST, {"records": []})
    assert data.items == [] and data.meta["empty"] == {"en": "Nothing waiting", "de": "Nichts wartet"}
    assert made(LIST.replace("empty: {en: Nothing waiting, de: Nichts wartet}\n", ""), {"records": []}).meta["empty"] is None


def test_karten6_ec4_a_long_title_arrives_whole_for_the_card_to_cut() -> None:
    long = "x" * 400
    data = made(LIST, {"records": [{"title": long, "series": "S", "season": 1, "size": 1}]})
    assert data.items[0]["title"] == long


def test_karten6_ec5_a_link_that_is_not_http_is_not_a_link() -> None:
    data = made(LIST.replace("limit: 3", "limit: 10"), RECORDS)
    by_title = {item["title"]: item for item in data.items}
    assert by_title["Small"]["url"] == "https://example.com/s"
    for title in ("Big", "Odd", "Odder"):
        assert "url" not in by_title[title], title
    posters = made(POSTERS, RECORDS)
    assert [("url" in item) for item in posters.items] == [True, False, False, False]


# -- AC-5, EC-3, EC-7: pictures ----------------------------------------------------------------


def test_karten6_ac5_a_picture_wall_has_a_picture_a_title_and_a_link() -> None:
    data = made(POSTERS, RECORDS, base=BASE)
    first = data.items[0]
    assert (first["title"], first["subtitle"], first["url"]) == ("Small", "X", "https://example.com/s")
    assert first["art"] == "proxy:/p/small.jpg"
    assert get_adapter("custom").widget("posters").renderer == "posters"


def test_karten6_ec3_a_picture_on_another_host_goes_through_the_proxy_without_the_credentials() -> None:
    art = made(POSTERS, RECORDS, base=BASE).items[1]["art"]
    assert art.startswith(f"proxy:{images.EXTERNAL}?u=") and "img.example.com" in quote("https://img.example.com/b.jpg", safe="") and "s=" in art
    assert images.external_address(art.removeprefix("proxy:")) == "https://img.example.com/b.jpg"


def test_karten6_ec3_a_picture_under_the_address_of_the_connection_keeps_the_credentials() -> None:
    assert images.reference(f"{BASE}/MediaCover/1/poster.jpg", BASE) == "proxy:/MediaCover/1/poster.jpg"
    assert images.reference("/MediaCover/1/poster.jpg", BASE) == "proxy:/MediaCover/1/poster.jpg"


@pytest.mark.parametrize("link", ["data:image/png;base64,AAAA", "javascript:alert(1)", "file:///etc/passwd", "ftp://example.com/a.png", "//img.example.com/a.png", "/a/../b.png", "", "https://user:pw@img.example.com/a.png"])
def test_karten6_ec7_an_address_that_is_no_picture_address_is_a_placeholder(link: str) -> None:
    assert images.reference(link, BASE) == ""


def test_karten6_ec7_a_row_without_a_usable_picture_has_no_art() -> None:
    data = made(POSTERS, RECORDS)
    assert "art" in data.items[0] and "art" in data.items[1]
    assert "art" not in data.items[2] and "art" not in data.items[3]


def test_karten6_ec3_a_forged_or_changed_signature_names_no_address() -> None:
    art = images.reference("https://img.example.com/a.jpg").removeprefix("proxy:")
    assert images.external_address(art) == "https://img.example.com/a.jpg"
    assert images.external_address(art.replace("img.example.com", "evil.example.com")) is None
    assert images.external_address(art[:-4] + "0000") is None
    assert images.external_address(f"{images.EXTERNAL}?u={quote('https://img.example.com/a.jpg', safe='')}") is None
    assert images.external_address("/other?u=x&s=y") is None


def _picture_route(client: TestClient, widget: int, art: str):  # noqa: ANN202
    return client.get(f"/api/v1/widgets/{widget}/image", params={"path": art.removeprefix("proxy:")})


@respx.mock
def test_karten6_ec3_the_route_fetches_a_foreign_picture_without_credentials_and_serves_it(stand: tuple[TestClient, int, int]) -> None:
    client, page, sonarr = stand
    widget = place(client, page, sonarr, kind="custom.posters", card="covers").json()["widget"]["id"]
    foreign = respx.get("https://img.example.com/a.jpg").mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
    own = respx.get(f"{BASE}/p/small.jpg").mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
    answer = _picture_route(client, widget, images.reference("https://img.example.com/a.jpg", BASE))
    assert (answer.status_code, answer.headers["content-type"]) == (200, "image/png")
    sent = {name.lower() for name in foreign.calls.last.request.headers}
    assert not sent & {"x-api-key", "authorization", "cookie"}, "the key of the connection went to another host"
    # A picture of the connection itself keeps going through its credentials.
    assert _picture_route(client, widget, images.reference("/p/small.jpg", BASE)).status_code == 200
    assert own.calls.last.request.headers["x-api-key"] == "key-1"


@respx.mock
@pytest.mark.parametrize("address", ["http://127.0.0.1:8080/a.png", "http://169.254.169.254/latest/meta-data/a.png", "http://localhost/a.png", "http://metadata.google.internal/a.png"])
def test_karten6_ec3_the_route_keeps_the_network_rule_for_a_foreign_picture(stand: tuple[TestClient, int, int], address: str) -> None:
    client, page, sonarr = stand
    widget = place(client, page, sonarr, kind="custom.posters", card="covers").json()["widget"]["id"]
    reached = respx.route().mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
    answer = _picture_route(client, widget, images.reference(address, BASE))
    assert answer.status_code == 404 and answer.json()["detail"]["code"] == "forbidden_host"
    assert not reached.called


@respx.mock
def test_karten6_ec3_the_route_follows_no_redirect_into_the_inside(stand: tuple[TestClient, int, int]) -> None:
    client, page, sonarr = stand
    widget = place(client, page, sonarr, kind="custom.posters", card="covers").json()["widget"]["id"]
    respx.get("https://img.example.com/a.jpg").mock(return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}))
    inside = respx.get("http://169.254.169.254/latest/meta-data/").mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
    answer = _picture_route(client, widget, images.reference("https://img.example.com/a.jpg", BASE))
    assert answer.status_code == 404 and not inside.called


@respx.mock
def test_karten6_ec3_the_route_serves_only_addresses_the_card_itself_named(stand: tuple[TestClient, int, int]) -> None:
    client, page, sonarr = stand
    widget = place(client, page, sonarr, kind="custom.posters", card="covers").json()["widget"]["id"]
    clock = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.clock"}, headers=CSRF).json()["widget"]["id"]
    reached = respx.route().mock(return_value=httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"}))
    unsigned = f"{images.EXTERNAL}?u={quote('https://img.example.com/a.jpg', safe='')}&s=" + "0" * 32
    assert client.get(f"/api/v1/widgets/{widget}/image", params={"path": unsigned}).status_code == 400
    assert client.get(f"/api/v1/widgets/{clock}/image", params={"path": images.reference("https://img.example.com/a.jpg").removeprefix("proxy:")}).status_code == 400
    assert not reached.called


@respx.mock
def test_karten6_ec2_a_picture_that_is_none_is_a_failed_picture_and_the_card_stays_green(stand: tuple[TestClient, int, int]) -> None:
    client, page, sonarr = stand
    widget = place(client, page, sonarr, kind="custom.posters", card="covers").json()["widget"]["id"]
    respx.get("https://img.example.com/a.jpg").mock(return_value=httpx.Response(200, text="<html>not a picture</html>", headers={"content-type": "text/html"}))
    answer = _picture_route(client, widget, images.reference("https://img.example.com/a.jpg", BASE))
    assert answer.status_code == 404
    assert made(POSTERS, RECORDS).status == "ok"


# -- AC-7 to AC-9: the ways every card goes ------------------------------------------------


@respx.mock
async def test_karten6_ac8_a_card_that_turns_yellow_is_in_the_chronicle_and_on_the_attention_card(stand: tuple[TestClient, int, int]) -> None:
    client, page, sonarr = stand
    widget = place(client, page, sonarr, refresh_seconds=10).json()["widget"]["id"]
    attention = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.problems", "title": "Attention"}, headers=CSRF).json()["widget"]
    collector.unschedule(attention["id"])
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 3}))
    await collector.refresh(widget)
    assert live.get(widget).status == "ok"
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 12}))
    collector._caches.clear()
    await collector.refresh(widget)
    assert live.get(widget).status == "warn"
    lines = client.get("/api/v1/chronicle").json()["events"]
    assert any(line["kind"] == "card" and (line["before"], line["after"]) == ("ok", "warn") and line["target"]["widget"] == widget for line in lines), lines
    ctx = Context(httpx.AsyncClient(), widget_id=attention["id"], cache={})
    read = await get_adapter("core").fetch("problems", {}, {"updates": False}, ctx)
    assert [(item["title"], item["status"]) for item in read.items] == [("Queue", "warn")]


def test_karten6_ac9_a_custom_card_goes_into_a_group_and_a_tab_and_the_side_bar(stand: tuple[TestClient, int, int]) -> None:
    client, page, sonarr = stand
    group = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.group", "title": "Group"}, headers=CSRF).json()["widget"]
    card = place(client, page, sonarr).json()["widget"]
    into = client.post(f"/api/v1/pages/{page}/place", json={"widget_id": card["id"], "into": "group", "group_id": group["id"]}, headers=CSRF)
    assert into.status_code == 200, into.text
    assert client.patch(f"/api/v1/pages/{page}", json={"side_place": "left"}, headers=CSRF).status_code == 200
    side = client.post(f"/api/v1/pages/{page}/place", json={"widget_id": card["id"], "into": "side"}, headers=CSRF)
    assert side.status_code == 200 and card["id"] in next(one for one in side.json()["pages"] if one["id"] == page)["side"]["cards"]
    tabs = client.post(f"/api/v1/pages/{page}/widgets", json={"kind": "core.tabs", "title": "Tabs"}, headers=CSRF)
    assert tabs.status_code == 201


def test_karten6_ac1_every_card_of_the_custom_adapter_declares_what_the_floor_of_its_drawing_needs() -> None:
    from app.adapters.base import RENDERER_MIN

    for widget in get_adapter("custom").widgets:
        floor = RENDERER_MIN[widget.renderer]
        assert widget.min_size[0] >= floor[0] and widget.min_size[1] >= floor[1], widget.kind
        assert widget.default_size[0] >= widget.min_size[0] and widget.default_size[1] >= widget.min_size[1]


def test_karten6_the_demo_of_every_form_is_the_example_answers_of_its_definition(stand: tuple[TestClient, int, int]) -> None:
    adapter = get_adapter("custom")
    stats = adapter.demo("stats", {"card": "disk"}, 0)
    assert (stats.primary["value"], [row["text"] for row in stats.secondary]) == (71, ["5.0 GB", "nas"])
    rows = adapter.demo("list", {"card": "waiting"}, 0)
    assert rows.items[0]["title"] == "A" and "art" not in rows.items[0], "a demo reaches no host"
    assert adapter.demo("posters", {"card": "covers"}, 0).items[0]["title"] == "A"


def test_karten6_the_text_of_the_author_is_never_looked_up_in_the_table_of_translations() -> None:
    """The label travels as the author wrote it, language by language, for the browser to pick; nothing here translates it."""
    data = made(VALUE_CARD, {"totalRecords": 1})
    assert data.primary["label"] == {"en": "Waiting", "de": "Wartend"} and data.meta["custom"] is True


def test_karten6_the_assistant_reads_a_custom_card_as_text_not_as_a_dictionary() -> None:
    from app.services.assistant.tools import _headline

    assert _headline(made(VALUE_CARD, {"totalRecords": 12})) == "Waiting: 12 items"
    assert _headline(made(STATS, {"used": 71, "free": 1, "name": "nas"})) == "Used: 71%"
