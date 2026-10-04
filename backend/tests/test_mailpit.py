"""Mailpit 1.31.4, measured on 04.10.2026 on docker-dev with three made-up mails: the shapes are the measured
ones, the senders made up."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

URL = "http://mailpit.example.com:8025"
API = f"{URL}/api/v1"
CONFIG = {"url": URL}
INFO = {
    "Version": "v1.31.4", "LatestVersion": "v1.31.4", "Database": "/tmp/mailpit-1791134080632968011.db",
    "DatabaseSize": 94208, "Messages": 3, "Unread": 2, "Tags": {},
    "RuntimeStats": {"Uptime": 41, "Memory": 9820424, "MessagesDeleted": 0, "SMTPAccepted": 3,
                     "SMTPAcceptedSize": 2051, "SMTPRejected": 1, "SMTPIgnored": 0},
}
WEBUI = {"Label": "", "MessageRelay": {"Enabled": False, "SMTPServer": "", "ReturnPath": "", "AllowedRecipients": "",
                                       "BlockedRecipients": "", "OverrideFrom": "", "PreserveMessageIDs": False,
                                       "RecipientAllowlist": ""},
         "SpamAssassin": False, "ChaosEnabled": False, "DuplicatesIgnored": False, "HideDeleteAllButton": False}


def mail(id_: str, name: str, address: str, subject: str, read: bool, minutes: int) -> dict:
    created = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"ID": id_, "MessageID": f"{id_}@mailpit", "Read": read, "From": {"Name": name, "Address": address},
            "To": [{"Name": "", "Address": "ops@example.com"}], "Cc": None, "Bcc": None, "ReplyTo": [],
            "Subject": subject, "Created": created, "Username": "", "Tags": [], "Size": 840, "Attachments": 0,
            "Snippet": "Made up."}


def messages() -> dict:
    """Made anew in every test: the ages are counted from now, and a full run takes half an hour."""
    return {
        "total": 3, "unread": 2, "count": 3, "messages_count": 3, "messages_unread": 2, "start": 0, "tags": [],
        "messages": [
            mail("4GszTwyHRXD934TADwK86w", "Sonarr", "sonarr@example.com", "Episode imported: Example Show S01E02", False, 2),
            mail("5wo4qi3zSdpG6I9XTgqMHn", "", "alerts@example.com", "[FIRING:1] Disk almost full", True, 3),
            mail("6xp5rj4aTeYH7J0UEhrNIo", "Backup Robot", "backup@example.com", "", False, 90),
        ],
    }


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_the_overview_counts_and_says_nothing_while_all_is_well(ctx: Context) -> None:
    respx.get(f"{API}/info").mock(return_value=httpx.Response(200, json=INFO))
    respx.get(f"{API}/webui").mock(return_value=httpx.Response(200, json=WEBUI))
    data = await get_adapter("mailpit").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Unread", "value": 2}
    assert {row["label"]: row["value"] for row in data.secondary} == {
        "All mail": 3, "Accepted": 3, "Rejected": 1, "Database": "92.0 KB"}
    assert data.status == "ok" and data.meta["status_reason"] == "" and data.metrics == {"unread": 2.0}


@respx.mock
async def test_chaos_turns_the_overview_amber_and_a_new_version_is_named(ctx: Context) -> None:
    respx.get(f"{API}/info").mock(return_value=httpx.Response(200, json={**INFO, "LatestVersion": "v1.32.0"}))
    respx.get(f"{API}/webui").mock(return_value=httpx.Response(200, json={**WEBUI, "ChaosEnabled": True}))
    data = await get_adapter("mailpit").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "warn"
    assert "Chaos is on" in data.meta["status_reason"] and "v1.32.0 is out; this one is v1.31.4" in data.meta["status_reason"]


@respx.mock
async def test_the_latest_mail_names_the_sender_and_opens_in_mailpit(ctx: Context) -> None:
    route = respx.get(f"{API}/messages").mock(return_value=httpx.Response(200, json=messages()))
    data = await get_adapter("mailpit").fetch("latest", CONFIG, {"limit": 2}, ctx)
    assert route.calls.last.request.url.params["limit"] == "2"
    assert [(row["title"], row["subtitle"], row["emphasis"]) for row in data.items] == [
        ("Sonarr", "Episode imported: Example Show S01E02", True),
        ("alerts@example.com", "[FIRING:1] Disk almost full", False),
    ]
    assert data.items[0]["url"] == f"{URL}/view/4GszTwyHRXD934TADwK86w"
    assert data.items[0]["value"] == "2 min"


@respx.mock
async def test_a_mail_without_a_subject_says_so(ctx: Context) -> None:
    respx.get(f"{API}/messages").mock(return_value=httpx.Response(200, json=messages()))
    data = await get_adapter("mailpit").fetch("latest", CONFIG, {}, ctx)
    assert data.items[-1]["subtitle"] == "(no subject)"


@respx.mock
async def test_only_unread_and_a_search_go_to_mailpits_own_search(ctx: Context) -> None:
    listing = respx.get(f"{API}/messages").mock(return_value=httpx.Response(200, json=messages()))
    search = respx.get(f"{API}/search").mock(return_value=httpx.Response(200, json={**messages(), "messages": []}))
    data = await get_adapter("mailpit").fetch("latest", CONFIG, {"unread_only": True, "query": "to:ops@example.com"}, ctx)
    assert not listing.called
    assert search.calls.last.request.url.params["query"] == "to:ops@example.com is:unread"
    assert data.items == [] and data.meta["empty"] == "No mail matches the search."


@respx.mock
async def test_a_login_goes_along_as_basic_and_a_refusal_is_told_apart(ctx: Context) -> None:
    route = respx.get(f"{API}/info").mock(return_value=httpx.Response(200, json=INFO))
    await get_adapter("mailpit").test({**CONFIG, "username": "probe", "password": "made-up-pass"}, ctx)
    assert route.calls.last.request.headers["Authorization"] == "Basic " + base64.b64encode(b"probe:made-up-pass").decode()

    refused = httpx.Response(401, text="Unauthorized.\n", headers={"WWW-Authenticate": 'Basic realm="Login"'})
    respx.get(f"{API}/info").mock(return_value=refused)
    with pytest.raises(AuthFailed, match="asks for a login"):
        await get_adapter("mailpit").test(CONFIG, ctx)
    with pytest.raises(AuthFailed, match="rejected the user or the password"):
        await get_adapter("mailpit").test({**CONFIG, "username": "probe", "password": "wrong"}, ctx)


@respx.mock
async def test_without_its_webroot_the_address_finds_no_api(ctx: Context) -> None:
    respx.get(f"{API}/info").mock(return_value=httpx.Response(404, text="404 page not found\n"))
    with pytest.raises(AdapterError) as caught:
        await get_adapter("mailpit").test(CONFIG, ctx)
    assert "webroot" in (caught.value.hint or "")


@respx.mock
async def test_a_webroot_in_the_url_moves_the_api_with_it(ctx: Context) -> None:
    route = respx.get(f"{URL}/mail/api/v1/info").mock(return_value=httpx.Response(200, json=INFO))
    said = await get_adapter("mailpit").test({"url": f"{URL}/mail/"}, ctx)
    assert route.called and said == "Mailpit v1.31.4 answers with 3 message(s), 2 unread."


def test_the_demo_fills_both_cards() -> None:
    adapter = get_adapter("mailpit")
    assert adapter.demo("overview", {}, 1).primary["label"] == "Unread"
    unread = adapter.demo("latest", {"unread_only": True}, 1).items
    assert unread and all(row["emphasis"] for row in unread)
