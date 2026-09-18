"""nexmail, against the answers its API contract for 0.17.0 describes.

⚠️ Built before nexmail 0.17.0 was released, from the contract its own session
wrote down and from the response models in its router; the fixtures under
``fixtures/nexmail_*.json`` follow those shapes. The adapter stays beta until
a card has read a real installation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, Unreachable
from app.adapters.nexmail import COUNTS_ONLY, REFUSALS

from .conftest import CSRF, setup_admin

FIXTURES = Path(__file__).parent / "fixtures"
# ⚠️ With a sub-path: nexmail may live below one behind a proxy, and every
# address has to keep it.
BASE = "https://mail.example.com/nexmail"
KEY = "nxm_made-up-key"
CONFIG = {"url": BASE + "/", "api_key": KEY}


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"nexmail_{name}.json").read_text(encoding="utf-8"))


def counts_only_me() -> dict[str, Any]:
    me = fixture("me")
    me["key"]["scope"] = "count"
    return me


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _me(answer: dict[str, Any] | None = None) -> respx.Route:
    return respx.get(f"{BASE}/api/v1/me").mock(return_value=httpx.Response(200, json=answer or fixture("me")))


def _summary(answer: dict[str, Any] | None = None) -> respx.Route:
    return respx.get(f"{BASE}/api/v1/summary").mock(return_value=httpx.Response(200, json=answer or fixture("summary")))


def _latest(answer: dict[str, Any] | None = None) -> respx.Route:
    return respx.get(f"{BASE}/api/v1/messages/latest").mock(
        return_value=httpx.Response(200, json=answer or fixture("latest")))


# -- signing in --------------------------------------------------------------


@respx.mock
async def test_the_key_travels_as_a_bearer_header_and_nowhere_else(ctx: Context) -> None:
    me = _me()
    await get_adapter("nexmail").test(CONFIG, ctx)
    request = me.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert KEY not in str(request.url), "never in the address, where proxies write it into their logs"
    assert "cookie" not in request.headers
    assert str(request.url) == f"{BASE}/api/v1/me", "the sub-path stays, the trailing slash goes"


@respx.mock
async def test_the_connection_test_says_what_the_key_may_read(ctx: Context) -> None:
    _me()
    said = await get_adapter("nexmail").test(CONFIG, ctx)
    assert "Alex Example" in said and "3 mailboxes" in said and "sender and subject" in said


@respx.mock
async def test_the_connection_test_warns_about_a_key_that_may_only_count(ctx: Context) -> None:
    """Said at setup, so the missing list card is not a riddle on the board."""
    _me(counts_only_me())
    said = await get_adapter("nexmail").test(CONFIG, ctx)
    assert "counts only" in said and "not offered" in said


@respx.mock
async def test_the_connection_test_says_when_no_mailbox_is_shared(ctx: Context) -> None:
    me = fixture("me")
    me["mailboxes"] = []
    _me(me)
    said = await get_adapter("nexmail").test(CONFIG, ctx)
    assert "no mailbox" in said


# -- unread mail -------------------------------------------------------------


@respx.mock
async def test_unread_mail_shows_the_total_over_one_row_per_mailbox(ctx: Context) -> None:
    _summary()
    data = await get_adapter("nexmail").fetch("unread", CONFIG, {}, ctx)
    assert data.primary == {"label": "Unread", "value": 17}
    assert data.meta["headline"] is True
    assert [(item["title"], item["value"]) for item in data.items] == [("Home", 4), ("Work", 11), ("Club", 2)]
    assert data.metrics == {"unread": 17.0}


@respx.mock
async def test_a_mailbox_that_cannot_sign_in_is_marked_and_turns_the_card_red(ctx: Context) -> None:
    """⚠️ Its number is from before the password stopped working. Shown like
    the others it would look like a quiet inbox."""
    _summary()
    data = await get_adapter("nexmail").fetch("unread", CONFIG, {}, ctx)
    club = data.items[2]
    assert club["status"] == "bad"
    assert club["subtitle"].startswith("Sign-in failed")
    assert [item["status"] for item in data.items[:2]] == ["ok", "ok"]
    assert data.status == "bad"
    assert "notice" in data.meta and "status_reason" in data.meta


@respx.mock
async def test_without_a_failed_mailbox_the_card_is_green_and_quiet(ctx: Context) -> None:
    summary = fixture("summary")
    summary["mailboxes"][2]["status"] = "ok"
    _summary(summary)
    data = await get_adapter("nexmail").fetch("unread", CONFIG, {}, ctx)
    assert data.status == "ok"
    assert "notice" not in data.meta
    assert data.items[2]["subtitle"] == "club@example.com"


@respx.mock
async def test_picked_mailboxes_are_the_rows_and_the_total(ctx: Context) -> None:
    """The headline has to agree with the rows under it."""
    _summary()
    data = await get_adapter("nexmail").fetch("unread", CONFIG, {"mailboxes": ["mb-home", "mb-club"]}, ctx)
    assert [item["title"] for item in data.items] == ["Home", "Club"]
    assert data.primary["value"] == 6


@respx.mock
async def test_a_pick_that_is_no_longer_shared_says_so(ctx: Context) -> None:
    _summary()
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexmail").fetch("unread", CONFIG, {"mailboxes": ["mb-gone"]}, ctx)
    assert refused.value.code == "nexmail_mailbox_unknown"


# -- latest mail -------------------------------------------------------------


@respx.mock
async def test_latest_mail_shows_sender_and_subject_and_links_to_the_message(ctx: Context) -> None:
    _me()
    latest = _latest()
    data = await get_adapter("nexmail").fetch("latest", CONFIG, {"limit": 5}, ctx)
    first, second, third = data.items
    assert first["title"] == "Build server"
    assert second["title"] == "parcel@example.com", "no name, so the address"
    assert first["subtitle"] == "Nightly build passed · Work", "several mailboxes, so each row names its own"
    assert third["subtitle"] == "(no subject) · Work"
    assert [item["emphasis"] for item in data.items] == [True, True, False]
    assert first["url"] == f"{BASE}/?nachricht=901"
    assert first["value"].endswith(("min", "h", "d"))
    assert second["value"], "a time without a zone is read as UTC, not dropped"
    request = latest.calls.last.request
    assert request.url.params.get_list("mailbox") == [], "nothing picked asks for every shared mailbox"
    assert request.url.params["limit"] == "5"
    assert request.url.params["unread_only"] == "false"
    assert request.headers["Authorization"] == f"Bearer {KEY}"


@respx.mock
async def test_latest_mail_asks_for_the_picked_mailboxes_the_number_and_only_unread(ctx: Context) -> None:
    _me()
    latest = _latest({"messages": fixture("latest")["messages"][:1]})
    data = await get_adapter("nexmail").fetch(
        "latest", CONFIG, {"mailboxes": ["mb-work"], "limit": 3, "unread_only": True}, ctx)
    params = latest.calls.last.request.url.params
    assert params.get_list("mailbox") == ["mb-work"]
    assert params["limit"] == "3"
    assert params["unread_only"] == "true"
    assert data.items[0]["subtitle"] == "Nightly build passed", "one mailbox: its name on every row says nothing"
    assert data.meta["empty"] == "No unread mail."


@pytest.mark.parametrize(("asked", "sent"), [(50, "20"), (-3, "1"), ("many", "5"), (None, "5")])
@respx.mock
async def test_the_number_of_messages_stays_inside_what_nexmail_accepts(ctx: Context, asked: Any, sent: str) -> None:
    """nexmail answers 422 outside 1..20; the card never asks for that."""
    _me()
    latest = _latest()
    await get_adapter("nexmail").fetch("latest", CONFIG, {"limit": asked}, ctx)
    assert latest.calls.last.request.url.params["limit"] == sent


@respx.mock
async def test_a_mailbox_taken_off_the_key_is_left_out_before_asking(ctx: Context) -> None:
    """⚠️ Otherwise one stale pick turns the whole card into nexmail's 404."""
    _me()
    latest = _latest()
    await get_adapter("nexmail").fetch("latest", CONFIG, {"mailboxes": ["mb-gone", "mb-home"]}, ctx)
    assert latest.calls.last.request.url.params.get_list("mailbox") == ["mb-home"]


