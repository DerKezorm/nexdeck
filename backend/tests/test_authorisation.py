"""Who may touch what: the checks that decide it, held against the ways round them.

Every test here stands for a hole that was open once. They are written as the
attack, not as the rule, so a rewrite that reopens one fails loudly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.boards import slugify

from .conftest import CSRF, create_user, login, setup_admin


def _board(client: TestClient, name: str, slug: str | None = None) -> dict:
    body: dict[str, object] = {"name": name}
    if slug is not None:
        body["slug"] = slug
    answer = client.post("/api/v1/boards", json=body, headers=CSRF)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _widget(client: TestClient, page_id: int, title: str) -> dict:
    answer = client.post(f"/api/v1/pages/{page_id}/widgets", json={
        "kind": "core.markdown", "title": title, "options": {"text": "private"},
    }, headers=CSRF)
    assert answer.status_code == 201, answer.text
    body = answer.json()
    return body if "id" in body else body["widget"]


def test_a_board_named_after_a_number_does_not_become_that_number(client: TestClient) -> None:
    """A slug of pure digits and a board id are the same address.

    Every widget and page route looks its board up by number. While the slug
    was tried first, a user who called a board "7" was asked about board 7.
    """
    setup_admin(client)
    made = _board(client, "7", slug="7")
    assert not made["slug"].isdigit(), "a slug must never be a bare number"
    assert slugify("42") == "b-42"
    assert slugify("Rack 3") == "rack-3", "digits inside a name are still fine"


def test_a_stranger_cannot_reach_a_widget_through_a_numeric_slug(client: TestClient) -> None:
    """The attack that worked: name a board after the boss's board id, then
    read, rename and delete the widgets on it."""
    setup_admin(client)
    create_user(client, "kim")
    secret = _board(client, "Boss private")
    widget = _widget(client, secret["pages"][0]["id"], "Boss notes")

    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    kim.post("/api/v1/boards", json={"name": "trap", "slug": str(secret["id"])}, headers=CSRF)

    assert kim.get(f"/api/v1/widgets/{widget['id']}/data").status_code == 403
    assert kim.patch(f"/api/v1/widgets/{widget['id']}", json={"title": "mine now"}, headers=CSRF).status_code == 403
    assert kim.delete(f"/api/v1/widgets/{widget['id']}", headers=CSRF).status_code == 403
    assert kim.post(f"/api/v1/widgets/{widget['id']}/refresh", headers=CSRF).status_code == 403

    still = client.get(f"/api/v1/boards/{secret['slug']}").json()
    titles = [w["title"] for page in still["pages"] for w in page["widgets"]]
    assert titles == ["Boss notes"], "the widget is untouched"


def test_a_stranger_cannot_reach_a_page_through_a_numeric_slug(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    secret = _board(client, "Boss private")
    page = secret["pages"][0]

    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    kim.post("/api/v1/boards", json={"name": "trap", "slug": str(secret["id"])}, headers=CSRF)

    assert kim.post(f"/api/v1/pages/{page['id']}/widgets", json={
        "kind": "core.markdown", "title": "mine", "options": {},
    }, headers=CSRF).status_code == 403
    assert kim.delete(f"/api/v1/pages/{page['id']}", headers=CSRF).status_code == 403


# -- the board import: what a member may bring in ------------------------------

ENV_YAML = """
board: {name: harmless}
integrations:
  - name: stolen
    kind: docker
    config: {host: "${NEXDECK_SECRET_KEY}"}
pages: [{name: one, widgets: []}]
"""

PLAIN_YAML = """
board: {name: brought along}
pages:
  - name: one
    widgets:
      - kind: core.markdown
        title: a note
        options: {text: hello}
