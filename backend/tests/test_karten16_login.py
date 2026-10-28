"""KARTEN-16: signing in to GitHub from nexdeck (AC-3, AC-4, EC-1, EC-2, EC-8)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import db_session
from app.models import GithubLogin, User
from app.workshop import github_login

from .conftest import ADMIN, CSRF, create_user, login, setup_admin
from .karten16_sample import CLIENT_ID, Hub

pytest_plugins = ["tests.karten14_sample", "tests.karten16_sample"]

BASE = "/api/v1/workshop/github"


@pytest.fixture
def github(hub: Hub) -> Hub:
    return hub


@pytest.fixture
def admin(client: TestClient, hub: Hub, moment: list[float]) -> TestClient:
    setup_admin(client)
    return client


def start(client: TestClient) -> dict:
    found = client.post(f"{BASE}/login", headers=CSRF)
    assert found.status_code == 200, found.text
    return found.json()


def poll(client: TestClient) -> dict:
    found = client.post(f"{BASE}/login/poll", headers=CSRF)
    assert found.status_code == 200, found.text
    return found.json()


def sign_in(client: TestClient, hub: Hub, moment: list[float], person: dict | None = None) -> dict:
    """The whole way: a code, the person types it, the next question is answered."""
    start(client)
    hub.sign_in_as(person or hub.person())
    moment[0] += 6
    return poll(client)


def row(user: str = "admin") -> GithubLogin | None:
    with db_session() as db:
        found = db.scalar(select(GithubLogin).join(User, User.id == GithubLogin.user_id).where(User.username == user))
        db.expunge_all()
        return found


def test_karten16_ac3_nexdeck_shows_a_code_and_a_link_and_the_person_is_signed_in_after_typing_it(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    assert admin.get(BASE).json() == {"signed_in": False, "login": None, "github_id": None, "until": None, "pending": None}
    code = start(admin)
    assert code["user_code"].startswith("WDJB-") and code["verification_uri"] == "https://github.com/login/device"
    assert code["interval"] == 5 and 0 < code["expires_in"] <= 900
    assert admin.get(BASE).json()["pending"]["user_code"] == code["user_code"]
    moment[0] += 6
    assert poll(admin) == {"status": "pending", "interval": 5}
    hub.sign_in_as(hub.person("someone", 4242))
    moment[0] += 6
    done = poll(admin)
    assert done["status"] == "signed_in" and done["login"] == "someone" and done["github_id"] == "4242"
    assert admin.get(BASE).json()["signed_in"] is True and admin.get(BASE).json()["pending"] is None
    # Only the public Client ID goes out: no secret, in the code request and in the question for the token.
    sent = [request.content.decode() for request in hub.requests if request.url.host == "github.com"]
    assert sent and all("secret" not in one for one in sent)
    assert all(f"client_id={CLIENT_ID}" in one for one in sent)


def test_karten16_ac3_github_is_asked_no_faster_than_it_allows(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    start(admin)
    assert poll(admin)["status"] == "pending" and hub.token_calls == 0, "not before the interval is over"
    moment[0] += 5
    poll(admin)
    assert hub.token_calls == 1
    poll(admin)
    assert hub.token_calls == 1, "a second question inside the interval is not sent"
    hub.slow_down = 1
    moment[0] += 5
    assert poll(admin) == {"status": "pending", "interval": 10}
    moment[0] += 6
    assert poll(admin)["status"] == "pending" and hub.token_calls == 2, "slow_down made the wait ten seconds"
    moment[0] += 5
    poll(admin)
    assert hub.token_calls == 3


def test_karten16_ac3_a_refusal_on_github_ends_the_wait(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    start(admin)
    hub.answer_with = "access_denied"
    moment[0] += 6
    assert poll(admin) == {"status": "denied"}
    assert poll(admin) == {"status": "none"}


def test_karten16_ac3_the_client_id_comes_from_the_setting(admin: TestClient, hub: Hub, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXDECK_WORKSHOP_CLIENT_ID", "Iv-other")
    found = admin.post(f"{BASE}/login", headers=CSRF)
    assert found.status_code == 502 and found.json()["detail"]["code"] == "github_login_failed"
    assert hub.requests[-1].content.decode() == "client_id=Iv-other"


def test_karten16_ec1_a_code_that_ran_out_is_replaced_by_a_new_one(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    first = start(admin)
    moment[0] += 901
    assert poll(admin) == {"status": "expired"}
    assert admin.get(BASE).json()["pending"] is None
    second = start(admin)
    assert second["user_code"] != first["user_code"] and second["expires_in"] == 900


def test_karten16_ec1_github_saying_the_code_ran_out_is_the_same(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    start(admin)
    hub.answer_with = "expired_token"
    moment[0] += 6
    assert poll(admin) == {"status": "expired"}


def test_karten16_ac4_the_tokens_are_kept_encrypted_and_never_shown(admin: TestClient, hub: Hub, moment: list[float], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"):
        shown = sign_in(admin, hub, moment)
    access = next(iter(hub.tokens))
    stored = row()
    assert stored is not None and stored.access.startswith("enc:") and stored.refresh.startswith("enc:")
    with db_session() as db:
        everything = " ".join(str(value) for value in db.execute(text("SELECT * FROM github_logins")).one())
    assert access not in everything and "ghr_refresh" not in everything
    assert access not in str(shown) and access not in admin.get(BASE).text and access not in caplog.text


def test_karten16_ac4_the_sign_in_lasts_six_months_at_most(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    hub.refresh_lifetime = 400 * 86400
    sign_in(admin, hub, moment)
    until = datetime.fromisoformat(admin.get(BASE).json()["until"].replace("Z", "+00:00"))
    began = datetime.fromtimestamp(moment[0], UTC)
    assert 180 <= (until - began).days <= 183
    moment[0] += 184 * 86400
    assert admin.get(BASE).json()["signed_in"] is False and row() is None


def test_karten16_ac4_an_access_token_that_ended_is_renewed_with_the_refresh_token(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    sign_in(admin, hub, moment)
    before = next(iter(hub.tokens))
    until = admin.get(BASE).json()["until"]
    moment[0] += 8 * 3600 - 30
    with db_session() as db:
        used = asyncio.run(github_login.session(db, 1))
    assert used.token != before and used.login == "someone"
    assert list(hub.tokens) == [used.token], "the old one was spent"
    assert admin.get(BASE).json()["until"] == until, "the six months run from the sign-in, not from the renewal"
    # Still good a moment later: nothing is renewed again.
    with db_session() as db:
        again = asyncio.run(github_login.session(db, 1))
    assert again.token == used.token and hub.token_calls == 2


def test_karten16_ac4_everyone_signs_in_with_their_own_account(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    sign_in(admin, hub, moment, hub.person("first", 11))
    create_user(admin, "second", role="admin")
    login(admin, "second", "another-long-password")
    assert admin.get(BASE).json()["signed_in"] is False
    sign_in(admin, hub, moment, hub.person("second-account", 22))
    assert admin.get(BASE).json()["login"] == "second-account"
    login(admin, ADMIN["username"], ADMIN["password"])
    assert admin.get(BASE).json()["login"] == "first"


def test_karten16_ac4_signing_out_deletes_the_tokens(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    sign_in(admin, hub, moment)
    assert row() is not None
    assert admin.delete(BASE, headers=CSRF).status_code == 204
    assert row() is None and admin.get(BASE).json()["signed_in"] is False


def test_karten16_ec2_a_sign_in_that_was_withdrawn_on_github_asks_for_a_new_one(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    sign_in(admin, hub, moment)
    hub.revoke_everything()
    moment[0] += 8 * 3600
    with db_session() as db, pytest.raises(github_login.GithubError) as raised:
        asyncio.run(github_login.session(db, 1))
    assert raised.value.code == "github_login_needed" and raised.value.status == 409
    assert row() is None and admin.get(BASE).json()["signed_in"] is False


def test_karten16_ec8_the_sign_in_goes_with_the_account(admin: TestClient, hub: Hub, moment: list[float]) -> None:
    other = create_user(admin, "second", role="admin")
    login(admin, "second", "another-long-password")
    sign_in(admin, hub, moment)
    login(admin, ADMIN["username"], ADMIN["password"])
    assert row("second") is not None
    assert admin.delete(f"/api/v1/users/{other['id']}", headers=CSRF).status_code == 204
    with db_session() as db:
        assert db.scalar(select(GithubLogin)) is None


@pytest.mark.parametrize(("method", "path"), [("GET", BASE), ("POST", f"{BASE}/login"), ("POST", f"{BASE}/login/poll"), ("DELETE", BASE)])
def test_karten16_only_administrators_sign_in_to_github(admin: TestClient, hub: Hub, method: str, path: str) -> None:
    create_user(admin, "plain")
    login(admin, "plain", "another-long-password")
    assert admin.request(method, path, headers=CSRF).status_code == 403
    admin.cookies.clear()
    assert admin.request(method, path, headers=CSRF).status_code == 401
