"""The reachability check against a busy moment: a second try, the reason in words, and starts spread over the round.

Found on 02.10.2026 on a Synology: every check of a round started in the same instant, and the one server outside the
home address broke the TLS handshake off in that burst, round after round. The tile of a service that was up stayed
red, with ``ConnectError`` as the only word on it.
"""

from __future__ import annotations

import errno
import socket
import ssl
import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.services import health

from .conftest import CSRF, setup_admin


def broken(cause: BaseException) -> httpx.ConnectError:
    error = httpx.ConnectError("")
    error.__cause__ = cause
    return error


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "RETRY_SECONDS", 0)


class Flaky:
    """A client whose first answers fail the way the Synology's did: a ConnectError over an SSL EOF.

    Not respx: it raises with ``from`` itself and so drops the cause the reason is read from.
    """

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def get(self, url: str, timeout: float) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.failures:
            try:
                raise ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
            except ssl.SSLEOFError as eof:
                raise httpx.ConnectError("") from eof
        return httpx.Response(200)


async def test_a_failure_to_connect_is_tried_once_more_before_it_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    flaky = Flaky(failures=1)
    monkeypatch.setattr(health, "http_client", lambda insecure: flaky)
    ok, _, detail = await health.check_http("https://ha.example.com", 5, 0, False)
    assert ok and detail == "HTTP 200"
    assert flaky.calls == 2


async def test_twice_broken_off_says_what_broke(monkeypatch: pytest.MonkeyPatch) -> None:
    flaky = Flaky(failures=2)
    monkeypatch.setattr(health, "http_client", lambda insecure: flaky)
    ok, _, detail = await health.check_http("https://ha.example.com", 5, 0, False)
    assert not ok and detail == "The TLS handshake was broken off."
    assert flaky.calls == 2


@respx.mock
async def test_an_answer_is_not_asked_twice() -> None:
    route = respx.get("http://svc.example.com").mock(return_value=httpx.Response(502))
    ok, _, detail = await health.check_http("http://svc.example.com", 5, 0, False)
    assert not ok and detail == "HTTP 502" and route.call_count == 1


def test_the_reason_comes_from_deep_in_the_chain() -> None:
    verify = ssl.SSLCertVerificationError(1, "certificate verify failed")
    assert health.reason(broken(verify)) == "The certificate is not trusted."
    assert health.reason(broken(socket.gaierror(-2, "Name or service not known"))) == "The name was not found."
    assert health.reason(broken(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))) == "The connection was refused."
    assert health.reason(broken(OSError(errno.EHOSTUNREACH, "No route to host"))) == "The host cannot be reached."
    assert health.reason(httpx.ReadTimeout("")) == "No answer in time."
    assert health.reason(httpx.ConnectError("")) == "ConnectError"


async def test_the_checks_of_a_round_do_not_start_in_one_instant(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_admin(client)
    board = client.post("/api/v1/boards", json={"name": "Lab"}, headers=CSRF).json()
    page_id = board["pages"][0]["id"]
    for name in ("one", "two", "three"):
        target = f"http://{name}.example.com"
        widget = client.post(f"/api/v1/pages/{page_id}/widgets", json={"kind": "core.app", "link": target}, headers=CSRF).json()["widget"]
        client.put(f"/api/v1/widgets/{widget['id']}/health", json={"kind": "http", "target": target}, headers=CSRF)
    started: list[float] = []

    async def probe(check: object) -> tuple[bool, int, str]:
        started.append(time.monotonic())
        return True, 1, "HTTP 200"

    monkeypatch.setattr(health, "run_check", probe)
    monkeypatch.setattr(health, "STAGGER_SECONDS", 0.05)
    await health.health.run_due(force=True)
    assert len(started) == 3
    started.sort()
    assert all(later - earlier >= 0.04 for earlier, later in zip(started, started[1:], strict=False))
