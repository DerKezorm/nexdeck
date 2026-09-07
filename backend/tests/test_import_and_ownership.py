"""What an import may do to a board, and what happens to what an account owns.

⚠️ Two things were true here until 07.09.2026 and should not have been:

* Replacing a board deleted its pages first and looked at what was arriving
  afterwards, so one unknown card kind emptied a board and wrote that down.
  Under provisioning that ran again every ten seconds, and the file that caused
  it was never repaired by anything.
* Deleting an account left its boards behind with no owner. They kept running,
  kept asking their services, kept answering their kiosk links, and appeared in
  nobody's list, because "mine" was false for everyone and "shared" only true
  where a share existed. Nothing in the interface could find them again.

And ``provisioning`` had no tests at all, although it is the one importer that
replaces something that already exists and the one that runs during start-up.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import db_session
from app.models import Board, HistorySample, Page, Widget
from app.services import provisioning

from .conftest import CSRF, create_user, login, setup_admin

GOOD = """
board: {name: The wall, icon: layout}
pages:
  - name: one
    widgets:
      - {kind: core.clock, title: time}
      - {kind: core.markdown, title: a note}
"""

BROKEN_CARD = """
board: {name: The wall, icon: layout}
pages:
  - name: one
    widgets:
      - {kind: core.clock, title: time}
      - {kind: core.notarealkind, title: nonsense}
