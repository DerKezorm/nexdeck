"""PatchMon, against the answers of a live PatchMon 2.1.3 with four hosts (27.09.2026), names and keys replaced."""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable, keep_parts

PM = "http://patchmon.example.com:3000"
HOSTS_URL = f"{PM}/api/v1/api/hosts"
CONFIG = {"url": PM, "token_key": "patchmon_ae_cards", "token_secret": "pm-test-key-for-the-cards"}
ADAPTER = get_adapter("patchmon")
#: 27.09.2026 11:42:30 UTC, a few seconds after the answer below was taken.
NOW = 1790509350.0
SERVERS = {"id": "3f9c2b7e-5d41-4c8a-9e06-7b1d2f4a8c90", "name": "Servers"}


def host(name: str, **fields: Any) -> dict[str, Any]:
    """One host the way ``?include=stats`` answered it."""
    entry = {"effective_status": "active", "friendly_name": name, "host_groups": [], "hostname": name, "id": f"id-{name}",
             "ip": "192.0.2.20", "last_update": "2026-09-27T11:42:16Z", "needs_reboot": False, "os_type": "Debian GNU/Linux",
             "os_version": "13 (trixie)", "reporting_state": "reporting", "security_updates_count": 0, "status": "active",
             "total_packages": 108, "update_state": "up_to_date", "updates_count": 0}
    entry.update(fields)
    return entry


HOSTS = [
    # ⚠️ Alpine 3.20 said its version was "Unknown".
    host("alpine-edge", effective_status="inactive", last_update="2026-09-27T11:29:07Z", os_type="Alpine Linux", os_version="Unknown",
         reporting_state="stale", total_packages=24),
    host("fresh-debian", host_groups=[SERVERS]),
    # ⚠️ Never reported: pending, "unknown" systems, and at first reporting_state "reporting".
    host("never-reported", effective_status="pending", hostname="", ip="", last_update="2026-09-27T11:27:38Z", os_type="unknown",
         os_version="unknown", status="pending", total_packages=0),
    host("new-debian", last_update="2026-09-27T11:40:06Z", reporting_state="overdue"),
    host("old-debian", host_groups=[SERVERS], needs_reboot=True, os_version="12 (bookworm)", security_updates_count=6,
         total_packages=106, update_state="security_required", updates_count=45),
]


def answer(hosts: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"hosts": hosts, "total": len(hosts), **extra}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


@pytest.fixture
def at_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.patchmon.time.time", lambda: NOW)


@respx.mock
async def test_one_key_of_the_type_api_reads_the_hosts_with_their_numbers(ctx: Context) -> None:
    route = respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(HOSTS)))
    spaced = {**CONFIG, "url": PM + "/", "token_key": " patchmon_ae_cards ", "token_secret": "pm-test-key-for-the-cards\n"}
    assert await ADAPTER.test(spaced, ctx) == "PatchMon answers; it knows 5 host(s)."
    sent = route.calls.last.request
    assert sent.url.params["include"] == "stats" and "hostgroup" not in sent.url.params
    assert sent.headers["Authorization"] == "Basic " + base64.b64encode(b"patchmon_ae_cards:pm-test-key-for-the-cards").decode()


@respx.mock
async def test_the_overview_adds_up_the_hosts(ctx: Context) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(HOSTS)))
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.status == "bad"
    assert card.primary == {"label": "Need updates", "value": 1, "unit": "/ 5"}
    assert [(row["part"], row["value"]) for row in card.secondary] == [
        ("security", 6), ("updates", 45), ("up_to_date", 3), ("offline", 1), ("reboot", 1), ("waiting", 1)]
    # ⚠️ Hosts, not packages: one each, and the host that never reported is not up to date.
    assert card.meta["ring"] == [{"label": "Up to date", "value": 3.0}, {"label": "Need updates", "value": 0.0},
                                 {"label": "With security updates", "value": 1.0}, {"label": "No report yet", "value": 1.0}]
    assert card.metrics == {"hosts_need_updates": 1.0, "security_updates": 6.0}


