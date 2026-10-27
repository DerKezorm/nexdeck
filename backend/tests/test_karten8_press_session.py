"""KARTEN-8: a button signs in the way the reads of its card do, also through an own connection with a session.

Memos as in ``test_karten3_auth.py``: a sign-in that hands out tickets and a service that answers 401 to a ticket that ran
out. A press with an old ticket signs in once more and is sent once more, exactly as a read is (KARTEN-3 EC-3).
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from .conftest import CSRF
from .karten3_sample import MEMOS
from .test_cards_editor_api import admin  # noqa: F401 - the fixture
from .test_cards_router import BASE
from .test_karten3_auth import PASSWORD, Memos, Moment, moment, own  # noqa: F401 - the fixture

CARD = """\
nexdeck-card: 1
slug: notes
name: Notes
version: 1.0.0
requires: ["custom:memos"]
requests:
  - id: memos
    path: /api/v1/memos
form: list
rows: {select: memos}
item: {title: id}
buttons:
  - id: archive
    label: Archive
    where: row
    method: POST
    path: /api/v1/memos/{id}/archive
"""


@respx.mock
def test_karten8_a_press_with_a_ticket_that_ran_out_signs_in_once_more_and_is_sent_once_more(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    archive = respx.post(f"{BASE}/api/v1/memos/1/archive").mock(side_effect=service.read)
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    assert admin.post("/api/v1/cards", json={"yaml": CARD}, headers=CSRF).status_code == 201
    board = admin.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    widget = admin.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "custom.list", "integration_id": number, "options": {"card": "notes"}}, headers=CSRF,
    ).json()["widget"]["id"]
    shown = admin.post(f"/api/v1/widgets/{widget}/refresh", headers=CSRF).json()
    assert shown["items"][0]["actions"][0]["params"] == {"id": 1}
    assert len(service.logins) == 1
    moment.pass_(minutes=10)
    service.valid.clear()  # the ticket ran out at the service
    answer = admin.post(f"/api/v1/widgets/{widget}/actions/button:archive", json={"params": {"id": 1}}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["message"] == "Done"
    assert len(service.logins) == 2
    assert [call.request.headers["authorization"] for call in archive.calls] == ["Bearer T1", "Bearer T2"]


@respx.mock
def test_karten8_a_press_refused_after_signing_in_again_says_so_and_goes_out_twice_at_most(admin: TestClient, moment: Moment) -> None:  # noqa: F811
    service = Memos().mount()
    archive = respx.post(f"{BASE}/api/v1/memos/1/archive").mock(return_value=httpx.Response(401))
    number = own(admin, MEMOS, username="ann", password=PASSWORD)
    admin.post("/api/v1/cards", json={"yaml": CARD}, headers=CSRF)
    board = admin.post("/api/v1/boards", json={"name": "Wall"}, headers=CSRF).json()
    widget = admin.post(
        f"/api/v1/pages/{board['pages'][0]['id']}/widgets",
        json={"kind": "custom.list", "integration_id": number, "options": {"card": "notes"}}, headers=CSRF,
    ).json()["widget"]["id"]
    admin.post(f"/api/v1/widgets/{widget}/refresh", headers=CSRF)
    moment.pass_(minutes=10)
    answer = admin.post(f"/api/v1/widgets/{widget}/actions/button:archive", json={"params": {"id": 1}}, headers=CSRF)
    # the words of a read of the same card that the service refuses after a new sign-in (KARTEN-3 EC-3)
    assert answer.json()["detail"]["code"] == "sign_in_failed"
    assert archive.call_count == 2 and len(service.logins) == 2
