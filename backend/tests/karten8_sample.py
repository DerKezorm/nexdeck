"""Cards with buttons for the tests of KARTEN-8: a list of downloads that pause, a card that limits the speed."""

from __future__ import annotations

from typing import Any

import yaml

#: A list of downloads in the shape of qBittorrent, read through a generic JSON connection, with buttons on the rows and one on the card.
DOWNLOADS = """\
nexdeck-card: 1
slug: downloads
name: {en: Downloads, de: Downloads}
version: 1.0.0
requires: [jsonapi]
requests:
  - id: torrents
    path: /api/v2/torrents/info
form: list
rows: {select: "@"}
item:
  title: name
  value: {path: progress, format: percent}
buttons:
  - id: pause
    label: {en: Pause, de: Pausieren}
    icon: pause
    where: row
    method: POST
    path: /api/v2/torrents/pause
    send: form
    body: {hashes: "{hash}"}
  - id: limit
    label: Limit speed
    icon: gauge
    where: card
    method: POST
    path: /api/v2/transfer/setDownloadLimit
    send: form
    body: {limit: "{ask.kib}"}
    confirm: true
    asks:
      - {name: kib, label: "KiB per second?", type: number, min: 0, max: 100000, step: 1}
  - id: delete
    label: Delete
    icon: trash
    where: row
    method: DELETE
    path: /api/v2/torrents/{hash}
    danger: true
demo:
  torrents:
    - {name: Ubuntu, hash: abc123, progress: 50}
    - {name: Debian, hash: def456, progress: 100}
"""


def with_buttons(*buttons: dict[str, Any], text: str = DOWNLOADS, **more: Any) -> str:
    """The sample with its buttons replaced, and other places of the top level set (``None`` removes one)."""
    data = yaml.safe_load(text)
    data["buttons"] = list(buttons)
    for name, value in more.items():
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def button(**fields: Any) -> dict[str, Any]:
    """A plain button on the card, with what the test changes."""
    return {"id": "go", "label": "Go", "method": "POST", "path": "/api/go", **fields}