"""


def test_an_imported_board_cannot_read_the_servers_environment(client: TestClient, monkeypatch) -> None:
    """The ${VAR} expansion belongs to the operator's own files. Over HTTP it
    handed any member the key that signs every session."""
    monkeypatch.setenv("NEXDECK_SECRET_KEY", "the-installation-signing-key")
    setup_admin(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    brought = kim.post("/api/v1/boards/import", json={"yaml_text": ENV_YAML}, headers=CSRF)
    assert brought.status_code == 400
    assert "connection" in brought.json()["detail"]["message"]
    assert all(entry["name"] != "stolen" for entry in kim.get("/api/v1/integrations").json())


def test_an_import_does_not_create_connections_even_for_an_administrator(client: TestClient) -> None:
    """Connections are made in one place, where the form validates them."""
    setup_admin(client)
    brought = client.post("/api/v1/boards/import", json={"yaml_text": ENV_YAML}, headers=CSRF)
    assert brought.status_code == 400


def test_a_board_without_connections_imports_fine(client: TestClient) -> None:
    setup_admin(client)
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    brought = kim.post("/api/v1/boards/import", json={"yaml_text": PLAIN_YAML}, headers=CSRF)
    assert brought.status_code == 201, brought.text
    assert brought.json()["name"] == "brought along"


def test_an_import_cannot_tie_a_widget_to_a_locked_connection(client: TestClient) -> None:
    """The widget routes check admin_only; the import used to walk past it."""
    setup_admin(client)
    made = client.post("/api/v1/integrations", json={
        "kind": "docker", "name": "Locked engine", "config": {"host": "tcp://127.0.0.1:2375"},
        "enabled": True, "demo": True, "admin_only": True,
    }, headers=CSRF)
    assert made.status_code in (200, 201), made.text
    create_user(client, "kim")
    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")

    yaml_text = """
board: {name: sneaky}
integrations: [{name: Locked engine, kind: docker}]
pages:
  - name: one
    widgets: [{kind: docker.containers, title: theirs, integration: Locked engine}]
