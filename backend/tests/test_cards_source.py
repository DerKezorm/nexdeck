"""Custom cards read through a connection (KARTEN-2): with its credentials, only underneath its address, only to read.

Every kind with ``raw_access`` is asked once with a recorded answer (respx) and has to send what the built-in cards of
that kind send. The list of kinds is a test of its own, so a kind cannot be switched on without a row here.
"""

from __future__ import annotations

import base64
import itertools
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters import all_adapters, get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.cards import source, store
from app.cards.schema import Request
from app.db import db_session
from app.migrations import migrate

from .cards_sample import VALUE_CARD, changed

BASE = "http://svc.example.com:8080"
OTHER = "http://other.example.com"
RECORDED = {"totalRecords": 4, "records": [{"title": "A"}]}


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


#: Per kind: the connection as saved, and the headers the built-in cards of that kind send. Written out by hand from the
#: adapters' own ``_headers`` and ``_auth``, so that a change to one of them cannot go unnoticed here.
RAW: dict[str, tuple[dict[str, Any], dict[str, str]]] = {
    "radarr": ({"url": BASE, "api_key": "k1"}, {"x-api-key": "k1"}),
    "sonarr": ({"url": BASE, "api_key": "k2"}, {"x-api-key": "k2"}),
    "lidarr": ({"url": BASE, "api_key": "k3"}, {"x-api-key": "k3"}),
    "readarr": ({"url": BASE, "api_key": "k4"}, {"x-api-key": "k4"}),
    "prowlarr": ({"url": BASE, "api_key": "k5"}, {"x-api-key": "k5"}),
    "jsonapi": ({"url": BASE, "token": "t6", "headers": "X-Extra: yes"}, {"authorization": "Bearer t6", "x-extra": "yes"}),
    "coolify": ({"url": BASE, "token": "t7"}, {"authorization": "Bearer t7"}),
    "nomad": ({"url": BASE, "token": "t8"}, {"x-nomad-token": "t8"}),
    "portainer": ({"url": BASE, "api_key": "k9"}, {"x-api-key": "k9"}),
    "proxmox": ({"url": BASE, "token_id": "root@pam!nexdeck", "token_secret": "s10"}, {"authorization": "PVEAPIToken=root@pam!nexdeck=s10"}),
    "watchtower": ({"url": BASE, "token": "t11"}, {"authorization": "Bearer t11"}),
    "audiobookshelf": ({"url": BASE, "api_key": "k12"}, {"authorization": "Bearer k12"}),
    "bazarr": ({"url": BASE, "api_key": "k13"}, {"x-api-key": "k13"}),
    "emby": ({"url": BASE, "api_key": "k14"}, {"x-emby-token": "k14"}),
    "fileflows": ({"url": BASE, "api_token": "t15"}, {"x-token": "t15"}),
    "immich": ({"url": BASE, "api_key": "k16"}, {"x-api-key": "k16"}),
    "jellyfin": ({"url": BASE, "api_key": "k17"}, {"authorization": 'MediaBrowser Token="k17", Client="nexdeck", Device="nexdeck", DeviceId="nexdeck", Version="1"'}),
    "jellyseerr": ({"url": BASE, "api_key": "k18"}, {"x-api-key": "k18"}),
    "overseerr": ({"url": BASE, "api_key": "k19"}, {"x-api-key": "k19"}),
    "seerr": ({"url": BASE, "api_key": "k20"}, {"x-api-key": "k20"}),
    "jellystat": ({"url": BASE, "api_key": "k21"}, {"x-api-token": "k21"}),
    "komga": ({"url": BASE, "api_key": "k22"}, {"x-api-key": "k22"}),
    "m3ueditor": ({"url": BASE, "api_key": "k23"}, {"authorization": "Bearer k23"}),
    "nexview": ({"url": BASE, "api_key": "k24"}, {"authorization": "Bearer k24"}),
    "nexbeat": ({"url": BASE, "api_key": "k25"}, {"authorization": "Bearer k25"}),
    "nexmail": ({"url": BASE, "api_key": "k26"}, {"authorization": "Bearer k26"}),
    "nexpulse": ({"url": BASE, "api_key": "k27"}, {"authorization": "Bearer k27"}),
    "photoprism": ({"url": BASE, "token": "t28"}, {"authorization": "Bearer t28"}),
    "plex": ({"url": BASE, "token": "t29"}, {"x-plex-token": "t29"}),
    "reclaimerr": ({"url": BASE, "api_key": "k30"}, {"authorization": "Bearer k30"}),
    "tubearchivist": ({"url": BASE, "token": "t31"}, {"authorization": "Token t31"}),
    "gotify": ({"url": BASE, "client_token": "t32"}, {"x-gotify-key": "t32"}),
    "homeassistant": ({"url": BASE, "token": "t33"}, {"authorization": "Bearer t33"}),
    "n8n": ({"url": BASE, "api_key": "k34"}, {"x-n8n-api-key": "k34"}),
    "ntfy": ({"url": BASE, "topic": "alerts", "token": "t35"}, {"authorization": "Bearer t35"}),
    "truenas": ({"url": BASE, "api_key": "k36"}, {"authorization": "Bearer k36"}),
    "gluetun": ({"url": BASE, "api_key": "k37"}, {"x-api-key": "k37"}),
    "netalertx": ({"url": BASE, "token": "t38"}, {"authorization": "Bearer t38"}),
    "speedtest": ({"url": BASE, "api_key": "k39"}, {"authorization": "Bearer k39"}),
    "nginxignition": ({"url": BASE, "token": "t40"}, {"authorization": "Bearer t40"}),
    "pfsense": ({"url": BASE, "api_key": "k41"}, {"x-api-key": "k41"}),
    "kimai": ({"url": BASE, "token": "t42"}, {"authorization": "Bearer t42"}),
    "tandoor": ({"url": BASE, "token": "t43"}, {"authorization": "Bearer t43"}),
    "adguard": ({"url": BASE, "username": "admin", "password": "pw44"}, {"authorization": basic("admin", "pw44")}),
    "mikrotik": ({"url": BASE, "username": "admin", "password": "pw45"}, {"authorization": basic("admin", "pw45")}),
    "opnsense": ({"url": BASE, "api_key": "key46", "api_secret": "secret46"}, {"authorization": basic("key46", "secret46")}),
    "traefik": ({"url": BASE, "username": "ops", "password": "pw47"}, {"authorization": basic("ops", "pw47")}),
    "peanut": ({"url": BASE, "device": "ups", "username": "ups", "password": "pw48"}, {"authorization": basic("ups", "pw48")}),
}

