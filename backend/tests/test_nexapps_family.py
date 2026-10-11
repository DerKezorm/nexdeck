"""The four apps of the family answer alike, so a card must tell them apart.

nexcanvas, nexbrand, nexpaper and nexdiary answer ``/me`` with the same few
fields, and nexcanvas and nexdiary hand out tokens with the same prefix. Run
against real instances on 11.10.2026, a nexbrand card at the address of
nexcanvas said "nexbrand 0.4.1 answers", and a nexdiary card with a nexcanvas
token drew a streak of nought. Each now says that another app answers.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context, outbound_client

BASE = "http://app.example.com"
CONFIG = {"url": BASE, "api_key": "nxa_example"}

#: What each app's ``/me`` answers, as its ``routers/v1.py`` has it.
ME = {
    "nexcanvas": {"name": "alex", "display_name": "Alex", "level": "read", "spaces": ["Home"], "version": "0.4.1"},
    "nexbrand": {"name": "alex", "display_name": "Alex", "level": "read", "clients": 2, "version": "0.2.0"},
    "nexpaper": {"name": "alex", "display_name": "Alex", "scope": "read", "version": "1.1.0"},
    "nexdiary": {"name": "alex", "display_name": "Alex", "level": "read", "version": "0.8.0"},
}
#: The card routes of the three whose cards read ``/dashboard``, by app.
DASHBOARD = {
    "nexcanvas": ("boards", {"spaces": 1, "boards": 3, "changed_today": 0, "changed_week": 1, "recent": []}),
    "nexpaper": ("inbox", {"version": "1.1.0", "inbox": 2, "inbox_oldest": [], "inbox_oldest_at": None, "filed": 5,
                           "total": 7, "added_week": 1, "processing": 0, "deadlines": []}),
    "nexdiary": ("diary", {"version": "0.8.0", "today_written": True, "streak": 4, "streak_unit": "days",
                           "entries_month": 3, "notes_month": 9, "next_capsule": None, "next_capsule_days": None}),
}


@pytest.fixture
def ctx() -> Context:
    return Context(outbound_client(guard=False), integration_id=1, widget_id=1, cache={})


@pytest.mark.parametrize("adapter", list(ME))
@pytest.mark.parametrize("answering", list(ME))
@respx.mock
async def test_the_connection_test_tells_the_app_that_answers(adapter: str, answering: str, ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/me").mock(return_value=httpx.Response(200, json=ME[answering]))
    if adapter == answering:
        assert (await get_adapter(adapter).test(CONFIG, ctx)).startswith(f"{adapter} ")
        return
    with pytest.raises(AdapterError) as refused:
        await get_adapter(adapter).test(CONFIG, ctx)
    assert refused.value.code == "wrong_app" and f"not as {adapter}" in str(refused.value)


@pytest.mark.parametrize("adapter", list(DASHBOARD))
@pytest.mark.parametrize("answering", list(DASHBOARD))
@respx.mock
async def test_a_card_says_another_app_answers_instead_of_drawing_noughts(adapter: str, answering: str, ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/dashboard").mock(return_value=httpx.Response(200, json=DASHBOARD[answering][1]))
    card = DASHBOARD[adapter][0]
    if adapter == answering:
        assert (await get_adapter(adapter).fetch(card, CONFIG, {}, ctx)).error is None
        return
    with pytest.raises(AdapterError) as refused:
        await get_adapter(adapter).fetch(card, CONFIG, {}, ctx)
    assert refused.value.code == "wrong_app"


@pytest.mark.parametrize("adapter", list(ME))
@respx.mock
async def test_an_address_with_a_path_is_told_to_drop_it(adapter: str, ctx: Context) -> None:
    respx.get(f"{BASE}/api/v1/api/v1/me").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    with pytest.raises(AdapterError) as refused:
        await get_adapter(adapter).test({**CONFIG, "url": f"{BASE}/api/v1"}, ctx)
    assert "without a path" in (refused.value.hint or ""), refused.value.hint
