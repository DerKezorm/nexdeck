"""Descriptions of own connections for the tests of KARTEN-3: the example files, and a builder that changes one place."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

EXAMPLES = Path(__file__).resolve().parent.parent / "app" / "cards" / "integration_examples"


def example(name: str) -> str:
    return (EXAMPLES / f"{name}.yaml").read_text(encoding="utf-8")


def changed(text: str, **places: Any) -> str:
    """The text with places replaced: ``changed(text, short="x", **{"auth.type": "none"})``. ``None`` removes a place."""
    data = yaml.safe_load(text)
    for place, value in places.items():
        cursor = data
        *parents, last = place.split(".")
        for part in parents:
            cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
        if value is None:
            cursor.pop(last, None)
        elif isinstance(cursor, list):
            cursor[int(last)] = value
        else:
            cursor[last] = value
    return yaml.safe_dump(data, sort_keys=False)


HEADER = example("bookstack")
MEMOS = example("memos")