def ctx(client: httpx.AsyncClient | None = None) -> Context:
    return Context(client or httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def request(path: str = "/api/v3/queue", **more: Any) -> Request:
    return Request(id="queue", path=path, **more)


# -- AC-1, AC-3: the credentials of the connection ---------------------------------------


@pytest.mark.parametrize("kind", sorted(RAW))
@respx.mock
async def test_karten2_ac1_a_custom_card_asks_with_the_credentials_of_its_connection(kind: str) -> None:
    config, expected = RAW[kind]
    # Watchtower reads only its status and metrics: every other GET of its API acts (``/v1/update``).
    path = "/v1/metrics" if kind == "watchtower" else "/api/v3/queue"
    route = respx.get(f"{BASE}{path}").mock(return_value=httpx.Response(200, json=RECORDED))
    answer = await source.fetch_source(get_adapter(kind), {**config, "url": BASE + "/"}, ctx(), request(path))
    assert answer == RECORDED
    sent = route.calls.last.request
    for name, value in expected.items():
        assert sent.headers[name] == value, f"{kind}: {name}"
    assert str(sent.url) == f"{BASE}{path}"


def test_karten2_ac12_every_adapter_can_be_read_by_a_card_or_stands_in_the_list_with_its_reason() -> None:
    from app.adapters.base import NOT_READ_BY_CARDS

    everything = {one.kind for one in all_adapters()}
    readable = {one.kind for one in all_adapters() if one.raw_access}
    assert readable | set(NOT_READ_BY_CARDS) == everything
    assert not readable & set(NOT_READ_BY_CARDS)
    assert set(NOT_READ_BY_CARDS) <= everything, "a kind in the list that does not exist"
    assert all(len(reason) > 20 for reason in NOT_READ_BY_CARDS.values())
    assert len(readable) >= 150
    assert {row["kind"] for row in source.sources()} == readable
    assert all(row["label"] and row["icon"] for row in source.sources())


@pytest.mark.parametrize("kind", sorted(__import__("app.adapters.base", fromlist=["x"]).NOT_READ_BY_CARDS))
async def test_karten2_ac2_a_kind_that_is_no_web_service_says_no_raw_access(kind: str) -> None:
    adapter = get_adapter(kind)
    assert adapter.raw_access is False
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(adapter, {"url": BASE}, ctx(), request())
    assert failure.value.code == "no_raw_access"


@respx.mock
async def test_karten2_ac3_a_json_api_connection_sends_its_token_and_its_extra_headers() -> None:
    route = respx.get(f"{BASE}/status").mock(return_value=httpx.Response(200, json={"ok": True}))
    config = {"url": BASE, "token": "secret-token", "headers": "X-Api-Key: abc\nX-Tenant: one"}
    await source.fetch_source(get_adapter("jsonapi"), config, ctx(), request("/status"))
    sent = route.calls.last.request.headers
    assert (sent["authorization"], sent["x-api-key"], sent["x-tenant"]) == ("Bearer secret-token", "abc", "one")


# -- AC-4, AC-5: where and how --------------------------------------------------------------


@pytest.mark.parametrize("path", ["http://evil.example.com/x", "https://evil.example.com", "//evil.example.com/x", "\\\\evil.example.com", "/a/../b", "/%2e%2e/b", "/a/%2E./b", "api/v3/queue"])
def test_karten2_ac4_a_path_that_names_a_host_or_climbs_is_refused_on_saving(path: str) -> None:
    with pytest.raises(ValidationError):
        Request(id="queue", path=path)


@pytest.mark.parametrize("path", ["/a/..;/b", "/a/;x=1/b", "/%2f../b", "/a%2Fb", "/a%5cb", "/%252e%252e/b", "/a/%2525", "/a/%2F..%2Fb"])
def test_karten2_ac4_semicolon_encoded_slash_and_double_encoding_are_refused_as_well(path: str) -> None:
    """``..;`` and ``%2f..%2f`` become ``..`` behind Tomcat or nginx; ``%252e`` is decoded twice (found in the review, 25.10.2026)."""
    with pytest.raises(ValidationError):
        Request(id="queue", path=path)


@pytest.mark.parametrize("path", ["/api/v3/series/lookup?term=a%20b", "/api/v3/queue?page=1&sort=a;b", "/a/b.json", "/search?q=100%25"])
def test_karten2_ac4_an_ordinary_path_with_a_query_still_passes(path: str) -> None:
    assert Request(id="queue", path=path).path == path


def test_karten2_ac4_the_same_refusal_reaches_a_saved_card() -> None:
    with pytest.raises(Exception) as failure:
        from app.cards import load

        load.load_definition(changed("path: /api/v3/queue", "path: //evil.example.com/queue"))
    assert "card_bad_path" in repr(getattr(failure.value, "problems", failure.value))


@respx.mock
async def test_karten2_ac4_every_request_goes_underneath_the_address_of_the_connection() -> None:
    inside = respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={}))
    elsewhere = respx.route(host="evil.example.com").mock(return_value=httpx.Response(200, json={}))
    forged = Request.model_construct(id="queue", path="http://evil.example.com/api/v3/queue", every=None)
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), forged)
    assert failure.value.code == "bad_path"
    assert not elsewhere.called and not inside.called