@respx.mock
async def test_the_overview_colours_and_leaves_out_what_is_nought(ctx: Context) -> None:
    calm = [host("fresh-debian"), host("web", updates_count=3, update_state="updates_pending")]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(calm)))
    card = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert card.status == "warn"
    assert [row["part"] for row in card.secondary] == ["security", "updates", "up_to_date", "offline"]
    assert card.meta["ring"][1] == {"label": "Need updates", "value": 1.0}
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer([host("fresh-debian")])))
    assert (await ADAPTER.fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))).status == "ok"
    gone = [host("fresh-debian", effective_status="inactive", reporting_state="stale")]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(gone)))
    assert (await ADAPTER.fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))).status == "warn"


@respx.mock
async def test_an_instance_without_hosts(ctx: Context) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json={"hosts": [], "total": 0}))
    summary = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert summary.status == "unknown" and summary.primary == {"label": "Need updates", "value": 0, "unit": "/ 0"}
    hosts = await ADAPTER.fetch("hosts", CONFIG, {}, ctx)
    assert hosts.items == [] and hosts.status == "unknown" and hosts.meta["empty"] == "PatchMon knows no host yet."
    systems = await ADAPTER.fetch("systems", CONFIG, {}, ctx)
    assert systems.items == [] and systems.meta["empty"] == "No host has reported its operating system yet."


@respx.mock
async def test_hosts_with_security_updates_and_offline_ones_first(ctx: Context, at_now: None) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(HOSTS)))
    card = await ADAPTER.fetch("hosts", CONFIG, {}, ctx)
    assert card.status == "bad"
    assert [(row["title"], row["subtitle"], row["status"], row.get("value")) for row in card.items] == [
        ("old-debian", "6 security updates · Reboot needed · Debian GNU/Linux 12 (bookworm) · 0 min ago", "bad", 45),
        ("alpine-edge", "Offline, last seen 13 min ago · Alpine Linux", "warn", 0),
        ("new-debian", "Report overdue · Debian GNU/Linux 13 (trixie) · 2 min ago", "warn", 0),
        # ⚠️ Its last_update is when it was made, so no age and no number.
        ("never-reported", "No report yet", "unknown", None),
        ("fresh-debian", "Debian GNU/Linux 13 (trixie) · 0 min ago", "ok", 0),
    ]


@respx.mock
async def test_a_host_offline_with_security_updates_still_says_so(ctx: Context, at_now: None) -> None:
    both = [host("quiet", effective_status="inactive", reporting_state="stale", last_update="2026-09-27T09:42:30Z",
                 security_updates_count=1, updates_count=2),
            host("other", effective_status="inactive", reporting_state="stale", last_update="", updates_count=4)]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(both)))
    card = await ADAPTER.fetch("hosts", CONFIG, {}, ctx)
    assert [(row["title"], row["subtitle"]) for row in card.items] == [
        ("quiet", "Offline, last seen 2 h ago · 1 security update · Debian GNU/Linux 13 (trixie)"),
        ("other", "Offline · Debian GNU/Linux 13 (trixie)"),
    ]


@respx.mock
async def test_before_2_0_3_a_stale_active_host_counts_as_offline(ctx: Context, at_now: None) -> None:
    # ⚠️ Without effective_status, status stays "active" for ever.
    old = [{key: value for key, value in host("legacy", reporting_state="stale").items() if key != "effective_status"}]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(old)))
    card = await ADAPTER.fetch("hosts", CONFIG, {}, ctx)
    assert card.items[0]["subtitle"].startswith("Offline, last seen") and card.items[0]["status"] == "warn"


@respx.mock
async def test_only_those_that_need_attention_and_a_limit(ctx: Context, at_now: None) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(HOSTS)))
    card = await ADAPTER.fetch("hosts", CONFIG, {"attention": True}, ctx)
    assert [row["title"] for row in card.items] == ["old-debian", "alpine-edge", "new-debian", "never-reported"]
    short = await ADAPTER.fetch("hosts", CONFIG, {"limit": 2}, ctx)
    assert [row["title"] for row in short.items] == ["old-debian", "alpine-edge"]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer([host("fresh-debian")])))
    calm = await ADAPTER.fetch("hosts", CONFIG, {"attention": True}, Context(httpx.AsyncClient(), cache={}))
    assert calm.items == [] and calm.meta["empty"] == "Every host is up to date."


