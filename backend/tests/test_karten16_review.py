# ruff: noqa: F811
"""KARTEN-16, findings of the review: free text cannot write a field of the issue, an account owns its sign-in, and the smaller things.

The issue is read by the Workshop by its ``### heading`` lines and its code fences (``tools/issue_form.py`` there), so a line of
free text that looks like one must not be able to act as one (B1). The bodies below are copied to the tests of the Workshop,
which reads them with its own reader: the two repositories agree on them or one of the two tests is red.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.models import GithubLogin, User
from app.workshop import github_login, real_values, submit

from .conftest import ADMIN, CSRF, create_user, login
from .karten14_sample import card_text
from .karten16_sample import Hub, account
from .test_karten16_submit import (  # noqa: F401  (fixtures)
    BASE,
    SLUG,
    check,
    github,
    install_from_another,
    me,
    put_issue,
    share,
    sign_in,
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


# -- B2: the sign-in and the texts of the probes belong to the account, not to its number ------------------------------


def second_admin_waits_for_a_code(me: TestClient) -> dict[str, Any]:
    second = create_user(me, "second", role="admin")
    login(me, "second", "another-long-password")
    assert me.post(f"{BASE}/github/login", headers=CSRF).status_code == 200
    login(me, ADMIN["username"], ADMIN["password"])
    return second


def test_karten16_b2_a_new_account_with_the_number_of_a_deleted_one_inherits_no_code(me: TestClient, hub: Hub, moment: list[float]) -> None:
    second = second_admin_waits_for_a_code(me)
    assert me.delete(f"/api/v1/users/{second['id']}", headers=CSRF).status_code == 204
    third = create_user(me, "third", role="admin")
    assert third["id"] == second["id"], "SQLite gives the number again"
    login(me, "third", "another-long-password")
    assert me.get(f"{BASE}/github").json()["pending"] is None
    hub.sign_in_as(hub.person("second-on-github", 9001))  # the deleted person types the code on github.com
    moment[0] += 6
    assert me.post(f"{BASE}/github/login/poll", headers=CSRF).json() == {"status": "none"}
    assert me.get(f"{BASE}/github").json()["signed_in"] is False


def test_karten16_b2_deleting_the_account_deletes_its_code_and_its_probe_texts(me: TestClient) -> None:
    second = second_admin_waits_for_a_code(me)
    real_values.remember(account(second["id"]), {"title": "Private title of second"})
    assert second["id"] in github_login._pending and second["id"] in real_values._kept  # noqa: SLF001
    assert me.delete(f"/api/v1/users/{second['id']}", headers=CSRF).status_code == 204
    assert second["id"] not in github_login._pending and second["id"] not in real_values._kept  # noqa: SLF001


def test_karten16_b2_the_account_alone_tells_a_new_one_from_a_deleted_one(me: TestClient) -> None:
    """Whatever left in memory is not read by an account that is not the one that put it there (the removal itself is not relied on)."""
    second = second_admin_waits_for_a_code(me)
    real_values.remember(account(second["id"]), {"title": "Private title of second"})
    with db_session() as db:
        db.delete(db.get(User, second["id"]))  # not through the router: nothing is cleaned up
        db.commit()
    third = create_user(me, "third", role="admin")
    assert third["id"] == second["id"]
    login(me, "third", "another-long-password")
    assert me.get(f"{BASE}/github").json()["pending"] is None
    assert real_values.places(account(third["id"]), {"q": {"title": "Private title of second"}}) == []


def test_karten16_b2_taking_the_administrator_role_away_ends_the_sign_in(me: TestClient, hub: Hub, moment: list[float]) -> None:
    second = create_user(me, "second", role="admin")
    login(me, "second", "another-long-password")
    sign_in(me, hub, moment, hub.person("second-on-github", 9001))
    real_values.remember(account(second["id"]), {"title": "Private title of second"})
    login(me, ADMIN["username"], ADMIN["password"])
    assert me.patch(f"/api/v1/users/{second['id']}", json={"role": "user"}, headers=CSRF).status_code == 200
    with db_session() as db:
        assert db.get(GithubLogin, second["id"]) is None
    assert second["id"] not in real_values._kept  # noqa: SLF001


# -- B3: addresses, host names and e-mail addresses of the last probe are warned of too (EC-4) ---------------------------

WHO = SimpleNamespace(id=1, username="a", created_at=None)


def warned_of(probe: dict[str, Any], demo: dict[str, Any]) -> list[dict[str, str]]:
    real_values.forget()
    real_values.remember(WHO, probe)
    found = real_values.places(WHO, {"q": demo})
    real_values.forget()
    return found


def test_karten16_b3_an_ipv4_address_of_the_probe_is_warned_of() -> None:
    found = warned_of({"host": "192.168.178.20", "name": "nas-of-example"}, {"host": "192.168.178.20", "name": "nas-of-example"})
    assert found == [{"path": "demo.q.host", "value": "192.168.178.20"}, {"path": "demo.q.name", "value": "nas-of-example"}]


def test_karten16_b3_an_address_inside_a_longer_text_is_found_on_both_sides() -> None:
    found = warned_of({"url": "http://192.168.178.20:8989/api/v3/queue"}, {"note": "Reached at 192.168.178.20 over http."})
    assert found == [{"path": "demo.q.note", "value": "192.168.178.20"}]


def test_karten16_b3_an_ipv6_address_is_warned_of() -> None:
    found = warned_of({"url": "http://[fd00::1a2b]:8989/"}, {"host": "FD00::1A2B", "other": "fd00::9"})
    assert found == [{"path": "demo.q.host", "value": "fd00::1a2b"}]


def test_karten16_b3_a_host_name_inside_a_text_is_warned_of() -> None:
    found = warned_of({"url": "https://nas.homelab.example.net:8989/queue"}, {"server": "nas.homelab.example.net"})
    assert found == [{"path": "demo.q.server", "value": "nas.homelab.example.net"}]


def test_karten16_b3_an_e_mail_address_is_warned_of() -> None:
    found = warned_of({"owner": "Owner: jane.roe@mail.example.org"}, {"contact": "write to jane.roe@mail.example.org"})
    assert found == [{"path": "demo.q.contact", "value": "jane.roe@mail.example.org"}]


def test_karten16_b3_things_that_only_look_like_addresses_are_no_reason_to_warn() -> None:
    probe = {"version": "1.2.3", "time": "at 12:30:45", "size": "10.5 GB", "mail": "someone@example.com"}
    demo = {"version": "1.2.3", "time": "since 12:30:45", "size": "about 10.5 GB", "domain": "example.com"}
    assert warned_of(probe, demo) == []


# -- B4: one question to GitHub at a time for one account ---------------------------------------------------------------


async def two_polls_at_once(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    original = github_login.call

    async def over_the_network(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0)  # a real request gives the event loop away once, like this
        return await original(*args, **kwargs)

    monkeypatch.setattr(github_login, "call", over_the_network)
    with db_session() as one, db_session() as two:
        return list(await asyncio.gather(github_login.poll(one, 1), github_login.poll(two, 1)))


def test_karten16_b4_two_polls_at_once_ask_github_once(me: TestClient, hub: Hub, moment: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    me.delete(f"{BASE}/github", headers=CSRF)
    hub.person_at_the_screen = None
    assert me.post(f"{BASE}/github/login", headers=CSRF).status_code == 200
    moment[0] += 6
    before = hub.token_calls
    answers = asyncio.run(two_polls_at_once(monkeypatch))
    assert hub.token_calls - before == 1
    assert [one["status"] for one in answers] == ["pending", "pending"]


def test_karten16_b4_the_poll_that_waited_finds_the_sign_in_and_not_an_error(me: TestClient, hub: Hub, moment: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    me.delete(f"{BASE}/github", headers=CSRF)
    assert me.post(f"{BASE}/github/login", headers=CSRF).status_code == 200
    hub.sign_in_as(hub.person("someone", 4242))
    moment[0] += 6
    before = hub.token_calls
    answers = asyncio.run(two_polls_at_once(monkeypatch))
    assert hub.token_calls - before == 1
    assert [one["status"] for one in answers] == ["signed_in", "signed_in"] and answers[1]["login"] == "someone"


# -- B5: a second tab shows the code of the first and does not make it worthless -----------------------------------------


def test_karten16_b5_a_second_tab_gets_the_code_that_waits(me: TestClient, hub: Hub, moment: list[float]) -> None:
    me.delete(f"{BASE}/github", headers=CSRF)
    hub.person_at_the_screen = None
    before = hub.device_calls
    first = me.post(f"{BASE}/github/login", headers=CSRF).json()
    moment[0] += 100
    second = me.post(f"{BASE}/github/login", headers=CSRF).json()
    assert hub.device_calls - before == 1, "GitHub is asked for a code once"
    assert second["user_code"] == first["user_code"] and second["expires_in"] == first["expires_in"] - 100
    moment[0] += 6
    assert me.post(f"{BASE}/github/login/poll", headers=CSRF).json()["status"] == "pending"
    hub.sign_in_as(hub.person("someone", 4242))  # the code of tab 1 is typed on github.com: it still works
    moment[0] += 6
    assert me.post(f"{BASE}/github/login/poll", headers=CSRF).json()["status"] == "signed_in"


def test_karten16_b5_a_code_that_ran_out_is_replaced_by_a_new_one(me: TestClient, hub: Hub, moment: list[float]) -> None:
    me.delete(f"{BASE}/github", headers=CSRF)
    first = me.post(f"{BASE}/github/login", headers=CSRF).json()
    moment[0] += 901
    again = me.post(f"{BASE}/github/login", headers=CSRF).json()
    assert again["user_code"] != first["user_code"] and again["expires_in"] > 800


# -- B6: a renamed GitHub account still finds its issues ----------------------------------------------------------------


def test_karten16_b6_a_renamed_account_does_not_make_a_second_issue_for_the_same_card(me: TestClient, hub: Hub) -> None:
    assert share(me).status_code == 200
    for person in hub.tokens.values():
        person["login"] = "someone-renamed"
    hub.issues[0]["user"] = {**hub.issues[0]["user"], "login": "someone-renamed"}
    again = share(me)
    assert again.status_code == 200, again.text
    assert len(hub.issues) == 1 and again.json()["created"] is False
    assert me.get(f"{BASE}/github").json()["login"] == "someone-renamed"
    listed = me.get(f"{BASE}/submissions").json()
    assert [one["issue"] for one in listed["items"]] == [1] and listed["login"] == "someone-renamed"


def test_karten16_b6_the_name_is_asked_for_once_in_a_round(me: TestClient, hub: Hub) -> None:
    before = len([r for r in hub.requests if r.url.path == "/user"])
    assert share(me).status_code == 200
    assert len([r for r in hub.requests if r.url.path == "/user"]) - before == 1


# -- M1: only the issues of the GitHub number of this account are its own -------------------------------------------------


def test_karten16_m1_only_the_issues_of_the_github_number_of_this_account_are_its_own(me: TestClient, hub: Hub) -> None:
    """Somebody else who now carries the old name of this account (another number) has issues the list by name finds too."""
    put_issue(hub, SLUG, hub.person("someone", 999))
    assert me.get(f"{BASE}/submissions").json()["items"] == []
    sent = share(me)
    assert sent.status_code == 200 and sent.json()["created"] is True
    assert len(hub.issues) == 2 and hub.issues[0]["user"]["id"] == 999
    assert [one["issue"] for one in me.get(f"{BASE}/submissions").json()["items"]] == [2]