@respx.mock
async def test_karten2_ac5_a_card_only_reads() -> None:
    route = respx.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request(), method="POST")
    assert failure.value.code == "read_only"
    assert not route.called
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={}))
    await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert [call.request.method for call in route.calls] == ["GET"]


# -- AC-6: no redirect ------------------------------------------------------------------------


@respx.mock
async def test_karten2_ac6_a_redirect_is_not_followed_and_the_key_stays_home() -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(302, headers={"location": f"{OTHER}/steal"}))
    stolen = respx.get(f"{OTHER}/steal").mock(return_value=httpx.Response(200, json={}))
    # A client that follows redirects, as the collector's does: only the request itself says no.
    async with httpx.AsyncClient(follow_redirects=True) as client:
        with pytest.raises(AdapterError) as failure:
            await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(client), request())
    assert failure.value.code == "redirected"
    assert "redirect" in failure.value.message
    assert not stolen.called, "the key of the connection went to another host"


@respx.mock
async def test_karten2_ac6_the_other_requests_of_the_same_client_still_follow_redirects() -> None:
    respx.get(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"location": f"{BASE}/new"}))
    respx.get(f"{BASE}/new").mock(return_value=httpx.Response(200, json={"moved": True}))
    async with httpx.AsyncClient(follow_redirects=True) as client:
        followed = await ctx(client).request("GET", f"{BASE}/old")
    assert followed.json() == {"moved": True}


