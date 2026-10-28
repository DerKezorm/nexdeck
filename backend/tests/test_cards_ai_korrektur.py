"""What the review of the card help found (Etappe 7): what leaves even with the tick, the examples of a card, what a translation may change.

⚠️ No real provider is asked: ``providers.turn`` is a script that records what it was sent.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.cards import ai, load
from app.services.collector import collector

from .conftest import CSRF, setup_admin
from .karten8_sample import DOWNLOADS
from .test_cards_ai import Script, card, run
from .test_cards_ai_routes import switch_on


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    return client


KEY_OF_THE_CONNECTION = "apikeyzeta998877aabbccdd"
#: Values a service may answer with that must not leave in any case, and the values that may.
HARD = {
    "credential": KEY_OF_THE_CONNECTION,
    "token": "tok_Q9vX2mK7pL4wZ8rT",
    "host": "kellerbox-omega.heimnetz.lan",
    "ip": "10.77.66.55",
    "mail": "erika.probe@example.org",
    "address_host": "nas-omega.heimnetz.lan",
    "ip_in_text": "10.77.66.57",
    "login": "erikamustermann-login",
    "session": "sessionvalue-4711",
}
SOFT = "Zq-Wert-Textmarke"
ANSWER = {
    "totalRecords": 73914628,
    "apiKey": HARD["credential"],
    "records": [
        {
            "title": SOFT, "host": HARD["host"], "ip": HARD["ip"], "mail": HARD["mail"], "token": HARD["token"], "size": 5,
            "link": f"http://{HARD['address_host']}:8989/series/big-bang?page=2", "note": f"seen from {HARD['ip_in_text']} today",
            "user": HARD["login"], "settings": {"sessionId": HARD["session"]},
        }
    ],
}


def values_of(answer: Any) -> ai.Ask:
    return ai.Ask(mode="new", description="Show my queue", connection_kind="sonarr", path="/api/v3/queue", answer=answer, include_values=True)


def test_karten17_ac3_even_with_the_tick_no_credential_host_address_or_mail_leaves() -> None:
    message = ai.outbound(values_of(ANSWER)).message
    for name, value in HARD.items():
        assert value not in message, name
    assert SOFT in message and "73914628" in message and "/series/big-bang" in message, "the rest of the values goes along"
    assert 'apiKey: string = "***"' in message and 'records[0].token: string = "***"' in message
    assert 'records[0].host: string = "example.com"' in message and 'records[0].ip: string = "192.0.2.1"' in message
    assert 'records[0].mail: string = "user@example.com"' in message
    assert "http://example.com:8989/series/big-bang" not in message, "the host of an address is example.com, the port is part of the host"
    assert "records[0].link: string = \"http://example.com/series/big-bang\"" in message
    assert "seen from 192.0.2.1 today" in message
    assert 'records[0].user: string = "***"' in message and 'sessionId: string = "***"' in message


def test_karten17_ac3_a_key_with_a_secret_shape_is_replaced_by_the_scanner_of_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    message = ai.outbound(values_of({"records": [{"title": SOFT, "note": secret, "other": f"Bearer {secret}"}]})).message
    assert secret not in message and SOFT in message
    script = Script(card())
    result = run(values_of(ANSWER), script, monkeypatch)
    assert result.ok and not any(value in script.sent() for value in HARD.values())




def test_karten17_ac6_the_keys_that_are_data_go_as_numbered_stand_ins_in_the_shape() -> None:
    answer = {
        "records": [], "AKIAIOSFODNN7EXAMPLE": {"a": 1}, "c0ffee00deadbeef12345678": {"a": 2}, "two words": {"a": 3}, "x" * 60: {"a": 4},
        "nas.heimnetz.lan": {"a": 5}, "queue_size": 1, "Queue": 2,
    }
    plain = ai.shape(answer)
    for data_key in ("AKIAIOSFODNN7EXAMPLE", "c0ffee00deadbeef12345678", "two words", "x" * 60, "nas.heimnetz.lan"):
        assert data_key not in plain
    assert "<key1>: object" in plain and "<key2>" not in plain, "the first stands for the others"
    assert "queue_size: number" in plain and "Queue: number" in plain, "names stay"
    with_values = ai.shape(answer, values=True)
    assert "<key1>.a: number = 1" in with_values and "<key5>.a: number = 5" in with_values
    assert "AKIAIOSFODNN7EXAMPLE" not in with_values


DEMO_CARD = """\
nexdeck-card: 1
slug: probe-card
name: Probe
version: 1.0.0
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: {path: totalRecords, label: Total}
demo:
  queue:
    totalRecords: 4
    title: DEMOWERT-Block-Eins
"""
SPELLINGS = {
    "block": DEMO_CARD,
    "flow_multiline": DEMO_CARD.replace("demo:\n  queue:\n    totalRecords: 4\n    title: DEMOWERT-Block-Eins\n", "demo: {queue: {totalRecords: 4,\ntitle: DEMOWERT-Block-Eins}}\n"),
    "quoted_key": DEMO_CARD.replace("demo:", '"demo":'),
    "json_card": json.dumps(yaml.safe_load(DEMO_CARD)),
    "comment_between": DEMO_CARD.replace("    totalRecords: 4\n", "    totalRecords: 4\n# a note in column 0\n"),
    "comment_before": "# demo: nothing here\n" + DEMO_CARD,
    "demo_last_with_dash_list": DEMO_CARD.replace("    title: DEMOWERT-Block-Eins\n", "    rows:\n    - DEMOWERT-Block-Eins\n"),
}








def dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
















