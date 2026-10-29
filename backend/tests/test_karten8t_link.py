"""B10 of the second security review: a link from a template follows the rule of the pictures.

A template is a path underneath the connection (placeholders and all), or an address written out whole without a
placeholder. With a host written out and a placeholder after it, a link carried any value the card reads to a host of the
card's author; such a card is now refused on checking, and one saved before shows no link.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.adapters.custom import _link_address, present
from app.cards import load, pipeline
from app.cards.load import CardInvalid
from app.services.collector import collector
from tests.conftest import CSRF, client, data_dir, setup_admin  # noqa: F401 - the fixtures
from tests.test_cards_router import BASE, connection

CARD = """\
nexdeck-card: 1
slug: queue-size
name: {en: Queue size}
version: 1.0.0
requires: [sonarr]
requests:
  - id: host
    path: /api/v3/config/host
form: list
rows: {select: "[@]"}
item:
  title: instanceName
"""
ANSWER = {"instanceName": "Sonarr", "internalHost": "nas01.home.lan", "slug": "sonarr-main"}


@pytest.mark.parametrize("template", [
    "https://stats.example.com/q?k={internalHost}",
    "https://stats.example.com/{internalHost}",
    "https://stats.example.com/q#{internalHost}",
    "http://svc.example.com:8080/x/{slug}",
])
def test_karten8t_b10_a_placeholder_after_a_host_written_out_is_refused(template: str) -> None:
    with pytest.raises(CardInvalid) as invalid:
        load.load_definition(CARD + f"  link: {{template: '{template}'}}\n")
    assert [problem.code for problem in invalid.value.problems] == ["card_link_address"]


@pytest.mark.parametrize("link", ["  link: {template: '/series/{slug}'}\n", "  link: {template: 'https://docs.example.com/sonarr'}\n", "  link: {path: url}\n"])
def test_karten8t_b10_a_path_a_whole_address_and_a_value_pass(link: str) -> None:
    load.load_definition(CARD + link)


def test_karten8t_b10_a_saved_card_with_a_host_of_its_author_shows_no_link() -> None:
    data = load.parse(CARD)[0]
    data["item"]["link"] = {"template": "https://stats.example.com/q?k={internalHost}"}
    definition = load.definition_from_data(data)
    assert present(definition, pipeline.run(definition, {"host": ANSWER}), base=BASE).items[0].get("url") is None


def test_karten8t_b10_the_preview_puts_a_path_link_underneath_the_connection(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    sonarr = connection(client, "sonarr")
    with respx.mock(assert_all_called=False) as svc:
        svc.get(f"{BASE}/api/v3/config/host").mock(return_value=httpx.Response(200, json=ANSWER))
        shown = client.post("/api/v1/cards/preview", json={"yaml": CARD + "  link: {template: '/series/{slug}'}\n", "integration_id": sonarr}, headers=CSRF)
    assert shown.status_code == 200, shown.text
    assert [item.get("url") for item in shown.json()["items"]] == [f"{BASE}/series/sonarr-main"]


def test_karten8t_b10_a_path_link_never_leaves_the_connection() -> None:
    assert _link_address("/series/x", BASE, named=False) == f"{BASE}/series/x"
    assert _link_address("/series/x", "", named=False) is None, "no connection, no link"
    assert _link_address("/series/x", "http://user:pass@svc.example.com", named=False) is None
    assert _link_address("/a/../../etc", BASE, named=False) is None
    assert _link_address("//evil.example.com/x", BASE, named=False) is None
    assert _link_address("/series/x", BASE, named=True) is None, "a path the service named is not followed into nexdeck"
    assert _link_address("https://evil.example.com/x", BASE, named=True) == "https://evil.example.com/x", "a value of the answer as it stands"
