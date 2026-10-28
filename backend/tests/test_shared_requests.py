"""Cards of one connection that ask for the same address at the same time share one request.

Measured with a pretend Proxmox: the kept answer only helped once an answer was there, so four cards on one
connection sent ``/nodes`` four times whenever the service was slower than the cards' start was spread.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from app.adapters.base import FLIGHT_PREFIX, AuthFailed, Context, Unreachable

URL = "http://service.example.com/api/nodes"


def _ctx(cache: dict) -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, cache=cache)


class Held:
    """A service that answers only when told to, and counts what it was asked."""

    def __init__(self, status: int = 200) -> None:
        self.go = asyncio.Event()
        self.asked = 0
        self.status = status

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked += 1
        await self.go.wait()
        return httpx.Response(self.status, json={"n": self.asked})


async def _until_asked(service: Held, times: int = 1) -> None:
    for _ in range(200):
        if service.asked >= times:
            return
        await asyncio.sleep(0.005)


@respx.mock
async def test_cards_asking_at_the_same_time_share_one_request() -> None:
    service = Held()
    respx.get(URL).mock(side_effect=service)
    cache: dict = {}
    calls = [asyncio.create_task(_ctx(cache).request("GET", URL, cache_seconds=5)) for _ in range(4)]
    await _until_asked(service)
    await asyncio.sleep(0.02)
    service.go.set()
    answers = await asyncio.gather(*calls)
    assert service.asked == 1
    assert {answer.json()["n"] for answer in answers} == {1}
    assert not [name for name in cache if name.startswith(FLIGHT_PREFIX)]


@respx.mock
async def test_a_card_that_stops_waiting_does_not_take_the_answer_from_the_others() -> None:
    service = Held()
    respx.get(URL).mock(side_effect=service)
    cache: dict = {}
    first = asyncio.create_task(_ctx(cache).request("GET", URL, cache_seconds=5))
    await _until_asked(service)
    second = asyncio.create_task(_ctx(cache).request("GET", URL, cache_seconds=5))
    await asyncio.sleep(0.02)
    first.cancel()
    service.go.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert (await second).json() == {"n": 1}
    assert service.asked == 1


@respx.mock
async def test_a_failure_reaches_everybody_waiting_and_the_next_card_asks_again() -> None:
    respx.get(URL).mock(side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={"n": 2})])
    cache: dict = {}
    results = await asyncio.gather(*(_ctx(cache).request("GET", URL, cache_seconds=5) for _ in range(3)),
                                   return_exceptions=True)
    assert all(isinstance(result, Unreachable) for result in results)
    assert respx.calls.call_count == 1
    assert (await _ctx(cache).request("GET", URL, cache_seconds=5)).json() == {"n": 2}
    assert respx.calls.call_count == 2


@respx.mock
async def test_a_refusal_is_shared_but_each_card_reads_it_its_own_way_and_it_is_not_kept() -> None:
    service = Held(status=401)
    respx.get(URL).mock(side_effect=service)
    cache: dict = {}
    strict = asyncio.create_task(_ctx(cache).request("GET", URL, cache_seconds=5))
    await _until_asked(service)
    lenient = asyncio.create_task(_ctx(cache).request("GET", URL, cache_seconds=5, auth_errors=False))
    await asyncio.sleep(0.02)
    service.go.set()
    with pytest.raises(AuthFailed):
        await strict
    assert (await lenient).status_code == 401
    assert service.asked == 1
    with pytest.raises(AuthFailed):
        await _ctx(cache).request("GET", URL, cache_seconds=5)
    assert service.asked == 2


@respx.mock
async def test_an_answer_asked_before_a_write_is_not_kept_after_it() -> None:
    service = Held()
    respx.get(URL).mock(side_effect=service)
    cache: dict = {}
    before = asyncio.create_task(_ctx(cache).request("GET", URL, cache_seconds=60))
    await _until_asked(service)
    _ctx(cache).forget_answers()
    service.go.set()
    assert (await before).json() == {"n": 1}
    assert (await _ctx(cache).request("GET", URL, cache_seconds=60)).json() == {"n": 2}


@respx.mock
async def test_stopping_the_server_lets_go_of_a_shared_request_nobody_waits_for() -> None:
    from app.services.collector import Collector

    service = Held()
    respx.get(URL).mock(side_effect=service)
    collector = Collector()
    cache = collector._caches.setdefault(1, {})
    waiting = asyncio.create_task(_ctx(cache).request("GET", URL, cache_seconds=5))
    await _until_asked(service)
    waiting.cancel()
    flight = next(value for name, value in cache.items() if name.startswith(FLIGHT_PREFIX))
    await collector.stop()
    await asyncio.sleep(0)
    assert flight.cancelled()


@pytest.mark.parametrize("asked", [
    {"cache_seconds": 0},
    {"cache_seconds": 5, "member": True},
])
@respx.mock
async def test_without_a_kept_answer_or_for_an_address_a_member_typed_every_card_asks_itself(asked) -> None:
    service = Held()
    respx.get(URL).mock(side_effect=service)
    cache: dict = {}
    calls = [asyncio.create_task(_ctx(cache).request("GET", URL, **asked)) for _ in range(2)]
    await _until_asked(service, 2)
    service.go.set()
    await asyncio.gather(*calls)
    assert service.asked == 2
