"""Which addresses nexdeck will call, and which it will not.

The server sits inside the network and reaches what a member's browser cannot:
nexdeck's own API, the router, the hypervisor. A notification channel takes an
address from any member and reports the answer back, which turned that field
into a way of asking what else is listening.

Two ranges are barred and nothing else. Private networks stay open on purpose:
a homelab dashboard that cannot reach 192.168.x is no use to anyone.

* loopback, because that is nexdeck itself and whatever else listens beside it
* 169.254.0.0/16, because it hands out the host's credentials on every cloud

Decided on 07.09.2026, after the first draft barred far more and would have
made the product worse.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import config
from app.adapters.base import AdapterError, guard_member_target, guard_outbound, outbound_client


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXDECK_ALLOW_LOOPBACK_TARGETS", raising=False)
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


#: Never a service, whoever named it. A machine answering on 169.254 has a
#: broken network, and the metadata address hands out the host's credentials.
BARRED_FOR_EVERYONE = [
    "http://169.254.169.254/latest/meta-data/",
    "https://169.254.1.1/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://[fd00:ec2::254]/latest/",
]

#: Barred only where a member typed the address.
BARRED_FOR_MEMBERS = [
    "http://127.0.0.1:8000/api/v1/boards",
    "http://127.0.0.1/",
    "http://[::1]:9000/",
]

ALLOWED = [
    "http://192.168.1.50:8080/",
    "http://172.16.4.9/",
    "https://ntfy.example.com/topic",
    "http://nas.local:5000/",
]


def test_what_is_never_a_service_is_refused_everywhere() -> None:
    for url in BARRED_FOR_EVERYONE:
        for check in (guard_outbound, guard_member_target):
            with pytest.raises(AdapterError) as refused:
                check(url)
            assert refused.value.code == "forbidden_host", f"{check.__name__}: {url}"
    assert len(BARRED_FOR_EVERYONE) >= 4, "the list shrank, so this test proves less than it says"


def test_loopback_is_barred_for_a_member_and_allowed_for_a_connection() -> None:
    """The difference is who put the address there.

    ⚠️ An administrator pointing a connection at ``http://127.0.0.1:7878`` is
    an ordinary Radarr on a host-network install, and ``test_cache_bounds.py``
    has said so since before this guard existed. A member typing the same
    thing into a notification channel is asking the server what else is
    listening beside it, and getting the answer as an HTTP status.

    The first draft barred it for everyone and turned that test red, which is
    how the difference was noticed at all.
    """
    for url in BARRED_FOR_MEMBERS:
        guard_outbound(url)  # a connection may
        with pytest.raises(AdapterError) as refused:
            guard_member_target(url)
        assert refused.value.code == "forbidden_host", url
    assert len(BARRED_FOR_MEMBERS) >= 3


def test_the_house_stays_reachable() -> None:
    """Private ranges and ordinary names go through, or the product is broken."""
    for url in ALLOWED:
        guard_outbound(url)
        guard_member_target(url)
    assert len(ALLOWED) >= 4


def test_only_http_and_https() -> None:
    for url in ("file:///etc/passwd", "gopher://x/", "ftp://host/f"):
        with pytest.raises(AdapterError) as refused:
            guard_outbound(url)
        assert refused.value.code == "bad_scheme", url


def test_the_operator_can_lift_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Somebody really does run a notification service next to nexdeck."""
    monkeypatch.setenv("NEXDECK_ALLOW_LOOPBACK_TARGETS", "1")
    config.reset_settings_cache()
    guard_member_target("http://127.0.0.1:8000/")


def test_a_name_that_points_at_loopback_still_gets_through() -> None:
    """The limit of this guard, written down so nobody assumes otherwise.

    ⚠️ ``localtest.me`` resolves to 127.0.0.1 and is allowed. Catching it would
    mean looking the name up before every request, on top of the lookup the
    connection makes anyway. Measured on 07.09.2026: a name with a dot that
    does not exist costs about 50 ms, a bare name like ``radarr`` costs 2.7 s,
    because Windows falls back to LLMNR and NetBIOS. A version of this guard
    that did resolve turned the test suite from eleven minutes into more than
    twenty-five, and it would have put those seconds in front of every card.

    So: literal addresses are barred, names are not, and closing this needs
    the check to move to the socket, where the address is already known.
    """
    guard_member_target("http://localtest.me/")


def test_the_second_hop_of_a_redirect_is_checked_too() -> None:
    """The guard hangs on the client, so httpx runs it for every hop.

    ⚠️ This is the whole reason it is a client hook and not a check on the
    address somebody typed. A service that answers 302 decides where the next
    request goes, and the first address says nothing about the second.
    """
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, text="arrived")

    async def probe() -> None:
        client = outbound_client(transport=httpx.MockTransport(handler), follow_redirects=True)
        try:
            await client.get("http://ntfy.example.com/start")
        finally:
            await client.aclose()

    with pytest.raises(AdapterError) as refused:
        asyncio.run(probe())
    assert refused.value.code == "forbidden_host"
    assert seen == ["http://ntfy.example.com/start"], f"the second hop was sent anyway: {seen}"
