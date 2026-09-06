"""The second factor, held against the ways it could lock somebody out.

Two dangers pull in opposite directions here. A factor that is too easy to get
past is decoration; one that is too hard to get past locks the owner out of
their own dashboard. Each test below is one of those.
"""

from __future__ import annotations

import time

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.models import User
from app.services import two_factor

from .conftest import ADMIN, CSRF, create_user, login, setup_admin


def _secret(client: TestClient) -> str:
    started = client.post("/api/v1/auth/two-factor/start", headers=CSRF)
    assert started.status_code == 200, started.text
    return started.json()["secret"]


def _code(secret: str, offset: int = 0) -> str:
    return pyotp.TOTP(secret).at(int(time.time()) + offset * 30)


def _switch_on(client: TestClient) -> tuple[str, list[str]]:
    secret = _secret(client)
    done = client.post("/api/v1/auth/two-factor/confirm", json={"code": _code(secret)}, headers=CSRF)
    assert done.status_code == 200, done.text
    return secret, done.json()["recovery_codes"]


# ---------------------------------------------------------------------------
# Setting it up
# ---------------------------------------------------------------------------


def test_starting_hands_out_a_secret_and_a_qr_code(client: TestClient) -> None:
    setup_admin(client)
    started = client.post("/api/v1/auth/two-factor/start", headers=CSRF).json()
    assert len(started["secret"]) >= 16
    assert started["otpauth_url"].startswith("otpauth://totp/")
    assert started["qr_svg"].startswith("<svg"), "drawn here, not by a foreign service"
    assert "<?xml" not in started["qr_svg"], "it goes into an HTML page"


def test_starting_does_not_switch_anything_on(client: TestClient) -> None:
    """⚠️ A setup somebody walked away from halfway must not lock them out."""
    setup_admin(client)
    _secret(client)
    assert client.get("/api/v1/auth/two-factor").json()["enabled"] is False

    fresh = TestClient(client.app)
    assert fresh.post("/api/v1/auth/login", json=ADMIN).status_code == 200, "still one step"


def test_a_wrong_code_does_not_switch_it_on(client: TestClient) -> None:
    setup_admin(client)
    _secret(client)
    refused = client.post("/api/v1/auth/two-factor/confirm", json={"code": "000000"}, headers=CSRF)
    assert refused.status_code == 400
    assert client.get("/api/v1/auth/two-factor").json()["enabled"] is False


def test_confirming_switches_it_on_and_hands_out_the_codes_once(client: TestClient) -> None:
    setup_admin(client)
    _secret, codes = _switch_on(client)
    assert len(codes) == two_factor.CODE_COUNT
    assert all("-" in code for code in codes)
    state = client.get("/api/v1/auth/two-factor").json()
    assert state["enabled"] is True
    assert state["recovery_codes_left"] == two_factor.CODE_COUNT


def test_a_code_never_counts_twice(client: TestClient) -> None:
    """⚠️ Without this an intercepted code is good for another half minute,
    which is longer than anybody needs to type it in somewhere else."""
    setup_admin(client)
    secret = _secret(client)
    code = _code(secret)
    assert client.post("/api/v1/auth/two-factor/confirm", json={"code": code}, headers=CSRF).status_code == 200
    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert two_factor.check_code(db, person, code) is False, "the same code again"


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------


def test_the_password_alone_no_longer_opens_a_session(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)

    fresh = TestClient(client.app)
    answer = fresh.post("/api/v1/auth/login", json=ADMIN)
    assert answer.status_code == 401
    detail = answer.json()["detail"]
    assert detail["code"] == "second_step"
    assert detail["ticket"]
    assert fresh.get("/api/v1/auth/me").status_code == 401, "and nothing was opened"


def test_the_ticket_alone_opens_nothing(client: TestClient) -> None:
    """⚠️ It is not a session. Its only use is to be exchanged, with a code."""
    setup_admin(client)
    _switch_on(client)
    fresh = TestClient(client.app)
    ticket = fresh.post("/api/v1/auth/login", json=ADMIN).json()["detail"]["ticket"]

    assert fresh.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401
    assert fresh.get("/api/v1/boards").status_code == 401


def test_the_ticket_and_a_code_open_the_session(client: TestClient) -> None:
    setup_admin(client)
    secret, _codes = _switch_on(client)
    fresh = TestClient(client.app)
    ticket = fresh.post("/api/v1/auth/login", json=ADMIN).json()["detail"]["ticket"]

    done = fresh.post("/api/v1/auth/login/second-step", json={"ticket": ticket, "code": _code(secret, 1)}, headers=CSRF)
    assert done.status_code == 200, done.text
    assert fresh.get("/api/v1/auth/me").status_code == 200