@respx.mock
async def test_pieces_of_a_row_can_be_left_out(ctx: Context, at_now: None) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(HOSTS)))
    options = {"show_os": False, "show_seen": False, "show_value": False}
    card = await ADAPTER.fetch("hosts", CONFIG, options, ctx)
    card = keep_parts(card, ADAPTER.widget("hosts").parts, options)
    assert card.items[0] == {"title": "old-debian", "subtitle": "6 security updates · Reboot needed", "status": "bad"}


@respx.mock
async def test_the_list_can_be_drawn_as_bars(ctx: Context) -> None:
    from app.adapters.base import as_bars

    heavy = [*HOSTS, host("web", updates_count=12)]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(heavy)))
    card = as_bars(await ADAPTER.fetch("hosts", CONFIG, {}, ctx), {"view": "bars"})
    assert card.meta["renderer"] == "bars"


@respx.mock
async def test_operating_systems_leave_out_hosts_that_never_reported(ctx: Context) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(HOSTS)))
    card = await ADAPTER.fetch("systems", CONFIG, {}, ctx)
    assert [(row["title"], row["value"]) for row in card.items] == [
        ("Debian GNU/Linux 13 (trixie)", 2), ("Alpine Linux", 1), ("Debian GNU/Linux 12 (bookworm)", 1)]
    assert card.meta["ring"] == [{"label": "Debian GNU/Linux 13 (trixie)", "value": 2.0}, {"label": "Alpine Linux", "value": 1.0},
                                 {"label": "Debian GNU/Linux 12 (bookworm)", "value": 1.0}]
    merged = await ADAPTER.fetch("systems", CONFIG, {"versions": False}, ctx)
    assert [(row["title"], row["value"], row.get("subtitle")) for row in merged.items] == [
        ("Debian GNU/Linux", 3, "12 (bookworm), 13 (trixie)"), ("Alpine Linux", 1, None)]


@respx.mock
async def test_a_pending_host_counts_nowhere_whatever_it_already_carries(ctx: Context) -> None:
    # PatchMon counts systems of active hosts only; a pending one that already names its system stays out.
    early = [host("fresh-debian"), host("enrolled", effective_status="pending", status="pending", os_type="Ubuntu", os_version="24.04 LTS",
                                         total_packages=0),
             host("half", effective_status="pending", status="pending", os_type="Ubuntu", os_version="24.04 LTS", total_packages=50,
                  updates_count=4)]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(early)))
    systems = await ADAPTER.fetch("systems", CONFIG, {}, ctx)
    assert [(row["title"], row["value"]) for row in systems.items] == [("Debian GNU/Linux 13 (trixie)", 1)]
    summary = await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert summary.primary["value"] == 0 and {row["part"]: row["value"] for row in summary.secondary}["waiting"] == 2
    rows = await ADAPTER.fetch("hosts", CONFIG, {}, ctx)
    assert {(row["title"], row["subtitle"], row["status"]) for row in rows.items[:2]} == {
        ("enrolled", "No report yet · Ubuntu 24.04 LTS", "unknown"), ("half", "No report yet · Ubuntu 24.04 LTS", "unknown")}


@respx.mock
async def test_the_ring_of_systems_keeps_six_slices(ctx: Context) -> None:
    many = [host(f"box-{index}", os_type=f"System {chr(65 + index)}", os_version="1", updates_count=0) for index in range(8)]
    many += [host("extra", os_type="System A", os_version="1")]
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(many)))
    card = await ADAPTER.fetch("systems", CONFIG, {}, ctx)
    assert len(card.items) == 8
    assert [piece["label"] for piece in card.meta["ring"]] == ["System A 1", "System B 1", "System C 1", "System D 1", "System E 1", "Other"]
    assert card.meta["ring"][0]["value"] == 2.0 and card.meta["ring"][-1]["value"] == 3.0
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(many[:6])))
    six = await ADAPTER.fetch("systems", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))
    assert "Other" not in [piece["label"] for piece in six.meta["ring"]] and len(six.meta["ring"]) == 6


