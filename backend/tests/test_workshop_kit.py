"""The kit of the workshop repository (KARTEN-13): it judges a card the way nexdeck does, with no nexdeck beside it.

``tools/workshop_kit.py`` copies the modules that check a card and writes ``check.py``; the actions of the workshop
repository run that. These tests build the kit into a folder of its own and run it in a fresh Python (``-I``, another
working directory), so that a module the kit forgot to take along fails here and not in the repository.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app import __version__

TOOL = Path(__file__).resolve().parent.parent / "tools" / "workshop_kit.py"

GOOD = """\
nexdeck-card: 1
slug: queue-size
name: {en: Queue size, de: Warteschlange}
version: 1.0.0
description: How many items wait in the queue.
requires: [jsonapi]
requests: [{id: q, path: /api/queue}]
form: value
value: {path: count, label: Queue, format: number}
demo:
  q: {count: 7}
"""

WITH_BUTTON = (
    GOOD.replace("slug: queue-size", "slug: queue-flush")
    + """\
buttons:
  - {id: flush, label: Flush, method: POST, path: /api/queue/flush, confirm: true}
"""
)

INTEGRATION = """\
nexdeck: integration
short: example-box
name: Example box
category: other
fields:
  - {name: user, label: User, required: true}
  - {name: password, type: secret, label: Password, required: true}
auth:
  type: session
  login: /api/login
  send: json
  body: {username: "{user}", password: "{password}"}
  ticket: {from: json, at: token}
  pass: {as: header, header: Authorization, value: "Bearer {ticket}"}
test: /api/status
reads:
  - {path: /api/items, label: Items}
