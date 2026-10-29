"""B7 of the second security review: a deeply nested style sheet of the look is refused with a code, never a 500."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import appearance, css_scan
from tests.conftest import CSRF, client, data_dir, setup_admin  # noqa: F401 - the fixtures

DEEP = "a{b:" + "(" * 3000 + ")" * 3000 + "}"
FIELDS = ("preset", "accent", "theme", "card_style", "font", "retro", "radius", "gap")


def test_karten8t_b7_a_deep_sheet_is_too_deep_not_a_recursion_error() -> None:
    assert len(DEEP) < appearance.MAX_CSS
    with pytest.raises(css_scan.TooDeep):
        css_scan.what_fetches(DEEP)
    with pytest.raises(appearance.AppearanceError) as refused:
        appearance.check_css(DEEP)
    assert refused.value.code == "css_too_deep"


def test_karten8t_b7_nesting_a_real_sheet_uses_still_passes_and_a_fetch_deep_inside_is_found() -> None:
    nested = "a{" * 10 + "b:calc(" * 5 + "1px" + ")" * 5 + "}" * 10
    assert css_scan.what_fetches(nested) is None
    deep_fetch = "@media all{" * 8 + "a{b:" + "calc(" * 20 + "url(https://e.example/x)" + ")" * 20 + "}" + "}" * 8
    assert css_scan.what_fetches(deep_fetch) is not None


def test_karten8t_b7_the_route_answers_400_with_a_code(client: TestClient) -> None:  # noqa: F811
    setup_admin(client)
    current = client.get("/api/v1/settings/appearance").json()
    body = {key: current[key] for key in FIELDS if key in current}
    with TestClient(client.app, raise_server_exceptions=False, cookies=client.cookies) as again:
        answer = again.put("/api/v1/settings/appearance", json={**body, "css": DEEP}, headers=CSRF)
    assert answer.status_code == 400, answer.text
    assert answer.json()["detail"]["code"] == "css_too_deep"
