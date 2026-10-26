"""KARTEN-3: how an own connection proves who asks, against stubs that behave like the real apps (AC-3 to AC-6, AC-9, EC-2 to EC-4, EC-7 to EC-9).

The stubs follow the recorded behaviour of Wiki.js (``Authorization: Bearer``), BookStack (``Authorization: Token id:secret``),
a service with the key in the address (Tautulli, ``?apikey=``) and Memos (a POST to ``/api/v1/auth/signin`` whose answer holds
``accessToken``, or the cookie ``memos.access-token``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters import defined, get_adapter
from app.adapters.base import AdapterError, Context
from app.db import db_session
from app.models import Event

from .conftest import CSRF
from .karten3_sample import HEADER, MEMOS, changed, example
from .test_cards_editor_api import admin, post  # noqa: F401 - the fixture
from .test_cards_router import BASE

API = "/api/v1/own-integrations"
KEY = "Zk-SuperSecret-0123456789"
PASSWORD = "pw-SuperSecret-9876543210"


class Moment:
    """The clock of the sign-in, moved by hand."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def pass_(self, **how: float) -> None:
        self.now += timedelta(**how)


@pytest.fixture
def moment(monkeypatch: pytest.MonkeyPatch) -> Moment:
    clock = Moment()
    monkeypatch.setattr(defined, "clock", clock)
    return clock


def own(client: TestClient, text: str, **config: Any) -> int:
    made = client.post(API, json={"yaml": text}, headers=CSRF)
    assert made.status_code == 201, made.text
    body = {"kind": made.json()["kind"], "name": "Mine", "config": {"url": BASE, **config}}
    connection = client.post("/api/v1/integrations", json=body, headers=CSRF)
    assert connection.status_code == 201, connection.text
    return int(connection.json()["id"])


class Counter:
    """A path nobody asked twice: an answer is kept for a few seconds, the same address would not be asked again."""

    def __init__(self) -> None:
        self.number = 0

    def path(self, base: str = "/api/v1/memos") -> str:
        self.number += 1
        return f"{base}?n={self.number}"


count = Counter()


def asked(client: TestClient, number: int, path: str | None = None) -> httpx.Response:
    return post(client, "probe", {"integration_id": number, "path": path or count.path()})


class Memos:
    """Memos as far as nexdeck meets it: a sign-in that hands out tickets, and notes that need one."""

    def __init__(self, *, cookie: bool = False) -> None:
        self.cookie = cookie
        self.valid: set[str] = set()
        self.issued = 0
        self.logins: list[httpx.Request] = []
        self.reads: list[httpx.Request] = []
        self.login_status = 200
        self.login_answer: httpx.Response | None = None
        self.refuse_everything = False

    def sign_in(self, request: httpx.Request) -> httpx.Response:
        self.logins.append(request)
        if self.login_answer is not None:
            return self.login_answer
        if self.login_status != 200:
            return httpx.Response(self.login_status, json={"message": "bad"})
        self.issued += 1
        ticket = f"T{self.issued}"
        self.valid.add(ticket)
        if self.cookie:
            return httpx.Response(200, json={"user": "x"}, headers={"set-cookie": f"memos.access-token={ticket}; Path=/; HttpOnly"})
        return httpx.Response(200, json={"accessToken": ticket})

    def read(self, request: httpx.Request) -> httpx.Response:
        self.reads.append(request)
        ticket = request.headers.get("authorization", "").removeprefix("Bearer ")
        if self.cookie:
            ticket = request.headers.get("cookie", "").removeprefix("memos.access-token=")
        if self.refuse_everything or ticket not in self.valid:
            return httpx.Response(401, json={"message": "unauthorized"})
        return httpx.Response(200, json={"memos": [{"id": 1}]})

    def mount(self) -> Memos:
        respx.post(f"{BASE}/api/v1/auth/signin").mock(side_effect=self.sign_in)
        respx.get(f"{BASE}/api/v1/memos").mock(side_effect=self.read)
        respx.get(f"{BASE}/api/v1/auth/status").mock(side_effect=self.read)
        return self


