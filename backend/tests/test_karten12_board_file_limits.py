"""KARTEN-12 EC-1: a board file nested too deeply, or one that repeats itself through YAML anchors, is refused with a reason
before anything is built from it; an exported board carries no anchors."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient

from app.adapters import forget_all_custom
from app.services import board_definitions
from app.services.boards import PlainDumper, most_resolved, resolved_size
from app.services.collector import collector

from .conftest import CSRF, login, setup_admin
from .karten12_sample import PLAIN, card

API = "/api/v1/boards"


@pytest.fixture
def member(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A member whose 500s come back as answers."""
    setup_admin(client)
    monkeypatch.setattr(collector, "running", False)
    made = client.post("/api/v1/users", json={"username": "kim", "password": "another-long-password", "role": "user"}, headers=CSRF)
    assert made.status_code == 201, made.text
    one = TestClient(client.app, raise_server_exceptions=False)
    login(one, "kim", "another-long-password")
    yield one
    forget_all_custom()


def big_card() -> str:
    """A card of about 50 KB, most of it a comment."""
    return card("a-card", PLAIN).replace("description:", "# " + "x" * 50_000 + "\ndescription:", 1)


def repeated(times: int) -> str:
    """The reviewer's file: the big card once under an anchor, then ``times`` aliases of it in ``custom_cards``."""
    first = yaml.safe_dump([big_card()]).replace("- ", "- &c ", 1).rstrip("\n")
    return (
        "board: {name: x}\npages: [{name: p, widgets: []}]\ncustom_cards:\n"
        + "\n".join(f"  {line}" for line in first.split("\n")) + "\n" + "".join("  - *c\n" for _ in range(times))
    )


def size_of(text: str) -> int:
    return resolved_size(yaml.compose(text, Loader=yaml.SafeLoader))


def refused(answer) -> str:  # noqa: ANN001
    assert answer.status_code == 400, (answer.status_code, answer.text[:200])
    assert answer.json()["detail"]["code"] == "bad_import"
    return answer.json()["detail"]["message"]


def test_karten12_ec1_a_board_file_nested_too_deeply_is_refused_with_a_reason(member: TestClient) -> None:
    deep = "board: {name: x}\npages: []\nextra: " + "[" * 5000 + "]" * 5000 + "\n"
    assert "nested too deeply" in refused(member.post(f"{API}/import/check", json={"yaml_text": deep}, headers=CSRF))
    assert "nested too deeply" in refused(member.post(f"{API}/import", json={"yaml_text": deep}, headers=CSRF))


def test_karten12_ec1_a_board_file_that_repeats_a_card_through_anchors_is_refused_before_it_is_read(member: TestClient) -> None:
    text = repeated(249)
    # Counted on the nodes: 250 copies of 50 KB, against a file of about 50 KB.
    assert size_of(text) > 250 * 50_000 > most_resolved(text)
    for route in ("import/check", "import"):
        assert "anchors" in refused(member.post(f"{API}/{route}", json={"yaml_text": text}, headers=CSRF))


def test_karten12_ec1_an_anchor_used_a_little_still_reads(member: TestClient) -> None:
    text = "board: {name: x}\npages:\n- {name: a, widgets: &w [{kind: core.clock}]}\n- {name: b, widgets: *w}\n"
    assert size_of(text) <= most_resolved(text)
    assert member.post(f"{API}/import/check", json={"yaml_text": text}, headers=CSRF).status_code == 200
    made = member.post(f"{API}/import", json={"yaml_text": text}, headers=CSRF)
    assert made.status_code == 201 and [len(page["widgets"]) for page in made.json()["pages"]] == [1, 1]


def test_karten12_ec1_a_file_without_anchors_never_comes_near_the_limit() -> None:
    text = yaml.safe_dump({"board": {"name": "x"}, "pages": [{"name": "p", "widgets": []}], "custom_cards": [big_card(), PLAIN]})
    assert size_of(text) <= len(text) + 1000


def test_karten12_ec1_an_exported_board_writes_what_is_shared_twice_and_not_as_an_anchor() -> None:
    shared = {"x": 0, "y": 0, "w": 4, "h": 2}
    document = {"pages": [{"widgets": [{"layout": {"lg": shared, "md": shared}}]}]}
    assert "&id" not in yaml.dump(document, Dumper=PlainDumper)
    assert "&" not in board_definitions.dump(document) and "*" not in board_definitions.dump(document)
    assert "&id" in yaml.safe_dump(document)  # what the plain dumper of PyYAML would have written
