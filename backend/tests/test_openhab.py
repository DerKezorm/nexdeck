"""openHAB, against the answers of openHAB 5.2.3 with the NTP binding installed (27.10.2026)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import CACHE_PREFIX, AdapterError, AuthFailed, Context, Unreachable

OH = "http://openhab.example.com:8080"
TOKEN = "oh.nexdeck.test-token-for-the-cards"
CONFIG = {"url": OH, "token": TOKEN}
ADAPTER = get_adapter("openhab")
FIXTURES = Path(__file__).parent / "fixtures"
NEEDS_TOKEN = {"error": {"message": "Authentication required", "http-code": 401}}
WRONG_TOKEN = {"error": {"message": "Invalid credentials", "http-code": 401}}


def recorded(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def fresh() -> Context:
    return Context(httpx.AsyncClient(), cache={})


def serve(*, things: Any = None, items: Any = None, rules: Any = None) -> dict[str, list[str]]:
    """A fake openHAB that writes down which token each request carried."""
    seen: dict[str, list[str]] = {"tokens": [], "item_query": []}

    def reply(answer: Any, remember: bool = False) -> Any:
        def inner(request: httpx.Request) -> httpx.Response:
            seen["tokens"].append(request.headers.get("X-OPENHAB-TOKEN", ""))
            if remember:
                seen["item_query"].append(request.url.query.decode())
            return httpx.Response(200, json=answer)
        return inner

    respx.get(f"{OH}/rest/").mock(side_effect=reply(recorded("openhab_root.json")))
    respx.get(f"{OH}/rest/things").mock(side_effect=reply(recorded("openhab_things.json") if things is None else things))
    respx.get(f"{OH}/rest/items").mock(side_effect=reply(recorded("openhab_items.json") if items is None else items, True))
    respx.get(f"{OH}/rest/rules").mock(side_effect=reply(recorded("openhab_rules.json") if rules is None else rules))
    return seen


@respx.mock
async def test_the_test_names_the_version_and_counts(ctx: Context) -> None:
    seen = serve()
    assert await ADAPTER.test(CONFIG, ctx) == "openHAB 5.2.3 answers with 3 things and 9 items."
    assert set(seen["tokens"]) == {TOKEN}


@respx.mock
async def test_without_a_token_items_are_read_and_the_test_says_what_is_missing(ctx: Context) -> None:
    seen = serve()
    said = await ADAPTER.test({"url": OH}, ctx)
    assert said == "openHAB 5.2.3 answers with 9 items. Add an API token to read things and rules."
    assert set(seen["tokens"]) == {""}


@respx.mock
async def test_the_overview_counts_things_and_rules(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    # One thing online, one offline, one switched off; two rules, one of which did not start.
    assert card.status == "bad" and card.primary == {"label": "Things online", "value": 1}
    assert [(row["label"], row["value"]) for row in card.secondary] == [
        ("Offline", 1), ("Items", 9), ("Rules", 2), ("Rules not running", 1)]
    assert card.metrics == {"things_online": 1.0, "things_offline": 0.0 + 1}


@respx.mock
async def test_a_disabled_thing_and_a_disabled_rule_are_a_choice_not_a_fault(ctx: Context) -> None:
    # ⚠️ Both are UNINITIALIZED, with the detail DISABLED.
    things = [thing for thing in recorded("openhab_things.json") if thing["UID"] != "ntp:ntp:broken"]
    rules = recorded("openhab_rules.json")
    rules[1]["status"]["statusDetail"] = "DISABLED"
    serve(things=things, rules=rules)
    card = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert card.status == "ok" and [row["label"] for row in card.secondary] == ["Offline", "Items", "Rules"]
    assert card.metrics["things_offline"] == 0.0


@respx.mock
async def test_a_rule_that_did_not_start_makes_the_overview_yellow_not_red(ctx: Context) -> None:
    serve(things=[thing for thing in recorded("openhab_things.json") if thing["UID"] == "ntp:ntp:local"])
    card = await ADAPTER.fetch("overview", CONFIG, {}, ctx)
    assert card.status == "warn" and card.metrics["things_offline"] == 0.0
    things = recorded("openhab_things.json")
    things[0]["statusInfo"] = {"status": "INITIALIZING", "statusDetail": "NONE"}
    serve(things=[things[0]], rules=[])
    assert (await ADAPTER.fetch("overview", CONFIG, {}, fresh())).status == "warn"


@respx.mock
async def test_things_needing_a_look_come_worst_first_with_the_reason(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("trouble", CONFIG, {}, ctx)
    assert card.status == "bad"
    assert [(row["title"], row["value"], row["status"]) for row in card.items] == [
        ("Broken time server", "Offline", "bad"), ("Disabled thing", "Disabled", "unknown")]
    assert card.items[0]["subtitle"].startswith("Communication error · The timeserver hostname nope.invalid is unknown")
    assert card.items[1]["subtitle"] == ""


@respx.mock
async def test_a_thing_that_did_not_start_is_red_and_one_starting_is_yellow(ctx: Context) -> None:
    things = recorded("openhab_things.json")
    things[0]["statusInfo"] = {"status": "UNINITIALIZED", "statusDetail": "HANDLER_MISSING_ERROR", "description": "x" * 300}
    things[1]["statusInfo"] = {"status": "INITIALIZING", "statusDetail": "NONE"}
    serve(things=things)
    card = await ADAPTER.fetch("trouble", CONFIG, {}, ctx)
    rows = {row["title"]: row for row in card.items}
    assert (rows["Time server"]["value"], rows["Time server"]["status"]) == ("Not started", "bad")
    assert (rows["Disabled thing"]["value"], rows["Disabled thing"]["status"]) == ("Starting", "warn")
    # The binding's words are cut, not poured over the card.
    assert rows["Time server"]["subtitle"].endswith("...") and len(rows["Time server"]["subtitle"]) < 150
    assert [row["status"] for row in card.items] == ["bad", "bad", "warn"]


@respx.mock
async def test_nothing_in_trouble_says_so(ctx: Context) -> None:
    serve(things=[thing for thing in recorded("openhab_things.json") if thing["UID"] == "ntp:ntp:local"])
    card = await ADAPTER.fetch("trouble", CONFIG, {}, ctx)
    assert card.status == "ok" and card.items == [] and card.meta["empty"] == "All things are online."


@respx.mock
async def test_items_read_in_words_with_a_switch_on_the_switches(ctx: Context) -> None:
    seen = serve()
    card = await ADAPTER.fetch("items", CONFIG, {}, ctx)
    rows = {row["id"]: row for row in card.items}
    # Groups are left out; labels lose their display pattern; the temperature keeps the unit it came with.
    assert "gLights" not in rows and len(rows) == 8
    assert (rows["Living_Temp"]["title"], rows["Living_Temp"]["value"]) == ("Living room temperature", "21.5 °C")
    assert rows["Bedroom_Dimmer"]["value"] == "35%" and rows["Front_Door"]["value"] == "Open"
    assert rows["Living_Light"]["value"] == "On" and rows["Status_Text"]["value"] == "All fine"
    # ⚠️ Never set is not off.
    assert rows["Unset_Switch"]["value"] == "?" and rows["Unset_Switch"]["status"] == "unknown"
    off = rows["Living_Light"]["actions"][0]
    assert (off.id, off.confirm, off.params) == ("off", True, {"item": "Living_Light"})
    assert rows["Kitchen_Light"]["actions"][0].id == "off" and rows["Unset_Switch"]["actions"][0].id == "on"
    assert rows["Front_Door"]["actions"] == [] and rows["Living_Temp"]["actions"] == []
    assert [row["title"] for row in card.items] == sorted((row["title"] for row in card.items), key=str.lower)
    # Only the fields the card reads are asked for.
    assert "fields=name" in seen["item_query"][0]


@respx.mock
async def test_a_group_shows_its_members_and_the_limit_cuts(ctx: Context) -> None:
    serve()
    card = await ADAPTER.fetch("items", CONFIG, {"group": "gLights"}, ctx)
    assert [row["title"] for row in card.items] == ["Kitchen light", "Living room light"]
    card = await ADAPTER.fetch("items", CONFIG, {"limit": 3}, fresh())
    assert len(card.items) == 3 and card.secondary == [{"label": "Items", "value": 8}]


@respx.mock
async def test_a_read_only_item_gets_no_switch(ctx: Context) -> None:
    items = recorded("openhab_items.json")
    for item in items:
        if item["name"] == "Living_Light":
            item["editable"] = False
    serve(items=items)
    card = await ADAPTER.fetch("items", CONFIG, {}, ctx)
    assert next(row for row in card.items if row["id"] == "Living_Light")["actions"] == []


@respx.mock
async def test_one_item_as_a_number_with_its_history(ctx: Context) -> None:
    respx.get(f"{OH}/rest/items/Power_Now").mock(return_value=httpx.Response(200, json=recorded("openhab_item_power.json")))
    card = await ADAPTER.fetch("item", CONFIG, {"item": "Power_Now"}, ctx)
    assert card.primary == {"label": "Power", "value": 412.0, "unit": "W"}
    assert card.metrics == {"value": 412.0} and card.actions == []
    assert [row["label"] for row in card.secondary] == ["Changed"] and card.secondary[0]["value"]


@respx.mock
async def test_one_item_as_a_switch_or_not_set(ctx: Context) -> None:
    respx.get(f"{OH}/rest/items/Living_Light").mock(return_value=httpx.Response(200, json=recorded("openhab_item_switch.json")))
    card = await ADAPTER.fetch("item", CONFIG, {"item": "Living_Light"}, ctx)
    assert card.primary == {"label": "Living room light", "value": "On"} and card.metrics == {}
    assert [(action.id, action.confirm) for action in card.actions] == [("off", True)]
    respx.get(f"{OH}/rest/items/Unset_Switch").mock(return_value=httpx.Response(200, json=recorded("openhab_item_unset.json")))
    card = await ADAPTER.fetch("item", CONFIG, {"item": "Unset_Switch"}, fresh())
    assert card.status == "unknown" and card.primary["value"] == "?" and card.metrics == {}


@respx.mock
async def test_a_missing_item_and_a_bad_name_are_said(ctx: Context) -> None:
    respx.get(f"{OH}/rest/items/Gone").mock(return_value=httpx.Response(404, json={"error": {"message": "Item Gone does not exist!", "http-code": 404}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("item", CONFIG, {"item": "Gone"}, ctx)
    assert caught.value.code == "no_item"
    # ⚠️ A name goes into the address; nothing but a name gets there.
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("item", CONFIG, {"item": "../things"}, fresh())
    assert caught.value.code == "bad_param"
    with pytest.raises(AdapterError):
        await ADAPTER.fetch("item", CONFIG, {}, fresh())


@respx.mock
async def test_the_choices_are_the_items_that_are_not_groups(ctx: Context) -> None:
    serve()
    choices = await ADAPTER.choices("item", CONFIG, ctx)
    assert ("Power_Now", "Power (Power_Now)") in choices and not any(value == "gLights" for value, _ in choices)
    assert choices == sorted(choices, key=lambda pair: pair[1].lower())


@respx.mock
async def test_the_switch_posts_a_command_as_plain_text_and_forgets_what_it_knew(ctx: Context) -> None:
    serve()
    route = respx.post(f"{OH}/rest/items/Kitchen_Light").mock(return_value=httpx.Response(200))
    await ADAPTER.fetch("items", CONFIG, {}, ctx)
    assert [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    assert await ADAPTER.action("items", "on", {"item": "Kitchen_Light"}, CONFIG, {}, ctx) == "Switched on."
    request = route.calls[0].request
    assert request.content == b"ON" and request.headers["Content-Type"] == "text/plain" and request.headers["X-OPENHAB-TOKEN"] == TOKEN
    assert not [key for key in ctx.cache if key.startswith(CACHE_PREFIX)]
    route.mock(return_value=httpx.Response(200))
    assert await ADAPTER.action("item", "off", {"item": "Kitchen_Light"}, CONFIG, {}, fresh()) == "Switched off."
    assert route.calls[1].request.content == b"OFF"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("item", "toggle", {"item": "Kitchen_Light"}, CONFIG, {}, ctx)
    assert caught.value.code == "no_such_action"
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.action("item", "on", {"item": "a/b"}, CONFIG, {}, ctx)
    assert caught.value.code == "bad_param"


@respx.mock
async def test_no_token_wrong_token_and_a_token_without_rights_are_told_apart(ctx: Context) -> None:
    # ⚠️ The first two are both 401; the text is the only difference.
    respx.get(f"{OH}/rest/things").mock(return_value=httpx.Response(401, json=NEEDS_TOKEN))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("trouble", {"url": OH}, {}, ctx)
    assert caught.value.message == "This needs an API token." and "API Tokens" in caught.value.hint
    respx.get(f"{OH}/rest/things").mock(return_value=httpx.Response(401, json=WRONG_TOKEN))
    with pytest.raises(AuthFailed) as caught:
        await ADAPTER.fetch("trouble", CONFIG, {}, fresh())
    assert caught.value.message == "openHAB does not know this API token."
    respx.get(f"{OH}/rest/things").mock(return_value=httpx.Response(403, json={"error": {"message": "Forbidden", "http-code": 403}}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("trouble", CONFIG, {}, fresh())
    assert caught.value.code == "forbidden" and not isinstance(caught.value, AuthFailed)


@respx.mock
async def test_the_test_fails_on_a_wrong_token_and_not_on_the_first_card(ctx: Context) -> None:
    serve()
    respx.get(f"{OH}/rest/things").mock(return_value=httpx.Response(401, json=WRONG_TOKEN))
    with pytest.raises(AuthFailed):
        await ADAPTER.test(CONFIG, ctx)


@respx.mock
async def test_unreachable_and_not_openhab(ctx: Context) -> None:
    respx.get(f"{OH}/rest/items").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unreachable):
        await ADAPTER.fetch("items", CONFIG, {}, ctx)
    respx.get(f"{OH}/rest/items").mock(return_value=httpx.Response(200, text="<html>a router</html>"))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("items", CONFIG, {}, fresh())
    assert caught.value.code == "not_openhab"
    respx.get(f"{OH}/rest/items").mock(return_value=httpx.Response(200, json={"something": "else"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("items", CONFIG, {}, fresh())
    assert caught.value.code == "not_openhab"
    respx.get(f"{OH}/rest/").mock(return_value=httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.test(CONFIG, fresh())
    assert caught.value.code == "not_openhab"
    respx.get(f"{OH}/rest/items").mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(AdapterError) as caught:
        await ADAPTER.fetch("items", CONFIG, {}, fresh())
    assert caught.value.code == "http_error"


@respx.mock
async def test_ignoring_tls_errors_goes_through_the_relaxed_client(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[int] = []
    relaxed = httpx.AsyncClient()
    monkeypatch.setattr("app.adapters.base._relaxed_client", lambda: (used.append(1), relaxed)[1])
    serve()
    await ADAPTER.fetch("items", {**CONFIG, "insecure": True}, {}, ctx)
    assert used
    used.clear()
    await ADAPTER.fetch("items", CONFIG, {}, fresh())
    assert not used


def test_numbers_and_words_of_an_item() -> None:
    from app.adapters.openhab import _number, _show

    assert _show({"type": "Number:Length", "state": "1.234567891234 m"}) == "1.23 m"
    assert _show({"type": "Number", "state": "7.0"}) == "7"
    assert _show({"type": "Rollershutter", "state": "100"}) == "100%"
    assert _show({"type": "Player", "state": "PLAY"}) == "Playing"
    assert _show({"type": "String", "state": "x" * 90}).endswith("...")
    assert _show({"type": "Switch", "state": "UNDEF"}) == "?"
    assert _number({"type": "Number:Power", "state": "-3.5 kW"}) == (-3.5, "kW")
    assert _number({"type": "Dimmer", "state": "40"}) == (40.0, "%")
    assert _number({"type": "String", "state": "12"}) is None and _number({"type": "Switch", "state": "ON"}) is None
    assert copy.deepcopy(_number({"type": "Number", "state": "NULL"})) is None


@pytest.mark.parametrize("kind", [widget.kind for widget in ADAPTER.widgets])
def test_demo_has_every_card(kind: str) -> None:
    for tick in (0, 5, 50, 110):
        card = ADAPTER.demo(kind, {"item": "Power_Now"}, tick)
        assert card.primary or card.items
        assert card.secondary
