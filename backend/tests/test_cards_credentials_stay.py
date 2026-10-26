"""Whatever signs a request of a custom card stays between the server and the service (JEDE-3).

Every kind may be read now, so the guard cannot be a list of tried kinds. The test takes the ways of signing that put
something into the address (a key as a parameter) or into a header, asks through the editor's addresses with the
service saying everything that can go wrong, and looks for the secret in everything that is kept or shown: the answers
of the server, the chronicle, the log of every logger (httpx's own included) and the answers of the list of what the
built-in cards read.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import db_session
from app.models import Event

from .conftest import CSRF
from .test_cards_editor_api import admin, post  # noqa: F401 - the fixture
from .test_cards_router import BASE, connection

SECRET = "Zk-SuperSecret-0123456789"


def everything_kept() -> str:
    with db_session() as db:
        return json.dumps([[getattr(one, column.name) for column in Event.__table__.columns] for one in db.scalars(select(Event))], default=str)


#: (kind, the configuration, how the secret travels)
SIGNED = (
    ("tautulli", {"url": BASE, "api_key": SECRET}, "a parameter of the address"),
    ("youtube", {"api_key": SECRET}, "a parameter of the address, on a fixed API host"),
    ("kavita", {"url": BASE, "api_key": SECRET}, "a key that is exchanged for a token"),
    ("wallos", {"url": BASE, "api_key": SECRET}, "a field of the body of the kind's own request"),
    ("sonarr", {"url": BASE, "api_key": SECRET}, "a header"),
)


@pytest.mark.parametrize(("kind", "config", "how"), SIGNED, ids=[row[0] for row in SIGNED])
@respx.mock
def test_jede4_the_secret_that_signs_a_request_is_in_no_answer_no_chronicle_and_no_log(
    admin: TestClient, caplog: pytest.LogCaptureFixture, kind: str, config: dict[str, str], how: str  # noqa: F811
) -> None:
    made = admin.post("/api/v1/integrations", json={"kind": kind, "name": f"My {kind}", "config": config}, headers=CSRF)
    assert made.status_code == 201, made.text
    integration = made.json()["id"]
    outcomes = [
        httpx.Response(200, json={"ok": True}),
        httpx.Response(500, text="boom"),
        httpx.Response(401, text="no"),
        httpx.Response(302, headers={"location": "http://elsewhere.example.com/x"}),
        httpx.Response(200, text="<html>login</html>"),
    ]
    route = respx.route().mock(side_effect=outcomes + [httpx.ConnectError("refused")] * 40)
    texts: list[str] = []
    with caplog.at_level(logging.DEBUG):
        for number in range(len(outcomes) + 1):
            # ⚠️ Another address each time: an answer is kept for a few seconds, the same address would never fail.
            answer = post(admin, "probe", {"integration_id": integration, "path": f"/api/v2/anything?x={number}"})
            texts.append(answer.text)
    sent = [str(call.request.url) + str(dict(call.request.headers)) + call.request.content.decode(errors="ignore") for call in route.calls]
    # The test means something only if the secret did travel to the service.
    assert any(SECRET in one for one in sent), f"{kind}: the secret never left, so nothing was proven ({how})"
    assert all(SECRET not in one for one in texts)
    assert SECRET not in everything_kept()
    assert SECRET not in caplog.text, "a logger wrote the secret down"