@respx.mock
async def test_karten2_ac6_a_connection_typed_as_http_reads_where_its_service_raises_it_to_https() -> None:
    # UniFi on 26.10.2026: the connection said http://, the service answered 301 to the same path on https.
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(301, headers={"location": "https://svc.example.com:8443/api/v3/queue"}))
    raised = respx.get("https://svc.example.com:8443/api/v3/queue").mock(return_value=httpx.Response(200, json={"records": []}))
    answer = await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert answer == {"records": []}
    assert raised.calls.last.request.headers.get("x-api-key") == RAW["sonarr"][0]["api_key"], "the key goes along to the same host"


@respx.mock
@pytest.mark.parametrize("elsewhere", [
    "http://svc.example.com:9090/api/v3/queue",  # another port on the same scheme
    "http://svc.example.com/api/v3/queue",  # http on the default port is another port too
    "https://other.example.com/api/v3/queue",  # another host
])
async def test_karten2_ac6_a_redirect_to_another_place_is_still_refused(elsewhere: str) -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(301, headers={"location": elsewhere}))
    there = respx.get(elsewhere).mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert failure.value.code == "redirected"
    assert not there.called


@respx.mock
async def test_karten2_ac6_same_place_redirects_end_after_three() -> None:
    hops = ["/api/v3/queue", "/hop1", "/hop2", "/hop3", "/hop4", "/hop5"]
    for here, there in itertools.pairwise(hops):
        respx.get(f"{BASE}{here}").mock(return_value=httpx.Response(301, headers={"location": f"{BASE}{there}"}))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert failure.value.code == "redirected"
    assert len(respx.calls) == 1 + source.MAX_HOPS


# -- AC-7: nothing but the connection's own -------------------------------------------------


def test_karten2_ac7_a_definition_cannot_set_headers_or_credentials() -> None:
    for extra in ({"headers": {"X-Api-Key": "k"}}, {"authorization": "Bearer x"}, {"auth": ["u", "p"]}):
        with pytest.raises(ValidationError):
            Request(id="queue", path="/api/v3/queue", **extra)


@respx.mock
async def test_karten2_ac7_the_request_carries_the_headers_of_the_connection_and_no_others() -> None:
    route = respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={}))
    await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    names = {name.lower() for name in route.calls.last.request.headers}
    assert "x-api-key" in names and not names & {"authorization", "cookie", "x-forwarded-for"}


# -- AC-8: the size --------------------------------------------------------------------------


@respx.mock
async def test_karten2_ac8_an_answer_over_two_megabytes_is_refused() -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, content=b'{"x": "' + b"a" * (2 * 1024 * 1024) + b'"}'))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert failure.value.code == "answer_too_large"