"""


def _provision(directory: Path, text: str, name: str = "wall.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _cards_of(slug: str) -> list[str]:
    with db_session() as db:
        board = db.scalar(select(Board).where(Board.slug == slug))
        if board is None:
            return []
        return sorted(db.scalars(select(Widget.title).join(Page).where(Page.board_id == board.id)))


def test_a_file_that_will_not_import_leaves_the_board_it_replaces_alone(client: TestClient, data_dir: Path) -> None:
    setup_admin(client)
    path = _provision(data_dir / "boards", GOOD)
    provisioning.load_all()
    assert _cards_of("the-wall") == ["a note", "time"], "the file did not import at all, so this proves nothing"

    path.write_text(BROKEN_CARD, encoding="utf-8")
    provisioning._load(path)
    assert _cards_of("the-wall") == ["a note", "time"], "the board was emptied by a file that was never imported"


def test_a_file_that_is_not_even_a_board_does_not_take_the_start_up_down(client: TestClient, data_dir: Path, caplog) -> None:
    """⚠️ ``load_all`` runs inside the lifespan. An AttributeError from a file
    whose 'board' section is a string took uvicorn down with it, the container
    restarted into the same file, and nobody could sign in to remove it.
    """
    setup_admin(client)
    _provision(data_dir / "boards", GOOD)
    # ⚠️ Not a made-up shape: ``layout`` is written as a mapping and this one
    # is a word, which is the kind of thing that happens to a file typed by
    # hand. It gets past every check that knows what it is looking for and
    # comes apart deeper down, which is the case the net is there for.
    path = _provision(data_dir / "boards", "board: {name: wrong}\npages: [{name: one, widgets: [{kind: core.clock, layout: nope}]}]\n", "wrong.yaml")

    with caplog.at_level(logging.WARNING, logger="nexdeck.provisioning"):
        provisioning.load_all()
    assert _cards_of("the-wall") == ["a note", "time"], "the good file was not loaded"

    # And it is not tried again on every pass of the watch: the file has not
    # changed, so the next round says nothing.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="nexdeck.provisioning"):
        for again in provisioning._files():
            if provisioning._seen.get(again.name) != again.stat().st_mtime:
                provisioning._load(again)
    assert caplog.records == [], "the same broken file was complained about twice"
    assert provisioning._seen.get(path.name) == path.stat().st_mtime


def test_an_import_refuses_an_interval_the_interface_could_never_repair(client: TestClient) -> None:
    """A card could arrive with the text "abc" in a column SQLite is happy to
    keep, and then no form in the browser could put a number back in it.
    """
    setup_admin(client)
    for interval in ("abc", 2, 999_999, True):
        text = f"board: {{name: odd}}\npages:\n  - name: one\n    widgets: [{{kind: core.clock, refresh_seconds: {interval!r}}}]\n"
        refused = client.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF)
        assert refused.status_code == 400, f"{interval!r} went through: {refused.text}"
        assert "refresh interval" in refused.json()["detail"]["message"]


def test_an_import_cannot_reach_a_locked_connection_through_the_options(client: TestClient) -> None:
    """⚠️ ``integration_id`` was checked and the options were not. The merged
    calendar keeps its sources in one, so this was the way past the check that
    the single field has had from the start.
    """
    setup_admin(client)
    made = client.post("/api/v1/integrations", json={
        "kind": "radarr", "name": "Locked films", "config": {"base_url": "http://films.example.com", "api_key": "x" * 32},
        "enabled": True, "demo": True, "admin_only": True,
    }, headers=CSRF)
    assert made.status_code in (200, 201), made.text
    locked = made.json()["id"]
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    text = f"board: {{name: sneaky}}\npages:\n  - name: one\n    widgets: [{{kind: calendar.upcoming, options: {{sources: [{locked}]}}}}]\n"
    refused = kim.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF)
    assert refused.status_code == 400, refused.text
    # The administrator may, because the card form would let them too.
    assert client.post("/api/v1/boards/import", json={"yaml_text": text}, headers=CSRF).status_code == 201


# -- what an account leaves behind --------------------------------------------


def _kims_board(client: TestClient) -> tuple[TestClient, dict, dict]:
    kim = create_user(client, "kim")
    theirs = TestClient(client.app)
    login(theirs, "kim", "another-long-password")
    board = theirs.post("/api/v1/boards", json={"name": "Kim's wall"}, headers=CSRF).json()
    made = theirs.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.clock", "title": "time"}, headers=CSRF)
    assert made.status_code == 201, made.text
    return theirs, kim, board


def test_deleting_an_account_asks_what_becomes_of_its_boards(client: TestClient) -> None:
    setup_admin(client)
    _, kim, board = _kims_board(client)

    hangs = client.get(f"/api/v1/users/{kim['id']}/belongings").json()
    assert [entry["slug"] for entry in hangs["boards"]] == [board["slug"]]

    refused = client.delete(f"/api/v1/users/{kim['id']}", headers=CSRF)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "boards_undecided"
    assert client.get(f"/api/v1/boards/{board['slug']}").status_code == 200, "the account was deleted anyway"


def test_the_boards_can_be_handed_over(client: TestClient) -> None:
    setup_admin(client)
    _, kim, board = _kims_board(client)

    gone = client.delete(f"/api/v1/users/{kim['id']}?boards=hand_over", headers=CSRF)
    assert gone.status_code == 204, gone.text
    mine = client.get("/api/v1/boards").json()
    assert board["slug"] in [entry["slug"] for entry in mine], "the board belongs to nobody again"
    with db_session() as db:
        kept = db.scalar(select(Board).where(Board.slug == board["slug"]))
        assert kept is not None and kept.owner_id is not None


def test_the_boards_can_go_with_the_account_and_take_their_history(client: TestClient) -> None:
    setup_admin(client)
    _, kim, board = _kims_board(client)
    with db_session() as db:
        widget_id = db.scalar(select(Widget.id).join(Page).join(Board).where(Board.slug == board["slug"]))
        db.add(HistorySample(key=f"{widget_id}:load", ts=1, value=1.0))

    gone = client.delete(f"/api/v1/users/{kim['id']}?boards=delete", headers=CSRF)
    assert gone.status_code == 204, gone.text
    with db_session() as db:
        assert db.scalar(select(Board).where(Board.slug == board["slug"])) is None
        left = db.scalar(select(func.count(HistorySample.id)).where(HistorySample.key.like(f"{widget_id}:%")))
        assert left == 0, "the measurements of a deleted card stay, and the next card inherits them"


def test_a_board_cannot_be_handed_to_somebody_who_could_not_hold_it(client: TestClient) -> None:
    """⚠️ ``owner_id`` was written through as it arrived: any number at all,
    including one belonging to nobody, which is the state this whole file is
    about.
    """
    setup_admin(client)
    _, _kim, board = _kims_board(client)
    guest = create_user(client, "sam", role="guest")

    for owner, expected, why in ((999_999, 404, "a number belonging to nobody"), (guest["id"], 400, "a guest, who may not own anything")):
        refused = client.patch(f"/api/v1/boards/{board['slug']}", json={"owner_id": owner}, headers=CSRF)
        assert refused.status_code == expected, f"{why} was accepted: {refused.text}"
        # And the reason reaches the browser, instead of being swallowed and
        # answered with "There is no such address."
        assert "board" in refused.json()["detail"]["message"]


def test_nothing_at_all_coming_out_of_an_import_reaches_the_start_up(client: TestClient, data_dir: Path, monkeypatch) -> None:
    """The net itself, whatever falls into it.

    ⚠️ The test above uses a file broken in a way somebody thought of. This one
    stands for the ways nobody thought of: whatever ``import_board`` raises,
    one bad file is one board missing and nothing else. Without the net the
    container restarts into the same file, the interface never answers, and
    only access to the host gets the file back off the server.
    """
    setup_admin(client)
    _provision(data_dir / "boards", GOOD)

    def comes_apart(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("something nobody thought of")

    monkeypatch.setattr(provisioning, "import_board", comes_apart)
    provisioning.load_all()  # must not raise
    assert _cards_of("the-wall") == [], "the importer was not actually replaced, so this proves nothing"