def test_a_recovery_code_also_opens_it_and_is_then_spent(client: TestClient) -> None:
    setup_admin(client)
    _secret, codes = _switch_on(client)
    fresh = TestClient(client.app)
    ticket = fresh.post("/api/v1/auth/login", json=ADMIN).json()["detail"]["ticket"]

    done = fresh.post("/api/v1/auth/login/second-step", json={"ticket": ticket, "recovery_code": codes[0]}, headers=CSRF)
    assert done.status_code == 200, done.text
    assert client.get("/api/v1/auth/two-factor").json()["recovery_codes_left"] == two_factor.CODE_COUNT - 1

    again = TestClient(client.app)
    ticket2 = again.post("/api/v1/auth/login", json=ADMIN).json()["detail"]["ticket"]
    refused = again.post("/api/v1/auth/login/second-step", json={"ticket": ticket2, "recovery_code": codes[0]}, headers=CSRF)
    assert refused.status_code == 401, "the same code twice"


def test_a_wrong_code_is_refused_and_counted(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)
    fresh = TestClient(client.app)
    ticket = fresh.post("/api/v1/auth/login", json=ADMIN).json()["detail"]["ticket"]
    refused = fresh.post("/api/v1/auth/login/second-step", json={"ticket": ticket, "code": "000000"}, headers=CSRF)
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "bad_code"


def test_a_made_up_ticket_is_refused(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)
    fresh = TestClient(client.app)
    for bad in ("", "nonsense", "a.b.c"):
        answer = fresh.post("/api/v1/auth/login/second-step", json={"ticket": bad, "code": "123456"}, headers=CSRF)
        assert answer.status_code == 401, bad


def test_a_password_change_kills_a_ticket_in_flight(client: TestClient) -> None:
    """The ticket says "the password was right"; if the password changed, it
    was not right after all."""
    setup_admin(client)
    secret, _codes = _switch_on(client)
    fresh = TestClient(client.app)
    ticket = fresh.post("/api/v1/auth/login", json=ADMIN).json()["detail"]["ticket"]

    time.sleep(0.01)
    changed = client.post("/api/v1/auth/password", json={
        "current_password": ADMIN["password"], "new_password": "a-brand-new-long-one",
    }, headers=CSRF)
    assert changed.status_code in (200, 204), changed.text

    refused = fresh.post("/api/v1/auth/login/second-step", json={"ticket": ticket, "code": _code(secret, 1)}, headers=CSRF)
    assert refused.status_code == 401
    assert refused.json()["detail"]["code"] == "bad_ticket"


# ---------------------------------------------------------------------------
# Switching it off
# ---------------------------------------------------------------------------


def test_switching_it_off_needs_the_password(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)
    refused = client.request("DELETE", "/api/v1/auth/two-factor", json={"password": "wrong"}, headers=CSRF)
    assert refused.status_code == 403
    assert client.get("/api/v1/auth/two-factor").json()["enabled"] is True


def test_switching_it_off_takes_the_secret_and_the_codes_with_it(client: TestClient) -> None:
    """⚠️ Left behind, the old QR code would work again the moment somebody
    switched it back on, along with every photograph of it, and a recovery
    code off a year-old scrap of paper would count again."""
    setup_admin(client)
    secret, codes = _switch_on(client)
    gone = client.request("DELETE", "/api/v1/auth/two-factor", json={"password": ADMIN["password"]}, headers=CSRF)
    assert gone.status_code == 204, gone.text

    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert person.totp_secret == ""
        assert person.totp_last_step == 0, "or the next setup refuses every code for half a minute"
        assert two_factor.codes_left(person) == 0

    new_secret = _secret(client)
    assert new_secret != secret, "and the new one is a different secret"


def test_new_recovery_codes_replace_the_old_ones(client: TestClient) -> None:
    setup_admin(client)
    _secret, codes = _switch_on(client)
    made = client.post("/api/v1/auth/two-factor/recovery-codes", json={"password": ADMIN["password"]}, headers=CSRF)
    assert made.status_code == 200, made.text
    fresh_codes = made.json()["recovery_codes"]
    assert set(fresh_codes) & set(codes) == set()
    assert client.get("/api/v1/auth/two-factor").json()["recovery_codes_left"] == two_factor.CODE_COUNT


# ---------------------------------------------------------------------------
# What the operator demands
# ---------------------------------------------------------------------------


def test_nobody_is_forced_by_default(client: TestClient) -> None:
    """⚠️ nexmail makes this compulsory because a mail client is where every
    "forgot my password" ends up. A dashboard is not, and a wall display has
    nobody to type a code."""
    setup_admin(client)
    assert client.get("/api/v1/auth/two-factor").json()["required_by_operator"] is False


def test_the_operator_can_demand_it(client: TestClient) -> None:
    setup_admin(client)
    with db_session() as db:
        two_factor.set_required(db, True)
    assert client.get("/api/v1/auth/two-factor").json()["required_by_operator"] is True
    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert two_factor.must_set_up(db, person) is True


def test_while_it_is_demanded_nobody_may_switch_theirs_off(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)
    with db_session() as db:
        two_factor.set_required(db, True)
    refused = client.request("DELETE", "/api/v1/auth/two-factor", json={"password": ADMIN["password"]}, headers=CSRF)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "required_by_operator"


