"""B9 of the second security review: the Workshop's kit checks what nexdeck checks, the corrections of the reviews included.

The kit in the public Workshop was made before the corrections S2 to S4, so the shop took cards nexdeck refuses. A kit
built now refuses them like nexdeck: a link that carries a value to a host of its author (S2, B10), a path with dots in
disguise (S4), and it knows the one rule for credentials in demo data (S3, B8) that the Workshop's check takes from it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.cards import load
from tests.test_workshop_kit import GOOD, _codes, _load_tool, _run

LINK = GOOD.replace("form: value\nvalue: {path: count, label: Queue, format: number}\n", "form: list\nrows: {select: items}\nitem:\n  title: name\n  link: {template: 'https://stats.example.com/q?k={name}'}\n").replace("q: {count: 7}", "q: {items: [{name: a}]}")
DISGUISED = GOOD.replace("path: /api/queue}", "path: /api/%c0%ae%c0%ae/config}")


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("workshop")
    _load_tool().build(out, page=False)
    return out


@pytest.mark.parametrize(("expected", "text"), [("card_link_address", LINK), ("card_bad_path", DISGUISED)], ids=["b10-link", "s4-path"])
def test_karten8t_b9_the_kit_refuses_what_nexdeck_refuses(made: Path, tmp_path: Path, expected: str, text: str) -> None:
    with pytest.raises(load.CardInvalid) as invalid:
        load.load_definition(text)
    assert expected in [problem.code for problem in invalid.value.problems]
    code, result = _run(made, tmp_path, text, "--type", "card")
    assert code != 0 and expected in _codes(result), result


def test_karten8t_b9_the_kit_has_the_one_rule_for_credentials_in_demo_data(made: Path, tmp_path: Path) -> None:
    probe = "from nexdeck_kit.credential_names import is_access_name as a; print([a(n) for n in ('X-Api-Key', 'privateKey', 'pwd', 'userName')])"
    done = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(made / 'kit')!r}); {probe}"], cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False)
    assert done.stdout.strip() == "[True, True, True, False]", done.stderr