"""

OPEN_INTEGRATION = """\
nexdeck: integration
short: example-box
name: Example box
category: other
auth: {type: none}
test: /api/status
"""


def _load_tool() -> Any:
    spec = importlib.util.spec_from_file_location("workshop_kit_tool", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("workshop")
    _load_tool().build(out, page=False)
    return out


def _run(made: Path, tmp_path: Path, text: str, *more: str) -> tuple[int, dict[str, Any]]:
    """The kit on a file, the way the action runs it: a fresh interpreter, another working directory."""
    source = tmp_path / "submission.yaml"
    source.write_text(text, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(made / "kit" / "check.py"), str(source), *more],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert done.stdout.strip(), done.stderr
    return done.returncode, json.loads(done.stdout)


def _codes(result: dict[str, Any]) -> list[str]:
    return [problem["code"] for problem in result["problems"]]


def test_karten13_kit_has_what_the_action_needs(made: Path) -> None:
    kit = made / "kit"
    version = json.loads((kit / "VERSION").read_text(encoding="utf-8"))
    assert version["nexdeck"] == __version__
    assert version["commit"]
    assert (kit / "check.py").is_file()
    assert "pydantic==" in (kit / "requirements.txt").read_text(encoding="utf-8")
    assert json.loads((made / "schema" / "card.schema.json").read_text(encoding="utf-8"))["title"] == "nexdeck card"
    assert json.loads((made / "schema" / "integration.schema.json").read_text(encoding="utf-8"))["properties"]["nexdeck"]


def test_karten13_kit_needs_no_nexdeck_source(made: Path, tmp_path: Path) -> None:
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import nexdeck_kit.adapters.custom, nexdeck_kit.cards.load, nexdeck_kit.cards.integration;"
        "print([name for name in sys.modules if name == 'app' or name.startswith('app.')])"
    )
    done = subprocess.run([sys.executable, "-I", "-c", probe, str(made / "kit")], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_karten13_good_card_is_read_only_and_drawn_from_its_demo(made: Path, tmp_path: Path) -> None:
    code, result = _run(made, tmp_path, GOOD)
    assert code == 0 and result["ok"], result["problems"]
    assert result["type"] == "card" and result["class"] == "read"
    assert result["slug"] == "queue-size" and result["version"] == "1.0.0"
    assert result["name"] == {"en": "Queue size", "de": "Warteschlange"}
    assert result["requires"] == ["jsonapi"] and result["buttons"] == []
    assert result["reads"] == [{"kind": "jsonapi", "path": "/api/queue"}]
    assert result["widget_data"]["primary"]["value"] == 7


def test_karten13_card_with_buttons_is_classed_by_its_buttons(made: Path, tmp_path: Path) -> None:
    code, result = _run(made, tmp_path, WITH_BUTTON)
    assert code == 0, result["problems"]
    assert result["class"] == "buttons"
    assert result["buttons"] == [{"label": "Flush", "method": "POST", "path": "/api/queue/flush"}]
    assert result["widget_data"]["actions"][0]["label"] == "Flush"


def test_karten13_integration_with_a_login_is_classed_login(made: Path, tmp_path: Path) -> None:
    code, result = _run(made, tmp_path, INTEGRATION)
    assert code == 0, result["problems"]
    assert result["type"] == "integration" and result["class"] == "login" and result["slug"] == "example-box"
    assert result["reads"] == [{"kind": "custom:example-box", "path": "/api/items"}]
    assert result["read_labels"] == ["Items"]
    code, result = _run(made, tmp_path, OPEN_INTEGRATION)
    assert code == 0, result["problems"]
    assert result["class"] == "read"


BROKEN = [
    ("card_bad_path", GOOD.replace("path: /api/queue}", "path: https://evil.example.com/queue}")),
    ("card_secret_value", GOOD.replace("path: /api/queue}", 'path: "/api/queue?apikey=' + "0123456789abcdef" * 2 + '"}')),
    ("card_needs_demo", GOOD.split("demo:")[0]),
    ("card_needs_newer", GOOD.replace("version: 1.0.0", "version: 1.0.0\nmin_nexdeck: 99.0.0")),
    ("card_unknown_kind", GOOD.replace("[jsonapi]", "[nosuchservice]")),
    ("command_refused", GOOD.replace("path: /api/queue}", 'path: "/api/queue?cmd=reboot"}')),
    ("card_needs_english", GOOD.replace("{en: Queue size, de: Warteschlange}", "{de: Warteschlange}")),
    ("card_bad_path", WITH_BUTTON.replace("path: /api/queue/flush", "path: //evil.example.com/flush")),
]


@pytest.mark.parametrize(("expected", "text"), BROKEN, ids=[f"{index}-{code}" for index, (code, _) in enumerate(BROKEN)])
def test_karten13_broken_cards_are_refused_with_the_reason(made: Path, tmp_path: Path, expected: str, text: str) -> None:
    code, result = _run(made, tmp_path, text)
    assert code == 1 and result["ok"] is False
    assert expected in _codes(result), result["problems"]


def test_karten13_every_reason_is_listed_not_only_the_first(made: Path, tmp_path: Path) -> None:
    text = GOOD.replace("path: /api/queue}", "path: https://evil.example.com/queue}").replace("{en: Queue size, de: Warteschlange}", "{de: Warteschlange}")
    code, result = _run(made, tmp_path, text)
    assert code == 1
    assert "card_bad_path" in _codes(result)
    assert all(problem["message"] for problem in result["problems"])
    assert any(problem["line"] for problem in result["problems"])


def test_karten13_wrong_type_and_not_a_card_are_refused(made: Path, tmp_path: Path) -> None:
    _, result = _run(made, tmp_path, GOOD, "--type", "integration")
    assert _codes(result) == ["type_mismatch"]
    _, result = _run(made, tmp_path, "hello: world\n")
    assert _codes(result) == ["unknown_type"]
    _, result = _run(made, tmp_path, GOOD + "---\n" + GOOD)
    assert _codes(result) == ["one_document"]
    _, result = _run(made, tmp_path, GOOD + "# " + "x" * 61_000 + "\n")
    assert _codes(result) == ["too_long"]


def test_karten13_texts_of_the_submission_are_scanned_for_secrets(made: Path, tmp_path: Path) -> None:
    note = tmp_path / "description.txt"
    note.write_text("Use the key " + "ghp" + "_" + "a1b2c3d4e5" * 4 + " to log in.", encoding="utf-8")
    code, result = _run(made, tmp_path, GOOD, "--scan", f"description={note}")
    assert code == 1 and _codes(result) == ["secret_in_text"]
    note.write_text("Shows how many items wait.", encoding="utf-8")
    code, result = _run(made, tmp_path, GOOD, "--scan", f"description={note}")
    assert code == 0


# -- skins (skins, phase D) ---------------------------------------------------------------------------------------------

SKIN = (Path(__file__).resolve().parent.parent / "app" / "skins" / "examples" / "console.json").read_text(encoding="utf-8")


def test_a_skin_is_checked_and_compiled_by_the_kit_as_nexdeck_compiles_it(made: Path, tmp_path: Path) -> None:
    from app.skins import compile as skin_compile
    from app.skins import store as skin_store

    code, result = _run(made, tmp_path, SKIN, "--type", "skin")
    assert code == 0 and result["ok"] and result["type"] == "skin" and result["class"] == "read", result
    assert (result["slug"], result["version"], result["requires"], result["reads"]) == ("console", "1.0", [], [])
    assert result["compiled"] == skin_compile.compile_skin(skin_store.read(SKIN)).as_json(), "the pictures wear what nexdeck would"
    assert (made / "schema" / "skin.schema.json").is_file()


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"css": "[data-part=chip] { color: red !important }"}, "bad_css"),
        ({"native": "retro"}, "bad_css"),
        ({"key": "1984"}, "taken"),
        ({"tokens": {"radius": 99}}, "bad_skin"),
    ],
    ids=["important", "native", "shipped-name", "radius"],
)
def test_a_skin_nexdeck_would_not_wear_is_refused_by_the_kit(made: Path, tmp_path: Path, change: dict[str, Any], code: str) -> None:
    status, result = _run(made, tmp_path, json.dumps({**json.loads(SKIN), **change}), "--type", "skin")
    assert status == 1 and code in _codes(result), result


def test_a_skin_handed_in_as_a_card_and_a_card_as_a_skin_are_refused(made: Path, tmp_path: Path) -> None:
    assert _codes(_run(made, tmp_path, SKIN, "--type", "card")[1]) == ["type_mismatch"]
    assert _codes(_run(made, tmp_path, GOOD, "--type", "skin")[1]) == ["type_mismatch"]
