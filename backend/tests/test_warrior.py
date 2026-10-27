"""ArchiveTeam Warrior, against the frames of a live warrior (seesaw-kit 0.10.3) without a network (27.10.2026).

A warrior at work was not measured; its frames below are written after the source of seesaw-kit.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, AuthFailed, Context, Unreachable
from app.adapters.warrior import WarriorAdapter

FIXTURES = Path(__file__).parent / "fixtures"
W = "http://warrior.example.com:8001"
INVALID = (FIXTURES / "warrior_frame_invalid_settings.txt").read_text(encoding="utf-8").strip()
NO_PROJECT = (FIXTURES / "warrior_frame_no_project.txt").read_text(encoding="utf-8").strip()
TICK = 'a["{\\"event_name\\": \\"timestamp\\", \\"message\\": {\\"timestamp\\": 1793138433.4}}"]'


def frame(*events: tuple[str, object]) -> str:
    return "a" + json.dumps([json.dumps({"event_name": name, "message": message}) for name, message in events])


WORKING = frame(("instance_id", "8-0.9"), ("warrior.status", {"status": "RUNNING_PROJECT"}),
                ("project.refresh", {"project": {"title": "URLs", "project_id": 1}, "status": "running",
                                     "items": [{"id": 1, "name": "Item a", "status": "running"}, {"id": 2, "name": "Item b", "status": "running"},
                                               {"id": 3, "name": "Item c", "status": "completed"}]}))
BANDWIDTH = frame(("bandwidth", {"received": 4_800_000_000, "sent": 900_000_000, "receiving": 524_288.0, "sending": 20_480.0}))


def fresh(number: int = 1) -> Context:
    return Context(httpx.AsyncClient(), integration_id=number, widget_id=1, cache={})


def polls(*answers: str) -> respx.Route:
    return respx.post(url__regex=rf"{W}/000/[0-9a-f]+/xhr").mock(side_effect=[httpx.Response(200, text=text + "\n") for text in ("o", *answers)])


@respx.mock
async def test_a_warrior_that_needs_a_nickname() -> None:
    """⚠️ Measured: a fresh warrior says INVALID_SETTINGS until it is given a nickname."""
    route = polls(INVALID, TICK)
    data = await get_adapter("warrior").fetch("status", {"url": W}, {}, fresh())
    assert data.status == "warn" and data.primary == {"label": "State", "value": "Needs a nickname", "unit": ""}
    assert data.secondary == [] and data.metrics == {}
    assert route.call_count == 3
    # One session: every poll goes to the same address.
    assert len({call.request.url.path for call in route.calls}) == 1 and route.calls.last.request.content == b""


@respx.mock
async def test_a_warrior_without_a_project() -> None:
    polls(NO_PROJECT, TICK)
    data = await get_adapter("warrior").fetch("status", {"url": W}, {}, fresh())
    assert data.primary["value"] == "No project" and data.status == "warn"


@respx.mock
async def test_a_warrior_at_work_shows_project_items_and_traffic() -> None:
    polls(WORKING, BANDWIDTH)
    data = await get_adapter("warrior").fetch("status", {"url": W}, {}, fresh())
    assert data.status == "ok" and data.primary["value"] == "Working"
    # Two items run, the third is done and is not in hand any more.
    assert data.secondary == [{"label": "Project", "value": "URLs"}, {"label": "Items in hand", "value": 2},
                              {"label": "Receiving", "value": "512.0 KB/s"}, {"label": "Sending", "value": "20.0 KB/s"}]
    assert data.metrics == {"items": 2.0, "receiving": 524288.0, "sending": 20480.0}


@respx.mock
async def test_the_connection_test_says_what_the_warrior_is_doing() -> None:
    polls(WORKING, TICK)
    assert await get_adapter("warrior").test({"url": W}, fresh()) == "The warrior answers: Working."


def test_other_states_have_words_and_a_colour() -> None:
    for code, words in (("STOPPING_PROJECT", "Stopping"), ("UNINITIALIZED", "Not connected to the tracker"), ("SHUTTING_DOWN", "Shutting down")):
        data = WarriorAdapter._card({"warrior.status": {"status": code}})
        assert data.primary["value"] == words and data.status == "warn", code
    assert WarriorAdapter._card({"warrior.status": {"status": "SOMETHING_NEW"}}).primary["value"] == "Something new"


@respx.mock
async def test_credentials_are_sent_and_refused_ones_say_so() -> None:
    route = polls(INVALID, TICK)
    await get_adapter("warrior").fetch("status", {"url": W, "username": "warrior", "password": "made-up"}, {}, fresh(1))
    assert route.calls.last.request.headers["Authorization"].startswith("Basic ")
    respx.post(url__regex=rf"{W}/000/[0-9a-f]+/xhr").mock(return_value=httpx.Response(401, text="Unauthorized"))
    with pytest.raises(AuthFailed):
        await get_adapter("warrior").fetch("status", {"url": W}, {}, fresh(2))


@respx.mock
async def test_not_a_warrior_and_unreachable() -> None:
    adapter = get_adapter("warrior")
    respx.post(url__regex=rf"{W}/000/[0-9a-f]+/xhr").mock(return_value=httpx.Response(200, text="<html>hello</html>"))
    with pytest.raises(AdapterError) as other:
        await adapter.fetch("status", {"url": W}, {}, fresh(1))
    assert other.value.code == "not_a_warrior"
    respx.post(url__regex=rf"{W}/000/[0-9a-f]+/xhr").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(AdapterError) as missing:
        await adapter.fetch("status", {"url": W}, {}, fresh(2))
    assert missing.value.code == "http_error"
    polls(TICK, TICK)
    with pytest.raises(AdapterError) as silent:
        await adapter.fetch("status", {"url": W}, {}, fresh(3))
    assert silent.value.code == "no_status"
    respx.post(url__regex=rf"{W}/000/[0-9a-f]+/xhr").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await adapter.fetch("status", {"url": W}, {}, fresh(4))


def test_the_password_is_a_secret_and_the_card_has_demo_data_that_moves() -> None:
    adapter = get_adapter("warrior")
    assert {field.name for field in adapter.fields if field.secret} == {"password"} and adapter.beta is True
    assert adapter.demo("status", {}, 0).status == "ok"
    assert len({adapter.demo("status", {}, tick).metrics["receiving"] for tick in range(0, 300, 10)}) > 1
