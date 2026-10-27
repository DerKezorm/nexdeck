"""Cards put together from blocks for the tests of KARTEN-7: a server at a glance with a list of containers."""

from __future__ import annotations

import copy
import json
from typing import Any

import yaml

#: A card of blocks read through a generic JSON connection: a header row, one value that is the main one, a bar, a
#: history, and a list of containers each with a state and a restart button.
GLANCE = """\
nexdeck-card: 1
slug: server-glance
name: {en: Server at a glance, de: Server im Blick}
version: 1.0.0
requires: [jsonapi]
requests:
  - id: sys
    path: /api/system
form: builder
main: cpu
rows: {select: containers, sort: {field: name}, limit: 20}
blocks:
  - type: row
    gap: m
    children:
      - {type: symbol, icon: server, color: accent}
      - {type: text, value: {path: host.name}, weight: bold}
      - {type: badge, value: {path: host.state, rules: [{op: "==", than: down, then: bad}]}, color: green}
  - {type: value, id: cpu, label: {en: CPU, de: Prozessor}, path: host.cpu, format: percent, rules: [{op: ">=", than: 90, then: bad}]}
  - {type: progress, value: {path: host.memory}, max: 100, color: accent}
  - {type: sparkline, id: cpu_trend, value: {path: host.cpu}}
  - {type: divider}
  - type: list
    empty: {en: No containers, de: Keine Container}
    item:
      - type: row
        align: between
        children:
          - {type: text, value: {path: name}}
          - {type: badge, value: {path: state}, color: muted}
          - {type: button, button: restart}
  - {type: button, button: reboot}
buttons:
  - id: restart
    label: Restart
    icon: rotate-cw
    where: row
    method: POST
    path: "/api/containers/{id}/restart"
  - id: reboot
    label: Reboot
    where: card
    method: POST
    path: /api/system/reboot
    danger: true
demo:
  sys:
    host: {name: nas, state: up, cpu: 42, memory: 61}
    containers:
      - {id: a1, name: web, state: running}
      - {id: b2, name: db, state: stopped}
"""


def changed(text: str = GLANCE, **top: Any) -> str:
    """The sample with places of the top level set (``None`` removes one)."""
    data = yaml.safe_load(text)
    for name, value in top.items():
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    # Through JSON and back: the same block used twice in a test would be written as an anchor, which a card does not allow.
    return yaml.safe_dump(json.loads(json.dumps(data)), sort_keys=False, allow_unicode=True)


def with_blocks(*blocks: dict[str, Any], **top: Any) -> str:
    """The sample with its blocks replaced."""
    return changed(blocks=list(blocks), **top)


def nested(depth: int, leaf: dict[str, Any] | None = None) -> dict[str, Any]:
    """A column inside a column ``depth`` levels deep (the first level is the column itself), with a leaf at the bottom."""
    block: dict[str, Any] = copy.deepcopy(leaf) if leaf is not None else {"type": "divider"}
    for _ in range(depth - 1):
        block = {"type": "column", "children": [block]}
    return block
