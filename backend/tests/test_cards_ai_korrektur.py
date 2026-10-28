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


def test_karten17_ac3_the_examples_of_a_card_go_through_the_same_filter_with_the_tick() -> None:
    data = yaml.safe_load(DOWNLOADS)
    data["demo"] = {"torrents": [{"name": SOFT, "host": HARD["host"], "ip": HARD["ip"], "apiKey": HARD["credential"], "mail": HARD["mail"], "c0ffee00deadbeef12345678": 1}]}
    text = yaml.safe_dump(data, sort_keys=False)
    without = ai.outbound(ai.Ask(mode="change", description="x", yaml=text)).message
    assert SOFT not in without and "demo" not in without
    with_tick = ai.outbound(ai.Ask(mode="change", description="x", yaml=text, include_values=True)).message
    assert SOFT in with_tick
    for value in (*HARD.values(), "c0ffee00deadbeef12345678"):
        assert value not in with_tick, value
    assert "<key1>" in with_tick and "example.com" in with_tick and "user@example.com" in with_tick


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


@pytest.mark.parametrize("spelling", list(SPELLINGS))
def test_karten17_ac6_a_change_without_the_tick_takes_the_demo_out_in_every_spelling(spelling: str, monkeypatch: pytest.MonkeyPatch) -> None:
    text = SPELLINGS[spelling]
    assert load.load_definition(text).definition.demo, "the card is valid"
    sent = ai.outbound(ai.Ask(mode="change", description="x", yaml=text)).message
    assert "DEMOWERT-Block-Eins" not in sent and "totalRecords: 4" not in sent
    # The card that comes back has no examples; the old ones are put back, whatever the spelling was.
    answer = yaml.safe_dump(yaml.safe_load(DEMO_CARD) | {"name": "Bigger"}, sort_keys=False)
    answer = answer.split("demo:")[0]
    result = run(ai.Ask(mode="change", description="x", yaml=text), Script(card(answer)), monkeypatch)
    assert result.ok and "Bigger" in result.yaml
    assert load.load_definition(result.yaml).definition.demo["queue"]["totalRecords"] == 4


def test_karten17_ac6_a_card_that_cannot_be_read_as_yaml_is_not_sent_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = "demo: {a: [1,\nname: x"
    script = Script()
    with pytest.raises(ai.AiError) as caught:
        run(ai.Ask(mode="change", description="x", yaml=broken), script, monkeypatch)
    assert caught.value.code == "bad_request" and script.seen == []


def test_karten17_ac6_with_the_tick_the_examples_that_came_back_unchanged_are_the_real_ones_again(monkeypatch: pytest.MonkeyPatch) -> None:
    data = yaml.safe_load(DEMO_CARD)
    data["demo"]["queue"]["apiKey"] = HARD["credential"]
    text = yaml.safe_dump(data, sort_keys=False)
    sent = ai.outbound(ai.Ask(mode="change", description="x", yaml=text, include_values=True)).message
    echoed = sent.split("```yaml\n", 1)[1].split("```", 1)[0]
    assert "'***'" in echoed or '"***"' in echoed
    result = run(ai.Ask(mode="change", description="x", yaml=text, include_values=True), Script(card(echoed)), monkeypatch)
    assert result.ok
    assert load.load_definition(result.yaml).definition.demo["queue"]["apiKey"] == HARD["credential"], "not the stand-in"
    # Examples the provider wrote itself stay.
    own = yaml.safe_load(echoed)
    own["demo"]["queue"]["title"] = "Written by the provider"
    result = run(ai.Ask(mode="change", description="x", yaml=text, include_values=True), Script(card(yaml.safe_dump(own, sort_keys=False))), monkeypatch)
    assert load.load_definition(result.yaml).definition.demo["queue"]["title"] == "Written by the provider"


def dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def test_karten17_ac7_a_translation_may_not_change_what_a_button_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    data = yaml.safe_load(DOWNLOADS)
    data["buttons"][0]["send"] = "json"
    data["buttons"][0]["body"] = {"hashes": "{hash}", "text": "pause now", "name": "x"}
    old = dump(data)
    load.load_definition(old)
    changed = yaml.safe_load(old)
    changed["buttons"][0]["body"]["text"] = {"en": "pause now", "de": "BODY-GEAENDERT"}
    changed["buttons"][0]["body"]["name"] = {"en": "x", "it": "ALTRO"}
    result = run(ai.Ask(mode="translate", yaml=old), Script(card(dump(changed)), card(dump(changed))), monkeypatch)
    assert result.ok is False and result.problems[0]["code"] == "ai_translate_changed"
    # The label of the same button is a text of the schema and may gain languages.
    label = yaml.safe_load(old)
    label["buttons"][0]["label"] = {**data["buttons"][0]["label"], "it": "Pausa"}
    assert run(ai.Ask(mode="translate", yaml=old), Script(card(dump(label))), monkeypatch).ok


def test_karten17_ac7_a_translation_never_takes_the_examples_of_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    changed = yaml.safe_load(DOWNLOADS)
    changed["demo"] = {"torrents": [{"name": "VOM-ANBIETER-ERFUNDEN", "hash": "zz", "progress": 1}]}
    changed["name"] = {**changed["name"], "fr": "Téléchargements"}
    old_examples = load.load_definition(DOWNLOADS).definition.demo
    result = run(ai.Ask(mode="translate", yaml=DOWNLOADS), Script(card(dump(changed))), monkeypatch)
    assert result.ok and "VOM-ANBIETER-ERFUNDEN" not in result.yaml and "Téléchargements" in result.yaml
    assert load.load_definition(result.yaml).definition.demo == old_examples