@respx.mock
async def test_a_host_group_is_asked_for_and_offered(ctx: Context) -> None:
    route = respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json=answer(HOSTS)))
    assert await ADAPTER.choices("group", CONFIG, ctx) == [(SERVERS["id"], "Servers")]
    route.mock(return_value=httpx.Response(200, json=answer([HOSTS[1], HOSTS[4]], filtered_by_groups=[SERVERS["id"]])))
    card = await ADAPTER.fetch("summary", CONFIG, {"group": SERVERS["id"]}, ctx)
    assert route.calls.last.request.url.params["hostgroup"] == SERVERS["id"]
    assert card.primary == {"label": "Need updates", "value": 1, "unit": "/ 2"}
    # ⚠️ A group that is gone answers an empty list, not an error.
    route.mock(return_value=httpx.Response(200, json=answer([], filtered_by_groups=["Gone"])))
    hosts = await ADAPTER.fetch("hosts", CONFIG, {"group": "Gone"}, ctx)
    assert hosts.items == [] and hosts.meta["empty"] == "No host in this group."
    systems = await ADAPTER.fetch("systems", CONFIG, {"group": "Gone"}, ctx)
    assert systems.meta["empty"] == "No host in this group."


@pytest.mark.parametrize(("said", "message"), [
    ("Invalid API secret", "PatchMon rejected the token key or its secret."),
    ("Invalid API key", "PatchMon rejected the token key or its secret."),
    ("Missing or invalid authorization header", "PatchMon rejected the token key or its secret."),
    ("API key is disabled", "The key is switched off in PatchMon."),
    ("API key has expired", "The key has expired in PatchMon."),
    # ⚠️ A GetHomepage key at the scoped API.
    ("Invalid API key type", "This key is not of the type API."),
])
@respx.mock
async def test_each_refusal_at_the_door_is_named(said: str, message: str, ctx: Context) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(401, json={"error": said}))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.test(CONFIG, ctx)
    assert caught.value.message == message and caught.value.code == "auth_failed"
    assert "usage type API" in caught.value.hint or said.startswith("API key")
    if said == "Invalid API key type":
        assert "GetHomepage" in caught.value.hint


@pytest.mark.parametrize(("body", "code"), [
    ({"error": "IP address not allowed"}, "address_refused"),
    ({"error": "Access denied", "message": "This API key does not have the required permissions"}, "forbidden"),
    # ⚠️ Any address not in CORS_ORIGIN, the API included.
    ({"error": "Host not allowed. Access this app via the URL configured in CORS_ORIGIN (.env or Database settings).",
      "code": "host_mismatch"}, "host_mismatch"),
])
@respx.mock
async def test_refusals_after_the_door(body: dict[str, str], code: str, ctx: Context) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(403, json=body))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("hosts", CONFIG, {}, ctx)
    assert caught.value.code == code and not isinstance(caught.value, AuthFailed)


@respx.mock
async def test_the_web_interface_is_not_the_api(ctx: Context) -> None:
    # ⚠️ An unknown path under /api/v1/api answers 200 with the web interface.
    respx.get(f"{PM}/api/v1/api/v1/api/hosts").mock(return_value=httpx.Response(200, text="<!doctype html><html lang=\"en\"></html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test({**CONFIG, "url": PM + "/api/v1"}, ctx)
    assert caught.value.code == "not_patchmon"
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(200, json={"total": 0}))
    with pytest.raises(AdapterError) as other:
        await ADAPTER.test(CONFIG, ctx)
    assert other.value.code == "not_patchmon"


@respx.mock
async def test_a_failing_server_and_one_that_is_not_there(ctx: Context) -> None:
    respx.get(HOSTS_URL).mock(return_value=httpx.Response(500, json={"error": "Failed to fetch hosts"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("summary", CONFIG, {}, ctx)
    assert caught.value.code == "http_error" and "500" in caught.value.message
    respx.get(HOSTS_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("summary", CONFIG, {}, Context(httpx.AsyncClient(), cache={}))


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 1, 7, 300):
        card = ADAPTER.demo(kind, {}, tick)
        assert card.items or card.primary
    grouped = ADAPTER.demo(kind, {"group": "group-web"}, 0)
    assert grouped.items or grouped.primary


def test_demo_offers_its_groups_and_draws_a_ring() -> None:
    assert ADAPTER.demo_choices("group") == [("group-infra", "Infrastructure"), ("group-web", "Web")]
    assert ADAPTER.demo_choices("other") == []
    assert len(ADAPTER.demo("summary", {}, 0).meta["ring"]) >= 2
    assert len(ADAPTER.demo("systems", {}, 0).meta["ring"]) >= 2
