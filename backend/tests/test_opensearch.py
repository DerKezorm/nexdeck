"""nexdeck as a search engine of the browser: the description, and the suggestions while somebody types.

The suggestions are asked with every key pressed, by a browser that may or
may not carry a session. They must never say more than the person may see,
and never answer with an error that has something in it.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from .conftest import CSRF, create_user, login, setup_admin
from .test_brand import upload
from .test_go import _board, _made, _tile

NS = {"os": "http://a9.com/-/spec/opensearch/1.1/"}


def _description(client: TestClient) -> ElementTree.Element:
    answer = client.get("/opensearch.xml")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("application/opensearchdescription+xml")
    return ElementTree.fromstring(answer.content)


def test_the_description_names_nexdeck_and_its_two_addresses(client: TestClient) -> None:
    setup_admin(client)
    root = _description(client)
    assert root.findtext("os:ShortName", namespaces=NS) == "nexdeck"
    urls = {url.get("type"): url.get("template") for url in root.findall("os:Url", NS)}
    assert urls == {
        "text/html": "http://testserver/go?q={searchTerms}",
        "application/x-suggestions+json": "http://testserver/api/v1/go/suggestions?q={searchTerms}",
    }
    assert root.findtext("os:Image", namespaces=NS) == "http://testserver/icon-192.png"


def test_the_description_carries_the_installations_own_name_and_logo(client: TestClient) -> None:
    setup_admin(client)
    saved = client.put("/api/v1/settings/brand", json={"name": "Lab <North> & Co, the long one"}, headers=CSRF)
    assert saved.status_code == 200, saved.text
    assert upload(client).status_code == 200
    root = _description(client)
    assert root.findtext("os:ShortName", namespaces=NS) == "Lab <North> & Co", "escaped, and cut to what OpenSearch allows"
    assert "Lab <North> & Co, the long one" in (root.findtext("os:Description", namespaces=NS) or "")
    assert (root.findtext("os:Image", namespaces=NS) or "").startswith("http://testserver/api/v1/brand/icon-192.png")


def test_the_description_uses_the_public_address_when_one_is_set(client: TestClient) -> None:
    setup_admin(client)
    assert client.patch("/api/v1/settings", json={"public_url": "https://deck.example.com/"}, headers=CSRF).status_code == 200
    root = _description(client)
    templates = [str(url.get("template")) for url in root.findall("os:Url", NS)]
    assert len(templates) == 2 and all(one.startswith("https://deck.example.com/") for one in templates)


def test_every_page_tells_the_browser_where_the_description_is() -> None:
    page = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="search" type="application/opensearchdescription+xml" href="/opensearch.xml"' in page


def _suggest(client: TestClient, words: str) -> list:
    answer = client.get("/api/v1/go/suggestions", params={"q": words})
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("application/x-suggestions+json")
    assert answer.headers["cache-control"] == "no-store"
    return answer.json()


def test_tiles_by_their_short_name_come_first_then_cards(client: TestClient) -> None:
    setup_admin(client)
    board = _board(client, "Lab")
    _made(_tile(client, board, "Plex", "https://plex.example.com"))
    _made(_tile(client, board, "Home Assistant", "https://ha.example.com", alias="ha"))
    client.post(f"/api/v1/pages/{board['pages'][0]['id']}/widgets", json={"kind": "core.clock", "title": "Plex clock"}, headers=CSRF)
    words, completions, descriptions = _suggest(client, "pl")
    assert words == "pl"
    assert completions == ["plex", "Plex clock"]
    assert descriptions[0] == "Plex" and descriptions[1].startswith("Lab ") and descriptions[1].endswith(" Overview")
    assert _suggest(client, "assist")[1] == ["ha"], "a tile is found by its name, offered by its short name"
    assert _suggest(client, "lex")[1] == [], "the start of a word, not any letters in it"


def test_nothing_without_a_session_and_nothing_from_a_board_one_may_not_open(client: TestClient) -> None:
    setup_admin(client)
    _made(_tile(client, _board(client, "Private"), "Vault", "https://vault.example.com"))
    assert _suggest(TestClient(client.app), "va") == ["va", [], []]
    create_user(client, "robin")
    member = TestClient(client.app)
    login(member, "robin", "another-long-password")
    assert _suggest(member, "va") == ["va", [], []]
    assert _suggest(client, "va")[1] == ["vault"]


def test_never_an_error_with_something_in_it(client: TestClient) -> None:
    setup_admin(client)
    assert _suggest(client, "") == ["", [], []]
    shared = _board(client, "Shared")
    _made(_tile(client, shared, "Vault", "https://vault.example.com"))
    kim = create_user(client, "kim")
    client.put(f"/api/v1/boards/{shared['slug']}/shares", json={"shares": [{"user_id": kim["id"], "level": "view"}]}, headers=CSRF)
    assert client.patch("/api/v1/settings", json={"require_two_factor": True}, headers=CSRF).status_code == 200
    held = TestClient(client.app)
    login(held, "kim", "another-long-password")
    assert _suggest(held, "va") == ["va", [], []], "held at the door: the board shared with kim stays shut"
    assert _suggest(TestClient(client.app, headers={"Authorization": "Bearer nd_not-a-token"}), "x") == ["x", [], []]
