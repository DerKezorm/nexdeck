"""Portainer, and the trap it used to set.

⚠️ The connection test used to say "Portainer answers" and list the
environments it had found, without ever looking at the number in the field.
On a Portainer whose environment is not number 1 the test went green and every
card went red a moment later. A test that passes where a card fails is worse
than no test, so each case below is one the test now has to catch.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

URL = "https://portainer:9443"
CONFIG = {"url": URL, "api_key": "key", "insecure": True}
CONTAINERS = [
    {"Id": "abc123def4567", "Names": ["/pihole"], "State": "running", "Status": "Up 3 days", "Image": "pihole/pihole"},
    {"Id": "def456abc7890", "Names": ["/whoami"], "State": "exited", "Status": "Exited (0)", "Image": "traefik/whoami"},
]


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def _environments(*pairs: tuple[int, str]) -> None:
    respx.get(f"{URL}/api/endpoints").mock(
        return_value=httpx.Response(200, json=[{"Id": number, "Name": name} for number, name in pairs])
    )


def _containers(endpoint: int) -> None:
    respx.get(f"{URL}/api/endpoints/{endpoint}/docker/containers/json").mock(
        return_value=httpx.Response(200, json=CONTAINERS)
    )


@respx.mock
async def test_one_environment_needs_no_number(ctx: Context) -> None:
    """The ordinary installation: nothing to type, whatever the number is."""
    _environments((3, "local"))
    _containers(3)
    portainer = get_adapter("portainer")

    said = await portainer.test(CONFIG, ctx)
    assert "3" in said and "local" in said

    card = await portainer.fetch("summary", CONFIG, {}, ctx)
    assert card.primary == {"label": "Running", "value": 1, "unit": "/ 2"}


@respx.mock
async def test_the_number_is_not_assumed_to_be_one(ctx: Context) -> None:
    """⚠️ The whole bug. A single environment numbered 3 used to be asked for
    as environment 1, because that was the default nobody changed."""
    _environments((3, "local"))
    _containers(3)
    await get_adapter("portainer").fetch("containers", CONFIG, {}, ctx)
    assert respx.calls.last.request.url.path == "/api/endpoints/3/docker/containers/json"


@respx.mock
async def test_a_named_environment_is_used(ctx: Context) -> None:
    _environments((1, "local"), (7, "shed"))
    _containers(7)
    card = await get_adapter("portainer").fetch("summary", {**CONFIG, "endpoint_id": "7"}, {}, ctx)
    assert card.primary["value"] == 1


@respx.mock
async def test_several_environments_ask_for_one_and_name_them(ctx: Context) -> None:
    _environments((1, "local"), (7, "shed"))
    with pytest.raises(AdapterError) as raised:
        await get_adapter("portainer").test(CONFIG, ctx)
    assert raised.value.code == "which_environment"
    assert "1 (local)" in raised.value.hint and "7 (shed)" in raised.value.hint


@respx.mock
async def test_a_number_that_does_not_exist_fails_the_test(ctx: Context) -> None:
    """⚠️ Where a card would fail, the test has to fail too."""
    _environments((3, "local"))
    with pytest.raises(AdapterError) as raised:
        await get_adapter("portainer").test({**CONFIG, "endpoint_id": "1"}, ctx)
    assert raised.value.code == "no_such_endpoint"
    assert "3 (local)" in raised.value.hint


@respx.mock
async def test_the_card_fails_the_same_way_as_the_test(ctx: Context) -> None:
    _environments((3, "local"))
    with pytest.raises(AdapterError) as raised:
        await get_adapter("portainer").fetch("summary", {**CONFIG, "endpoint_id": "1"}, {}, ctx)
    assert raised.value.code == "no_such_endpoint"


@respx.mock
async def test_a_portainer_without_environments_says_so(ctx: Context) -> None:
    _environments()
    with pytest.raises(AdapterError) as raised:
        await get_adapter("portainer").test(CONFIG, ctx)
    assert raised.value.code == "no_environments"


@respx.mock
async def test_nonsense_in_the_field_is_treated_as_empty(ctx: Context) -> None:
    """Somebody types the name instead of the number. One environment, so it
    still works rather than failing on a typo."""
    _environments((3, "local"))
    _containers(3)
    card = await get_adapter("portainer").fetch("summary", {**CONFIG, "endpoint_id": "local"}, {}, ctx)
    assert card.primary["value"] == 1


@respx.mock
async def test_an_action_goes_to_the_resolved_environment(ctx: Context) -> None:
    _environments((3, "local"))
    route = respx.post(f"{URL}/api/endpoints/3/docker/containers/abc123def4567/restart").mock(
        return_value=httpx.Response(204)
    )
    await get_adapter("portainer").action("containers", "restart", {"id": "abc123def4567"}, CONFIG, {}, ctx)
    assert route.called


@respx.mock
async def test_the_field_no_longer_defaults_to_one() -> None:
    """A default that is right on most installations and silently wrong on the
    rest is worse than no default."""
    field = next(f for f in get_adapter("portainer").fields if f.name == "endpoint_id")
    assert field.default == ""
    assert field.required is False