@respx.mock
async def test_only_stale_picks_say_so_instead_of_showing_everything(ctx: Context) -> None:
    _me()
    latest = _latest()
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexmail").fetch("latest", CONFIG, {"mailboxes": ["mb-gone"]}, ctx)
    assert refused.value.code == "nexmail_mailbox_unknown"
    assert not latest.called, "an empty pick must not become every mailbox"


@respx.mock
async def test_a_key_that_may_only_count_gets_a_hint_and_asks_nothing(ctx: Context) -> None:
    """⚠️ A hint, not an error: the key does what its owner chose."""
    _me(counts_only_me())
    latest = _latest()
    data = await get_adapter("nexmail").fetch("latest", CONFIG, {}, ctx)
    assert data.error is None
    assert data.items == []
    assert data.meta["notice"] == COUNTS_ONLY
    assert not latest.called


# -- the library asks first --------------------------------------------------


@respx.mock
async def test_the_list_card_is_barred_for_a_key_that_may_only_count(ctx: Context) -> None:
    _me(counts_only_me())
    adapter = get_adapter("nexmail")
    assert adapter.bars_widgets is True
    assert await adapter.barred("latest", CONFIG, ctx) == COUNTS_ONLY
    assert await adapter.barred("unread", CONFIG, ctx) == "", "counting is what such a key is for"


