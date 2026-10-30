"""Skins made by the provider of the assistant: the guide it gets, what leaves, what comes back and what is kept.

Never a real provider: ``providers.turn`` is a script here, as for the card help.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services.assistant import providers
from app.skins import ai, css

from .conftest import CSRF, create_user, login, setup_admin
from .test_cards_ai import Script

CONFIG = {"provider": "anthropic", "model": "claude-sonnet-5-5", "base_url": "", "key": "x"}
EXAMPLE = json.loads(ai.EXAMPLE)
CURRENT = {"nexdeck_skin": 1, "key": "mine", "name": "Mine", "tokens": {"radius": 4}, "switches": {"blur": "off"}}


def submitted(skin: dict[str, Any], text: str = "", summary: str = "A console with bricks.", tokens: tuple[int, int] = (0, 0)) -> providers.Turn:
    call = {"id": "call-1", "name": "submit_skin", "input": {"skin": skin, "summary": summary}}
    return providers.Turn(text=text, calls=[call], stop="tools", tokens_in=tokens[0], tokens_out=tokens[1])


def run(ask: ai.Ask, script: Script, monkeypatch: pytest.MonkeyPatch) -> ai.Outcome:
    monkeypatch.setattr(providers, "turn", script)
    return asyncio.run(ai.generate(ask, CONFIG, "key"))


# The guide ------------------------------------------------------------------------------------------------------


def test_the_guide_names_every_part_motion_wave_font_and_property_there_is() -> None:
    guide = ai.guide()
    data = css.registry()
    for name in data["parts"]:
        assert f"- {name}:" in guide, name
    for word in [*ai.schema.MOTIONS, *ai.schema.WAVES, *ai.schema.ANCHORS, *data["fonts"]]:
        assert word in guide, word
    for members in data["groups"].values():
        for prop in members:
            assert prop in guide, prop


def test_the_guide_asks_for_both_modes_and_the_tool_for_a_summary() -> None:
    assert ":mode(dark) or :mode(light)" in ai.guide()
    assert ai.SUBMIT_TOOL["input_schema"]["required"] == ["skin", "summary"]


def test_the_example_in_the_guide_is_a_skin_nexdeck_wears() -> None:
    assert ai.problems_of(EXAMPLE) == []


# What leaves ----------------------------------------------------------------------------------------------------


def test_only_the_request_the_skin_and_the_locks_leave_and_a_picture_only_on_the_second_look(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(submitted({**EXAMPLE, "key": "x"}), submitted({**EXAMPLE, "key": "x"}))
    run(ai.Ask(prompt="Like a console", skin=CURRENT, locked=["tokens"]), script, monkeypatch)
    first = script.seen[0]["transcript"][0]
    assert "Like a console" in first["text"] and '"radius": 4' in first["text"] and "Locked, leave exactly as they are: tokens." in first["text"]
    assert "images" not in first and script.seen[0]["tools"] == [ai.SUBMIT_TOOL]
    pictures = [ai.Picture("dark", "AAAA"), ai.Picture("light", "BBBB", "image/png"), ai.Picture("dusk", "CCCC")]
    run(ai.Ask(prompt="Like a console", skin=CURRENT, review=True, pictures=pictures, audit=["light: card-title: 2.1:1"]), script, monkeypatch)
    second = script.seen[1]["transcript"][0]
    assert second["images"] == [{"media_type": "image/jpeg", "data": "AAAA"}, {"media_type": "image/png", "data": "BBBB"}]
    assert "dark mode and light mode, in this order" in second["text"] and "reads badly in either mode" in second["text"]
    assert "- light: card-title: 2.1:1" in second["text"] and "second look" in second["text"]


def test_a_picture_without_the_second_look_stays_home() -> None:
    _system, transcript = ai.outbound(ai.Ask(prompt="x", skin=CURRENT, pictures=[ai.Picture("dark", "AAAA")]))
    assert "images" not in transcript[0]


def test_a_picture_goes_to_claude_before_the_words_and_to_the_openai_form_as_a_data_address() -> None:
    entry = {"role": "user", "text": "Look", "images": [{"media_type": "image/png", "data": "QUJD"}]}
    claude = providers.to_anthropic([entry])[0]["content"]
    assert claude[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}} and claude[1] == {"type": "text", "text": "Look"}
    openai = providers.to_openai("system", [entry])[1]["content"]
    assert openai == [{"type": "text", "text": "Look"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]
    assert providers.to_anthropic([{"role": "user", "text": "Plain"}])[0]["content"] == "Plain"


# What comes back ------------------------------------------------------------------------------------------------


def test_a_skin_that_passes_is_taken_with_its_key_and_its_locked_sections_as_they_were(monkeypatch: pytest.MonkeyPatch) -> None:
    proposed = {**EXAMPLE, "key": "renamed", "tokens": {"radius": 20}, "switches": {}}
    outcome = run(ai.Ask(prompt="x", skin=CURRENT, locked=["tokens", "switches", "nothing"]), Script(submitted(proposed)), monkeypatch)
    assert outcome.ok and outcome.text == "A console with bricks."
    assert outcome.skin["key"] == "mine" and outcome.skin["tokens"] == {"radius": 4} and outcome.skin["switches"] == {"blur": "off"}
    assert outcome.skin["sprites"] == EXAMPLE["sprites"]


def test_the_summary_handed_in_with_the_skin_is_what_the_editor_shows_and_words_beside_it_only_without_one(monkeypatch: pytest.MonkeyPatch) -> None:
    said = run(ai.Ask(prompt="x", skin=CURRENT), Script(submitted(EXAMPLE, text="Done.", summary="Bricks behind red cards.")), monkeypatch)
    assert said.text == "Bricks behind red cards."
    silent = run(ai.Ask(prompt="x", skin=CURRENT), Script(submitted(EXAMPLE, text="Done.", summary="  ")), monkeypatch)
    assert silent.text == "Done."


def test_the_tokens_of_every_round_are_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = {**EXAMPLE, "css": "[data-part=chip] { color: red !important }"}
    outcome = run(ai.Ask(prompt="x", skin=CURRENT), Script(submitted(broken, tokens=(1000, 200)), submitted(EXAMPLE, tokens=(1500, 300))), monkeypatch)
    assert outcome.ok and (outcome.tokens_in, outcome.tokens_out) == (2500, 500)


def test_a_locked_section_the_skin_did_not_have_stays_out() -> None:
    assert "css" not in ai.kept(ai.Ask(prompt="", skin=CURRENT, locked=["css"]), {**EXAMPLE, "css": "[data-part=chip] { color: #000000 }"})


def test_a_skin_that_fails_goes_back_once_with_its_problems_and_the_second_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = {**EXAMPLE, "css": "[data-part=chip] { color: red !important }"}
    script = Script(submitted(broken), submitted(EXAMPLE))
    outcome = run(ai.Ask(prompt="x", skin=CURRENT), script, monkeypatch)
    assert outcome.ok
    told = script.seen[1]["transcript"][-1]
    assert told["role"] == "tool" and told["results"][0]["is_error"] and "!important" in told["results"][0]["content"]


def test_a_skin_that_fails_twice_is_shown_with_its_problems_and_not_a_third_time_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = {**EXAMPLE, "native": "retro"}
    script = Script(submitted(broken), submitted(broken), submitted(EXAMPLE))
    outcome = run(ai.Ask(prompt="x", skin=CURRENT), script, monkeypatch)
    assert not outcome.ok and outcome.problems and len(script.seen) == 2


def test_a_skin_in_a_json_block_instead_of_the_tool_is_taken_too(monkeypatch: pytest.MonkeyPatch) -> None:
    turn = providers.Turn(text=f"Here it is:\n```json\n{json.dumps(EXAMPLE)}\n```")
    assert run(ai.Ask(prompt="x", skin=CURRENT), Script(turn), monkeypatch).ok


def test_an_answer_without_a_skin_is_a_problem_the_provider_is_told(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(providers.Turn(text="I would rather not."), providers.Turn(text="Still no."))
    outcome = run(ai.Ask(prompt="x", skin=CURRENT), script, monkeypatch)
    assert not outcome.ok and "submit_skin" in outcome.problems[0]["message"]
    assert script.seen[1]["transcript"][-1]["role"] == "user"


# The routes -----------------------------------------------------------------------------------------------------


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    setup_admin(client)
    return client


def switch_on(client: TestClient, **more: Any) -> None:
    done = client.put("/api/v1/settings/assistant", json={"provider": "anthropic", "model": "", "key": "sk-ant-test", **more}, headers=CSRF)
    assert done.status_code == 200, done.text


def test_without_a_provider_the_editor_offers_no_tab_and_the_call_says_so(admin: TestClient) -> None:
    assert admin.get("/api/v1/skins/schema").json()["ai"] == {"ready": False, "vision": False}
    answer = admin.post("/api/v1/skins/ai", json={"prompt": "x", "skin": CURRENT}, headers=CSRF)
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "assistant_off"


def test_claude_sees_a_picture_and_a_service_of_the_openai_form_only_when_switched_on(admin: TestClient) -> None:
    switch_on(admin)
    assert admin.get("/api/v1/skins/schema").json()["ai"] == {"ready": True, "vision": True}
    local = {"provider": "openai", "base_url": "http://ollama:11434/v1", "model": "llama3", "key": ""}
    assert admin.put("/api/v1/settings/assistant", json=local, headers=CSRF).status_code == 200
    assert admin.get("/api/v1/skins/schema").json()["ai"] == {"ready": True, "vision": False}
    refused = admin.post("/api/v1/skins/ai", json={"prompt": "x", "skin": CURRENT, "review": True, "pictures": [{"mode": "dark", "data": "AAAA"}]}, headers=CSRF)
    assert refused.status_code == 400
    assert admin.put("/api/v1/settings/assistant", json={**local, "vision": True}, headers=CSRF).json()["vision"] is True
    assert admin.get("/api/v1/skins/schema").json()["ai"]["vision"] is True
    assert admin.put("/api/v1/settings/assistant", json=local, headers=CSRF).json()["vision"] is True, "left out keeps it"


def test_the_route_answers_with_the_skin_and_only_administrators_may(admin: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    switch_on(admin)
    monkeypatch.setattr(providers, "turn", Script(submitted(EXAMPLE, tokens=(4321, 765))))
    with caplog.at_level("INFO", logger="nexdeck.skins"):
        answer = admin.post("/api/v1/skins/ai", json={"prompt": "A console", "skin": CURRENT, "locked": ["tokens"]}, headers=CSRF)
    assert answer.status_code == 200, answer.text
    assert answer.json()["ok"] and answer.json()["skin"]["key"] == "mine" and answer.json()["skin"]["tokens"] == {"radius": 4}
    assert answer.json()["text"] == "A console with bricks."
    assert "had a skin made by the assistant (4321 tokens in, 765 out)." in caplog.text
    assert admin.delete("/api/v1/skins/ai", headers=CSRF).json() == {"cancelled": False}
    create_user(admin, "ann")
    login(admin, "ann", "another-long-password")
    assert admin.post("/api/v1/skins/ai", json={"prompt": "x", "skin": CURRENT}, headers=CSRF).status_code == 403


def test_the_stage_comes_in_two_modes_at_most_and_only_as_dark_or_light(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(admin)
    script = Script(submitted(EXAMPLE))
    monkeypatch.setattr(providers, "turn", script)
    body = {"prompt": "x", "skin": CURRENT, "review": True}
    dusk = admin.post("/api/v1/skins/ai", json={**body, "pictures": [{"mode": "dusk", "data": "AAAA"}]}, headers=CSRF)
    three = admin.post("/api/v1/skins/ai", json={**body, "pictures": [{"mode": "dark", "data": "A"}, {"mode": "light", "data": "B"}, {"mode": "dark", "data": "C"}]}, headers=CSRF)
    gif = admin.post("/api/v1/skins/ai", json={**body, "pictures": [{"mode": "dark", "data": "A", "media_type": "image/gif"}]}, headers=CSRF)
    assert (dusk.status_code, three.status_code, gif.status_code) == (422, 422, 400) and script.seen == []
    both = admin.post("/api/v1/skins/ai", json={**body, "pictures": [{"mode": "dark", "data": "A"}, {"mode": "light", "data": "B"}]}, headers=CSRF)
    assert both.status_code == 200 and [image["data"] for image in script.seen[0]["transcript"][0]["images"]] == ["A", "B"]


def test_a_provider_that_fails_says_so_in_its_own_words(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_on(admin)
    monkeypatch.setattr(providers, "turn", Script(providers.AssistantError("rate_limited", "busy", "Your credit balance is too low.")))
    answer = admin.post("/api/v1/skins/ai", json={"prompt": "x", "skin": CURRENT}, headers=CSRF)
    assert answer.status_code == 502 and answer.json()["detail"] == {"code": "ai_limit", "message": "Your credit balance is too low."}