# -- AC-3, AC-4, AC-5: a key in the head, a user and password, a key in the address --------------------------------


@respx.mock
def test_karten3_ac3_the_head_and_its_form_are_the_description_s_wiki_js_bearer_and_bookstack_token(admin: TestClient) -> None:  # noqa: F811
    wiki = respx.get(f"{BASE}/api/v1/memos").mock(return_value=httpx.Response(200, json={"ok": True}))
    number = own(admin, changed(example("wikijs"), **{"auth.value": "Bearer {token}", "test": "/api/v1/memos"}), token=KEY)
    assert asked(admin, number).status_code == 200
    assert wiki.calls.last.request.headers["authorization"] == f"Bearer {KEY}"
    book = respx.get(f"{BASE}/api/books").mock(return_value=httpx.Response(200, json={"data": []}))
    number = own(admin, example("bookstack"), token_id="abc", token_secret=KEY)
    assert asked(admin, number, "/api/books?count=3").status_code == 200
    assert book.calls.last.request.headers["authorization"] == f"Token abc:{KEY}"


@respx.mock
def test_karten3_ac4_a_user_and_a_password_go_with_every_request_as_basic(admin: TestClient) -> None:  # noqa: F811
    text = changed(MEMOS, short="basic-app", auth={"type": "basic", "user": "{username}", "password": "{password}"})
    route = respx.get(f"{BASE}/api/v1/memos").mock(return_value=httpx.Response(200, json={"ok": True}))
    number = own(admin, text, username="ann", password=PASSWORD)
    for _ in range(2):
        assert asked(admin, number).status_code == 200
    expected = "Basic " + base64.b64encode(f"ann:{PASSWORD}".encode()).decode()
    assert [call.request.headers["authorization"] for call in route.calls] == [expected, expected]


@respx.mock
def test_karten3_ac5_a_key_in_the_address_goes_under_the_name_the_description_gives(admin: TestClient) -> None:  # noqa: F811
    route = respx.get(f"{BASE}/api/v2").mock(return_value=httpx.Response(200, json={"response": {"result": "success"}}))
    number = own(admin, example("apikey-in-address"), api_key=KEY)
    assert asked(admin, number, "/api/v2?cmd=get_activity").status_code == 200
    sent = route.calls.last.request.url
    assert sent.params["apikey"] == KEY and sent.params["cmd"] == "get_activity"


BASIC = base64.b64encode(f"ann:{PASSWORD}".encode()).decode()
#: (how it is signed, the description, the settings, the secret, what of it travels to the service)
SIGNED = (
    ("a key in the head", HEADER, {"token_id": "abc", "token_secret": KEY}, KEY, KEY),
    ("a key in the address", example("apikey-in-address"), {"api_key": KEY}, KEY, KEY),
    ("user and password as basic", changed(MEMOS, short="basic-app", auth={"type": "basic", "user": "{username}", "password": "{password}"}), {"username": "ann", "password": PASSWORD}, PASSWORD, BASIC),
    ("a session whose password goes in the sign-in body", MEMOS, {"username": "ann", "password": PASSWORD}, PASSWORD, PASSWORD),
)


@pytest.mark.parametrize(("how", "text", "config", "secret", "travels"), SIGNED, ids=[row[0] for row in SIGNED])
@respx.mock
def test_karten3_ac5_what_proves_who_asks_is_in_no_answer_no_chronicle_and_no_log(
    admin: TestClient, caplog: pytest.LogCaptureFixture, how: str, text: str, config: dict[str, Any], secret: str, travels: str  # noqa: F811
) -> None:
    number = own(admin, text, **config)
    outcomes = [
        httpx.Response(200, json={"accessToken": "T-ticket-9", "ok": True}),
        httpx.Response(500, text="boom"),
        httpx.Response(401, text="no"),
        httpx.Response(302, headers={"location": "http://elsewhere.example.com/x"}),
        httpx.Response(200, text="<html>login</html>"),
    ]
    route = respx.route().mock(side_effect=outcomes + [httpx.ConnectError("refused")] * 60)
    texts: list[str] = []
    with caplog.at_level(logging.DEBUG):
        for _ in range(len(outcomes) + 2):
            texts.append(asked(admin, number).text)
        tested = admin.post(f"/api/v1/integrations/{number}/test", headers=CSRF)
        texts.append(tested.text)
        listed = admin.get("/api/v1/integrations")
        texts.append(listed.text)
    sent = [str(call.request.url) + str(dict(call.request.headers)) + call.request.content.decode(errors="ignore") for call in route.calls]
    assert any(travels in one for one in sent), f"{how}: the secret never left, so nothing was proven"
    with db_session() as db:
        kept = json.dumps([[getattr(one, column.name) for column in Event.__table__.columns] for one in db.scalars(select(Event))], default=str)
    for hidden in (secret, travels):
        assert all(hidden not in one for one in texts), f"{how}: an answer holds it"
    # the ticket is the service's own data in the answer of a probe that is not a sign-in: not asked of the answers
    for hidden in (secret, travels, "T-ticket-9"):
        assert hidden not in kept, f"{how}: the chronicle holds it"
        assert hidden not in caplog.text, f"{how}: a logger wrote it down"


