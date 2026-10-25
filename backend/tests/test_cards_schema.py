"""The definition of a custom card (KARTEN-1): what is accepted, what is refused, and what the refusal says."""

from __future__ import annotations

import json

import pytest

from app import __version__
from app.cards import load, pipeline, schema

from .cards_sample import DEMO_LINE, VALUE_CARD, changed


def refused(text: str, **options: str) -> load.CardInvalid:
    with pytest.raises(load.CardInvalid) as caught:
        load.load_definition(text, **options)
    return caught.value


def codes(failure: load.CardInvalid) -> list[str]:
    return [problem.code for problem in failure.problems]


def line_of(text: str, needle: str) -> int:
    """The line a text stands on, counted from 1 like an editor does."""
    return next(number for number, line in enumerate(text.splitlines(), start=1) if needle in line)


def test_karten1_ac1_a_valid_definition_is_accepted_and_kept_as_json() -> None:
    loaded = load.load_definition(VALUE_CARD)
    definition = loaded.definition
    assert (definition.slug, definition.version, definition.min_nexdeck, definition.author, definition.category) == (
        "queue-size", "1.0.0", "0.40.0", "Example Author", "media",
    )  # fmt: skip
    assert definition.name == {"en": "Queue", "de": "Warteschlange"}
    assert loaded.data["nexdeck-card"] == 1 and loaded.data["form"] == "value"
    json.dumps(loaded.data)  # it is plain JSON
    assert load.definition_from_data(loaded.data) == definition


def test_karten1_ac1_a_definition_that_does_not_fit_the_schema_is_not_accepted() -> None:
    for old, new in (
        ("slug: queue-size\n", ""),
        ("form: value", "form: dial"),
        ('version: "1.0.0"', "version: soon"),
        ("requests:\n  - id: queue\n    path: /api/v3/queue\n    every: 30s\n", "requests: []\n"),
        ("form: value\nvalue:", "form: value\nvalu:"),
    ):
        assert refused(changed(old, new)).problems, old


def test_karten1_ac2_the_message_names_the_field_the_line_and_the_reason() -> None:
    text = changed("author: Example Author", "autor: Example Author")
    failure = refused(text)
    problem = failure.problems[0]
    assert (problem.code, problem.path, problem.line) == ("card_unknown_field", "autor", line_of(text, "autor"))
    assert "autor" in problem.message and "not a field" in problem.message
    assert f"(line {problem.line})" in str(failure)

    text = changed("every: 30s", "every: 5x")
    problem = refused(text).problems[0]
    assert (problem.path, problem.line, problem.code) == ("requests[0].every", line_of(text, "every:"), "card_bad_form")

    shown = "value:\n  path: totalRecords\n  label: {en: Waiting, de: Wartend}\n  unit: items"
    problem = refused(changed(shown, "value:\n  label: x")).problems[0]
    assert (problem.code, problem.path) == ("card_one_of", "value")


def test_karten1_ac2_text_that_is_not_yaml_gets_the_line_of_the_break() -> None:
    text = changed("category: media", "category: [media")
    problem = refused(text).problems[0]
    assert problem.code == "card_yaml" and problem.line is not None and problem.line > line_of(text, "category")
    assert refused("just words").problems[0].code == "card_not_a_mapping"
    assert refused("").problems[0].code == "card_empty"


def test_karten1_ac2_every_problem_comes_at_once() -> None:
    text = changed("slug: queue-size", "slug: Queue Size")
    text = changed("form: value", "form: value\nbogus: 1", text)
    assert {"card_bad_slug", "card_unknown_field"} <= set(codes(refused(text)))


def test_karten1_ac3_a_card_that_needs_a_newer_nexdeck_is_refused_with_the_version() -> None:
    text = changed('min_nexdeck: "0.40.0"', 'min_nexdeck: "99.0.0"')
    problem = refused(text).problems[0]
    assert problem.code == "card_needs_newer"
    assert problem.params == {"need": "99.0.0", "have": __version__} and "99.0.0" in problem.message
    assert problem.line == line_of(text, "min_nexdeck")
    # a card that needs exactly this version, or an older one, runs
    load.load_definition(changed('"0.40.0"', f'"{__version__}"'))
    load.load_definition(changed('"0.40.0"', '"0.9"'))
    assert refused(changed('"0.40.0"', '"0.49.0"'), running_version="0.48.0").problems[0].code == "card_needs_newer"
    load.load_definition(changed('"0.40.0"', '"0.49.0"'), running_version="0.49.0")


