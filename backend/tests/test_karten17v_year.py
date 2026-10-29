"""A year in a card is written as a year, not as 2,005 (found in a real run on 1.0.0 with nexcrate's titles).

The guided way, the card help and most hand-written cards leave the format of a year out; a whole number in a field named
for a year is then text, while every other number keeps its grouping.
"""

from __future__ import annotations

import json

from app.cards import load, pipeline

CARD = """nexdeck-card: 1
slug: years
name: Years
version: 1.0.0
requires: [nexcrate]
requests:
  - {id: titles, path: /api/v1/titles}
form: list
rows: {select: items}
item:
  title: name
  subtitle: productionYear
  value: year
rules: []
value: {path: count}
"""


def shown(answer: dict) -> str:
    definition = load.load_definition(CARD.replace("rules: []\nvalue: {path: count}\n", "")).definition
    return json.dumps(pipeline.run(definition, {"titles": answer}), default=lambda one: getattr(one, "__dict__", str(one)))


def test_karten17v_a_field_named_for_a_year_is_text_and_other_numbers_stay_numbers() -> None:
    answer = {"items": [{"name": "Smile", "year": 1997, "productionYear": 2005, "count": 2005}]}
    out = shown(answer)
    assert '"text": "1997", "format": "text"' in out and '"text": "2005", "format": "text"' in out, out
    # Not a year: a count of 2005, a year field with a number that is no year, a fraction.
    assert pipeline._a_year("count", 2005) is False
    assert pipeline._a_year("year", 123456) is False and pipeline._a_year("year", 1997.5) is False
    assert pipeline._a_year("album.first_release_year", 1999) is True and pipeline._a_year("years", 2005) is False
