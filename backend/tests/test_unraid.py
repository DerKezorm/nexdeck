"""Unraid: one GraphQL request per part, so one refusal cannot empty every card.

The five top-level fields are non-null in Unraid's schema. An error in one of
them nulls the whole answer, ``data: null``, which is what the fake server
below does, exactly as a GraphQL server would for a single combined query.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import AdapterError, Context

URL = "https://tower.example.com"
CONFIG = {"url": URL, "api_key": "key"}
ANSWERS = {
    "info": {"os": {"uptime": "2026-09-01T08:00:00.000Z"}, "cpu": {"brand": "Example CPU"}},
    "metrics": {"cpu": {"percentTotal": 12.34}, "memory": {"percentTotal": 41.0, "used": "1", "total": "2"}},
    "array": {
        "state": "STARTED",
        "capacity": {"kilobytes": {"used": "750", "total": "1000", "free": "250"}},
        "parities": [{"name": "parity", "status": "DISK_OK", "temp": 31}],
        "disks": [{"name": "disk1", "status": "DISK_OK", "temp": 35, "fsSize": 1000, "fsUsed": 880}],
    },
    "docker": {"containers": [{"names": ["/plex"], "state": "RUNNING"}, {"names": ["/old"], "state": "EXITED"}]},
    "vms": {"domain": [{"name": "Home Assistant", "state": "RUNNING"}, {"name": "Windows", "state": "SHUTOFF"}]},
}


@pytest.fixture
def ctx() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


def serve(refused: dict[str, str] | None = None) -> list[str]:
    """Answer each query like Unraid would; returns the parts asked for, in order."""
    refused = refused or {}
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "key"
        query = json.loads(request.content)["query"]
        parts = [part for part in ANSWERS if re.search(rf"(?<![a-z]){part}\s*\{{", query)]
        asked.extend(parts)
        errors = [{"message": refused[part], "path": [part]} for part in parts if part in refused]
        if errors:
            # A non-null field failed: GraphQL nulls everything up to the root.
            return httpx.Response(200, json={"data": None, "errors": errors})
        return httpx.Response(200, json={"data": {part: ANSWERS[part] for part in parts}})

    respx.post(f"{URL}/graphql").mock(side_effect=answer)
    return asked


@respx.mock
async def test_every_card_reads_what_it_shows(ctx: Context) -> None:
    asked = serve()
    unraid = get_adapter("unraid")

    system = await unraid.fetch("system", CONFIG, {}, ctx)
    assert sorted(asked) == ["array", "info", "metrics"], "the system card has no business with Docker or VMs"
    assert system.primary == {"label": "CPU", "value": 12.3, "unit": "%"}
    assert [entry["value"] for entry in system.secondary] == [41.0, 75.0, "2026-09-01"]
    assert system.status == "ok"

    disks = await unraid.fetch("array", CONFIG, {}, ctx)
    assert [(item["title"], item.get("progress")) for item in disks.items] == [("parity", None), ("disk1", 88.0)]

    guests = await unraid.fetch("guests", CONFIG, {}, ctx)
    assert guests.primary == {"label": "Containers running", "value": 1, "unit": "/ 2"}
    assert guests.secondary == [{"label": "VMs", "value": "1 / 2"}]


@respx.mock
async def test_a_switched_off_vm_service_empties_no_card(ctx: Context) -> None:
    """Issue #3 is a candidate: one refused part used to null the whole answer,
    and every card of the connection showed the same error."""
    serve(refused={"vms": "VMs are not available"})
    unraid = get_adapter("unraid")

    system = await unraid.fetch("system", CONFIG, {}, ctx)
    assert system.primary == {"label": "CPU", "value": 12.3, "unit": "%"}
    disks = await unraid.fetch("array", CONFIG, {}, ctx)
    assert len(disks.items) == 2
    guests = await unraid.fetch("guests", CONFIG, {}, ctx)
    assert guests.primary == {"label": "Containers running", "value": 1, "unit": "/ 2"}
    assert guests.secondary == [{"label": "VMs", "value": "?"}]


@respx.mock
async def test_a_card_without_its_own_part_says_why(ctx: Context) -> None:
    serve(refused={"docker": "Forbidden resource"})
    with pytest.raises(AdapterError) as refused:
        await get_adapter("unraid").fetch("guests", CONFIG, {}, ctx)
    assert refused.value.code == "graphql_error"
    assert "docker" in refused.value.message and "Forbidden resource" in refused.value.message


@respx.mock
async def test_the_system_card_marks_a_missing_array_instead_of_failing(ctx: Context) -> None:
    serve(refused={"array": "Forbidden resource", "info": "Forbidden resource"})
    system = await get_adapter("unraid").fetch("system", CONFIG, {}, ctx)
    assert system.primary == {"label": "CPU", "value": 12.3, "unit": "%"}
    assert [entry["value"] for entry in system.secondary] == [41.0, "?", "?"]


@respx.mock
async def test_the_connection_test_names_what_it_cannot_read(ctx: Context) -> None:
    serve(refused={"vms": "VMs are not available"})
    text = await get_adapter("unraid").test(CONFIG, ctx)
    assert text.startswith("Unraid answers, array is STARTED.")
    assert "vms" in text and "VMs are not available" in text


@respx.mock
async def test_the_connection_test_fails_when_nothing_is_readable(ctx: Context) -> None:
    serve(refused={part: "Invalid API key" for part in ANSWERS})
    with pytest.raises(AdapterError) as refused:
        await get_adapter("unraid").test(CONFIG, ctx)
    assert "Invalid API key" in refused.value.message


@respx.mock
async def test_parts_are_shared_between_cards_for_a_few_seconds(ctx: Context) -> None:
    asked = serve()
    unraid = get_adapter("unraid")
    await unraid.fetch("system", CONFIG, {}, ctx)
    await unraid.fetch("array", CONFIG, {}, ctx)
    assert asked.count("array") == 1
