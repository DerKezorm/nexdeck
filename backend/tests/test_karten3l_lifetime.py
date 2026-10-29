"""KARTEN-3 AC-6 (extended): how long a ticket holds, and which answers mean that it ran out.

Memos as in ``test_karten3_auth.py``, with a sign-in that can say ``expiresIn`` and a service that can answer an old ticket with
something else than 401 (Wallabag says 500). The clock of the sign-in is moved by hand.
"""

from __future__ import annotations

import httpx
import pytest
import respx
import yaml
from fastapi.testclient import TestClient

from .conftest import CSRF
from .karten3_sample import MEMOS, changed
from .test_cards_editor_api import admin  # noqa: F401 - the fixture
from .test_karten3_auth import (  # noqa: F401 - the fixtures
    API,
    PASSWORD,
    Memos,
    Moment,
    asked,
    moment,
    own,
)

SECONDS = 3600


class Timed(Memos):
    """A service whose sign-in names how many seconds the ticket holds, and that answers an old ticket with ``refusal``."""

    def __init__(self, *, expires_in: object = SECONDS, refusal: int = 401) -> None:
        super().__init__()
        self.expires_in = expires_in
        self.refusal = refusal
        self.dropped = False

    async def sign_in(self, request: httpx.Request) -> httpx.Response:
        answer = await super().sign_in(request)
        if answer.status_code != 200 or self.expires_in is None:
            return answer
        return httpx.Response(200, json={**answer.json(), "expiresIn": self.expires_in})

    def read(self, request: httpx.Request) -> httpx.Response:
        if self.dropped:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request)
        answer = super().read(request)
        if answer.status_code == 401 and self.refusal != 401:
            return httpx.Response(self.refusal, text="<html>Internal Server Error</html>")
        return answer


def described(**places: object) -> str:
    return changed(MEMOS, short="life", **places)


def tickets(service: Memos) -> list[str]:
    return [call.headers["authorization"] for call in service.reads]


# -- lifetime: sign in again before the ticket runs out ---------------------------------------------------------------