def test_karten17_ac7_a_plain_text_stays_the_english_one(monkeypatch: pytest.MonkeyPatch) -> None:
    old = ai.EXAMPLE.replace("name: {en: Download queue, de: Warteschlange}", "name: Download queue")
    moved = ai.EXAMPLE.replace("name: {en: Download queue, de: Warteschlange}", "name: {en: Something else entirely, de: Download queue}")
    result = run(ai.Ask(mode="translate", yaml=old), Script(card(moved), card(moved)), monkeypatch)
    assert result.ok is False and result.problems[0]["code"] == "ai_translate_changed"
    kept = ai.EXAMPLE.replace("name: {en: Download queue, de: Warteschlange}", "name: {en: Download queue, de: Warteschlange, fr: File}")
    assert run(ai.Ask(mode="translate", yaml=old), Script(card(kept)), monkeypatch).ok
    # A language that was there may not go either.
    gone = ai.EXAMPLE.replace("name: {en: Download queue, de: Warteschlange}", "name: {en: Download queue}")
    assert run(ai.Ask(mode="translate", yaml=ai.EXAMPLE), Script(card(gone), card(gone)), monkeypatch).ok is False


def test_karten17_ac10_the_summary_is_made_from_the_card_that_came_back_not_from_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    moved = ai.EXAMPLE.replace("requires: [sonarr]", "requires: [radarr]").replace("path: /api/v3/queue", "path: /api/v3/history")
    ask = ai.Ask(mode="change", description="x", yaml=ai.EXAMPLE, connection_kind="sonarr", path="/api/v3/queue", answer={"records": []})
    result = run(ask, Script(card(moved)), monkeypatch)
    assert result.ok
    assert result.summary["connection_kind"] == "radarr" and result.summary["path"] == "/api/v3/history"
    assert result.summary["requires"] == ["radarr"] and result.summary["paths"] == ["/api/v3/history"]

    two = ai.EXAMPLE.replace("requests:\n", "requests:\n  - id: more\n    path: /api/v3/series\n")
    result = run(ask, Script(card(two)), monkeypatch)
    assert result.ok and result.summary["paths"] == ["/api/v3/series", "/api/v3/queue"] and result.summary["path"] == "/api/v3/series, /api/v3/queue"


def test_karten17_ac10_the_summary_names_the_methods_of_the_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    data = yaml.safe_load(DOWNLOADS)
    data.pop("demo")
    start = ai.Ask(mode="new", description="downloads", connection_kind=data["requires"][0], path=data["requests"][0]["path"], answer=[{"name": "a", "hash": "b", "progress": 1}])
    result = run(start, Script(card(dump(data))), monkeypatch)
    assert result.ok and result.summary["buttons"] is True
    assert result.summary["methods"] == sorted({button["method"] for button in data["buttons"]})
    plain = run(start.__class__(mode="new", description="x", connection_kind="sonarr", path="/api/v3/queue", answer={}), Script(card()), monkeypatch)
    assert plain.summary["buttons"] is False and plain.summary["methods"] == []


@pytest.mark.parametrize("debug", [False, True])
def test_karten17_ac8_the_routes_end_a_request_from_another_thread_than_the_one_it_runs_on(debug: bool) -> None:
    """``DELETE /cards/ai`` and switching the provider off run in a worker thread; the task lives on the loop of the server."""
    loop = asyncio.new_event_loop()
    loop.set_debug(debug)
    started = threading.Event()
    outcome: dict[str, Any] = {}

    async def hang() -> str:
        await asyncio.Event().wait()
        return "never"

    async def main() -> None:
        job = asyncio.ensure_future(ai.supervised(4711, hang()))
        await asyncio.sleep(0)
        started.set()
        outcome["result"] = await job

    runner = threading.Thread(target=loop.run_until_complete, args=(main(),), daemon=True)
    runner.start()
    assert started.wait(5)
    assert ai.cancel(4711) is True, "nothing raises, in debug mode neither"
    runner.join(5)
    assert not runner.is_alive(), "the task ended by itself"
    assert outcome["result"] == (False, None) and ai.RUNNING == {}
    loop.close()
    assert ai.cancel(4711) is False


def test_karten17_ec6_the_provider_taken_away_ends_every_request_from_another_thread() -> None:
    loop = asyncio.new_event_loop()
    started = threading.Event()
    results: list[Any] = []

    async def hang() -> str:
        await asyncio.Event().wait()
        return "never"

    async def main() -> None:
        jobs = [asyncio.ensure_future(ai.supervised(number, hang())) for number in (1, 2)]
        await asyncio.sleep(0)
        started.set()
        results.extend(await asyncio.gather(*jobs))

    runner = threading.Thread(target=loop.run_until_complete, args=(main(),), daemon=True)
    runner.start()
    assert started.wait(5)
    assert ai.cancel_all() == 2
    runner.join(5)
    assert not runner.is_alive() and results == [(False, None), (False, None)] and ai.RUNNING == {}
    loop.close()


def test_karten17_ac9_the_state_of_the_assistant_names_the_service_the_questions_go_to(admin: TestClient) -> None:
    switch_on(admin)
    assert admin.get("/api/v1/assistant").json()["service"] == "", "Claude is Claude"
    done = admin.put("/api/v1/settings/assistant", json={"provider": "openai", "base_url": "https://llm.example.org:8443/v1", "model": "m", "key": "k"}, headers=CSRF)
    assert done.status_code == 200, done.text
    state = admin.get("/api/v1/assistant").json()
    assert state["service"] == "llm.example.org:8443" and "k" != state["service"]
    assert "base_url" not in state and "key" not in json.dumps(state)
