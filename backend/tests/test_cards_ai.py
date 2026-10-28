"""The card written by the provider of the assistant: what leaves, what comes back, what is taken over (KARTEN-17).

⚠️ No real provider is asked: ``providers.turn`` is a script that records what it was sent.
"""

from __future__ import annotations

import asyncio
import json
import typing
from typing import Any

import pytest

from app.cards import ai, load, schema
from app.cards.blocks import Block
from app.services.assistant import providers

from .cards_sample import VALUE_CARD

CONFIG = {"provider": "anthropic", "model": "claude-sonnet-5-5", "base_url": ""}
#: Values that must not leave without the tick: one as a value, one as a number, one as a key that is data.
SECRET_TEXT = "Zq-Marker-Alpha"
SECRET_NUMBER = 918273645
SECRET_KEY = "9f86d081884c7d659a2feaa0"
ANSWER = {"totalRecords": SECRET_NUMBER, "records": [{"title": SECRET_TEXT, "size": 5}], "byHash": {SECRET_KEY: {"name": "x"}}}


class Script:
    def __init__(self, *turns: providers.Turn | Exception) -> None:
        self.turns = list(turns)
        self.seen: list[dict[str, Any]] = []

    async def __call__(self, settings: dict, key: str, system: str, transcript: list[dict], tools: list[dict]) -> providers.Turn:
        self.seen.append({"system": system, "transcript": [dict(entry) for entry in transcript], "tools": tools})
        step = self.turns.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def sent(self) -> str:
        return json.dumps(self.seen, default=str)


def card(text: str = ai.EXAMPLE) -> providers.Turn:
    return providers.Turn(text=f"```yaml\n{text}```")


def run(ask: ai.Ask, script: Script, monkeypatch: pytest.MonkeyPatch) -> ai.Outcome:
    monkeypatch.setattr(providers, "turn", script)
    return asyncio.run(ai.generate(ask, CONFIG, "key"))


def new(**more: Any) -> ai.Ask:
    return ai.Ask(mode="new", description="Show my queue", connection_kind="sonarr", path="/api/v3/queue", answer=ANSWER, **more)


def test_karten17_the_lists_of_forms_and_blocks_are_the_ones_of_the_schema() -> None:
    forms = set(schema.json_schema()["discriminator"]["mapping"])
    kinds = {typing.get_args(model.model_fields["type"].annotation)[0] for model in typing.get_args(typing.get_args(Block)[0])}
    assert set(ai.FORMS) == forms and set(ai.BLOCKS) == kinds
    assert load.load_definition(ai.EXAMPLE).definition.form == "list", "the example the provider is shown is a valid card"


