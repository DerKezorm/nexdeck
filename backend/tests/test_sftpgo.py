"""SFTPGo. The fixtures were recorded from SFTPGo 2.7.6 on 27.10.2026 with the
defender switched on: three users (one with a quota in use, one without a
quota, one disabled), two transfers running, and a ban that the failed
logins of the measurement itself had caused. Names and addresses are made up."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, outbound_client
from app.adapters.sftpgo import _wait_left

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = {"url": "http://sftpgo:8080", "api_key": "abc123.example-secret"}
API = "http://sftpgo:8080/api/v2"


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


def served(*, banned: list[dict[str, Any]] | None = None, defender: bool = True) -> None:
    status = recorded("sftpgo_status.json")
    status["defender"]["is_active"] = defender
    respx.get(f"{API}/status").mock(return_value=httpx.Response(200, json=status))
    respx.get(f"{API}/version").mock(return_value=httpx.Response(200, json=recorded("sftpgo_version.json")))
    respx.get(f"{API}/connections").mock(return_value=httpx.Response(200, json=recorded("sftpgo_connections.json")))
    respx.get(f"{API}/users").mock(return_value=httpx.Response(200, json=recorded("sftpgo_users.json")))
    respx.get(f"{API}/defender/hosts").mock(
        return_value=httpx.Response(200, json=banned if banned is not None else recorded("sftpgo_banned.json")))


@respx.mock
async def test_the_overview_counts_connections_transfers_users_and_bans(ctx: Context) -> None:
    served()
    data = await get_adapter("sftpgo").fetch("overview", CONFIG, {}, ctx)
    assert data.primary == {"label": "Connections", "value": 2}
    assert data.secondary == [
        {"label": "Transfers", "value": 2}, {"label": "Users", "value": 3}, {"label": "Banned addresses", "value": 1}]
    assert data.status == "warn"
    assert data.metrics == {"connections": 2.0, "banned": 1.0}
    assert respx.calls[0].request.headers["X-SFTPGO-API-KEY"] == "abc123.example-secret"


@respx.mock
async def test_with_the_defender_off_the_overview_says_so_and_never_asks_for_bans(ctx: Context) -> None:
    served(defender=False)
    data = await get_adapter("sftpgo").fetch("overview", CONFIG, {}, ctx)
    assert {"label": "Defender", "value": "Off"} in data.secondary
    assert data.status == "ok" and "banned" not in data.metrics
    assert not any(call.request.url.path.endswith("/defender/hosts") for call in respx.calls)


@respx.mock
async def test_no_bans_is_green(ctx: Context) -> None:
    served(banned=[])
    data = await get_adapter("sftpgo").fetch("overview", CONFIG, {}, ctx)
    assert data.status == "ok" and data.metrics["banned"] == 0.0


@respx.mock
async def test_the_connections_card_names_user_address_and_what_is_moving(ctx: Context) -> None:
    served()
    now = 1793124593.7
    data = get_adapter("sftpgo")._connections(recorded("sftpgo_connections.json"), {}, now)
    first = data.items[0]
    assert first["title"] == "alice"
    assert first["subtitle"] == "192.0.2.10:36194 · Downloading /blob1 · 13s"
    assert first["value"] == "SFTP"
    assert data.items[1]["subtitle"].startswith("192.0.2.10:36196 · Uploading /slow1")
    assert data.secondary == [{"label": "Connections", "value": 2}]
    live = await get_adapter("sftpgo").fetch("connections", CONFIG, {"limit": 1}, ctx)
    assert len(live.items) == 1


@respx.mock
async def test_a_connection_can_be_closed_and_the_button_says_who(ctx: Context) -> None:
    served()
    data = await get_adapter("sftpgo").fetch("connections", CONFIG, {}, ctx)
    [button] = data.items[0]["actions"]
    assert (button.id, button.confirm, button.params) == ("disconnect", True, {"id": "SFTP_ab12cd34_1"})
    route = respx.delete(f"{API}/connections/SFTP_ab12cd34_1").mock(return_value=httpx.Response(200, json={"message": "Connection closed"}))
    assert await get_adapter("sftpgo").action("connections", "disconnect", {"id": "SFTP_ab12cd34_1"}, CONFIG, {}, ctx) == "Connection closed."
    assert route.calls.last.request.headers["X-SFTPGO-API-KEY"] == "abc123.example-secret"


@respx.mock
async def test_a_connection_that_closed_meanwhile_is_said_so(ctx: Context) -> None:
    respx.delete(f"{API}/connections/SFTP_gone_1").mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("sftpgo").action("connections", "disconnect", {"id": "SFTP_gone_1"}, CONFIG, {}, ctx)
    assert failure.value.code == "gone"


@respx.mock
async def test_the_quota_card_gives_used_against_quota_and_marks_a_disabled_user(ctx: Context) -> None:
    served()
    data = await get_adapter("sftpgo").fetch("quotas", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in data.items}
    assert rows["alice"]["subtitle"] == "3.8 MB of 10.0 MB" and rows["alice"]["value"] == 4_000_000
    # Alice used 38 percent; a quota of 0 is no quota.
    assert rows["alice"]["status"] == "ok"
    assert rows["bob"]["subtitle"] == "0 B" and rows["bob"]["status"] == "ok"
    assert rows["carol"]["subtitle"] == "0 B of 1.0 MB · Disabled"
    assert data.items[0]["title"] == "alice"
    assert data.secondary == [{"label": "Users", "value": 3}]


@respx.mock
async def test_a_user_near_the_quota_is_yellow_then_red(ctx: Context) -> None:
    users = recorded("sftpgo_users.json")
    users[0]["used_quota_size"] = 9_000_000
    served()
    respx.get(f"{API}/users").mock(return_value=httpx.Response(200, json=users))
    data = await get_adapter("sftpgo").fetch("quotas", CONFIG, {}, ctx)
    assert (data.items[0]["status"], data.status) == ("warn", "warn")
    users[0]["used_quota_size"] = 10_300_000
    ctx.cache.clear()
    respx.get(f"{API}/users").mock(return_value=httpx.Response(200, json=users))
    data = await get_adapter("sftpgo").fetch("quotas", CONFIG, {}, ctx)
    assert (data.items[0]["status"], data.status) == ("bad", "bad")


@respx.mock
async def test_more_than_a_page_of_users_is_read_page_by_page(ctx: Context) -> None:
    page = [{"username": f"u{n}", "status": 1, "quota_size": 0, "used_quota_size": n} for n in range(100)]
    route = respx.get(f"{API}/users").mock(side_effect=[
        httpx.Response(200, json=page), httpx.Response(200, json=page[:7])])
    data = await get_adapter("sftpgo").fetch("quotas", CONFIG, {"limit": 3}, ctx)
    assert data.secondary == [{"label": "Users", "value": 107}]
    assert [call.request.url.params["offset"] for call in route.calls] == ["0", "100"]
    assert len(data.items) == 3


@respx.mock
async def test_the_banned_card_gives_the_address_and_the_time_left_and_can_unban(ctx: Context) -> None:
    served()
    data = await get_adapter("sftpgo").fetch("banned", CONFIG, {}, ctx)
    row = data.items[0]
    assert (row["title"], row["value"], row["status"]) == ("192.0.2.7", "Banned", "warn")
    [button] = row["actions"]
    assert (button.id, button.confirm, button.params) == ("unban", True, {"id": "3139322e302e322e37"})
    assert data.status == "warn" and data.secondary == [{"label": "Banned addresses", "value": 1}]
    route = respx.delete(f"{API}/defender/hosts/3139322e302e322e37").mock(return_value=httpx.Response(200, json={"message": "OK"}))
    assert await get_adapter("sftpgo").action("banned", "unban", {"id": "3139322e302e322e37"}, CONFIG, {}, ctx) == "Address unbanned."
    assert route.call_count == 1


def test_the_time_left_of_a_ban_reads_in_minutes_and_is_empty_when_over() -> None:
    assert _wait_left("2026-10-27T20:10:45Z", 1793131845 - 1700 + 0) == "28 min left"
    assert _wait_left("2026-10-27T20:10:45Z", 1793131845 + 5) == ""
    assert _wait_left("nonsense") == ""


@respx.mock
async def test_with_the_defender_off_the_banned_card_is_unknown_not_empty(ctx: Context) -> None:
    served(defender=False)
    data = await get_adapter("sftpgo").fetch("banned", CONFIG, {}, ctx)
    assert data.status == "unknown" and data.items == []
    assert data.secondary == [{"label": "Defender", "value": "Off"}]


@respx.mock
async def test_an_id_that_climbs_out_of_the_path_never_reaches_the_server(ctx: Context) -> None:
    route = respx.delete(url__regex=rf"{API}/.*").mock(return_value=httpx.Response(200, json={}))
    for bad in ("../users/alice", "a?b", "", None):
        with pytest.raises(AdapterError) as failure:
            await get_adapter("sftpgo").action("banned", "unban", {"id": bad}, CONFIG, {}, ctx)
        assert failure.value.code == "bad_param"
    assert route.call_count == 0
    with pytest.raises(AdapterError) as failure:
        await get_adapter("sftpgo").action("banned", "format", {"id": "ab"}, CONFIG, {}, ctx)
    assert failure.value.code == "no_such_action"


@respx.mock
async def test_the_connection_test_names_the_version(ctx: Context) -> None:
    served()
    assert await get_adapter("sftpgo").test(CONFIG, ctx) == "SFTPGo 2.7.6 answers."
    assert await get_adapter("sftpgo").running_version(CONFIG, ctx) == "2.7.6"


@respx.mock
async def test_a_key_the_server_refuses_is_an_authentication_failure(ctx: Context) -> None:
    respx.get(f"{API}/connections").mock(return_value=httpx.Response(401, json={"error": "invalid credentials", "message": "Unauthorized"}))
    with pytest.raises(AuthFailed):
        await get_adapter("sftpgo").fetch("connections", CONFIG, {}, ctx)


@respx.mock
async def test_a_ban_of_nexdecks_own_address_is_told_apart_from_a_wrong_key(ctx: Context) -> None:
    respx.get(f"{API}/connections").mock(return_value=httpx.Response(403, json={"error": "your IP address is blocked", "message": ""}))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("sftpgo").fetch("connections", CONFIG, {}, ctx)
    assert failure.value.code == "blocked_by_defender"
    assert not isinstance(failure.value, AuthFailed)
    assert "safe list" in (failure.value.hint or "")


@respx.mock
async def test_the_sftp_port_instead_of_the_web_port_says_so(ctx: Context) -> None:
    route = respx.get(f"{API}/connections").mock(return_value=httpx.Response(200, text="SSH-2.0-SFTPGo"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("sftpgo").fetch("connections", CONFIG, {}, ctx)
    assert failure.value.code == "not_json"
    ctx.cache.clear()
    route.mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(AdapterError) as failure:
        await get_adapter("sftpgo").fetch("connections", CONFIG, {}, ctx)
    assert failure.value.code == "http_error"


@respx.mock
async def test_an_unreachable_server_is_unreachable(ctx: Context) -> None:
    respx.get(f"{API}/connections").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await get_adapter("sftpgo").fetch("connections", CONFIG, {}, ctx)


@respx.mock
async def test_the_fullest_user_comes_first_whatever_order_sftpgo_lists_them_in(ctx: Context) -> None:
    served()
    respx.get(f"{API}/users").mock(return_value=httpx.Response(200, json=recorded("sftpgo_users.json")[::-1]))
    data = await get_adapter("sftpgo").fetch("quotas", CONFIG, {}, ctx)
    assert [row["title"] for row in data.items] == ["alice", "bob", "carol"]
