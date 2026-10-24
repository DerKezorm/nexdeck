"""Key figures: a card that holds number cards of its page and draws each as a tile."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.services.holders import is_number_card

from .conftest import CSRF, setup_admin
from .test_groups import _board, _card
from .test_holders import _page, _place, _widget


def test_a_number_card_is_one_that_measures_a_number() -> None:
    # This machine: rows of numbers and metrics it records.
    assert is_number_card("core.host")
    assert is_number_card("uptimekuma.summary")
    # A list, a clock, a note, a number it does not record and a kind nobody knows are not.
    for kind in ("uptimekuma.monitors", "core.clock", "core.markdown", "publicip.address", "nothing.here"):
        assert not is_number_card(kind), kind


def test_key_figures_keep_number_cards_only(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Wall")
    page = board["pages"][0]["id"]
    machine = _card(client, page, "core.host", title="NAS")
    clock = _card(client, page, "core.clock")
    note = _card(client, page, "core.markdown")
    group = _card(client, page, "core.group")
    figures = _card(client, page, "core.figures", options={"cards": [clock["id"], machine["id"], note["id"], group["id"]]})
    assert figures["options"]["cards"] == [machine["id"]], "a clock, a note and a holder are left on the board"


def test_a_number_card_is_dropped_into_key_figures_and_others_are_refused(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Wall")
    page = board["pages"][0]["id"]
    machine = _card(client, page, "core.host", title="NAS")
    clock = _card(client, page, "core.clock")
    figures = _card(client, page, "core.figures", title="Figures")
    answer = _place(client, page, widget_id=machine["id"], into="group", group_id=figures["id"])
    assert answer.status_code == 200, answer.text
    assert _widget(_page(answer.json(), page), figures["id"])["options"]["cards"] == [machine["id"]]
    refused = _place(client, page, widget_id=clock["id"], into="group", group_id=figures["id"])
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "not_a_number"


def test_a_card_picked_for_key_figures_leaves_its_group(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Wall")
    page = board["pages"][0]["id"]
    machine = _card(client, page, "core.host")
    group = _card(client, page, "core.group", options={"cards": []})
    _place(client, page, widget_id=machine["id"], into="group", group_id=group["id"])
    _card(client, page, "core.figures", options={"cards": [machine["id"]]})
    shown = _page(client.get(f"/api/v1/boards/{board['slug']}").json(), page)
    assert _widget(shown, group["id"])["options"]["cards"] == [], "a card stands in one place"


def test_key_figures_survive_export_and_import_with_their_tiles(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Wall")
    page = board["pages"][0]["id"]
    machine = _card(client, page, "core.host", title="NAS")
    _card(client, page, "core.figures", title="Figures", options={"cards": [machine["id"]], "columns": "3"})
    text = client.get(f"/api/v1/boards/{board['slug']}/export").text
    imported = client.post("/api/v1/boards/import", json={"yaml_text": text, "slug": "wall-copy"}, headers=CSRF)
    assert imported.status_code in (200, 201), imported.text
    widgets = {one["title"]: one for one in client.get("/api/v1/boards/wall-copy").json()["pages"][0]["widgets"]}
    assert widgets["Figures"]["options"]["cards"] == [widgets["NAS"]["id"]]
    assert widgets["Figures"]["options"]["columns"] == "3"


def test_key_figures_pass_on_only_the_looks_they_have() -> None:
    meta = get_adapter("core").demo("figures", {"cards": [1, 2], "columns": "5", "tone": "loud", "history": 1}, 0).meta
    assert meta == {"holder": "figures", "holds": 2, "columns": "auto", "tone": "fill", "history": True}
    meta = get_adapter("core").demo("figures", {"columns": "4", "tone": "border"}, 0).meta
    assert (meta["columns"], meta["tone"], meta["history"]) == ("4", "border", False)
