"""What may run in nexdeck's own origin, and what may not.

Three separate doors into the same room, all found on 06.09.2026:

* the icon proxy hands out SVG it fetched from a public collection, from
  nexdeck's own address, and SVG is a document that runs script
* the stylesheet an operator may set barred ``@import`` and allowed ``url()``,
  which fetches just as well
* ``NEXDECK_CORS_ORIGINS='*'`` reads like "let anyone see the public parts"
  and means "let any site the operator visits act as them"
"""

from __future__ import annotations

import importlib
import re

import pytest
from fastapi.testclient import TestClient

from app.services.appearance import FORBIDDEN

from .conftest import setup_admin


def _policy(response) -> str:  # noqa: ANN001
    return response.headers.get("content-security-policy", "")


def test_answers_under_api_carry_a_policy_too(client: TestClient) -> None:
    """⚠️ The rule used to be set for everything except ``/api/``, on the
    grounds that JSON needs none. Two addresses under it do not answer with
    JSON: the icon proxy and the image proxy, and what they pass through comes
    from somewhere else.
    """
    setup_admin(client)
    answer = client.get("/api/health")
    assert "sandbox" in _policy(answer), "no policy on an API answer"
    assert "default-src 'none'" in _policy(answer)
    assert answer.headers.get("x-content-type-options") == "nosniff"


def test_a_foreign_svg_comes_with_its_sandbox(client: TestClient) -> None:
    """The icons are fetched from a public collection; one of them may bite."""
    setup_answer = client.get("/api/v1/icons/nexview.svg")
    assert setup_answer.status_code == 200, setup_answer.text
    assert setup_answer.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in _policy(setup_answer), (
        "an SVG from a foreign collection was served from our own address with no policy on it"
    )


STYLESHEETS_REFUSED = [
    "body{background:url(https://elsewhere.example/x.png)}",
    "body{background: url( //elsewhere.example/x )}",
    '@import url("https://elsewhere.example/x.css");',
    "a{background:url('http://elsewhere.example/pixel.gif')}",
]
STYLESHEETS_ALLOWED = [
    "body{color:#ffffff}",
    "a{background:url('data:image/png;base64,AAA')}",
]


def test_a_stylesheet_may_not_fetch_from_anywhere() -> None:
    """⚠️ ``@import`` was barred and ``url()`` was not, and both fetch. A
    background image on a foreign address tells that address the IP and the
    user agent of everyone who opens a board.
    """
    for css in STYLESHEETS_REFUSED:
        assert any(pattern.search(css) for pattern, _ in FORBIDDEN), f"allowed: {css}"
    for css in STYLESHEETS_ALLOWED:
        assert not any(pattern.search(css) for pattern, _ in FORBIDDEN), f"refused: {css}"
    assert len(STYLESHEETS_REFUSED) >= 4


def test_cors_with_a_star_refuses_to_start(monkeypatch: pytest.MonkeyPatch, data_dir) -> None:  # noqa: ANN001
    """Starlette does not send a literal star when credentials are allowed.

    ⚠️ It echoes back whatever Origin asked and sets Allow-Credentials with it,
    and the preflight then waves through ``X-Nexdeck-Request``, the one header
    that stops another site from acting as the signed-in user. Measured against
    a running instance on 07.09.2026.
    """
    from app import config, main

    try:
        monkeypatch.setenv("NEXDECK_CORS_ORIGINS", "*")
        config.reset_settings_cache()
        with pytest.raises(RuntimeError) as refused:
            importlib.reload(main)
        assert "cannot be combined" in str(refused.value)

        # And a named origin still works, or the setting would be useless.
        monkeypatch.setenv("NEXDECK_CORS_ORIGINS", "https://deck.example.com")
        config.reset_settings_cache()
        importlib.reload(main)
        assert any("CORSMiddleware" in str(m) for m in main.app.user_middleware)
    finally:
        # ⚠️ Reloading the module replaces ``app``, and every other test reads
        # it from here. Leaving one behind with a middleware nobody asked for
        # is the kind of thing that turns up three files later as a mystery.
        monkeypatch.delenv("NEXDECK_CORS_ORIGINS", raising=False)
        config.reset_settings_cache()
        importlib.reload(main)
        assert not any("CORSMiddleware" in str(m) for m in main.app.user_middleware)


IFRAME = re.compile(r"framesOurselves\(url\)")


def test_the_iframe_card_refuses_our_own_address() -> None:
    """``allow-same-origin`` has to stay or most services break inside a frame,
    so what gets refused is the address, not the sandbox.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "renderers.tsx").read_text(encoding="utf-8")
    assert IFRAME.search(source), "the iframe card no longer checks whether it is framing nexdeck itself"
    assert "allow-same-origin" in source, "the sandbox was loosened or tightened without this test hearing about it"
