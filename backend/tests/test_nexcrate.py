"""nexcrate: the library read once and then only what changed, the cards in
words that can be translated, the refusals in plain words, and the pairing
that brings the key without anyone copying it."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context
from app.adapters.nexcrate import TITLES

from .conftest import CSRF, create_user, login, setup_admin

URL = "http://nexcrate.example.com"
API = f"{URL}/api/v1"
CONFIG = {"url": URL, "api_key": "nxc_test-key"}
NEXCRATE = get_adapter("nexcrate")


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=None, widget_id=1, cache={})


def title(kind: str, ref: int, *states: str, seq: int = 1, name: str = "Title") -> dict:
    return {"kind": kind, "ref": ref, "name": name, "year": 2025, "seq": seq, "versions": [{"state": s} for s in states]}


def page(items: list[dict], after: int, more: bool = False, removed: list[dict] | None = None) -> httpx.Response:
    return httpx.Response(200, json={"items": items, "removed": removed or [], "next_after": after, "more": more})


def no_findings() -> None:
    respx.get(f"{API}/health").mock(return_value=httpx.Response(200, json={"items": []}))


# -- the library -----------------------------------------------------------------


@respx.mock
async def test_the_library_is_read_in_pages_once_and_then_only_what_changed(ctx: Context) -> None:
    no_findings()
    route = respx.get(f"{API}/titles").mock(side_effect=[
        page([title("movie", 1, "available"), title("movie", 2, "wanted")], after=2, more=True),
        page([title("series", 3, "available")], after=3),
        page([title("movie", 2, "available")], after=4, removed=[{"kind": "series", "ref": 3}]),
    ])
    first = await NEXCRATE.fetch("library", CONFIG, {}, ctx)
    assert [call.request.url.params["after"] for call in route.calls] == ["0", "2"]
    assert first.primary == {"label": "In the library", "value": 2}

    second = await NEXCRATE.fetch("library", CONFIG, {}, ctx)
    assert route.calls[2].request.url.params["after"] == "3", "the second reading asks only for what changed"
    assert second.primary["value"] == 2, "one film arrived, the series was removed"
    assert route.calls[0].request.headers["authorization"] == "Bearer nxc_test-key"


@respx.mock
async def test_the_chips_by_kind_add_up_to_the_number_above_them(ctx: Context) -> None:
    no_findings()
    respx.get(f"{API}/titles").mock(return_value=page([
        title("movie", 1, "available"), title("movie", 2, "wanted"), title("series", 3, "upgrade"),
        title("album", 4, "available"), title("album", 5, "unmonitored"), title("album", 6, "unmonitored"),
        title("artist", 7, "available"),
    ], after=7))
    data = await NEXCRATE.fetch("library", CONFIG, {}, ctx)
    chips = {row["label"]: row["value"] for row in data.secondary}
    assert data.primary["value"] == 3, "an artist is no title of the library"
    assert chips["Films"] + chips["Series"] + chips["Albums"] == 3
    assert chips["Albums"] == 1, "albums nobody wants are not counted as there"
    assert chips["Wanted"] == 1


@respx.mock
async def test_a_marker_older_than_nexcrate_keeps_starts_the_reading_over(ctx: Context) -> None:
    no_findings()
    ctx.cache[TITLES] = {"after": 50, "items": {"movie:9": title("movie", 9, "available")}}
    route = respx.get(f"{API}/titles").mock(side_effect=[
        httpx.Response(410, json={"code": "marker_too_old", "message": "Too old."}),
        page([title("movie", 1, "available"), title("movie", 2, "available")], after=60),
    ])
    data = await NEXCRATE.fetch("library", CONFIG, {}, ctx)
    assert route.calls[1].request.url.params["after"] == "0"
    assert data.primary["value"] == 2, "what was kept before is thrown away, not added to"


@respx.mock
async def test_a_first_reading_cut_off_halfway_goes_on_where_it_stopped(ctx: Context) -> None:
    no_findings()
    route = respx.get(f"{API}/titles").mock(side_effect=[
        page([title("movie", 1, "available")], after=1, more=True),
        httpx.ReadTimeout("slow"),
        page([title("movie", 2, "available")], after=2),
    ])
    with pytest.raises(AdapterError):
        await NEXCRATE.fetch("library", CONFIG, {}, ctx)
    data = await NEXCRATE.fetch("library", CONFIG, {}, ctx)
    assert route.calls[2].request.url.params["after"] == "1"
    assert data.primary["value"] == 2


@respx.mock
async def test_two_cards_starting_together_read_the_library_once(ctx: Context) -> None:
    no_findings()
    respx.post(f"{API}/titles/why").mock(return_value=httpx.Response(200, json={"items": [{"why": {"versions": []}}]}))

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        after = int(request.url.params["after"])
        return page([title("movie", 1, "wanted")] if after == 0 else [], after=5)

    route = respx.get(f"{API}/titles").mock(side_effect=slow)
    await asyncio.gather(NEXCRATE.fetch("library", CONFIG, {}, ctx), NEXCRATE.fetch("why", CONFIG, {}, ctx))
    assert [call.request.url.params["after"] for call in route.calls] == ["0", "5"]


# -- the other cards --------------------------------------------------------------


@respx.mock
async def test_why_counts_what_is_missing_of_the_kind_it_shows(ctx: Context) -> None:
    respx.get(f"{API}/titles").mock(return_value=page([
        title("movie", 1, "wanted", seq=1, name="Old"), title("movie", 2, "wanted", seq=5, name="New"), title("album", 3, "wanted"),
    ], after=3))
    route = respx.post(f"{API}/titles/why").mock(return_value=httpx.Response(200, json={"items": [
        {"why": {"versions": [{"because": {"code": "no_fitting_release", "params": {"releases": 12}}}]}},
        {"why": {"versions": [{"because": {"code": "not_released", "params": {"date": "2026-10-01"}}}]}},
    ]}))
    data = await NEXCRATE.fetch("why", CONFIG, {"kind": "movie"}, ctx)
    assert json.loads(route.calls[0].request.content) == {"items": [{"kind": "movie", "ref": 2}, {"kind": "movie", "ref": 1}]}
    assert data.secondary == [{"label": "Wanted", "value": 2}], "the album is not counted on a card of films"
    assert data.items[0]["subtitle"] == "Only releases the profile refuses" and data.items[0]["value"] == "12 found"
    assert data.items[0]["status"] == "warn" and data.items[1]["status"] == "ok"


@respx.mock
async def test_findings_are_built_from_the_code_and_marked_as_wording(ctx: Context) -> None:
    respx.get(f"{API}/health").mock(return_value=httpx.Response(200, json={"items": [
        {"code": "automatic_off", "level": "warning", "params": {"kind": "album"}, "message": "Automatic search for music is off."},
        {"code": "indexer_failing", "level": "error", "params": {"name": "Indexer A", "error": "timeout"}, "message": "Indexer A fails."},
        {"code": "something_new", "level": "notice", "params": {}, "message": "A thing nexdeck does not know yet."},
    ]}))
    data = await NEXCRATE.fetch("findings", CONFIG, {}, ctx)
    first, second, third = data.items
    assert (first["title"], first["worded"]) == ("The automatic search for music is off", True)
    assert (second["title"], second["subtitle"], second["status"]) == ("An indexer fails", "Indexer A: timeout", "bad")
    assert (third["title"], third["worded"]) == ("A thing nexdeck does not know yet.", False), "nexcrate's own sentence is shown, not translated"
    assert data.status == "bad"


@respx.mock
async def test_storage_names_the_kinds_on_a_volume_in_words_that_translate(ctx: Context) -> None:
    tera = 1024 ** 4
    respx.get(f"{API}/storage").mock(return_value=httpx.Response(200, json={"items": [
        {"volume": "/data", "kind": "movie", "total_bytes": 10 * tera, "free_bytes": 5 * tera},
        {"volume": "/data", "kind": "series", "total_bytes": 10 * tera, "free_bytes": 5 * tera},
        {"volume": "/music", "kind": "album", "total_bytes": 10 * tera, "free_bytes": 0.5 * tera},
    ]}))
    data = await NEXCRATE.fetch("storage", CONFIG, {}, ctx)
    films, music = data.items
    assert films["title"] == "Films · Series" and films["worded"] is True
    assert films["value"] == 50.0 and films["unit"] == "%" and films["subtitle"].endswith(" free of 10.0 TB")
    assert music["status"] == "warn" and data.status == "warn"


@respx.mock
async def test_a_stuck_download_carries_the_buttons_nexcrate_offers_and_what_needs_the_owner_comes_first(ctx: Context) -> None:
    respx.get(f"{API}/problems").mock(return_value=httpx.Response(200, json={"items": [
        {"download_id": "a", "title": {"name": "Quiet"}, "problem": {"message": "No progress.", "actions": ["retry", "unknown"]}},
        {"download_id": "b", "title": {"name": "Loud"}, "problem": {"message": "Which episode?", "needs_owner": True, "actions": ["remove"]}},
    ]}))
    data = await NEXCRATE.fetch("problems", CONFIG, {}, ctx)
    assert [row["title"] for row in data.items] == ["Loud", "Quiet"]
    assert [a.id for a in data.items[1]["actions"]] == ["retry"], "a button nexdeck does not know is left out"
    assert data.items[0]["actions"][0].params == {"download_id": "b"}
    assert data.status == "bad"


@respx.mock
async def test_remove_asks_nexcrate_to_search_again(ctx: Context) -> None:
    route = respx.post(f"{API}/downloads/b/remove").mock(return_value=httpx.Response(200, json={}))
    said = await NEXCRATE.action("problems", "remove", {"download_id": "b"}, CONFIG, {}, ctx)
    assert json.loads(route.calls[0].request.content) == {"search_again": True}
    assert said.startswith("Removed")
    with pytest.raises(AdapterError):
        await NEXCRATE.action("problems", "retry", {}, CONFIG, {}, ctx)


# -- refusals ---------------------------------------------------------------------


@respx.mock
async def test_a_revoked_key_and_a_missing_scope_say_what_to_do(ctx: Context) -> None:
    respx.get(f"{API}/storage").mock(return_value=httpx.Response(401, json={"code": "api_key_invalid"}))
    with pytest.raises(AuthFailed, match="Pair the connection again"):
        await NEXCRATE.fetch("storage", CONFIG, {}, ctx)
    respx.post(f"{API}/downloads/b/retry").mock(return_value=httpx.Response(403, json={"code": "scope_missing", "params": {"scope": "operate"}}))
    with pytest.raises(AdapterError) as refused:
        await NEXCRATE.action("problems", "retry", {"download_id": "b"}, CONFIG, {}, ctx)
    assert refused.value.code == "nexcrate_scope" and "operate" in refused.value.message


@respx.mock
async def test_an_address_that_is_not_nexcrate_says_so(ctx: Context) -> None:
    respx.get(f"{API}/system").mock(return_value=httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(AdapterError) as refused:
        await NEXCRATE.test(CONFIG, ctx)
    assert refused.value.code == "not_nexcrate"


# -- pairing ----------------------------------------------------------------------


@respx.mock
def test_pairing_keeps_the_secret_here_and_hands_the_key_over_once(client: TestClient) -> None:
    setup_admin(client)
    asked = respx.post(f"{API}/pairing").mock(return_value=httpx.Response(201, json={
        "pairing_id": "p1", "secret": "the-pairing-secret", "code": "K7Q-4ZP", "expires_at": "2026-09-22T12:10:00Z", "poll_seconds": 2,
    }))
    polled = respx.get(f"{API}/pairing/p1").mock(side_effect=[
        httpx.Response(200, json={"state": "pending"}),
        httpx.Response(200, json={"state": "confirmed", "key": "nxc_the-new-key", "scopes": ["read", "operate"]}),
    ])
    started = client.post("/api/v1/nexcrate/pairing", json={"url": f"{URL}/"}, headers=CSRF)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["code"] == "K7Q-4ZP" and "the-pairing-secret" not in started.text
    assert json.loads(asked.calls[0].request.content) == {"app": "nexdeck", "scopes": ["read", "operate"]}

    assert client.post(f"/api/v1/nexcrate/pairing/{body['id']}", headers=CSRF).json() == {"state": "pending"}
    assert polled.calls[0].request.headers["x-pairing-secret"] == "the-pairing-secret"
    done = client.post(f"/api/v1/nexcrate/pairing/{body['id']}", headers=CSRF).json()
    assert done["state"] == "confirmed" and done["key"] == "nxc_the-new-key"
    again = client.post(f"/api/v1/nexcrate/pairing/{body['id']}", headers=CSRF).json()
    assert again == {"state": "expired"} and polled.call_count == 2, "the key comes once; the pairing is forgotten"


@respx.mock
def test_a_denied_pairing_and_a_lost_key_end_the_pairing(client: TestClient) -> None:
    setup_admin(client)
    respx.post(f"{API}/pairing").mock(side_effect=[
        httpx.Response(201, json={"pairing_id": "p1", "secret": "s1", "code": "AAA", "poll_seconds": 2}),
        httpx.Response(201, json={"pairing_id": "p2", "secret": "s2", "code": "BBB", "poll_seconds": 2}),
    ])
    respx.get(f"{API}/pairing/p1").mock(return_value=httpx.Response(200, json={"state": "denied"}))
    respx.get(f"{API}/pairing/p2").mock(return_value=httpx.Response(200, json={"state": "delivered"}))
    one = client.post("/api/v1/nexcrate/pairing", json={"url": URL}, headers=CSRF).json()["id"]
    two = client.post("/api/v1/nexcrate/pairing", json={"url": URL}, headers=CSRF).json()["id"]
    assert client.post(f"/api/v1/nexcrate/pairing/{one}", headers=CSRF).json() == {"state": "denied"}
    assert client.post(f"/api/v1/nexcrate/pairing/{two}", headers=CSRF).json() == {"state": "expired"}


def test_pairing_is_for_administrators_and_checks_the_address(client: TestClient) -> None:
    setup_admin(client)
    barred = client.post("/api/v1/nexcrate/pairing", json={"url": "http://169.254.169.254"}, headers=CSRF)
    assert barred.status_code == 400
    assert client.post("/api/v1/nexcrate/pairing", json={"url": "nexcrate:8390"}, headers=CSRF).json()["detail"]["code"] == "bad_url"
    create_user(client, "member")
    login(client, "member", "another-long-password")
    refused = client.post("/api/v1/nexcrate/pairing", json={"url": URL}, headers=CSRF)
    assert refused.status_code == 403
