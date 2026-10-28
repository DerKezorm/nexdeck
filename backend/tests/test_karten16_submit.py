"""KARTEN-16: sharing a card in the Card shop, what became of it, and the way without signing in (AC-2, AC-5 to AC-10, EC-2 to EC-9)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.workshop import real_values, submit

from .cards_sample import DEMO_LINE, VALUE_CARD, changed
from .conftest import CSRF, create_user, login
from .karten14_sample import REPO, card_text
from .karten16_sample import DAY, Hub, account

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]

BASE = "/api/v1/workshop"
SLUG = "queue-size"
ME = 4242
KEY = "ghp_the-key-of-the-operator-0123456789"


@pytest.fixture
def github(hub: Hub) -> Hub:
    return hub


@pytest.fixture
def me(shop: TestClient, hub: Hub, moment: list[float]) -> TestClient:
    """An administrator with the shop on, signed in to GitHub as 'someone' (4242), and a card of his own."""
    sign_in(shop, hub, moment, hub.person("someone", ME))
    add_card(shop)
    return shop


def sign_in(client: TestClient, hub: Hub, moment: list[float], person: dict[str, Any]) -> None:
    assert client.post(f"{BASE}/github/login", headers=CSRF).status_code == 200
    hub.sign_in_as(person)
    moment[0] += 6
    done = client.post(f"{BASE}/github/login/poll", headers=CSRF).json()
    assert done["status"] == "signed_in", done


def add_card(client: TestClient, text: str = VALUE_CARD) -> None:
    made = client.post("/api/v1/cards", json={"yaml": text}, headers=CSRF)
    assert made.status_code == 201, made.text


def body(**more: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "type": "card", "slug": SLUG, "category": "media", "description": "Shows how many items wait in the queue.",
        "changes": "", "license": True,
    }
    found.update(more)
    return found


def post(client: TestClient, path: str, **more: Any) -> httpx.Response:
    return client.post(f"{BASE}/{path}", json=body(**more), headers=CSRF)


def share(client: TestClient, **more: Any) -> httpx.Response:
    return post(client, "submit", **more)


def check(client: TestClient, **more: Any) -> dict[str, Any]:
    found = post(client, "submit/check", **more)
    assert found.status_code == 200, found.text
    return found.json()


def codes(found: dict[str, Any]) -> list[str]:
    return [one["code"] for one in found["problems"]]


def accepted(hub: Hub, clock: list[float], number: int, text: str = VALUE_CARD, **more: Any) -> None:
    """The action takes issue ``number`` in, and the shop looks at its catalog again."""
    hub.accept(number, text, **more)
    clock[0] += 700


def put_issue(hub: Hub, slug: str, person: dict[str, Any] | None = None, *, update: bool = False, state: str = "open", text: str | None = None) -> int:
    """An issue as the form or nexdeck would have made it, put straight into the pretend repository."""
    who = person or hub.person("someone", ME)
    definition = text or card_text(slug=slug)
    hub.issues.append({
        "number": len(hub.issues) + 1, "title": f"{'Submit update: ' if update else 'Submit: '}{slug}",
        "body": submit.build_body(type="card", category="media", definition=definition, description="A card.", changes="More." if update else ""),
        "state": state, "user": who, "created_at": f"{DAY}T09:00:00Z",
    })
    return len(hub.issues)


def issues_made(hub: Hub) -> list[httpx.Request]:
    return [one for one in hub.requests if one.method == "POST" and one.url.path == f"/repos/{REPO}/issues"]


# -- the issue: its shape and its name (AC-5) -----------------------------------------------------------------------


def test_karten16_ac5_the_body_is_the_one_the_form_of_the_workshop_writes() -> None:
    """The text the Workshop's own ``issue_form.build_body`` wrote for these inputs, copied here; nexdeck adds only its version after it."""
    golden = (
        "### Type\n\nCard\n\n### Category\n\nSmart home\n\n### Definition\n\n```yaml\na: 1\nb: [x]\n```\n\n### Description\n\nSome text\n\n"
        "### Changes\n\nc\n\n### Based on\n\n1/x-y\n\n### Update of\n\n_No response_\n\n### License\n\n"
        "- [x] I submit this under the MIT License and I have the right to do so.\n"
    )
    made = submit.build_body(type="card", category="smart_home", definition="a: 1\nb: [x]\n", description="Some text", changes="c", based_on="1/x-y")
    assert made == golden.rstrip("\n") + f"\n\n### nexdeck version\n\n{__version__}\n"
    again = submit.parse_body(made)
    assert again["definition"] == "a: 1\nb: [x]\n" and again["changes"] == "c" and again["update_of"] == "" and again["version"] == __version__


