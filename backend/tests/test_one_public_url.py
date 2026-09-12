"""Every place that needs the public address reads the same one.

⚠️ The address can be set in the interface or in NEXDECK_PUBLIC_URL, and five
places read it three different ways. Web Push and the rescue link read only
the environment, so an installation that set its address in the interface
signed its push messages as mailto:admin@localhost, which a push service may
refuse, and printed a rescue link to localhost. Still open in the check of
12.09.2026.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import db_session
from app.models import Setting
from app.services.channels import webpush

from .conftest import setup_admin

APP = Path(__file__).resolve().parents[1] / "app"
HELPER = APP / "services" / "public_url.py"
READS_IT = re.compile(r"(?:settings|get_settings\(\))\.public_url\b|\.get\(\s*[\"']public_url[\"']")


def test_web_push_signs_with_the_address_set_in_the_interface(client: TestClient) -> None:
    setup_admin(client)
    with db_session() as db:
        db.merge(Setting(key="general", value={"public_url": "https://deck.example.com"}))
    assert webpush.subject() == "https://deck.example.com"


def test_nothing_but_the_helper_reads_the_address() -> None:
    readers = sorted(
        str(path.relative_to(APP)) for path in APP.rglob("*.py")
        if path != HELPER and READS_IT.search(path.read_text(encoding="utf-8"))
    )
    assert readers == []
    assert READS_IT.search(HELPER.read_text(encoding="utf-8")), "the helper reads nothing, so this guard looks at nothing"