@respx.mock
async def test_karten2_ac8_an_answer_just_under_two_megabytes_is_read() -> None:
    body = b'{"x": "' + b"a" * (2 * 1024 * 1024 - 20) + b'"}'
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, content=body))
    answer = await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert len(answer["x"]) > 2_000_000


# -- AC-9, AC-14: how often, how many -----------------------------------------------------


def test_karten2_ac9_a_request_every_few_seconds_is_not_saved() -> None:
    for too_often in ("5s", "9s", "0s"):
        with pytest.raises(ValidationError):
            Request(id="queue", path="/api/v3/queue", every=too_often)
    assert Request(id="queue", path="/api/v3/queue", every="10s").every == "10s"


def test_karten2_ac14_more_than_five_requests_are_not_saved() -> None:
    """The six-request card is valid in every other way (its demo data names a request that exists), so only the limit can refuse it."""
    from app.cards import load

    def with_requests(count: int) -> str:
        more = "".join(f"  - id: r{number}\n    path: /api/v3/r{number}\n" for number in range(count - 1))
        return changed("    every: 30s\n", "    every: 30s\n" + more)

    assert load.load_definition(with_requests(5)).definition.requests[-1].id == "r3"
    refused = pytest.raises(load.CardInvalid)
    with refused as caught:
        load.load_definition(with_requests(6))
    assert [(problem.code, problem.path) for problem in caught.value.problems] == [("card_too_many", "requests")]


@respx.mock
async def test_karten2_ac9_the_pace_of_a_request_is_how_long_its_answer_is_kept() -> None:
    route = respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=RECORDED))
    shared = ctx()
    for _ in range(3):
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], shared, request(every="1m"))
    assert route.call_count == 1
    assert source.cache_for(request()) == 5.0
    assert source.cache_for(request(every="1h")) == 3600.0
    assert source.cache_for(request(every="5h")) == source.MOST_SECONDS


# -- AC-11: failures are those of a built-in card ------------------------------------------


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
async def test_karten2_ac11_a_refused_key_is_an_auth_failure(status: int) -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(status))
    with pytest.raises(AuthFailed):
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())


@respx.mock
async def test_karten2_ac11_a_service_that_does_not_answer_is_unreachable() -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(side_effect=httpx.ConnectTimeout("late"))
    with pytest.raises(Unreachable):
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    respx.get(f"{BASE}/api/v3/queue").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(Unreachable):
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())


@respx.mock
async def test_karten2_ac11_an_error_page_says_the_status() -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert (failure.value.code, "404" in failure.value.message) == ("http_error", True)


# -- EC-1: places in a path ---------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize("value", ["../admin", "a/b", "7?x=1", "a b", "", "..", "%2e%2e", "a#b"])
async def test_karten2_ec1_a_value_with_a_slash_dots_or_a_question_mark_is_refused_not_asked_for(value: str) -> None:
    route = respx.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request("/api/v3/series/{id}"), values={"id": value})
    assert failure.value.code == "bad_param"
    assert not route.called


@respx.mock
async def test_karten2_ec1_a_plain_value_fills_its_place() -> None:
    route = respx.get(f"{BASE}/api/v3/series/42").mock(return_value=httpx.Response(200, json={"id": 42}))
    assert await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request("/api/v3/series/{id}"), values={"id": 42}) == {"id": 42}
    assert route.called


# -- EC-4, EC-7: what an answer may be --------------------------------------------------------


@respx.mock
@pytest.mark.parametrize("kind", ["text/plain", "text/html", "application/octet-stream", ""])
async def test_karten2_ec7_json_is_json_whatever_the_service_calls_it(kind: str) -> None:
    headers = {"content-type": kind} if kind else {}
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, content=b'{"totalRecords": 3}', headers=headers))
    assert await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request()) == {"totalRecords": 3}


@respx.mock
async def test_karten2_ec4_a_short_plain_text_is_one_value() -> None:
    respx.get(f"{BASE}/api/v3/version").mock(return_value=httpx.Response(200, text="4.0.11.2680\n", headers={"content-type": "text/plain"}))
    assert await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request("/api/v3/version")) == "4.0.11.2680"


