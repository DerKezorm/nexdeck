"""nexbrand 0.2.0, from its ``docs/api.md`` and ``routers/v1.py``: the shapes are the documented ones, the names and
counts made up. The adapter was also run against a fresh
instance on 11.10.2026; these tests keep what that showed."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters import nexbrand as module
from app.adapters.base import AdapterError, AuthFailed, Context, outbound_client

CONFIG = {"url": "http://nexbrand:8540", "api_key": "nxb_example"}
BASE = "http://nexbrand:8540/api/v1"


def client(number: int, name: str, current: str | None = "2026", projects: int = 0) -> dict:
    return {"id": f"c{number}", "name": name, "sector": "Bakery", "current_version": current,
            "colors": ["#C23B2E"], "projects": [{"id": f"p{number}-{index}", "name": f"Project {index}"} for index in range(projects)]}


def version(number: str, label: str, status: str = "published", valid_from: str | None = "2026-03-01", author: str = "robin") -> dict:
    return {"id": number, "label": label, "status": status, "valid_from": valid_from, "origin": "hand", "author": author,
            "note": "Warmer red.", "based_on": None}


CLIENTS = [client(1, "Example Bakery", projects=2), client(2, "Example Outdoor", projects=1), client(3, "Example Clinic", current=None)]
VERSIONS = {
    "c1": [version("v1", "2025", valid_from="2025-03-01"), version("v2", "2026", valid_from="2026-03-01"),
           version("v3", "2027", status="draft", valid_from=None, author="sam")],
    "c2": [version("v4", "1.0", valid_from="2026-09-15", author="alex"), version("v5", "2.0", valid_from="2026-12-01")],
    "c3": [],
}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.fixture(autouse=True)
def on_the_measured_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_today", lambda: "2026-10-11")


def mock_versions() -> dict[str, respx.Route]:
    return {key: respx.get(f"{BASE}/clients/{key}/versions").mock(return_value=httpx.Response(200, json=rows)) for key, rows in VERSIONS.items()}


@respx.mock
async def test_the_overview_counts_clients_with_a_version_and_projects(ctx: Context) -> None:
    route = respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=CLIENTS))
    data = await get_adapter("nexbrand").fetch("clients", CONFIG, {}, ctx)
    assert data.primary == {"label": "Clients", "value": 3}
    assert {row["label"]: row["value"] for row in data.secondary} == {"With a version": 2, "Projects": 3}
    assert data.metrics == {"clients": 3.0}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer nxb_example" and "nxb_" not in str(request.url)
    assert "origin" not in request.headers
    assert "#C23B2E" not in data.model_dump_json(), "the colours of a client's brand stay in nexbrand"


@respx.mock
async def test_the_versions_come_drafts_first_then_the_newest_day_with_a_link_to_the_client(ctx: Context) -> None:
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=CLIENTS))
    mock_versions()
    data = await get_adapter("nexbrand").fetch("versions", CONFIG, {"limit": 10}, ctx)
    assert [(item["title"], item["subtitle"]) for item in data.items] == [
        ("Example Bakery · 2027", "Draft · sam"),
        ("Example Outdoor · 2.0", "Scheduled · 2026-12-01 · robin"),
        ("Example Outdoor · 1.0", "Published · 2026-09-15 · alex"),
        ("Example Bakery · 2026", "Published · 2026-03-01 · robin"),
        ("Example Bakery · 2025", "Published · 2025-03-01 · robin"),
    ]
    assert [item["emphasis"] for item in data.items] == [True, False, False, False, False]
    assert data.items[0]["url"] == "http://nexbrand:8540/c/c1" and data.meta["notice"] == ""
    assert "Warmer red" not in data.model_dump_json(), "the note of a version is not for the board"
    limited = await get_adapter("nexbrand").fetch("versions", CONFIG, {"limit": 2}, ctx)
    assert len(limited.items) == 2


@respx.mock
async def test_one_client_can_be_picked_and_a_gone_one_is_said(ctx: Context) -> None:
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=CLIENTS))
    routes = mock_versions()
    data = await get_adapter("nexbrand").fetch("versions", CONFIG, {"client": "c2"}, ctx)
    assert {item["title"].split(" · ")[0] for item in data.items} == {"Example Outdoor"}
    assert routes["c2"].called and not routes["c1"].called and not routes["c3"].called
    with pytest.raises(AdapterError) as gone:
        await get_adapter("nexbrand").fetch("versions", CONFIG, {"client": "c9"}, ctx)
    assert gone.value.code == "no_client" and "no such client" in str(gone.value)


@respx.mock
async def test_only_the_first_twelve_clients_are_asked_about_and_the_card_says_so(ctx: Context) -> None:
    many = [client(number, f"Client {number:02d}") for number in range(1, 16)]
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=many))
    routes = {f"c{number}": respx.get(f"{BASE}/clients/c{number}/versions").mock(return_value=httpx.Response(200, json=[version(f"v{number}", "2026")])) for number in range(1, 16)}
    data = await get_adapter("nexbrand").fetch("versions", CONFIG, {"limit": 50}, ctx)
    assert sum(route.call_count for route in routes.values()) == module.LOOKED_AT == 12
    assert len(data.items) == 12
    assert data.meta["notice"] == "Only the first 12 of 15 clients are looked at."


@respx.mock
async def test_a_client_whose_versions_fail_does_not_take_the_card_down_but_all_failing_does(ctx: Context) -> None:
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=CLIENTS))
    respx.get(f"{BASE}/clients/c1/versions").mock(return_value=httpx.Response(500))
    respx.get(f"{BASE}/clients/c2/versions").mock(return_value=httpx.Response(200, json=VERSIONS["c2"]))
    respx.get(f"{BASE}/clients/c3/versions").mock(return_value=httpx.Response(200, json=[]))
    data = await get_adapter("nexbrand").fetch("versions", CONFIG, {}, ctx)
    assert {item["title"].split(" · ")[0] for item in data.items} == {"Example Outdoor"}

    respx.get(f"{BASE}/clients/c2/versions").mock(return_value=httpx.Response(500))
    respx.get(f"{BASE}/clients/c3/versions").mock(return_value=httpx.Response(500))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    with pytest.raises(AdapterError) as refused:
        await get_adapter("nexbrand").fetch("versions", CONFIG, {}, fresh)
    assert refused.value.code == "http_error"


@pytest.mark.parametrize(("status", "code", "ours", "words"), [
    (403, "origin_refused", "origin_refused", "Origin"),
    (401, "api_off", "api_off", "switched off"),
    (401, "token_invalid", "auth_failed", "does not know this token"),
    (429, "slow_down", "rate_limited", "fewer requests"),
    (500, "", "http_error", "HTTP 500"),
])
@respx.mock
async def test_each_refusal_says_what_to_do(status: int, code: str, ours: str, words: str, ctx: Context) -> None:
    body = {"detail": {"code": code, "message": "x"}} if code else {}
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(status, json=body))
    for kind in ("clients", "versions"):
        fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
        with pytest.raises(AdapterError) as refused:
            await get_adapter("nexbrand").fetch(kind, CONFIG, {}, fresh)
        assert refused.value.code == ours and words in str(refused.value)
        assert isinstance(refused.value, AuthFailed) is (code == "token_invalid")
        if code == "api_off":
            assert "Settings > Server > API" in refused.value.hint


@respx.mock
async def test_missing_fields_do_not_bring_the_card_down(ctx: Context) -> None:
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=[{"id": "c1"}, "junk", None, {"name": "No id", "projects": "none"}]))
    respx.get(f"{BASE}/clients/c1/versions").mock(return_value=httpx.Response(200, json=[{}, "junk", {"status": "draft"}]))
    overview = await get_adapter("nexbrand").fetch("clients", CONFIG, {}, ctx)
    assert overview.primary == {"label": "Clients", "value": 2} and {row["label"]: row["value"] for row in overview.secondary} == {"With a version": 0, "Projects": 0}
    listed = await get_adapter("nexbrand").fetch("versions", CONFIG, {}, ctx)
    assert [item["subtitle"] for item in listed.items] == ["Draft", "Published"]
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json={"not": "a list"}))
    fresh = Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})
    assert (await get_adapter("nexbrand").fetch("versions", CONFIG, {}, fresh)).items == []


@respx.mock
async def test_a_client_id_is_one_segment_of_the_path(ctx: Context) -> None:
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=[{"id": "../../me", "name": "Odd"}]))
    route = respx.get(url__regex=r".*/api/v1/.*/versions").mock(return_value=httpx.Response(200, json=[]))
    await get_adapter("nexbrand").fetch("versions", CONFIG, {}, ctx)
    assert route.calls.last.request.url.raw_path.endswith(b"/clients/..%2F..%2Fme/versions")


@respx.mock
async def test_the_connection_test_names_version_level_and_reach(ctx: Context) -> None:
    respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"name": "robin", "display_name": "Robin", "level": "read", "clients": 3, "version": "0.2.0"}))
    assert await get_adapter("nexbrand").test(CONFIG, ctx) == "nexbrand 0.2.0 answers; the token of robin (read) reads 3 client(s)."


@respx.mock
async def test_the_client_list_offers_names(ctx: Context) -> None:
    respx.get(f"{BASE}/clients").mock(return_value=httpx.Response(200, json=CLIENTS + ["junk", {"name": "no id"}]))
    assert await get_adapter("nexbrand").choices("client", CONFIG, ctx) == [("c1", "Example Bakery"), ("c2", "Example Outdoor"), ("c3", "Example Clinic")]


def test_every_demo_draws() -> None:
    adapter = get_adapter("nexbrand")
    for widget in adapter.widgets:
        for tick in (0, 40, 800):
            options = {field.name: field.default for field in widget.options}
            data = adapter.demo(widget.kind, options, tick)
            assert data.items or data.primary, widget.kind
    assert adapter.demo("versions", {"client": "demo-client-2"}, 0).items
    assert adapter.demo_choices("client") and adapter.demo_choices("other") == []
