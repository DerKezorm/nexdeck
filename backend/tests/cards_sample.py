"""A small valid card to bend in the tests of the custom cards."""

from __future__ import annotations

VALUE_CARD = """\
# A comment on top stays where it is.
nexdeck-card: 1
slug: queue-size
name: {en: Queue, de: Warteschlange}   # trailing comment
version: "1.0.0"
min_nexdeck: "0.40.0"
author: Example Author
description: How many items wait in the queue.
category: media
requires: [sonarr, radarr]   # either one
requests:
  - id: queue
    path: /api/v3/queue
    every: 30s
form: value
value:
  path: totalRecords
  label: {en: Waiting, de: Wartend}
  unit: items
rules:
  - {value: totalRecords, op: ">=", than: 10, then: warn}
demo:
  queue: {totalRecords: 4, records: [{title: "A", size: 100}]}
"""

DEMO_LINE = 'demo:\n  queue: {totalRecords: 4, records: [{title: "A", size: 100}]}\n'


def changed(old: str, new: str, text: str = VALUE_CARD) -> str:
    """The sample with one place replaced; fails loudly when the place is not there."""
    assert old in text, old
    return text.replace(old, new, 1)