@respx.mock
@pytest.mark.parametrize("body", [b"<html><body>Sign in</body></html>", b"x" * 2049, b"\x00\x01\x02binary", b"", b"   "])
async def test_karten2_ec4_anything_else_is_not_json(body: bytes) -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, content=body))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert failure.value.code == "not_json"


@respx.mock
async def test_karten2_ec4_json_nested_deeper_than_can_be_read_is_an_error_of_the_card_and_no_crash() -> None:
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, content=b"[" * 1_000_000 + b"]" * 1_000_000))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), request())
    assert failure.value.code == "not_json" and "nested" in failure.value.message


# -- EC-5, EC-6: what the connection says ---------------------------------------------------


async def test_karten2_ec5_a_connection_that_ignores_tls_errors_does_so_for_a_card_too(monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[str] = []

    def relaxed() -> httpx.AsyncClient:
        used.append("relaxed")
        return httpx.AsyncClient()

    monkeypatch.setattr("app.adapters.base._relaxed_client", relaxed)
    with respx.mock:
        respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={}))
        await source.fetch_source(get_adapter("sonarr"), {**RAW["sonarr"][0], "insecure": True}, ctx(), request())
        assert used == ["relaxed"]
        respx.get(f"{BASE}/api/v3/other").mock(return_value=httpx.Response(200, json={}))
        await source.fetch_source(get_adapter("sonarr"), {**RAW["sonarr"][0], "insecure": False}, ctx(), request("/api/v3/other"))
    assert used == ["relaxed"], "a connection that checks certificates must keep checking them"


def test_karten2_ec5_the_default_of_the_kind_decides_when_the_connection_says_nothing() -> None:
    # Proxmox and TrueNAS ship with "ignore TLS errors" on, Sonarr with it off; a card follows the built-in cards of its kind.
    assert get_adapter("proxmox").raw_verify({"url": BASE}) is False
    assert get_adapter("sonarr").raw_verify({"url": BASE}) is True
    assert get_adapter("proxmox").raw_verify({"url": BASE, "insecure": False}) is True


@respx.mock
@pytest.mark.parametrize("address", ["http://169.254.169.254", "http://169.254.10.1:8080", "http://metadata.google.internal"])
async def test_karten2_ec6_an_address_that_is_barred_for_the_built_in_cards_is_barred_for_a_custom_one(address: str) -> None:
    route = respx.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), {**RAW["sonarr"][0], "url": address}, ctx(), request())
    assert failure.value.code == "forbidden_host"
    assert not route.called


# -- the custom adapter: AC-9, AC-10, AC-13, EC-2, EC-3, EC-8, EC-9 --------------------------


@pytest.fixture
def db(data_dir) -> Iterator[Session]:  # noqa: ANN001
    migrate()
    with db_session() as session:
        yield session
    store.invalidate()


async def fetch_card(config: dict[str, Any], *, kind: str = "sonarr", widget: str = "value", options: dict[str, Any] | None = None) -> Any:
    """What the collector does for a custom card: its own context, and the connection resolved through it."""
    real_ctx = Context(httpx.AsyncClient(follow_redirects=True), integration_id=1, cache={})

    async def resolve(_number: int) -> tuple[Any, dict[str, Any], Context]:
        return get_adapter(kind), config, real_ctx

    own = Context(real_ctx.client, integration_id=1, widget_id=7, cache={}, resolve_integration=resolve)
    return await get_adapter("custom").fetch(widget, {}, options if options is not None else {"card": "queue-size"}, own)


@respx.mock
async def test_karten2_ac1_a_custom_card_shows_the_values_of_its_service(db: Session) -> None:
    store.create(db, VALUE_CARD)
    route = respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=RECORDED))
    data = await fetch_card(RAW["sonarr"][0])
    assert (data.primary["value"], data.meta["custom"], data.status) == (4, True, "ok")
    assert route.calls.last.request.headers["x-api-key"] == "k2"


