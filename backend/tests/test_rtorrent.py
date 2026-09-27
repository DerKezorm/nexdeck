"""rTorrent, against the answers of a live rTorrent 0.16.22 with ruTorrent 5.3.14 (27.09.2026).

crazymax/rtorrent-rutorrent, reached over its XML-RPC port and through
ruTorrent's httprpc plugin. The rows are the measured ones, field for field:
a Debian image downloading, a torrent whose tracker does not exist and then
paused, a seeding one without a tracker, a finished one that was stopped and
checked, a damaged one checked again, and one caught in its hash check. The
names are invented, and so are the hashes, which are words and not hex.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable

RT = "http://rtorrent.example.com:8000"
RU = "http://rutorrent.example.com:8080"
CONFIG = {"url": RT, "username": "watcher", "password": "rt-test-password-for-the-cards"}
ADAPTER = get_adapter("rtorrent")

FIELDS = ("hash", "name", "state", "is_active", "is_open", "complete", "is_hash_checking", "hashing", "message", "size_bytes",
          "completed_bytes", "left_bytes", "down_rate", "up_rate", "size_chunks", "chunks_hashed")


def row(**values: Any) -> list[Any]:
    base = {"hash": "", "name": "", "state": 0, "is_active": 0, "is_open": 0, "complete": 0, "is_hash_checking": 0, "hashing": 0,
            "message": "", "size_bytes": 0, "completed_bytes": 0, "left_bytes": 0, "down_rate": 0, "up_rate": 0, "size_chunks": 0,
            "chunks_hashed": 0}
    base.update(values)
    return [base[name] for name in FIELDS]


DOWNLOADING = row(hash="HASH-OF-THE-DISTRIBUTION-IMAGE-FOR-TESTS", name="distro-13.7.0-amd64-netinst.iso", state=1, is_active=1, is_open=1,
                  size_bytes=792723456, completed_bytes=20447232, left_bytes=772276224, down_rate=208309, up_rate=423,
                  size_chunks=3024, chunks_hashed=3024)
#: ⚠️ A tracker that does not exist is not an error: the torrent was paused with d.pause.
PAUSED = row(hash="HASH-OF-A-TORRENT-WITH-A-DEAD-TRACKER-XX", name="sample-deadtracker.bin", state=1, is_active=0, is_open=1,
             message="Tracker: [v6 : Could not resolve hostname  |  v4 : Could not resolve hostname]",
             size_bytes=2097152, left_bytes=2097152, size_chunks=128)
#: ⚠️ Healthy, and still with a message.
SEEDING = row(hash="HASH-OF-A-SEEDING-TORRENT-WITHOUT-TRACKER", name="sample-seeding.bin", state=1, is_active=1, is_open=1, complete=1,
              message="Tracker: [No DHT nodes available for peer search.]", size_bytes=3145728, completed_bytes=3145728,
              up_rate=51200, size_chunks=192, chunks_hashed=192)
#: ⚠️ Stopped, then checked: open again, not started.
FINISHED = row(hash="HASH-OF-A-FINISHED-AND-STOPPED-TORRENT-XX", name="sample-finished.bin", is_open=1, complete=1,
               size_bytes=4194304, completed_bytes=4194304, size_chunks=256, chunks_hashed=256)
DAMAGED = row(hash="HASH-OF-A-TORRENT-DAMAGED-ON-THE-DISK-XXX", name="sample-damaged.bin", is_open=1,
              message="Download registered as completed, but hash check returned unfinished chunks.",
              size_bytes=3145728, completed_bytes=1048576, left_bytes=2097152, size_chunks=192, chunks_hashed=192)
#: ⚠️ In its check: not active, still complete, and the progress is the chunks hashed.
CHECKING = row(hash="HASH-OF-A-TORRENT-IN-ITS-HASH-CHECK-XXXXX", name="sample-bigcheck.bin", state=1, is_active=0, is_open=1, complete=1,
               is_hash_checking=1, hashing=3, size_bytes=419430400, completed_bytes=0, size_chunks=25600, chunks_hashed=8193)
ALL = [DOWNLOADING, PAUSED, SEEDING, FINISHED, DAMAGED, CHECKING]

#: One answer as rTorrent writes it, with its <i8>, to be sure those are read.
RAW_VERSION = '<?xml version="1.0"?><methodResponse><params><param><value><string>0.16.22</string></value></param></params></methodResponse>'
RAW_RATES = ('<?xml version="1.0"?><methodResponse><params><param><value><array><data><value><array><data><value><i8>208220</i8>'
             '</value></data></array></value><value><array><data><value><i8>385</i8></value></data></array></value></data></array>'
             '</value></param></params></methodResponse>')
UNKNOWN = ('<?xml version="1.0"?><methodResponse><fault><value><struct><member><name>faultCode</name><value><i8>-506</i8></value>'
           '</member><member><name>faultString</name><value><string>method \'no.such.method\' not defined</string></value></member>'
           '</struct></value></fault></methodResponse>')
REJECTED = ('<?xml version="1.0" encoding="UTF-8"?>\n<methodResponse><fault><value><struct><member><name>faultCode</name><value><i4>-501</i4>'
            '</value></member><member><name>faultString</name><value><string>The command \'execute.throw\' was rejected by this server.'
            '</string></value></member></struct></value></fault></methodResponse>')
NGINX_401 = "<html>\r\n<head><title>401 Authorization Required</title></head>\r\n<body>\r\n</body>\r\n</html>\r\n"
NGINX_404 = "<html>\r\n<head><title>404 Not Found</title></head>\r\n<body>\r\n</body>\r\n</html>\r\n"


def answer_xml(value: Any) -> httpx.Response:
    return httpx.Response(200, text=xmlrpc.client.dumps((value,), methodresponse=True), headers={"Content-Type": "text/xml"})


def server(url: str, rows: list[list[Any]] | None = None) -> list[tuple[str, str, tuple[Any, ...]]]:
    """A fake rTorrent at ``url``: answers the calls the cards make and notes each one with the path it came to."""
    calls: list[tuple[str, str, tuple[Any, ...]]] = []
    kept = ALL if rows is None else rows

    def answer(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != httpx.BasicAuth(CONFIG["username"], CONFIG["password"])._auth_header:
            return httpx.Response(401, text=NGINX_401, headers={"Content-Type": "text/html"})
        params, method = xmlrpc.client.loads(request.content)
        calls.append((request.url.path, method or "", params))
        if method == "system.client_version":
            return httpx.Response(200, text=RAW_VERSION, headers={"Content-Type": "text/xml"})
        if method == "d.multicall2":
            assert params[:2] == ("", "main") and len(params) == 2 + len(FIELDS)
            return answer_xml(kept)
        if method == "system.multicall":
            return httpx.Response(200, text=RAW_RATES, headers={"Content-Type": "text/xml"})
        if method in ("d.stop", "d.start"):
            return answer_xml(0)
        return httpx.Response(200, text=UNKNOWN, headers={"Content-Type": "text/xml"})

    respx.post(url__startswith=url).mock(side_effect=answer)
    return calls


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@respx.mock
async def test_straight_to_the_xml_rpc_port(ctx: Context) -> None:
    calls = server(RT)
    assert await ADAPTER.test(CONFIG, ctx) == "rTorrent 0.16.22 answers with 6 torrents."
    assert [(path, method) for path, method, _ in calls] == [("/RPC2", "system.client_version"), ("/RPC2", "d.multicall2")]
    assert ctx.cache["rtorrent_endpoint"] == (RT, f"{RT}/RPC2")


@respx.mock
async def test_through_rutorrent_when_there_is_no_rpc2(ctx: Context) -> None:
    # ⚠️ ruTorrent answers /RPC2 with 404 and takes the same XML-RPC on its plugin.
    respx.post(f"{RU}/RPC2").mock(return_value=httpx.Response(404, text=NGINX_404, headers={"Content-Type": "text/html"}))
    calls = server(f"{RU}/plugins/httprpc/action.php")
    config = {**CONFIG, "url": RU}
    await ADAPTER.test(config, ctx)
    card = await ADAPTER.fetch("overview", config, {}, ctx)
    assert card.primary == {"label": "Torrents", "value": 6}
    assert {path for path, _method, _params in calls} == {"/plugins/httprpc/action.php"}
    assert respx.calls.call_count == len(calls) + 1, "the 404 on /RPC2 is asked once and then remembered"


@respx.mock
async def test_an_address_with_its_path_is_taken_as_it_is(ctx: Context) -> None:
    calls = server(RU)
    await ADAPTER.test({**CONFIG, "url": f"{RU}/rutorrent/plugins/httprpc/action.php"}, ctx)
    assert {path for path, _method, _params in calls} == {"/rutorrent/plugins/httprpc/action.php"}


@respx.mock
async def test_every_state_in_one_word(ctx: Context) -> None:
    server(RT)
    card = await ADAPTER.fetch("torrents", CONFIG, {"limit": 10}, ctx)
    assert [(item["title"], item["subtitle"], item["value"], item["status"]) for item in card.items] == [
        ("sample-damaged.bin", "3.0 MB · error · Download registered as completed, but hash check returned unfinished chunks.", "33%", "bad"),
        ("distro-13.7.0-amd64-netinst.iso", "756.0 MB · downloading · ↓ 203.4 KB/s · ↑ 423 B/s", "3%", "ok"),
        ("sample-bigcheck.bin", "400.0 MB · checking", "32%", "ok"),
        ("sample-deadtracker.bin", "2.0 MB · paused", "0%", "warn"),
        ("sample-seeding.bin", "3.0 MB · seeding · ↑ 50.0 KB/s", "100%", "ok"),
        ("sample-finished.bin", "4.0 MB · finished", "100%", "ok"),
    ]
    assert card.items[2]["progress"] == 32.0, "8193 of 25600 chunks hashed, while completed_chunks reads 0"
    assert card.status == "bad"
    shorter = await ADAPTER.fetch("torrents", CONFIG, {"limit": 2}, ctx)
    assert len(shorter.items) == 2


@respx.mock
async def test_the_overview_counts_each_state_and_the_speeds(ctx: Context) -> None:
    server(RT)
    card = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert {row["part"]: row["value"] for row in card.secondary} == {
        "download": "203.3 KB/s", "upload": "385 B/s", "downloading": 1, "seeding": 1, "paused": 1, "finished": 1, "error": 1, "checking": 1}
    assert card.status == "bad"
    # Bytes per second from rTorrent, megabytes per second in the history like every download card.
    assert card.metrics == {"download": 0.2, "upload": 0.0}


@respx.mock
async def test_the_queue_is_what_is_not_done_yet(ctx: Context) -> None:
    server(RT)
    card = await ADAPTER.fetch("queue", CONFIG, {}, ctx)
    assert [(item["title"], item["subtitle"], item["status"]) for item in card.items] == [
        ("sample-damaged.bin", "3.0 MB · error", "bad"),
        ("distro-13.7.0-amd64-netinst.iso", "756.0 MB · 1h 1m left", "ok"),
        ("sample-deadtracker.bin", "2.0 MB · paused", "warn"),
    ]
    # The one in its check is complete and stays out, like the seeding and the finished one.
    assert [action.id for action in card.actions] == ["pause"]
    speed = await ADAPTER.fetch("speed", CONFIG, {}, ctx)
    assert speed.primary == {"label": "Download", "value": 0.2, "unit": "MB/s"}
    assert {"label": "Left", "value": "740.5 MB"} in speed.secondary


@respx.mock
async def test_all_paused_offers_resume(ctx: Context) -> None:
    server(RT, rows=[PAUSED, FINISHED])
    card = await ADAPTER.fetch("queue", CONFIG, {}, ctx)
    assert card.status == "warn" and [action.id for action in card.actions] == ["resume"]


@respx.mock
async def test_pause_stops_each_download_on_its_own(ctx: Context) -> None:
    calls = server(RT)
    assert await ADAPTER.action("queue", "pause", {}, CONFIG, {}, ctx) == "Downloads paused."
    changing = [(method, params) for _path, method, params in calls if method not in ("d.multicall2", "system.client_version")]
    # ⚠️ Not a multicall, and d.stop rather than d.pause: see pause().
    assert changing == [("d.stop", ("HASH-OF-THE-DISTRIBUTION-IMAGE-FOR-TESTS",))]


@respx.mock
async def test_resume_starts_what_is_paused_or_stopped_and_leaves_the_done_ones(ctx: Context) -> None:
    stopped = row(hash="HASH-OF-A-TORRENT-STOPPED-BY-SOMEBODY-XXX", name="stopped.bin", size_bytes=10, left_bytes=10)
    calls = server(RT, rows=[PAUSED, stopped, FINISHED, SEEDING, DAMAGED])
    assert await ADAPTER.action("queue", "resume", {}, CONFIG, {}, ctx) == "Downloads resumed."
    changing = [(method, params[0]) for _path, method, params in calls if method in ("d.stop", "d.start", "system.multicall")]
    assert changing == [
        # ⚠️ Paused with d.pause: d.start alone leaves it paused.
        ("d.stop", "HASH-OF-A-TORRENT-WITH-A-DEAD-TRACKER-XX"), ("d.start", "HASH-OF-A-TORRENT-WITH-A-DEAD-TRACKER-XX"),
        ("d.start", "HASH-OF-A-TORRENT-STOPPED-BY-SOMEBODY-XXX"),
        ("d.start", "HASH-OF-A-TORRENT-DAMAGED-ON-THE-DISK-XXX"),
    ]


@respx.mock
async def test_a_wrong_password_on_either_door(ctx: Context) -> None:
    server(RT)
    with pytest.raises(AuthFailed, match="rejected the user name or password"):
        await ADAPTER.test({**CONFIG, "password": "wrong"}, ctx)


@respx.mock
async def test_a_command_rutorrent_refuses_is_a_refusal_and_not_a_password(ctx: Context) -> None:
    respx.post(f"{RU}/plugins/httprpc/action.php").mock(return_value=httpx.Response(403, text=REJECTED, headers={"Content-Type": "text/xml; charset=UTF-8"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test({**CONFIG, "url": f"{RU}/plugins/httprpc/action.php"}, ctx)
    assert caught.value.code == "rpc_error" and "rejected by this server" in caught.value.message


@respx.mock
async def test_an_unknown_method_is_named(ctx: Context) -> None:
    respx.post(f"{RT}/RPC2").mock(return_value=httpx.Response(200, text=UNKNOWN, headers={"Content-Type": "text/xml"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "rpc_error" and "not defined" in caught.value.message


@respx.mock
@pytest.mark.parametrize(("status", "body"), [(502, "<html>502 Bad Gateway</html>"), (500, "Could not complete the rTorrent XMLRPC request.")])
async def test_rtorrent_stopped_behind_the_web_server(ctx: Context, status: int, body: str) -> None:
    # ⚠️ Measured with rTorrent stopped: 502 from the XML-RPC port, 500 from ruTorrent.
    respx.post(url__startswith=RT).mock(return_value=httpx.Response(status, text=body, headers={"Content-Type": "text/html"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert caught.value.code == "rtorrent_down"


@respx.mock
async def test_a_web_page_is_not_rtorrent(ctx: Context) -> None:
    respx.post(url__startswith=RT).mock(return_value=httpx.Response(200, text="<html>welcome</html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.code == "not_rtorrent"
    assert respx.calls.call_count == 2, "both doors were tried"


@respx.mock
async def test_rtorrent_out_of_reach(ctx: Context) -> None:
    respx.post(url__startswith=RT).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("queue", CONFIG, {}, ctx)


def test_the_state_words() -> None:
    from app.adapters.rtorrent import state_of

    def state(values: list[Any]) -> str:
        return state_of(dict(zip(FIELDS, values, strict=True)))

    assert [state(one) for one in ALL] == ["downloading", "paused", "seeding", "finished", "error", "checking"]
    # Queued for its check, before is_hash_checking says so.
    assert state(row(state=1, is_active=1, is_open=1, hashing=1)) == "checking"
    assert state(row(state=1, is_active=1, is_open=1, message="Tracker: [Tried all trackers.]")) == "downloading"


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in range(6):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary
