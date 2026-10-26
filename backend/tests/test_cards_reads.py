"""What the built-in cards of a connection read, offered to the editor as a start (JEDE-4).

Memory only, GET only, only built-in cards, no credentials, at most twenty per connection, and the name the card has on
the board now.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters.base import Context
from app.cards import reads
from app.services.collector import collector

from .conftest import CSRF, create_user, login, setup_admin
from .test_cards_placing import page_of, place
from .test_cards_router import BASE, connection

KEY = "Zk-Key-0123456789"


@pytest.fixture(autouse=True)
def nothing_noted() -> None:
    reads.clear()


def ctx(widget: int | None = 5) -> Context:
    return Context(httpx.AsyncClient(), integration_id=3, widget_id=widget, cache={})


def paths(base: str = BASE, secrets: list[str] | None = None) -> list[str]:
    return [one.path for one in reads.read(3, base, secrets or [])]


@respx.mock
async def test_jede5_a_get_of_a_built_in_card_is_noted_under_the_address_of_the_connection_without_its_key() -> None:
    respx.route().mock(return_value=httpx.Response(200, json={}))
    await ctx().request("GET", f"{BASE}/api/v3/queue?page=1&apikey={KEY}", params={"token": KEY, "limit": 5})
    assert paths() == ["/api/v3/queue?page=1&limit=5"]
    assert all(KEY not in one for one in paths())


@respx.mock
async def test_jede5_only_what_a_built_in_card_reads_is_noted() -> None:
    respx.route().mock(return_value=httpx.Response(200, json={}))
    held = ctx()
    await held.request("POST", f"{BASE}/api/v3/command", json_body={"name": "x"})
    await held.request("GET", f"{BASE}/api/a", note=False)  # a custom card's own request
    await ctx(None).request("GET", f"{BASE}/api/b")  # the Test button has no card
    await held.tapped(lambda *args: None).request("GET", f"{BASE}/api/c")  # a connection test that is watched
    assert paths() == []
    await held.request("GET", f"{BASE}/api/real")
    assert paths() == ["/api/real"]


@respx.mock
async def test_jede5_twenty_paths_at_most_and_the_newest_first() -> None:
    respx.route().mock(return_value=httpx.Response(200, json={}))
    held = ctx()
    for number in range(30):
        await held.request("GET", f"{BASE}/api/n{number}")
    shown = paths()
    assert len(shown) == reads.MOST == 20
    assert shown[0] == "/api/n29" and shown[-1] == "/api/n10"


def test_jede5_a_path_with_a_secret_of_the_connection_in_it_is_not_shown_and_another_address_is_not_this_connection() -> None:
    reads.note(3, 5, "GET", f"{BASE}/api/{KEY}/movies", None)
    reads.note(3, 5, "GET", "http://other.example.com/api/x", None)
    reads.note(3, 5, "GET", f"{BASE}/api/fine", None)
    assert paths(secrets=[KEY]) == ["/api/fine"]
    assert paths(f"{BASE}/prefix") == [], "only what lies under the address of the connection"


def test_jede5_a_path_under_a_prefix_is_shown_relative_to_the_address_of_the_connection() -> None:
    reads.note(3, 5, "GET", f"{BASE}/prefix/api/x", None)
    assert paths(f"{BASE}/prefix") == ["/api/x"]


@respx.mock
def test_jede5_the_editor_is_told_the_cards_by_the_name_they_have_now_and_only_the_cards_that_are_still_on_a_board(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    sonarr = connection(client, "sonarr")
    page = page_of(client)
    made = place(client, page, sonarr, kind="sonarr.queue", card=None, title="Downloads at home")
    assert made.status_code == 201, made.text
    widget = made.json()["widget"]["id"]
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"records": [], "totalRecords": 0}))
    respx.route().mock(return_value=httpx.Response(200, json={}))
    client.post(f"/api/v1/widgets/{widget}/preview", json={"options": {}, "integration_id": sonarr}, headers=CSRF)
    shown = client.get(f"/api/v1/cards/sources/{sonarr}/read")
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert body["cards"] == 1
    assert body["reads"], "the card asked something"
    first = body["reads"][0]
    assert first["path"].startswith("/api/") and first["card"]["id"] == widget and first["card"]["title"] == "Downloads at home"
    assert "apikey" not in shown.text and "key-1" not in shown.text
    # Renamed on the board: the new name is shown. Taken off the board: its paths go with it.
    client.patch(f"/api/v1/widgets/{widget}", json={"title": "Queue now"}, headers=CSRF)
    assert client.get(f"/api/v1/cards/sources/{sonarr}/read").json()["reads"][0]["card"]["title"] == "Queue now"
    client.delete(f"/api/v1/widgets/{widget}", headers=CSRF)
    after = client.get(f"/api/v1/cards/sources/{sonarr}/read").json()
    assert after == {"reads": [], "cards": 0}


def test_jede5_only_administrators_ask_what_the_cards_read(client: TestClient) -> None:
    setup_admin(client)
    sonarr = connection(client, "sonarr")
    for role in ("user", "guest"):
        create_user(client, f"visitor-{role}", role=role)
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert client.get(f"/api/v1/cards/sources/{sonarr}/read").status_code == 401
    for role in ("user", "guest"):
        login(client, f"visitor-{role}", "another-long-password")
        assert client.get(f"/api/v1/cards/sources/{sonarr}/read").status_code == 403, role
        client.post("/api/v1/auth/logout", headers=CSRF)


def test_jede5_a_kind_that_cannot_be_read_says_so_and_a_missing_connection_is_a_404(client: TestClient) -> None:
    setup_admin(client)
    docker = client.post("/api/v1/integrations", json={"kind": "docker", "name": "Engine", "config": {"host": BASE}}, headers=CSRF).json()["id"]
    refused = client.get(f"/api/v1/cards/sources/{docker}/read")
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "no_raw_access"
    assert client.get("/api/v1/cards/sources/9999/read").status_code == 404


# -- korrektur J1, F4: what the connection puts into an address to prove who asks is not offered, and does not crowd ----------


@respx.mock
def test_korrektur_f4_the_user_name_the_token_and_the_salt_of_navidrome_are_not_offered_and_a_new_salt_is_no_new_entry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    made = client.post(
        "/api/v1/integrations",
        json={"kind": "navidrome", "name": "Music", "config": {"url": BASE, "username": "anna-music", "password": "Zk-password-1"}},
        headers=CSRF,
    )
    assert made.status_code == 201, made.text
    music = int(made.json()["id"])
    page = page_of(client)
    widget = place(client, page, music, kind="navidrome.library", card=None, title="Music").json()["widget"]["id"]
    respx.route().mock(return_value=httpx.Response(200, json={"subsonic-response": {"status": "ok", "version": "1.16.1"}}))
    sizes = []
    for _ in range(3):
        client.post(f"/api/v1/widgets/{widget}/preview", json={"options": {}, "integration_id": music}, headers=CSRF)
        shown = client.get(f"/api/v1/cards/sources/{music}/read").json()["reads"]
        sizes.append(len(shown))
        assert shown, "the card asked something"
        for one in shown:
            assert not any(part in one["path"] for part in ("anna-music", "Zk-password-1", "u=", "t=", "s=")), one["path"]
    assert len(set(sizes)) == 1, "a salt that changes with every call renews an entry, it does not add one"


def test_korrektur_f4_a_value_that_is_a_credential_of_the_connection_leaves_whatever_the_parameter_is_called() -> None:
    reads.note(3, 5, "GET", f"{BASE}/api/x?who=anna-music&page=2&alias=Zk-secret-value", None)
    shown = reads.read(3, BASE, [], names=frozenset(), values=frozenset({"anna-music", "Zk-secret-value"}))
    assert [one.path for one in shown] == ["/api/x?page=2"]


def test_korrektur_f4_a_path_that_comes_with_other_values_is_one_entry_and_other_paths_keep_their_place() -> None:
    for number in range(40):
        reads.note(3, 5, "GET", f"{BASE}/rest/getScanStatus?s=salt{number}&t=tok{number}", None)
        reads.note(3, 6, "GET", f"{BASE}/rest/getOther{number % 3}", None)
    shown = [one.path for one in reads.read(3, BASE, [])]
    assert len([one for one in shown if one.startswith("/rest/getScanStatus")]) == 1
    assert {"/rest/getOther0", "/rest/getOther1", "/rest/getOther2"} <= set(shown)