@respx.mock
async def test_karten2_ac3_a_json_api_connection_is_a_source_of_a_card(db: Session) -> None:
    store.create(db, changed("requires: [sonarr, radarr]", "requires: [jsonapi]"))
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=RECORDED))
    data = await fetch_card({"url": BASE, "token": "t"}, kind="jsonapi")
    assert data.primary["value"] == 4


async def test_karten2_ac10_a_connection_of_a_kind_the_card_does_not_name_is_not_read(db: Session) -> None:
    store.create(db, VALUE_CARD)
    with respx.mock:
        route = respx.route().mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(AdapterError) as failure:
            await fetch_card(RAW["lidarr"][0], kind="lidarr")
    assert failure.value.code == "kind_mismatch"
    assert not route.called


async def test_karten2_ec2_a_card_without_its_definition_says_so(db: Session) -> None:
    with pytest.raises(AdapterError) as failure:
        await fetch_card(RAW["sonarr"][0], options={"card": "gone"})
    assert failure.value.code == "definition_missing"


@respx.mock
async def test_karten2_ec3_the_next_request_asks_the_new_address(db: Session) -> None:
    store.create(db, VALUE_CARD)
    old = respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json=RECORDED))
    moved = respx.get("http://new.example.com:9090/api/v3/queue").mock(return_value=httpx.Response(200, json={"totalRecords": 9}))
    assert (await fetch_card(RAW["sonarr"][0])).primary["value"] == 4
    changed_config = {**RAW["sonarr"][0], "url": "http://new.example.com:9090"}
    assert (await fetch_card(changed_config)).primary["value"] == 9
    assert (old.call_count, moved.call_count) == (1, 1)


@respx.mock
async def test_karten2_ec8_a_field_the_service_renamed_is_a_dash_not_a_failed_card(db: Session) -> None:
    store.create(db, VALUE_CARD)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(200, json={"total": 4}))
    data = await fetch_card(RAW["sonarr"][0])
    assert data.error is None and data.status == "ok"
    assert data.primary["value"] is None and data.primary["text"] == "–"


@respx.mock
async def test_karten2_ac11_a_refused_key_fails_the_custom_card_like_a_built_in_one(db: Session) -> None:
    store.create(db, VALUE_CARD)
    respx.get(f"{BASE}/api/v3/queue").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthFailed):
        await fetch_card(RAW["sonarr"][0])


def test_karten2_ac13_the_demo_shows_the_example_answers_and_asks_no_service(db: Session) -> None:
    store.create(db, VALUE_CARD)
    with respx.mock:
        route = respx.route().mock(return_value=httpx.Response(200, json={}))
        data = get_adapter("custom").demo("value", {"card": "queue-size"}, 0)
    assert data.primary["value"] == 4 and data.meta["custom"] is True
    assert not route.called


def test_karten2_ac13_a_card_without_example_answers_says_so_in_demo_mode(db: Session) -> None:
    from .cards_sample import DEMO_LINE

    store.create(db, changed(DEMO_LINE, ""))
    with pytest.raises(AdapterError) as failure:
        get_adapter("custom").demo("value", {"card": "queue-size"}, 0)
    assert failure.value.code == "no_demo_data"


@respx.mock
async def test_karten6_a_card_whose_definition_became_another_form_says_so(db: Session) -> None:
    from .test_cards_forms import LIST

    store.create(db, LIST)
    route = respx.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AdapterError) as failure:
        await fetch_card(RAW["sonarr"][0], widget="value", options={"card": "waiting"})
    assert failure.value.code == "form_changed" and not route.called


@respx.mock
async def test_karten2_a_request_with_a_space_in_its_path_is_told_to_write_it_as_percent_20() -> None:
    sent = respx.get(url__regex=rf"{BASE}/.*").mock(return_value=httpx.Response(200, json={}))
    forged = Request.model_construct(id="queue", path="/graphql?query=x y", every=None)
    with pytest.raises(AdapterError) as failure:
        await source.fetch_source(get_adapter("sonarr"), RAW["sonarr"][0], ctx(), forged)
    assert failure.value.code == "bad_path" and "%20" in (failure.value.hint or "") and not sent.called
