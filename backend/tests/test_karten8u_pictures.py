"""B2 of a review of 1.0.2: a picture path a card's text makes goes through the check of a read of its kind.

A picture of a custom card is fetched by GET with the connection's credentials, for every viewer of the board. A path
the card's text makes (``template``, ``named=False``) is checked like a request of the card: when the card is checked,
before it is signed (``images.reference``) and once more when it is fetched (``custom_picture``). Refused, the card
shows no picture and says why. The Card shop shows these paths before installing, and an update that brings a new one
is confirmed by the administrator.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
import pytest
import respx
import yaml
from fastapi.testclient import TestClient

from app.adapters import get_adapter
from app.adapters.custom import PICTURE_REFUSED, present
from app.cards import images, load, pipeline
from app.services.collector import collector
from app.workshop import derived, updates

from .conftest import CSRF, setup_admin
from .karten8_sample import DOWNLOADS

BASE = "http://svc.example.com:8080"


def card(kind: str, read: str, picture: str) -> str:
    return f"""\
nexdeck-card: 1
slug: pictures
name: {{en: Pictures}}
version: 1.0.0
requires: [{kind}]
requests:
  - id: state
    path: {read}
form: posters
rows: {{select: "[@]"}}
item:
  title: name
  image: {{template: "{picture}"}}
"""


@pytest.fixture
def admin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    return client


def connect(client: TestClient, kind: str, config: dict[str, str]) -> int:
    made = client.post("/api/v1/integrations", json={"kind": kind, "name": kind, "config": {"url": BASE, **config}}, headers=CSRF)
    assert made.status_code == 201, made.text
    return int(made.json()["id"])


def codes(text: str) -> list[str]:
    with pytest.raises(load.CardInvalid) as invalid:
        load.load_definition(text)
    return [one.code for one in invalid.value.problems]


@pytest.mark.parametrize(
    ("kind", "picture"),
    [("shelly", "/relay/0?turn=off"), ("watchtower", "/v1/reboot"), ("sonarr", "/api/v3/system/restart"), ("custom:mine", "/api/shutdown")],
    ids=["shelly-turn", "word-reboot", "word-restart", "own-connection"],
)
def test_karten8u_b2_checking_a_card_refuses_a_picture_path_that_acts(kind: str, picture: str) -> None:
    assert codes(card(kind, "/status", picture)) == ["card_picture_acts"]


def test_karten8u_b2_a_picture_block_is_checked_the_same() -> None:
    text = """\
nexdeck-card: 1
slug: pictures
name: {en: Pictures}
version: 1.0.0
requires: [shelly]
requests:
  - id: state
    path: /status
form: builder
blocks:
  - type: image
    src: {template: "/relay/0?turn=off"}
"""
    assert codes(text) == ["card_picture_acts"]


def test_karten8u_b2_a_picture_path_that_only_reads_is_fine() -> None:
    load.load_definition(card("sonarr", "/api/v3/series", "/MediaCover/{id}/poster.jpg"))
    load.load_definition(card("shelly", "/status", "/status"))


def test_karten8u_b2_a_path_put_together_from_the_answer_is_not_signed_and_the_card_says_why() -> None:
    """A template that only reads when it is checked can still become a command with a value of the answer."""
    definition = load.load_definition(card("sonarr", "/api/v3/series", "/api/{action}").replace('"[@]"', '"@"')).definition
    rows = [{"name": "a", "action": "reboot"}, {"name": "b", "action": "poster.jpg"}]
    data = present(definition, pipeline.run(definition, {"state": rows}), base=BASE, adapter=get_adapter("sonarr"))
    assert "art" not in data.items[0]
    assert images.connection_path(data.items[1]["art"].removeprefix("proxy:"), BASE) == "/api/poster.jpg"
    assert data.meta["notice"] == PICTURE_REFUSED


def test_karten8u_b2_the_rules_of_the_kind_count_before_signing() -> None:
    """``turn`` is no word that acts for every kind; the list of Shelly forbids it."""
    assert images.reference("/relay/0?turn=off", BASE, named=False).startswith(f"proxy:{images.CONNECTION}?")
    with pytest.raises(Exception) as refused:
        images.reference("/relay/0?turn=off", BASE, named=False, adapter=get_adapter("shelly"))
    assert getattr(refused.value, "code", "") == "command_refused"
    # A value of the answer, as it stands, is the service's own picture: not a path the card made.
    assert images.reference("/relay/0?turn=off", BASE, named=True, adapter=get_adapter("shelly")).startswith(f"proxy:{images.CONNECTION}?")


def test_karten8u_b2_the_mark_of_a_made_path_is_signed() -> None:
    art = images.reference("/p/a.jpg", BASE, named=False).removeprefix("proxy:")
    assert images.made_by_card(art) and images.connection_path(art, BASE) == "/p/a.jpg"
    assert images.connection_path(art.replace("&m=1", ""), BASE) is None


def test_karten8u_b2_the_image_route_checks_a_made_path_again(admin: TestClient) -> None:
    """The second wall: signed before the kind's list said otherwise (or by a card checked against an older nexdeck)."""
    number = connect(admin, "shelly", {})
    art = images.reference("/relay/0?turn=off", BASE, named=False).removeprefix("proxy:")
    with respx.mock(assert_all_called=False) as svc:
        switched = svc.get(url__startswith=f"{BASE}/relay/0").mock(return_value=httpx.Response(200, json={"ison": False}))
        answer = admin.get(f"/api/v1/cards/preview-image?integration_id={number}&path={quote(art, safe='')}")
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == "command_refused"
    assert switched.call_count == 0


