"""Saved custom cards (KARTEN-1): the text word for word, one card per short name, a cache that never shows an old card."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cards import load, store
from app.db import db_session
from app.migrations import migrate
from app.models import CardRecord

from .cards_sample import VALUE_CARD, changed
from .conftest import setup_admin
from .test_backup import _archive, _make, _upload


@pytest.fixture
def db(data_dir) -> Iterator[Session]:  # noqa: ANN001
    migrate()
    with db_session() as session:
        yield session
    store.invalidate()


def count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(CardRecord)) or 0


def test_karten1_ac1_a_valid_definition_is_saved_and_an_invalid_one_leaves_nothing_behind(db: Session) -> None:
    with pytest.raises(load.CardInvalid):
        store.create(db, changed("form: value", "form: dial"))
    assert count(db) == 0
    row = store.create(db, VALUE_CARD)
    assert (row.slug, row.kind, row.origin, row.users_may_place) == ("queue-size", "card", "local", False)
    assert row.definition["form"] == "value" and count(db) == 1


def test_karten1_ac9_comments_survive_saving_opening_and_exporting(db: Session) -> None:
    store.create(db, VALUE_CARD)
    entry = store.get(db, "queue-size")
    assert entry is not None
    # what is opened and what is exported is the text that was typed, comment for comment
    assert entry.text == VALUE_CARD
    assert "# A comment on top stays where it is." in entry.text and "# either one" in entry.text
    row = db.scalar(select(CardRecord))
    assert row is not None and row.yaml_source == VALUE_CARD
    edited = changed("# A comment on top stays where it is.", "# Another comment\n# on two lines")
    store.update(db, row, edited)
    assert store.get(db, "queue-size").text == edited  # type: ignore[union-attr]


def test_karten1_ec5_a_short_name_that_is_taken_is_refused_with_the_line(db: Session) -> None:
    store.create(db, VALUE_CARD)
    with pytest.raises(load.CardInvalid) as caught:
        store.create(db, changed("name: {en: Queue, de: Warteschlange}", "name: Another"))
    problem = caught.value.problems[0]
    assert (problem.code, problem.path, problem.line, problem.params) == ("card_slug_taken", "slug", 3, {"slug": "queue-size"})
    assert count(db) == 1


def test_karten1_the_short_name_of_a_saved_card_does_not_change(db: Session) -> None:
    row = store.create(db, VALUE_CARD)
    with pytest.raises(load.CardInvalid) as caught:
        store.update(db, row, changed("slug: queue-size", "slug: queue-other"))
    assert caught.value.problems[0].code == "card_slug_changed"
    assert row.slug == "queue-size" and row.yaml_source == VALUE_CARD


def test_karten1_a_changed_or_removed_card_is_never_shown_as_it_was(db: Session) -> None:
    row = store.create(db, VALUE_CARD)
    first = store.get(db, "queue-size")
    assert first is not None and store.get(db, "queue-size") is first  # from memory the second time
    store.update(db, row, changed('version: "1.0.0"', 'version: "2.0.0"'))
    second = store.get(db, "queue-size")
    assert second is not None and second.definition.version == "2.0.0"
    store.set_users_may_place(db, row, True)
    assert store.get(db, "queue-size").users_may_place is True  # type: ignore[union-attr]
    store.delete(db, row)
    assert store.get(db, "queue-size") is None and count(db) == 0


def test_karten1_a_card_the_installed_nexdeck_cannot_read_stays_out_of_the_way(db: Session) -> None:
    row = store.create(db, VALUE_CARD)
    row.definition = {**row.definition, "form": "from-the-future"}
    db.commit()
    store.invalidate()
    assert store.get(db, "queue-size") is None
    assert [one.slug for one in store.listing(db)] == ["queue-size"]


def test_karten1_ec9_a_backup_brings_every_card_back_with_its_comments(client: TestClient) -> None:
    setup_admin(client)
    with db_session() as db:
        store.create(db, VALUE_CARD)
    entry = _make(client, "with a card")
    blob = _archive(client, entry["name"])
    with db_session() as db:
        store.delete(db, db.scalars(select(CardRecord)).one())
        assert store.get(db, "queue-size") is None

    restored = _upload(client, blob)
    assert restored.status_code == 200, restored.text
    with db_session() as db:
        again = store.get(db, "queue-size")
        assert again is not None
        assert again.text == VALUE_CARD and again.definition.name == {"en": "Queue", "de": "Warteschlange"}
