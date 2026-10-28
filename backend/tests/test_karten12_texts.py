"""KARTEN-12: every code an import of cards, integrations or a board is refused with has a sentence in every language.

The codes are read from the code, so a new refusal without a text fails here instead of showing English in a German
dialog. The problems of a document are guarded with the problems of a card (``test_cards_schema``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.cards import exchange
from app.routers import boards as board_routes

I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"
#: Refusals the dialogs word with the sentence the lists already have for them (``importFailure`` in ``lib/cardExchange.ts``).
OWN_SENTENCE = {"too_many_cards": ("cards", "tooMany"), "integration_limit": ("cards", "integrations", "tooMany")}


def refusal_codes() -> set[str]:
    found = set(re.findall(r'Refused\(\s*"([a-z_]+)"', Path(exchange.__file__).read_text(encoding="utf-8")))
    routes = Path(board_routes.__file__).read_text(encoding="utf-8")
    # The import routes of boards: everything between the two headings.
    part = routes[routes.index("# -- export and import") : routes.index("# -- kiosk tokens")]
    found |= set(re.findall(r'error\(\s*"([a-z_]+)"', part))
    return found


def test_karten12_every_refusal_of_an_import_has_a_sentence_in_every_language() -> None:
    codes = refusal_codes()
    assert {"import_invalid", "import_choice_missing", "definitions_admin_only", "bad_import"} <= codes, "the guard does not find the codes"
    for language in ("en", "de", "es", "fr", "it"):
        texts = json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))
        worded = set(texts["cards"]["exchange"]["errors"])
        assert codes - worded - set(OWN_SENTENCE) == set(), f"{language}: codes without a sentence"
        for path in OWN_SENTENCE.values():
            found = texts
            for key in path:
                found = found[key]
            assert isinstance(found, str) and found, (language, path)
        # Each text fills only the blanks the dialogs give it.
        for code, text in texts["cards"]["exchange"]["errors"].items():
            assert set(re.findall(r"\{\{(\w+)\}\}", text)) <= {"message", "problem"}, (language, code)