def test_karten8u_b2_probe_reboot_as_a_picture_no_longer_leaves(admin: TestClient) -> None:
    """The probe of the review, turned round: the card is refused and nothing is asked of the service."""
    number = connect(admin, "watchtower", {"token": "wt-token-123456"})
    text = card("watchtower", "/v1/status", "/v1/reboot")
    with respx.mock(assert_all_called=False) as svc:
        svc.get(f"{BASE}/v1/status").mock(return_value=httpx.Response(200, json={"name": "watchtower"}))
        acted = svc.get(f"{BASE}/v1/reboot").mock(return_value=httpx.Response(200, text="ok"))
        shown = admin.post("/api/v1/cards/preview", json={"yaml": text, "integration_id": number}, headers=CSRF)
    assert shown.status_code == 400, shown.text
    assert acted.call_count == 0
    assert admin.post("/api/v1/cards", json={"yaml": text}, headers=CSRF).status_code in (400, 422)


def _with_picture(template: str | None, version: str = "1.0.0") -> dict[str, Any]:
    data = yaml.safe_load(DOWNLOADS)
    data["version"] = version
    data["buttons"] = []
    if template is not None:
        data["item"]["image"] = {"template": template}
    return load.load_definition(yaml.safe_dump(data, sort_keys=False)).data


def test_karten8u_b2_the_shop_shows_the_picture_paths_of_a_card() -> None:
    data = yaml.safe_load(DOWNLOADS)
    data["item"]["image"] = {"template": "/api/v2/torrents/{hash}/thumb.jpg"}
    facts = derived.read(yaml.safe_dump(data, sort_keys=False))
    assert facts.pictures == [{"kind": "jsonapi", "path": "/api/v2/torrents/{hash}/thumb.jpg"}]


def test_karten8u_b2_an_update_that_brings_or_changes_a_picture_path_is_confirmed() -> None:
    before = _with_picture(None)
    brought = updates.permissions(before, _with_picture("/api/v2/thumb/{hash}.jpg", "1.1.0"))
    assert brought["pictures"] == {"added": ["/api/v2/thumb/{hash}.jpg"], "removed": []}
    assert updates.pictures_to_confirm(brought) == ["/api/v2/thumb/{hash}.jpg"]
    changed = updates.permissions(_with_picture("/api/v2/thumb/{hash}.jpg"), _with_picture("/api/v2/other/{hash}.jpg", "1.1.0"))
    assert updates.pictures_to_confirm(changed) == ["/api/v2/other/{hash}.jpg"]
    assert changed["pictures"]["removed"] == ["/api/v2/thumb/{hash}.jpg"]
    same = updates.permissions(_with_picture("/api/v2/thumb/{hash}.jpg"), _with_picture("/api/v2/thumb/{hash}.jpg", "1.1.0"))
    assert updates.pictures_to_confirm(same) == []
