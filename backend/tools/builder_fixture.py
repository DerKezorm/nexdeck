"""Writes ``frontend/src/test/builderBackend.json``: what the server really sends for a card of blocks.

    python tools/builder_fixture.py

The browser tests of the builder read this file, so that they draw the data as :func:`present` makes it and not as a
test would imagine it. Only invented names and example.com.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters.custom import present  # noqa: E402
from app.cards import load, pipeline  # noqa: E402

DEFINITION = """\
nexdeck-card: 1
slug: fixture
name: Fixture
version: 1.0.0
requires: [jsonapi]
requests: [{id: sys, path: /api/system}]
form: builder
blocks:
  - {type: text, text: {en: Hello, de: Hallo, fr: Salut}}
  - {type: badge, text: {en: Fixed, de: Fest}}
  - {type: text, text: Plain}
  - {type: value, id: big, path: big, format: number}
  - {type: value, path: part, format: number, digits: 1, unit: {en: items, de: Stück}}
  - {type: value, path: usage, format: percent, digits: 1}
  - {type: value, path: size, format: bytes}
  - {type: value, path: moment, format: datetime}
  - {type: value, path: day, format: date}
  - {type: value, path: word}
"""

ANSWER = {
    "big": 1234567.891,
    "part": 4.25,
    "usage": 12.5,
    "size": 5368709120,
    "moment": "2025-10-27T22:20:00Z",
    "day": "2025-10-27T22:20:00Z",
    "word": "up",
}


def main() -> None:
    loaded = load.load_definition(DEFINITION)
    assert loaded.definition is not None, loaded.problems
    result = pipeline.run(loaded.definition, {"sys": ANSWER})
    data = present(loaded.definition, result, base="http://svc.local", widget_id=7).model_dump()
    target = BACKEND.parent / "frontend" / "src" / "test" / "builderBackend.json"
    target.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
