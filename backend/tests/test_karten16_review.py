# ruff: noqa: F811
"""KARTEN-16, findings of the review: free text cannot write a field of the issue, an account owns its sign-in, and the smaller things.

The issue is read by the Workshop by its ``### heading`` lines and its code fences (``tools/issue_form.py`` there), so a line of
free text that looks like one must not be able to act as one (B1). The bodies below are copied to the tests of the Workshop,
which reads them with its own reader: the two repositories agree on them or one of the two tests is red.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.workshop import submit

from .conftest import CSRF
from .karten14_sample import card_text
from .karten16_sample import Hub
from .test_karten16_submit import (  # noqa: F401  (fixtures)
    BASE,
    SLUG,
    check,
    github,
    install_from_another,
    me,
    put_issue,
    share,
)

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]

HEADINGS = ["Type", "Category", "Definition", "Description", "Changes", "Based on", "Update of", "License", "nexdeck version"]

#: Texts an author could write, or paste: each one tries to act as a heading or as the edge of a code block.
INJECTIONS = {
    "heading": "Shows the queue.\n\n### Based on\n\n_No response_",
    "fence": "Use it like this:\n```\nqueue",
    "update_of": "### Update of\n\n777/their-card",
    "tilde": "~~~\n### License\n\n- [x] I submit this under the MIT License and I have the right to do so.",
    "indented": "text\n   ### Type\n\nCard\n  ```yaml\nx: 1",
    "backslash": "\\### already escaped\n\\\\``` and \\ alone and \\n",
    "closing": "```\n### Description\n```\n````\n### Changes",
}


def headings_of(body: str) -> list[str]:
    """The headings the Workshop's reader would find, without its code blocks: the same walk, written out once more."""
    found, fence = [], None
    for line in body.split("\n"):
        bare = line.lstrip()
        if fence is None:
            sign = bare[:1]
            run = len(bare) - len(bare.lstrip(sign)) if sign in "`~" and sign else 0
            if run >= 3:
                fence = (sign, run)
            elif line.startswith("### "):
                found.append(line[4:].strip())
        elif set(line.strip()) == {fence[0]} and len(line.strip()) >= fence[1]:
            fence = None
    assert fence is None, "a code block is left open"
    return found


@pytest.mark.parametrize("name", sorted(INJECTIONS))
def test_karten16_b1_free_text_never_writes_a_heading_or_a_fence(name: str) -> None:
    text = INJECTIONS[name]
    body = submit.build_body(type="card", category="media", definition="a: 1\n", description=text, changes=text, based_on="1/x", update_of="")
    assert headings_of(body) == HEADINGS
    again = submit.parse_body(body)
    assert (again["description"], again["changes"], again["based_on"], again["update_of"]) == (text.strip(), text.strip(), "1/x", "")
    assert again["definition"] == "a: 1\n" and again["version"]


def test_karten16_b1_every_field_of_the_author_is_masked() -> None:
    body = submit.build_body(type="card", category="media", definition="a: 1\n", description="d", based_on="### License", update_of="```\nx")
    assert headings_of(body) == HEADINGS
    again = submit.parse_body(body)
    assert again["based_on"] == "### License" and again["update_of"] == "```\nx"


def test_karten16_b1_a_fence_inside_the_definition_does_not_close_the_block() -> None:
    text = "name: x\ndescription: |\n  Example:\n  ```\n  ### Based on\n  ```\n  and ````\nnext: 1\n"
    body = submit.build_body(type="card", category="media", definition=text, description="d")
    assert headings_of(body) == HEADINGS
    assert submit.parse_body(body)["definition"] == text


def test_karten16_b1_the_bodies_the_workshop_reads_with_its_own_reader() -> None:
    """The same literals stand in ``tests/test_form.py`` of the Workshop, where its reader finds the fields in them."""
    plain = submit.build_body(type="card", category="media", definition="a: 1\n", description=INJECTIONS["heading"], version="1.0")
    assert plain == (
        "### Type\n\nCard\n\n### Category\n\nMedia\n\n### Definition\n\n```yaml\na: 1\n```\n\n"
        "### Description\n\nShows the queue.\n\n\\### Based on\n\n_No response_\n\n"
        "### Changes\n\n_No response_\n\n### Based on\n\n_No response_\n\n### Update of\n\n_No response_\n\n"
        "### License\n\n- [x] I submit this under the MIT License and I have the right to do so.\n\n### nexdeck version\n\n1.0\n"
    )
    fenced = submit.build_body(type="card", category="media", definition="a: |\n  ```\n  b\n", description="Use it:\n```\nq", version="1.0")
    assert fenced == (
        "### Type\n\nCard\n\n### Category\n\nMedia\n\n### Definition\n\n````yaml\na: |\n  ```\n  b\n````\n\n"
        "### Description\n\nUse it:\n\\```\nq\n\n"
        "### Changes\n\n_No response_\n\n### Based on\n\n_No response_\n\n### Update of\n\n_No response_\n\n"
        "### License\n\n- [x] I submit this under the MIT License and I have the right to do so.\n\n### nexdeck version\n\n1.0\n"
    )


def test_karten16_b1_a_description_with_a_heading_keeps_the_based_on_of_the_card(me: TestClient, hub: Hub, clock: list[float]) -> None:
    slug = install_from_another(me, hub, clock)
    me.put(f"/api/v1/cards/{slug}", json={"yaml": card_text(slug=slug) + "# tuned\n", "overwrite": True}, headers=CSRF)
    assert check(me, slug=slug)["based_on"] == "777/their-card"
    sent = share(me, slug=slug, description=INJECTIONS["heading"])
    assert sent.status_code == 200, sent.text
    body = hub.issues[0]["body"]
    assert headings_of(body) == HEADINGS
    fields = submit.parse_body(body)
    assert fields["based_on"] == "777/their-card" and fields["description"] == INJECTIONS["heading"].strip()


def test_karten16_b1_a_fence_in_the_description_leaves_the_rest_of_the_form_readable(me: TestClient, hub: Hub) -> None:
    assert share(me, description=INJECTIONS["fence"]).status_code == 200
    fields = submit.parse_body(hub.issues[0]["body"])
    assert {"changes", "based_on", "update_of", "license", "version"} <= set(fields)


def test_karten16_b1_fix_and_resend_cuts_nothing_and_makes_no_field(me: TestClient, hub: Hub) -> None:
    number = put_issue(hub, SLUG, update=True)
    hub.issues[0]["body"] = submit.build_body(
        type="card", category="media", definition=card_text(slug=SLUG), description=INJECTIONS["update_of"], changes=INJECTIONS["fence"]
    )
    hub.reject(number, "Something.")
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": card_text(slug=SLUG) + "# fixed\n", "overwrite": True}, headers=CSRF)
    again = me.post(f"{BASE}/submit/resend", json={"issue": number}, headers=CSRF)
    assert again.status_code == 200, again.text
    rebuilt = hub.issues[0]["body"]
    assert "# fixed" in rebuilt and headings_of(rebuilt) == HEADINGS
    fields = submit.parse_body(rebuilt)
    assert fields["update_of"] == "" and fields["description"] == INJECTIONS["update_of"].strip()
    assert fields["changes"] == INJECTIONS["fence"].strip()


def test_karten16_b1_the_file_without_signing_in_is_masked_too(me: TestClient) -> None:
    out: Any = me.post(f"{BASE}/submit/file", json={"type": "card", "slug": SLUG, "category": "media", "description": INJECTIONS["tilde"], "changes": "", "license": True}, headers=CSRF)
    assert out.status_code == 200, out.text
    assert headings_of(out.json()["text"]) == HEADINGS