@respx.mock
async def test_the_list_card_is_not_barred_for_a_key_that_may_read_headers(ctx: Context) -> None:
    _me()
    assert await get_adapter("nexmail").barred("latest", CONFIG, ctx) == ""


@respx.mock
async def test_the_mailbox_list_comes_from_the_key(ctx: Context) -> None:
    _me()
    offered = await get_adapter("nexmail").choices("mailboxes", CONFIG, ctx)
    assert offered == [("mb-home", "Home"), ("mb-work", "Work"), ("mb-club", "Club")]


# -- refusals ----------------------------------------------------------------


@pytest.mark.parametrize(("status", "detail", "code"), [
    (401, "api_schluessel_fehlt", "nexmail_key_missing"),
    (401, "api_schluessel_ungueltig", "nexmail_key_invalid"),
    (403, "api_schluessel_abgeschaltet", "nexmail_keys_off"),
    (403, "api_schluessel_nur_anzahl", "nexmail_counts_only"),
    (404, "postfach_unbekannt", "nexmail_mailbox_unknown"),
])
@respx.mock
async def test_every_refusal_reads_as_what_to_do(ctx: Context, status: int, detail: str, code: str) -> None:
    """Not "the credentials were rejected": two of these are fixed somewhere
    else entirely, by the operator of nexmail or by editing the key."""
    _me()
    respx.get(f"{BASE}/api/v1/messages/latest").mock(return_value=httpx.Response(status, json={"detail": detail}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexmail").fetch("latest", CONFIG, {}, ctx)
    assert refused.value.code == code
    assert refused.value.message == REFUSALS[detail][0]


@pytest.mark.parametrize("detail", ["api_schluessel_fehlt", "api_schluessel_ungueltig", "api_schluessel_abgeschaltet"])
@respx.mock
async def test_the_connection_test_carries_the_same_sentences(ctx: Context, detail: str) -> None:
    respx.get(f"{BASE}/api/v1/me").mock(
        return_value=httpx.Response(403 if detail.endswith("abgeschaltet") else 401, json={"detail": detail}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexmail").test(CONFIG, ctx)
    assert refused.value.message == REFUSALS[detail][0]


def test_every_refusal_says_where_to_go() -> None:
    """Each sentence names nexmail or this connection, so it says where to act."""
    for message, code in REFUSALS.values():
        assert code.startswith("nexmail_")
        assert "nexmail" in message
    assert "Settings → API keys" in REFUSALS["api_schluessel_abgeschaltet"][0]
    assert "Count, sender and subject" in REFUSALS["api_schluessel_nur_anzahl"][0]


@respx.mock
async def test_a_number_out_of_range_is_named(ctx: Context) -> None:
    _me()
    respx.get(f"{BASE}/api/v1/messages/latest").mock(return_value=httpx.Response(422, json={"detail": [{"loc": ["query", "limit"]}]}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexmail").fetch("latest", CONFIG, {}, ctx)
    assert refused.value.code == "nexmail_bad_limit"


@respx.mock
async def test_an_address_without_the_api_says_to_check_the_url(ctx: Context) -> None:
    """An older nexmail, or a sub-path left out, answers 404 without an identifier."""
    respx.get(f"{BASE}/api/v1/summary").mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexmail").fetch("unread", CONFIG, {}, ctx)
    assert refused.value.code == "http_error"
    assert "0.17.0" in refused.value.message


@respx.mock
async def test_a_login_page_is_not_data(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/summary").mock(return_value=httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexmail").fetch("unread", CONFIG, {}, ctx)
    assert refused.value.code == "not_json"


@respx.mock
async def test_an_unreachable_nexmail_says_so(ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/summary").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("nexmail").fetch("unread", CONFIG, {}, ctx)


# -- demo --------------------------------------------------------------------


def test_the_demo_fills_both_cards_and_follows_the_options() -> None:
    adapter = get_adapter("nexmail")
    unread = adapter.demo("unread", {}, 0)
    assert unread.primary["value"] == sum(item["value"] for item in unread.items)
    latest = adapter.demo("latest", {"limit": 2, "unread_only": True}, 0)
    assert len(latest.items) == 2 and all(item["emphasis"] for item in latest.items)
    picked = adapter.demo("latest", {"mailboxes": ["2"]}, 0)
    assert picked.items and all(" · " not in item["subtitle"] for item in picked.items)
    assert [value for value, _label in adapter.demo_choices("mailboxes")] == ["1", "2", "3"]


# -- the question the library asks -------------------------------------------


def _nexmail(client: TestClient) -> int:
    made = client.post("/api/v1/integrations", json={
        "kind": "nexmail", "name": "nexmail", "config": {"url": BASE, "api_key": KEY},
    }, headers=CSRF)
    assert made.status_code == 201, made.text
    return made.json()["id"]


def test_the_library_hears_why_a_card_is_barred(client: TestClient) -> None:
    setup_admin(client)
    integration = _nexmail(client)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/v1/me").mock(return_value=httpx.Response(200, json=counts_only_me()))
        mock.route(host="testserver").pass_through()
        barred = client.get(f"/api/v1/integrations/{integration}/barred/latest")
        allowed = client.get(f"/api/v1/integrations/{integration}/barred/unread")
    assert barred.status_code == 200 and barred.json() == {"reason": COUNTS_ONLY}
    assert allowed.json() == {"reason": ""}


def test_a_nexmail_that_cannot_be_asked_bars_nothing(client: TestClient) -> None:
    """The card says for itself what is wrong; the library does not refuse
    because of a network hiccup."""
    setup_admin(client)
    integration = _nexmail(client)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/api/v1/me").mock(side_effect=httpx.ConnectError("refused"))
        mock.route(host="testserver").pass_through()
        answer = client.get(f"/api/v1/integrations/{integration}/barred/latest")
    assert answer.json() == {"reason": ""}


def test_asking_about_a_card_the_connection_does_not_have_is_refused(client: TestClient) -> None:
    setup_admin(client)
    integration = _nexmail(client)
    assert client.get(f"/api/v1/integrations/{integration}/barred/nonsense").status_code == 400
