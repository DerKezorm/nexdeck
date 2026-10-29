"""S2 (security review, stage 8): a link a card puts together leads where its own text says.

The rule of the pictures (korrektur J1, F3) for ``link``: a template is a path that starts with a single ``/``, or ``http`` or
``https`` with the host written out before any placeholder. Otherwise a value the card reads, or the answer itself, would
choose the host a viewer is sent to, with that value in the address.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import get_adapter
from app.adapters.base import Context
from app.adapters.custom import present
from app.cards import load, pipeline, source
from app.cards.load import CardInvalid
from app.cards.schema import Request

HEAD = """\
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


def problems_of(link: str) -> list[Any]:
    with pytest.raises(CardInvalid) as invalid:
        load.load_definition(HEAD + link)
    return invalid.value.problems


@pytest.mark.parametrize(
    "link",
    [
        "  link: {template: '{url}'}\n",
        "  link: {template: 'https://{host}/x'}\n",
        "  link: {template: 'https://stats.example.com{path}'}\n",
        "  link: {template: 'https://stats.example.com?k={apiKey}'}\n",
        "  link: {template: 'https://stats.example.com@{host}/x'}\n",
        "  link: {template: '//{host}/x'}\n",
        "  link: {template: 'javascript:alert({apiKey})'}\n",
        "  link: {template: 'ftp://files.example.com/{name}'}\n",
        "  link: {template: 'http{s}://files.example.com/x'}\n",
        "  link: {formula: '{url} + 1'}\n",
    ],
)
def test_karten8s_s2_a_link_whose_host_is_not_written_out_is_refused_on_checking(link: str) -> None:
    found = problems_of(link)
    assert [one.code for one in found] == ["card_link_address"]
    assert found[0].line == 13 and found[0].path.startswith("item.link"), "the problem sits on the line of the link"


@pytest.mark.parametrize(
    "link",
    [
        "  link: url\n",
        "  link: {path: url}\n",
        "  link: {template: '/series/{titleSlug}'}\n",
        "  link: {template: 'https://docs.example.com/sonarr/queue'}\n",
        "  link: {template: 'HTTP://svc.example.com:8989/x'}\n",
    ],
)
def test_karten8s_s2_a_value_a_path_and_an_address_with_its_host_written_out_are_fine(link: str) -> None:
    load.load_definition(HEAD + link)


def present_unchecked(link: dict[str, Any], row: dict[str, Any]) -> Any:
    """A definition that did not pass the check (a card saved before it), shown with a row."""
    data = {
        "nexdeck-card": 1, "slug": "queue-size", "name": "Sample", "version": "1.0.0", "requires": ["sonarr"],
        "requests": [{"id": "host", "path": "/api/v3/config/host"}], "form": "list", "rows": {"select": "[@]"},
        "item": {"title": "instanceName", "link": link},
    }
    definition = load.definition_from_data(data)
    return present(definition, pipeline.run(definition, {"host": row}))


def test_karten8s_s2_a_saved_card_that_breaks_the_rule_shows_no_link_and_one_that_keeps_it_does() -> None:
    row = {"instanceName": "Sonarr", "url": "https://evil.example.com/x", "host": "evil.example.com"}
    assert present_unchecked({"template": "{url}"}, row).items[0].get("url") is None
    assert present_unchecked({"template": "https://{host}/x"}, row).items[0].get("url") is None
    assert present_unchecked({"formula": "{url}"}, row).items[0].get("url") is None
    # Since B10 of the second review a placeholder after a host written out breaks it too.
    assert present_unchecked({"template": "https://stats.example.com/{instanceName}"}, row).items[0].get("url") is None
    kept = present_unchecked({"template": "https://docs.example.com/queue"}, row).items[0].get("url")
    assert kept == "https://docs.example.com/queue"
    # A value of the answer as it stands may lead anywhere: the service named it, not the card.
    assert present_unchecked({"path": "url"}, row).items[0].get("url") == "https://evil.example.com/x"


KEY = "0123456789abcdef" * 2  # a Sonarr key has 32 hex digits
BASE = "http://svc.example.com:8989"


@respx.mock
def test_karten8s_s2_the_probe_of_the_review_a_link_to_another_host_carries_no_key() -> None:
    """The probe of S1/S2 the other way round: a link with the key in it carries it nowhere (a host of the author is refused since B10)."""
    card = HEAD + "  value: apiKey\n  link: {template: '/q?k={apiKey}'}\n"
    definition = load.load_definition(card).definition
    respx.get(f"{BASE}/api/v3/config/host").mock(return_value=httpx.Response(200, json={"instanceName": "Sonarr", "apiKey": KEY}))
    context = Context(httpx.AsyncClient(), integration_id=1, widget_id=1, cache={})
    answer = asyncio.run(source.fetch_source(get_adapter("sonarr"), {"url": BASE, "api_key": KEY}, context, Request(id="host", path="/api/v3/config/host")))
    data = present(definition, pipeline.run(definition, {"host": answer}), base=BASE)
    links = [item.get("url") for item in data.items]
    assert links and not any(KEY in (link or "") for link in links), links
    assert KEY not in data.model_dump_json()


def test_karten8s_s2_the_editor_says_it_in_five_languages() -> None:
    folder = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"
    for language in ("en", "de", "es", "fr", "it"):
        texts = json.loads((folder / f"{language}.json").read_text(encoding="utf-8"))
        found = [one["card_link_address"] for one in _all_dicts(texts) if "card_link_address" in one]
        assert found and all(text.strip() for text in found), language


def _all_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [value, *(one for child in value.values() for one in _all_dicts(child))]