def test_karten1_a_rule_looks_at_one_thing() -> None:
    both = changed("{value: totalRecords, op: \">=\"", "{value: totalRecords, formula: \"1\", op: \">=\"")
    assert refused(both).problems[0].code == "card_one_of"
    alone = changed("{value: totalRecords, op: \">=\", than: 10, then: warn}", "{op: \">=\", than: 10, then: warn}")
    assert refused(alone).problems[0].code == "card_rule_subject"


def test_karten1_ac4_a_card_names_the_connection_it_needs() -> None:
    assert load.load_definition(VALUE_CARD).definition.requires == ["sonarr", "radarr"]
    one = load.load_definition(changed("requires: [sonarr, radarr]", "requires: [jsonapi]")).definition
    assert one.requires == ["jsonapi"]
    own = load.load_definition(changed("requires: [sonarr, radarr]", "requires: ['custom:my-service']")).definition
    assert own.requires == ["custom:my-service"]


def test_karten1_ac4_a_card_without_one_or_with_a_kind_nexdeck_does_not_know_is_refused() -> None:
    assert refused(changed("requires: [sonarr, radarr]", "requires: []")).problems[0].code == "card_too_few"
    assert refused(changed("requires: [sonarr, radarr]", "requires: [sonar]")).problems[0].code == "card_unknown_kind"
    assert refused(changed("requires: [sonarr, radarr]   # either one\n", "")).problems[0].code == "card_missing_field"


def test_karten1_ac5_ac6_texts_stay_as_the_author_wrote_them() -> None:
    data = load.load_definition(VALUE_CARD).data
    assert data["name"] == {"en": "Queue", "de": "Warteschlange"}
    assert data["value"]["label"] == {"en": "Waiting", "de": "Wartend"}
    # one language only: not turned into several, not translated, not completed
    assert data["description"] == "How many items wait in the queue."
    assert data["value"]["unit"] == "items"


def test_karten1_ac7_a_value_shaped_like_a_secret_is_refused_and_says_why() -> None:
    for secret in (
        "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4",
        "Bearer abcdefghijklmnop",
        "https://user:hunter2@example.com/x",
        "0123456789abcdef" * 2,
        "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MDEyMzQ1Ng",
    ):
        text = changed("author: Example Author", f"author: {json.dumps(secret)}")
        problem = refused(text).problems[0]
        assert problem.code == "card_secret_value", secret
        assert problem.line == line_of(text, "author:") and "secret" in problem.message


def test_karten1_ac7_a_key_in_the_query_of_a_path_is_refused_but_a_placeholder_is_not() -> None:
    problem = refused(changed("path: /api/v3/queue", "path: /api/v3/queue?apikey=abc123")).problems[0]
    assert (problem.code, problem.path) == ("card_secret_value", "requests[0].path")
    load.load_definition(changed("path: /api/v3/queue", "path: /api/v3/queue?apikey={api_key}&page=1"))


def test_karten1_ac7_a_field_for_headers_or_a_credential_is_refused() -> None:
    for field in ("headers: {X-Thing: 1}", "Authorization: x", "api_token: x", "password: x", "cookie: x"):
        text = changed("category: media", f"category: media\n{field}")
        problem = refused(text).problems[0]
        assert problem.code == "card_secret_field", field
        assert problem.line == line_of(text, field)
    assert "headers" in refused(changed("every: 30s", "every: 30s\n    headers: {a: b}")).problems[0].message


def test_karten1_ac7_demo_answers_may_hold_what_a_service_sends() -> None:
    sent = 'demo:
  queue: {hash: "' + "0123456789abcdef" * 2 + '01234567", token: "x", records: []}
'
    load.load_definition(changed(DEMO_LINE, sent))
    # but not a credential that is unmistakably one
    leak = 'demo:\n  queue: {note: "Bearer abcdefghijklmnop"}\n'
    assert refused(changed(DEMO_LINE, leak)).problems[0].code == "card_secret_value"


def test_karten1_ac8_a_definition_over_sixty_thousand_characters_is_refused_with_length_and_limit() -> None:
    padded = VALUE_CARD + "#" * (schema.MAX_DEFINITION - len(VALUE_CARD) - 1) + "\n"
    assert len(padded) == schema.MAX_DEFINITION
    load.load_definition(padded)
    problem = refused(padded + "#").problems[0]
    assert problem.code == "card_definition_too_long"
    assert problem.params == {"length": 60_001, "limit": 60_000}
    assert "60001" in problem.message and "60000" in problem.message


def test_karten1_ac8_the_demo_answers_count_toward_the_limit() -> None:
    big = 'demo:\n  queue: {text: "' + "x" * 60_000 + '"}\n'
    assert refused(changed(DEMO_LINE, big)).problems[0].code == "card_definition_too_long"