"""
    brought = kim.post("/api/v1/boards/import", json={"yaml_text": yaml_text}, headers=CSRF)
    assert brought.status_code == 400
    assert "reserved" in brought.json()["detail"]["message"]
    # The administrator may, because the widget form would let them too.
    assert client.post("/api/v1/boards/import", json={"yaml_text": yaml_text}, headers=CSRF).status_code == 201


# -- uploaded files ------------------------------------------------------------

import pytest  # noqa: E402

from app.routers.assets import unsafe_svg  # noqa: E402

PAYLOADS = [
    (b"<svg><script>alert(1)</script></svg>", "a plain script"),
    (b'<svg><animate onbegin="alert(1)" attributeName="x"/></svg>', "a handler on an animation"),
    (b'<svg onload = "alert(1)"></svg>', "a handler with spaces around the equals sign"),
    (b'<svg><foreignObject><body onmouseover="alert(1)"/></foreignObject></svg>', "foreign content"),
    (b'<svg><a href="javascript:alert(1)">x</a></svg>', "a javascript address"),
    (b'<svg><set onbegin="alert(1)"/></svg>', "a handler on a set element"),
    (b'<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', "an entity declaration"),
    (b'<svg><iframe src="https://evil.example.com"></iframe></svg>', "an embedded page"),
    # No handler and no literal javascript: in this one. An animation that
    # rewrites an attribute is its own way in, so it needs its own pattern.
    (b'<svg><animate attributeName="xlink:href" values="data:text/html,x"/></svg>', "an animation that rewrites a link"),
]


@pytest.mark.parametrize(("payload", "what"), PAYLOADS, ids=[what for _, what in PAYLOADS])
def test_an_svg_that_can_run_is_refused(payload: bytes, what: str) -> None:
    """The old check named three strings; five of these walked past it."""
    assert unsafe_svg(payload), what


def test_a_plain_drawing_is_accepted() -> None:
    assert unsafe_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10" fill="#22d3ee"/></svg>') == ""


def test_an_uploaded_file_is_served_in_a_sandbox(client: TestClient) -> None:
    """Even a payload that got past the check must not run as part of nexdeck."""
    setup_admin(client)
    drawing = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'
    made = client.post("/api/v1/assets", files={"file": ("bg.svg", drawing, "image/svg+xml")}, headers=CSRF)
    assert made.status_code == 201, made.text
    asset = made.json()

    answer = client.get(f"/api/v1/assets/{asset['id']}/{asset['filename']}")
    assert answer.status_code == 200
    assert "sandbox" in answer.headers["content-security-policy"]
    assert answer.headers["x-content-type-options"] == "nosniff"


def test_every_answer_says_not_to_guess_the_type(client: TestClient) -> None:
    """Including the ones under /api/, which the middleware used to skip."""
    setup_admin(client)
    for path in ("/api/v1/auth/me", "/api/v1/boards"):
        assert client.get(path).headers.get("x-content-type-options") == "nosniff", path


def test_an_svg_with_a_handler_never_reaches_the_disk(client: TestClient) -> None:
    setup_admin(client)
    answer = client.post(
        "/api/v1/assets",
        files={"file": ("evil.svg", b'<svg><animate onbegin="alert(1)"/></svg>', "image/svg+xml")},
        headers=CSRF,
    )
    assert answer.status_code == 400
    assert answer.json()["detail"]["code"] == "bad_svg"
    assert client.get("/api/v1/assets").json() == []


# -- guessing a password -------------------------------------------------------


def test_guessing_one_account_is_capped_however_many_addresses_it_comes_from(client: TestClient) -> None:
    """The address is whatever a proxy header says. The account name is not."""
    from app.services import login_guard

    login_guard.reset()
    setup_admin(client)
    for attempt in range(login_guard.MAX_PER_ACCOUNT):
        login_guard.failed(f"203.0.113.{attempt}", "admin")
    answer = client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse-battery"})
    assert answer.status_code == 429, "a fresh address must not buy another ten guesses"
    login_guard.reset()


def test_signing_in_does_not_wipe_the_slate_for_a_different_account(client: TestClient) -> None:
    """A guesser with one account of their own used to reset the counter.

    The address bucket has to be the one that decides here, or the test would
    pass on the account bucket alone and never see the hole.
    """
    from app.services import login_guard

    login_guard.reset()
    setup_admin(client)
    create_user(client, "kim")
    # Full on the address, spread over account names so no account is capped.
    for attempt in range(login_guard.MAX_PER_ADDRESS):
        login_guard.failed("testclient", f"ghost{attempt}")

    kim = TestClient(client.app)
    # Even kim's own correct password is refused while the address is hot.
    assert kim.post("/api/v1/auth/login", json={"username": "kim", "password": "another-long-password"}).status_code == 429
    login_guard.succeeded("testclient", "kim")
    answer = kim.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-again-entirely"})
    assert answer.status_code == 429, "a success must not clear the address it came from"
    login_guard.reset()


def test_a_good_sign_in_clears_that_account(client: TestClient) -> None:
    from app.services import login_guard

    login_guard.reset()
    setup_admin(client)
    for _ in range(login_guard.MAX_PER_ACCOUNT - 1):
        login_guard.failed("203.0.113.5", "admin")
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse-battery"}).status_code == 200
    for _ in range(login_guard.MAX_PER_ACCOUNT - 1):
        login_guard.failed("203.0.113.5", "admin")
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse-battery"}).status_code == 200
    login_guard.reset()


def test_the_guard_does_not_grow_a_key_for_every_address_asked_about() -> None:
    from app.services import login_guard

    login_guard.reset()
    for number in range(500):
        login_guard.check(f"198.51.100.{number % 256}", "nobody")
    assert login_guard._failures == {}, "asking is not failing"


def test_a_numeric_slug_that_is_already_in_the_database_reaches_nothing(client: TestClient) -> None:
    """The two layers are separate, and this one is the one that counts.

    ``slugify`` stops a new board from being called "2", but an installation
    that ran the older code may already have one, and renaming it is not
    something an upgrade may do behind the operator's back. So the lookup
    itself must be safe: a widget's board is fetched by number, never by name.
    """
    from sqlalchemy import select

    from app.db import db_session
    from app.models import Board

    setup_admin(client)
    create_user(client, "kim")
    secret = _board(client, "Boss private")
    widget = _widget(client, secret["pages"][0]["id"], "Boss notes")

    kim = TestClient(client.app)
    login(kim, "kim", "another-long-password")
    trap = kim.post("/api/v1/boards", json={"name": "trap"}, headers=CSRF).json()
    # Straight into the database, the way an older installation would have it.
    with db_session() as db:
        row = db.scalar(select(Board).where(Board.id == trap["id"]))
        row.slug = str(secret["id"])

    assert kim.get(f"/api/v1/widgets/{widget['id']}/data").status_code == 403
    assert kim.delete(f"/api/v1/widgets/{widget['id']}", headers=CSRF).status_code == 403
    assert kim.get(f"/api/v1/boards/{secret['id']}").status_code in (200, 403), "the address by number still resolves somewhere"


def test_an_untrusted_import_never_looks_at_the_environment(monkeypatch) -> None:
    """The refusal above happens first, so this pins the rule underneath it:
    the expansion belongs to a file on the server, never to a request."""
    import os

    from app.db import db_session
    from app.services.boards import ImportError_, import_board

    def forbidden(*args: object, **kwargs: object) -> str:
        raise AssertionError("an untrusted import must not read the environment")

    monkeypatch.setattr(os.environ, "get", forbidden)
    with db_session() as db, pytest.raises(ImportError_):
        import_board(db, ENV_YAML, owner_id=None, trusted=False, allow_locked=False)