def test_a_kiosk_link_is_not_asked_for_a_code(client: TestClient) -> None:
    """⚠️ A wall display has nobody standing at it with a phone. Putting a
    second step in front of it would mean a display that stops working with no
    way to fix it from where it hangs."""
    setup_admin(client)
    _switch_on(client)
    with db_session() as db:
        two_factor.set_required(db, True)
    board = client.post("/api/v1/boards", json={"name": "Hall"}, headers=CSRF).json()
    made = client.post(f"/api/v1/boards/{board['slug']}/kiosk-tokens", json={"name": "Hall"}, headers=CSRF)
    assert made.status_code == 201, made.text

    display = TestClient(client.app)
    door = display.post("/api/v1/kiosk/session", json={"token": made.json()["token"]}, headers=CSRF)
    assert door.status_code == 200, door.text
    assert display.get("/api/v1/kiosk").status_code == 200


def test_an_api_token_is_not_asked_for_a_code(client: TestClient) -> None:
    """It has no sign-in to put a step in front of."""
    setup_admin(client)
    token = client.post("/api/v1/tokens", json={"name": "script"}, headers=CSRF).json()["token"]
    _switch_on(client)
    with db_session() as db:
        two_factor.set_required(db, True)
    fresh = TestClient(client.app)
    assert fresh.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_somebody_elses_account_is_not_touched(client: TestClient) -> None:
    setup_admin(client)
    _switch_on(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    assert kim.get("/api/v1/auth/two-factor").json()["enabled"] is False


@pytest.mark.parametrize("code", ["", "   ", "abcdef", "12345", "1234567"])
def test_nonsense_never_passes(client: TestClient, code: str) -> None:
    setup_admin(client)
    secret = _secret(client)
    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert two_factor.check_code(db, person, code) is False


# ---------------------------------------------------------------------------
# The edges the first round of tests walked past
# ---------------------------------------------------------------------------


def test_the_window_is_narrow(client: TestClient) -> None:
    """⚠️ Tolerance is for a phone whose clock drifts a little, not for a code
    from a quarter of an hour ago. A wide window is the quiet way to turn a
    thirty-second code into a ten-minute one."""
    setup_admin(client)
    secret = _secret(client)
    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert two_factor.check_code(db, person, _code(secret, offset=5)) is False, "five steps ahead"
    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert two_factor.check_code(db, person, _code(secret, offset=-5)) is False, "five steps behind"


def test_the_secret_is_not_readable_in_the_database(client: TestClient) -> None:
    """⚠️ A stored secret is a stored password: anybody holding the file could
    make codes for the account for ever."""
    setup_admin(client)
    secret = _secret(client)
    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert person.totp_secret, "something was kept"
        assert secret not in person.totp_secret
        assert two_factor.read_secret(person) == secret, "and it comes back"


def test_a_demand_is_satisfied_by_having_one(client: TestClient) -> None:
    """Otherwise the person who did as they were told stays at the door."""
    setup_admin(client)
    with db_session() as db:
        two_factor.set_required(db, True)
        person = db.get(User, 1)
        assert person is not None
        assert two_factor.must_set_up(db, person) is True
    _switch_on(client)
    with db_session() as db:
        person = db.get(User, 1)
        assert person is not None
        assert two_factor.must_set_up(db, person) is False


def test_guessing_codes_is_throttled(client: TestClient) -> None:
    """⚠️ Six digits are a million tries, and a machine does that in an hour.
    The first step is counted; the second has to be counted too."""
    setup_admin(client)
    _switch_on(client)
    fresh = TestClient(client.app)
    refused = fresh.post("/api/v1/auth/login", json=ADMIN)
    ticket = refused.json()["detail"]["ticket"]
    codes = {
        fresh.post("/api/v1/auth/login/second-step", json={"ticket": ticket, "code": "000000"}, headers=CSRF).status_code
        for _ in range(30)
    }
    assert 429 in codes


def test_a_session_cookie_is_not_a_ticket(client: TestClient) -> None:
    """The two are signed with different keys, and that already stops it."""
    setup_admin(client)
    _switch_on(client)
    from app.security import create_session_token, read_step_token

    assert read_step_token(create_session_token(1, session_id=1)) is None


def test_only_a_ticket_counts_as_a_ticket(client: TestClient) -> None:
    """⚠️ A signature says who wrote a token, not what it is for. Should
    anything else ever be signed with this key, the sign-in must still refuse
    it, so the ticket says what it is and that word is checked.

    Forged here with the key itself, because that is the only way to ask the
    question the signature cannot answer.
    """
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.security import ALGORITHM, _step_key, read_step_token

    now = datetime.now(UTC)
    for use in ("session", "", "SECOND-STEP", "reset"):
        forged = jwt.encode(
            {"sub": "1", "use": use, "ms": int(now.timestamp() * 1000),
             "exp": int((now + timedelta(minutes=5)).timestamp())},
            _step_key(), algorithm=ALGORITHM,
        )
        assert read_step_token(forged) is None, f"{use!r} is not a ticket"

    honest = jwt.encode(
        {"sub": "1", "use": "second-step", "ms": int(now.timestamp() * 1000),
         "exp": int((now + timedelta(minutes=5)).timestamp())},
        _step_key(), algorithm=ALGORITHM,
    )
    assert read_step_token(honest) is not None, "and the real one still works"
