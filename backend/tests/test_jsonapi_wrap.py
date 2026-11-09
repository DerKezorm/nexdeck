"""'Wrap long text' on the JSON API cards (#63).

The card only says it wants long text broken onto further lines; drawing it
is the frontend's business. Off by default, so every card already on a board
reads exactly as it did.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context

API = "https://api.example.com"
CONFIG = {"url": API}
ANSWER = {"status": {"message": "The nightly backup finished with three warnings about files that changed while read"},
          "jobs": [{"name": "A job whose name is far too long for one line on a card two columns wide", "state": "done"}]}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def test_both_cards_offer_the_switch_and_it_starts_off() -> None:
    adapter = get_adapter("jsonapi")
    for widget in adapter.widgets:
        wrap = next((field for field in widget.options if field.name == "wrap"), None)
        assert wrap is not None, widget.kind
        assert wrap.type == "bool" and wrap.default is False


@respx.mock
@pytest.mark.parametrize("wrap", [True, False])
async def test_the_value_card_says_whether_to_wrap(ctx: Context, wrap: bool) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=ANSWER))
    data = await get_adapter("jsonapi").fetch("value", CONFIG, {"value_path": "status.message", "wrap": wrap}, ctx)
    assert data.primary["value"] == ANSWER["status"]["message"], "the text itself is never cut by the server"
    assert data.meta.get("wrap", False) is wrap


@respx.mock
@pytest.mark.parametrize("wrap", [True, False])
async def test_the_list_card_says_whether_to_wrap(ctx: Context, wrap: bool) -> None:
    respx.get(API).mock(return_value=httpx.Response(200, json=ANSWER))
    data = await get_adapter("jsonapi").fetch("list", CONFIG, {"items_path": "jobs", "title_path": "name", "wrap": wrap}, ctx)
    assert data.items[0]["title"] == ANSWER["jobs"][0]["name"]
    assert data.meta.get("wrap", False) is wrap


def test_the_demo_follows_the_switch() -> None:
    adapter = get_adapter("jsonapi")
    assert adapter.demo("value", {"wrap": True}, tick=1).meta == {"wrap": True}
    assert adapter.demo("list", {"wrap": True}, tick=1).meta == {"wrap": True}
    assert adapter.demo("list", {}, tick=1).meta == {}