# -- AC-6: a session -------------------------------------------------------------------------------------------------


@respx.mock
def test_karten3_ac6_memos_signs_in_once_keeps_the_ticket_and_passes_it_on(admin: TestClient) -> None:  # noqa: F811
    service = Memos().mount()
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    for _ in range(3):
        assert asked(admin, number).status_code == 200
    assert len(service.logins) == 1
    assert json.loads(service.logins[0].content) == {"username": "ann", "password": PASSWORD}
    assert {call.headers["authorization"] for call in service.reads} == {"Bearer T1"}


@respx.mock
def test_karten3_ac6_the_ticket_may_be_a_cookie_and_travel_as_one(admin: TestClient) -> None:  # noqa: F811
    service = Memos(cookie=True).mount()
    number = own(admin, example("memos-cookie"), username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200 and asked(admin, number).status_code == 200
    assert len(service.logins) == 1
    assert {call.headers["cookie"] for call in service.reads} == {"memos.access-token=T1"}


@respx.mock
def test_karten3_ac6_the_sign_in_may_be_a_form_and_the_ticket_may_travel_in_the_address(admin: TestClient) -> None:  # noqa: F811
    text = changed(MEMOS, short="form-app", **{"auth.send": "form", "auth.pass": {"as": "query", "param": "sid"}})
    seen: list[httpx.Request] = []

    def sign_in(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"accessToken": "SID-1"})

    respx.post(f"{BASE}/api/v1/auth/signin").mock(side_effect=sign_in)
    read = respx.get(f"{BASE}/api/v1/memos").mock(return_value=httpx.Response(200, json={"ok": True}))
    number = own(admin, text, username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    assert seen[0].headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert dict(httpx.QueryParams(seen[0].content.decode())) == {"username": "ann", "password": PASSWORD}
    assert read.calls.last.request.url.params["sid"] == "SID-1"


@respx.mock
def test_karten3_ac6_a_401_signs_in_again_once_and_asks_again(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(minutes=30)
    service.valid.clear()  # the service forgot the ticket
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 2
    assert [call.headers["authorization"] for call in service.reads] == ["Bearer T1", "Bearer T1", "Bearer T2"]


@respx.mock
def test_karten3_ec3_when_the_new_sign_in_is_refused_too_the_card_asks_no_third_time(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    moment.pass_(minutes=30)
    service.refuse_everything = True
    before = (len(service.logins), len(service.reads))
    answer = asked(admin, number)
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "sign_in_failed"
    assert "sign-in failed" in answer.json()["detail"]["message"].lower()
    assert (len(service.logins) - before[0], len(service.reads) - before[1]) == (1, 2)


@respx.mock
def test_karten3_ec3_a_ticket_refused_the_moment_it_was_given_is_not_signed_in_for_again_in_the_same_breath(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    service.refuse_everything = True
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    answer = asked(admin, number)
    assert answer.json()["detail"]["code"] == "sign_in_failed"
    assert (len(service.logins), len(service.reads)) == (1, 1)


@respx.mock
def test_karten3_ec4_three_failed_sign_ins_pause_the_connection_for_fifteen_minutes_and_the_test_button_goes_on(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    service.login_status = 401
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    for _ in range(3):
        answer = asked(admin, number)
        assert answer.json()["detail"]["code"] == "sign_in_failed"
    assert len(service.logins) == 3
    paused = asked(admin, number)
    detail = paused.json()["detail"]
    until = (moment.now + timedelta(minutes=15)).astimezone().strftime("%H:%M")
    assert detail["code"] == "sign_in_paused" and f"paused until {until}" in detail["message"]
    assert len(service.logins) == 3, "no sign-in during the pause"
    moment.pass_(minutes=14)
    assert asked(admin, number).json()["detail"]["code"] == "sign_in_paused"
    # the Test button signs in whatever the pause says
    service.login_status = 200
    tested = admin.post(f"/api/v1/integrations/{number}/test", headers=CSRF).json()
    assert tested["ok"] is True and len(service.logins) == 4
    moment.pass_(minutes=2)
    service.login_status = 401
    assert asked(admin, number).json()["detail"]["code"] == "sign_in_failed"
    assert len(service.logins) == 5, "after the pause one attempt is made, not three"
    assert asked(admin, number).json()["detail"]["code"] == "sign_in_paused"


@respx.mock
def test_karten3_ec4_a_sign_in_that_worked_clears_the_count(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    service.login_status = 401
    for _ in range(2):
        assert asked(admin, number).json()["detail"]["code"] == "sign_in_failed"
    service.login_status = 200
    assert asked(admin, number).status_code == 200
    service.login_status = 401
    moment.pass_(minutes=30)
    service.valid.clear()
    # three more in a row, and only then the pause: the two before the success do not count
    for _ in range(3):
        assert asked(admin, number).json()["detail"]["code"] == "sign_in_failed"
    assert asked(admin, number).json()["detail"]["code"] == "sign_in_paused"


def adapter_and_config(short: str, **config: Any) -> tuple[Any, dict[str, Any]]:
    return get_adapter(f"custom:{short}"), {"url": BASE, **config}


@respx.mock
def test_karten3_ec8_ten_cards_that_need_a_session_together_sign_in_once_and_ten_that_all_got_a_401_sign_in_once(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    assert admin.post(API, json={"yaml": MEMOS}, headers=CSRF).status_code == 201
    adapter, config = adapter_and_config("memos", username="ann", password=PASSWORD)

    async def together() -> tuple[list[int], int, list[int], int]:
        async with httpx.AsyncClient() as client:
            ctx = Context(client, integration_id=7, cache={})

            async def ten(first: int) -> list[int]:
                answers = await asyncio.gather(*(adapter.raw_request("GET", f"/api/v1/memos?n={n}", config, ctx) for n in range(first, first + 10)))
                return [one.status_code for one in answers]

            first = await ten(0)
            logins = len(service.logins)
            moment.pass_(minutes=30)
            service.valid.clear()
            return first, logins, await ten(100), len(service.logins)

    first, logins, second, after = asyncio.run(together())
    assert first == [200] * 10 and logins == 1
    assert second == [200] * 10 and after == 2


# -- AC-9, EC-2, EC-9: the test ------------------------------------------------------------------------------------


def pressed(client: TestClient, number: int) -> dict[str, Any]:
    return client.post(f"/api/v1/integrations/{number}/test", headers=CSRF).json()  # type: ignore[no-any-return]


@respx.mock
def test_karten3_ac9_the_test_asks_the_test_path_and_is_green_on_a_2xx(admin: TestClient) -> None:  # noqa: F811
    route = respx.get(f"{BASE}/api/books").mock(return_value=httpx.Response(200, json={"data": []}))
    number = own(admin, example("bookstack"), token_id="abc", token_secret=KEY)
    result = pressed(admin, number)
    assert result["ok"] is True and route.calls.last.request.url.params["count"] == "1"
    before = admin.post("/api/v1/integrations/test", json={"kind": "custom:bookstack-own", "config": {"url": BASE, "token_id": "abc", "token_secret": KEY}}, headers=CSRF)
    assert before.json()["ok"] is True


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (httpx.Response(401, json={}), "auth_failed"),
        (httpx.Response(403, json={}), "auth_failed"),
        (httpx.Response(404, json={}), "unexpected_answer"),
        (httpx.Response(500, text="boom"), "unexpected_answer"),
        (httpx.Response(200, text="<html>Welcome</html>", headers={"content-type": "text/html"}), "unexpected_answer"),
        (httpx.ConnectError("refused"), "unreachable"),
    ],
    ids=["401", "403", "404", "500", "web page where json is expected", "no answer"],
)
@respx.mock
def test_karten3_ac9_the_test_is_red_with_the_reason(admin: TestClient, answer: Any, code: str) -> None:  # noqa: F811
    def serve(request: httpx.Request) -> httpx.Response:
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[no-any-return]

    respx.get(f"{BASE}/api/books").mock(side_effect=serve)
    number = own(admin, example("bookstack"), token_id="abc", token_secret=KEY)
    result = pressed(admin, number)
    assert result["ok"] is False and result["code"] == code and result["message"] and KEY not in json.dumps(result)


@respx.mock
def test_karten3_ac9_a_web_page_is_green_where_the_description_does_not_ask_for_json(admin: TestClient) -> None:  # noqa: F811
    respx.get(f"{BASE}/healthz").mock(return_value=httpx.Response(200, text="OK", headers={"content-type": "text/plain"}))
    number = own(admin, example("wikijs"), token=KEY)
    assert pressed(admin, number)["ok"] is True


@respx.mock
def test_karten3_ec2_a_sign_in_answer_without_the_ticket_is_told_so(admin: TestClient) -> None:  # noqa: F811
    service = Memos().mount()
    service.login_answer = httpx.Response(200, json={"user": "ann"})
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    result = pressed(admin, number)
    assert result["ok"] is False and result["code"] == "sign_in_no_ticket" and result["message"] == "sign-in answer without a ticket"
    service.login_answer = httpx.Response(200, json={"accessToken": ""})
    assert pressed(admin, number)["code"] == "sign_in_no_ticket"
    cookie = Memos(cookie=True)
    cookie.login_answer = httpx.Response(200, json={}, headers={"set-cookie": "other=1"})
    respx.post(f"{BASE}/api/v1/auth/signin").mock(side_effect=cookie.sign_in)
    number = own(admin, example("memos-cookie"), username="ann", password=PASSWORD)
    assert pressed(admin, number)["code"] == "sign_in_no_ticket"


@respx.mock
def test_karten3_ec9_a_sign_in_that_leads_to_a_web_page_says_so_and_is_not_followed(admin: TestClient) -> None:  # noqa: F811
    service = Memos().mount()
    elsewhere = respx.route(host="login.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))
    service.login_answer = httpx.Response(302, headers={"location": "https://login.example.com/start?rd=1"})
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    result = pressed(admin, number)
    assert result["ok"] is False and result["code"] == "sign_in_web_page" and result["message"] == "sign-in redirects to a web page"
    assert "key" in result["hint"].lower() and "proxy" in result["hint"].lower()
    assert not elsewhere.called, "the sign-in was sent on to another place"
    service.login_answer = httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html; charset=utf-8"})
    assert pressed(admin, number)["code"] == "sign_in_web_page"


@respx.mock
def test_karten3_the_test_signs_in_by_itself_and_a_refused_sign_in_reads_as_failed(admin: TestClient) -> None:  # noqa: F811
    service = Memos().mount()
    service.login_status = 401
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    result = pressed(admin, number)
    assert result["ok"] is False and result["code"] == "sign_in_failed"
    service.login_status = 200
    assert pressed(admin, number)["ok"] is True


# -- EC-7: the address with a path, and the guards of every read ---------------------------------------------------------


@pytest.mark.parametrize("address", ["http://svc.example.com:8080/memos", "http://svc.example.com:8080/memos/", "http://svc.example.com:8080/memos//"])
@respx.mock
def test_karten3_ec7_a_path_under_the_address_and_a_slash_at_the_end_put_the_paths_in_the_right_place(admin: TestClient, address: str) -> None:  # noqa: F811
    login = respx.post("http://svc.example.com:8080/memos/api/v1/auth/signin").mock(return_value=httpx.Response(200, json={"accessToken": "T1"}))
    read = respx.get("http://svc.example.com:8080/memos/api/v1/memos").mock(return_value=httpx.Response(200, json={"ok": True}))
    made = admin.post(API, json={"yaml": MEMOS}, headers=CSRF)
    connection = admin.post("/api/v1/integrations", json={"kind": made.json()["kind"], "name": "Mine", "config": {"url": address, "username": "a", "password": "b"}}, headers=CSRF)
    number = connection.json()["id"]
    assert asked(admin, number).status_code == 200
    assert login.called and read.called


@respx.mock
def test_karten3_the_guards_of_every_card_hold_for_an_own_connection(admin: TestClient) -> None:  # noqa: F811
    wrong = respx.route(host="elsewhere.example.com").mock(return_value=httpx.Response(200, json={}))
    service = Memos().mount()
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    # a word that acts is refused before anything leaves, a path that climbs out too
    refused = asked(admin, number, "/api/v1/memos?action=restart")
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "command_refused"
    assert asked(admin, number, "/api/v1/../admin").status_code == 400
    # a redirect to another place is not followed with the ticket
    respx.get(f"{BASE}/api/v1/redirect").mock(return_value=httpx.Response(302, headers={"location": "http://elsewhere.example.com/x"}))
    assert asked(admin, number, "/api/v1/redirect").status_code >= 400
    assert not wrong.called
    # nothing but the sign-in is anything but a GET, and it goes to the sign-in path
    methods = {(call.request.method, call.request.url.path) for call in respx.calls}
    assert {method for method, _ in methods if method != "GET"} == {"POST"}
    assert {path for method, path in methods if method == "POST"} == {"/api/v1/auth/signin"}
    assert len(service.logins) == 1


@respx.mock
def test_karten3_the_sign_in_goes_only_to_the_address_of_the_connection(admin: TestClient) -> None:  # noqa: F811
    for login in ("https://elsewhere.example.com/signin", "//elsewhere.example.com/signin", "/../signin"):
        bad = changed(MEMOS, short="elsewhere", **{"auth.login": login})
        response = admin.post(API, json={"yaml": bad}, headers=CSRF)
        assert response.status_code == 400, login
        assert "card_integration_path" in {one["code"] for one in response.json()["detail"]["problems"]}


@respx.mock
def test_karten3_ac11_a_change_of_the_description_makes_the_connection_sign_in_again(admin: TestClient) -> None:  # noqa: F811
    service = Memos().mount()
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 1
    other = changed(MEMOS, **{"auth.pass": {"as": "header", "header": "Authorization", "value": "Bearer {ticket}"}, "description": "Changed."})
    assert admin.put(f"{API}/memos", json={"yaml": other}, headers=CSRF).status_code == 200
    assert asked(admin, number).status_code == 200
    assert len(service.logins) == 2


def test_karten3_ac10_the_switch_for_tls_errors_is_there_like_it_is_for_the_built_in_kinds(admin: TestClient) -> None:  # noqa: F811
    assert admin.post(API, json={"yaml": MEMOS}, headers=CSRF).status_code == 201
    adapter = get_adapter("custom:memos")
    field = next(one for one in adapter.fields if one.name == "insecure")
    assert (field.label, field.type, field.default) == ("Ignore TLS errors", "bool", False)
    assert adapter.raw_verify({"url": BASE}) is True
    assert adapter.raw_verify({"url": BASE, "insecure": True}) is False
    assert get_adapter("sonarr").raw_verify({"insecure": True}) is False


def test_karten3_a_missing_kind_says_integration_missing_instead_of_failing() -> None:
    from app.adapters import adapter_or_missing

    gone = adapter_or_missing("custom:gone")
    assert gone.kind == "custom:gone" and gone.fields == () and gone.raw_access is False
    with pytest.raises(AdapterError) as failure:
        asyncio.run(gone.test({}, Context(httpx.AsyncClient())))
    assert failure.value.code == "integration_missing" and failure.value.message == "integration missing"
