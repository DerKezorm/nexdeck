"""What nexdeck can ask of each kind of service is found in the code and kept in a file that this test makes again (lesen L1, L2, L3).

The file ``app/cards/card_reads.json`` is made by ``tools/card_reads.py`` from the built-in cards themselves: each one is
fetched against a stand-in service and the GET requests that leave are written down. A test that compared the file with a
list typed by hand would prove nothing; this one compares it with what the adapters do now.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.adapters import all_adapters, get_adapter
from app.adapters.base import NOT_READ_BY_CARDS, Context
from app.cards import card_reads
from app.credential_names import is_credential_name

from .conftest import CSRF, create_user, login, setup_admin

TOOL = Path(__file__).resolve().parent.parent / "tools" / "card_reads.py"


def tool():
    spec = importlib.util.spec_from_file_location("card_reads_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def made():
    module = tool()
    return module, module.build()


def readable() -> set[str]:
    return {one.kind for one in all_adapters() if one.kind not in NOT_READ_BY_CARDS}


def test_lesen_l2_the_file_is_what_the_code_gives_now(made) -> None:
    module, found = made
    assert json.loads(card_reads.TARGET.read_text(encoding="utf-8")) == json.loads(module.render(found)), (
        "A built-in card asks something else than the file says. Make it again: cd backend && python tools/card_reads.py"
    )
    assert card_reads.TARGET.read_text(encoding="utf-8") == module.render(found), "same content, other spelling: make the file again"


def test_lesen_l2_the_list_is_made_by_asking_not_typed(made) -> None:
    """Sonarr's queue is on the list because its card asks for it: an adapter whose card asks another path changes the answer."""
    _, found = made
    sonarr = {one["path"]: one["widgets"] for one in found["sonarr"]}
    assert "queue" in sonarr["/api/v3/queue?pageSize=100&includeUnknownMovieItems=true"]
    assert any(one["path"] == "/api/v2/torrents/info?filter=downloading" for one in found["qbittorrent"]), "a kind with a client of its own"
    assert any(one["path"].startswith("/proxy/network/integration/v1/sites") for one in found["unifi"]), "UniFi's own client too"


def test_lesen_l1_every_entry_names_a_card_of_its_kind_and_a_path_under_the_address() -> None:
    kinds = card_reads.kinds_with_reads()
    assert len(kinds) > 100
    for kind in kinds:
        adapter = get_adapter(kind)
        assert kind in readable(), f"{kind} cannot be read by a custom card"
        for one in card_reads.reads_of(kind):
            assert one["path"].startswith("/") and one["path"] != "/" and len(one["path"]) <= 300, (kind, one)
            for widget in one["widgets"]:
                assert adapter.widget(widget).label, (kind, widget)


def test_lesen_l1_nothing_that_proves_who_asks_is_in_a_path() -> None:
    for kind in card_reads.kinds_with_reads():
        for one in card_reads.reads_of(kind):
            parts = urlsplit(one["path"])
            for name, value in parse_qsl(parts.query, keep_blank_values=True):
                assert not is_credential_name(name), (kind, one)
                assert not re.match(r"^(\d{4}-\d{2}-\d{2}|\d{10})", value), f"a moment is not part of where the data lives: {kind} {one}"
            assert "zk" not in one["path"].lower() and "://" not in one["path"], (kind, one)
    assert "t=" not in json.dumps(card_reads.reads_of("navidrome")), "Navidrome's token and salt do not leave"


def test_lesen_l1_what_comes_from_the_connection_is_a_place_not_a_value() -> None:
    assert {"path": "/api/states/{entity_id}", "widgets": ["entity", "entities"]} in card_reads.reads_of("homeassistant")
    paths = [one["path"] for one in card_reads.reads_of("github")]
    assert "/repos/{owner}/{repo}/releases/latest" in paths
    assert any(one["path"] == "/zones?name={zone}" for one in card_reads.reads_of("cloudflare")), "written in lower case by the service, found all the same"


def test_lesen_l3_a_kind_without_reads_stands_with_its_reason(made) -> None:
    module, found = made
    assert set(module.GAPS) == readable() - set(found), "put a kind with no reads into GAPS with the reason, or take one out that has them now"
    assert all(len(reason) > 20 for reason in module.GAPS.values())


def test_lesen_l3_home_assistant_has_the_rest_paths_of_its_documentation() -> None:
    paths = {one["path"]: one["widgets"] for one in card_reads.reads_of("homeassistant")}
    assert paths["/api/states"] == ["entities"]
    assert paths["/api/config"] == [], "no card asks it: from the documentation, without a card's name"


def test_lesen_l1_a_kind_nobody_knows_has_nothing() -> None:
    assert card_reads.reads_of("nothing-like-it") == []


# -- L5: the list by kind, for administrators ----------------------------------------------------------------------


def test_lesen_l5_the_list_of_a_kind_comes_without_a_connection_or_a_card_on_a_board(client: TestClient) -> None:
    setup_admin(client)
    shown = client.get("/api/v1/cards/sources/sonarr/reads")
    assert shown.status_code == 200, shown.text
    reads = {one["path"]: one["widgets"] for one in shown.json()["reads"]}
    assert reads["/api/v3/queue?pageSize=100&includeUnknownMovieItems=true"] == [{"kind": "queue", "label": get_adapter("sonarr").widget("queue").label}]
    assert "zk" not in shown.text.lower() and "apikey" not in shown.text.lower()
    assert client.get("/api/v1/cards/sources/synology/reads").json() == {"reads": []}, "a kind with nothing known has an empty list, not an error"


def test_lesen_l5_only_administrators_ask(client: TestClient) -> None:
    setup_admin(client)
    for role in ("user", "guest"):
        create_user(client, f"visitor-{role}", role=role)
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert client.get("/api/v1/cards/sources/sonarr/reads").status_code == 401
    for role in ("user", "guest"):
        login(client, f"visitor-{role}", "another-long-password")
        assert client.get("/api/v1/cards/sources/sonarr/reads").status_code == 403, role
        client.post("/api/v1/auth/logout", headers=CSRF)


def test_lesen_l5_a_kind_that_cannot_be_read_says_so_and_a_kind_nobody_knows_is_a_404(client: TestClient) -> None:
    setup_admin(client)
    refused = client.get("/api/v1/cards/sources/docker/reads")
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "no_raw_access"
    assert client.get("/api/v1/cards/sources/nothing-like-it/reads").status_code == 404


def test_lesen_l4_the_memory_of_what_a_card_asked_is_gone() -> None:
    import importlib.util
    import inspect

    assert importlib.util.find_spec("app.cards.reads") is None
    assert "note" not in inspect.signature(Context.request).parameters