def test_karten16_ac5_the_issue_stands_under_the_name_of_the_administrator_with_his_own_token(me: TestClient, hub: Hub, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXDECK_WORKSHOP_TOKEN", KEY)
    sent = share(me)
    assert sent.status_code == 200, sent.text
    assert sent.json()["created"] is True and sent.json()["update"] is False
    assert len(hub.issues) == 1
    issue = hub.issues[0]
    assert issue["user"]["login"] == "someone" and issue["title"] == f"Submit: {SLUG}"
    parts = [line[4:] for line in issue["body"].split("\n") if line.startswith("### ")]
    assert parts == ["Type", "Category", "Definition", "Description", "Changes", "Based on", "Update of", "License", "nexdeck version"], "nothing else goes in"
    fields = submit.parse_body(issue["body"])
    assert fields["definition"] == VALUE_CARD and fields["description"] == "Shows how many items wait in the queue."
    assert fields["category"] == "Media" and fields["version"] == __version__
    made = issues_made(hub)[0]
    assert made.headers["authorization"] != f"Bearer {KEY}" and made.headers["authorization"].startswith("Bearer ghu_")


def test_karten16_ac5_the_whole_text_of_the_card_goes_in_with_its_comments(me: TestClient, hub: Hub) -> None:
    share(me)
    assert submit.parse_body(hub.issues[0]["body"])["definition"].startswith("# A comment on top stays where it is.\n")


# -- what the dialog asks for (AC-2) --------------------------------------------------------------------------------


def test_karten16_ac2_the_dialog_is_told_what_the_card_is_and_what_it_is_missing(me: TestClient) -> None:
    found = check(me)
    assert found["problems"] == [] and found["name"] == "Queue" and found["version"] == "1.0.0" and found["mode"] == "new"
    assert found["suggested"] == {"description": "How many items wait in the queue.", "category": "media"}
    assert found["daily"] == {"used": 0, "max": 10, "reached": False} and found["login"] == "someone"



def test_karten16_ac2_the_check_of_the_dialog_judges_the_card_not_the_words_still_empty(me: TestClient) -> None:
    """The dialog asks before anything is typed, and again right after the sign-in: only which card, no words yet."""
    found = me.post(f"{BASE}/submit/check", json={"type": "card", "slug": SLUG}, headers=CSRF)
    assert found.status_code == 200, found.text
    assert found.json()["signed_in"] is True and found.json()["problems"] == []
    refused = me.post(f"{BASE}/submit", json={"type": "card", "slug": SLUG}, headers=CSRF)
    assert {"category", "description", "license"} <= {one["code"] for one in refused.json()["detail"]["problems"]}

@pytest.mark.parametrize(
    ("text", "code"),
    [
        (changed("demo:\n  queue: {totalRecords: 4, records: [{title: \"A\", size: 100}]}\n", "", VALUE_CARD), "card_needs_demo"),
        (changed("name: {en: Queue, de: Warteschlange}", "name: {de: Warteschlange}"), "card_needs_english"),
    ],
)
def test_karten16_ac2_a_card_without_demo_data_or_english_texts_is_not_shared(me: TestClient, hub: Hub, text: str, code: str) -> None:
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": text, "overwrite": True}, headers=CSRF)
    assert code in codes(check(me))
    refused = share(me)
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "submission_invalid"
    assert code in [one["code"] for one in refused.json()["detail"]["problems"]]
    assert hub.issues == []


@pytest.mark.parametrize(
    ("more", "code"),
    [({"description": "  "}, "description"), ({"category": ""}, "category"), ({"category": "cooking"}, "category"), ({"license": False}, "license")],
)
def test_karten16_ac2_description_category_and_the_mit_licence_are_asked_for(me: TestClient, hub: Hub, more: dict[str, Any], code: str) -> None:
    refused = share(me, **more)
    assert refused.status_code == 400
    assert code in [one["code"] for one in refused.json()["detail"]["problems"]]
    assert hub.issues == []


def test_karten16_ac2_a_key_in_the_description_is_refused(me: TestClient, hub: Hub) -> None:
    refused = share(me, description="Use ghp_abcdefghijklmnopqrstuvwxyz0123456789 to log in.")
    assert "secret_in_text" in [one["code"] for one in refused.json()["detail"]["problems"]]
    assert hub.issues == []


def test_karten16_ac2_an_own_connection_is_shared_like_a_card(me: TestClient, hub: Hub) -> None:
    from .karten3_sample import MEMOS

    made = me.post("/api/v1/own-integrations", json={"yaml": MEMOS}, headers=CSRF)
    assert made.status_code == 201, made.text
    short = made.json()["short"]
    found = check(me, type="integration", slug=short)
    assert found["problems"] == [] and found["type"] == "integration" and found["reads"], "the tile of a connection is its reads"
    sent = share(me, type="integration", slug=short, category="other")
    assert sent.status_code == 200, sent.text
    fields = submit.parse_body(hub.issues[0]["body"])
    assert fields["type"] == "Connection" and fields["definition"] == MEMOS


def test_karten16_ac2_what_is_not_there_is_not_found(me: TestClient) -> None:
    assert post(me, "submit/check", slug="nothing-here").status_code == 404
    assert post(me, "submit", slug="Not A Slug").status_code == 422


# -- a submission is read back (AC-6, EC-6) -------------------------------------------------------------------------


def listing(client: TestClient) -> dict[str, dict[str, Any]]:
    found = client.get(f"{BASE}/submissions")
    assert found.status_code == 200, found.text
    return {one["slug"]: one for one in found.json()["items"]}


def test_karten16_ac6_each_submission_has_the_state_the_action_gave_it(me: TestClient, hub: Hub, clock: list[float]) -> None:
    waiting = put_issue(hub, "waiting-card")
    failed = put_issue(hub, "failed-card")
    wait = put_issue(hub, "waits-for-tomorrow")
    taken = put_issue(hub, "taken-card")
    gone = put_issue(hub, "gone-card")
    edited = put_issue(hub, "edited-card")
    hub.reject(failed, "The demo data do not work with this card (line 12).", "Add a description.")
    hub.defer(wait)
    accepted(hub, clock, taken, card_text(slug="taken-card"), thumbs=7)
    accepted(hub, clock, gone, card_text(slug="gone-card"), removed={"level": "harmful", "reason": "It asks for the wrong thing.", "at": "2026-10-27T10:00:00Z"})
    hub.reject(edited, "Not yet.")
    hub.issues[edited - 1]["body"] += "\nMore words.\n"
    found = listing(me)
    assert waiting and found["waiting-card"]["state"] == "checking"
    assert found["failed-card"]["state"] == "failed" and found["failed-card"]["reasons"] == ["The demo data do not work with this card (line 12).", "Add a description."]
    assert found["waits-for-tomorrow"]["state"] == "waiting"
    assert found["taken-card"]["state"] == "in_shop" and found["taken-card"]["entry"]["thumbs"] == 7 and found["taken-card"]["entry"]["version"] == "1.0.0"
    assert found["gone-card"]["state"] == "removed" and found["gone-card"]["removed"]["level"] == "harmful"
    assert found["gone-card"]["removed"]["reason"] == "It asks for the wrong thing."
    assert found["edited-card"]["state"] == "checking", "a wording the action has not judged yet is in review again"
    assert found["failed-card"]["url"].endswith(f"/issues/{failed}")


def test_karten16_ac6_only_the_issues_of_this_account_and_only_submissions_are_shown(me: TestClient, hub: Hub) -> None:
    put_issue(hub, "mine")
    put_issue(hub, "theirs", hub.person("another", 99))
    hub.issues.append({"number": 3, "title": "A question", "body": "Hello", "state": "open", "user": hub.person("someone", ME), "created_at": f"{DAY}T09:00:00Z"})
    assert set(listing(me)) == {"mine"}


def test_karten16_ac6_the_newest_issue_of_a_name_tells_where_it_stands(me: TestClient, hub: Hub, clock: list[float]) -> None:
    first = put_issue(hub, SLUG, state="closed")
    accepted(hub, clock, first)
    put_issue(hub, SLUG, update=True)
    shown = listing(me)
    assert shown[SLUG]["state"] == "checking" and shown[SLUG]["update"] is True and shown[SLUG]["issue"] == 2


def test_karten16_ac6_the_list_is_read_from_github_and_asks_for_the_sign_in(client: TestClient, hub: Hub, shop: TestClient) -> None:
    found = shop.get(f"{BASE}/submissions").json()
    assert found == {"signed_in": False, "login": None, "items": [], "catalog_known": False}
    assert [one for one in hub.requests if one.url.path.startswith(f"/repos/{REPO}/issues")] == []


def test_karten16_ac6_without_the_shop_the_state_comes_from_the_issues_alone(me: TestClient, hub: Hub) -> None:
    taken = put_issue(hub, "taken-card")
    hub.accept(taken, card_text(slug="taken-card"))
    me.put(f"{BASE}/settings", json={"enabled": False}, headers=CSRF)
    found = me.get(f"{BASE}/submissions").json()
    assert found["catalog_known"] is False and found["items"][0]["state"] == "in_shop" and found["items"][0]["entry"] is None


def test_karten16_ec6_a_submission_shows_only_once_github_has_it_and_a_second_try_is_the_same_one(me: TestClient, hub: Hub) -> None:
    hub.lose_the_answer_of_the_next_issue = True
    lost = share(me)
    assert lost.status_code == 502 and lost.json()["detail"]["code"] == "github_unreachable"
    hub.issues.clear()  # GitHub did not get it after all
    assert listing(me) == {}
    hub.lose_the_answer_of_the_next_issue = True
    lost = share(me)
    assert lost.status_code == 502 and len(hub.issues) == 1, "GitHub got it, the answer was lost"
    again = share(me)
    assert again.status_code == 200 and again.json()["created"] is False and again.json()["changed"] is False
    assert len(hub.issues) == 1, "the second try is the issue that is there"
    assert set(listing(me)) == {SLUG}


def test_karten16_ec6_github_not_reachable_creates_nothing(me: TestClient, hub: Hub) -> None:
    hub.mode = "down"
    refused = share(me)
    assert refused.status_code == 502 and refused.json()["detail"]["code"] == "github_unreachable"
    hub.mode = "ok"
    assert hub.issues == []


# -- twice (EC-7) ----------------------------------------------------------------------------------------------------


def test_karten16_ec7_a_double_click_sends_it_once(me: TestClient, hub: Hub) -> None:
    first, second = share(me), share(me)
    assert first.status_code == 200 and second.status_code == 200
    assert len(hub.issues) == 1 and len(issues_made(hub)) == 1


def test_karten16_ec7_a_second_click_while_the_first_is_on_its_way_is_told_to_wait(me: TestClient, hub: Hub) -> None:
    submit._busy.add((1, "card", SLUG))  # noqa: SLF001 - the first click, still on its way
    waiting = share(me)
    assert waiting.status_code == 409 and waiting.json()["detail"]["code"] == "already_sending"
    assert hub.issues == []
    submit._busy.clear()  # noqa: SLF001
    assert share(me).status_code == 200 and len(hub.issues) == 1


def test_karten16_ec7_what_failed_does_not_block_the_next_try(me: TestClient, hub: Hub) -> None:
    hub.mode = "down"
    assert share(me).status_code == 502
    hub.mode = "ok"
    assert share(me).status_code == 200 and len(hub.issues) == 1


def test_karten16_ec7_a_changed_wording_goes_into_the_open_issue(me: TestClient, hub: Hub) -> None:
    share(me)
    again = share(me, description="Shows how many items wait for download, in a few words.")
    assert again.json()["created"] is False and again.json()["changed"] is True
    assert len(hub.issues) == 1 and "for download" in hub.issues[0]["body"]


# -- an update (AC-7) -----------------------------------------------------------------------------------------------


def test_karten16_ac7_a_card_that_is_in_the_shop_is_shared_again_as_an_update_with_its_changes(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1)
    newer = changed('version: "1.0.0"', 'version: "1.1.0"')
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": newer, "overwrite": True}, headers=CSRF)
    found = check(me)
    assert found["mode"] == "update" and found["previous_version"] == "1.0.0" and found["daily"] is None
    without = share(me)
    assert without.status_code == 400 and "changes" in [one["code"] for one in without.json()["detail"]["problems"]]
    sent = share(me, changes="Added the unit.")
    assert sent.status_code == 200 and sent.json()["update"] is True and sent.json()["created"] is True
    issue = hub.issues[1]
    assert issue["title"] == f"Submit update: {SLUG}" and submit.parse_body(issue["body"])["changes"] == "Added the unit."


def test_karten16_ac7_an_entry_in_the_catalog_makes_it_an_update_even_when_no_issue_of_it_is_left(me: TestClient, hub: Hub, clock: list[float]) -> None:
    hub.publish(VALUE_CARD, author=str(ME))
    clock[0] += 700
    found = check(me)
    assert found["mode"] == "update" and found["previous_version"] == "1.0.0"


def test_karten16_ac7_an_accepted_issue_makes_it_an_update_while_the_shop_is_off(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1)
    me.put(f"{BASE}/settings", json={"enabled": False}, headers=CSRF)
    found = check(me)
    assert found["mode"] == "update" and found["previous_version"] is None, "the closed issue with the answer of the action is enough"


def test_karten16_ac7_an_update_needs_a_higher_version(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1)
    found = check(me, changes="Nothing new.")
    assert "version_not_higher" in codes(found)
    assert share(me, changes="Nothing new.").status_code == 400
    assert len(hub.issues) == 1


def test_karten16_ac7_only_the_same_github_account_updates_it(me: TestClient, hub: Hub, clock: list[float], moment: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1)
    create_user(me, "second", role="admin")
    login(me, "second", "another-long-password")
    sign_in(me, hub, moment, hub.person("someone-else", 999))
    found = check(me)
    assert found["mode"] == "new" and found["previous_version"] is None, "the entry belongs to account 4242, not to this one"
    sent = share(me)
    assert sent.json()["update"] is False and hub.issues[1]["user"]["id"] == 999
    assert hub.issues[1]["title"] == f"Submit: {SLUG}"


def test_karten16_ac7_an_entry_taken_out_by_a_maintainer_is_not_updated_from_here(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1, removed={"level": "harmful", "reason": "Bad.", "at": "2026-10-27T10:00:00Z"})
    found = check(me)
    assert "entry_removed" in codes(found) and found["removed"]["level"] == "harmful"


def test_karten16_ac7_an_entry_withdrawn_by_its_author_may_come_back(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1, removed={"level": "withdrawn", "reason": "withdrawn by the author", "at": "2026-10-27T10:00:00Z"})
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": changed('version: "1.0.0"', 'version: "1.2.0"'), "overwrite": True}, headers=CSRF)
    assert "entry_removed" not in codes(check(me))


# -- based on (AC-8) ------------------------------------------------------------------------------------------------


def install_from_another(client: TestClient, hub: Hub, clock: list[float]) -> str:
    hub.publish(card_text(slug="their-card"), author="777")
    clock[0] += 700
    made = client.post(f"{BASE}/entries/777/their-card/install", json={"accept_risk": True}, headers=CSRF)
    assert made.status_code == 201, made.text
    return "their-card"


def test_karten16_ac8_a_card_made_from_somebody_elses_is_a_new_card_based_on_theirs(me: TestClient, hub: Hub, clock: list[float]) -> None:
    slug = install_from_another(me, hub, clock)
    row = me.get("/api/v1/cards").json()["cards"]
    assert [one["origin"] for one in row if one["slug"] == slug] == ["shop"]
    mine = card_text(slug=slug) + "# tuned for my server\n"
    me.put(f"/api/v1/cards/{slug}", json={"yaml": mine, "overwrite": True}, headers=CSRF)
    found = check(me, slug=slug)
    assert found["based_on"] == "777/their-card" and found["mode"] == "new"
    sent = share(me, slug=slug)
    assert sent.status_code == 200, sent.text
    fields = submit.parse_body(hub.issues[0]["body"])
    assert fields["based_on"] == "777/their-card" and hub.issues[0]["title"] == f"Submit: {slug}"


def test_karten16_ac8_somebody_elses_card_as_it_came_is_not_shared_in_the_name_of_this_account(me: TestClient, hub: Hub, clock: list[float]) -> None:
    slug = install_from_another(me, hub, clock)
    assert "unchanged_from_shop" in codes(check(me, slug=slug))
    refused = share(me, slug=slug)
    assert refused.status_code == 400 and hub.issues == []


# -- Fix and resend (AC-10) -----------------------------------------------------------------------------------------


def resend(client: TestClient, number: int) -> httpx.Response:
    return client.post(f"{BASE}/submit/resend", json={"issue": number}, headers=CSRF)


def test_karten16_ac10_the_corrected_card_goes_into_the_same_issue(me: TestClient, hub: Hub) -> None:
    share(me)
    hub.reject(1, "The demo data do not work with this card.")
    fixed = changed("unit: items", "unit: things")
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": fixed, "overwrite": True}, headers=CSRF)
    sent = resend(me, 1)
    assert sent.status_code == 200 and sent.json()["how"] == "edited", sent.text
    assert len(hub.issues) == 1 and submit.parse_body(hub.issues[0]["body"])["definition"] == fixed
    assert submit.parse_body(hub.issues[0]["body"])["description"] == "Shows how many items wait in the queue.", "the words stay"
    assert listing(me)[SLUG]["state"] == "checking", "edited, so the action has to judge it again"


def test_karten16_ac10_an_unchanged_card_is_asked_to_be_checked_again(me: TestClient, hub: Hub) -> None:
    share(me)
    hub.reject(1, "A lost network.")
    sent = resend(me, 1)
    assert sent.json()["how"] == "recheck"
    assert hub.comments[1][-1]["body"] == "/recheck" and hub.comments[1][-1]["user"]["login"] == "someone"


def test_karten16_ac10_only_an_open_submission_of_this_account_is_resent(me: TestClient, hub: Hub) -> None:
    other = put_issue(hub, SLUG, hub.person("another", 99))
    assert resend(me, other).status_code == 409
    done = put_issue(hub, SLUG, state="closed")
    assert resend(me, done).status_code == 409
    assert resend(me, 77).status_code == 403, "an issue that is not there looks like a repository that cannot be reached"


def test_karten16_ac10_a_card_that_is_still_wrong_is_not_sent(me: TestClient, hub: Hub) -> None:
    share(me)
    before = hub.issues[0]["body"]
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": changed("name: {en: Queue, de: Warteschlange}", "name: {de: Warteschlange}"), "overwrite": True}, headers=CSRF)
    refused = resend(me, 1)
    assert refused.status_code == 400 and hub.issues[0]["body"] == before


# -- signed out and withdrawn (EC-2) ---------------------------------------------------------------------------------


def test_karten16_ec2_a_sign_in_withdrawn_on_github_asks_again_and_the_submission_is_not_lost(me: TestClient, hub: Hub, moment: list[float]) -> None:
    hub.revoke_everything()
    lost = share(me)
    assert lost.status_code == 409 and lost.json()["detail"]["code"] == "github_login_needed"
    assert me.get(f"{BASE}/github").json()["signed_in"] is False
    assert check(me)["signed_in"] is False and hub.issues == []
    sign_in(me, hub, moment, hub.person("someone", ME))
    assert share(me).status_code == 200 and len(hub.issues) == 1, "the same words go out after the new sign-in"


def test_karten16_ec2_without_a_sign_in_nothing_is_sent(shop: TestClient, hub: Hub) -> None:
    add_card(shop)
    sent = share(shop)
    assert sent.status_code == 409 and sent.json()["detail"]["code"] == "github_login_needed"
    assert [one for one in hub.requests if one.url.path.startswith(f"/repos/{REPO}/issues")] == []


# -- the private repository (EC-3) ----------------------------------------------------------------------------------


def test_karten16_ec3_an_account_without_access_to_the_private_repository_gets_a_clear_sentence(me: TestClient, hub: Hub) -> None:
    hub.outsiders.add("someone")
    found = check(me)
    assert found["github"]["code"] == "repo_no_access" and "invited" in found["github"]["message"]
    refused = share(me)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "repo_no_access"
    assert hub.issues == []
    assert me.get(f"{BASE}/submissions").status_code == 403


# -- real values in the demo data (EC-4) ----------------------------------------------------------------------------


def card_with_demo(title: str) -> str:
    return changed(DEMO_LINE, f'demo:\n  queue: {{totalRecords: 4, records: [{{title: "{title}", size: 100}}]}}\n')


def test_karten16_ec4_demo_data_that_match_the_last_probe_are_warned_of_with_their_places(me: TestClient, hub: Hub) -> None:
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": card_with_demo("Peaky Blinders in my cellar"), "overwrite": True}, headers=CSRF)
    assert check(me)["warnings"]["real_values"] == []
    real_values.remember(account(1), {"records": [{"title": "Peaky Blinders in my cellar", "id": 4}], "note": "ok"})
    found = check(me)
    assert found["warnings"]["real_values"] == [{"path": "demo.queue.records[0].title", "value": "Peaky Blinders in my cellar"}]
    assert found["problems"] == [], "a warning, not a refusal"
    assert share(me).status_code == 200, "sharing stays possible"


def test_karten16_ec4_a_probe_of_another_administrator_or_of_yesterday_is_no_reason_to_warn(me: TestClient, hub: Hub, monkeypatch: pytest.MonkeyPatch) -> None:
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": card_with_demo("Peaky Blinders in my cellar"), "overwrite": True}, headers=CSRF)
    real_values.remember(account(2), {"title": "Peaky Blinders in my cellar"})
    assert check(me)["warnings"]["real_values"] == []
    real_values.remember(account(1), {"title": "Peaky Blinders in my cellar"})
    assert len(check(me)["warnings"]["real_values"]) == 1
    later = real_values.now() + 25 * 3600
    monkeypatch.setattr(real_values, "now", lambda: later)
    assert check(me)["warnings"]["real_values"] == []


def test_karten16_ec4_short_and_numeric_values_are_no_reason_to_warn() -> None:
    real_values.forget()
    who = SimpleNamespace(id=1, username="a", created_at=None)
    real_values.remember(who, {"state": "ok", "n": 12, "id": "12345", "version": "1.2.3", "name": "Living room lamp"})
    found = real_values.places(who, {"a": {"state": "ok", "id": "12345", "version": "1.2.3", "name": "Living room lamp"}})
    assert found == [{"path": "demo.a.name", "value": "Living room lamp"}]
    real_values.forget()


# -- too long (EC-5) ----------------------------------------------------------------------------------------------------


def test_karten16_ec5_a_submission_longer_than_an_issue_can_hold_is_told_before_it_is_sent() -> None:
    one = submit.Subject("card", SLUG, "x: 1\n" * 12_000, "local", "", False)
    long = submit.Form("media", "a" * 4000, "b" * 4000, True)
    assert [p["code"] for p in submit._length(one, long, None, True)] == ["too_long"]  # noqa: SLF001
    assert submit._length(submit.Subject("card", SLUG, "x: 1\n", "local", "", False), long, None, True) == []  # noqa: SLF001


def test_karten16_ec5_a_definition_over_the_limit_of_a_card_is_told(me: TestClient) -> None:
    from app.cards import schema

    one = submit.Subject("card", SLUG, "x" * (schema.MAX_DEFINITION + 1), "local", "", False)
    assert [p["code"] for p in submit.read_definition(one)] == ["too_long"]


# -- ten a day (EC-9) -----------------------------------------------------------------------------------------------------


def test_karten16_ec9_ten_new_ones_today_are_told_before_sending(me: TestClient, hub: Hub) -> None:
    for number in range(10):
        put_issue(hub, f"card-{number}", state="closed")
    found = check(me)
    assert found["daily"] == {"used": 10, "max": 10, "reached": True}
    refused = share(me)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "daily_limit"
    assert len(hub.issues) == 10


def test_karten16_ec9_nine_are_still_fine_and_yesterdays_do_not_count(me: TestClient, hub: Hub) -> None:
    for number in range(9):
        put_issue(hub, f"card-{number}")
    for number in range(5):
        put_issue(hub, f"old-{number}")
        hub.issues[-1]["created_at"] = "2026-10-27T09:00:00Z"
    assert check(me)["daily"] == {"used": 9, "max": 10, "reached": False}
    assert share(me).status_code == 200


def test_karten16_ec9_updates_do_not_count_against_the_ten(me: TestClient, hub: Hub, clock: list[float]) -> None:
    share(me)
    accepted(hub, clock, 1)
    for number in range(10):
        put_issue(hub, f"update-{number}", update=True, state="closed")
    me.put(f"/api/v1/cards/{SLUG}", json={"yaml": changed('version: "1.0.0"', 'version: "1.1.0"'), "overwrite": True}, headers=CSRF)
    sent = share(me, changes="A new unit.")
    assert sent.status_code == 200, sent.text


# -- without signing in (AC-9) ------------------------------------------------------------------------------------------


def test_karten16_ac9_without_signing_in_the_submission_is_a_file_and_a_link_to_the_form(shop: TestClient, hub: Hub) -> None:
    add_card(shop)
    before = len(hub.requests)
    found = post(shop, "submit/file")
    assert found.status_code == 200, found.text
    made = found.json()
    assert made["filename"] == f"nexdeck-submission-{SLUG}.md"
    assert submit.parse_body(made["text"])["definition"] == VALUE_CARD and "### License" in made["text"]
    link = httpx.URL(made["link"])
    assert (link.host, link.path) == ("github.com", f"/{REPO}/issues/new")
    assert dict(link.params) == {"template": "submit.yml", "title": f"Submit: {SLUG}", "type": "Card", "category": "Media", "description": "Shows how many items wait in the queue."}
    assert len(hub.requests) == before, "GitHub is not asked at all"


def test_karten16_ac9_the_file_asks_for_the_same_things_as_the_issue(shop: TestClient) -> None:
    add_card(shop)
    refused = post(shop, "submit/file", license=False, description="")
    assert refused.status_code == 400
    assert {one["code"] for one in refused.json()["detail"]["problems"]} == {"description", "license"}


def test_karten16_ac9_a_description_longer_than_an_address_holds_is_cut_in_the_link_only(shop: TestClient) -> None:
    add_card(shop)
    long = "word " * 700
    made = post(shop, "submit/file", description=long).json()
    assert len(dict(httpx.URL(made["link"]).params)["description"]) <= 1500 and long.strip() in made["text"]


# -- who may (everything above is for administrators) ------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), [("POST", "submit"), ("POST", "submit/check"), ("POST", "submit/file"), ("POST", "submit/resend"), ("GET", "submissions")])
def test_karten16_only_administrators_share(me: TestClient, method: str, path: str) -> None:
    create_user(me, "plain")
    login(me, "plain", "another-long-password")
    assert me.request(method, f"{BASE}/{path}", json=body() if method == "POST" else None, headers=CSRF).status_code == 403
    me.cookies.clear()
    assert me.request(method, f"{BASE}/{path}", json=body() if method == "POST" else None, headers=CSRF).status_code == 401


def test_karten16_the_sign_in_is_not_used_by_anyone_else(me: TestClient, hub: Hub, moment: list[float]) -> None:
    """A second administrator who has not signed in cannot send with the first one's token."""
    create_user(me, "second", role="admin")
    login(me, "second", "another-long-password")
    sent = share(me)
    assert sent.status_code == 409 and sent.json()["detail"]["code"] == "github_login_needed"
    assert hub.issues == []
    assert hub.sent == []