def test_karten1_ac10_a_definition_can_carry_demo_answers_for_the_preview() -> None:
    definition = load.load_definition(VALUE_CARD).definition
    answers = pipeline.demo_answers(definition)
    assert answers == {"queue": {"totalRecords": 4, "records": [{"title": "A", "size": 100}]}}
    result = pipeline.run(definition, answers or {})
    assert result.value is not None and result.value.text == "4"


def test_karten1_ac10_demo_answers_keep_what_a_service_sent_nulls_included() -> None:
    text = changed(DEMO_LINE, "demo:\n  queue: {totalRecords: null, records: [{title: null, size: 0}]}\n")
    loaded = load.load_definition(text)
    assert loaded.data["demo"] == {"queue": {"totalRecords": None, "records": [{"title": None, "size": 0}]}}


def test_karten1_ac10_a_demo_answer_must_belong_to_a_request() -> None:
    text = changed("demo:\n  queue:", "demo:\n  quue:")
    problem = refused(text).problems[0]
    assert problem.code == "card_demo_unknown_request" and problem.line == line_of(text, "quue")


def test_karten1_ac11_a_definition_without_demo_data_is_saved_locally_and_marked_for_the_shop() -> None:
    loaded = load.load_definition(changed(DEMO_LINE, ""))
    assert pipeline.demo_answers(loaded.definition) is None
    assert [problem.code for problem in load.check_for_submission(loaded.definition)] == ["card_needs_demo"]
    assert load.check_for_submission(load.load_definition(VALUE_CARD).definition) == []


def test_karten1_ac12_name_label_and_description_have_limits_that_are_named() -> None:
    def limit_of(old: str, new: str) -> dict[str, object]:
        problem = refused(changed(old, new)).problems[0]
        assert problem.code == "card_too_long"
        return {"path": problem.path, **problem.params}

    name = "name: {en: Queue, de: Warteschlange}"
    assert limit_of(name, "name: " + "n" * 61) == {"path": "name", "length": 61, "limit": 60}
    assert limit_of(name, "name: {en: Queue, de: " + "n" * 61 + "}")["limit"] == 60
    assert limit_of("unit: items", "unit: " + "u" * 41) == {"path": "value.unit", "length": 41, "limit": 40}
    assert limit_of("label: {en: Waiting, de: Wartend}", "label: " + "l" * 41)["limit"] == 40
    description = "description: How many items wait in the queue."
    assert limit_of(description, "description: " + "d" * 2001) == {"path": "description", "length": 2001, "limit": 2000}
    # exactly the limit is fine
    load.load_definition(changed(name, "name: " + "n" * 60))
    load.load_definition(changed("unit: items", "unit: " + "u" * 40))
    load.load_definition(changed(description, "description: " + "d" * 2000))


def test_karten1_ec1_a_higher_format_is_refused_instead_of_dropping_fields() -> None:
    text = changed("nexdeck-card: 1", "nexdeck-card: 2") + "brand_new_field: 1\n"
    failure = refused(text)
    assert codes(failure) == ["card_needs_newer_format"]
    assert failure.problems[0].params == {"format": 2, "known": schema.FORMAT_VERSION}
    assert failure.problems[0].line == line_of(text, "nexdeck-card")
    assert "newer nexdeck" in failure.problems[0].message
    assert codes(refused(changed("nexdeck-card: 1\n", ""))) == ["card_missing_field"]
    assert codes(refused(changed("nexdeck-card: 1", "nexdeck-card: one"))) == ["card_wrong_type"]


def test_karten1_ec2_an_older_format_is_read_and_comes_out_in_the_new_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # Format 2 does not exist yet; this stands in for the day it does: nothing but the number differs.
    monkeypatch.setattr(schema, "FORMAT_VERSION", 2)
    monkeypatch.setitem(load.UPGRADES, 1, lambda data: {**data, "nexdeck-card": 2})
    loaded = load.load_definition(VALUE_CARD)
    assert loaded.source_format == 1 and loaded.data["nexdeck-card"] == 2
    assert loaded.data["slug"] == "queue-size" and loaded.data["demo"]["queue"]["totalRecords"] == 4
    assert loaded.definition.requests[0].path == "/api/v3/queue"


def test_karten1_ec3_a_name_of_spaces_or_empty_is_refused() -> None:
    for name in ('""', '"   "', "{en: ' '}", "{}"):
        problem = refused(changed("name: {en: Queue, de: Warteschlange}", f"name: {name}")).problems[0]
        assert (problem.code, problem.path) == ("card_blank", "name"), name
    assert refused(changed("name: {en: Queue, de: Warteschlange}", "name:")).problems[0].path == "name"