@respx.mock
def test_karten3l_a_fixed_lifetime_signs_in_again_a_minute_before_the_ticket_runs_out(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(expires_in=None).mount()
    number = own(admin, described(**{"auth.lifetime": 600}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(seconds=539)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 1, "a ticket with a minute to go is still used"
    moment.pass_(seconds=2)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 2
    assert tickets(service) == ["Bearer T1", "Bearer T1", "Bearer T2"], "signed in before asking: no 401 on the way"


@respx.mock
def test_karten3l_the_lifetime_can_be_the_number_of_seconds_in_the_sign_in_answer(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(expires_in=300).mount()
    number = own(admin, described(**{"auth.lifetime": {"from": "json", "at": "expiresIn"}}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(seconds=239)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 1
    moment.pass_(seconds=2)
    assert asked(admin, number).status_code == 200
    assert tickets(service) == ["Bearer T1", "Bearer T1", "Bearer T2"]
    service.expires_in = "7200"  # a number written as text counts
    moment.pass_(seconds=300)
    assert asked(admin, number).status_code == 200
    moment.pass_(seconds=7000)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 3, "the lifetime of the newest answer rules the newest ticket"
    moment.pass_(seconds=200)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 4


@respx.mock
def test_karten3l_a_ticket_is_held_for_at_least_thirty_seconds(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(expires_in=None).mount()
    number = own(admin, described(**{"auth.lifetime": 45}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(seconds=29)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 1, "a minute of notice would be before the sign-in: thirty seconds are held"
    moment.pass_(seconds=2)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 2


@pytest.mark.parametrize("said", [None, 0, -5, "soon", True, [3600]], ids=["absent", "zero", "negative", "text", "bool", "list"])
@respx.mock
def test_karten3l_an_answer_without_a_usable_lifetime_leaves_the_ticket_as_it_is_without_one(admin: TestClient, moment: Moment, said: object) -> None:  # noqa: F811
    service = Timed(expires_in=said).mount()
    number = own(admin, described(**{"auth.lifetime": {"from": "json", "at": "expiresIn"}}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(hours=20)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 1
    service.valid.clear()
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 2, "a 401 still signs in again"


@respx.mock
def test_karten3l_without_a_lifetime_the_ticket_is_kept_until_the_service_refuses_it(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed().mount()
    number = own(admin, described(), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(hours=20)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 1


@respx.mock
def test_karten3l_a_fetch_that_signed_in_before_the_end_does_not_sign_in_again_when_the_new_ticket_is_refused(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(expires_in=None).mount()
    number = own(admin, described(**{"auth.lifetime": 600}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(seconds=600)
    service.refuse_everything = True
    service.on_read = lambda: moment.pass_(seconds=10)  # a slow service: the new ticket is no longer "fresh"
    before = (len(service.logins), len(service.reads))
    answer = asked(admin, number)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "sign_in_failed"
    assert (len(service.logins) - before[0], len(service.reads) - before[1]) == (1, 1), "the sign-in before asking is the one of this fetch: a 401 after it is the end"


# -- renew_on: which answers mean that the ticket ran out ---------------------------------------------------------------


@respx.mock
def test_karten3l_renew_on_lets_a_500_sign_in_again_once_and_ask_again(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(refusal=500, expires_in=None).mount()
    number = own(admin, described(**{"auth.renew_on": [401, 500]}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(minutes=30)
    service.valid.clear()
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 2
    assert tickets(service) == ["Bearer T1", "Bearer T1", "Bearer T2"]


@respx.mock
def test_karten3l_without_renew_on_only_a_401_signs_in_again(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(refusal=500, expires_in=None).mount()
    number = own(admin, described(), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(minutes=30)
    service.valid.clear()
    answer = asked(admin, number)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "http_error"
    assert len(service.logins) == 1, "a 500 is the service's own trouble unless the description says it means signed out"


@pytest.mark.parametrize("status", [403, 419, 440])
@respx.mock
def test_karten3l_every_status_renew_on_may_name_signs_in_again(admin: TestClient, moment: Moment, status: int) -> None:  # noqa: F811
    service = Timed(refusal=status, expires_in=None).mount()
    number = own(admin, described(**{"auth.renew_on": [status]}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(minutes=30)
    service.valid.clear()
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 2


@respx.mock
def test_karten3l_a_500_that_a_new_sign_in_does_not_cure_stays_a_500_and_is_asked_for_once(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(refusal=500, expires_in=None).mount()
    number = own(admin, described(**{"auth.renew_on": [401, 500]}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(minutes=30)
    service.refuse_everything = True
    before = (len(service.logins), len(service.reads))
    answer = asked(admin, number)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "http_error", "a failing path is not a wrong password"
    assert (len(service.logins) - before[0], len(service.reads) - before[1]) == (1, 2)


@respx.mock
def test_karten3l_a_cut_off_request_never_signs_in_again(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Timed(refusal=500, expires_in=None).mount()
    number = own(admin, described(**{"auth.renew_on": [401, 403, 419, 440, 500]}), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(minutes=30)
    service.dropped = True
    answer = asked(admin, number)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "unreachable"
    assert len(service.logins) == 1


# -- the description ------------------------------------------------------------------------------------------------------


BAD = {
    "zero": {"auth.lifetime": 0},
    "negative": {"auth.lifetime": -1},
    "longer than a year": {"auth.lifetime": 31_536_001},
    "text": {"auth.lifetime": "3600"},
    "bool": {"auth.lifetime": True},
    "from a cookie": {"auth.lifetime": {"from": "cookie", "name": "x"}},
    "json without at": {"auth.lifetime": {"from": "json"}},
    "unknown status": {"auth.renew_on": [404]},
    "empty": {"auth.renew_on": []},
    "twice": {"auth.renew_on": [401, 401]},
    "text status": {"auth.renew_on": ["401"]},
    "bool status": {"auth.renew_on": [True]},
}


@pytest.mark.parametrize("places", BAD.values(), ids=list(BAD))
def test_karten3l_a_lifetime_or_renew_on_that_makes_no_sense_is_refused(admin: TestClient, places: dict[str, object]) -> None:  # noqa: F811
    made = admin.post(API, json={"yaml": described(**places)}, headers=CSRF)
    assert made.status_code in (400, 422), made.text


def test_karten3l_lifetime_and_renew_on_belong_to_the_session_type(admin: TestClient) -> None:  # noqa: F811
    keyed = changed(MEMOS, short="life", auth={"type": "header", "header": "X-Key", "value": "{password}", "lifetime": 60})
    assert admin.post(API, json={"yaml": keyed}, headers=CSRF).status_code in (400, 422)
    keyed = changed(MEMOS, short="life", auth={"type": "header", "header": "X-Key", "value": "{password}", "renew_on": [500]})
    assert admin.post(API, json={"yaml": keyed}, headers=CSRF).status_code in (400, 422)


def test_karten3l_the_expression_of_a_lifetime_in_the_answer_is_checked_like_the_one_of_the_ticket(admin: TestClient) -> None:  # noqa: F811
    broken = described(**{"auth.lifetime": {"from": "json", "at": "a["}})
    made = admin.post(API, json={"yaml": broken}, headers=CSRF)
    assert made.status_code in (400, 422), made.text
    assert "lifetime" in made.text


def test_karten3l_a_description_with_both_is_taken_and_keeps_them(admin: TestClient) -> None:  # noqa: F811
    text = described(**{"auth.lifetime": {"from": "json", "at": "expiresIn"}, "auth.renew_on": [401, 500]})
    made = admin.post(API, json={"yaml": text}, headers=CSRF)
    assert made.status_code == 201, made.text
    assert yaml.safe_load(text)["auth"]["renew_on"] == [401, 500]
