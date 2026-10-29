"""The hints of the security review of stage 8: the thumb, the pictures and the examples of the Card shop.

(a) A thumb is set only on a discussion of the Workshop repository, also when the catalog names it by its id.
(b) The server keeps the pictures of an entry by the ``picture_version`` of the catalog: a ``v`` it does not name asks
    GitHub nothing.
(c) An example is checked in full the moment it is fetched, the way an installation checks it.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import CSRF
from .karten3_sample import MEMOS
from .karten14_sample import AUTHOR, GitHub, card_text
from .karten16_sample import Hub
from .test_karten8n_backend import me  # noqa: F401 - the fixture
from .test_karten16w2_thumb import graphql, sign_in

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]

BASE = "/api/v1/workshop"
ME = 4242
SLUG = "queue-size"
THUMB = f"{BASE}/entries/{ME}/{SLUG}/thumb"


@pytest.fixture
def github(hub: Hub) -> Hub:
    return hub


# -- (a) the thumb ------------------------------------------------------------------------------------------------


def stranger(hub: Hub) -> dict[str, Any]:
    """A discussion somewhere else on GitHub, named by its id in a catalog that says it is the entry's."""
    found = hub.open_discussion("D_kwDOstranger", 99)
    hub.discussions["D_kwDOstranger"]["url"] = "https://github.com/somebody/else/discussions/99"
    return {"id": found["id"], "url": found["url"]}


def test_karten8s_hint_a_an_id_of_a_discussion_outside_the_workshop_gets_no_thumb(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    named = stranger(hub)
    hub.publish(card_text(), author=str(ME), discussion=named)
    sign_in(shop, hub, moment, hub.person("someone", ME))
    assert shop.get(THUMB).json() == {"signed_in": True, "on": None}
    refused = shop.put(THUMB, json={"on": True}, headers=CSRF)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "no_discussion"
    assert hub.discussions["D_kwDOstranger"]["thumbs"] == set()
    assert not any("Reaction(" in one["query"] for one in graphql(hub)), "only looked at, never reacted to"
    assert all("nameWithOwner" in one["query"] for one in graphql(hub))


def test_karten8s_hint_a_an_id_of_a_discussion_of_the_workshop_still_gets_it(shop: TestClient, hub: Hub, moment: list[float]) -> None:
    named = hub.open_discussion()
    hub.publish(card_text(), author=str(ME), discussion=named)
    sign_in(shop, hub, moment, hub.person("someone", ME))
    assert shop.put(THUMB, json={"on": True}, headers=CSRF).json() == {"on": True}
    assert hub.discussions[named["id"]]["thumbs"] == {"someone"}


# -- (b) the pictures -------------------------------------------------------------------------------------------------

IMAGE = f"{BASE}/entries/{ME}/{SLUG}/image"


def test_karten8s_hint_b_a_v_the_catalog_does_not_name_fetches_nothing_from_github(me: TestClient, hub: Hub) -> None:  # noqa: F811
    hub.publish(card_text(version="1.0.0"), author=str(ME))
    hub.files[f"entries/{ME}/{SLUG}/preview-light.png"] = b"\x89PNG\r\n\x1a\none"
    assert me.get(f"{IMAGE}/light?v=1.0.0").content.endswith(b"one")
    for made_up in ("2", "x", "1.0.1", "a" * 64, ""):
        assert me.get(f"{IMAGE}/light?v={made_up}").content.endswith(b"one")
    assert hub.count("preview-light.png") == 1, "one fetch for the version of the catalog, whatever v said"


# -- (c) the examples ---------------------------------------------------------------------------------------------------


def test_karten8s_hint_c_an_example_that_does_not_pass_the_check_is_refused_when_it_is_fetched(shop: TestClient, github: GitHub) -> None:
    found = github.publish(card_text(), starter=True)
    broken = card_text().replace("form: value", "form: nothing-of-the-kind")
    # The checksum of the catalog fits the text: only the check of this nexdeck can find what is wrong with it.
    github.files[found["files"]["definition"]] = broken.encode()
    found["sha256"] = hashlib.sha256(broken.encode()).hexdigest()
    refused = shop.get(f"{BASE}/examples/{AUTHOR}/{SLUG}")
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "entry_invalid" and detail["problems"], detail


def test_karten8s_hint_c_a_good_card_and_a_good_connection_still_come_as_examples(shop: TestClient, github: GitHub) -> None:
    github.publish(card_text(), starter=True)
    found = github.publish(MEMOS, starter=True)
    assert shop.get(f"{BASE}/examples/{AUTHOR}/{SLUG}").status_code == 200
    fetched = shop.get(f"{BASE}/examples/{AUTHOR}/{found['slug']}")
    assert fetched.status_code == 200, fetched.text
