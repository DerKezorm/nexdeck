"""A custom card only reads: what acts is refused before it leaves, whoever wrote the card (korrektur J1, F2).

"Only GET" is not "only reading": ``GET /api.cgi?cmd=Reboot`` restarts a camera with the key of the connection. A card can
come from a shop. The kinds whose address carries the command list what a card may ask; for every kind the words that act
(``reboot``, ``delete``, ``purge`` and so on) are refused as a whole word in a path segment or the value of a parameter.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import all_adapters, get_adapter
from app.adapters.base import AdapterError, Context
from app.adapters.rawread import refuse_a_command

BASE = "http://svc.example.com:8080"

#: Kind -> (requests that act, requests that read).
BY_KIND: dict[str, tuple[list[str], list[str]]] = {
    "reolink": (
        ["/api.cgi?cmd=Reboot", "/api.cgi?cmd=PtzCtrl&channel=0", "/api.cgi?cmd=SetTime", "/api.cgi?CMD=Login", "/api.cgi?cmd=GetDevInfo&cmd=Format"],
        ["/api.cgi?cmd=GetDevInfo", "/api.cgi?cmd=Snap&channel=0", "/api.cgi?cmd=Search&channel=0"],
    ),
    "tautulli": (
        ["/api/v2?cmd=restart", "/api/v2?cmd=sql&query=x", "/api/v2?cmd=get_apikey", "/api/v2?cmd=update"],
        ["/api/v2?cmd=get_activity", "/api/v2?cmd=get_history&length=5", "/api/v2?cmd=status"],
    ),
    "sabnzbd": (
        ["/api?mode=queue&name=delete&value=all", "/api?mode=shutdown", "/api?mode=pause", "/api?mode=set_config", "/api?mode=get_config&section=misc", "/api?mode=queue&name=pause"],
        ["/api?mode=queue&output=json", "/api?mode=history&limit=5", "/api?mode=version", "/api?mode=get_cats&output=json"],
    ),
    "synology": (
        ["/webapi/entry.cgi?api=SYNO.Core.System&method=shutdown", "/webapi/entry.cgi?api=SYNO.API.Auth&method=logout", "/webapi/entry.cgi?api=SYNO.Core.System&method=reboot"],
        ["/webapi/entry.cgi?api=SYNO.Core.System&method=info&version=1", "/webapi/entry.cgi?api=SYNO.Docker.Container&method=list"],
    ),
    "navidrome": (
        ["/rest/deletePlaylist?id=1", "/rest/startScan", "/rest/createUser.view", "/rest/updatePlaylist?playlistId=1"],
        ["/rest/getScanStatus", "/rest/getArtists.view", "/rest/ping", "/rest/search3?query=x"],
    ),
    "urbackup": (["/x?a=login", "/x?a=add_client", "/x?a=start_backup"], ["/x?a=status", "/x?a=progress"]),
    "nzbget": (["/jsonrpc/shutdown", "/jsonrpc/reload", "/jsonrpc/editqueue"], ["/jsonrpc/listgroups", "/jsonrpc/status", "/jsonrpc/version"]),
    "technitium": (["/api/zones/create", "/api/settings/set", "/api/cache/flush"], ["/api/dashboard/stats/get", "/api/zones/list", "/api/dashboard/stats/getTop"]),
    "blocky": (["/api/blocking/disable?duration=5m", "/api/blocking/enable"], ["/api/stats", "/api/blocking/status"]),
    "plex": (["/library/sections/1/refresh", "/:/scrobble?key=1", "/library/optimize"], ["/library/sections", "/status/sessions"]),
    "owncast": (["/api/admin/disconnect"], ["/api/status", "/api/admin/status", "/api/admin/followers?limit=1"]),
}


@pytest.mark.parametrize("kind", sorted(BY_KIND))
def test_korrektur_f2_a_kind_whose_address_carries_the_command_refuses_what_acts_and_lets_a_read_through(kind: str) -> None:
    adapter = get_adapter(kind)
    acts, reads = BY_KIND[kind]
    assert adapter.raw_read_commands is not None or kind in ("blocky", "plex")
    for path in acts:
        with pytest.raises(AdapterError) as refused:
            refuse_a_command(adapter, path)
        assert refused.value.code == "command_refused" and refused.value.hint, path
    for path in reads:
        refuse_a_command(adapter, path)


@respx.mock
async def test_korrektur_f2_a_refused_command_never_leaves_and_a_read_does() -> None:
    adapter = get_adapter("reolink")
    config = {"url": BASE, "username": "admin", "password": "Zk-password-1"}
    sent = respx.get(url__regex=rf"{BASE}/api\.cgi.*").mock(return_value=httpx.Response(200, json=[{"cmd": "GetDevInfo", "code": 0}]))
    login = respx.post(url__regex=rf"{BASE}/api\.cgi.*").mock(
        return_value=httpx.Response(200, json=[{"cmd": "Login", "code": 0, "value": {"Token": {"name": "tok", "leaseTime": 3600}}}])
    )
    held = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as refused:
        await adapter.raw_request("GET", "/api.cgi?cmd=Reboot", config, held)
    assert refused.value.code == "command_refused"
    assert not sent.called and not login.called, "nothing was sent, not even a sign-in"
    answer = await adapter.raw_request("GET", "/api.cgi?cmd=GetDevInfo", config, held)
    assert answer.status_code == 200 and sent.called


@pytest.mark.parametrize("word", ["reboot", "restart", "shutdown", "poweroff", "delete", "remove", "purge", "kill", "format", "reset", "factory"])
def test_korrektur_f2_every_kind_refuses_the_words_that_act_as_a_whole_word(word: str) -> None:
    # One kind of each way to carry a word: a path segment, a parameter value, camel case, a different case.
    adapter = get_adapter("radarr")
    for path in (f"/api/{word}", f"/api/x/{word}-all", f"/api/x?do={word}", f"/api/x?do={word.upper()}", f"/api/x/{word.title()}Now"):
        with pytest.raises(AdapterError) as refused:
            refuse_a_command(adapter, path)
        assert refused.value.code == "command_refused", path


def test_korrektur_f2_a_harmless_name_that_only_contains_the_word_is_not_refused() -> None:
    adapter = get_adapter("radarr")
    for path in (
        "/api/updates", "/api/v3/system/status", "/api/items?sort=lastUpdated", "/api/items?fields=deletedAt", "/api/x?format=json",
        "/api/removedItems", "/api/resetting", "/api/formatted", "/api/x?q=killer+whale", "/api/factoryworks",
    ):
        refuse_a_command(adapter, path)


def test_korrektur_f2_the_rule_goes_over_every_kind_that_can_be_read() -> None:
    # Every adapter that a card can read through refuses the same words, not only the ones with a list of their own.
    for adapter in all_adapters():
        if not adapter.raw_access:
            continue
        with pytest.raises(AdapterError):
            refuse_a_command(adapter, "/api/x?cmd=reboot")