def test_karten17_ac2_without_the_tick_no_value_of_the_probe_leaves(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(card())
    result = run(new(), script, monkeypatch)
    assert result.ok and result.sent == {"values": False}
    sent = script.sent()
    for secret in (SECRET_TEXT, str(SECRET_NUMBER), SECRET_KEY):
        assert secret not in sent
    outgoing = ai.outbound(new()).message
    assert "records[0].title: string" in outgoing and "records: array (1 entries)" in outgoing and "byHash.<key>: object" in outgoing
    assert "Show my queue" in outgoing and "sonarr" in outgoing and "/api/v3/queue" in outgoing


def test_karten17_ac3_the_tick_sends_the_values_of_that_one_request_but_never_a_key_that_is_data(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(card())
    result = run(new(include_values=True), script, monkeypatch)
    assert result.sent == {"values": True}
    sent = script.sent()
    assert SECRET_TEXT in sent and str(SECRET_NUMBER) in sent
    assert SECRET_KEY not in sent
    assert len(ai.shape({"a": "x" * 500}, values=True)) < 300, "a text is cut"
    assert ai.shape({"a": list(range(30))}, values=True).count("a[") == ai.VALUE_ENTRIES


def test_karten17_ac4_a_card_that_fails_the_check_is_sent_back_once_with_its_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = ai.EXAMPLE.replace("form: list", "form: carousel")
    script = Script(providers.Turn(text="", calls=[{"id": "t1", "name": "submit_card", "input": {"yaml": broken}}], stop="tools"), card())
    result = run(new(), script, monkeypatch)
    assert result.ok and len(script.seen) == 2
    again = script.seen[1]["transcript"]
    assert [entry["role"] for entry in again] == ["user", "assistant", "tool"]
    assert again[2]["results"][0]["is_error"] is True and "did not accept" in again[2]["results"][0]["content"]


def test_karten17_ec2_a_second_failure_shows_what_was_there_and_takes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = ai.EXAMPLE.replace("form: list", "form: carousel")
    script = Script(card(broken), card(broken))
    result = run(new(), script, monkeypatch)
    assert result.ok is False and len(script.seen) == 2, "asked once more, not a third time"
    assert result.yaml.strip() == broken.strip() and result.problems
    assert result.body()["problems"] == result.problems and result.body()["summary"]["form"] is None


@pytest.mark.parametrize("fault", [
    "path: /api/v3/queue?apikey=" + "0123456789abcdef" * 2, "path: http://evil.example.com/steal",
])
def test_karten17_ec3_a_secret_or_a_host_of_its_own_is_refused_like_in_any_definition(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    bad = ai.EXAMPLE.replace("path: /api/v3/queue", fault)
    result = run(new(), Script(card(bad), card(bad)), monkeypatch)
    assert result.ok is False and result.problems
    assert {problem["code"] for problem in result.problems} & {"card_secret_value", "card_bad_path", "card_secret_key"}


def test_karten17_the_kind_of_the_connection_must_be_required_by_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    other = ai.EXAMPLE.replace("requires: [sonarr]", "requires: [radarr]")
    result = run(new(), Script(card(other), card(other)), monkeypatch)
    assert result.ok is False and result.problems[0]["code"] == "ai_wrong_kind"


def test_karten17_ac6_a_change_sends_the_card_without_its_examples_and_keeps_them(monkeypatch: pytest.MonkeyPatch) -> None:
    ask = ai.Ask(mode="change", description="make the numbers bigger", yaml=VALUE_CARD)
    changed = VALUE_CARD.replace("Example Author", "Another Author")
    changed_without_demo, _ = ai.without_demo(changed)
    script = Script(card(changed_without_demo))
    result = run(ask, script, monkeypatch)
    assert result.ok and "Another Author" in result.yaml
    assert "totalRecords: 4" not in script.sent(), "the examples stay at home"
    assert "totalRecords: 4" in result.yaml, "and come back with the new card"
    assert load.load_definition(result.yaml).definition.demo

    script = Script(card(changed))
    run(ai.Ask(mode="change", description="x", yaml=VALUE_CARD, include_values=True), script, monkeypatch)
    assert "totalRecords: 4" in script.sent(), "with the tick they go along"


def test_karten17_ac6_a_change_keeps_the_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    other = VALUE_CARD.replace("slug: queue-size", "slug: something-else")
    result = run(ai.Ask(mode="change", description="x", yaml=VALUE_CARD), Script(card(other), card(other)), monkeypatch)
    assert result.ok is False and result.problems[0]["code"] == "ai_slug_changed"


def test_karten17_ac7_a_translation_adds_languages_and_changes_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    old = ai.EXAMPLE
    good = old.replace("name: {en: Download queue, de: Warteschlange}", "name: {en: Download queue, de: Warteschlange, es: Cola, fr: File, it: Coda}")
    result = run(ai.Ask(mode="translate", yaml=old), Script(card(good)), monkeypatch)
    assert result.ok and "es: Cola" in result.yaml
    # A plain text may become one per language when it stays among them.
    plain = old.replace("name: {en: Download queue, de: Warteschlange}", "name: Download queue")
    grown = old.replace("name: {en: Download queue, de: Warteschlange}", "name: {en: Download queue, de: Warteschlange}")
    assert run(ai.Ask(mode="translate", yaml=plain), Script(card(grown)), monkeypatch).ok
    # A changed word, a changed path or a changed threshold is not a translation.
    for sneaky in (good.replace("de: Warteschlange", "de: Schlange"), good.replace("limit: 8", "limit: 9"), good.replace("/api/v3/queue", "/api/v3/other")):
        result = run(ai.Ask(mode="translate", yaml=old), Script(card(sneaky), card(sneaky)), monkeypatch)
        assert result.ok is False and result.problems[0]["code"] == "ai_translate_changed", sneaky


def test_karten17_ec1_ec4_the_failures_of_the_provider_are_told_in_its_words(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(error: Exception) -> ai.AiError:
        with pytest.raises(ai.AiError) as caught:
            run(new(), Script(error), monkeypatch)
        return caught.value

    limit = failing(providers.AssistantError("rate_limited", "busy", "Your credit balance is too low."))
    assert (limit.code, limit.message) == ("ai_limit", "Your credit balance is too low.")
    assert failing(providers.AssistantError("provider", "HTTP 400", "Your credit balance is too low.")).code == "ai_limit"
    assert failing(providers.AssistantError("unreachable", "Anthropic could not be reached.")).code == "ai_unreachable"
    assert failing(providers.AssistantError("auth", "Anthropic refused the key.")).code == "ai_failed"
    assert failing(providers.AssistantError("off", "off")).code == "assistant_off"

    async def never(*_args: object) -> providers.Turn:
        await asyncio.Event().wait()
        raise AssertionError

    monkeypatch.setattr(ai, "TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(providers, "turn", never)
    with pytest.raises(ai.AiError) as caught:
        asyncio.run(ai.generate(new(), CONFIG, "key"))
    assert caught.value.code == "ai_unreachable"


def test_karten17_ac8_one_request_per_administrator_and_it_can_be_cancelled() -> None:
    async def scenario() -> None:
        release = asyncio.Event()

        async def work() -> str:
            await release.wait()
            return "done"

        first = asyncio.ensure_future(ai.supervised(1, work()))
        await asyncio.sleep(0)
        with pytest.raises(ai.Busy):
            await ai.supervised(1, work())
        other = asyncio.ensure_future(ai.supervised(2, work()))
        await asyncio.sleep(0)
        assert ai.cancel(1) is True
        assert await first == (False, None)
        release.set()
        assert await other == (True, "done")
        assert ai.RUNNING == {}

    asyncio.run(scenario())