def test_karten1_ec4_a_name_with_emoji_and_umlauts_is_kept_and_the_short_name_is_plain() -> None:
    loaded = load.load_definition(changed("name: {en: Queue, de: Warteschlange}", 'name: "Wärme \U0001f321 Übersicht"'))
    assert loaded.definition.name == "Wärme \U0001f321 Übersicht"
    assert json.loads(json.dumps(loaded.data))["name"] == "Wärme \U0001f321 Übersicht"
    for slug in ("Queue", "queue_size", "qüeue", "-queue", "queue size", "q" * 61, ""):
        assert refused(changed("slug: queue-size", f'slug: "{slug}"')).problems[0].code in ("card_bad_slug", "card_too_long"), slug
    for slug in ("queue", "a-b-1", "9lives", "q" * 60):
        assert load.load_definition(changed("slug: queue-size", f"slug: {slug}")).definition.slug == slug


def test_karten1_ec6_a_text_without_english_is_saved_locally_but_not_handed_in() -> None:
    loaded = load.load_definition(changed("name: {en: Queue, de: Warteschlange}", "name: {de: Warteschlange}"))
    problems = load.check_for_submission(loaded.definition)
    assert [(problem.code, problem.path) for problem in problems] == [("card_needs_english", "name")]


def test_karten1_ec7_spaces_at_the_edges_of_names_and_labels_are_removed() -> None:
    text = changed("name: {en: Queue, de: Warteschlange}", 'name: {en: "  Queue ", de: " Warteschlange"}')
    text = changed("unit: items", 'unit: "  items "', text)
    loaded = load.load_definition(text)
    assert loaded.definition.name == {"en": "Queue", "de": "Warteschlange"}
    assert loaded.definition.value.unit == "items"
    assert loaded.data["name"]["en"] == "Queue"


def test_karten1_ec8_html_in_a_text_is_kept_as_the_text_it_is() -> None:
    hostile = "<img src=x onerror=alert(1)>"
    loaded = load.load_definition(changed("description: How many items wait in the queue.", f"description: {json.dumps(hostile)}"))
    # nothing is stripped and nothing is run; showing it as plain text is the job of the frontend (cardText.test.tsx)
    assert loaded.definition.description == hostile
    assert loaded.data["description"] == hostile


def test_karten1_yaml_no_anchors_no_duplicate_fields_and_no_surprises() -> None:
    problem = refused(changed("requires: [sonarr, radarr]", "requires: &r [sonarr]")).problems[0]
    assert problem.code == "card_yaml" and "anchors" in problem.message
    assert codes(refused(changed("category: media", "category: media\ncategory: tv"))) == ["card_duplicate_key"]
    # the language "no" is a key, not a boolean; a date-like text is a text
    text = changed("name: {en: Queue, de: Warteschlange}", "name: {en: Queue, no: Ko}")
    assert load.load_definition(text).definition.name == {"en": "Queue", "no": "Ko"}
    assert load.load_definition(changed("category: media", "category: 2026-10-25")).definition.category == "2026-10-25"
    assert codes(refused(changed("category: media", "category: media\n1: x"))) == ["card_key_not_text"]
    assert codes(refused(changed('version: "1.0.0"', "version: 1.10"))) == ["card_quote_it"]
    assert load.load_definition(changed('version: "1.0.0"', "version: 2")).definition.version == "2"


def test_karten1_a_request_stays_underneath_the_connection() -> None:
    for path in ("http://example.com/x", "//example.com/x", "api/v3/queue", "/a/../b c", "/a\\b", "/a\nb"):
        assert refused(changed("path: /api/v3/queue", f"path: {json.dumps(path)}")).problems[0].code == "card_bad_path", path
    for every in ("5s", "2d", "0m", "100000s"):
        assert refused(changed("every: 30s", f"every: {every}")).problems, every
    assert schema.every_seconds("5m") == 300 and schema.every_seconds(None) is None


def test_karten1_a_value_can_be_just_its_path() -> None:
    long_form = "value:\n  path: totalRecords\n  label: {en: Waiting, de: Wartend}\n  unit: items\n"
    loaded = load.load_definition(changed(long_form, "value: totalRecords\n"))
    assert loaded.definition.value.path == "totalRecords"
    assert loaded.data["value"] == {"path": "totalRecords", "rules": []}


def test_karten1_t1_the_json_schema_describes_the_four_forms() -> None:
    document = schema.json_schema()
    assert document["title"] == "nexdeck card"
    assert len(document["oneOf"]) == 4 and document["discriminator"]["propertyName"] == "form"
    value_card = document["$defs"]["ValueCard"]
    assert "nexdeck-card" in value_card["properties"] and "nexdeck-card" in value_card["required"]
    assert value_card["properties"]["name"]["anyOf"][0]["maxLength"] == 60
    assert value_card["additionalProperties"] is False
    json.dumps(document)
