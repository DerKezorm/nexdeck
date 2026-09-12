"""The page a kiosk link opens does not pass its address on.

⚠️ A kiosk link carries its token in the address, ``/k/nk_...``, and the page
was sent with ``Referrer-Policy: same-origin``. Every script, style and picture
that first page loaded went out with the whole address as its Referer, so the
token stood in the access log of every reverse proxy in front of nexdeck, once
per file. Found on 07.09.2026, still there on 12.09.2026.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_a_kiosk_link_page_is_sent_without_a_referrer(client: TestClient) -> None:
    answer = client.get("/k/nk_made-up-token-for-the-test")
    assert answer.headers.get("referrer-policy") == "no-referrer"


def test_every_other_page_keeps_its_policy(client: TestClient) -> None:
    for path in ("/", "/login", "/b/home", "/k"):
        assert client.get(path).headers.get("referrer-policy") == "same-origin", path
